from __future__ import annotations

import gzip
import io
import json
import ipaddress
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup
import extruct
import tldextract
import trafilatura

from .evidence import evidence

USER_AGENT = "builderr-signalpost-poc/0.1 (+https://builderr.ai)"
SOCIAL_HOSTS = {
    "linkedin.com": "linkedin",
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "x.com": "x",
    "twitter.com": "x",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "tiktok.com": "tiktok",
}


def assert_public_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("Only public HTTP(S) URLs are allowed")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("Local hosts are blocked")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise UnresolvableHost("Hostname did not resolve") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("Private, loopback, link-local, multicast, and reserved addresses are blocked")


class UnresolvableHost(ValueError):
    """The hostname has no DNS record: the site does not exist, nothing refused us."""


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        assert_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


SAFE_OPENER = urllib.request.build_opener(SafeRedirectHandler())


def normalize_homepage(value: str | None) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", "", ""))


def _registered_domain(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    ext = tldextract.extract(parsed.hostname or "")
    return ext.top_domain_under_public_suffix


_ROBOTS_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_ROBOTS_LOCK = threading.Lock()


def _robots_key(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}".casefold()


def robots_cached(url: str) -> bool:
    """True when robots.txt for this host was already fetched, so checking it costs no request."""
    with _ROBOTS_LOCK:
        return _robots_key(url) in _ROBOTS_CACHE


def robots_sitemaps(url: str) -> list[str]:
    """Sitemap URLs the host declares in robots.txt (empty when none or not fetched yet)."""
    with _ROBOTS_LOCK:
        parser = _ROBOTS_CACHE.get(_robots_key(url))
    try:
        return list(parser.site_maps() or []) if parser else []
    except Exception:
        return []


def _robots_allowed(url: str, timeout: float) -> bool:
    """Check robots.txt, fetching it once per scheme+host for the whole run."""
    assert_public_url(url)
    parsed = urllib.parse.urlparse(url)
    key = _robots_key(url)
    with _ROBOTS_LOCK:
        cached = key in _ROBOTS_CACHE
        parser = _ROBOTS_CACHE.get(key)
    if not cached:
        robots_url = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))
        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(robots_url)
        try:
            request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
            with SAFE_OPENER.open(request, timeout=timeout) as response:
                parser.parse(response.read().decode("utf-8", errors="replace").splitlines())
        except Exception:
            # An unavailable robots file is not permission to ignore explicit site terms; callers retain
            # the URL and can route uncertain domains to review. For this bounded homepage POC, allow one
            # ordinary GET when robots.txt is absent rather than crawl deeper.
            parser = None
        with _ROBOTS_LOCK:
            _ROBOTS_CACHE[key] = parser
    return True if parser is None else parser.can_fetch(USER_AGENT, url)


def _social_links(base_url: str, soup: BeautifulSoup) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}
    candidates = [str(node.get("href") or "") for node in soup.select("a[href]")]
    candidates.extend(str(node.get("data-href") or "") for node in soup.select("[data-href]"))
    candidates.extend(str(node.get("src") or "") for node in soup.select("iframe[src]"))
    for candidate in candidates:
        url = urllib.parse.urljoin(base_url, candidate)
        parsed_candidate = urllib.parse.urlparse(url)
        if (parsed_candidate.hostname or "").casefold().removeprefix("www.") == "facebook.com" and parsed_candidate.path.startswith("/plugins/"):
            embedded = urllib.parse.parse_qs(parsed_candidate.query).get("href", [])
            if embedded:
                url = embedded[0]
        normalized = normalize_social_url(url)
        if not normalized:
            continue
        found[(normalized["platform"], normalized["url"])] = {**normalized, "found_on": base_url}
    return sorted(found.values(), key=lambda item: (item["platform"], item["url"]))


def structured_social_links(value: Any, found_on: str | None = None) -> list[dict[str, str]]:
    """Profiles a page declares as its organisation's own through JSON-LD ``sameAs``."""
    found: dict[tuple[str, str], dict[str, str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            same_as = node.get("sameAs")
            urls = same_as if isinstance(same_as, list) else [same_as]
            for raw in urls:
                if not isinstance(raw, str):
                    continue
                normalized = normalize_social_url(raw.strip())
                if normalized:
                    found[(normalized["platform"], normalized["url"])] = {**normalized, "found_on": found_on or "", "via": "json_ld_same_as"}
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return sorted(found.values(), key=lambda item: (item["platform"], item["url"]))


def normalize_social_url(url: str) -> dict[str, str] | None:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower().removeprefix("www.")
    platform = next((label for domain, label in SOCIAL_HOSTS.items() if host == domain or host.endswith("." + domain)), None)
    if not platform:
        return None
    parts = [part.strip() for part in parsed.path.split("/") if part.strip()]
    lowered = [part.casefold() for part in parts]
    rejected_first = {
        "facebook": {"sharer", "sharer.php", "share.php", "share", "dialog", "policy.php", "privacy", "events", "groups", "plugins", "watch", "photo.php", "story.php", "permalink.php", "hashtag"},
        "instagram": {"p", "reel", "reels", "stories", "explore"},
        "x": {"intent", "share", "home", "search", "i"},
    }
    if not parts or lowered[0] in rejected_first.get(platform, set()):
        return None
    if platform == "facebook" and lowered[0] == "profile.php":
        return None
    if platform == "linkedin" and (lowered[0] not in {"company", "school", "showcase"} or len(parts) < 2):
        return None
    if platform == "youtube" and lowered[0] not in {"channel", "user", "c"} and not parts[0].startswith("@"):
        return None
    if host == "youtu.be":
        return None
    if platform == "tiktok" and not parts[0].startswith("@"):
        return None
    if platform == "x" and len(parts) != 1:
        return None
    canonical_host = {
        "linkedin": "linkedin.com",
        "facebook": "facebook.com",
        "instagram": "instagram.com",
        "x": "x.com",
        "youtube": "youtube.com",
        "tiktok": "tiktok.com",
    }[platform]
    if platform == "linkedin":
        parts = parts[:2]
    elif platform == "youtube":
        parts = parts[:1] if parts[0].startswith("@") else parts[:2]
    return {"platform": platform, "url": f"https://{canonical_host}/{'/'.join(parts)}"}


# Crawl targets by kind, in priority order. Each kind gets a share of the page budget so a
# site with many "about" links still has its careers and news pages read.
LINK_CATEGORIES: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("careers", ("karriere", "stillinger", "ledige-stillinger", "jobb", "jobs", "career", "vacancies",
                 "rekruttering", "bli-med-pa-laget", "jobb-hos-oss", "work-with-us", "join-us"), 2),
    ("news", ("nyheter", "nyhet", "aktuelt", "news", "presse", "press", "pressemeldinger", "artikler",
              "blogg", "blog", "nyhetsrom", "newsroom", "pressroom", "media", "kunngjoringer", "announcements"), 2),
    ("about", ("om-oss", "om_oss", "about", "ledelse", "management", "team", "people"), 2),
    ("contact", ("kontakt", "contact"), 1),
    ("investors", ("investors", "investor", "investorer"), 1),
    ("locations", ("locations", "lokasjoner", "avdelinger", "butikker"), 1),
    ("events", ("events", "arrangementer"), 1),
)
NOT_A_PAGE = re.compile(r"\.(?:pdf|jpe?g|png|gif|svg|webp|zip|docx?|xlsx?|pptx?|mp4|mp3)$", re.IGNORECASE)
NEWSLETTER = ("newsletter", "nyhetsbrev")


def _priority_links(base_url: str, soup: BeautifulSoup, limit: int = 8) -> list[str]:
    """Same-site pages worth reading: careers, news, about, contact, investors, locations, events.

    Index pages (shorter paths) come before sub-pages, and every kind gets its share of the
    budget before any kind gets a second page.
    """
    base = urllib.parse.urlparse(base_url)
    base_host = (base.hostname or "").casefold().removeprefix("www.")
    base_reg = _registered_domain(base_url)
    best: dict[str, tuple[int, tuple[int, int, int]]] = {}
    for anchor in soup.select("a[href]"):
        href = str(anchor.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or NOT_A_PAGE.search(parsed.path):
            continue
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        same_host = host == base_host
        # "askvvs.no/kontakt" linked from www.askvvs.no: fetch it on the host that answered.
        netloc = base.netloc if same_host else parsed.netloc
        clean = urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path or "/", "", "", ""))
        if clean.rstrip("/") == base_url.rstrip("/"):
            continue
        if not same_host and _registered_domain(url) != base_reg:
            continue
        path = parsed.path.casefold()
        text = anchor.get_text(" ", strip=True).casefold()
        if any(word in path or word in text for word in NEWSLETTER):
            continue
        subdomain = "" if same_host else host.split(".")[0]
        for index, (_, terms, _) in enumerate(LINK_CATEGORIES):
            in_path = any(term in path or (subdomain and term in subdomain) for term in terms)
            in_text = any(term.replace("-", " ").replace("_", " ") in text for term in terms)
            if in_path or in_text:
                depth = len([segment for segment in path.split("/") if segment])
                rank = (index, (0 if in_path else 1, depth, len(path)))
                if clean not in best or rank < best[clean]:
                    best[clean] = rank
                break

    by_kind = {index: sorted((url for url, rank in best.items() if rank[0] == index), key=lambda url: (best[url][1], url)) for index in range(len(LINK_CATEGORIES))}
    chosen: list[str] = []
    for round_ in range(max(quota for _, _, quota in LINK_CATEGORIES)):
        for index, (_, _, quota) in enumerate(LINK_CATEGORIES):
            if round_ < quota and len(by_kind[index]) > round_:
                chosen.append(by_kind[index][round_])
    chosen.extend(url for url in sorted(best, key=lambda url: (best[url], url)) if url not in chosen)
    return chosen[:limit]


def safe_decompress_body(raw: bytes, encoding: str = "", max_bytes: int = 2_000_000) -> tuple[bytes, str | None]:
    """Safely decompress gzip or deflate HTTP payloads with streaming byte limit enforcement."""
    if not raw:
        return raw, None
    enc = encoding.lower()
    is_gzip = (len(raw) >= 2 and raw[:2] == b"\x1f\x8b") or "gzip" in enc
    is_deflate = "deflate" in enc
    if not (is_gzip or is_deflate):
        return raw, None
    try:
        if is_gzip:
            buf = io.BytesIO(raw)
            with gzip.GzipFile(fileobj=buf) as gz:
                decompressed = gz.read(max_bytes + 1)
                return decompressed, None
        elif is_deflate:
            # Handles raw deflate (-MAX_WBITS) as well as zlib-wrapped deflate (MAX_WBITS)
            try:
                decompressed = zlib.decompress(raw, -zlib.MAX_WBITS, max_bytes + 1)
            except zlib.error:
                decompressed = zlib.decompress(raw, zlib.MAX_WBITS, max_bytes + 1)
            return decompressed, None
    except Exception as exc:
        return raw, f"decompression_error: {type(exc).__name__}"
    return raw, None


FOOTER_SELECTORS = "footer, address, [class*=footer], [id*=footer], [class*=kontakt], [class*=contact], [id*=contact]"


def _footer_identity_text(soup: BeautifulSoup) -> str:
    """Text of footer/contact blocks, where Norwegian sites usually print org.nr, address and phone.

    The main-text extractor drops these blocks as boilerplate, so without this the identity
    gate never sees the strongest evidence a site offers.
    """
    parts = []
    for element in soup.select(FOOTER_SELECTORS)[:12]:
        text = element.get_text(" ", strip=True)
        if text:
            parts.append(text)
    return " ".join(dict.fromkeys(parts))[:3000]


PUBLISHED_META = (
    'meta[property="article:published_time"]', 'meta[property="og:article:published_time"]',
    'meta[name="article:published_time"]', 'meta[itemprop="datePublished"]', 'meta[name="pubdate"]',
    'meta[name="publishdate"]', 'meta[name="publish_date"]', 'meta[name="publication_date"]',
    'meta[name="dc.date.issued"]', 'meta[name="DC.date.issued"]', 'meta[name="dcterms.created"]', 'meta[name="date"]',
)
PUBLISHED_LABEL = re.compile(
    r"(?:publisert|published|posted|lagt ut|pressemelding)\s*:?\s*(?:den\s+|on\s+)?"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\.?\s+[a-zæøå]+\.?\s+\d{4}|[a-z]+\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)
PUBLISHED_JSON_KEY = re.compile(r'"(?:datePublished|publishDate|publishedDate|publicationDate|publishedAt|published_at|date)"\s*:\s*"([^"]{8,32})"')


def _jsonld_date_published(structured: dict[str, Any]) -> str | None:
    from .jobs import normalize_date_string

    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("datePublished"):
                value = normalize_date_string(str(node["datePublished"]))
                if value:
                    found.append(value)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(structured.get("json-ld") or [])
    return found[0] if found else None


def page_publication_date(html: str, soup: BeautifulSoup, structured: dict[str, Any]) -> tuple[str | None, str | None]:
    """The page's own publication date and where it came from, or (None, None).

    Only dates the page states about itself count: structured data, publish meta tags, a lone
    <time> element, a "Publisert:" label, or a single publish date in the page's own data.
    A date merely mentioned in the text is not the publication date.
    """
    from .jobs import normalize_date_string

    value = _jsonld_date_published(structured)
    if value:
        return value, "json_ld_date_published"
    for selector in PUBLISHED_META:
        tag = soup.select_one(selector)
        value = normalize_date_string(str(tag.get("content") or "")) if tag else None
        if value:
            return value, "meta_published_time"
    scoped = soup.select("article time[datetime], main time[datetime], header time[datetime]")
    times = scoped or soup.select("time[datetime]")
    if len(times) == 1 or scoped:
        value = normalize_date_string(str(times[0].get("datetime") or ""))
        if value:
            return value, "time_element"
    match = PUBLISHED_LABEL.search(soup.get_text(" ", strip=True)[:20000])
    if match:
        value = normalize_date_string(match.group(1)) or _english_date(match.group(1))
        if value:
            return value, "published_label"
    embedded = {normalize_date_string(raw) for raw in PUBLISHED_JSON_KEY.findall(html)} - {None}
    if len(embedded) == 1:
        return embedded.pop(), "embedded_page_data"
    return None, None


def _english_date(text: str) -> str | None:
    """'September 22, 2025' -> '2025-09-22'."""
    from .jobs import MONTH_MAP

    match = re.match(r"([a-z]+)\s+(\d{1,2}),?\s+(\d{4})", text.strip(), re.IGNORECASE)
    if not match:
        return None
    month = MONTH_MAP.get(match.group(1).casefold())
    day, year = int(match.group(2)), int(match.group(3))
    return f"{year:04d}-{month}-{day:02d}" if month and 1 <= day <= 31 and 2000 <= year <= 2100 else None


def _headline(soup: BeautifulSoup) -> str:
    tag = soup.select_one('meta[property="og:title"]')
    if tag and str(tag.get("content") or "").strip():
        return str(tag["content"]).strip()[:300]
    h1 = soup.select_one("h1")
    return h1.get_text(" ", strip=True)[:300] if h1 else ""


def _job_board_links(base_url: str, soup: BeautifulSoup) -> list[dict[str, str]]:
    """Links and embeds that open the company's applicant-tracking job board.

    A bare recruiter homepage (finn.no, nav.no) or a LinkedIn company page is not a job board.
    """
    from .jobs import job_board_url

    found: dict[str, dict[str, str]] = {}
    for node in soup.select("a[href], iframe[src], script[src]"):
        raw = str(node.get("href") or node.get("src") or "").strip()
        if not raw or raw.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url = urllib.parse.urljoin(base_url, raw)
        board = job_board_url(url)
        if board and board not in found:
            found[board] = {
                "url": board,
                "text": node.get_text(" ", strip=True)[:160] if node.name == "a" else "",
                "kind": "link" if node.name == "a" else "embed",
            }
    return list(found.values())[:10]


def _feed_links(base_url: str, soup: BeautifulSoup) -> list[str]:
    """RSS/Atom feeds the page advertises on its own registered domain (comment feeds excluded)."""
    feeds: list[str] = []
    for tag in soup.select('link[rel~="alternate"][href]'):
        kind = str(tag.get("type") or "").casefold()
        if "rss" not in kind and "atom" not in kind:
            continue
        url = urllib.parse.urljoin(base_url, str(tag["href"]))
        label = (str(tag.get("title") or "") + " " + url).casefold()
        if "comment" in label or "kommentar" in label or _registered_domain(url) != _registered_domain(base_url):
            continue
        if url not in feeds:
            feeds.append(url)
    return feeds[:3]


def _page_signals(html: str, soup: BeautifulSoup, structured: dict[str, Any], final_url: str) -> dict[str, Any]:
    """Facts read from the full page before it is cut down for storage."""
    published, method = page_publication_date(html, soup, structured)
    return {
        "published_date": published,
        "published_date_method": method,
        "headline": _headline(soup),
        "job_board_links": _job_board_links(final_url, soup),
    }


def _bounded_html(soup: BeautifulSoup) -> str:
    """Return a highly minimal HTML fragment preserving only structural layout and date/identity metadata."""
    for tag in soup.find_all(["style", "svg", "nav", "footer", "form", "iframe", "canvas", "img", "video", "audio", "noscript"]):
        tag.decompose()
    for tag in soup.find_all("script"):
        if tag.get("type") != "application/ld+json":
            tag.decompose()
    
    allowed_attrs = {"class", "id", "href", "datetime", "property", "content", "name", "type"}
    for tag in soup.find_all(True):
        if tag.name != "script":
            tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed_attrs}
    
    return str(soup)[:150000]


def _decode(raw: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w-]+)", content_type or "", re.IGNORECASE)
    try:
        return raw.decode(match.group(1) if match else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _fetch_secondary_page(url: str, *, homepage_domain: str, timeout: float, max_bytes: int) -> tuple[dict[str, Any] | None, list[dict[str, str]], int, int, int, str | None]:
    robots_requests = 0 if robots_cached(url) else 1
    try:
        if not _robots_allowed(url, timeout):
            return None, [], robots_requests, 0, 0, "robots.txt disallows page"
    except ValueError as exc:  # the page's host does not resolve or is not public: skip the page, keep the site
        return None, [], 0, 0, 0, f"{type(exc).__name__}: {str(exc)[:120]}"
    requests = robots_requests + 1
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with SAFE_OPENER.open(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            encoding = response.headers.get("content-encoding", "")
            raw = response.read(max_bytes + 1)
            elapsed = int((time.monotonic() - started) * 1000)
            final_url = response.geturl()
            if len(raw) > max_bytes or "html" not in content_type.lower():
                return None, [], requests, len(raw), elapsed, "unsupported or oversized page"
            if _registered_domain(final_url) != homepage_domain:
                return None, [], requests, len(raw), elapsed, "redirected outside registered domain"
        decompressed_raw, decomp_err = safe_decompress_body(raw, encoding=encoding, max_bytes=max_bytes)
        if len(decompressed_raw) > max_bytes:
            return None, [], requests, len(raw), elapsed, "decompressed page exceeds byte limit"
        page_html = _decode(decompressed_raw, content_type)
        page_soup = BeautifulSoup(page_html, "lxml")
        structured = extruct.extract(page_html, base_url=final_url, syntaxes=["json-ld", "microdata", "opengraph"])
        page_text = trafilatura.extract(page_html, url=final_url, include_links=False, include_tables=False, favor_precision=True) or ""
        meta_identity = " ".join(filter(None, [_extract_metadata_identity_text(structured, page_soup), _footer_identity_text(page_soup)]))
        # Read links and page facts before _bounded_html strips nav, footer, scripts and iframes.
        social = _social_links(final_url, page_soup) + structured_social_links(structured.get("json-ld"), final_url)
        page = {
            "url": final_url,
            "title": page_soup.title.get_text(" ", strip=True)[:500] if page_soup.title else "",
            "main_text_excerpt": page_text[:5000],
            "identity_text_excerpt": meta_identity,
            "content_sha256": __import__("hashlib").sha256(decompressed_raw).hexdigest(),
            **_page_signals(page_html, page_soup, structured, final_url),
        }
        page["html"] = _bounded_html(page_soup)
        page["_raw"] = decompressed_raw
        return page, social, requests, len(raw), elapsed, None
    except Exception as exc:
        return None, [], requests, 0, int((time.monotonic() - started) * 1000), f"{type(exc).__name__}: {str(exc)[:120]}"


def fetch_site_page(url: str, *, homepage_domain: str, timeout: float = 15.0, max_bytes: int = 1_000_000) -> tuple[dict[str, Any] | None, list[dict[str, str]], dict[str, Any]]:
    """Fetch one more page of an already verified site (robots.txt respected, same registered domain)."""
    page, social, requests, size, elapsed, error = _fetch_secondary_page(url, homepage_domain=homepage_domain, timeout=timeout, max_bytes=max_bytes)
    return page, social, {"requests": requests, "bytes": size, "latencies_ms": [elapsed] if elapsed else [], "error": error}


def _jsonld_organisations(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            kind = value.get("@type")
            kinds = set(kind if isinstance(kind, list) else [kind])
            if kinds & {"Organization", "Corporation", "LocalBusiness", "Store", "Restaurant"}:
                values.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(metadata.get("json-ld", []))
    return values[:20]


def _extract_metadata_identity_text(structured: dict[str, Any], soup: BeautifulSoup) -> str:
    """Extract authoritative brand & identity text from structured metadata (OpenGraph & JSON-LD).
    
    Used when HTML body is minimal (password page, JS shell) but site declares its identity in headers.
    """
    parts: list[str] = []
    # 1. OpenGraph site_name and title
    og_items = structured.get("opengraph") or []
    for item in og_items:
        props = dict(item.get("properties") or [])
        if props.get("og:site_name"):
            parts.append(str(props["og:site_name"]).strip())
        if props.get("og:title"):
            parts.append(str(props["og:title"]).strip())
        if props.get("og:description"):
            parts.append(str(props["og:description"]).strip())
            
    # 2. Direct meta tags fallback
    for selector in ('meta[property="og:site_name"]', 'meta[name="application-name"]'):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            parts.append(str(tag["content"]).strip())
            
    # 3. JSON-LD organization names
    for org in _jsonld_organisations(structured):
        for k in ("name", "legalName", "alternateName"):
            val = org.get(k)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())

    return " ".join(dict.fromkeys(parts))[:2000]


def _extraction_state(text: str, soup: BeautifulSoup) -> str:
    return "js_fallback_candidate" if len(text.strip()) < 100 and len(soup.select("script[src]")) >= 2 else "static_complete"


def fetch_website(url: str | None, *, timeout: float = 15.0, max_bytes: int = 2_000_000) -> tuple[dict[str, Any], dict[str, Any]]:
    supplied_url = str(url or "").strip()
    supplied_scheme = bool(re.match(r"^https?://", supplied_url, re.I))
    normalized = normalize_homepage(url)
    if not normalized:
        return evidence("website", "not_found", "registry_linked_company_website", "https://data.brreg.no/enhetsregisteret/api/enheter", note="No valid registry website URL"), {"requests": 0, "bytes": 0, "latencies_ms": []}
    try:
        assert_public_url(normalized)
    except UnresolvableHost:
        host = urllib.parse.urlparse(normalized).hostname or ""
        if not host.startswith("www."):
            # Many Norwegian sites only answer on the www. name.
            www_url = normalized.replace(f"://{host}", f"://www.{host}", 1)
            try:
                assert_public_url(www_url)
            except ValueError:
                pass
            else:
                return fetch_website(www_url, timeout=timeout, max_bytes=max_bytes)
        return evidence("website", "not_found", "registry_linked_company_website", normalized, note="Domain does not resolve (no DNS record)"), {"requests": 0, "bytes": 0, "latencies_ms": []}
    except ValueError as exc:
        return evidence("website", "blocked", "registry_linked_company_website", normalized, note=str(exc)), {"requests": 0, "bytes": 0, "latencies_ms": []}
    if not _robots_allowed(normalized, timeout):
        return evidence("website", "blocked", "registry_linked_company_website", normalized, note="robots.txt disallows this user agent"), {"requests": 1, "bytes": 0, "latencies_ms": []}
    started = time.monotonic()
    request = urllib.request.Request(normalized, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with SAFE_OPENER.open(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            encoding = response.headers.get("content-encoding", "")
            raw = response.read(max_bytes + 1)
            elapsed = int((time.monotonic() - started) * 1000)
            if len(raw) > max_bytes:
                return evidence("website", "source_error", "registry_linked_company_website", normalized, note="Homepage exceeds byte limit"), {"requests": 2, "bytes": len(raw), "latencies_ms": [elapsed]}
            if "html" not in content_type.lower():
                return evidence("website", "source_error", "registry_linked_company_website", normalized, note=f"Unsupported content type: {content_type}"), {"requests": 2, "bytes": len(raw), "latencies_ms": [elapsed]}
            final_url = response.geturl()
            assert_public_url(final_url)
        decompressed_raw, decomp_err = safe_decompress_body(raw, encoding=encoding, max_bytes=max_bytes)
        if len(decompressed_raw) > max_bytes:
            return evidence("website", "source_error", "registry_linked_company_website", normalized, note="Decompressed homepage exceeds byte limit"), {"requests": 2, "bytes": len(raw), "latencies_ms": [elapsed]}
        html = _decode(decompressed_raw, content_type)
        soup = BeautifulSoup(html, "lxml")
        structured = extruct.extract(html, base_url=final_url, syntaxes=["json-ld", "microdata", "opengraph"])
        text = trafilatura.extract(html, url=final_url, include_links=False, include_tables=False, favor_precision=True) or ""
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        description_tag = soup.select_one('meta[name="description"], meta[property="og:description"]')
        description = str(description_tag.get("content") or "").strip() if description_tag else ""
        meta_identity = " ".join(filter(None, [_extract_metadata_identity_text(structured, soup), _footer_identity_text(soup)]))
        value = {
            "requested_url": normalized,
            "final_url": final_url,
            "registered_domain": _registered_domain(final_url),
            "title": title[:500],
            "description": description[:2000],
            "main_text_excerpt": text[:5000],
            "identity_text_excerpt": meta_identity,
            "social_links": _social_links(final_url, soup) + structured_social_links(structured.get("json-ld"), final_url),
            "feed_links": _feed_links(final_url, soup),
            "wordpress": "/wp-content/" in html or "/wp-includes/" in html,
            "structured_organisations": _jsonld_organisations(structured),
            "content_sha256": __import__("hashlib").sha256(raw).hexdigest(),
            "extraction_state": _extraction_state(text, soup),
        }
        # Read links and page facts before _bounded_html strips nav, footer, scripts and iframes.
        crawl_targets = _priority_links(final_url, soup)
        homepage = {"url": final_url, "title": title[:500], "main_text_excerpt": text[:5000], "identity_text_excerpt": meta_identity, "content_sha256": value["content_sha256"], **_page_signals(html, soup, structured, final_url)}
        homepage["html"] = _bounded_html(soup)
        homepage["_raw"] = decompressed_raw
        pages = [homepage]
        social = value["social_links"]
        crawl_errors = []
        requests = 2
        bytes_received = len(raw)
        page_latencies = [elapsed]
        homepage_domain = value["registered_domain"]
        for page_url in crawl_targets:
            page, page_social, page_requests, page_bytes, page_elapsed, page_error = _fetch_secondary_page(
                page_url,
                homepage_domain=homepage_domain,
                timeout=timeout,
                max_bytes=min(max_bytes, 1_000_000),
            )
            requests += page_requests
            bytes_received += page_bytes
            if page_elapsed:
                page_latencies.append(page_elapsed)
            if page:
                pages.append(page)
                social.extend(page_social)
            elif page_error:
                crawl_errors.append({"url": page_url, "error": page_error})
        value["pages"] = pages
        value["social_links"] = list({(item["platform"], item["url"]): item for item in social}.values())
        value["crawl_errors"] = crawl_errors
        return evidence("website", "available", "registry_linked_company_website", final_url, value=value, note="Company-controlled claim layer; not an official registry fact", content_sha256=value["content_sha256"]), {"requests": requests, "bytes": bytes_received, "latencies_ms": page_latencies}
    except urllib.error.HTTPError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        status = "not_found" if exc.code in {404, 410} else "blocked" if exc.code in {401, 403, 429, 451} else "source_error"
        return evidence("website", status, "registry_linked_company_website", normalized, note=f"HTTP {exc.code}"), {"requests": 2, "bytes": 0, "latencies_ms": [elapsed]}
    except urllib.error.URLError as exc:
        if not supplied_scheme and normalized.startswith("https://"):
            first_elapsed = int((time.monotonic() - started) * 1000)
            record, metrics = fetch_website("http://" + supplied_url, timeout=timeout, max_bytes=max_bytes)
            metrics["requests"] += 2
            metrics["latencies_ms"].insert(0, first_elapsed)
            return record, metrics
        elapsed = int((time.monotonic() - started) * 1000)
        return evidence("website", "source_error", "registry_linked_company_website", normalized, note=f"URLError: {str(exc.reason)[:180]}"), {"requests": 2, "bytes": 0, "latencies_ms": [elapsed]}
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        return evidence("website", "source_error", "registry_linked_company_website", normalized, note=f"{type(exc).__name__}: {str(exc)[:180]}"), {"requests": 2, "bytes": 0, "latencies_ms": [elapsed]}
