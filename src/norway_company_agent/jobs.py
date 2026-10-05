from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
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
    extraction_method: str = "html"
    posting_evidence: tuple[str, ...] = ()
    found_on_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Last path segments of a careers landing page (as opposed to one posting).
CAREER_INDEX_SEGMENTS = {
    "karriere", "careers", "career", "jobs", "jobb", "jobber", "stillinger", "ledige-stillinger",
    "ledige-jobber", "vacancies", "jobb-hos-oss", "rekruttering", "open-positions", "join-us",
    "bli-med-pa-laget", "en", "no", "nb",
}
JOB_LINK_TEXT = {
    "les mer", "read more", "se stilling", "se stillingen", "søk her", "søk nå", "apply", "apply now",
    "søk", "mer info", "se alle stillinger", "alle stillinger", "se ledige stillinger", "view all jobs",
}
POSTING_HINTS = re.compile(
    r"søknadsfrist|søk på stillingen|søk stillingen|søk nå|apply now|apply for|application deadline|"
    r"stillingsprosent|fast stilling|fast ansettelse|vikariat|engasjement|heltid|deltid|full[- ]time|part[- ]time|"
    r"tiltredelse|arbeidssted|stillingstittel|job id|stillings-?id",
    re.IGNORECASE,
)
LINK_TEXT_PATTERN = re.compile(
    r"^(?:les mer|read more|klikk her|trykk her|se mer|mer om|mer info|søk her|søk nå|apply|se stilling|se ledige|vis stilling)"
    r"|stillingen her|her!?$|click here|learn more",
    re.IGNORECASE,
)
RECRUITER_DOMAINS = {
    "finn.no", "jobbnorge.no", "webcruiter.com", "webcruiter.no", "karrierestart.no",
    "manpower.no", "adecco.no", "nav.no", "linkedin.com",
    "recman.no", "cruit.no", "easycruit.com", "hr-manager.net",
    "jobylon.com", "teamtailor.com", "reachmee.com", "cvideo.no",
    "meyerhaugen.no", "cruitive.com", "smartrecruiters.com",
    "workday.com", "myworkdayjobs.com", "taleo.net", "successfactors.eu", "icims.com",
}


def _registered_domain(url: str) -> str:
    return tldextract.extract(urlparse(url).hostname or "").top_domain_under_public_suffix or ""


# Applicant-tracking systems that host one employer's job board under its own path or
# subdomain. Staffing agencies (Manpower, Adecco) are not the company's own board.
JOB_BOARD_DOMAINS = {
    "webcruiter.com", "webcruiter.no", "jobbnorge.no", "recman.no", "recman.page", "cruit.no",
    "easycruit.com", "hr-manager.net", "jobylon.com", "teamtailor.com", "reachmee.com", "cvideo.no",
    "smartrecruiters.com", "myworkdayjobs.com", "workday.com", "taleo.net", "successfactors.eu",
    "successfactors.com", "icims.com", "greenhouse.io", "lever.co", "personio.de", "personio.com",
    "recruitee.com", "workable.com", "homerun.co", "varbi.com", "emply.com", "karrierestart.no",
    "finn.no", "nav.no", "linkedin.com",
}
NON_TENANT_SUBDOMAINS = {"", "www", "cdn", "static", "assets", "media", "img", "images", "help", "support", "blog"}


def job_board_url(url: str) -> str | None:
    """The URL when it opens one employer's job board on an applicant-tracking system, else None.

    A recruiter's own homepage, a LinkedIn company page or a general job portal is not a job
    board; finn.no, nav.no and LinkedIn count only through their job listing paths.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    ext = tldextract.extract(parsed.hostname or "")
    domain = ext.top_domain_under_public_suffix or ""
    if domain not in JOB_BOARD_DOMAINS:
        return None
    path = (parsed.path or "/").casefold()
    if re.search(r"\.(?:js|css|png|jpe?g|svg|gif|webp|ico)$", path):
        return None
    subdomain = ext.subdomain.casefold()
    if domain == "linkedin.com":
        tenant = "/jobs" in path and path.startswith("/company/")
    elif domain == "finn.no":
        tenant = path.startswith("/job/") and bool(parsed.query or path.count("/") > 2)
    elif domain == "nav.no":
        tenant = subdomain.endswith("arbeidsplassen") and path.startswith(("/stillinger/", "/stilling/"))
    elif subdomain in NON_TENANT_SUBDOMAINS:
        # The provider's own site ("Powered by Teamtailor") unless the path names one employer or ad.
        tenant = bool(re.search(r"\d{3,}|/(?:arbeidsgiver|employers?|bedrift|company|companies|stilling|job)s?/", path))
    elif subdomain in {"boards", "job-boards", "jobs", "apply", "candidate", "careers"} or re.fullmatch(r"career\d*", subdomain):
        tenant = path.strip("/") != "" or bool(parsed.query)  # shared host: the path or query names the employer
    else:
        tenant = True  # employer's own subdomain (acme.teamtailor.com, equinor.wd3.myworkdayjobs.com)
    if not tenant:
        return None
    return parsed._replace(fragment="").geturl()


def posting_evidence_for(job_url: str, context_text: str, deadline: str | None) -> tuple[str, ...]:
    """Collect concrete signs that a link is one job posting rather than a careers landing page."""
    found: list[str] = []
    if deadline:
        found.append("deadline")
    if POSTING_HINTS.search(context_text or ""):
        found.append("posting_terms")
    if _registered_domain(job_url) in RECRUITER_DOMAINS:
        found.append("ats_listing")
    return tuple(found)


def is_publishable_job(job: "JobRecord") -> bool:
    """A hiring fact needs a real role: a structured JobPosting, or a role-specific listing
    with a deadline, posting terms or an applicant-tracking link. A careers page is not enough."""
    title = job.job_title.casefold().strip()
    if title in JOB_LINK_TEXT or title in GENERIC_CAREER_TITLES or not (4 <= len(title) <= 160):
        return False
    if LINK_TEXT_PATTERN.search(title):
        return False
    if job.extraction_method == "jsonld":
        return True
    segments = [seg for seg in urlparse(job.source_url).path.casefold().split("/") if seg]
    page = (job.found_on_url or "").split("#", 1)[0].rstrip("/")
    if "ats_listing" not in job.posting_evidence:
        if job.source_url.split("#", 1)[0].rstrip("/") == page:
            return False  # card without its own posting page
        if not segments or segments[-1] in CAREER_INDEX_SEGMENTS:
            return False
    return bool(job.posting_evidence)


def normalize_date_string(raw: str | None) -> str | None:
    """Normalize various date formats into ISO YYYY-MM-DD string."""
    if not raw or not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    iso_match = re.search(r"\b(202\d-[01]\d-[0-3]\d)(?:T|\b|\s)", cleaned)
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

    is_external_ats = job_reg_domain in RECRUITER_DOMAINS

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
        if job_candidate.get("linked_from_verified_site"):
            score = 0.92
            reason = "Applicant-tracking posting linked directly from the verified company website"
            method = "verified_site_ats_link"
        elif token_ratio >= 0.75 or has_org_nr:
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
            extraction_method="jsonld",
            posting_evidence=("structured_job_posting",),
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
        links = soup.select("a[href*='/stilling/'], a[href*='/jobb/'], a[href*='/job/'], a[href*='/careers/'], a[href*='/karriere/'], a[href*='/vacancies/'], a[href*='/ledige-stillinger/']")
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

            # Use the parent's text only when it belongs to this link alone; a shared list
            # wrapper would lend every link the same deadline and posting terms.
            parent = link.parent
            own_parent = parent is not None and len(parent.select("a[href]")) <= 2
            parent_text = parent.get_text(" ", strip=True) if own_parent else link.get_text(" ", strip=True)
            deadline = _extract_deadline_from_text(parent_text)
            published = normalize_date_string(parent_text)

            id_assessment = verify_job_identity(profile, {"title": title_text, "linked_from_verified_site": True}, full_url)
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
                extraction_method="html_link",
                posting_evidence=posting_evidence_for(full_url, parent_text, deadline),
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

        id_assessment = verify_job_identity(profile, {"title": title, "description": card_text, "linked_from_verified_site": True}, job_url)
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
            extraction_method="html_card",
            posting_evidence=posting_evidence_for(job_url, card_text, deadline),
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

        jsonld_jobs = [replace(j, found_on_url=p_url) for j in extract_jobs_from_jsonld(p_html, p_url, profile)]
        for j in jsonld_jobs:
            if j.job_id not in all_jobs:
                all_jobs[j.job_id] = j

        p_path = urlparse(p_url).path.casefold()
        is_career_url = any(k in p_path for k in ("karriere", "stillinger", "jobb", "jobs", "career", "rekruttering"))
        if is_career_url or not jsonld_jobs:
            html_jobs = [replace(j, found_on_url=p_url) for j in extract_jobs_from_html_cards(p_html, p_url, profile)]
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
    seen: set[str] = set()

    from .identity import within_site_scope
    web_value = website.get("value") or {}
    scope = (web_value.get("identity_assessment") or {}).get("site_scope")
    for job in jobs:
        if not is_publishable_job(job):
            continue
        if not within_site_scope(job.source_url, web_value.get("final_url"), scope):
            continue  # the posting belongs to the wider site (or an ATS we cannot tie to this section)
        key = f"{job.source_url}|{job.job_title.casefold()}"
        if key in seen:
            continue
        seen.add(key)
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
            "found_on_url": job.found_on_url,
            "posting_evidence": list(job.posting_evidence),
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


CAREER_PATH_HINTS = ("karriere", "career", "jobb", "jobs", "stilling", "rekruttering", "vacanc", "work-with-us", "join-us")


def extract_hiring_signal_observations(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """One hiring signal per company: a page on its verified site that opens its job board.

    This is an apply action (a link or embed into the company's applicant-tracking job board),
    not a careers page by itself; individual postings are published separately.
    """
    org = str(profile.get("organisation_number") or "")
    website = profile.get("evidence", {}).get("website", {})
    if not org or website.get("status") != "available":
        return []
    from .identity import within_site_scope

    value = website.get("value") or {}
    homepage = value.get("final_url") or ""
    scope = (value.get("identity_assessment") or {}).get("site_scope")
    candidates: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
    for order, page in enumerate(value.get("pages") or []):
        page_url = page.get("url") or ""
        if page.get("kind") == "feed" or not within_site_scope(page_url, homepage, scope):
            continue
        path = urlparse(page_url).path.casefold()
        rank = 0 if any(hint in path for hint in CAREER_PATH_HINTS) else 1 if page_url.rstrip("/") == homepage.rstrip("/") else 2
        for link in page.get("job_board_links") or []:
            candidates.append((rank, order, page, link))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, _, page, link = candidates[0]
    boards = list(dict.fromkeys(item[3]["url"] for item in candidates if item[2] is page))
    board_domain = _registered_domain(link["url"])
    label = f' ("{link["text"]}")' if link.get("text") else ""
    return [{
        "id": f"hiring-signal-{org}",
        "organisation_number": org,
        "platform": "job_board",
        "signal_type": "hiring_signal",
        "source_url": page.get("url"),
        "found_on_url": page.get("url"),
        "retrieved_at": website.get("retrieved_at") or utc_now(),
        "content_sha256": page.get("content_sha256"),
        "exact_entity": True,
        "identity_proof": [{
            "type": "verified_site_job_board_link",
            "method": "job_board_linked_from_verified_site",
            "reason": "The company's verified website links to this job board",
        }],
        "acquisition_mode": "permitted_public_page",
        "rights_status": "approved",
        "source_class": "company_careers",
        "evidence_span": f"Careers page links to the company's job board on {board_domain}{label}",
        "posting_evidence": ["job_board_" + link.get("kind", "link")],
        "metrics": {
            "job_board_url": link["url"],
            "job_board": board_domain,
            "job_board_urls": boards[:5],
            "link_text": link.get("text") or None,
            "page_title": page.get("title"),
        },
    }]
