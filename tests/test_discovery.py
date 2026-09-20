from __future__ import annotations

import pytest
from norway_company_agent.discovery import (
    CandidateRejectionReason,
    CandidateSource,
    assess_candidate_funnel,
    classify_source_type_from_url,
    generate_brreg_relationship_candidates,
    generate_company_candidate_sources,
    generate_deterministic_domain_candidates,
    normalize_candidate_url,
)


def test_normalize_candidate_url():
    assert normalize_candidate_url("https://www.example.no/") == "https://example.no/"
    assert normalize_candidate_url("http://example.no") == "https://example.no/"
    assert normalize_candidate_url("https://example.no/about/") == "https://example.no/about"
    assert normalize_candidate_url(None) is None
    assert normalize_candidate_url("") is None


def test_classify_source_type_from_url():
    assert classify_source_type_from_url("https://example.no/") == "website"
    assert classify_source_type_from_url("https://example.no/karriere") == "careers"
    assert classify_source_type_from_url("https://example.no/careers") == "careers"
    assert classify_source_type_from_url("https://example.no/job/12345") == "jobs"
    assert classify_source_type_from_url("https://example.no/nyheter") == "news"
    assert classify_source_type_from_url("https://linkedin.com/company/example") == "social"


def test_generate_deterministic_domain_candidates_norwegian_characters():
    profile = {
        "name": "BLÅTT OG GRØNT BRYGGERI AS",
        "organisation_number": "912345678",
    }
    cands = generate_deterministic_domain_candidates(profile, max_candidates=6)
    assert len(cands) <= 6
    assert len(cands) > 0
    # Checks that norwegian characters æ, ø, å are normalized to a, o
    for c in cands:
        assert "å" not in c
        assert "ø" not in c
        assert "æ" not in c
        assert c.startswith("https://")


def test_generate_deterministic_domain_candidates_capped():
    profile = {
        "name": "NORDIC DIGITAL INNOVATION SOLUTIONS NORWAY AS",
        "organisation_number": "912345678",
    }
    cands = generate_deterministic_domain_candidates(profile, max_candidates=4)
    assert len(cands) == 4
    # All unique
    assert len(set(cands)) == len(cands)


def test_generate_brreg_relationship_candidates():
    profile = {
        "name": "HOLDING SELSKAPET AS",
        "organisation_number": "987654321",
        "evidence": {
            "registry": {
                "value": {
                    "epostadresse": "kontakt@operativedrift.no",
                }
            },
            "locations": {
                "value": {
                    "locations": [
                        {"name": "OSLO KAFFEBRENNERI AVDELING 1"},
                    ]
                }
            }
        }
    }
    rel_cands = generate_brreg_relationship_candidates(profile)
    assert len(rel_cands) >= 2
    # Email domain candidate
    email_cand = next((c for c in rel_cands if c.discovery_tier == "tier2_email_domain"), None)
    assert email_cand is not None
    assert "operativedrift.no" in email_cand.url
    assert "kontakt@operativedrift.no" in email_cand.discovery_reason

    # Subunit brand candidate
    sub_cand = next((c for c in rel_cands if c.discovery_tier == "tier2_brreg_relationship"), None)
    assert sub_cand is not None
    assert "oslokaffebrenneri" in sub_cand.url or "oslo-kaffebrenneri" in sub_cand.url


def test_generate_brreg_relationship_generic_email_ignored():
    profile = {
        "name": "TEST AS",
        "evidence": {
            "registry": {
                "value": {
                    "epostadresse": "owner@gmail.com",
                }
            }
        }
    }
    rel_cands = generate_brreg_relationship_candidates(profile)
    assert len(rel_cands) == 0


def test_candidate_source_dataclass_separation():
    cand = CandidateSource(
        url="https://testfirm.no/",
        source_type="website",
        discovery_tier="tier1_deterministic_domain",
        discovery_reason="Legal name token match",
    )
    assert cand.verification_status == "unverified"
    assert cand.identity_score == 0.0
    assert cand.identity_evidence == {}
    assert cand.rejection_reason is None

    # Verification phase update
    cand.verification_status = "verified"
    cand.identity_score = 0.95
    cand.identity_evidence = {"matched_tokens": ["testfirm"], "exact_orgnr": True}

    d = cand.to_dict()
    assert d["discovery_tier"] == "tier1_deterministic_domain"
    assert d["verification_status"] == "verified"
    assert d["identity_score"] == 0.95


def test_assess_candidate_funnel_with_verified_and_rejection():
    profile = {
        "name": "TEST FIRMA AS",
        "organisation_number": "999888777",
    }
    candidates = [
        CandidateSource(
            url="https://proff.no/selskap/test",
            source_type="website",
            discovery_tier="tier3_public_search",
            discovery_reason="Search result",
        ),
        CandidateSource(
            url="https://testfirma-dead.no/",
            source_type="website",
            discovery_tier="tier1_deterministic_domain",
            discovery_reason="Permutation 1",
        ),
        CandidateSource(
            url="https://testfirma-parked.no/",
            source_type="website",
            discovery_tier="tier1_deterministic_domain",
            discovery_reason="Permutation 2",
        ),
        CandidateSource(
            url="https://testfirma.no/",
            source_type="website",
            discovery_tier="tier1_deterministic_domain",
            discovery_reason="Permutation 3",
        ),
    ]

    def mock_fetch(url: str):
        if "proff.no" in url:
            return {"status": "available", "value": {}}, {"requests": 1, "bytes": 100}
        if "dead" in url:
            return {"status": "not_found", "note": "Hostname did not resolve"}, {"requests": 1, "bytes": 0}
        if "parked" in url:
            return {"status": "available", "value": {"title": "Domain for Sale"}}, {"requests": 2, "bytes": 500}
        if "testfirma.no" in url:
            return {"status": "available", "value": {"title": "Test Firma AS", "main_text_excerpt": "Org 999888777"}}, {"requests": 2, "bytes": 2000}
        return {"status": "not_found"}, {"requests": 1, "bytes": 0}

    def mock_identity_gate(prof: dict, web_rec: dict):
        val = web_rec.get("value") or {}
        title = val.get("title") or ""
        if "Domain for Sale" in title:
            return {
                "website": web_rec,
                "assessment": {"publishable": False, "score": 0.1, "is_parked": True, "method": "parked_detector"},
            }
        if "Test Firma AS" in title:
            return {
                "website": web_rec,
                "assessment": {"publishable": True, "score": 1.0, "exact_orgnr": True, "method": "authoritative_match"},
            }
        return {
            "website": web_rec,
            "assessment": {"publishable": False, "score": 0.2, "method": "unrelated"},
        }

    res = assess_candidate_funnel(profile, candidates, mock_fetch, mock_identity_gate, max_fetches=4)
    funnel = res["funnel_metrics"]

    assert funnel["generated"] == 4
    # Aggregator pre-filtered without fetch
    assert funnel["rejection_reasons"][CandidateRejectionReason.GENERIC_AGGREGATOR.value] == 1
    # Dead domain rejected
    assert funnel["rejection_reasons"][CandidateRejectionReason.DEAD_DOMAIN.value] == 1
    # Parked domain rejected
    assert funnel["rejection_reasons"][CandidateRejectionReason.PARKED_DOMAIN.value] == 1
    # 1 verified
    assert funnel["verified"] == 1
    assert len(res["verified_sources"]) == 1
    assert res["verified_sources"][0]["url"] == "https://testfirma.no/"
    assert res["verified_yield"] > 0.0
    assert res["candidate_efficiency"] > 0.0
