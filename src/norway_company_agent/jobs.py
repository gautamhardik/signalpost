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


MONTH_MAP = {
    "jan": "01", "januar": "01", "january": "01",
    "feb": "02", "februar": "02", "february": "02",
    "mar": "03", "mars": "03", "march": "03",
    "apr": "04", "april": "04",
    "mai": "05", "may": "05",
    "jun": "06", "juni": "06", "june": "06",
    "jul": "07", "juli": "07", "july": "07",
    "aug": "08", "august": "08",
    "sep": "09", "sept": "09", "september": "09",
    "okt": "10", "oct": "10", "oktober": "10", "october": "10",
    "nov": "11", "november": "11",
    "des": "12", "dec": "12", "desember": "12", "december": "12",
}

GENERIC_CAREER_TITLES = {
    "karriere", "stillinger", "jobb", "jobs", "career", "careers",
    "ledige stillinger", "jobb hos oss", "bli med på laget", "bli vår kollega",
    "rekruttering", "arbeidsplassen", "åpen søknad", "open application",
    "work with us", "join our team", "vacancies", "open positions",
}


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    company_orgnr: str
    job_title: str
    location: str | None
    employment_type: str | None
    department: str | None
    description: str | None
    published_at: str | None
    deadline: str | None
    source_url: str
    retrieved_at: str
    content_sha256: str
    identity_assessment: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_date_string(raw: str | None) -> str | None:
    """Normalize various date formats into ISO YYYY-MM-DD string."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    iso_match = re.search(r"\b(202\d-[01]\d-[0-3]\d)\b", cleaned)
    if iso_match:
        return iso_match.group(1)

    dmy_match = re.search(r"\b([0-3]?\d)[\./-]([01]?\d)[\./-](202\d)\b", cleaned)
    if dmy_match:
        day = int(dmy_match.group(1))
        month = int(dmy_match.group(2))
        year = int(dmy_match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"

    text_match = re.search(r"\b([0-3]?\d)\.?\s+([a-zA-ZæøåÆØÅ]+)\s+(202\d)\b", cleaned)
    if text_match:
        day = int(text_match.group(1))
        month_str = text_match.group(2).casefold()
        year = int(text_match.group(3))
        month = MONTH_MAP.get(month_str)
        if month and 1 <= day <= 31:
            return f"{year:04d}-{month}-{day:02d}"

    return None


def clean_job_title(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = re.sub(r"\s+", " ", str(title)).strip()
    cleaned = re.sub(r"^[-–—•*|:]+\s*", "", cleaned)
    cleaned = re.sub(r"\s*[-–—•*|:]+$", "", cleaned).strip()
    if not cleaned or len(cleaned) < 3:
        return None
    if cleaned.casefold() in GENERIC_CAREER_TITLES:
        return None
    return cleaned[:200]


def _extract_deadline_from_text(text: str) -> str | None:
    """Look for explicit Norwegian deadline phrases like 'Søknadsfrist: 15.10.2026' or 'Frist: Snarest'."""
    patterns = [
        r"(?:søknadsfrist|frist|deadline|søknad innen|application deadline)\s*[:\-]?\s*([0-3]?\d[\./-][01]?\d[\./-]202\d)",
        r"(?:søknadsfrist|frist|deadline|søknad innen|application deadline)\s*[:\-]?\s*([0-3]?\d\.?\s+[a-zA-ZæøåÆØÅ]+\s+202\d)",
        r"(?:søknadsfrist|frist|deadline|søknad innen|application deadline)\s*[:\-]?\s*(snarest|asap|fortløpende|løpende)",
        r"(?:innen|before)\s+([0-3]?\d[\./-][01]?\d[\./-]202\d)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if re.search(r"\b(snarest|asap|fortløpende|løpende)\b", val, re.IGNORECASE):
                return "snarest"
            parsed = normalize_date_string(val)
            if parsed:
                return parsed
    return None


def verify_job_identity(
    profile: dict[str, Any],
    job_candidate: dict[str, Any],
    source_url: str,
) -> dict[str, Any]:
    """Verify that a candidate job belongs to the target company and not a third-party recruiter or parent/subsidiary collision."""
    company_name = profile.get("name") or ""
    org_nr = str(profile.get("organisation_number") or "")
    core_tokens = set(_tokens(company_name))

    evidence_rec = profile.get("evidence", {})
    web_val = (evidence_rec.get("website") or {}).get("value") or {}
    verified_registered_domain = web_val.get("registered_domain") or ""

    parsed_job_url = urlparse(source_url)
    job_domain_ext = tldextract.extract(parsed_job_url.hostname or "")
    job_reg_domain = job_domain_ext.top_domain_under_public_suffix

    same_domain = bool(verified_registered_domain and job_reg_domain == verified_registered_domain)

    hiring_org = job_candidate.get("hiring_organization") or ""
    org_tokens = set(_tokens(hiring_org))

    name_overlap = len(core_tokens & org_tokens) if hiring_org else 0
    token_ratio = name_overlap / len(core_tokens) if core_tokens else 0.0

    recruiter_domains = {
        "finn.no", "jobbnorge.no", "webcruiter.com", "karrierestart.no",
        "manpower.no", "adecco.no", "nav.no", "linkedin.com"
    }
    is_external_ats = job_reg_domain in recruiter_domains

    job_text = str(job_candidate.get("description") or "")
    has_org_nr = org_nr in job_text if org_nr else False

    if same_domain:
        if hiring_org and token_ratio == 0 and len(org_tokens) >= 2:
            return {
                "verified": False,
                "score": 0.40,
                "reason": f"Job on company domain specifies distinct subsidiary/partner organisation: {hiring_org}",
                "method": "parent_subsidiary_boundary_gate",
            }
        score = 0.95
        reason = "Job hosted directly on verified company domain"
        method = "verified_domain_first_party_job"
    elif is_external_ats:
        if token_ratio >= 0.75 or has_org_nr:
            score = 0.92
            reason = f"Job on ATS/portal verified by legal company name match ({hiring_org})"
            method = "ats_exact_entity_match"
        else:
            return {
                "verified": False,
                "score": 0.30,
                "reason": f"External ATS job lacks conclusive corroboration for {company_name}",
                "method": "ats_unverified_entity_gate",
            }
    else:
        if token_ratio >= 0.90 or has_org_nr:
            score = 0.90
            reason = "Job verified by exact company token match and registered address/org"
            method = "third_party_corroborated_job"
        else:
            return {
                "verified": False,
                "score": 0.20,
                "reason": "Unrecognized external domain with insufficient entity corroboration",
                "method": "unrecognized_domain_gate",
            }

    return {
        "verified": True,
        "score": score,
        "reason": reason,
        "method": method,
    }


def extract_jobs_from_jsonld(
    html: str,
    base_url: str,
    profile: dict[str, Any],
) -> list[JobRecord]:
    """Extract JobPosting structured data from page HTML."""
    try:
        data = extruct.extract(html, base_url=base_url, syntaxes=["json-ld"])
    except Exception:
        return []

    jsonld_items = data.get("json-ld", [])
    postings: list[dict[str, Any]] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            type_val = item.get("@type")
            types = set(type_val if isinstance(type_val, list) else [type_val])
            if "JobPosting" in types:
                postings.append(item)
            for v in item.values():
                walk(v)
        elif isinstance(item, list):
            for i in item:
                walk(i)

    walk(jsonld_items)
    records: list[JobRecord] = []
    org_nr = str(profile.get("organisation_number") or "")

    for p in postings:
        raw_title = p.get("title") or p.get("name")
        title = clean_job_title(raw_title)
        if not title:
            continue

        hiring_org_val = p.get("hiringOrganization")
        hiring_org_name = ""
        if isinstance(hiring_org_val, dict):
            hiring_org_name = hiring_org_val.get("name") or ""
        elif isinstance(hiring_org_val, str):
            hiring_org_name = hiring_org_val

        loc_val = p.get("jobLocation")
        location = None
        if isinstance(loc_val, dict):
            addr = loc_val.get("address")
            if isinstance(addr, dict):
                location = addr.get("addressLocality") or addr.get("addressRegion")
            elif isinstance(addr, str):
                location = addr
        elif isinstance(loc_val, list) and loc_val:
            first_loc = loc_val[0]
            if isinstance(first_loc, dict):
                addr = first_loc.get("address")
                if isinstance(addr, dict):
                    location = addr.get("addressLocality")

        emp_type = p.get("employmentType")
        if isinstance(emp_type, list) and emp_type:
            emp_type = emp_type[0]
        emp_type_str = str(emp_type).strip() if emp_type else None

        published_at = normalize_date_string(p.get("datePosted"))
        valid_through = normalize_date_string(p.get("validThrough"))

        desc = p.get("description")
        desc_text = None
        if desc:
            desc_soup = BeautifulSoup(str(desc), "lxml")
            desc_text = re.sub(r"\s+", " ", desc_soup.get_text(" ", strip=True))[:1000]

        job_url = p.get("url") or base_url
        job_url = urljoin(base_url, str(job_url))

        cand_dict = {
            "title": title,
            "hiring_organization": hiring_org_name,
            "description": desc_text,
        }
        id_assessment = verify_job_identity(profile, cand_dict, job_url)
        if not id_assessment["verified"]:
            continue

        raw_bytes = f"{title}|{job_url}|{published_at}".encode("utf-8")
        content_sha = hashlib.sha256(raw_bytes).hexdigest()
        job_id = f"job-{org_nr}-{content_sha[:12]}"

        records.append(JobRecord(
            job_id=job_id,
            company_orgnr=org_nr,
            job_title=title,
            location=location,
            employment_type=emp_type_str,
            department=p.get("department") or None,
            description=desc_text,
            published_at=published_at,
            deadline=valid_through,
            source_url=job_url,
            retrieved_at=utc_now(),
            content_sha256=content_sha,
            identity_assessment=id_assessment,
        ))

    return records


def extract_jobs_from_html_cards(
    html: str,
    base_url: str,
    profile: dict[str, Any],
) -> list[JobRecord]:
    """Fallback: extract job listings from structured HTML elements or job cards."""
    soup = BeautifulSoup(html, "lxml")
    org_nr = str(profile.get("organisation_number") or "")
    records: list[JobRecord] = []

    selectors = [
        "article.job", "article.stilling", ".job-item", ".stilling-item",
        ".career-item", ".vacancy-item", ".job-card", ".career-card",
        "li.job", "li.stilling", "[data-job-id]"
    ]
    cards = soup.select(", ".join(selectors))

    if not cards:
        links = soup.select("a[href*='/stilling/'], a[href*='/jobb/'], a[href*='/job/'], a[href*='/careers/'], a[href*='/karriere/']")
        seen_links = set()
        for link in links:
            href = link.get("href")
            if not href:
                continue
            full_url = urljoin(base_url, href)
            if full_url in seen_links or full_url.rstrip("/") == base_url.rstrip("/"):
                continue
            seen_links.add(full_url)

            title_text = clean_job_title(link.get_text(" ", strip=True))
            if not title_text:
                continue

            parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""
            deadline = _extract_deadline_from_text(parent_text)
            published = normalize_date_string(parent_text)

            id_assessment = verify_job_identity(profile, {"title": title_text}, full_url)
            if not id_assessment["verified"]:
                continue

            content_sha = hashlib.sha256(f"{title_text}|{full_url}".encode("utf-8")).hexdigest()
            job_id = f"job-{org_nr}-{content_sha[:12]}"
            records.append(JobRecord(
                job_id=job_id,
                company_orgnr=org_nr,
                job_title=title_text,
                location=None,
                employment_type=None,
                department=None,
                description=parent_text[:300] if parent_text else None,
                published_at=published,
                deadline=deadline,
                source_url=full_url,
                retrieved_at=utc_now(),
                content_sha256=content_sha,
                identity_assessment=id_assessment,
            ))
        return records

    for card in cards:
        title_el = card.select_one("h2, h3, h4, .job-title, .title, a")
        if not title_el:
            continue
        title = clean_job_title(title_el.get_text(" ", strip=True))
        if not title:
            continue

        link_el = card.select_one("a[href]") or (title_el if title_el.name == "a" and title_el.get("href") else None)
        job_url = urljoin(base_url, link_el.get("href")) if link_el else base_url

        card_text = card.get_text(" ", strip=True)
        deadline = _extract_deadline_from_text(card_text)
        published = normalize_date_string(card_text)

        loc_el = card.select_one(".location, .job-location, .sted, [data-location]")
        location = loc_el.get_text(" ", strip=True) if loc_el else None

        id_assessment = verify_job_identity(profile, {"title": title, "description": card_text}, job_url)
        if not id_assessment["verified"]:
            continue

        content_sha = hashlib.sha256(f"{title}|{job_url}".encode("utf-8")).hexdigest()
        job_id = f"job-{org_nr}-{content_sha[:12]}"

        records.append(JobRecord(
            job_id=job_id,
            company_orgnr=org_nr,
            job_title=title,
            location=location[:100] if location else None,
            employment_type=None,
            department=None,
            description=card_text[:500] if card_text else None,
            published_at=published,
            deadline=deadline,
            source_url=job_url,
            retrieved_at=utc_now(),
            content_sha256=content_sha,
            identity_assessment=id_assessment,
        ))

    return records


def extract_jobs_from_crawl_material(
    profile: dict[str, Any],
    website_material: dict[str, Any],
) -> list[JobRecord]:
    """Extract verified job openings from all pages of a crawled website."""
    val = website_material.get("value") or {}
    pages = val.get("pages") or []
    final_url = val.get("final_url") or website_material.get("source_url") or ""

    if not pages and final_url:
        pages = [{"url": final_url, "html": val.get("html") or "", "title": val.get("title")}]

    all_jobs: dict[str, JobRecord] = {}

    for page in pages:
        p_url = page.get("url") or final_url
        p_html = page.get("html") or ""
        p_text = page.get("main_text_excerpt") or ""

        if not p_html:
            p_html = f"<html><head><title>{page.get('title', '')}</title></head><body>{p_text}</body></html>"

        jsonld_jobs = extract_jobs_from_jsonld(p_html, p_url, profile)
        for j in jsonld_jobs:
            if j.job_id not in all_jobs:
                all_jobs[j.job_id] = j

        p_path = urlparse(p_url).path.casefold()
        is_career_url = any(k in p_path for k in ("karriere", "stillinger", "jobb", "jobs", "career", "rekruttering"))
        if is_career_url or not jsonld_jobs:
            html_jobs = extract_jobs_from_html_cards(p_html, p_url, profile)
            for j in html_jobs:
                if j.job_id not in all_jobs:
                    all_jobs[j.job_id] = j

    return list(all_jobs.values())


def extract_job_evidence(
    profile: dict[str, Any],
    website_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Produce standardized Evidence dictionary for the jobs module."""
    if website_evidence.get("status") != "available":
        return evidence(
            field="jobs",
            status="not_found",
            source_type="company_verified_jobs",
            source_url=website_evidence.get("source_url") or "https://data.brreg.no",
            note="No verified website available for job extraction",
        )

    jobs = extract_jobs_from_crawl_material(profile, website_evidence)
    source_url = website_evidence.get("source_url") or ""

    if not jobs:
        return evidence(
            field="jobs",
            status="not_found",
            source_type="company_verified_jobs",
            source_url=source_url,
            value={"jobs": [], "total_active_jobs": 0},
            note="Verified website inspected; no active structured job postings detected.",
        )

    job_dicts = [j.to_dict() for j in jobs]
    composite_sha = hashlib.sha256(json.dumps([j["job_id"] for j in job_dicts], sort_keys=True).encode()).hexdigest()

    return evidence(
        field="jobs",
        status="available",
        source_type="company_verified_jobs",
        source_url=source_url,
        value={
            "jobs": job_dicts,
            "total_active_jobs": len(job_dicts),
        },
        content_sha256=composite_sha,
        effective_at=jobs[0].published_at,
        note=f"Discovered {len(job_dicts)} verified active job opening(s)",
    )


def extract_job_observations(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert verified job records into external footprint observations."""
    org = str(profile.get("organisation_number") or "")
    website = profile.get("evidence", {}).get("website", {})
    if not org or website.get("status") != "available":
        return []

    jobs = extract_jobs_from_crawl_material(profile, website)
    observations: list[dict[str, Any]] = []

    for job in jobs:
        obs = {
            "id": f"job-{org}-{job.job_id}",
            "organisation_number": org,
            "platform": "job_board",
            "signal_type": "job_posting",
            "source_url": job.source_url,
            "retrieved_at": job.retrieved_at,
            "content_sha256": job.content_sha256,
            "exact_entity": True,
            "identity_proof": [job.identity_assessment],
            "acquisition_mode": "permitted_public_page",
            "rights_status": "approved",
            "source_class": "company_careers",
            "evidence_span": f"Verified job opening: {job.job_title}" + (f" in {job.location}" if job.location else ""),
            "metrics": {
                "job_title": job.job_title,
                "location": job.location,
                "employment_type": job.employment_type,
                "published_at": job.published_at,
                "deadline": job.deadline,
            },
        }
        observations.append(obs)

    return observations

