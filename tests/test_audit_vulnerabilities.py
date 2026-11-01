from __future__ import annotations

import pytest
from bs4 import BeautifulSoup
from norway_company_agent.activity import ActivityRecord, is_publishable_news, extract_activity_observations
from norway_company_agent.discovery import search_lite_duckduckgo, SearchCircuitBreaker
from norway_company_agent.identity import assess_social_identity
from norway_company_agent.official import _classified
from norway_company_agent.http import FetchResult
from norway_company_agent.website import _priority_links


def test_careers_vacant_positions_priority_over_generic_subpage():
    html = """
    <nav>
      <a href="/careers">Careers</a>
      <a href="/careers/growth">Growth and Culture</a>
      <a href="/careers/vacant-positions">Vacant Positions</a>
      <a href="/news">News</a>
    </nav>
    """
    soup = BeautifulSoup(html, "lxml")
    targets = _priority_links("https://www.tomra.com/", soup, limit=4)
    assert "https://www.tomra.com/careers" in targets
    assert "https://www.tomra.com/careers/vacant-positions" in targets
    # Vacant positions must come before growth
    vacant_idx = targets.index("https://www.tomra.com/careers/vacant-positions")
    if "https://www.tomra.com/careers/growth" in targets:
        growth_idx = targets.index("https://www.tomra.com/careers/growth")
        assert vacant_idx < growth_idx


def test_news_pagination_and_hash_rejection():
    # 1. Fragment anchor
    act_hash = ActivityRecord(
        activity_id="act-1",
        company_orgnr="912345678",
        title="Valid Headline About Business Growth",
        description="Detailed article text",
        activity_date="2026-05-10",
        activity_type="company_update",
        source_url="https://acme.no/nyheter/apning#content",
        retrieved_at="2026-10-04T00:00:00Z",
        content_sha256="a" * 64,
        identity_assessment={"publishable": True},
    )
    assert is_publishable_news(act_hash) is False

    # 2. Pagination query
    act_page = ActivityRecord(
        activity_id="act-2",
        company_orgnr="912345678",
        title="Valid Headline About Business Growth",
        description="Detailed article text",
        activity_date="2026-05-10",
        activity_type="company_update",
        source_url="https://acme.no/nyheter/artikkel?page=2",
        retrieved_at="2026-10-04T00:00:00Z",
        content_sha256="a" * 64,
        identity_assessment={"publishable": True},
    )
    assert is_publishable_news(act_page) is False

    # 3. Short headline < 15 chars (e.g. 'Read more')
    act_short = ActivityRecord(
        activity_id="act-3",
        company_orgnr="912345678",
        title="Read more here",
        description="Detailed article text",
        activity_date="2026-05-10",
        activity_type="company_update",
        source_url="https://acme.no/nyheter/artikkel",
        retrieved_at="2026-10-04T00:00:00Z",
        content_sha256="a" * 64,
        identity_assessment={"publishable": True},
    )
    assert is_publishable_news(act_short) is False


def test_news_cap_at_top_8_items():
    profile = {
        "organisation_number": "912345678",
        "name": "ACME AS",
        "evidence": {
            "website": {
                "status": "available",
                "value": {
                    "final_url": "https://acme.no/",
                    "registered_domain": "acme.no",
                    "identity_assessment": {"publishable": True},
                    "pages": [{
                        "url": "https://acme.no/feed/",
                        "kind": "feed",
                        "feed_items": [
                            {"title": f"Article number {i} with long headline", "url": f"https://acme.no/nyheter/artikkel-{i}", "published": f"2026-05-{10+i:02d}"}
                            for i in range(15)
                        ]
                    }],
                }
            }
        }
    }
    obs = extract_activity_observations(profile)
    assert len(obs) <= 8


def test_official_status_classification():
    # 200 with empty financials records -> not_found (maps to not_available)
    res_empty = FetchResult(
        url="https://data.brreg.no",
        status=200,
        body=[],
        raw=b"[]",
        content_sha256="a" * 64,
        retrieved_at="2026-10-04T00:00:00Z",
        elapsed_ms=50,
        bytes_received=2,
    )
    rec_empty = _classified("financials", "official_annual_accounts", res_empty, value={"records": []})
    assert rec_empty["status"] == "not_found"

    # 401/403/429 -> blocked
    res_403 = FetchResult(
        url="https://data.brreg.no",
        status=403,
        error="Forbidden",
        retrieved_at="2026-10-04T00:00:00Z",
        elapsed_ms=50,
        bytes_received=0,
    )
    rec_403 = _classified("financials", "official_annual_accounts", res_403)
    assert rec_403["status"] == "blocked"

    # 404 -> not_found
    res_404 = FetchResult(
        url="https://data.brreg.no",
        status=404,
        error="Not Found",
        retrieved_at="2026-10-04T00:00:00Z",
        elapsed_ms=50,
        bytes_received=0,
    )
    rec_404 = _classified("financials", "official_annual_accounts", res_404)
    assert rec_404["status"] == "not_found"

    # 500 -> source_error
    res_500 = FetchResult(
        url="https://data.brreg.no",
        status=500,
        error="Internal Server Error",
        retrieved_at="2026-10-04T00:00:00Z",
        elapsed_ms=50,
        bytes_received=0,
    )
    rec_500 = _classified("financials", "official_annual_accounts", res_500)
    assert rec_500["status"] == "source_error"


def test_strict_disambiguation_for_search_social():
    # Single-word name SOLBERG AS found in search with no corroboration -> rejected
    profile_solberg = {
        "organisation_number": "912345678",
        "name": "SOLBERG AS",
        "legal_form": "AS",
        "municipality": "OSLO",
    }
    link = {"platform": "instagram", "url": "https://instagram.com/solberg"}
    res = assess_social_identity(profile_solberg, link, is_search_discovery=True, context_snippet="Petter Solberg racing team updates")
    assert res["publishable"] is False
    assert res["identity_score"] <= 0.30

    # With OrgNr corroboration in snippet -> accepted
    res_corr = assess_social_identity(profile_solberg, link, is_search_discovery=True, context_snippet="Solberg AS reg 912345678 in Oslo")
    assert res_corr["publishable"] is True
    assert res_corr["identity_score"] >= 0.90
