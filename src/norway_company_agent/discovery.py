from __future__ import annotations

import dataclasses
import enum
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable

from .website import normalize_homepage


BLOCKED_DISCOVERY_HOSTS = {
    "proff.no", "purehelp.no", "1881.no", "gulesider.no", "firmalisten.no", "companywall.no",
    "firmadatabasen.no", "sokfirma.no", "yra.no", "northdata.com", "nor47business.com",
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
}
GENERIC_NAME_TOKENS = {
    "as", "asa", "ans", "da", "enk", "iks", "sa", "sam", "sti", "stiftelsen",
    "nuf", "ab", "b", "v", "limited", "ltd", "inc", "plc", "the", "og", "and",
    "company", "norge", "norway", "gruppen", "group", "hold", "holding",
    "drift", "eiendom", "investering", "invest", "management", "consulting",
    "service", "partner", "nordic",
}
GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "online.no", "hotmail.com", "hotmail.no",
    "outlook.com", "yahoo.com", "yahoo.no", "live.com", "live.no", "telenor.no", "icloud.com",
}

# Maximum candidate limits per entity to prevent budget exhaustion
MAX_DOMAIN_CANDIDATES_PER_COMPANY = 8
MAX_TOTAL_CANDIDATES_PER_COMPANY = 12


class CandidateRejectionReason(str, enum.Enum):
    WRONG_ORGNR = "wrong_orgnr"
    WRONG_DOMAIN = "wrong_domain"
    PARENT_ENTITY = "parent_entity"
    SUBSIDIARY_ENTITY = "subsidiary_entity"
    PARKED_DOMAIN = "parked_domain"
    GENERIC_AGGREGATOR = "generic_aggregator"
    UNRELATED_COMPANY = "unrelated_company"
    NO_IDENTITY_EVIDENCE = "no_identity_evidence"
    BLOCKED = "blocked"
    DEAD_DOMAIN = "dead_domain"
    INVALID_URL = "invalid_url"
    UNFETCHED_CAPPED = "unfetched_capped"
    UNFETCHED_EARLY_TERMINATED = "unfetched_early_terminated"
    PREFILTER_BLOCKED = "prefilter_blocked"


@dataclass
class CandidateSource:
    url: str
    source_type: str  # "website", "careers", "jobs", "activity", "news", "social", "other"
    discovery_tier: str  # "tier1_deterministic_domain", "tier2_brreg_relationship", "tier2_email_domain", "tier3_public_search", "crawled_link"
    discovery_reason: str
    rank: int = 1
    # Identity & Verification evidence (strictly separated from discovery)
    identity_evidence: dict[str, Any] = field(default_factory=dict)
    verification_status: str = "unverified"  # "unverified", "plausible", "verified", "rejected"
    identity_score: float = 0.0
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def normalize_candidate_url(raw_url: str | None) -> str | None:
    """Canonicalize candidate URL to prevent duplicate candidates."""
    normalized = normalize_homepage(raw_url)
    if not normalized:
        return None
    parsed = urllib.parse.urlparse(normalized)
    scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urllib.parse.urlunparse((scheme, hostname, path, "", "", ""))


def classify_source_type_from_url(url: str) -> str:
    """Simple, deterministic classification of candidate source type."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()

    if any(s in host for s in ("linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "tiktok.com")):
        return "social"
    if any(k in path for k in ("/karriere", "/karrierer", "/career", "/careers", "/jobb", "/stillinger", "/ledige-stillinger", "/work-with-us")):
        return "careers"
    if any(k in path for k in ("/job/", "/stilling/", "/stillinger/", "/jobs/", "/vacancies/")):
        return "jobs"
    if any(k in path for k in ("/nyheter", "/news", "/aktuelt", "/presse", "/press", "/artikler", "/blogg", "/blog")):
        return "news"
    return "website"


def calculate_discovery_opportunity(profile: dict[str, Any]) -> float:
    """Calculate expected evidence discovery opportunity score (0.0 - 1.0)."""
    legal_form = str(profile.get("legal_form") or "").upper()
    industry_code = str(profile.get("industry_code") or "")
    employees = int(profile.get("employees") or 0)
    name = str(profile.get("name") or "")

    # Inactive or dissolved entities: immediate minimum opportunity
    if bool(profile.get("bankrupt")) or bool(profile.get("liquidating")):
        return 0.05

    # Passive entities: holding companies, real estate shells, housing cooperatives, or 0-employee non-public entities
    is_passive_holding = (
        legal_form in {"ESEK", "BRL"}
        or industry_code.startswith(("64.2", "64.3", "68.201", "97.", "68.200", "00.000"))
        or (employees == 0 and not bool(profile.get("website")) and any(w in name.lower() for w in ("holding", "invest", "eiendom", "utleie")))
    )
    if is_passive_holding:
        return 0.15

    reg_val = profile.get("evidence", {}).get("registry", {}).get("value") or {}
    email = str(reg_val.get("epostadresse") or reg_val.get("epost") or "").casefold()
    email_domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    is_custom_domain = bool(email_domain and email_domain not in GENERIC_EMAIL_DOMAINS)

    # Public-facing / customer-serving industry divisions
    is_public_facing = bool(industry_code.startswith((
        "47.", "55.", "56.", "62.", "63.", "70.", "71.", "85.", "86.", "93.", "95.", "96.", "43."
    )))

    if employees >= 20:
        prob = 0.65
    elif employees >= 10:
        prob = 0.55
    elif employees >= 5:
        prob = 0.45
    elif employees >= 1:
        prob = 0.35
    else:
        # Zero employees / holding / dormant
        if not is_custom_domain:
            return 0.15
        prob = 0.20

    if is_public_facing:
        prob += 0.15
    if is_custom_domain:
        prob += 0.25

    name_tokens = [t for t in _tokens(name) if t not in GENERIC_NAME_TOKENS]
    if len(name_tokens) >= 2:
        prob += 0.10

    return min(1.0, round(prob, 2))


def _tokens(value: Any) -> list[str]:
    text = str(value or "").translate(str.maketrans({"ø": "o", "å": "a", "æ": "ae", "Ø": "O", "Å": "A", "Æ": "AE"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return [token for token in re.findall(r"[a-z0-9]+", text) if len(token) > 1]


def generate_deterministic_domain_candidates(profile: dict[str, Any], *, max_candidates: int = MAX_DOMAIN_CANDIDATES_PER_COMPANY) -> list[str]:
    """Generate high-confidence candidate domain URLs derived from clean legal name tokens.
    
    Constraint: Conservative generation. No speculative arbitrary industry tokens.
    Supports clean token combinations (.no, .com, -as.no).
    """
    name = " ".join(str(profile.get("name") or "").split())
    if not name:
        return []

    tokens = [t for t in _tokens(name) if t not in GENERIC_NAME_TOKENS]
    if not tokens:
        return []

    raw_candidates: list[str] = []
    if len(tokens) == 1:
        t = tokens[0]
        if len(t) >= 3:
            raw_candidates.extend([
                f"https://{t}.no/",
                f"https://{t}-as.no/",
                f"https://{t}.com/",
            ])
    elif len(tokens) == 2:
        t1, t2 = tokens[0], tokens[1]
        raw_candidates.extend([
            f"https://{t1}{t2}.no/",
            f"https://{t1}-{t2}.no/",
            f"https://{t1}{t2}-as.no/",
            f"https://{t1}-{t2}-as.no/",
            f"https://{t1}{t2}.com/",
            f"https://{t1}-{t2}.com/",
        ])
    elif len(tokens) == 3:
        t1, t2, t3 = tokens[0], tokens[1], tokens[2]
        raw_candidates.extend([
            f"https://{t1}{t2}{t3}.no/",
            f"https://{t1}-{t2}-{t3}.no/",
            f"https://{t1}{t2}.no/",
            f"https://{t1}-{t2}.no/",
            f"https://{t1}{t2}{t3}.com/",
        ])
    elif len(tokens) >= 4:
        t1, t2, t3, t4 = tokens[0], tokens[1], tokens[2], tokens[3]
        raw_candidates.extend([
            f"https://{t1}{t2}{t3}{t4}.no/",
            f"https://{t1}-{t2}-{t3}-{t4}.no/",
            f"https://{t1}{t2}{t3}.no/",
            f"https://{t1}-{t2}-{t3}.no/",
            f"https://{t1}{t2}.no/",
        ])

    deduped: list[str] = []
    seen: set[str] = set()
    for cand in raw_candidates:
        norm = normalize_candidate_url(cand)
        if norm and norm not in seen:
            seen.add(norm)
            deduped.append(norm)
            if len(deduped) >= max_candidates:
                break
    return deduped


def generate_brreg_relationship_candidates(profile: dict[str, Any], *, max_candidates: int = 4) -> list[CandidateSource]:
    """Generate candidate domains derived strictly from Brreg relationships (subunits, email domains).
    
    Constraint: These remain candidates, NOT proof. Must pass V6 identity gate.
    """
    candidates: list[CandidateSource] = []
    seen: set[str] = set()

    # 1. Distinctive registry email domain
    reg_val = profile.get("evidence", {}).get("registry", {}).get("value") or {}
    email = str(reg_val.get("epostadresse") or reg_val.get("epost") or "").strip().casefold()
    if email and "@" in email:
        email_domain = email.rsplit("@", 1)[-1].removeprefix("www.")
        if email_domain not in GENERIC_EMAIL_DOMAINS and "." in email_domain and len(email_domain) >= 4:
            email_url = f"https://{email_domain}/"
            norm = normalize_candidate_url(email_url)
            if norm and norm not in seen:
                seen.add(norm)
                candidates.append(CandidateSource(
                    url=norm,
                    source_type="website",
                    discovery_tier="tier2_email_domain",
                    discovery_reason=f"Registry contact email domain ({email})",
                    rank=1,
                ))

    # 2. Operating subunits (underenheter)
    locations_val = (profile.get("evidence", {}).get("locations", {}).get("value") or {}).get("locations") or []
    for loc in locations_val[:3]:
        sub_name = str(loc.get("name") or "").strip()
        sub_tokens = [t for t in _tokens(sub_name) if t not in GENERIC_NAME_TOKENS]
        if sub_tokens and len(sub_tokens) >= 2:
            s1, s2 = sub_tokens[0], sub_tokens[1]
            for cand_pattern in (f"https://{s1}{s2}.no/", f"https://{s1}-{s2}.no/"):
                norm = normalize_candidate_url(cand_pattern)
                if norm and norm not in seen:
                    seen.add(norm)
                    candidates.append(CandidateSource(
                        url=norm,
                        source_type="website",
                        discovery_tier="tier2_brreg_relationship",
                        discovery_reason=f"Operating subunit registered name: '{sub_name}'",
                        rank=2,
                    ))
                    if len(candidates) >= max_candidates:
                        return candidates

    return candidates[:max_candidates]


def generate_company_candidate_sources(profile: dict[str, Any], *, max_candidates: int = MAX_TOTAL_CANDIDATES_PER_COMPANY) -> list[CandidateSource]:
    """Orchestrate prioritized candidate generation across Tier 1, Tier 2, and existing seeds.
    
    All candidates are deduplicated and bounded by max_candidates.
    """
    candidates: list[CandidateSource] = []
    seen: set[str] = set()

    # 0. Official registry website seed (if available in profile)
    seed_web = profile.get("website")
    if seed_web:
        norm_seed = normalize_candidate_url(seed_web)
        if norm_seed:
            seen.add(norm_seed)
            candidates.append(CandidateSource(
                url=norm_seed,
                source_type="website",
                discovery_tier="tier0_brreg_seed",
                discovery_reason="Authority filing in Brreg Enhetsregisteret",
                rank=1,
            ))

    # 1. Tier 2: Email domain & Subunit candidates (high specificity)
    rel_cands = generate_brreg_relationship_candidates(profile, max_candidates=4)
    for c in rel_cands:
        if c.url not in seen:
            seen.add(c.url)
            candidates.append(c)

    # 2. Tier 1: Deterministic Name Domain Candidates
    domain_cands = generate_deterministic_domain_candidates(profile, max_candidates=MAX_DOMAIN_CANDIDATES_PER_COMPANY)
    for dom_url in domain_cands:
        if dom_url not in seen:
            seen.add(dom_url)
            candidates.append(CandidateSource(
                url=dom_url,
                source_type="website",
                discovery_tier="tier1_deterministic_domain",
                discovery_reason="Deterministic legal name token permutation",
                rank=len(candidates) + 1,
            ))
        if len(candidates) >= max_candidates:
            break

    return candidates[:max_candidates]


def assess_candidate_funnel(
    profile: dict[str, Any],
    candidates: list[CandidateSource],
    fetch_fn: Callable[[str], tuple[dict[str, Any], dict[str, Any]]],
    identity_gate_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    *,
    max_fetches: int = 4,
) -> dict[str, Any]:
    """Execute candidate funnel tracking every candidate through:
    GENERATED -> FETCHED -> PLAUSIBLE -> VERIFIED (or REJECTED with explicit reason).
    
    Maintains zero wrong-company tolerance. Rejections are categorized.
    """
    funnel_metrics = {
        "generated": len(candidates),
        "not_fetched": 0,
        "fetched": 0,
        "plausible": 0,
        "verified": 0,
        "rejected_after_fetch": 0,
        "rejected": 0,  # total non-verified candidates = not_fetched + rejected_after_fetch
        "rejection_reasons": {r.value: 0 for r in CandidateRejectionReason},
        "requests": 0,
        "bytes": 0,
    }

    verified_sources: list[CandidateSource] = []
    fetches_made = 0
    verified_found = False

    for cand in candidates:
        # If an authoritative verified official website has already been confirmed,
        # terminate subsequent candidate fetches early to conserve request budget
        if verified_found:
            cand.verification_status = "rejected"
            cand.rejection_reason = CandidateRejectionReason.UNFETCHED_EARLY_TERMINATED.value
            funnel_metrics["not_fetched"] += 1
            funnel_metrics["rejected"] += 1
            funnel_metrics["rejection_reasons"][CandidateRejectionReason.UNFETCHED_EARLY_TERMINATED.value] += 1
            continue

        # Pre-filter checks
        parsed = urllib.parse.urlparse(cand.url)
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        if any(host == b or host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS):
            cand.verification_status = "rejected"
            cand.rejection_reason = CandidateRejectionReason.GENERIC_AGGREGATOR.value
            funnel_metrics["not_fetched"] += 1
            funnel_metrics["rejected"] += 1
            funnel_metrics["rejection_reasons"][CandidateRejectionReason.GENERIC_AGGREGATOR.value] += 1
            continue

        if fetches_made >= max_fetches:
            cand.verification_status = "rejected"
            cand.rejection_reason = CandidateRejectionReason.UNFETCHED_CAPPED.value
            funnel_metrics["not_fetched"] += 1
            funnel_metrics["rejected"] += 1
            funnel_metrics["rejection_reasons"][CandidateRejectionReason.UNFETCHED_CAPPED.value] += 1
            continue

        # Fetch candidate
        fetches_made += 1
        funnel_metrics["fetched"] += 1
        web_record, web_metrics = fetch_fn(cand.url)
        funnel_metrics["requests"] += web_metrics.get("requests", 1)
        funnel_metrics["bytes"] += web_metrics.get("bytes", 0)

        status = web_record.get("status")
        if status in ("source_error", "not_found"):
            cand.verification_status = "rejected"
            cand.rejection_reason = CandidateRejectionReason.DEAD_DOMAIN.value
            funnel_metrics["rejected_after_fetch"] += 1
            funnel_metrics["rejected"] += 1
            funnel_metrics["rejection_reasons"][CandidateRejectionReason.DEAD_DOMAIN.value] += 1
            continue
        elif status in ("blocked", "blocked_robots", "blocked_policy"):
            cand.verification_status = "rejected"
            cand.rejection_reason = CandidateRejectionReason.BLOCKED.value
            funnel_metrics["rejected_after_fetch"] += 1
            funnel_metrics["rejected"] += 1
            funnel_metrics["rejection_reasons"][CandidateRejectionReason.BLOCKED.value] += 1
            continue

        # Candidate fetched successfully -> apply V6 Identity Gate
        gated = identity_gate_fn(profile, web_record)
        assessment = gated.get("assessment") or {}
        score = float(assessment.get("score") or 0.0)
        cand.identity_score = score
        cand.identity_evidence = {
            "score": score,
            "method": assessment.get("method"),
            "matched_tokens": assessment.get("matched_tokens"),
            "exact_orgnr": assessment.get("exact_orgnr"),
            "is_parked": assessment.get("is_parked"),
        }

        # Plausibility threshold
        if score >= 0.50:
            funnel_metrics["plausible"] += 1

        is_publishable = bool(assessment.get("publishable"))
        if is_publishable:
            cand.verification_status = "verified"
            funnel_metrics["verified"] += 1
            verified_sources.append(cand)
            verified_found = True
        else:
            cand.verification_status = "rejected"
            funnel_metrics["rejected_after_fetch"] += 1
            funnel_metrics["rejected"] += 1
            # Determine specific rejection category
            if assessment.get("is_parked"):
                cand.rejection_reason = CandidateRejectionReason.PARKED_DOMAIN.value
            elif assessment.get("is_wrong_org"):
                cand.rejection_reason = CandidateRejectionReason.WRONG_ORGNR.value
            elif assessment.get("is_subsidiary"):
                cand.rejection_reason = CandidateRejectionReason.SUBSIDIARY_ENTITY.value
            elif assessment.get("is_parent"):
                cand.rejection_reason = CandidateRejectionReason.PARENT_ENTITY.value
            elif score > 0.3:
                cand.rejection_reason = CandidateRejectionReason.UNRELATED_COMPANY.value
            else:
                cand.rejection_reason = CandidateRejectionReason.NO_IDENTITY_EVIDENCE.value
            funnel_metrics["rejection_reasons"][cand.rejection_reason] += 1

    verified_yield = (
        round(funnel_metrics["verified"] / funnel_metrics["fetched"], 3)
        if funnel_metrics["fetched"] > 0 else 0.0
    )
    candidate_efficiency = (
        round(funnel_metrics["verified"] / funnel_metrics["requests"], 3)
        if funnel_metrics["requests"] > 0 else 0.0
    )

    return {
        "funnel_metrics": funnel_metrics,
        "verified_yield": verified_yield,
        "candidate_efficiency": candidate_efficiency,
        "verified_sources": [s.to_dict() for s in verified_sources],
        "all_candidates": [c.to_dict() for c in candidates],
    }


def build_company_search_query(profile: dict[str, Any]) -> str:
    name = " ".join(str(profile.get("name") or "").split())
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    municipality = " ".join(str(profile.get("municipality") or "").split())
    if not name or not org:
        raise ValueError("Company discovery requires a legal name and organisation number")
    location = f" {municipality}" if municipality else ""
    return f'"{name}" {org}{location}'


def build_flexible_company_search_queries(profile: dict[str, Any]) -> list[str]:
    name = " ".join(str(profile.get("name") or "").split())
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    municipality = " ".join(str(profile.get("municipality") or "").split())

    clean_name = name
    for suffix in [" AS", " ASA", " ENK", " DA", " ANS", " NUF", " SA", " BRL", " ESEK"]:
        if clean_name.endswith(suffix):
            clean_name = clean_name[:-len(suffix)].strip()

    queries = [
        f'"{name}" {org}',
        f'"{clean_name}" {municipality}' if municipality else f'"{clean_name}" Norge',
        f'"{name}" {municipality}'.strip() if municipality else f'"{name}" Norge',
    ]

    registry_value = profile.get("evidence", {}).get("registry", {}).get("value") or {}
    registry_email = str(
        registry_value.get("epostadresse")
        or registry_value.get("epost")
        or ""
    ).strip().casefold()
    email_domain = registry_email.rsplit("@", 1)[-1] if "@" in registry_email else ""
    email_domain = email_domain.removeprefix("www.")

    if email_domain and "." in email_domain and email_domain not in GENERIC_EMAIL_DOMAINS:
        queries.append(f'"{clean_name}" {email_domain}')

    # Subunit & Brand Bridge Queries
    locations_val = (profile.get("evidence", {}).get("locations", {}).get("value") or {}).get("locations") or []
    for loc in locations_val[:3]:
        sub_name = str(loc.get("name") or "").strip()
        sub_clean = sub_name
        for s in [" AS", " ASA", " A/S", " ENK", " DA", " ANS", " NUF", " SA"]:
            if sub_clean.endswith(s):
                sub_clean = sub_clean[:-len(s)].strip()
        if sub_clean and sub_clean.casefold() != clean_name.casefold() and len(sub_clean) >= 3:
            addr = loc.get("address") or {}
            street = (addr.get("adresse") or [""])[0] if isinstance(addr.get("adresse"), list) else str(addr.get("adresse") or "")
            city = str(addr.get("poststed") or addr.get("kommune") or municipality or "")
            if street:
                queries.append(f'"{sub_clean}" {street}')
            elif city:
                queries.append(f'"{sub_clean}" {city}')
            else:
                queries.append(f'"{sub_clean}" Norge')

    return list(dict.fromkeys(queries))


def parse_brave_web_results(payload: dict[str, Any], *, query: str) -> list[dict[str, Any]]:
    results = (payload.get("web") or {}).get("results") or []
    parsed = []
    for rank, result in enumerate(results, start=1):
        if not isinstance(result, dict) or not result.get("url"):
            continue
        parsed.append({
            "url": result.get("url"),
            "title": result.get("title") or "",
            "snippet": result.get("description") or "",
            "rank": rank,
            "provider": "brave_search_api",
            "query": query,
        })
    return parsed


def score_search_candidate(profile: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_homepage(result.get("url"))
    if not normalized:
        return {"status": "rejected", "score": 0.0, "publishable_candidate": False, "reasons": ["invalid HTTP(S) candidate URL"]}
    host = (urllib.parse.urlparse(normalized).hostname or "").casefold().removeprefix("www.")
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_DISCOVERY_HOSTS):
        return {"status": "rejected", "score": 0.0, "publishable_candidate": False, "url": normalized, "host": host, "reasons": ["directory, aggregator, or social host is not a company website candidate"]}

    name_tokens = [token for token in _tokens(profile.get("name")) if token not in GENERIC_NAME_TOKENS]
    title_tokens = _tokens(result.get("title"))
    snippet_tokens = _tokens(result.get("snippet"))
    evidence_tokens = set(title_tokens + snippet_tokens + _tokens(host))
    host_tokens = _tokens(host)
    host_compact = "".join(host_tokens)
    name_compact = "".join(name_tokens)
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    evidence_digits = re.sub(r"\D", "", f"{result.get('title', '')} {result.get('snippet', '')}")
    municipality_tokens = set(_tokens(profile.get("municipality")))

    org_match = bool(org and org in evidence_digits)
    all_name_tokens = bool(name_tokens and set(name_tokens).issubset(evidence_tokens))
    all_name_tokens_in_title = bool(name_tokens and set(name_tokens).issubset(set(title_tokens)))
    
    name_in_host = bool(
        (name_compact and name_compact in host_compact)
        or (name_tokens and all(token in host_tokens or token in host_compact for token in name_tokens))
    )

    registry_value = profile.get("evidence", {}).get("registry", {}).get("value") or {}
    registry_email = str(
        registry_value.get("epostadresse")
        or registry_value.get("epost")
        or ""
    ).strip().casefold()

    email_domain = registry_email.rsplit("@", 1)[-1] if "@" in registry_email else ""
    email_domain = email_domain.removeprefix("www.")
    candidate_domain = host.removeprefix("www.")
    email_domain_match = bool(
        email_domain
        and candidate_domain
        and (
            candidate_domain == email_domain
            or candidate_domain.endswith("." + email_domain)
        )
    )

    municipality_match = bool(municipality_tokens and municipality_tokens <= set(snippet_tokens))
    
    locations_val = (profile.get("evidence", {}).get("locations", {}).get("value") or {}).get("locations") or []
    subunit_name_in_host = False
    for loc in locations_val:
        sub_n = str(loc.get("name") or "")
        sub_toks = [t for t in _tokens(sub_n) if t not in GENERIC_NAME_TOKENS]
        if sub_toks and len(sub_toks) >= 2 and all(t in host_tokens or t in host_compact for t in sub_toks):
            subunit_name_in_host = True
            break

    score = 0.0
    reasons = []
    if org_match:
        score += 0.75
        reasons.append("exact organisation number appears in result evidence")
    if all_name_tokens_in_title:
        score += 0.45
        reasons.append("all distinctive legal-name tokens appear in the result title")
    elif all_name_tokens:
        score += 0.25
        reasons.append("all distinctive legal-name tokens appear across result evidence")
    if name_in_host:
        score += 0.3
        reasons.append("normalized legal name appears in candidate hostname")
    if subunit_name_in_host:
        score += 0.4
        reasons.append("registered subunit name appears in candidate hostname")
    if email_domain_match:
        score += 0.35
        reasons.append("candidate hostname matches the registry email domain")
    if municipality_match:
        score += 0.1
        reasons.append("registry municipality appears in result snippet")
    score = min(score, 1.0)

    publishable_candidate = (
        score >= 0.75
        and (name_in_host or subunit_name_in_host or email_domain_match)
        and (org_match or all_name_tokens_in_title or (name_in_host and len(name_tokens) >= 2) or subunit_name_in_host)
    )
    return {
        "status": "accepted_for_crawl" if publishable_candidate else "review" if score >= 0.6 else "rejected",
        "score": score,
        "publishable_candidate": publishable_candidate,
        "url": normalized,
        "host": host,
        "name_in_host": name_in_host,
        "email_domain": email_domain or None,
        "email_domain_match": email_domain_match,
        "rank": result.get("rank"),
        "provider": result.get("provider"),
        "query": result.get("query"),
        "reasons": reasons or ["insufficient exact-entity evidence"],
        "method": "deterministic_search_candidate_identity_v1",
    }


def choose_search_candidate(profile: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    assessed = [score_search_candidate(profile, result) for result in results]
    assessed.sort(key=lambda item: (-item.get("score", 0.0), item.get("rank") or 10_000, item.get("url") or ""))
    accepted = [item for item in assessed if item.get("publishable_candidate")]
    return {
        "selected": accepted[0] if accepted else None,
        "candidates": assessed,
        "abstained": not accepted,
        "policy": "A search result is only a crawl candidate. Publication still requires fetched-page exact-entity verification.",
    }
