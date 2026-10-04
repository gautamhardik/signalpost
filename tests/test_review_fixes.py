"""Regression tests for the issues raised in the Builderr reviews."""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date

import pytest

from norway_company_agent import batch
from norway_company_agent.activity import ActivityRecord, date_from_url, extract_activity_from_html_articles, is_publishable_news
from norway_company_agent.batch import evidence_terminal_state, load_profiles, terminal_envelope, validate_envelopes
from norway_company_agent.evidence import PUBLISHED_STATES, evidence, normalize_evidence_states, normalize_status
from norway_company_agent.evidence_store import EvidenceStore, attach_observation_snapshots, snapshot_website_pages
from norway_company_agent.http import FetchResult
from norway_company_agent.identity import assess_website_identity
from norway_company_agent.jobs import JobRecord, extract_job_observations, is_publishable_job
from norway_company_agent.viewer import build_viewer


# --- result states -----------------------------------------------------------

@pytest.mark.parametrize("legacy,expected", [
    ("not_found", "not_available"),
    ("source_error", "failed"),
    ("budget_exhausted", "failed"),
    ("not_fetched", "failed"),
    ("blocked_robots", "blocked"),
    ("available", "available"),
    ("ambiguous", "ambiguous"),
    ("something_new", "failed"),
])
def test_legacy_states_map_to_contract_states(legacy, expected):
    assert normalize_status(legacy) == expected


def test_envelope_only_uses_contract_states():
    profile = {
        "organisation_number": "912345678",
        "name": "TEST AS",
        "evidence": normalize_evidence_states({
            "registry": evidence("registry", "available", "official_registry_bulk", "https://data.brreg.no"),
            "financials": evidence("financials", "not_found", "official_annual_accounts", "https://data.brreg.no"),
            "roles": evidence("roles", "source_error", "official_roles", "https://data.brreg.no"),
        }),
    }
    envelope = terminal_envelope(profile, run_id="t", modules=["registry", "financials", "roles", "website"], started_at="a", completed_at="b")
    states = {module["state"] for module in envelope["modules"].values()} | {envelope["state"]}
    assert states <= set(PUBLISHED_STATES)
    assert envelope["modules"]["website"]["state"] == "failed"  # missing module is reported, never dropped
    assert validate_envelopes([envelope], 1)["passed"]


def test_unverified_website_is_reported_ambiguous_not_available():
    record = {"status": "available", "value": {"identity_assessment": {"publishable": False}}}
    assert evidence_terminal_state(record) == "ambiguous"


# --- identity: name-only matches on unrelated sites ---------------------------

def _site_profile(name, url, *, title, text="", registry=None):
    return {
        "organisation_number": "912345678",
        "name": name,
        "evidence": {
            "registry": {"value": registry or {}},
            "website": {
                "status": "available",
                "source_url": url,
                "value": {"final_url": url, "title": title, "main_text_excerpt": text, "pages": []},
            },
        },
    }


def test_single_word_name_on_foreign_site_is_not_published():
    text = "Nyati Safari Lodge is a luxury lodge in the Kruger area offering guided game drives. " * 3
    profile = _site_profile("NYATI AS", "https://nyatisafarilodge.co.za/", title="Home - Nyati Safari", text=text,
                            registry={"forretningsadresse.postnummer": "0150", "forretningsadresse.poststed": "OSLO"})
    assert not assess_website_identity(profile)["publishable"]


def test_single_word_name_with_registry_address_on_site_is_published():
    text = "Eltavler AS lager tavler for bygg. Besøk oss i Tomtegata 12, 3050 Mjøndalen. " * 3
    profile = _site_profile("ELTAVLER AS", "https://www.eltavler.no/", title="Eltavler", text=text,
                            registry={"forretningsadresse.adresse": "Tomtegata 12", "forretningsadresse.postnummer": "3050", "forretningsadresse.poststed": "MJØNDALEN"})
    assert assess_website_identity(profile)["publishable"]


def test_registry_website_and_email_domain_confirm_script_only_homepage():
    profile = _site_profile("ELOPAK ASA", "https://www.elopak.com/", title="", text="",
                            registry={"hjemmeside": "www.elopak.com", "epostadresse": "elopak@elopak.com"})
    assert assess_website_identity(profile)["publishable"]


def test_shared_mail_host_does_not_confirm_a_site():
    profile = _site_profile("ACME AS", "https://www.gmail.com/", title="", text="",
                            registry={"hjemmeside": "www.gmail.com", "epostadresse": "acme@gmail.com"})
    assert not assess_website_identity(profile)["publishable"]


# --- hiring: real postings only -----------------------------------------------

def _job(title, url, *, method="html_link", evidence=(), found_on="https://acme.no/karriere"):
    return JobRecord(
        job_id="j", company_orgnr="912345678", job_title=title, location=None, employment_type=None,
        department=None, description=None, published_at=None, deadline=None, source_url=url,
        retrieved_at="2026-10-04T00:00:00Z", content_sha256="0" * 64, identity_assessment={"verified": True},
        extraction_method=method, posting_evidence=tuple(evidence), found_on_url=found_on,
    )


def test_careers_landing_page_is_not_a_job():
    assert not is_publishable_job(_job("Ledige stillinger hos oss", "https://acme.no/karriere", evidence=("posting_terms",)))
    assert not is_publishable_job(_job("Les mer", "https://acme.no/karriere/elektriker", evidence=("deadline",)))
    assert not is_publishable_job(_job("Elektriker", "https://acme.no/karriere/elektriker"))  # no posting evidence


def test_specific_posting_with_evidence_is_a_job():
    assert is_publishable_job(_job("Elektriker", "https://acme.no/karriere/elektriker", evidence=("deadline",)))
    assert is_publishable_job(_job("Prosjektleder", "https://acme.teamtailor.com/jobs/123", evidence=("ats_listing",)))
    assert is_publishable_job(_job("Prosjektleder", "https://acme.no/", method="jsonld"))


def test_homepage_with_career_keywords_publishes_no_hiring_fact():
    html = "<html><body><nav><a href='/karriere'>Karriere</a></nav><p>Vil du jobbe hos oss? Se ledige stillinger.</p></body></html>"
    profile = {
        "organisation_number": "912345678",
        "name": "ACME AS",
        "evidence": {"website": {"status": "available", "source_url": "https://acme.no/", "value": {
            "final_url": "https://acme.no/", "registered_domain": "acme.no",
            "pages": [{"url": "https://acme.no/", "html": html, "title": "Acme"}],
        }}},
    }
    assert extract_job_observations(profile) == []


# --- news: dated single articles only -----------------------------------------

def _news(title, url, when, kind="company_update", found_on="https://acme.no/nyheter"):
    return ActivityRecord(
        activity_id="a", company_orgnr="912345678", activity_type=kind, title=title, description=None,
        activity_date=when, source_url=url, retrieved_at="2026-10-04T00:00:00Z", content_sha256="0" * 64,
        identity_assessment={"verified": True}, found_on_url=found_on,
    )


def test_news_requires_a_dated_individual_article():
    today = date(2026, 10, 4)
    assert is_publishable_news(_news("Ny avtale med Statens vegvesen", "https://acme.no/nyheter/ny-avtale", "2026-09-01"), today)
    assert not is_publishable_news(_news("Ny avtale med Statens vegvesen", "https://acme.no/nyheter/ny-avtale", None), today)
    assert not is_publishable_news(_news("Nyheter og utlysninger", "https://acme.no/nyheter", "2026-09-01"), today)
    assert not is_publishable_news(_news("Ny avtale med Statens vegvesen", "https://acme.no/author/ola/", "2026-09-01"), today)
    assert not is_publishable_news(_news("Strategi og rådgivning", "https://acme.no/#kontakt", "2026-09-01", found_on="https://acme.no/"), today)
    assert not is_publishable_news(_news("Les mer", "https://acme.no/nyheter/ny-avtale", "2026-09-01"), today)
    assert not is_publishable_news(_news("Ny avtale med Statens vegvesen", "https://acme.no/nyheter/ny-avtale", "2027-09-01"), today)


def test_dates_are_read_from_article_urls():
    assert date_from_url("https://patch.no/blog/2026-10-02-notes-on-coverage/") == "2026-10-02"
    assert date_from_url("https://la5b.no/2026/08/10/field-day/") == "2026-08-10"
    assert date_from_url("https://acme.no/om-oss") is None


def test_listing_page_date_is_not_copied_onto_every_card():
    html = """<html><head><meta property="article:published_time" content="2020-03-16"></head><body>
      <article><h3><a href="/news/award-one">Ship design wins award one</a></h3></article>
      <article><h3><a href="/news/award-two">Ship design wins award two</a></h3></article>
    </body></html>"""
    profile = {"organisation_number": "912345678", "name": "ACME AS", "evidence": {"website": {"value": {"registered_domain": "acme.no"}}}}
    records = extract_activity_from_html_articles(html, "https://acme.no/awards", profile)
    assert records and all(record.activity_date is None for record in records)


def test_links_in_a_shared_list_are_dated_individually():
    html = """<html><body><div class="list">
      <a href="/media/press-releases/2026/a">30 September 2026 | Share buyback status update</a>
      <a href="/media/press-releases/2026/b">24 September 2026 | Interim report published</a>
      <a href="/media/press-releases/2026/c">Financial calendar update</a>
    </div></body></html>"""
    profile = {"organisation_number": "912345678", "name": "ACME ASA", "evidence": {"website": {"value": {"registered_domain": "acme.no"}}}}
    dates = {r.title: r.activity_date for r in extract_activity_from_html_articles(html, "https://acme.no/media/press-releases/", profile)}
    assert dates["Share buyback status update"] == "2026-09-30"  # date kept, prefix stripped from title
    assert dates["Interim report published"] == "2026-09-24"
    assert dates["Financial calendar update"] is None


def test_shared_list_deadline_does_not_make_every_link_a_posting():
    html = """<html><body><div>
      <p>Søknadsfrist: 01.11.2026</p>
      <a href="/karriere/om-oss-som-arbeidsgiver">Om oss som arbeidsgiver</a>
      <a href="/karriere/fordeler">Fordeler ved å jobbe her</a>
      <a href="/karriere/kontakt">Kontakt rekruttering</a>
    </div></body></html>"""
    profile = {
        "organisation_number": "912345678", "name": "ACME AS",
        "evidence": {"website": {"status": "available", "source_url": "https://acme.no/", "value": {
            "final_url": "https://acme.no/", "registered_domain": "acme.no",
            "pages": [{"url": "https://acme.no/karriere", "html": html, "title": "Karriere"}],
        }}},
    }
    assert extract_job_observations(profile) == []


# --- evidence store -----------------------------------------------------------

def test_source_pages_are_saved_and_linked(tmp_path):
    store = EvidenceStore(tmp_path / "sources", link_base=tmp_path)
    body = b"<html><body>Acme AS org.nr 912345678</body></html>"
    record = {"status": "available", "value": {"final_url": "https://acme.no/", "pages": [
        {"url": "https://acme.no/", "_raw": body, "html": "<html></html>"},
        {"url": "https://acme.no/nyheter/a", "_raw": b"<html>article</html>"},
    ]}}
    refs = snapshot_website_pages(store, record)
    digest = hashlib.sha256(body).hexdigest()
    assert record["value"]["snapshot_sha256"] == digest
    assert all("_raw" not in page and "html" not in page for page in record["value"]["pages"])
    assert gzip.decompress((tmp_path / record["value"]["snapshot_path"]).read_bytes()) == body

    observations = [
        {"source_url": "https://acme.no/nyheter/a", "signal_type": "public_post"},
        {"source_url": "https://facebook.com/acme", "signal_type": "profile_handle"},
    ]
    attach_observation_snapshots(observations, refs, "https://acme.no/")
    assert observations[0]["snapshot_sha256"] == hashlib.sha256(b"<html>article</html>").hexdigest()
    assert observations[1]["snapshot_sha256"] == digest

    snapshot_website_pages(store, {"value": {"pages": [{"url": "https://acme.no/", "_raw": body}]}})
    assert store.summary()["reused"] == 1  # identical source bytes are stored once


# --- unseen companies ---------------------------------------------------------

def test_unknown_company_still_gets_exactly_one_result(monkeypatch):
    def fake_fetch(url, **_):
        if url.endswith("/999999999"):
            return FetchResult(url, 404, 1, 0, error="HTTP 404", retrieved_at="2026-10-04T00:00:00Z")
        body = {"organisasjonsnummer": "912345678", "navn": "LIVE AS", "organisasjonsform": {"kode": "AS"},
                "forretningsadresse": {"adresse": ["Gate 1"], "postnummer": "0150", "poststed": "OSLO", "kommune": "OSLO"},
                "hjemmeside": "www.live.no"}
        raw = json.dumps(body).encode()
        return FetchResult(url, 200, 1, len(raw), body, content_sha256=hashlib.sha256(raw).hexdigest(), retrieved_at="2026-10-04T00:00:00Z")

    monkeypatch.setattr("norway_company_agent.http.fetch_json", fake_fetch)
    monkeypatch.setattr(batch, "profiles_from_bulk", lambda *_: (_ for _ in ()).throw(KeyError("absent")))
    monkeypatch.setattr("norway_company_agent.identity_store.DEFAULT_SQLITE_PATH", batch.Path("does-not-exist.db"))
    profiles, meta = load_profiles("missing.csv", ["912345678", "999999999"])
    assert [p["organisation_number"] for p in profiles] == ["912345678", "999999999"]
    assert profiles[0]["name"] == "LIVE AS" and profiles[0]["website"] == "www.live.no"
    assert profiles[1]["evidence"]["registry"]["status"] == "not_available"
    assert meta["live_resolved"] == 2


# --- viewer -------------------------------------------------------------------

def test_viewer_is_built_from_run_profiles(tmp_path):
    profile = {
        "organisation_number": "912345678", "name": "ACME AS", "municipality": "OSLO",
        "evidence": {"website": {"status": "ambiguous", "value": {"candidate_url": "https://acme.com/", "identity_assessment": {"reasons": ["no link"]}}}},
        "synthesis": {"what_changed": [], "what_is_unknown": [{"topic": "news", "state": "not_available", "reason": "none"}]},
    }
    path = build_viewer([profile], tmp_path, run_id="r1")
    html = path.read_text(encoding="utf-8")
    assert "ACME AS" in html and "912345678" in html and 'name="viewport"' in html
    assert "@media (max-width:760px)" in html and "Evidence Inspector" in html
