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


def test_isabella_cafe_foreign_com_domain_rejection():
    from norway_company_agent.identity import apply_website_identity_gate

    profile = {
        "name": "ISABELLA CAFE AS",
        "organisation_number": "932415313",
        "legal_form": "AS",
        "municipality": "RINGERIKE",
    }
    record = {
        "status": "available",
        "value": {
            "final_url": "https://www.isabellacafe.com/",
            "title": "Home | Isabella's Cafe Italian Restaurant | Tinley Park, IL",
            "main_text_excerpt": "Welcome to Isabella's Cafe located in Tinley Park, Illinois.",
        },
    }
    gate = apply_website_identity_gate(profile, record)
    assert gate["assessment"]["publishable"] is False
    assert gate["assessment"]["score"] <= 0.85


def test_registry_com_domain_still_accepted_with_statutory_anchor():
    from norway_company_agent.identity import apply_website_identity_gate

    profile = {
        "name": "EQUINOR ASA",
        "organisation_number": "923609016",
        "legal_form": "ASA",
        "municipality": "STAVANGER",
        "website": "https://www.equinor.com",
        "evidence": {"registry": {"value": {"hjemmeside": "www.equinor.com"}}},
    }
    record = {
        "status": "available",
        "value": {
            "final_url": "https://www.equinor.com/no",
            "title": "Equinor - Et bredt energiselskap",
            "main_text_excerpt": "Equinor er et internasjonalt energiselskap med virksomhet i mer enn 30 land og ledende innen offshore fornybar energi.",
        },
    }
    gate = apply_website_identity_gate(profile, record)
    assert gate["assessment"]["publishable"] is True
    assert gate["assessment"]["score"] >= 0.90


def test_cms_vendor_social_handle_rejection():
    from norway_company_agent.website import normalize_social_url, _social_links, structured_social_links
    from norway_company_agent.identity import assess_social_identity

    # 1. normalize_social_url drops vendor handles
    assert normalize_social_url("http://twitter.com/squarespace") is None
    assert normalize_social_url("https://facebook.com/wix") is None
    assert normalize_social_url("https://instagram.com/wordpress") is None

    # 2. _social_links drops footer vendor links
    html = """
    <footer>
      <a href="http://twitter.com/squarespace">Follow us</a>
      <a href="https://instagram.com/lowehjerte">Real Profile</a>
    </footer>
    """
    soup = BeautifulSoup(html, "lxml")
    links = _social_links("https://lowehjerte.no", soup)
    assert not any("squarespace" in l["url"] for l in links)
    assert any("lowehjerte" in l["url"] for l in links)

    # 3. structured_social_links drops CMS template JSON-LD
    schema = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Squarespace Template",
        "sameAs": ["https://twitter.com/squarespace", "https://instagram.com/squarespace"],
    }
    struct_links = structured_social_links(schema, found_on="https://lowehjerte.no")
    assert len(struct_links) == 0

    # 4. assess_social_identity marks CMS provider handle as unpublishable
    profile = {
        "name": "LØWEHJERTE DESIGN AS",
        "organisation_number": "921838840",
    }
    assessment = assess_social_identity(profile, {"platform": "x", "url": "https://x.com/squarespace"})
    assert assessment["publishable"] is False
    assert assessment["identity_score"] <= 0.2


def test_job_postings_emitted_as_verified_job_opening_claims():
    from norway_company_agent.research import answer_profile

    profile = {
        "organisation_number": "912345678",
        "name": "ACME AS",
        "evidence": {
            "registry": {
                "status": "available",
                "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/912345678",
                "retrieved_at": "2026-10-04T00:00:00Z",
                "content_sha256": "f" * 64,
                "value": {"navn": "ACME AS"},
            },
            "external_footprint": {
                "status": "available",
                "source_url": "https://acme.no",
                "retrieved_at": "2026-10-04T00:00:00Z",
                "content_sha256": "e" * 64,
                "value": {
                    "observations": [
                        {
                            "id": "job-912345678-abc",
                            "organisation_number": "912345678",
                            "platform": "job_board",
                            "signal_type": "job_posting",
                            "source_url": "https://acme.teamtailor.com/jobs/123",
                            "retrieved_at": "2026-10-04T00:00:00Z",
                            "content_sha256": "1" * 64,
                            "exact_entity": True,
                            "metrics": {
                                "job_title": "Senior Cloud Engineer",
                                "location": "Oslo",
                            },
                        },
                        {
                            "id": "hiring-signal-912345678",
                            "organisation_number": "912345678",
                            "platform": "job_board",
                            "signal_type": "hiring_signal",
                            "source_url": "https://acme.no/karriere",
                            "retrieved_at": "2026-10-04T00:00:00Z",
                            "content_sha256": "2" * 64,
                            "exact_entity": True,
                            "metrics": {
                                "job_board": "teamtailor.com",
                            },
                        },
                    ]
                },
            },
        },
    }

    res = answer_profile(profile, "Does ACME AS have any job openings?")
    facts = res["facts"]
    job_facts = [f for f in facts if f["claim"] == "Verified job opening"]
    assert len(job_facts) == 1
    assert job_facts[0]["value"] == "Senior Cloud Engineer (ACME AS)"
    assert job_facts[0]["classification"] == "company_verified_job_posting"
    assert job_facts[0]["source_url"] == "https://acme.teamtailor.com/jobs/123"
    assert job_facts[0]["content_sha256"] == "1" * 64

    hiring_facts = [f for f in facts if f["claim"] == "Verified hiring signal"]
    assert len(hiring_facts) == 1
    assert "teamtailor.com" in hiring_facts[0]["value"]
    assert hiring_facts[0]["classification"] == "company_verified_hiring_signal"


def test_buyer_first_summary_starts_with_commercial_scale_and_citations():
    from norway_company_agent.research import generate_deterministic_company_summary

    profile = {
        "organisation_number": "923609016",
        "name": "EQUINOR ASA",
        "legal_form": "ASA",
        "municipality": "STAVANGER",
        "employees": 23000,
        "evidence": {
            "financials": {
                "status": "available",
                "value": {
                    "records": [
                        {"year": 2024, "revenue": 100_000_000, "currency": "NOK"},
                        {"year": 2023, "revenue": 80_000_000, "currency": "NOK"},
                    ]
                },
            },
            "website": {
                "status": "available",
                "value": {
                    "final_url": "https://www.equinor.com",
                    "identity_assessment": {"publishable": True},
                },
            },
        },
    }

    summary = generate_deterministic_company_summary(profile)
    # 1. Must open with revenue, year, YoY %, and explicit citation
    assert summary.startswith("Reported NOK 100,000,000 revenue in 2024 (up +25.0% from 2023) with 23000 registered employees according to Regnskapsregisteret annual accounts and Brønnøysund Enhetsregisteret.")
    # 2. Must not start with boilerplate
    assert not summary.startswith("EQUINOR ASA (Org.nr")
    # 3. Sentence 2 must state what company does and scale in municipality
    assert "Based in STAVANGER, EQUINOR ASA (Org.nr 923609016) is a registered ASA" in summary
    # 4. Sentence 3 must cite verified website host
    assert "Verified public signals include its verified website (www.equinor.com)." in summary
    # 5. Final sentence must state explicit unknowns
    assert "Still unknown:" in summary


def test_buyer_first_summary_for_unfiled_accounts():
    from norway_company_agent.research import generate_deterministic_company_summary

    profile = {
        "organisation_number": "932415313",
        "name": "ISABELLA CAFE AS",
        "legal_form": "AS",
        "municipality": "RINGERIKE",
        "industry_label": "Bakervarer",
        "employees": 4,
        "evidence": {},
    }

    summary = generate_deterministic_company_summary(profile)
    assert summary.startswith("Operates with 4 registered employees in RINGERIKE according to Brønnøysund Enhetsregisteret.")
    assert "Based in RINGERIKE, ISABELLA CAFE AS (Org.nr 932415313) is a registered AS operating in Bakervarer." in summary
    assert "Still unknown: annual financial accounts have not been filed with Regnskapsregisteret" in summary


def test_no_homonym_collision_rejection():
    """SOLBERG HOLDING AS in Tromsø guessing solberg.no without Brreg link or OrgNr must be rejected."""
    from norway_company_agent.identity import assess_website_identity

    profile = {
        "organisation_number": "999888777",
        "name": "SOLBERG HOLDING AS",
        "legal_form": "AS",
        "municipality": "TROMSØ",
        "evidence": {
            "registry": {
                "value": {
                    "forretningsadresse.postnummer": "9008",
                    "forretningsadresse.poststed": "TROMSØ",
                    "forretningsadresse.kommune": "TROMSØ",
                }
            },
            "website": {
                "status": "available",
                "value": {
                    "url": "https://solberg.no",
                    "final_url": "https://solberg.no",
                    "title": "Solberg Bil - Din forhandler i Drammen",
                    "description": "Velkommen til Solberg Bil AS i Drammen",
                    "main_text_excerpt": "Solberg Bil AS, Bragernes Torg 1, 3017 Drammen. Tlf: 32800000. Org.nr: 888777666 MVA.",
                },
            },
        },
    }
    assessment = assess_website_identity(profile)
    assert assessment["publishable"] is False
    assert assessment["score"] < 0.90


def test_agency_footer_social_link_rejection():
    """Web agency footer link ('Design av Mediabyrået') must not be extracted as company social link."""
    from bs4 import BeautifulSoup
    from norway_company_agent.website import _social_links

    html = """
    <html>
    <body>
        <main>
            <h1>Velkommen til Bedriften</h1>
            <p>Vi leverer kvalitetsprodukter over hele Norge.</p>
        </main>
        <footer>
            <div class="company-social">
                <a href="https://www.facebook.com/bedriftenas">Følg oss på Facebook</a>
            </div>
            <div class="developer-credit">
                <span>Design og webutvikling av</span>
                <a href="https://www.facebook.com/mediabyraetas">Mediabyrået på Facebook</a>
            </div>
        </footer>
    </body>
    </html>
    """
    soup = BeautifulSoup(html, "html.parser")
    links = _social_links("https://bedriften.no", soup)
    urls = [link["url"] for link in links]
    assert "https://facebook.com/bedriftenas" in urls
    assert "https://facebook.com/mediabyraetas" not in urls


def test_social_generic_word_handle_rejection():
    """Social handle matching only generic business words like 'design' or 'cafe' must be rejected."""
    from norway_company_agent.identity import assess_social_identity

    profile = {
        "organisation_number": "912345678",
        "name": "LØWEHJERTE DESIGN AS",
        "legal_form": "AS",
        "municipality": "OSLO",
    }
    link = {"platform": "instagram", "url": "https://instagram.com/design"}
    assessed = assess_social_identity(profile, link, site_root="lowehjerte")
    assert assessed["publishable"] is False
    assert assessed["identity_score"] <= 0.30



