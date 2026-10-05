"""Deeper reading of a verified company website: its sitemap and its news feed.

Runs only after the identity gate has tied the site to the company. A homepage crawl reaches
index pages; individual articles often sit several levels deeper (a hospital's research unit
news under /fag-og-forskning/.../nyheter-rkr/). The site's own sitemap lists them, and an
RSS/Atom feed lists recent posts with their publication dates. Every article read here is
fetched from the company's own registered domain, with robots.txt respected.
"""
from __future__ import annotations

import email.utils
import hashlib
import html as html_lib
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

from bs4 import BeautifulSoup

from .activity import NEWS_INDEX_SEGMENTS, NON_ARTICLE_SEGMENTS, date_from_url
from .identity import within_site_scope
from .jobs import CAREER_INDEX_SEGMENTS, normalize_date_string
from .website import (
    SAFE_OPENER,
    USER_AGENT,
    _registered_domain,
    _robots_allowed,
    fetch_site_page,
    robots_cached,
    robots_sitemaps,
    safe_decompress_body,
)

NEWS_SEGMENT = re.compile(
    r"(?:^|-)(?:nyhet|nyheter|news|aktuelt|artikkel|artikler|article|articles|blogg?|presse?|pressemelding(?:er)?|"
    r"press-releases?|siste-nytt|kunngjoring(?:er)?|newsroom|pressroom)(?:-|$)"
)
OTHER_LANGUAGE = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$")
OWN_LANGUAGES = {"no", "nb", "nn", "en", "nb-no", "no-nb", "nn-no", "no-no", "en-gb", "en-us"}
SKIP_CHILD_SITEMAP = re.compile(r"page|product|produkt|categor|kategori|tag|author|forfatter|attachment|image|video|portfolio|taxonom|user|employee|ansatt", re.IGNORECASE)
NEWS_CHILD_SITEMAP = re.compile(r"news|nyhet|post|artik|article|blog|press|aktuelt", re.IGNORECASE)
BLOCK = re.compile(r"<(?:[\w-]+:)?(url|sitemap)\b[^>]*>(.*?)</(?:[\w-]+:)?\1\s*>", re.IGNORECASE | re.DOTALL)
TAG = lambda name: re.compile(rf"<(?:[\w-]+:)?{name}\b[^>]*>\s*(.*?)\s*</(?:[\w-]+:)?{name}\s*>", re.IGNORECASE | re.DOTALL)  # noqa: E731
LOC, LASTMOD, NEWS_DATE, NEWS_TITLE = TAG("loc"), TAG("lastmod"), TAG("publication_date"), TAG("title")

MAX_SITEMAP_BYTES = 8_000_000
MAX_FEED_BYTES = 2_000_000


def _text(match: re.Match[str] | None) -> str:
    if not match:
        return ""
    value = match.group(1).strip()
    if value.startswith("<![CDATA["):
        value = value[9:].removesuffix("]]>")
    value = html_lib.unescape(value).strip()
    if value.casefold().startswith(("http%3a", "https%3a")):
        value = urllib.parse.unquote(value)
    return value


def parse_sitemap(xml: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(child sitemaps, page entries) of a sitemap index or url set."""
    children: list[dict[str, str]] = []
    entries: list[dict[str, str]] = []
    for kind, body in BLOCK.findall(xml):
        loc = _text(LOC.search(body))
        if not loc:
            continue
        item = {"loc": loc, "lastmod": normalize_date_string(_text(LASTMOD.search(body))) or ""}
        if kind.casefold() == "sitemap":
            children.append(item)
        else:
            news_date = _text(NEWS_DATE.search(body))
            if news_date:
                item["news_date"] = normalize_date_string(news_date) or ""
                item["news_title"] = _text(NEWS_TITLE.search(body))
            entries.append(item)
    return children, entries


def _segments(url: str) -> list[str]:
    return [segment for segment in urllib.parse.urlparse(url).path.casefold().split("/") if segment]


def is_article_url(url: str) -> bool:
    """A single article under a news section: /nyheter/<slug>, /news/2026/<slug>, /blog/<slug>."""
    segments = _segments(url)
    if len(segments) < 2:
        return False
    if OTHER_LANGUAGE.match(segments[0]) and segments[0] not in OWN_LANGUAGES:
        return False  # a translation of the site (Elopak's /de/news/...)
    news_at = next((index for index, segment in enumerate(segments) if NEWS_SEGMENT.search(segment)), None)
    if news_at is None or news_at == len(segments) - 1:
        return False  # no news section, or the section's own index page
    last = segments[-1]
    if last in NEWS_INDEX_SEGMENTS or last.isdigit() or any(segment in NON_ARTICLE_SEGMENTS for segment in segments):
        return False
    return len(last) >= 8 and ("-" in last or "_" in last or bool(date_from_url(url)))


def is_careers_index(url: str) -> bool:
    segments = _segments(url)
    return bool(segments) and len(segments) <= 2 and segments[-1] in CAREER_INDEX_SEGMENTS - {"en", "no", "nb"}


def _news_section(url: str) -> str:
    """The path up to and including the news segment: /fag/.../nyheter-rkr for one section's articles."""
    segments = _segments(url)
    news_at = next((index for index, segment in enumerate(segments) if NEWS_SEGMENT.search(segment)), len(segments) - 1)
    return "/".join(segments[: news_at + 1])


def select_articles(entries: list[dict[str, str]], limit: int, skip: set[str]) -> list[dict[str, str]]:
    """Recent article URLs, newest first within each news section, taken in turn from each
    section. Last-modified dates are often bulk-updated, so one section must not take every slot."""
    # A URL with other pages listed below it is a section or category, not an article.
    parents = {
        "/".join(_segments(entry["loc"])[:depth])
        for entry in entries
        for depth in range(1, len(_segments(entry["loc"])))
    }
    picked: dict[str, dict[str, str]] = {}
    for entry in entries:
        url = entry["loc"]
        canonical = url.split("#", 1)[0].rstrip("/")
        if canonical in skip or not is_article_url(url) or "/".join(_segments(url)) in parents:
            continue
        slug = _segments(url)[-1]
        sort_date = date_from_url(url) or entry.get("news_date") or entry.get("lastmod") or ""
        if slug not in picked or sort_date > picked[slug]["sort_date"]:
            picked[slug] = {**entry, "sort_date": sort_date}
    sections: dict[str, list[dict[str, str]]] = {}
    for item in sorted(picked.values(), key=lambda item: item["sort_date"], reverse=True):
        sections.setdefault(_news_section(item["loc"]), []).append(item)
    ordered = sorted(sections.values(), key=lambda items: items[0]["sort_date"], reverse=True)
    chosen: list[dict[str, str]] = []
    while len(chosen) < limit and any(ordered):
        for items in ordered:
            if items and len(chosen) < limit:
                chosen.append(items.pop(0))
    return chosen


def parse_feed(xml: bytes | str, site_domain: str) -> tuple[str, list[dict[str, str]]]:
    """(feed title, items) of an RSS or Atom feed; only items on the site's own domain."""
    soup = BeautifulSoup(xml, "xml")
    channel = soup.find(["channel", "feed"])
    feed_title = channel.find("title").get_text(" ", strip=True) if channel and channel.find("title") else ""
    items: list[dict[str, str]] = []
    for node in soup.find_all(["item", "entry"]):
        title = node.find("title").get_text(" ", strip=True) if node.find("title") else ""
        link_node = node.find("link", attrs={"rel": "alternate"}) or node.find("link")
        link = ""
        if link_node is not None:
            link = str(link_node.get("href") or "").strip() or link_node.get_text(" ", strip=True)
        raw_date = ""
        for tag in ("pubDate", "published", "date", "issued", "updated"):
            found = node.find(tag)
            if found is not None and found.get_text(strip=True):
                raw_date = found.get_text(strip=True)
                break
        published = _feed_date(raw_date)
        if title and link and published and _registered_domain(link) == site_domain:
            items.append({"title": html_lib.unescape(title)[:300], "url": link, "published": published})
    items.sort(key=lambda item: item["published"], reverse=True)
    return feed_title, items[:15]


def _feed_date(raw: str) -> str | None:
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError, IndexError):
        pass
    match = re.match(r"(\d{4}-\d{2}-\d{2})", raw.strip())
    return match.group(1) if match else normalize_date_string(raw)


def _fetch_document(url: str, *, site_domain: str, timeout: float, max_bytes: int) -> tuple[bytes | None, str, dict[str, Any]]:
    """GET one XML document (sitemap or feed) from the site's own registered domain."""
    metrics: dict[str, Any] = {"requests": 0 if robots_cached(url) else 1, "bytes": 0, "latencies_ms": [], "error": None}
    if _registered_domain(url) != site_domain:
        metrics["error"] = "outside the site's registered domain"
        return None, url, metrics
    try:
        if not _robots_allowed(url, timeout):
            metrics["error"] = "robots.txt disallows"
            return None, url, metrics
    except ValueError as exc:
        metrics["error"] = str(exc)[:120]
        return None, url, metrics
    metrics["requests"] += 1
    started = time.monotonic()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml,application/rss+xml,application/atom+xml,*/*;q=0.5"})
    try:
        with SAFE_OPENER.open(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            final_url = response.geturl()
            encoding = response.headers.get("content-encoding", "")
        metrics["latencies_ms"].append(int((time.monotonic() - started) * 1000))
        metrics["bytes"] = len(raw)
        if len(raw) > max_bytes:
            metrics["error"] = "document exceeds byte limit"
            return None, final_url, metrics
        if _registered_domain(final_url) != site_domain:
            metrics["error"] = "redirected outside the site's registered domain"
            return None, final_url, metrics
        body, _ = safe_decompress_body(raw, encoding=encoding, max_bytes=max_bytes)
        if b"<" not in body[:2000]:
            metrics["error"] = "not an XML document"
            return None, final_url, metrics
        return body, final_url, metrics
    except Exception as exc:
        metrics["latencies_ms"].append(int((time.monotonic() - started) * 1000))
        metrics["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        return None, url, metrics


def read_site_sources(
    website_value: dict[str, Any],
    *,
    reserve: Callable[[int], bool],
    charge: Callable[[dict[str, Any]], None],
    timeout: float = 12.0,
    max_articles: int = 8,
) -> dict[str, Any]:
    """Read the verified site's feed and sitemap; append the article pages found to its pages.

    ``reserve(n)`` asks the company's request allowance for n more requests; ``charge(metrics)``
    records what a fetch actually used. Returns a summary of what was read.
    """
    homepage = website_value.get("final_url") or ""
    site_domain = website_value.get("registered_domain") or _registered_domain(homepage)
    pages: list[dict[str, Any]] = website_value.setdefault("pages", [])
    seen = {str(page.get("url") or "").split("#", 1)[0].rstrip("/") for page in pages}
    summary: dict[str, Any] = {"feeds": [], "sitemaps": [], "articles": [], "careers_pages": [], "errors": []}
    if not homepage or not site_domain:
        return summary
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(homepage))

    def fetch_document(url: str, max_bytes: int) -> tuple[bytes | None, str]:
        if not reserve(1):
            summary["errors"].append({"url": url, "error": "per-company request cap reached"})
            return None, url
        body, final_url, metrics = _fetch_document(url, site_domain=site_domain, timeout=timeout, max_bytes=max_bytes)
        charge(metrics)
        if metrics.get("error"):
            summary["errors"].append({"url": url, "error": metrics["error"]})
        return body, final_url

    def fetch_page(url: str, via: str) -> dict[str, Any] | None:
        if not reserve(1):
            summary["errors"].append({"url": url, "error": "per-company request cap reached"})
            return None
        page, _, metrics = fetch_site_page(url, homepage_domain=site_domain, timeout=timeout)
        charge(metrics)
        if not page:
            summary["errors"].append({"url": url, "error": metrics.get("error")})
            return None
        page["discovered_via"] = via
        canonical = str(page.get("url") or url).split("#", 1)[0].rstrip("/")
        if canonical in seen:
            return None
        seen.add(canonical)
        pages.append(page)
        return page

    # 1. News feed: titles and publication dates straight from the site's own feed.
    feeds = list(website_value.get("feed_links") or [])
    if not feeds and website_value.get("wordpress"):
        feeds = [origin + "/feed/"]
    for feed_url in feeds[:1]:
        body, final_url = fetch_document(feed_url, MAX_FEED_BYTES)
        if not body:
            continue
        title, items = parse_feed(body, site_domain)
        if items:
            pages.append({
                "url": final_url,
                "kind": "feed",
                "title": title,
                "feed_items": items,
                "main_text_excerpt": "",
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "snapshot_kind": "xml",
                "_raw": body,
                "discovered_via": "feed",
            })
            summary["feeds"].append({"url": final_url, "items": len(items)})

    # 2. Sitemap: the robots.txt declaration, else the conventional location.
    declared = [url for url in robots_sitemaps(homepage) if _registered_domain(url) == site_domain]
    roots = declared[:2] or [origin + "/sitemap.xml"]
    entries: list[dict[str, str]] = []
    for root in roots:
        body, _ = fetch_document(root, MAX_SITEMAP_BYTES)
        if not body:
            continue
        children, found = parse_sitemap(body.decode("utf-8", errors="replace"))
        entries.extend(found)
        summary["sitemaps"].append({"url": root, "entries": len(found), "child_sitemaps": len(children)})
        # News/post sitemaps first, then the most recently modified; skip product, tag and image maps.
        queue = [child for child in children if NEWS_CHILD_SITEMAP.search(child["loc"]) or not SKIP_CHILD_SITEMAP.search(child["loc"])]
        queue.sort(key=lambda child: child.get("lastmod") or "", reverse=True)
        queue.sort(key=lambda child: 0 if NEWS_CHILD_SITEMAP.search(child["loc"]) else 1)
        for child in queue[:2]:
            child_body, _ = fetch_document(child["loc"], MAX_SITEMAP_BYTES)
            if not child_body:
                continue
            grandchildren, child_entries = parse_sitemap(child_body.decode("utf-8", errors="replace"))
            entries.extend(child_entries)
            summary["sitemaps"].append({"url": child["loc"], "entries": len(child_entries), "child_sitemaps": len(grandchildren)})
            news_children = [item for item in grandchildren if NEWS_CHILD_SITEMAP.search(item["loc"])][:1]
            for grandchild in news_children:
                grand_body, _ = fetch_document(grandchild["loc"], MAX_SITEMAP_BYTES)
                if grand_body:
                    entries.extend(parse_sitemap(grand_body.decode("utf-8", errors="replace"))[1])
        if entries:
            break

    # A company whose site is one section of a larger site (a local branch's pages on its
    # national organisation's domain) only owns the articles under that section.
    scope = (website_value.get("identity_assessment") or {}).get("site_scope")
    if scope:
        entries = [entry for entry in entries if within_site_scope(entry["loc"], homepage, scope)]

    # 3. The newest articles the sitemap lists, unless the feed already covers them.
    feed_urls = {item["url"].split("#", 1)[0].rstrip("/") for page in pages if page.get("kind") == "feed" for item in page["feed_items"]}
    for entry in select_articles(entries, max_articles, seen | feed_urls):
        page = fetch_page(entry["loc"], "sitemap")
        if page:
            page["sitemap_lastmod"] = entry.get("lastmod") or None
            summary["articles"].append(page["url"])

    # 4. A careers page the homepage did not link to (its job board link is a hiring signal).
    have_careers = any(is_careers_index(str(page.get("url") or "")) for page in pages)
    if not have_careers:
        careers = sorted((entry["loc"] for entry in entries if is_careers_index(entry["loc"])), key=len)[:1]
        for url in careers:
            if fetch_page(url, "sitemap"):
                summary["careers_pages"].append(url)
    return summary
