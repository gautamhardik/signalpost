from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .evidence import create_evidence_record, utc_now
from .identity import _tokens, LEGAL_AND_GENERIC


DATE_PATTERNS = [
    r"\b(202[0-6])[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12][0-9]|3[01])\b",
    r"\b(0[1-9]|[12][0-9]|3[01])[-/.](0[1-9]|1[0-2])[-/.](202[0-6])\b",
    r"\b([0-2]?[0-9]|3[01])\.\s*(januar|februar|mars|april|mai|juni|juli|august|september|oktober|november|desember)\s*(202[0-6])\b",
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s*([0-2]?[0-9]|3[01]),?\s*(202[0-6])\b",
]

MONTH_MAP = {
    "januar": "01", "january": "01", "februar": "02", "february": "02",
    "mars": "03", "march": "03", "april": "04", "mai": "05", "may": "05",
    "juni": "06", "june": "06", "juli": "07", "july": "07",
    "august": "08", "september": "09", "oktober": "10", "october": "10",
    "november": "11", "desember": "12", "december": "12"
}


def extract_iso_date(text: str) -> str | None:
    """Extract standard ISO-8601 date (YYYY-MM-DD) from text/metadata."""
    # Check YYYY-MM-DD
    m1 = re.search(r"\b(202[0-6])[-/.](0[1-9]|1[0-2])[-/.](0[1-9]|[12][0-9]|3[01])\b", text)
    if m1:
        y, m, d = m1.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"
    
    # Check DD-MM-YYYY
    m2 = re.search(r"\b(0[1-9]|[12][0-9]|3[01])[-/.](0[1-9]|1[0-2])[-/.](202[0-6])\b", text)
    if m2:
        d, m, y = m2.groups()
        return f"{y}-{m.zfill(2)}-{d.zfill(2)}"

    # Check Norwegian text date: 15. mars 2026
    m3 = re.search(r"\b([0-2]?[0-9]|3[01])\.\s*(januar|februar|mars|april|mai|juni|juli|august|september|oktober|november|desember)\s*(202[0-6])\b", text, re.IGNORECASE)
    if m3:
        d, month_name, y = m3.groups()
        m_num = MONTH_MAP.get(month_name.lower(), "01")
        return f"{y}-{m_num}-{d.zfill(2)}"

    # Check English text date: March 15, 2026
    m4 = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s*([0-2]?[0-9]|3[01]),?\s*(202[0-6])\b", text, re.IGNORECASE)
    if m4:
        month_name, d, y = m4.groups()
        m_num = MONTH_MAP.get(month_name.lower(), "01")
        return f"{y}-{m_num}-{d.zfill(2)}"

    return None


def extract_article_candidates(
    page_url: str,
    html: str,
    page_text: str,
    *,
    company_name: str,
    company_org: str,
) -> list[dict[str, Any]]:
    """Parse HTML and page text for dated article items.
    
    Requires:
    1. Title
    2. Published date (explicitly dated activity)
    3. Supporting text
    4. Canonical / article source URL
    """
    soup = BeautifulSoup(html, "lxml")
    articles: list[dict[str, Any]] = []

    # Check for meta publication date
    meta_date = None
    for attr in ("article:published_time", "og:published_time", "datePublished", "pubdate"):
        tag = soup.find(attrs={"property": attr}) or soup.find(attrs={"name": attr})
        if tag and tag.get("content"):
            parsed_d = extract_iso_date(str(tag.get("content")))
            if parsed_d:
                meta_date = parsed_d
                break

    # If the page itself is an article page
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    canonical_tag = soup.find("link", rel="canonical")
    canonical_url = canonical_tag.get("href") if canonical_tag and canonical_tag.get("href") else page_url
    if not canonical_url.startswith("http"):
        canonical_url = urljoin(page_url, canonical_url)

    # Strategy 1: Page-level article if meta_date or date in text
    doc_date = meta_date or extract_iso_date(page_text[:1000]) or extract_iso_date(page_title)
    if doc_date and len(page_text.strip()) >= 150:
        articles.append({
            "title": page_title[:250],
            "published_at": doc_date,
            "source_url": canonical_url,
            "supporting_text": page_text[:4000],
            "content_sha256": hashlib.sha256(f"{canonical_url}|{doc_date}|{page_title}".encode("utf-8")).hexdigest(),
        })

    # Strategy 2: Individual article elements on a newsroom / news list page
    for el in soup.select("article, .article, .news-item, .post-item, .nyhet"):
        el_text = el.get_text(" ", strip=True)
        el_date = extract_iso_date(el_text)
        a_tag = el.find("a", href=True)
        article_url = urljoin(page_url, a_tag["href"]) if a_tag else canonical_url
        h_tag = el.find(["h1", "h2", "h3", "h4"])
        title = h_tag.get_text(" ", strip=True) if h_tag else el_text[:100]

        if el_date and len(el_text) >= 60 and len(title) >= 10:
            articles.append({
                "title": title[:250],
                "published_at": el_date,
                "source_url": article_url,
                "supporting_text": el_text[:2000],
                "content_sha256": hashlib.sha256(f"{article_url}|{el_date}|{title}".encode("utf-8")).hexdigest(),
            })

    # Deduplicate by canonical URL / content hash
    deduped: dict[str, dict[str, Any]] = {}
    for item in articles:
        deduped[item["content_sha256"]] = item

    return list(deduped.values())


def verify_news_identity(
    article: dict[str, Any],
    profile: dict[str, Any],
    homepage_host: str,
) -> dict[str, Any]:
    """Verify that an article belongs to the subject legal entity.
    
    Strict rules:
    - Same registered domain as verified company website OR
    - Explicit Norwegian organisation number in text OR
    - Distinctive legal name tokens in title or text with verified domain link
    """
    article_url = article.get("source_url") or ""
    article_host = (urlparse(article_url).hostname or "").casefold().removeprefix("www.")
    clean_hp = homepage_host.casefold().removeprefix("www.")

    # Domain match check
    domain_match = bool(clean_hp and (article_host == clean_hp or article_host.endswith("." + clean_hp)))

    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    haystack = f"{article.get('title', '')} {article.get('supporting_text', '')}"
    org_in_text = bool(org and org in haystack)

    name_tokens = [t for t in _tokens(profile.get("name")) if t not in LEGAL_AND_GENERIC]
    text_tokens = set(_tokens(haystack))
    name_matched = bool(name_tokens and (set(name_tokens).issubset(text_tokens) or (len(name_tokens) >= 2 and sum(t in text_tokens for t in name_tokens) >= 2)))

    # Verification threshold
    verified = False
    reasons = []

    if domain_match:
        # First-party domain: requires either name mention or reasonable site context
        if name_matched or len(name_tokens) == 0 or len(article.get("supporting_text", "")) >= 100:
            verified = True
            reasons.append("article published on verified first-party company domain")
    elif org_in_text:
        verified = True
        reasons.append("exact organisation number corroborated in article text")
    elif name_matched and len(name_tokens) >= 2:
        verified = True
        reasons.append("distinctive multi-token legal name corroborated in article")
    else:
        reasons.append("insufficient entity corroboration or unrelated third-party host")

    return {
        "verified": verified,
        "score": 0.95 if (domain_match and (name_matched or org_in_text)) else 0.90 if verified else 0.30,
        "reasons": reasons,
        "domain_match": domain_match,
        "org_in_text": org_in_text,
        "name_matched": name_matched,
    }
