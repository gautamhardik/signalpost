from __future__ import annotations

import pytest
from norway_company_agent.activity import (
    classify_activity_type,
    clean_activity_title,
    extract_activity_date_from_text,
    extract_activity_evidence,
    extract_activity_from_html_articles,
    extract_activity_from_jsonld,
    extract_activity_observations,
    verify_activity_identity,
)


@pytest.fixture
def mock_profile():
    return {
        "organisation_number": "923456789",
        "name": "NORDIC SOLAR SOLUTIONS AS",
        "legal_form": "AS",
        "municipality": "OSLO",
        "evidence": {
            "website": {
                "status": "available",
                "source_url": "https://nordicsolar.no",
                "value": {
                    "final_url": "https://nordicsolar.no",
                    "registered_domain": "nordicsolar.no",
                    "title": "Nordic Solar Solutions | Ren Solenergi",
                },
            }
        },
    }


def test_clean_activity_title():
    assert clean_activity_title("  Nytt Solcelleanlegg åpnet i Fredrikstad  ") == "Nytt Solcelleanlegg åpnet i Fredrikstad"
    assert clean_activity_title("Nyheter") is None  # Generic nav title
    assert clean_activity_title("Aktuelt") is None  # Generic nav title
    assert clean_activity_title("Hei") is None  # Too short


def test_classify_activity_type():
    assert classify_activity_type("Pressemelding: Kvartalsrapport Q2", "Oslo, Norge") == "press_release"
    assert classify_activity_type("Inngår strategisk partnerskap med Statkraft", "Avtale signert") == "partnership"
    assert classify_activity_type("Lanserer ny batterilagring for næringsbygg", "Ny teknologi") == "launch"
    assert classify_activity_type("Vinner Årets Fornybarpris 2026", "Kåret under festkveld") == "award"
    assert classify_activity_type("Webinar om solenergi for borettslag", "Bli med 14. mai") == "event"
    assert classify_activity_type("Viktig kunngjøring til våre kunder", "Prisendring") == "announcement"
    assert classify_activity_type("Siste nyheter fra prosjektet", "Bygging i rute") == "news"


def test_extract_activity_date_from_text():
    assert extract_activity_date_from_text("Publisert: 15.09.2026 av redaksjonen") == "2026-09-15"
    assert extract_activity_date_from_text("Dato: 2026-08-20") == "2026-08-20"
    assert extract_activity_date_from_text("Oppdatert 4. mai 2026") == "2026-05-04"
    assert extract_activity_date_from_text("General overview without dates") is None


def test_jsonld_activity_extraction(mock_profile):
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org/",
      "@type": "NewsArticle",
      "headline": "Nordic Solar signerer avtale om 50 MW solpark",
      "description": "Vi har i dag signert en historisk utbyggingsavtale for solenergi i Innlandet.",
      "datePublished": "2026-08-14",
      "publisher": {
        "@type": "Organization",
        "name": "Nordic Solar Solutions AS"
      },
      "url": "https://nordicsolar.no/nyheter/50mw-solpark"
    }
    </script>
    """
    acts = extract_activity_from_jsonld(html, "https://nordicsolar.no/nyheter", mock_profile)
    assert len(acts) == 1
    act = acts[0]
    assert act.title == "Nordic Solar signerer avtale om 50 MW solpark"
    assert act.activity_date == "2026-08-14"
    assert act.activity_type == "partnership"
    assert act.source_url == "https://nordicsolar.no/nyheter/50mw-solpark"
    assert act.identity_assessment["verified"] is True
    assert act.identity_assessment["score"] >= 0.90


def test_html_article_fallback(mock_profile):
    html = """
    <html>
    <body>
      <div class="news-list">
        <article class="nyhetskort">
          <h2 class="title"><a href="/aktuelt/apning-moss">Offisiell åpning av nytt kontor i Moss</a></h2>
          <time datetime="2026-06-10">10. juni 2026</time>
          <p class="summary">Veksten fortsetter, og vi åpner nå regionskontor for å betjene Østfold.</p>
        </article>
      </div>
    </body>
    </html>
    """
    acts = extract_activity_from_html_articles(html, "https://nordicsolar.no/aktuelt", mock_profile)
    assert len(acts) == 1
    act = acts[0]
    assert act.title == "Offisiell åpning av nytt kontor i Moss"
    assert act.activity_date == "2026-06-10"
    assert act.activity_type == "company_update"
    assert act.source_url == "https://nordicsolar.no/aktuelt/apning-moss"


def test_missing_date_is_none(mock_profile):
    html = """
    <article>
      <h3><a href="/nyhet/energipriser">Slik påvirker nye nettleiemodeller bedrifter</a></h3>
      <p>En orientering om overgang til effektbasert tariff for næringskunder.</p>
    </article>
    """
    acts = extract_activity_from_html_articles(html, "https://nordicsolar.no/nyhet", mock_profile)
    assert len(acts) == 1
    assert acts[0].activity_date is None


def test_parent_subsidiary_attribution_quarantine(mock_profile):
    # Article on company website explicitly attributing headline/author to an external parent company
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org/",
      "@type": "NewsArticle",
      "headline": "Global Energy Parent ASA Acquires Brazilian Wind Farm",
      "description": "Global Energy Parent expands in South America.",
      "datePublished": "2026-07-01",
      "publisher": {
        "@type": "Organization",
        "name": "Global Energy Parent ASA"
      },
      "url": "https://nordicsolar.no/news/parent-acquisition"
    }
    </script>
    """
    acts = extract_activity_from_jsonld(html, "https://nordicsolar.no/news", mock_profile)
    # Should quarantine due to explicit external publisher
    assert len(acts) == 0


def test_wrong_company_external_pr_wire_rejection(mock_profile):
    cand = {"title": "Equinor ASA Awards Subsea Contract", "description": "Equinor today announced..."}
    assessment = verify_activity_identity(mock_profile, cand, "https://www.ntb.no/pressemelding/equinor-award-12345")
    assert assessment["verified"] is False
    assert assessment["score"] <= 0.40


def test_extract_activity_evidence(mock_profile):
    html = """
    <article>
      <h2><a href="/pressemelding/solpark-ferdig">Første spadetak for Romerike Solpark</a></h2>
      <time datetime="2026-05-18">18.05.2026</time>
      <p>Pressemelding: Byggestart markerer en milepæl for lokal energiproduksjon.</p>
    </article>
    """
    material = {
        "status": "available",
        "source_url": "https://nordicsolar.no",
        "value": {
            "final_url": "https://nordicsolar.no",
            "registered_domain": "nordicsolar.no",
            "pages": [{"url": "https://nordicsolar.no/pressemeldinger", "html": html, "title": "Pressemeldinger"}],
        }
    }
    ev = extract_activity_evidence(mock_profile, material)
    assert ev["status"] == "available"
    assert ev["value"]["total_activities"] == 1
    assert ev["value"]["dated_activities_count"] == 1
    assert ev["effective_at"] == "2026-05-18"
    assert ev["value"]["activities"][0]["activity_type"] == "press_release"


def test_extract_activity_observations_integration(mock_profile):
    html = """
    <article>
      <h2><a href="/pressemelding/nytt-styremedlem">Valgt inn i Solenergiklyngens styre</a></h2>
      <time datetime="2026-04-12">12.04.2026</time>
      <p>Daglig leder er valgt inn som styremedlem i klyngen.</p>
    </article>
    """
    mock_profile["evidence"]["website"]["value"]["pages"] = [
        {"url": "https://nordicsolar.no/aktuelt", "html": html, "title": "Aktuelt"}
    ]
    obs = extract_activity_observations(mock_profile)
    assert len(obs) == 1
    assert obs[0]["signal_type"] == "public_post"
    assert obs[0]["platform"] == "news"
    assert obs[0]["exact_entity"] is True
    assert obs[0]["metrics"]["activity_date"] == "2026-04-12"
