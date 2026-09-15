from __future__ import annotations

import re
import unicodedata
import urllib.parse
from typing import Any

from .website import normalize_homepage


BLOCKED_DISCOVERY_HOSTS = {
    "proff.no", "purehelp.no", "1881.no", "gulesider.no", "firmalisten.no", "companywall.no",
    "firmadatabasen.no", "sokfirma.no", "yra.no", "northdata.com", "nor47business.com",
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
}
GENERIC_NAME_TOKENS = {"as", "asa", "ans", "da", "enk", "sa", "nuf", "company", "norge", "norway", "gruppen", "group"}


def calculate_discovery_opportunity(profile: dict[str, Any]) -> float:
    """Calculate expected evidence discovery opportunity score (0.0 - 1.0).
    
    Prioritizes active operating entities with distinctive names, custom domains, 
    registered employees, or active locations, while abstaining on holding,
    shell, bankrupt/liquidating, or purely personal entities with zero public digital signals.
    """
    legal_form = str(profile.get("legal_form") or "").upper()
    industry_code = str(profile.get("industry_code") or "")
    employees = int(profile.get("employees") or 0)
    name = str(profile.get("name") or "")

    # Inactive or dissolved entities: immediate minimum opportunity
    if bool(profile.get("bankrupt")) or bool(profile.get("liquidating")):
        return 0.05

    # Passive entities: holding companies, real estate shells, housing cooperatives
    if legal_form in {"ESEK", "BRL"} or industry_code.startswith(("64.2", "64.3", "68.201", "97.")):
        return 0.15

    reg_val = profile.get("evidence", {}).get("registry", {}).get("value") or {}
    email = str(reg_val.get("epostadresse") or reg_val.get("epost") or "").casefold()
    email_domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    is_custom_domain = bool(email_domain and email_domain not in {
        "gmail.com", "googlemail.com", "online.no", "hotmail.com", "hotmail.no",
        "outlook.com", "yahoo.com", "yahoo.no", "live.com", "live.no", "telenor.no", "icloud.com"
    })

    # Public-facing / customer-serving industry divisions (Retail, Dining, Health, Tech, Trades)
    is_public_facing = bool(industry_code.startswith((
        "47.", "55.", "56.", "62.", "63.", "70.", "71.", "85.", "86.", "93.", "95.", "96.", "43."
    )))

    # Base probability by employee bracket and public orientation
    if employees >= 20:
        prob = 0.65
    elif employees >= 10:
        prob = 0.55
    elif employees >= 5:
        prob = 0.45
    elif employees >= 1:
        prob = 0.35
    else:
        prob = 0.25

    if is_public_facing:
        prob += 0.15
    if is_custom_domain:
        prob += 0.25

    name_tokens = [t for t in _tokens(name) if t not in GENERIC_NAME_TOKENS]
    if len(name_tokens) >= 2:
        prob += 0.10

    return min(1.0, round(prob, 2))


def generate_deterministic_domain_candidates(profile: dict[str, Any]) -> list[str]:
    """Generate high-confidence candidate URLs derived from clean legal name tokens.
    
    Used only for high/medium opportunity entities before falling back to search queries.
    """
    name = " ".join(str(profile.get("name") or "").split())
    if not name:
        return []

    tokens = [t for t in _tokens(name) if t not in GENERIC_NAME_TOKENS]
    if not tokens:
        return []

    candidates: list[str] = []
    # 1. Combined tokens (e.g., 'fetsund-tannklinikk' or 'fetsundtannklinikk')
    if len(tokens) == 1:
        t = tokens[0]
        if len(t) >= 4:
            candidates.extend([f"https://{t}.no/", f"https://www.{t}.no/", f"https://{t}-as.no/"])
    elif len(tokens) == 2:
        t1, t2 = tokens[0], tokens[1]
        candidates.extend([
            f"https://{t1}{t2}.no/",
            f"https://www.{t1}{t2}.no/",
            f"https://{t1}-{t2}.no/",
            f"https://www.{t1}-{t2}.no/",
        ])
    elif len(tokens) == 3:
        t1, t2, t3 = tokens[0], tokens[1], tokens[2]
        candidates.extend([
            f"https://{t1}{t2}{t3}.no/",
            f"https://{t1}-{t2}-{t3}.no/",
            f"https://{t1}{t2}.no/",
        ])

    return list(dict.fromkeys(candidates))


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

    generic_emails = {
        "gmail.com", "googlemail.com", "online.no", "hotmail.com", "hotmail.no",
        "outlook.com", "yahoo.com", "yahoo.no", "live.com", "live.no", "telenor.no", "icloud.com"
    }
    if email_domain and "." in email_domain and email_domain not in generic_emails:
        queries.append(f'"{clean_name}" {email_domain}')

    # Subunit & Brand Bridge Queries: reverse discovery via operating workplaces
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


def _tokens(value: Any) -> list[str]:
    text = str(value or "").translate(str.maketrans({"ø": "o", "å": "a", "æ": "ae", "Ø": "O", "Å": "A", "Æ": "AE"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return [token for token in re.findall(r"[a-z0-9]+", text) if len(token) > 1]


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
    
    # Token-boundary aware name in host matching (handles b.wood -> bwood, fetsund-tannklinikk -> fetsundtannklinikk)
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
    
    # Subunit hostname & evidence check
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

    # Candidate gate: must have distinctive name or subunit name in hostname, or matching email domain,
    # and either exact org number, title name match, or strong multi-token host evidence.
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
