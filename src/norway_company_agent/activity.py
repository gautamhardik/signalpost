from __future__ import annotations

import collections
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
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
    found_on_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


URL_DATE_PATTERNS = (
    re.compile(r"/(20\d{2})/([01]?\d)/([0-3]?\d)(?:/|$)"),
    re.compile(r"(?:^|[/_-])(20\d{2})-([01]\d)-([0-3]\d)(?:[/_-]|$)"),
    re.compile(r"/(20\d{2})([01]\d)([0-3]\d)(?:[-_]|/|$)"),  # /news/20260512-5000-oil-cargoes
)

# Path segments that mark a listing, archive or author page rather than one article.
NEWS_INDEX_SEGMENTS = {
    "nyheter", "news", "blog", "blogg", "aktuelt", "presse", "press", "artikler", "arkiv",
    "nyhetsarkiv", "media", "newsroom", "pressroom", "events", "arrangementer", "kunngjoringer",
    "pressemeldinger", "press-releases", "investors", "investor", "en", "no", "nb",
}
NON_ARTICLE_SEGMENTS = {
    "author", "tag", "tags", "category", "kategori", "page", "side", "search", "sok",
    "kontakt", "kontakt-oss", "contact", "contact-us", "om", "om-oss", "about", "about-us",
    "personvern", "privacy", "privacy-policy", "personvernerklaering", "cookies", "cookie-policy",
    "vilkar", "terms", "ansatte", "team", "people", "ledelse", "management",
    "karriere", "careers", "jobs", "jobb", "ledige-stillinger",
    "categories", "archive", "archives", "arkiv", "collections", "collection", "products", "produkter",
    "produkt", "product", "shop", "butikk", "nettbutikk", "register", "registrer", "bli-medlem", "medlemskap",
    "login", "logg-inn", "min-side", "checkout", "cart", "handlekurv", "kasse",
}
# A news word at the start of a path segment or after a hyphen: "/nyheter-rkr/", "/blog/",
# "/press-releases/", but not "/express-fjord-road-trip/" or "/multimedia/".
ARTICLE_PATH_WORD = re.compile(
    r"(?:^|[-_])(?:nyhet|news|aktuelt|artikkel|artikler|article|blog|presse|press|pressemelding|event|arrangement|kunngjoring|siste-nytt|media|investor)",
)
ACTIVITY_PATH_WORD = re.compile(r"(?:^|[-_])(?:nyhet|aktuelt|presse|news|press|blog|event|artikkel)")


def has_path_word(path: str, pattern: re.Pattern[str] = ARTICLE_PATH_WORD) -> bool:
    return any(pattern.search(segment) for segment in path.casefold().split("/") if segment)


NON_ARTICLE_TITLE = re.compile(r"^(?:kontakt|contact|om oss|about|personvern|privacy|cookies|bli medlem|meld deg|logg inn|log in|sign up|registrer|handlekurv|nettbutikk)\b", re.IGNORECASE)
# Sample posts that site builders create (WordPress "Hello world!", Wix's lorem-ipsum posts).
PLACEHOLDER_TITLE = re.compile(
    r"^(?:hello world|hei verden|hallo verden|lorem ipsum|hvor kommer det fra|hvorfor bruker vi det|hva er lorem ipsum|"
    r"sample page|sample post|eksempelside|eksempelinnlegg|my first blog post|welcome to wordpress|untitled|blog post title|post title)\b",
    re.IGNORECASE,
)
# Headlines about criminal charges or convictions name or concern individuals; that is
# sensitive personal data, not news about the company, and is never republished.
CRIMINAL_MATTER = re.compile(
    r"\b(?:dømt|domfelt|straffedømt|voldtekt\w*|overgrep\w*|seksuell\w* omgang|drap\w*|siktet|tiltalt|"
    r"fengsel\w*|pedofil\w*|convicted|sentenced|rape|sexual assault)\b",
    re.IGNORECASE,
)
LINK_TEXT_TITLES = {
    "les mer", "read more", "les hele saken", "se alle", "se mer", "mer", "more", "vis alle",
    "flere nyheter", "flere prosjekter", "alle nyheter", "all news", "neste", "forrige",
}


def date_from_url(url: str) -> str | None:
    """Read a publication date embedded in an article URL (/2026/08/10/slug or 2026-08-10-slug)."""
    path = urlparse(url).path
    for pattern in URL_DATE_PATTERNS:
        m = pattern.search(path)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def is_publishable_news(act: "ActivityRecord", today: date | None = None) -> bool:
    """A news fact must be one dated article, not an index page, menu link or undated page."""
    if not act.activity_date:
        return False
    try:
        published = date.fromisoformat(act.activity_date)
    except ValueError:
        return False
    today = today or datetime.now(timezone.utc).date()
    horizon = timedelta(days=366) if act.activity_type == "event" else timedelta(days=1)
    if published < date(2000, 1, 1) or published > today + horizon:
        return False
    parsed = urlparse(act.source_url)
    segments = [seg for seg in parsed.path.casefold().split("/") if seg]
    if not segments:
        return False  # homepage, or an anchor on it
    if parsed.fragment and act.found_on_url and act.source_url.split("#", 1)[0].rstrip("/") == act.found_on_url.split("#", 1)[0].rstrip("/"):
        return False  # in-page anchor, not an article
    if segments[-1] in NEWS_INDEX_SEGMENTS or any(seg in NON_ARTICLE_SEGMENTS for seg in segments):
        return False
    title = act.title.casefold().strip()
    if len(title) < 8 or title in LINK_TEXT_TITLES or NON_ARTICLE_TITLE.search(title):
        return False
    if PLACEHOLDER_TITLE.search(title) or CRIMINAL_MATTER.search(title):
        return False
    page_itself = bool(act.found_on_url) and act.source_url.split("#", 1)[0].rstrip("/") == act.found_on_url.split("#", 1)[0].rstrip("/")
    if page_itself and not date_from_url(act.source_url) and not has_path_word(parsed.path):
        return False  # an ordinary page carrying a publish date is not an article
    return True


# Leading "Publisert: 01.07.2026", "13.08.2026 |", "24 September 2026, 21:00 |" and a section
# word ("Nyheter", "News") that listing cards print before the actual headline.
TITLE_DATE_PREFIX = re.compile(
    r"^(?:(?:publisert|oppdatert|published|updated|dato|date)\s*:?\s*)?"
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\.?\s+(?:" + "|".join(sorted(MONTH_MAP, key=len, reverse=True)) + r")\.?\s+\d{4})"
    r"(?:,?\s*(?:kl\.?\s*)?\d{1,2}[:.]\d{2})?\s*[|·•–—-]?\s*",
    re.IGNORECASE,
)
TITLE_TIME_PREFIX = re.compile(r"^(?:kl\.?\s*)?\d{1,2}[:.]\d{2}\s*(?:\((?:CEST|CET|UTC|GMT|BST)\)|CEST|CET|UTC|GMT)?\s*[|·•–—-]?\s+(?=\S)", re.IGNORECASE)
TITLE_SECTION_PREFIX = re.compile(r"^(?:nyheter|nyhet|news|aktuelt|pressemelding|press release|blogg|blog|artikkel)\s*[|·:–—-]?\s+(?=\S)", re.IGNORECASE)


def clean_activity_title(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = re.sub(r"\s+", " ", str(title)).strip()
    cleaned = TITLE_DATE_PREFIX.sub("", cleaned)
    cleaned = TITLE_TIME_PREFIX.sub("", cleaned)
    cleaned = re.sub(r"^\s*\|?\s*regulatory information\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = TITLE_SECTION_PREFIX.sub("", cleaned)
    # trailing "13.04.2021 - Publisert av ..." bylines
    cleaned = re.sub(r"\s*\d{1,2}\.\d{1,2}\.\d{4}\s*[-–]?\s*(?:publisert|oppdatert|published).*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*[-–|]\s*(?:publisert|published) av .*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^[-–—•*|:/]+\s*", "", cleaned)
    cleaned = re.sub(r"\s*[-–—•*|:]+$", "", cleaned).strip()
    if not cleaned or len(cleaned) < 4:
        return None
    if cleaned.casefold() in GENERIC_NAV_TITLES:
        return None
    return cleaned[:300]


SITE_SUFFIX = re.compile(r"^(?P<title>.{8,}?)\s+[-–—|·]\s+(?P<site>[^-–—|·]{2,60})$")


def strip_site_suffix(title: str, site_root: str, name: str | None) -> str:
    """Drop a trailing site name ("Bedre sosial funksjon - Sunnaas sykehus HF" -> "Bedre sosial funksjon")."""
    match = SITE_SUFFIX.match(title or "")
    if not match:
        return title
    suffix = re.sub(r"[^a-z0-9]", "", " ".join(_tokens(match.group("site"))))
    markers = [token for token in _tokens(name) if len(token) >= 4] + ([site_root] if len(site_root or "") >= 3 else [])
    head, site = match.group("title").strip(), match.group("site").strip()
    # A site name is short and shorter than the headline; "Siste nytt - Sunnaas åpner nytt bygg" keeps its words.
    if len(site.split()) > 5 or len(head.split()) <= len(site.split()):
        return title
    return head if suffix and any(marker in suffix for marker in markers) else title


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
        act_url_for_date = urljoin(base_url, str(c.get("url") or base_url))
        activity_date = normalize_date_string(date_raw) or date_from_url(act_url_for_date)

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
    
    # Global page-level publication date from metadata
    page_meta_date = None
    meta_tag = soup.select_one('meta[property="article:published_time"], meta[name="publication_date"], meta[name="date"]')
    if meta_tag and meta_tag.get("content"):
        page_meta_date = normalize_date_string(meta_tag.get("content"))

    # Article or card containers
    selectors = [
        "article", ".news-item", ".nyhet-item", ".post-item",
        ".article-card", ".nyhetskort", ".press-release", ".event-item",
        ".aktuelt-item", ".blog-post", ".press-release-item", ".news-card",
        "li.news-item", "li.article", ".news-list-item"
    ]
    cards = soup.select(", ".join(selectors))

    # If no article containers, inspect linked news anchors
    if not cards:
        links = soup.select("a[href*='/nyheter/'], a[href*='/aktuelt/'], a[href*='/presse/'], a[href*='/news/'], a[href*='/artikler/'], a[href*='/media/'], a[href*='/newsroom/'], a[href*='/pressroom/'], a[href*='/press-releases/'], a[href*='/investors/']")
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

            # Date the link from its own text, or from its parent only when the parent holds no
            # other article links; a shared list wrapper would give every link the first date.
            link_text = link.get_text(" ", strip=True)
            parent = link.parent
            own_parent = parent is not None and len(parent.select("a[href]")) <= 2
            parent_text = parent.get_text(" ", strip=True) if own_parent else link_text
            activity_date = (
                extract_activity_date_from_text(link_text)
                or (extract_activity_date_from_text(parent_text) if own_parent else None)
                or date_from_url(full_url)
            )

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
        # The headline itself, not a link that wraps headline and teaser together.
        title_el = card.select_one("h1, h2, h3, h4, h5, .title, .headline") or card.select_one("a")
        if not title_el:
            continue
        title = clean_activity_title(title_el.get_text(" ", strip=True))
        if not title:
            continue

        # The card's URL is the headline's own link. A card holding the page's h1 is the page's
        # own article; its other links (tags, topics, related pages) are not its address.
        link_el = (
            (title_el if title_el.name == "a" and title_el.get("href") else None)
            or title_el.find_parent("a", href=True)
            or title_el.select_one("a[href]")
        )
        if link_el is None and title_el.name != "h1" and len({a.get("href") for a in card.select("a[href]")}) == 1:
            link_el = card.select_one("a[href]")
        item_url = urljoin(base_url, link_el.get("href")) if link_el else base_url

        card_text = card.get_text(" ", strip=True)

        # Date extraction: search <time> tags first, then text regex, then page meta
        time_el = card.select_one("time")
        activity_date = None
        if time_el:
            activity_date = normalize_date_string(time_el.get("datetime") or time_el.get_text(" ", strip=True))
        if not activity_date and item_url.split("#", 1)[0].rstrip("/") == base_url.split("#", 1)[0].rstrip("/"):
            # The page's own publish date only dates the page itself, never the cards listed on it.
            activity_date = page_meta_date
        if not activity_date:
            activity_date = extract_activity_date_from_text(card_text)
        if not activity_date:
            activity_date = date_from_url(item_url)

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


def child_link_count(html: str, url: str) -> int:
    """How many distinct pages below this page's own path it links to (/news/blog/design/<slug>)."""
    base = urlparse(url)
    prefix = base.path.rstrip("/") + "/"
    children = set()
    for anchor in BeautifulSoup(html or "", "lxml").select("a[href]"):
        target = urlparse(urljoin(url, str(anchor.get("href") or "")))
        if target.netloc == base.netloc and target.path.startswith(prefix) and target.path.rstrip("/") != base.path.rstrip("/"):
            children.add(target.path.rstrip("/"))
    return len(children)


def _activities_from_feed(profile: dict[str, Any], page: dict[str, Any]) -> list[ActivityRecord]:
    """Articles listed in the site's own RSS/Atom feed, each with the feed's publication date."""
    org_nr = str(profile.get("organisation_number") or "")
    records: list[ActivityRecord] = []
    for item in page.get("feed_items") or []:
        title = clean_activity_title(item.get("title"))
        if not title or not item.get("published"):
            continue
        id_assessment = verify_activity_identity(profile, {"title": title}, item["url"])
        if not id_assessment["verified"]:
            continue
        content_sha = hashlib.sha256(f"{title}|{item['url']}|{item['published']}".encode("utf-8")).hexdigest()
        records.append(ActivityRecord(
            activity_id=f"act-{org_nr}-{content_sha[:12]}",
            company_orgnr=org_nr,
            activity_type=classify_activity_type(title, ""),
            title=title,
            description=None,
            activity_date=item["published"],
            source_url=item["url"],
            retrieved_at=utc_now(),
            content_sha256=content_sha,
            identity_assessment={**id_assessment, "method": "verified_site_news_feed"},
            found_on_url=page.get("url"),
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

    org_nr = str(profile.get("organisation_number") or "")
    for page in pages:
        p_url = page.get("url") or final_url
        if page.get("kind") == "feed":
            for act in _activities_from_feed(profile, page):
                all_activities.setdefault(act.activity_id, act)
            continue
        p_html = page.get("html") or ""
        p_text = page.get("main_text_excerpt") or ""

        if not p_html:
            p_html = f"<html><head><title>{page.get('title', '')}</title></head><body>{p_text}</body></html>"

        # 1. Primary: JSON-LD Article/Event
        jsonld_activities = [replace(act, found_on_url=p_url) for act in extract_activity_from_jsonld(p_html, p_url, profile)]
        for act in jsonld_activities:
            if act.activity_id not in all_activities:
                all_activities[act.activity_id] = act

        # 2. Fallback: HTML cards / links
        p_path = urlparse(p_url).path.casefold()
        is_activity_url = has_path_word(p_path, ACTIVITY_PATH_WORD)
        html_activities: list[ActivityRecord] = []
        if is_activity_url or not jsonld_activities:
            html_activities = [replace(act, found_on_url=p_url) for act in extract_activity_from_html_articles(p_html, p_url, profile)]
            for act in html_activities:
                if act.activity_id not in all_activities:
                    all_activities[act.activity_id] = act

        # 3. The page itself as one article: a page the sitemap listed as an article, or an
        #    article-like page with no cards of its own. Its date must be one the page states
        #    about itself (structured data, publish meta, "Publisert:"), or the URL's date.
        from_sitemap = page.get("discovered_via") == "sitemap"
        if not (from_sitemap or (is_activity_url and not html_activities)):
            continue
        if child_link_count(p_html, p_url) >= 2:
            continue  # it links to pages below itself: a section or category index, not one article
        p_title = clean_activity_title(page.get("headline") or page.get("title"))
        if not p_title or (len(p_text.strip()) <= 40 and not from_sitemap):
            continue
        act_date = page.get("published_date") or date_from_url(p_url) or (None if from_sitemap else extract_activity_date_from_text(p_text[:400]))
        if act_date and act_date > datetime.now(timezone.utc).date().isoformat():
            act_date = None  # a page cannot have been published in the future: that is an event date
        id_assessment = verify_activity_identity(profile, {"title": p_title, "description": p_text}, p_url)
        if not id_assessment["verified"]:
            continue
        content_sha = hashlib.sha256(f"{p_title}|{p_url}|{act_date}".encode("utf-8")).hexdigest()
        act_id = f"act-{org_nr}-{content_sha[:12]}"
        all_activities.setdefault(act_id, ActivityRecord(
            activity_id=act_id,
            company_orgnr=org_nr,
            activity_type=classify_activity_type(p_title, p_text),
            title=p_title,
            description=p_text[:500],
            activity_date=act_date,
            source_url=p_url,
            retrieved_at=utc_now(),
            content_sha256=content_sha,
            identity_assessment=id_assessment,
            found_on_url=p_url,
        ))

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


# Newspapers, magazines, broadcasters and news agencies (NACE 58.13, 58.14, 60.1, 60.2, 63.91):
# the articles on their sites are their editorial product, not news about the company.
NEWS_PUBLISHER_CODES = ("58.13", "58.14", "60.1", "60.2", "63.91")


def is_news_publisher(profile: dict[str, Any]) -> bool:
    return str(profile.get("industry_code") or "").startswith(NEWS_PUBLISHER_CODES)


def extract_activity_observations(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert verified activity records into external footprint observations."""
    org = str(profile.get("organisation_number") or "")
    website = profile.get("evidence", {}).get("website", {})
    if not org or website.get("status") != "available" or is_news_publisher(profile):
        return []

    activities = extract_activity_from_crawl_material(profile, website)
    # Where a listing card and the article page itself describe the same URL, the article
    # page's own title and date win.
    activities.sort(key=lambda act: 0 if act.found_on_url and act.source_url.split("#", 1)[0].rstrip("/") == act.found_on_url.split("#", 1)[0].rstrip("/") else 1)
    observations: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    from .identity import specific_name_tokens, within_site_scope
    web_value = website.get("value") or {}
    scope = (web_value.get("identity_assessment") or {}).get("site_scope")
    site_root = (urlparse(web_value.get("final_url") or "").hostname or "").removeprefix("www.").split(".")[0]
    for act in activities:
        stripped = strip_site_suffix(act.title, site_root, profile.get("name"))
        if stripped != act.title and len(stripped) >= 8:
            act = replace(act, title=stripped)
        if not is_publishable_news(act):
            continue
        if not within_site_scope(act.source_url, web_value.get("final_url"), scope):
            specific = specific_name_tokens(profile.get("name"), urlparse(web_value.get("final_url") or "").hostname or "")
            title_compact = re.sub(r"[^a-z0-9]", "", " ".join(_tokens(act.title)))
            if not specific or not all(token in title_compact for token in specific):
                continue  # article belongs to the wider site, not this company's section
        clean_url = re.sub(r"(?<!:)/{2,}", "/", act.source_url)
        if clean_url != act.source_url:
            act = replace(act, source_url=clean_url)
        canonical = clean_url.split("#", 1)[0].rstrip("/")
        title_key = f"{act.title.casefold()}|{act.activity_date}"
        if canonical in seen_urls or title_key in seen_urls:
            continue
        seen_urls.update({canonical, title_key})
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
            "found_on_url": act.found_on_url,
            "metrics": {
                "activity_type": act.activity_type,
                "title": act.title,
                "activity_date": act.activity_date,
                "published_at": act.activity_date,
            },
        }
        observations.append(obs)

    # Several one- or two-word "posts" published on the same day ("Forretningsplan",
    # "Foredrag", "Styreverv") are a site's service pages set up as posts, not news.
    per_day = collections.Counter(obs["metrics"]["activity_date"] for obs in observations)
    return [
        obs for obs in observations
        if not (per_day[obs["metrics"]["activity_date"]] >= 3 and len(str(obs["metrics"]["title"]).split()) <= 2)
    ]
