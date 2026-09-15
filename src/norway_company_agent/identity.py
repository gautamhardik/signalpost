from __future__ import annotations

import re
import unicodedata
import urllib.parse
from typing import Any


LEGAL_AND_GENERIC = {
    "as", "asa", "ans", "da", "enk", "iks", "sa", "sam", "sti", "stiftelsen",
    "nuf", "ab", "b", "v", "limited", "ltd", "inc", "plc", "the", "og", "and",
}

GENERIC_BRAND_TOKENS = {
    "hold", "holding", "drift", "eiendom", "investering", "group", "invest",
    "management", "consulting", "norge", "nordic", "service", "partner",
}


def _tokens(value: Any) -> list[str]:
    text = str(value or "").translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return [token for token in re.findall(r"[a-z0-9]+", text) if token not in LEGAL_AND_GENERIC and len(token) > 1]


def _compact_identity_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize(
        "NFKD", str(value or "")
    ).encode("ascii", "ignore").decode().casefold())


def _compact_digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))



def _structured_names(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"name", "legalName", "alternateName"} and isinstance(child, str):
                names.append(child)
            else:
                names.extend(_structured_names(child))
    elif isinstance(value, list):
        for child in value:
            names.extend(_structured_names(child))
    return names


def assess_website_identity(profile: dict[str, Any]) -> dict[str, Any]:
    website = profile.get("evidence", {}).get("website", {})
    value = website.get("value") or {}
    core = _tokens(profile.get("name"))
    hostname = urllib.parse.urlparse(value.get("final_url") or website.get("source_url") or "").hostname or ""
    structured_names = _structured_names(value.get("structured_organisations") or [])
    rendered = value.get("js_fallback") or {}
    homepage_identity_parts = [
        value.get("title"), value.get("description"), value.get("identity_text_excerpt"), hostname, *structured_names,
        rendered.get("title"),
    ]
    candidate_parts = [
        *homepage_identity_parts, value.get("main_text_excerpt"),
        *[page.get("title") for page in value.get("pages", [])],
        *[page.get("main_text_excerpt") for page in value.get("pages", [])],
        *[page.get("identity_text_excerpt") for page in value.get("pages", [])],
    ]
    candidate_parts.append(rendered.get("main_text_excerpt"))
    candidate_text = " ".join(str(part or "") for part in candidate_parts)
    homepage_candidate_text = " ".join(str(part or "") for part in [*homepage_identity_parts, value.get("main_text_excerpt"), rendered.get("main_text_excerpt")])
    normalized_candidate_text = " ".join(_tokens(candidate_text))
    candidate_tokens = set(_tokens(candidate_text))
    org_digits = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))

    registry_value = profile.get("evidence", {}).get("registry", {}).get("value") or {}
    registry_street = str(
        registry_value.get("forretningsadresse.adresse")
        or registry_value.get("postadresse.adresse")
        or ""
    ).strip()

    registry_postcode = _compact_digits(
        registry_value.get("forretningsadresse.postnummer")
        or registry_value.get("postadresse.postnummer")
        or ""
    )

    registry_city = _compact_identity_text(
        registry_value.get("forretningsadresse.poststed")
        or registry_value.get("forretningsadresse.kommune")
        or registry_value.get("postadresse.poststed")
        or registry_value.get("postadresse.kommune")
        or ""
    )

    registry_phone = _compact_digits(
        registry_value.get("mobil")
        or registry_value.get("telefon")
        or ""
    )

    registry_email = str(
        registry_value.get("epostadresse")
        or registry_value.get("epost")
        or ""
    ).strip().casefold()

    email_domain = registry_email.rsplit("@", 1)[-1] if "@" in registry_email else ""
    email_domain = email_domain.removeprefix("www.")

    candidate_host = str(value.get("url") or value.get("final_url") or website.get("source_url") or "").split("://")[-1].split("/", 1)[0].split(":", 1)[0].casefold()
    candidate_host = candidate_host.removeprefix("www.")

    email_domain_match = bool(
        email_domain
        and candidate_host
        and (
            candidate_host == email_domain
            or candidate_host.endswith("." + email_domain)
        )
    )

    registry_website = str(
        registry_value.get("hjemmeside")
        or profile.get("website")
        or ""
    ).strip().casefold()
    registry_host = registry_website.split("://")[-1].split("/", 1)[0].split(":", 1)[0].casefold().removeprefix("www.")
    registry_domain_match = bool(
        registry_host
        and candidate_host
        and (
            candidate_host == registry_host
            or candidate_host.endswith("." + registry_host)
        )
    )

    title_text = str(value.get("title") or rendered.get("title") or "")
    title_tokens = set(_tokens(title_text))
    cand_domain_root = candidate_host.split(".")[0]
    brand_tokens = {
        t for t in set(core) & title_tokens
        if len(t) >= 4 and t not in GENERIC_BRAND_TOKENS
    }
    brand_title_corroboration = (
        registry_domain_match
        and bool(brand_tokens)
        and any(t == cand_domain_root or t in cand_domain_root for t in brand_tokens)
    )

    identity_text = f"{candidate_text} {homepage_candidate_text}"
    compact_identity = _compact_identity_text(identity_text)

    street_match = bool(
        registry_street
        and _compact_identity_text(registry_street) in compact_identity
    )

    postcode_match = bool(
        registry_postcode
        and registry_postcode in _compact_digits(identity_text)
    )

    city_match = bool(
        registry_city
        and registry_city in _compact_identity_text(identity_text)
    )

    phone_match = bool(
        registry_phone
        and len(registry_phone) >= 8
        and registry_phone in _compact_digits(identity_text)
    )

    # Check registered operational subunits (underenheter) under this parent company
    subunits = (profile.get("evidence", {}).get("locations", {}).get("value") or {}).get("locations") or []
    subunit_match = False
    subunit_matched_name = None
    for sub in subunits:
        sub_name = str(sub.get("name") or "")
        sub_core = [t for t in _tokens(sub_name) if t not in LEGAL_AND_GENERIC]
        sub_addr = sub.get("address") or {}
        sub_postcode = _compact_digits(sub_addr.get("postnummer"))
        sub_street = str(sub_addr.get("adresse") or "")
        sub_name_in_page = bool(sub_core and (len(sub_core) >= 2 and all(t in candidate_tokens for t in sub_core)))
        sub_addr_in_page = bool((sub_postcode and sub_postcode in _compact_digits(identity_text)) or
                                (sub_street and _compact_identity_text(sub_street) in compact_identity))
        if sub_name_in_page and (sub_addr_in_page or (sub_core and len(sub_core) >= 3)):
            subunit_match = True
            subunit_matched_name = sub_name
            break

    address_match = street_match and postcode_match

    strong_registry_corroboration = (
        address_match
        or (postcode_match and city_match and phone_match)
        or (street_match and phone_match)
        or subunit_match
    )

    compact_candidate = re.sub(r"\D", "", candidate_text)
    compact_homepage_candidate = re.sub(r"\D", "", homepage_candidate_text)
    overlap = sorted(set(core) & candidate_tokens)
    ratio = len(overlap) / len(set(core)) if core else 0.0
    reasons = []
    parked_markers = (
        "domain is for sale", "domain for sale", "hugedomains", "parked at", "miss hosting",
        "her flytter snart en ny gjest", "has been informing visitors",
        "find the best information and most relevant links on all topics related to",
    )
    normalized_raw = unicodedata.normalize("NFKD", candidate_text).encode("ascii", "ignore").decode().casefold()
    homepage_token_sets = [set(_tokens(part)) for part in homepage_identity_parts if part]
    exact_homepage_name = bool(core and any(set(core).issubset(tokens) for tokens in homepage_token_sets))
    substantive_homepage = len(str(value.get("main_text_excerpt") or "").strip()) >= 100
    substantive_site = substantive_homepage or any(len(str(p.get("main_text_excerpt") or "").strip()) >= 100 for p in value.get("pages", []))
    is_business_sports_club = bool(re.search(r"(?:^|\s)B\.?\s*I\.?\s*L\.?(?:\s|$)", str(profile.get("name") or ""), re.I))
    # Conflicting 9-digit Norwegian OrgNr detection
    found_org_numbers = set(re.findall(r"\b[89]\d{8}\b", homepage_candidate_text))
    has_conflicting_org = bool(org_digits and any(o != org_digits for o in found_org_numbers))

    if any(marker in normalized_raw for marker in parked_markers):
        score = 0.1
        reasons.append("captured page is a parked, for-sale, or generic hosting placeholder")
    elif is_business_sports_club and "bedriftsidrett" not in normalized_candidate_text and "b i l" not in normalized_candidate_text:
        score = 0.3
        reasons.append("business sports-club entity points to the operating company's site without club evidence")
    elif org_digits and org_digits in compact_homepage_candidate:
        score = 1.0
        reasons.append("exact organisation number appears in homepage identity evidence")
    elif has_conflicting_org and not (org_digits and org_digits in compact_homepage_candidate):
        score = 0.2
        reasons.append("captured page contains conflicting organisation number belonging to a different entity")
    elif len(core) >= 2 and exact_homepage_name:
        score = 0.95
        reasons.append("all normalized legal-name tokens appear together in homepage identity evidence")
    elif len(core) == 1 and exact_homepage_name and substantive_homepage:
        score = 0.95
        reasons.append("single distinctive legal-name token appears in homepage identity evidence with substantive content")
    elif (
        core
        and (exact_homepage_name or ratio >= 0.75)
        and (strong_registry_corroboration or (phone_match and len(overlap) >= 1))
    ):
        score = 0.95
        reasons.append(
            "company name is corroborated by matching registry address or phone evidence"
        )
    elif ratio >= 0.75 and len(overlap) >= 2 and email_domain_match:
        score = 0.95
        reasons.append(
            "most legal-name tokens appear and candidate hostname matches the registry email domain"
        )
    elif (
        registry_domain_match
        and brand_title_corroboration
        and substantive_site
    ):
        score = 0.90
        reasons.append(
            "candidate domain is registered to company in official registry and homepage title corroborates primary brand token"
        )
    elif ratio >= 0.75 and len(overlap) >= 2:
        score = 0.85
        reasons.append("most legal-name tokens appear, but exact identity is incomplete")
    elif ratio >= 0.5 and len(overlap) >= 2:
        score = 0.65
        reasons.append("partial legal-name overlap only")
    else:
        score = 0.3
        reasons.append("registry-linked URL lacks strong exact-entity identity evidence")
    status = "exact" if score >= 0.9 else "review" if score >= 0.8 else "related_or_uncertain"
    return {
        "status": status,
        "score": score,
        "publishable": status == "exact",
        "exact_entity": score >= 0.9,
        "matched_name_tokens": overlap,
        "name_token_count": len(core),
        "name_match_ratio": ratio,
        "email_domain": email_domain or None,
        "email_domain_match": email_domain_match,
        "registry_identity": {
            "street_match": street_match,
            "postcode_match": postcode_match,
            "city_match": city_match,
            "phone_match": phone_match,
            "address_match": address_match,
            "strong_corroboration": strong_registry_corroboration,
        },
        "reasons": reasons,
        "method": "deterministic_name_org_evidence_v3",
    }


def assess_social_identity(profile: dict[str, Any], link: dict[str, str]) -> dict[str, Any]:
    core = _tokens(profile.get("name"))
    parsed = urllib.parse.urlparse(link.get("url") or "")
    handle_text = urllib.parse.unquote(parsed.path)

    # Strip non-alphanumeric chars (dots, underscores, hyphens) for compact comparison
    handle_raw_compact = re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", handle_text).encode("ascii", "ignore").decode().casefold())
    handle_tokens = _tokens(handle_text)
    handle_compact = "".join(handle_tokens)
    core_compact = "".join(core)

    # Check token overlap both from tokenized handle and raw compacted handle
    matched = [token for token in core if (token in handle_tokens or token in handle_compact or token in handle_raw_compact)]
    ratio = len(set(matched)) / len(set(core)) if core else 0.0

    if (core_compact and (core_compact in handle_compact or core_compact in handle_raw_compact)):
        score = 0.98
        reason = "normalized legal-name sequence appears in the social handle"
    elif len(core) == 1 and matched:
        score = 0.95
        reason = "single distinctive legal-name token appears in the social handle"
    elif ratio >= 0.75 and len(set(matched)) >= 2:
        score = 0.9
        reason = "most legal-name tokens appear in the social handle"
    elif len(core) >= 2 and set(core).issubset(set(handle_tokens)):
        score = 0.95
        reason = "all distinctive legal-name tokens appear in the social handle"
    else:
        score = 0.3
        reason = "social handle lacks strong exact-entity name evidence"
    return {
        **link,
        "identity_score": score,
        "publishable": score >= 0.9,
        "matched_tokens": matched,
        "reason": reason,
        "method": "deterministic_social_handle_identity_v1",
    }


def apply_website_identity_gate(profile: dict[str, Any], website: dict[str, Any]) -> dict[str, Any]:
    if website.get("status") != "available":
        return {"website": website, "assessment": None, "quarantined_social_links": 0}
    temporary_profile = {**profile, "evidence": {**profile.get("evidence", {}), "website": website}}
    value = website.get("value") or {}
    assessment = assess_website_identity(temporary_profile)
    value["identity_assessment"] = assessment
    original = list(value.get("discovered_social_links") or value.get("social_links") or [])
    value["discovered_social_links"] = original
    social_assessments = [assess_social_identity(profile, link) for link in original]
    value["social_link_assessments"] = social_assessments
    value["social_links"] = [
        {"platform": item["platform"], "url": item["url"]}
        for item in social_assessments
        if assessment["publishable"] and item["publishable"]
    ]
    website["value"] = value
    return {
        "website": website,
        "assessment": assessment,
        "quarantined_social_links": len(original) - len(value["social_links"]),
    }
