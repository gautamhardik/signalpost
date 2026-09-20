from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import extruct
import tldextract

from .evidence import Evidence, evidence, utc_now
from .identity import _tokens
from .jobs import MONTH_MAP, normalize_date_string


ACTIVITY_TYPES = {
    "news",
    "press_release",
    "announcement",
    "event",
    "partnership",
    "launch",
    "award",
    "company_update",
}

GENERIC_NAV_TITLES = {
    "nyheter", "aktuelt", "presse", "news", "press", "artikler", "blogg", "blog",
    "pressemeldinger", "arkiv", "newsroom", "events", "arrangementer", "kurs",
    "hjem", "forside", "home", "om oss", "about us", "kontakt oss", "contact us",
}


@dataclass(frozen=True)
class ActivityRecord:
    activity_id: str
    company_orgnr: str
    activity_type: str
    title: str
    description: str | None
    activity_date: str | None
    source_url: str
    retrieved_at: str
    content_sha256: str
    identity_assessment: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def clean_activity_title(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = re.sub(r"\s+", " ", str(title)).strip()
    cleaned = re.sub(r"^[-–—•*|:]+\s*", "", cleaned)
    cleaned = re.sub(r"\s*[-–—•*|:]+$", "", cleaned).strip()
    if not cleaned or len(cleaned) < 4:
        return None
    if cleaned.casefold() in GENERIC_NAV_TITLES:
        return None
    return cleaned[:300]


def classify_activity_type(title: str, text: str) -> str:
    """Classify activity type based on title and content keywords."""
    combined = (title + " " + text[:500]).casefold()

    if any(k in combined for k in ("pressemelding", "press release", "børsmelding")):
        return "press_release"
    if any(k in combined for k in ("samarbeid", "partnerskap", "partner", "partnership", "allianse", "avtale")):
        return "partnership"
    if any(k in combined for k in ("lanserer", "lansering", "launch", "nytt produkt", "ny tjeneste", "introduserer")):
        return "launch"
    if any(k in combined for k in ("vinner", "vant", "kåret", "award", "akkreditering", "sertifisering")) or re.search(r"\b(pris|prisen|priser)\b", combined):
        return "award"
    if any(k in combined for k in ("webinar", "konferanse", "seminar", "event", "messe", "arrangement", "frokostmøte")):
        return "event"
    if any(k in combined for k in ("kunngjøring", "announcement", "endring", "varsel", "informasjon til")):
        return "announcement"
    if any(k in combined for k in ("nyhet", "siste nytt", "aktuelt", "artikkel")):
        return "news"

    return "company_update"


def extract_activity_date_from_text(text: str) -> str | None:
    """Extract explicit publication or event dates from article header or text context."""
    patterns = [
        # Explicit date prefixes in Norwegian / English
        r"(?:publisert|oppdatert|dato|posted|published|date)\s*[:\-]?\s*([0-3]?\d[\./-][01]?\d[\./-]202\d)",
        r"(?:publisert|oppdatert|dato|posted|published|date)\s*[:\-]?\s*([0-3]?\d\.?\s+[a-zA-ZæøåÆØÅ]+\s+202\d)",
        # ISO format
        r"\b(202\d-[01]\d-[0-3]\d)\b",
        # DD.MM.YYYY
        r"\b([0-3]?\d[\./-][01]?\d[\./-]202\d)\b",
        # DD. Month YYYY
        r"\b([0-3]?\d)\.?\s+([a-zA-ZæøåÆØÅ]+)\s+(202\d)\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(0)
            parsed = normalize_date_string(val)
            if parsed:
                return parsed
    return None


def verify_activity_identity(
    profile: dict[str, Any],
    activity_candidate: dict[str, Any],
    source_url: str,
) -> dict[str, Any]:
    """Verify that a candidate activity belongs to the target company and not an uncorroborated third party, parent, or partner."""
    company_name = profile.get("name") or ""
    org_nr = str(profile.get("organisation_number") or "")
    core_tokens = set(_tokens(company_name))

    evidence_rec = profile.get("evidence", {})
    web_val = (evidence_rec.get("website") or {}).get("value") or {}
    verified_registered_domain = web_val.get("registered_domain") or ""

    parsed_url = urlparse(source_url)
    domain_ext = tldextract.extract(parsed_url.hostname or "")
    candidate_reg_domain = domain_ext.top_domain_under_public_suffix

    same_domain = bool(verified_registered_domain and candidate_reg_domain == verified_registered_domain)

    author_or_publisher = activity_candidate.get("publisher") or activity_candidate.get("author") or ""
    author_tokens = set(_tokens(author_or_publisher))
    name_overlap = len(core_tokens & author_tokens) if author_or_publisher else 0
    token_ratio = name_overlap / len(core_tokens) if core_tokens else 0.0

    title_text = str(activity_candidate.get("title") or "")
    desc_text = str(activity_candidate.get("description") or "")

    # Group/Subsidiary boundary protection:
    # If the headline or author explicitly credits a different corporate parent or unrelated company
    if same_domain:
        if author_or_publisher and token_ratio == 0 and len(author_tokens) >= 2:
            # Explicit external publisher on company blog -> third party or subsidiary guest post
            return {
                "verified": False,
                "score": 0.35,
                "reason": f"Activity on company domain is explicitly attributed to another organisation: {author_or_publisher}",
                "method": "parent_subsidiary_boundary_gate",
            }
        score = 0.95
        reason = "Activity published directly on verified company domain"
        method = "verified_domain_first_party_activity"
    else:
        # External news portal or PR distribution platform (e.g. NTB Kommunikasjon, Mynewsdesk, Cision)
        pr_hosts = {"ntb.no", "mynewsdesk.com", "cision.com", "globenewswire.com"}
        is_pr_wire = candidate_reg_domain in pr_hosts

        title_tokens = set(_tokens(title_text))
        body_tokens = set(_tokens(desc_text))
        mentioned_in_title = bool(core_tokens & title_tokens)
        mentioned_in_body = (len(core_tokens & body_tokens) / len(core_tokens) >= 0.75) if core_tokens else False
        has_org_nr = org_nr in desc_text if org_nr else False

        if is_pr_wire and (mentioned_in_title or has_org_nr or (token_ratio >= 0.75)):
            score = 0.92
            reason = f"Verified press release via wire distribution for {company_name}"
            method = "pr_wire_corroborated_activity"
        elif has_org_nr or (mentioned_in_title and mentioned_in_body):
            score = 0.90
            reason = "External news coverage strongly corroborates exact company identity"
            method = "external_news_corroborated_match"
        else:
            return {
                "verified": False,
                "score": 0.25,
                "reason": f"External activity lacks conclusive corroboration for legal entity {company_name}",
                "method": "external_activity_unverified_gate",
            }

    return {
        "verified": True,
        "score": score,
        "reason": reason,
        "method": method,
    }


def extract_activity_from_jsonld(
    html: str,
    base_url: str,
    profile: dict[str, Any],
) -> list[ActivityRecord]:
    """Extract Article, NewsArticle, BlogPosting, or Event structured data from page HTML."""
    try:
        data = extruct.extract(html, base_url=base_url, syntaxes=["json-ld"])
    except Exception:
        return []

    jsonld_items = data.get("json-ld", [])
    candidates: list[dict[str, Any]] = []

    target_types = {
        "Article", "NewsArticle", "BlogPosting", "PressRelease",
        "Event", "BusinessEvent", "SocialEvent"
    }

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            type_val = item.get("@type")
            types = set(type_val if isinstance(type_val, list) else [type_val])
            if types & target_types:
                candidates.append(item)
            for v in item.values():
                walk(v)
        elif isinstance(item, list):
            for i in item:
                walk(i)

    walk(jsonld_items)
    records: list[ActivityRecord] = []
    org_nr = str(profile.get("organisation_number") or "")

    for c in candidates:
        raw_title = c.get("headline") or c.get("name") or c.get("title")
        title = clean_activity_title(raw_title)
        if not title:
            continue

        raw_desc = c.get("description") or c.get("articleBody") or ""
        desc_soup = BeautifulSoup(str(raw_desc), "lxml")
        desc = re.sub(r"\s+", " ", desc_soup.get_text(" ", strip=True))[:1000] if raw_desc else None

        # Dates: datePublished, startDate (for events), dateModified
        date_raw = c.get("datePublished") or c.get("startDate") or c.get("dateCreated")
        activity_date = normalize_date_string(date_raw)

        # Publisher / author
        pub_val = c.get("publisher") or c.get("author")
        pub_name = ""
        if isinstance(pub_val, dict):
            pub_name = pub_val.get("name") or ""
        elif isinstance(pub_val, str):
            pub_name = pub_val

        act_url = c.get("url") or base_url
        act_url = urljoin(base_url, str(act_url))

        # Identity gate
        cand_dict = {
            "title": title,
            "description": desc or "",
            "publisher": pub_name,
        }
        id_assessment = verify_activity_identity(profile, cand_dict, act_url)
        if not id_assessment["verified"]:
            continue

        # Classify type
        type_str = classify_activity_type(title, desc or "")
        c_type = c.get("@type")
        types = set(c_type if isinstance(c_type, list) else [c_type])
        if types & {"Event", "BusinessEvent", "SocialEvent"}:
            type_str = "event"

        raw_bytes = f"{title}|{act_url}|{activity_date}".encode("utf-8")
        content_sha = hashlib.sha256(raw_bytes).hexdigest()
        act_id = f"act-{org_nr}-{content_sha[:12]}"

        records.append(ActivityRecord(
            activity_id=act_id,
            company_orgnr=org_nr,
            activity_type=type_str,
            title=title,
            description=desc,
            activity_date=activity_date,
            source_url=act_url,
            retrieved_at=utc_now(),
            content_sha256=content_sha,
            identity_assessment=id_assessment,
        ))

    return records


def extract_activity_from_html_articles(
    html: str,
    base_url: str,
    profile: dict[str, Any],
) -> list[ActivityRecord]:
    """Fallback: extract articles, news posts, or announcements from structured HTML elements."""
    soup = BeautifulSoup(html, "lxml")
    org_nr = str(profile.get("organisation_number") or "")
    records: list[ActivityRecord] = []

    # Article or card containers
    selectors = [
        "article", ".news-item", ".nyhet-item", ".post-item",
        ".article-card", ".nyhetskort", ".press-release", ".event-item",
        ".aktuelt-item", ".blog-post"
    ]
    cards = soup.select(", ".join(selectors))

    # If no article containers, inspect linked news anchors
    if not cards:
        links = soup.select("a[href*='/nyheter/'], a[href*='/aktuelt/'], a[href*='/presse/'], a[href*='/news/'], a[href*='/artikler/']")
        seen_links = set()
        for link in links:
            href = link.get("href")
            if not href:
                continue
            full_url = urljoin(base_url, href)
            if full_url in seen_links or full_url.rstrip("/") == base_url.rstrip("/"):
                continue
            seen_links.add(full_url)

            title_text = clean_activity_title(link.get_text(" ", strip=True))
            if not title_text:
                continue

            parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""
            activity_date = extract_activity_date_from_text(parent_text)

            id_assessment = verify_activity_identity(profile, {"title": title_text, "description": parent_text}, full_url)
            if not id_assessment["verified"]:
                continue

            act_type = classify_activity_type(title_text, parent_text)
            content_sha = hashlib.sha256(f"{title_text}|{full_url}|{activity_date}".encode("utf-8")).hexdigest()
            act_id = f"act-{org_nr}-{content_sha[:12]}"

            records.append(ActivityRecord(
                activity_id=act_id,
                company_orgnr=org_nr,
                activity_type=act_type,
                title=title_text,
                description=parent_text[:300] if parent_text else None,
                activity_date=activity_date,
                source_url=full_url,
                retrieved_at=utc_now(),
                content_sha256=content_sha,
                identity_assessment=id_assessment,
            ))
        return records

    for card in cards:
        title_el = card.select_one("h1, h2, h3, h4, .title, .headline, a")
        if not title_el:
            continue
        title = clean_activity_title(title_el.get_text(" ", strip=True))
        if not title:
            continue

        link_el = card.select_one("a[href]") or (title_el if title_el.name == "a" and title_el.get("href") else None)
        item_url = urljoin(base_url, link_el.get("href")) if link_el else base_url

        card_text = card.get_text(" ", strip=True)

        # Date extraction: search <time> tags first, then text regex
        time_el = card.select_one("time")
        activity_date = None
        if time_el:
            activity_date = normalize_date_string(time_el.get("datetime") or time_el.get_text(" ", strip=True))
        if not activity_date:
            activity_date = extract_activity_date_from_text(card_text)

        id_assessment = verify_activity_identity(profile, {"title": title, "description": card_text}, item_url)
        if not id_assessment["verified"]:
            continue

        act_type = classify_activity_type(title, card_text)
        content_sha = hashlib.sha256(f"{title}|{item_url}|{activity_date}".encode("utf-8")).hexdigest()
        act_id = f"act-{org_nr}-{content_sha[:12]}"

        records.append(ActivityRecord(
            activity_id=act_id,
            company_orgnr=org_nr,
            activity_type=act_type,
            title=title,
            description=card_text[:500] if card_text else None,
            activity_date=activity_date,
            source_url=item_url,
            retrieved_at=utc_now(),
            content_sha256=content_sha,
            identity_assessment=id_assessment,
        ))

    return records


def extract_activity_from_crawl_material(
    profile: dict[str, Any],
    website_material: dict[str, Any],
) -> list[ActivityRecord]:
    """Extract verified company activities from all pages of a crawled website."""
    val = website_material.get("value") or {}
    pages = val.get("pages") or []
    final_url = val.get("final_url") or website_material.get("source_url") or ""

    if not pages and final_url:
        pages = [{"url": final_url, "html": val.get("html") or "", "title": val.get("title")}]

    all_activities: dict[str, ActivityRecord] = {}

    for page in pages:
        p_url = page.get("url") or final_url
        p_html = page.get("html") or ""
        p_text = page.get("main_text_excerpt") or ""

        if not p_html:
            p_html = f"<html><head><title>{page.get('title', '')}</title></head><body>{p_text}</body></html>"

        # 1. Primary: JSON-LD Article/Event
        jsonld_activities = extract_activity_from_jsonld(p_html, p_url, profile)
        for act in jsonld_activities:
            if act.activity_id not in all_activities:
                all_activities[act.activity_id] = act

        # 2. Fallback: HTML cards / links
        p_path = urlparse(p_url).path.casefold()
        is_activity_url = any(k in p_path for k in ("nyhet", "aktuelt", "presse", "news", "press", "blog", "event", "artikkel"))
        if is_activity_url or not jsonld_activities:
            html_activities = extract_activity_from_html_articles(p_html, p_url, profile)
            for act in html_activities:
                if act.activity_id not in all_activities:
                    all_activities[act.activity_id] = act

            # 3. If the page itself is a dedicated article/event page (not an empty archive) and no sub-cards were found:
            if not html_activities and is_activity_url:
                p_title = clean_activity_title(page.get("title"))
                if p_title and len(p_text.strip()) > 40:
                    act_date = extract_activity_date_from_text(p_text[:400])
                    act_type = classify_activity_type(p_title, p_text)
                    id_assessment = verify_activity_identity(profile, {"title": p_title, "description": p_text}, p_url)
                    if id_assessment["verified"]:
                        content_sha = hashlib.sha256(f"{p_title}|{p_url}|{act_date}".encode("utf-8")).hexdigest()
                        org_nr = str(profile.get("organisation_number") or "")
                        act_id = f"act-{org_nr}-{content_sha[:12]}"
                        standalone_act = ActivityRecord(
                            activity_id=act_id,
                            company_orgnr=org_nr,
                            activity_type=act_type,
                            title=p_title,
                            description=p_text[:500],
                            activity_date=act_date,
                            source_url=p_url,
                            retrieved_at=utc_now(),
                            content_sha256=content_sha,
                            identity_assessment=id_assessment,
                        )
                        if act_id not in all_activities:
                            all_activities[act_id] = standalone_act

    return list(all_activities.values())


def extract_activity_evidence(
    profile: dict[str, Any],
    website_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Produce standardized Evidence dictionary for the activity module."""
    if website_evidence.get("status") != "available":
        return evidence(
            field="activity",
            status="not_found",
            source_type="company_verified_activity",
            source_url=website_evidence.get("source_url") or "https://data.brreg.no",
            note="No verified website available for activity extraction",
        )

    activities = extract_activity_from_crawl_material(profile, website_evidence)
    source_url = website_evidence.get("source_url") or ""

    if not activities:
        return evidence(
            field="activity",
            status="not_found",
            source_type="company_verified_activity",
            source_url=source_url,
            value={"activities": [], "total_activities": 0},
            note="Verified website inspected; no active structured company updates or dated announcements detected.",
        )

    act_dicts = [a.to_dict() for a in activities]
    composite_sha = hashlib.sha256(json.dumps([a["activity_id"] for a in act_dicts], sort_keys=True).encode()).hexdigest()

    dated_items = [a for a in activities if a.activity_date]
    effective_at = dated_items[0].activity_date if dated_items else None

    return evidence(
        field="activity",
        status="available",
        source_type="company_verified_activity",
        source_url=source_url,
        value={
            "activities": act_dicts,
            "total_activities": len(act_dicts),
            "dated_activities_count": len(dated_items),
        },
        content_sha256=composite_sha,
        effective_at=effective_at,
        note=f"Discovered {len(act_dicts)} verified company update(s) ({len(dated_items)} dated)",
    )


def extract_activity_observations(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert verified activity records into external footprint observations."""
    org = str(profile.get("organisation_number") or "")
    website = profile.get("evidence", {}).get("website", {})
    if not org or website.get("status") != "available":
        return []

    activities = extract_activity_from_crawl_material(profile, website)
    observations: list[dict[str, Any]] = []

    for act in activities:
        obs = {
            "id": f"act-{org}-{act.activity_id}",
            "organisation_number": org,
            "platform": "news",
            "signal_type": "public_post",
            "source_url": act.source_url,
            "retrieved_at": act.retrieved_at,
            "content_sha256": act.content_sha256,
            "exact_entity": True,
            "identity_proof": [act.identity_assessment],
            "acquisition_mode": "permitted_public_page",
            "rights_status": "approved",
            "source_class": f"company_{act.activity_type}",
            "evidence_span": f"Verified {act.activity_type}: {act.title}" + (f" ({act.activity_date})" if act.activity_date else ""),
            "metrics": {
                "activity_type": act.activity_type,
                "title": act.title,
                "activity_date": act.activity_date,
            },
        }
        observations.append(obs)

    return observations
