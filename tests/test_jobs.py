from __future__ import annotations

import json
import pytest
from norway_company_agent.jobs import (
    clean_job_title,
    extract_job_evidence,
    extract_jobs_from_crawl_material,
    extract_jobs_from_html_cards,
    extract_jobs_from_jsonld,
    normalize_date_string,
    verify_job_identity,
)


@pytest.fixture
def mock_profile():
    return {
        "organisation_number": "912345678",
        "name": "NORDIC TECH INNOVATIONS AS",
        "legal_form": "AS",
        "municipality": "OSLO",
        "evidence": {
            "website": {
                "status": "available",
                "source_url": "https://nordictech.no",
                "value": {
                    "final_url": "https://nordictech.no",
                    "registered_domain": "nordictech.no",
                    "title": "Nordic Tech Innovations | Cloud & AI Solutions",
                },
            }
        },
    }


def test_date_normalization():
    assert normalize_date_string("2026-10-15") == "2026-10-15"
    assert normalize_date_string("15.10.2026") == "2026-10-15"
    assert normalize_date_string("15/10/2026") == "2026-10-15"
    assert normalize_date_string("15. oktober 2026") == "2026-10-15"
    assert normalize_date_string("1. mai 2026") == "2026-05-01"
    assert normalize_date_string("invalid date") is None
    assert normalize_date_string(None) is None


def test_clean_job_title():
    assert clean_job_title("  Senior Backend Engineer - Python  ") == "Senior Backend Engineer - Python"
    assert clean_job_title("• Utvikler / Konsulent:") == "Utvikler / Konsulent"
    assert clean_job_title("Karriere") is None  # Generic career title
    assert clean_job_title("Ledige stillinger") is None  # Generic career title
    assert clean_job_title("Bli med på laget") is None
    assert clean_job_title("a") is None  # Too short


def test_jsonld_job_extraction(mock_profile):
    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <script type="application/ld+json">
      {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": "Senior Data Platform Engineer",
        "description": "<p>We are seeking an experienced data engineer in Oslo.</p>",
        "datePosted": "2026-09-15",
        "validThrough": "2026-10-31",
        "employmentType": "FULL_TIME",
        "hiringOrganization": {
          "@type": "Organization",
          "name": "Nordic Tech Innovations AS"
        },
        "jobLocation": {
          "@type": "Place",
          "address": {
            "@type": "PostalAddress",
            "addressLocality": "Oslo",
            "addressCountry": "NO"
          }
        },
        "url": "https://nordictech.no/careers/senior-data-engineer"
      }
      </script>
    </head>
    <body><h1>Careers</h1></body>
    </html>
    """
    jobs = extract_jobs_from_jsonld(html, "https://nordictech.no/careers", mock_profile)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.job_title == "Senior Data Platform Engineer"
    assert job.location == "Oslo"
    assert job.employment_type == "FULL_TIME"
    assert job.published_at == "2026-09-15"
    assert job.deadline == "2026-10-31"
    assert job.source_url == "https://nordictech.no/careers/senior-data-engineer"
    assert job.identity_assessment["verified"] is True
    assert job.identity_assessment["score"] >= 0.90


def test_html_job_card_fallback(mock_profile):
    html = """
    <html>
    <body>
      <div class="career-section">
        <article class="job-card">
          <h3 class="job-title"><a href="/karriere/regnskapsforer">Autorisert Regnskapsfører</a></h3>
          <span class="location">Bergen</span>
          <p class="desc">Vi søker regnskapsfører til vårt kontor i Bergen. Søknadsfrist: 25.11.2026.</p>
        </article>
      </div>
    </body>
    </html>
    """
    jobs = extract_jobs_from_html_cards(html, "https://nordictech.no/karriere", mock_profile)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.job_title == "Autorisert Regnskapsfører"
    assert job.location == "Bergen"
    assert job.deadline == "2026-11-25"
    assert job.source_url == "https://nordictech.no/karriere/regnskapsforer"
    assert job.identity_assessment["verified"] is True


def test_parent_subsidiary_boundary_protection(mock_profile):
    # Job on same domain, but schema explicitly names a distinct subsidiary/third party with no token overlap
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org/",
      "@type": "JobPosting",
      "title": "Project Director",
      "hiringOrganization": {
        "@type": "Organization",
        "name": "Completely Unrelated Subsidiary Holding AS"
      },
      "url": "https://nordictech.no/jobs/director"
    }
    </script>
    """
    jobs = extract_jobs_from_jsonld(html, "https://nordictech.no/jobs", mock_profile)
    # Should be rejected or quarantined by parent_subsidiary_boundary_gate
    assert len(jobs) == 0


def test_wrong_company_rejection(mock_profile):
    # Job candidate from an external recruiter domain (e.g. Finn.no) with unrelated company
    cand = {"title": "Warehouse Worker", "hiring_organization": "Totally Different Logistics AS"}
    assessment = verify_job_identity(mock_profile, cand, "https://www.finn.no/job/fulltime/ad.html?finnkode=123456")
    assert assessment["verified"] is False
    assert assessment["score"] <= 0.40


def test_ats_corroborated_match(mock_profile):
    # External ATS (e.g. Webcruiter/Finn) with matching legal name
    cand = {"title": "Software Developer", "hiring_organization": "Nordic Tech Innovations AS"}
    assessment = verify_job_identity(mock_profile, cand, "https://webcruiter.com/job/987654")
    assert assessment["verified"] is True
    assert assessment["score"] >= 0.90


def test_generic_career_page_abstention(mock_profile):
    # Career page has general text ("Send open application") but NO distinct job openings
    html = """
    <html>
    <body>
      <h2>Karriere hos oss</h2>
      <p>Vi er alltid på jakt etter dyktige medarbeidere! Send gjerne en åpen søknad til post@nordictech.no.</p>
    </body>
    </html>
    """
    material = {
        "status": "available",
        "source_url": "https://nordictech.no",
        "value": {
            "final_url": "https://nordictech.no",
            "registered_domain": "nordictech.no",
            "pages": [{"url": "https://nordictech.no/karriere", "html": html, "main_text_excerpt": "Vi er alltid på jakt etter dyktige medarbeidere"}],
        }
    }
    ev = extract_job_evidence(mock_profile, material)
    assert ev["status"] == "not_found"
    assert ev["value"]["total_active_jobs"] == 0
    assert len(ev["value"]["jobs"]) == 0


def test_extract_job_evidence_success(mock_profile):
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org/",
      "@type": "JobPosting",
      "title": "Lead Cloud Architect",
      "datePosted": "2026-09-10",
      "validThrough": "2026-10-15",
      "jobLocation": {"address": {"addressLocality": "Oslo"}},
      "url": "https://nordictech.no/jobs/cloud-arch"
    }
    </script>
    """
    material = {
        "status": "available",
        "source_url": "https://nordictech.no",
        "value": {
            "final_url": "https://nordictech.no",
            "registered_domain": "nordictech.no",
            "pages": [{"url": "https://nordictech.no/jobs", "html": html, "title": "Careers"}],
        }
    }
    ev = extract_job_evidence(mock_profile, material)
    assert ev["status"] == "available"
    assert ev["value"]["total_active_jobs"] == 1
    assert ev["value"]["jobs"][0]["job_title"] == "Lead Cloud Architect"
    assert ev["value"]["jobs"][0]["deadline"] == "2026-10-15"
    assert ev["value"]["jobs"][0]["published_at"] == "2026-09-10"
    assert ev["content_sha256"] is not None
