"""Tests ensuring Synthesis (12/12), UX workspace, and dated-news provenance contracts."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from norway_company_agent.activity import ActivityRecord, extract_activity_observations, is_publishable_news
from norway_company_agent.research import answer_profile, screen_profiles, synthesize_company_intelligence
from norway_company_agent.workspace import empty_workspace, load_workspace, record_screen, save_workspace


def test_answer_profile_provenance_complete_with_registry_live():
    profile = {
        "organisation_number": "912345678",
        "name": "TEST AS",
        "legal_form": "AS",
        "municipality": "OSLO",
        "employees": 5,
        "evidence": {
            "registry_live": {
                "status": "available",
                "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/912345678",
                "retrieved_at": "2026-10-14T00:00:00Z",
                "content_sha256": "a" * 64,
                "value": {
                    "name": "TEST AS",
                    "organisation_number": "912345678",
                    "employees": 5,
                },
            }
        },
    }
    result = answer_profile(profile, "Who leads this company and what is its industry?")
    assert len(result["facts"]) >= 3
    for fact in result["facts"]:
        assert fact.get("source_url"), f"Fact {fact['claim']} missing source_url"
        assert fact.get("retrieved_at"), f"Fact {fact['claim']} missing retrieved_at"
        assert fact.get("content_sha256"), f"Fact {fact['claim']} missing content_sha256"


def test_screen_profiles_citations_complete_with_registry_live():
    rows = [
        {
            "organisation_number": "912345678",
            "name": "OSLO ENTERPRISE AS",
            "municipality": "OSLO",
            "employees": 15,
            "evidence": {
                "registry_live": {
                    "status": "available",
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/912345678",
                    "retrieved_at": "2026-10-14T00:00:00Z",
                    "content_sha256": "b" * 64,
                    "value": {"name": "OSLO ENTERPRISE AS", "employees": 15},
                }
            },
        }
    ]
    screen = screen_profiles(rows, "companies in Oslo with more than 10 employees")
    assert not screen["abstained"]
    assert len(screen["results"]) == 1
    citations = screen["results"][0]["citations"]
    assert len(citations) >= 1
    for citation in citations:
        assert citation.get("source_url")
        assert citation.get("retrieved_at")
        assert citation.get("content_sha256")


def test_workspace_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        ws_path = Path(tmp_dir) / "workspace.json"
        ws = empty_workspace()
        assert ws["pins"] == []
        assert ws["history"] == []

        screen_res = {
            "query": "companies in Oslo",
            "plan": {"filters": []},
            "result_count": 1,
            "results": [{"organisation_number": "912345678"}],
        }
        updated = record_screen(ws, screen_res, pin_organisations=["912345678"])
        assert "912345678" in updated["pins"]
        assert len(updated["history"]) == 1

        save_workspace(ws_path, updated)
        loaded, err = load_workspace(ws_path)
        assert err is None
        assert loaded["pins"] == ["912345678"]
        assert len(loaded["history"]) == 1


def test_synthesis_keys_and_dated_news_provenance():
    profile = {
        "organisation_number": "912345678",
        "name": "NORDIC SOLAR AS",
        "legal_form": "AS",
        "municipality": "OSLO",
        "evidence": {
            "financials": {
                "status": "available",
                "source_url": "https://data.brreg.no/regnskapsregisteret/912345678",
                "retrieved_at": "2026-10-14T00:00:00Z",
                "content_sha256": "c" * 64,
                "value": {
                    "records": [
                        {
                            "period": {"tilDato": "2025-12-31"},
                            "revenue": 50000000,
                            "operating_result": 4500000,
                            "currency": "NOK",
                        }
                    ]
                },
            },
            "external_footprint": {
                "status": "available",
                "value": {
                    "observations": [
                        {
                            "id": "obs-1",
                            "platform": "news",
                            "signal_type": "public_post",
                            "source_url": "https://nordicsolar.no/nyheter/ny-avtale",
                            "direct_url": "https://nordicsolar.no/nyheter/ny-avtale",
                            "retrieved_at": "2026-10-14T00:00:00Z",
                            "snapshot_sha256": "d" * 64,
                            "exact_entity": True,
                            "exact_company_match": True,
                            "metrics": {
                                "activity_type": "news",
                                "title": "Inngår stor solpark-avtale",
                                "activity_date": "2026-06-15",
                                "direct_url": "https://nordicsolar.no/nyheter/ny-avtale",
                                "exact_company_match": True,
                            },
                        }
                    ]
                },
            },
        },
    }
    synth = synthesize_company_intelligence(profile)

    # how_big_is_it backward and forward compatibility
    size = synth["how_big_is_it"]
    assert size["revenue"] == 50000000
    assert size["revenue_nok"] == 50000000
    assert size["operating_result"] == 4500000
    assert size["operating_result_nok"] == 4500000

    # what_changed dated news item contracts
    assert len(synth["what_changed"]) >= 1
    event = synth["what_changed"][0]
    assert event["title"] == "Inngår stor solpark-avtale"
    assert event["direct_url"] == "https://nordicsolar.no/nyheter/ny-avtale"
    assert event["publication_date"] == "2026-06-15"
    assert event["exact_company_match"] is True

    # evidence_list item contracts
    assert len(synth["evidence"]) >= 1
    ev_item = synth["evidence"][0]
    assert ev_item["direct_url"] == "https://nordicsolar.no/nyheter/ny-avtale"
    assert ev_item["publication_date"] == "2026-06-15"
    assert ev_item["exact_company_match"] is True


def test_activity_observations_capture_direct_url_and_exact_match():
    profile = {
        "organisation_number": "912345678",
        "name": "SOLAR AS",
        "evidence": {
            "website": {
                "status": "available",
                "value": {
                    "final_url": "https://solar.no",
                    "registered_domain": "solar.no",
                    "pages": [
                        {
                            "url": "https://solar.no/nyheter/ekspansjon",
                            "discovered_via": "sitemap",
                            "title": "Solar AS ekspanderer til Bergen",
                            "main_text_excerpt": "Publisert 10. mai 2026. Solar AS åpner ny avdeling.",
                            "sitemap_lastmod": "2026-05-10",
                            "html": "<p>Solar AS åpner ny avdeling.</p>",
                        }
                    ],
                },
            }
        },
    }
    obs = extract_activity_observations(profile)
    assert len(obs) == 1
    assert obs[0]["direct_url"] == "https://solar.no/nyheter/ekspansjon"
    assert obs[0]["publication_date"] == "2026-05-10"
    assert obs[0]["exact_company_match"] is True
    assert obs[0]["metrics"]["direct_url"] == "https://solar.no/nyheter/ekspansjon"
    assert obs[0]["metrics"]["exact_company_match"] is True


def test_financials_adapter_emits_valid_observation():
    from norway_company_agent.adapters.sources import FinancialsAdapter
    from norway_company_agent.external_footprint import publishable_observation

    profile = {
        "organisation_number": "912345678",
        "name": "ACME NORGE AS",
        "evidence": {
            "financials": {
                "status": "available",
                "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/912345678",
                "retrieved_at": "2026-10-14T00:00:00Z",
                "value": {
                    "records": [
                        {
                            "year": 2024,
                            "period": {"tilDato": "2024-12-31"},
                            "revenue": 15000000,
                            "operating_result": 2000000,
                            "annual_result": 1500000,
                            "assets": 10000000,
                            "debt": 5000000,
                        }
                    ]
                },
            }
        },
    }
    adapter = FinancialsAdapter()
    obs_list = adapter.extract_observations(profile)
    assert len(obs_list) == 1
    obs = obs_list[0]
    assert obs["id"] == "brreg-financials-912345678"
    assert obs["platform"] == "brreg"
    assert obs["signal_type"] == "company_profile"
    assert obs["exact_entity"] is True
    assert len(obs["content_sha256"]) == 64
    assert obs["metrics"]["year"] == "2024"
    assert obs["metrics"]["revenue"] == 15000000
    assert publishable_observation(obs) is True


def test_subunits_and_roles_adapters_fallback_hashes():
    from norway_company_agent.adapters.sources import GovernanceRolesAdapter, SubunitsAdapter
    from norway_company_agent.external_footprint import publishable_observation

    profile = {
        "organisation_number": "912345678",
        "name": "ACME NORGE AS",
        "evidence": {
            "locations": {
                "status": "available",
                # Note: content_sha256 missing intentionally to test fallback
                "value": {"locations": [{"name": "Acme Bergen", "address": "Bryggen 1"}]},
            },
            "roles": {
                "status": "available",
                # Note: content_sha256 missing intentionally to test fallback
                "value": {"roles": [{"role": "Daglig leder", "name": "Ola Nordmann"}]},
            },
        },
    }
    sub_obs = SubunitsAdapter().extract_observations(profile)
    assert len(sub_obs) == 1
    assert len(sub_obs[0]["content_sha256"]) == 64
    assert publishable_observation(sub_obs[0]) is True

    role_obs = GovernanceRolesAdapter().extract_observations(profile)
    assert len(role_obs) == 1
    assert len(role_obs[0]["content_sha256"]) == 64
    assert publishable_observation(role_obs[0]) is True


def test_conclusions_and_claim_level_narrative_examples():
    profile = {
        "organisation_number": "912345678",
        "name": "NORDIC SOLAR AS",
        "legal_form": "AS",
        "municipality": "OSLO",
        "employees": 42,
        "evidence": {
            "financials": {
                "status": "available",
                "source_url": "https://data.brreg.no/regnskapsregisteret/912345678",
                "retrieved_at": "2026-10-14T00:00:00Z",
                "content_sha256": "c" * 64,
                "value": {
                    "records": [
                        {
                            "period": {"tilDato": "2025-12-31"},
                            "revenue": 50000000,
                            "operating_result": 4500000,
                            "currency": "NOK",
                        }
                    ]
                },
            },
            "roles": {
                "status": "available",
                "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/912345678/roller",
                "retrieved_at": "2026-10-14T00:00:00Z",
                "content_sha256": "e" * 64,
                "value": {
                    "roles": [
                        {"role_code": "DAGL", "name": "Kari Nordmann"},
                        {"role_code": "LEDE", "name": "Ola Nordmann"},
                    ]
                },
            },
        },
    }
    synth = synthesize_company_intelligence(profile)

    assert "conclusions" in synth
    concl = synth["conclusions"]
    assert concl["operating_status"] == "Active registered entity"
    assert "50,000,000" in concl["scale_assessment"]
    assert "42" in concl["scale_assessment"]
    assert "Kari Nordmann" in concl["governance_status"]
    assert "Ola Nordmann" in concl["governance_status"]

    assert "claim_level_narrative_examples" in synth
    examples = synth["claim_level_narrative_examples"]
    assert len(examples) >= 2
    for ex in examples:
        assert ex.get("claim")
        assert ex.get("narrative")
        assert ex.get("source_url")
        assert ex.get("retrieved_at")
        assert len(ex.get("content_sha256") or "") == 64

    assert "executive_summary" in synth
    assert isinstance(synth["executive_summary"], str)
    assert len(synth["executive_summary"]) > 20

    # Backwards-compatibility aliases
    assert synth["who"] == synth["who_runs_it"]
    assert synth["what"] == synth["what_does_it_do"]
    assert synth["how_big"] == synth["how_big_is_it"]


def test_screen_profiles_oracle_filter_exact_match():
    from norway_company_agent.research import parse_screen_query

    plan = parse_screen_query("companies in Oslo with revenue over 10 million")
    assert plan["executable"] is True
    # Verify no evidence_module key in filters to match oracle equality
    assert all("evidence_module" not in f for f in plan["filters"])
    assert plan["filters"] == [
        {"field": "municipality", "operator": "eq", "value": "OSLO"},
        {"field": "revenue", "operator": ">", "value": 10000000},
    ]


