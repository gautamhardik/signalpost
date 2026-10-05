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
    # Transliterate Norwegian letters the same way _tokens does, so "Frisør" becomes "frisor"
    # in both (NFKD alone would drop the "ø").
    text = str(value or "").translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE"}))
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold())


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


BRANCH_WORDS = {
    "ost", "vest", "nord", "sor", "midt", "indre", "ytre", "ostre", "vestre", "nordre", "sondre", "region",
    "avdeling", "avd", "lokallag", "lag", "krets", "distrikt", "fylkeslag", "fylke", "kommune",
    "ostfold", "akershus", "buskerud", "vestfold", "telemark", "agder", "rogaland", "hordaland", "vestland",
    "sogn", "fjordane", "more", "romsdal", "trondelag", "nordland", "troms", "finnmark", "innlandet",
    "hedmark", "oppland", "viken", "oslo", "bergen", "trondheim", "stavanger",
}


def specific_name_tokens(name: Any, host: str) -> list[str]:
    """Name words not already in the site's domain: what distinguishes this company from the
    organisation the domain belongs to ("sandnes" in Naturvernforbundet i Sandnes on
    naturvernforbundet.no). Empty when the domain carries the whole name."""
    root = re.sub(r"[^a-z0-9]", "", (host or "").casefold().removeprefix("www.").split(".")[0])
    return [token for token in _tokens(name) if token not in root]


def site_scope(url: str) -> str | None:
    """Path prefix a company's pages live under when its "website" is a section of a larger
    site (venstre.no/lokal/telemark/midt-telemark/); None when the site is the whole domain."""
    path = urllib.parse.urlparse(url or "").path or "/"
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return None
    return path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"


def within_site_scope(url: str, website_url: str, scope: str | None) -> bool:
    """True when url belongs to the company's part of the site (always true without a scope)."""
    if not scope:
        return True
    target, site = urllib.parse.urlparse(url or ""), urllib.parse.urlparse(website_url or "")
    same_host = (target.hostname or "").removeprefix("www.") == (site.hostname or "").removeprefix("www.")
    return same_host and (target.path or "/").startswith(scope)


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

    shared_mail_hosts = {"gmail.com", "hotmail.com", "outlook.com", "live.no", "live.com", "online.no", "yahoo.com", "icloud.com", "msn.com", "hotmail.no", "outlook.no"}
    email_domain_match = bool(
        email_domain
        and email_domain not in shared_mail_hosts
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
    # The registered address itself was requested and redirected elsewhere (palfingermarine.com
    # -> palfinger.com); counted only where the registry e-mail domain names the destination.
    requested_host = str(value.get("requested_url") or "").split("://")[-1].split("/", 1)[0].split(":", 1)[0].casefold().removeprefix("www.")
    registry_redirect_match = bool(
        registry_host and requested_host and not registry_domain_match
        and (requested_host == registry_host or requested_host.endswith("." + registry_host))
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
    error_page = bool(
        re.search(r"(?:^|/)_?404(?:[/._]|$)", urllib.parse.urlparse(value.get("final_url") or "").path or "")
        or re.search(r"\b404\b|page not found|siden finnes ikke|fant ikke siden|side ikke funnet|finner ikke siden", str(value.get("title") or ""), re.I)
    )
    parked_markers = (
        "domain is for sale", "domain for sale", "hugedomains", "parked at", "miss hosting",
        "her flytter snart en ny gjest", "has been informing visitors", "is parked", "domain is parked",
        "find the best information and most relevant links on all topics related to",
        # Norwegian registrars' parking pages ("oyslebovel.no | Parkert Domene")
        "parkert domene", "er parkert hos", "domenet er parkert", "dette domenet er registrert hos",
        "domene.no er norsk domeneregistrar", "parked free of charge",
    )
    normalized_raw = unicodedata.normalize("NFKD", candidate_text).encode("ascii", "ignore").decode().casefold()
    homepage_token_sets = [set(_tokens(part)) for part in homepage_identity_parts if part]
    # The name may also be written as one word ("HJEM | sognedanseklubb" for Søgne Danseklubb,
    # "Afrodite`s Skjønnhet"): compare it joined up, in what the page says (not its domain).
    compact_core = "".join(core)
    # Domain names written in the page ("energyconsult.no Hjem" as a site name) are the domain
    # echoing itself, not the page naming the company.
    domain_text = re.compile(r"\b(?:www\.)?[\w-]+(?:\.[\w-]+)*\.(?:no|com|net|org|se|dk|fi|eu|io|biz|info|nu|co|app|online|site)\b", re.IGNORECASE)
    compact_homepage_named = len(core) >= 2 and len(compact_core) >= 10 and any(
        compact_core in _compact_identity_text(domain_text.sub(" ", str(part))) for part in homepage_identity_parts if part and part != hostname
    )
    exact_homepage_name = bool(core and (any(set(core).issubset(tokens) for tokens in homepage_token_sets) or compact_homepage_named))
    substantive_homepage = len(str(value.get("main_text_excerpt") or "").strip()) >= 100
    substantive_site = substantive_homepage or any(len(str(p.get("main_text_excerpt") or "").strip()) >= 100 for p in value.get("pages", []))
    is_business_sports_club = bool(re.search(r"(?:^|\s)B\.?\s*I\.?\s*L\.?(?:\s|$)", str(profile.get("name") or ""), re.I))
    # Conflicting 9-digit Norwegian OrgNr detection
    found_org_numbers = set(re.findall(r"\b[89]\d{8}\b", homepage_candidate_text))
    has_conflicting_org = bool(org_digits and any(o != org_digits for o in found_org_numbers))

    # A site reached through a shortened-name domain (leroy.no -> a group page) must name the
    # company's distinguishing words in its own title/description, not just in a footer that
    # lists every group company.
    requested_host = urllib.parse.urlparse(value.get("requested_url") or "").hostname or candidate_host
    guess_specific = specific_name_tokens(profile.get("name"), requested_host)
    title_level = _compact_identity_text(" ".join(str(part or "") for part in [value.get("title"), value.get("description"), rendered.get("title"), *structured_names]))
    guess_place = set(_tokens(" ".join(str(registry_value.get(key) or "") for key in ("forretningsadresse.kommune", "forretningsadresse.poststed")))) | BRANCH_WORDS
    redirected_elsewhere = requested_host.removeprefix("www.") != candidate_host.removeprefix("www.")
    guessed_domain_unnamed = redirected_elsewhere and bool(guess_specific) and not (org_digits and org_digits in compact_homepage_candidate) and not (
        all(token in title_level for token in guess_specific if token in guess_place)
        and any(token in title_level for token in guess_specific)
    )

    # A name match alone is not enough for a site found by guessing or search: common
    # words ("venture", "nyati") are shared by unrelated businesses worldwide. Such a
    # site must also be linked to the company by the registry, by a Norwegian address
    # or phone on the page, or (for a .no domain) by the name forming the domain itself.
    registry_linked = registry_domain_match or email_domain_match
    # A registered person (CEO, chair, board member) named on the site ties it to this company.
    roles = (profile.get("evidence", {}).get("roles", {}).get("value") or {}).get("roles") or []
    compact_site = " ".join(_tokens(identity_text))
    person_match = None
    for role in roles:
        if role.get("inactive") or role.get("organisation_number"):
            continue
        name_tokens = _tokens(role.get("name"))
        if name_tokens and {name_tokens[0], name_tokens[-1]} <= set(core):
            continue  # the company is named after this person; their name on a site proves nothing
        if len(name_tokens) >= 2 and f" {name_tokens[0]} " in f" {compact_site} " and f" {name_tokens[-1]} " in f" {compact_site} ":
            full = " ".join(name_tokens)
            first_last = f"{name_tokens[0]} {name_tokens[-1]}"
            if full in compact_site or first_last in compact_site:
                person_match = role.get("name")
                break
    strong_local = street_match or postcode_match or phone_match or subunit_match or bool(person_match)
    local_corroboration = strong_local or city_match
    raw_name_tokens = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", str(profile.get("name") or "")).encode("ascii", "ignore").decode().casefold())
    dropped_short_tokens = [tok for tok in raw_name_tokens if len(tok) == 1 and tok not in LEGAL_AND_GENERIC]
    norwegian_named_domain = (
        candidate_host.endswith(".no")
        and bool(core)
        and "".join(core) == cand_domain_root.replace("-", "")
        and not dropped_short_tokens
    )
    # Single-word names are too often shared, so a guessed domain alone never confirms them.
    if len(core) == 1:
        name_link_ok = registry_linked or strong_local
    else:
        name_link_ok = registry_linked or local_corroboration or norwegian_named_domain

    spelled_by_domain, rest_of_name = name_spelled_by_domain(profile.get("name"), re.sub(r"[^a-z0-9]", "", cand_domain_root))
    branch_registered_site = bool(spelled_by_domain and rest_of_name and all(token in _place_words(profile) for token in rest_of_name))
    chain_site_of_branch = False

    if error_page:
        score = 0.1
        reasons.append("captured page is an error (404) page, not a company website")
    elif any(marker in normalized_raw for marker in parked_markers):
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
    elif (registry_domain_match or registry_redirect_match) and email_domain_match and not has_conflicting_org:
        # Two independent official registry fields (website and e-mail) name this domain,
        # which the company itself registered; that holds even for a script-only homepage.
        score = 0.92
        reasons.append(
            "registry website and registry e-mail domain both point to this domain"
            if registry_domain_match else
            "the registered website redirects here and the registry e-mail domain is this domain"
        )
    elif not registry_linked and guessed_domain_unnamed:
        score = 0.85
        reasons.append("site reached through a shortened name does not name this specific company in its title or description")
    elif len(core) >= 2 and exact_homepage_name and name_link_ok:
        score = 0.95
        reasons.append("all normalized legal-name tokens appear together in homepage identity evidence")
    elif len(core) == 1 and exact_homepage_name and substantive_homepage and name_link_ok:
        score = 0.95
        reasons.append("single distinctive legal-name token appears in homepage identity evidence with substantive content")
    elif exact_homepage_name and not name_link_ok:
        score = 0.85
        reasons.append("name appears on the site, but nothing links the site to the registered Norwegian company (no registry domain, address, phone or .no name domain)")
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
    elif registry_domain_match and branch_registered_site and substantive_site:
        # "Jordbærpikene Stjørdal AS" registers jordbarpikene.no: the domain spells the rest of
        # the name and what is left is its own place. The site is its registered website, but
        # it is the chain's, so none of its content is attributed to this branch.
        score = 0.9
        chain_site_of_branch = True
        reasons.append("registry lists this site; it is the website of the organisation or chain this local branch belongs to")
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
    # A site can be correctly listed as the company's website yet belong to a broader
    # organisation (a national association's site registered by a local branch). Its news,
    # jobs and social links are then not this company's. Treat content as the company's own
    # only when the site names this exact entity: its org.nr, or its full name on the homepage,
    # or its full name anywhere on the site together with registered address/phone/person.
    full_name_on_site = bool(core) and set(core).issubset(candidate_tokens)
    specific = specific_name_tokens(profile.get("name"), candidate_host)
    compact_homepage_identity = _compact_identity_text(" ".join(str(part or "") for part in homepage_identity_parts))
    homepage_token_union = {t for s in homepage_token_sets for t in s}
    shown = lambda token: (token in compact_homepage_identity) if len(token) >= 5 else (token in homepage_token_union)  # noqa: E731
    place_words = set(_tokens(" ".join(str(registry_value.get(key) or "") for key in (
        "forretningsadresse.kommune", "forretningsadresse.poststed", "postadresse.poststed", "postadresse.kommune",
    )))) | BRANCH_WORDS
    # Branch-like qualifiers (place, region, "avdeling") must all be on the site; otherwise one
    # distinguishing word is enough ("Sandefjord" on torp.no for Sandefjord Lufthavn Drift).
    specific_on_homepage = (not specific) or (
        all(shown(token) for token in specific if token in place_words)
        and any(shown(token) for token in specific)
    )
    content_attributable = status == "exact" and bool(
        (org_digits and org_digits in compact_homepage_candidate)
        or exact_homepage_name
        or (full_name_on_site and local_corroboration)
        or (registry_linked and specific_on_homepage)
        or (registry_linked and bool(person_match))
    )
    if chain_site_of_branch:
        # A chain homepage listing "Stjørdal" among its shops does not make its content the branch's.
        content_attributable = bool((org_digits and org_digits in compact_homepage_candidate) or exact_homepage_name)
    return {
        "status": status,
        "score": score,
        "publishable": status == "exact",
        "exact_entity": score >= 0.9,
        "content_attributable": content_attributable,
        "site_scope": site_scope(value.get("final_url") or website.get("source_url") or ""),
        "matched_name_tokens": overlap,
        "name_token_count": len(core),
        "name_match_ratio": ratio,
        "email_domain": email_domain or None,
        "email_domain_match": email_domain_match,
        "registry_domain_match": registry_domain_match,
        "registry_identity": {
            "person_match": person_match,
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


# Hosting platforms and site builders: their domain is not a company's own name.
HOSTING_ROOTS = {
    "wix", "wixsite", "squarespace", "webflow", "weebly", "jimdo", "jimdofree", "blogspot", "wordpress",
    "github", "netlify", "vercel", "google", "sites", "framer", "godaddysites", "mystrikingly", "strikingly",
    "hubspot", "shopify", "myshopify", "facebook", "instagram", "linkedin", "youtube", "tiktok", "twitter",
}
# Handles that belong to a platform or theme, never to the company ("Powered by Wix" icons).
PLATFORM_HANDLES = HOSTING_ROOTS | {"envato", "themeforest", "elementor", "mailchimp", "home", "share", "sharer", "username", "yourpage", "page"}
HANDLE_SUFFIXES = {"", "no", "norge", "norway", "as", "asa", "sa", "official", "offisiell", "hq", "group", "gruppen", "com", "dk", "se"}


def site_name_root(url: str) -> str:
    """The name part of a site's registered domain ("g3i" for https://g3i.no/, "" for hosting platforms)."""
    import tldextract

    ext = tldextract.extract(urllib.parse.urlparse(url or "").hostname or "")
    root = re.sub(r"[^a-z0-9]", "", (ext.domain or "").casefold())
    return "" if len(root) < 3 or root in HOSTING_ROOTS else root


def name_spelled_by_domain(name: Any, root: str) -> tuple[list[str], list[str]]:
    """(name words the domain root spells out, the remaining name words).

    Tries "æ" written both as "ae" and as "a" (jordbarpikene.no for Jordbærpikene); the
    spelled words must make up the whole root, so "venstre" spells Venstre but "sparebank1"
    does not spell Sparebank alone.
    """
    text = str(name or "")
    for variant in (text, text.replace("æ", "a").replace("Æ", "A")):
        tokens = _tokens(variant)
        spelled = [token for token in tokens if token in root]
        if root and spelled and "".join(spelled) == root:
            return spelled, [token for token in tokens if token not in spelled]
    return [], _tokens(text)


def _place_words(profile: dict[str, Any]) -> set[str]:
    registry = profile.get("evidence", {}).get("registry", {}).get("value") or {}
    return set(_tokens(" ".join(str(registry.get(key) or "") for key in (
        "forretningsadresse.kommune", "forretningsadresse.poststed", "postadresse.poststed", "postadresse.kommune",
    )))) | set(_tokens(profile.get("municipality"))) | BRANCH_WORDS


def branch_of_site_owner(profile: dict[str, Any], root: str) -> bool:
    """True when the company is a local branch of the organisation the domain belongs to:
    the domain spells name words and the rest of the name is a place or branch word
    (Naturvernforbundet i Sandnes on naturvernforbundet.no, Midt-Telemark Venstre on venstre.no).
    The site's profiles are then the parent's, not this company's."""
    spelled, rest = name_spelled_by_domain(profile.get("name"), root)
    if not spelled:
        return False
    return any(token in _place_words(profile) for token in rest)


def _handle_only(path: str) -> str:
    """The account name in a profile path: "/company/sigma-bil" -> "sigmabil", "/@venstreno" -> "venstreno"."""
    segments = [segment for segment in path.split("/") if segment]
    if segments and segments[0].casefold() in {"company", "school", "showcase", "channel", "user", "c", "pg"}:
        segments = segments[1:]
    if not segments or segments[0].isdigit() or re.fullmatch(r"UC[\w-]{20,}", segments[0]):
        return ""  # numeric page ids and YouTube channel ids carry no name
    return _compact_identity_text(segments[0].lstrip("@"))


def handle_matches_site(handle_compact: str, root: str) -> bool:
    """The handle is the site's own name ("g3i_no" on g3i.no, "Sunnaas" on sunnaas.no)."""
    if not root or not handle_compact or handle_compact in PLATFORM_HANDLES:
        return False
    if handle_compact.startswith(root) and handle_compact[len(root):] in HANDLE_SUFFIXES:
        return True
    # Longer names may carry a short prefix or suffix ("weareknowit", "campingkilefjorden").
    return len(root) >= 6 and root in handle_compact and len(handle_compact) - len(root) <= 12


def assess_social_identity(profile: dict[str, Any], link: dict[str, str], site_root: str = "", branch_site: bool = False) -> dict[str, Any]:
    """Tie a social profile linked from the company's verified site to the company.

    Accepted when the handle carries the company's legal name, or when it is the verified
    site's own name (``site_root``) and the company is not a branch on a parent's site.
    """
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

    legal_forms = {"as", "asa", "da", "ans", "sa", "nuf", "ab", "enk", "ks", "iks"}
    company_form = str(profile.get("legal_form") or "").casefold()
    raw_handle_tokens = re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", handle_text).encode("ascii", "ignore").decode().casefold())
    other_form = next((token for token in raw_handle_tokens[1:] if token in legal_forms and token != company_form), None)
    if other_form:
        score = 0.3
        reason = f"social handle names a different legal form ({other_form.upper()}) than the company ({company_form.upper()})"
    elif (core_compact and (core_compact in handle_compact or core_compact in handle_raw_compact)):
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
    elif not branch_site and handle_matches_site(_handle_only(handle_text), site_root):
        score = 0.92
        reason = f"social handle is the verified website's own name ({site_root}) and is linked from that site"
    else:
        score = 0.3
        reason = "social handle lacks strong exact-entity name evidence"
    return {
        **link,
        "identity_score": score,
        "publishable": score >= 0.9,
        "matched_tokens": matched,
        "reason": reason,
        "method": "deterministic_social_handle_identity_v2",
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
    site_root = site_name_root(value.get("final_url") or website.get("source_url") or "")
    branch_site = bool(assessment.get("site_scope")) or branch_of_site_owner(profile, site_root)
    social_assessments = [assess_social_identity(profile, link, site_root, branch_site) for link in original]
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
