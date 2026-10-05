"""Regression tests for the recall work after the 58.57 review: sitemap and feed news,
social handles that match the verified site, job-board hiring signals, and growth signals
kept apart from inference."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from norway_company_agent.activity import ActivityRecord, date_from_url, extract_activity_from_crawl_material, extract_activity_from_html_articles, strip_site_suffix
from norway_company_agent.identity import apply_website_identity_gate, branch_of_site_owner, handle_matches_site, site_name_root
from norway_company_agent.jobs import extract_hiring_signal_observations, job_board_url
from norway_company_agent.official import normalize_financials
from norway_company_agent.research import synthesize_company_intelligence
from norway_company_agent.site_sources import is_article_url, parse_feed, parse_sitemap, select_articles
from norway_company_agent.website import _priority_links, page_publication_date


# --- social profiles -----------------------------------------------------------------

def test_handle_that_is_the_sites_own_name_is_accepted():
    assert site_name_root("https://g3i.no/") == "g3i"
    assert handle_matches_site("g3ino", "g3i")          # x.com/g3i_no on g3i.no
    assert handle_matches_site("sunnaas", "sunnaas")    # facebook.com/Sunnaas on sunnaas.no
    assert handle_matches_site("weareknowit", "knowit")
    assert not handle_matches_site("juridiskno", "framadvokat")
    assert not handle_matches_site("g3ixyz", "g3i")      # short names need an exact handle
    assert not handle_matches_site("wix", "wix")


def test_hosting_platform_domain_is_not_a_company_name():
    assert site_name_root("https://acme.wixsite.com/acme") == ""


def _social_site(name, url, links, *, municipality=None):
    profile = {
        "organisation_number": "912345678",
        "name": name,
        "legal_form": "AS",
        "municipality": municipality,
        "evidence": {"registry": {"value": {"forretningsadresse.kommune": municipality}}},
    }
    website = {
        "status": "available",
        "source_url": url,
        "value": {
            "final_url": url,
            "title": name,
            "main_text_excerpt": f"Velkommen til {name}. Org.nr 912 345 678",
            "identity_text_excerpt": "Org.nr 912345678",
            "social_links": [{"platform": platform, "url": link, "found_on": url} for platform, link in links],
            "pages": [],
        },
    }
    profile["evidence"]["website"] = website
    return profile, website


def test_verified_site_brand_handles_are_published():
    profile, website = _social_site("G3 GAUSDAL TREINDUSTRIER SA", "https://g3i.no/", [
        ("x", "https://x.com/g3i_no"), ("instagram", "https://instagram.com/g3i.no"), ("facebook", "https://facebook.com/someoneelse"),
    ], municipality="GAUSDAL")
    gated = apply_website_identity_gate(profile, website)
    published = {item["url"] for item in gated["website"]["value"]["social_links"]}
    assert published == {"https://x.com/g3i_no", "https://instagram.com/g3i.no"}


def test_branch_does_not_inherit_the_national_organisations_profiles():
    profile, website = _social_site("NATURVERNFORBUNDET I SANDNES", "https://naturvernforbundet.no/", [
        ("facebook", "https://facebook.com/naturvernforbundet"),
    ], municipality="SANDNES")
    assert branch_of_site_owner(profile, "naturvernforbundet")
    gated = apply_website_identity_gate(profile, website)
    assert gated["website"]["value"]["social_links"] == []


def test_brand_domain_is_not_mistaken_for_a_branch():
    profile, _ = _social_site("VOSS VEKSEL- OG LANDMANDSBANK ASA", "https://vekselbanken.no/", [], municipality="VOSS")
    assert not branch_of_site_owner(profile, "vekselbanken")


# --- hiring ---------------------------------------------------------------------------

def test_job_board_urls():
    assert job_board_url("https://equinor.wd3.myworkdayjobs.com/EQNR")
    assert job_board_url("https://candidate.webcruiter.com/nb-no/Home/companyadverts?companylock=265559264")
    assert job_board_url("https://acme.teamtailor.com/jobs")
    assert job_board_url("https://www.linkedin.com/company/acme/jobs/")
    assert not job_board_url("https://www.teamtailor.com/en/")           # "Powered by Teamtailor"
    assert not job_board_url("https://www.linkedin.com/company/acme")    # a social profile
    assert not job_board_url("https://www.finn.no/")
    assert not job_board_url("https://www.manpower.no/ledige-stillinger")  # staffing agency
    assert not job_board_url("https://cdn.jobylon.com/embedder.js")


def _hiring_profile(pages):
    return {
        "organisation_number": "923609016",
        "name": "EQUINOR ASA",
        "evidence": {"website": {"status": "available", "retrieved_at": "2026-10-05T00:00:00Z", "value": {
            "final_url": "https://www.equinor.com/",
            "identity_assessment": {"publishable": True, "content_attributable": True},
            "pages": pages,
        }}},
    }


def test_careers_page_linking_the_job_board_is_one_hiring_signal():
    board = {"url": "https://equinor.wd3.myworkdayjobs.com/EQNR", "text": "See our open positions", "kind": "link"}
    profile = _hiring_profile([
        {"url": "https://www.equinor.com/", "job_board_links": [board]},
        {"url": "https://www.equinor.com/careers", "title": "Careers", "content_sha256": "a" * 64, "job_board_links": [board]},
    ])
    [signal] = extract_hiring_signal_observations(profile)
    assert signal["signal_type"] == "hiring_signal"
    assert signal["source_url"] == "https://www.equinor.com/careers"
    assert signal["metrics"]["job_board_url"] == board["url"]


def test_careers_page_without_a_job_board_is_not_a_hiring_signal():
    profile = _hiring_profile([{"url": "https://www.equinor.com/careers", "job_board_links": []}])
    assert extract_hiring_signal_observations(profile) == []


# --- crawl targets --------------------------------------------------------------------

def test_careers_and_news_pages_get_crawl_slots():
    links = "".join(f'<a href="/about-us/page-{i}">About {i}</a>' for i in range(12))
    soup = BeautifulSoup(f'<nav>{links}<a href="/careers">Careers</a><a href="/news">News</a></nav>', "lxml")
    targets = _priority_links("https://www.equinor.com/", soup)
    assert "https://www.equinor.com/careers" in targets
    assert "https://www.equinor.com/news" in targets


# --- sitemaps and feeds ---------------------------------------------------------------

SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://acme.no/nyheter/</loc><lastmod>2026-10-01</lastmod></url>
<url><loc>https://acme.no/nyheter/ny-fabrikk-apnet-i-moss/</loc><lastmod>2026-09-30T10:00:00+02:00</lastmod></url>
<url><loc>https://acme.no/de/nyheter/neue-fabrik-in-moss/</loc><lastmod>2026-09-30</lastmod></url>
<url><loc>https://acme.no/nyheter/blogg/design/</loc><lastmod>2026-09-29</lastmod></url>
<url><loc>https://acme.no/nyheter/blogg/design/farger-som-selger-best/</loc><lastmod>2026-09-28</lastmod></url>
<url><loc>https://acme.no/fag/nyheter-forskning/ny-studie-om-rehabilitering/</loc><lastmod>2025-10-02</lastmod></url>
<url><loc>https://acme.no/produkter/stol/</loc><lastmod>2026-10-02</lastmod></url>
</urlset>"""


def test_sitemap_articles_skip_indexes_translations_and_categories():
    children, entries = parse_sitemap(SITEMAP)
    assert children == [] and len(entries) == 7
    assert not is_article_url("https://acme.no/nyheter/")
    assert not is_article_url("https://acme.no/de/nyheter/neue-fabrik-in-moss/")
    assert not is_article_url("https://acme.no/produkter/stol/")
    chosen = [item["loc"] for item in select_articles(entries, 3, set())]
    assert "https://acme.no/nyheter/blogg/design/" not in chosen  # has pages under it: a category
    assert chosen[0] == "https://acme.no/nyheter/ny-fabrikk-apnet-i-moss/"
    # every news section gets a turn, so an older section is not crowded out
    assert "https://acme.no/fag/nyheter-forskning/ny-studie-om-rehabilitering/" in chosen


def test_sitemap_index_children_are_listed():
    children, entries = parse_sitemap('<sitemapindex><sitemap><loc>https://acme.no/post-sitemap.xml</loc><lastmod>2026-09-01</lastmod></sitemap></sitemapindex>')
    assert children == [{"loc": "https://acme.no/post-sitemap.xml", "lastmod": "2026-09-01"}] and entries == []


def test_feed_items_carry_their_publication_dates():
    rss = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Acme</title>
    <item><title>Ny avtale med Statens vegvesen</title><link>https://acme.no/2026/09/ny-avtale/</link><pubDate>Mon, 22 Sep 2025 20:00:00 +0200</pubDate></item>
    <item><title>Gjesteinnlegg</title><link>https://other.no/innlegg</link><pubDate>Tue, 23 Sep 2025 10:00:00 +0200</pubDate></item>
    </channel></rss>"""
    title, items = parse_feed(rss, "acme.no")
    assert title == "Acme"
    assert items == [{"title": "Ny avtale med Statens vegvesen", "url": "https://acme.no/2026/09/ny-avtale/", "published": "2025-09-22"}]


# --- article pages --------------------------------------------------------------------

def _date(html):
    return page_publication_date(html, BeautifulSoup(html, "lxml"), {"json-ld": []})


def test_publication_date_comes_from_what_the_page_says_about_itself():
    assert _date('<meta property="article:published_time" content="2025-09-22T20:00:00+02:00">') == ("2025-09-22", "meta_published_time")
    assert _date("<p>Publisert 22.09.2025</p>")[0] == "2025-09-22"
    assert _date('<script>{"date":"29/04/2026"}</script>')[0] == "2026-04-29"
    assert _date('<script>{"date":"29/04/2026","other":{"date":"01/05/2026"}}</script>') == (None, None)
    assert _date("<p>Vi åpner 12.11.2026 i Moss.</p>") == (None, None)  # a date in the text is not a publish date


def test_compact_url_dates_are_read():
    assert date_from_url("https://www.equinor.com/news/20260512-5000-oil-cargoes-from-gullfaks") == "2026-05-12"


def test_site_name_is_removed_from_article_titles():
    assert strip_site_suffix("Bedre sosial funksjon etter hjerneskade - Sunnaas sykehus HF", "sunnaas", "SUNNAAS SYKEHUS HF") == "Bedre sosial funksjon etter hjerneskade"
    assert strip_site_suffix("Siste nytt - Sunnaas åpner nytt bygg", "sunnaas", "SUNNAAS SYKEHUS HF") == "Siste nytt - Sunnaas åpner nytt bygg"


def _news_profile(pages):
    return {"organisation_number": "883971752", "name": "SUNNAAS SYKEHUS HF", "evidence": {"website": {"status": "available", "value": {
        "final_url": "https://www.sunnaas.no/", "registered_domain": "sunnaas.no", "pages": pages}}}}


def test_sitemap_article_is_published_with_its_own_date_but_never_a_future_one():
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
    article = {"url": "https://www.sunnaas.no/fag/nyheter-rkr/bedre-sosial-funksjon/", "discovered_via": "sitemap",
               "headline": "Bedre sosial funksjon etter hjerneskade", "published_date": "2025-09-22", "html": "<h1>x</h1>", "main_text_excerpt": "x" * 50}
    event = {**article, "url": "https://www.sunnaas.no/fag/nyheter-rkr/seminar/", "headline": "Seminar om rehabilitering i Oslo", "published_date": tomorrow}
    acts = {act.source_url: act for act in extract_activity_from_crawl_material(_news_profile([article, event]), {"value": {"pages": [article, event], "final_url": "https://www.sunnaas.no/"}})}
    assert acts[article["url"]].activity_date == "2025-09-22"
    assert acts[article["url"]].title == "Bedre sosial funksjon etter hjerneskade"
    assert acts[event["url"]].activity_date is None


def test_feed_page_items_become_dated_articles():
    feed = {"url": "https://www.sunnaas.no/feed/", "kind": "feed", "feed_items": [
        {"title": "Ny avtale om rehabilitering", "url": "https://www.sunnaas.no/nyheter/ny-avtale/", "published": "2026-09-01"}]}
    [act] = extract_activity_from_crawl_material(_news_profile([feed]), {"value": {"pages": [feed], "final_url": "https://www.sunnaas.no/"}})
    assert (act.activity_date, act.found_on_url) == ("2026-09-01", "https://www.sunnaas.no/feed/")


def test_card_title_is_the_headline_not_the_teaser_and_url_is_the_headlines_link():
    html = """<article><a href="/news/20260903-citrus"><h3>Equinor brings storage online</h3><p>East Point Energy, a wholly owned company, has completed construction.</p></a><time datetime="2026-09-03">3 Sep</time></article>"""
    profile = {"organisation_number": "923609016", "name": "EQUINOR ASA", "evidence": {"website": {"value": {"registered_domain": "equinor.com"}}}}
    [act] = extract_activity_from_html_articles(html, "https://www.equinor.com/news", profile)
    assert act.title == "Equinor brings storage online"
    assert act.source_url == "https://www.equinor.com/news/20260903-citrus"


def test_article_page_card_keeps_the_page_url_not_a_topic_link():
    html = """<article><h1>Equinor brings storage online</h1><a href="/energy/flexible-power">Flexible power</a><a href="/where-we-are/us">USA</a><p>Published 3 September 2026</p></article>"""
    profile = {"organisation_number": "923609016", "name": "EQUINOR ASA", "evidence": {"website": {"value": {"registered_domain": "equinor.com"}}}}
    [act] = extract_activity_from_html_articles(html, "https://www.equinor.com/news/20260903-citrus", profile)
    assert act.source_url == "https://www.equinor.com/news/20260903-citrus"


# --- accounts and growth signals ----------------------------------------------------

def _account(year, revenue):
    return {"id": year, "regnskapstype": "SELSKAP", "valuta": "NOK", "regnskapsperiode": {"fraDato": f"{year}-01-01", "tilDato": f"{year}-12-31"},
            "resultatregnskapResultat": {"driftsresultat": {"driftsinntekter": {"sumDriftsinntekter": revenue}}}}


def test_latest_accounts_come_first():
    records = normalize_financials([_account(2022, 100), _account(2024, 130), _account(2023, 110)])["records"]
    assert [r["period"]["tilDato"][:4] for r in records] == ["2024", "2023", "2022"]


def test_growth_signals_keep_facts_and_inference_apart():
    records = normalize_financials([_account(2024, 100_000_000), _account(2025, 120_000_000)])
    profile = {
        "organisation_number": "912345678", "name": "ACME AS", "legal_form": "AS",
        "evidence": {
            "financials": {"status": "available", "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/912345678", "value": records},
            "external_footprint": {"status": "available", "value": {"observations": [{
                "signal_type": "hiring_signal", "platform": "job_board", "source_url": "https://acme.no/karriere",
                "metrics": {"job_board_url": "https://acme.teamtailor.com/jobs"}}]}},
        },
    }
    growth = synthesize_company_intelligence(profile)["growth_signals"]
    supported = {item["id"]: item for item in growth["supported"]}
    assert supported["revenue_trend"]["change_pct"] == 20.0
    assert supported["revenue_trend"]["source_url"].startswith("https://data.brreg.no/")
    assert supported["job_board"]["source_url"] == "https://acme.no/karriere"
    assert all(item["kind"] == "inference" and item["basis"] for item in growth["inferred"])
    assert {basis for item in growth["inferred"] for basis in item["basis"]} <= set(supported)
    assert not any("source_url" in item for item in growth["inferred"])


def test_news_words_must_start_a_path_word():
    from norway_company_agent.activity import has_path_word

    assert has_path_word("/nyheter-rkr/bedre-sosial-funksjon/")
    assert has_path_word("/press-releases/q3-results/")
    assert not has_path_word("/tours/express-fjord-road-trip/")
    assert not has_path_word("/om-oss/multimedia/")


def test_a_newspapers_articles_are_not_company_news():
    from norway_company_agent.activity import extract_activity_observations

    article = {"url": "https://www.nyetroms.no/ssb-innvandringen-vil-oke/s/80-95-106634", "discovered_via": "sitemap",
               "headline": "SSB: Innvandringen vil øke raskere enn antatt", "published_date": "2026-10-01", "html": "<h1>x</h1>", "main_text_excerpt": "x" * 50}
    profile = {"organisation_number": "912345678", "name": "AS NYE TROMS", "industry_code": "58.130", "evidence": {"website": {"status": "available", "value": {
        "final_url": "https://www.nyetroms.no/", "registered_domain": "nyetroms.no", "identity_assessment": {"publishable": True}, "pages": [article]}}}}
    assert extract_activity_observations(profile) == []


def _fake_site(monkeypatch, documents):
    """Serve read_site_sources from memory: documents maps URL -> bytes (XML) or a page dict."""
    from norway_company_agent import site_sources

    fetched: list[str] = []

    def fetch_document(url, *, site_domain, timeout, max_bytes):
        fetched.append(url)
        body = documents.get(url)
        return (body if isinstance(body, bytes) else None), url, {"requests": 1, "bytes": len(body or b""), "latencies_ms": [], "error": None if isinstance(body, bytes) else "HTTP 404"}

    def fetch_page(url, *, homepage_domain, timeout=12.0, max_bytes=1_000_000):
        fetched.append(url)
        page = documents.get(url)
        return (dict(page) if isinstance(page, dict) else None), [], {"requests": 1, "bytes": 0, "latencies_ms": [], "error": None if page else "HTTP 404"}

    monkeypatch.setattr(site_sources, "_fetch_document", fetch_document)
    monkeypatch.setattr(site_sources, "fetch_site_page", fetch_page)
    monkeypatch.setattr(site_sources, "robots_sitemaps", lambda url: [])
    return fetched


def test_site_sources_read_feed_sitemap_articles_and_careers(monkeypatch):
    from norway_company_agent.site_sources import read_site_sources

    sitemap = b"""<urlset><url><loc>https://acme.no/nyheter/ny-fabrikk-apnet-i-moss/</loc><lastmod>2026-09-30</lastmod></url>
    <url><loc>https://acme.no/karriere</loc></url></urlset>"""
    feed = b"""<rss><channel><title>Acme</title><item><title>Ny avtale med kunde</title><link>https://acme.no/nyheter/ny-avtale/</link><pubDate>Mon, 01 Sep 2026 10:00:00 +0200</pubDate></item></channel></rss>"""
    fetched = _fake_site(monkeypatch, {
        "https://acme.no/feed/": feed,
        "https://acme.no/sitemap.xml": sitemap,
        "https://acme.no/nyheter/ny-fabrikk-apnet-i-moss/": {"url": "https://acme.no/nyheter/ny-fabrikk-apnet-i-moss/", "title": "Ny fabrikk"},
        "https://acme.no/karriere": {"url": "https://acme.no/karriere", "title": "Karriere", "job_board_links": []},
    })
    value = {"final_url": "https://acme.no/", "registered_domain": "acme.no", "wordpress": True, "pages": [{"url": "https://acme.no/"}]}
    used = []
    summary = read_site_sources(value, reserve=lambda n: True, charge=lambda met: used.append(met["requests"]))
    kinds = [(page.get("kind"), page.get("discovered_via"), page["url"]) for page in value["pages"][1:]]
    assert ("feed", "feed", "https://acme.no/feed/") in kinds
    assert (None, "sitemap", "https://acme.no/nyheter/ny-fabrikk-apnet-i-moss/") in kinds
    assert (None, "sitemap", "https://acme.no/karriere") in kinds
    assert summary["feeds"] == [{"url": "https://acme.no/feed/", "items": 1}]
    assert sum(used) == len(fetched) == 4


def test_site_sources_stay_inside_a_scoped_section_and_respect_the_allowance(monkeypatch):
    from norway_company_agent.site_sources import read_site_sources

    sitemap = b"""<urlset><url><loc>https://venstre.no/nyheter/nasjonal-sak-om-skatt/</loc><lastmod>2026-09-30</lastmod></url>
    <url><loc>https://venstre.no/lokal/telemark/midt-telemark/nyheter/lokal-sak-om-skole/</loc><lastmod>2026-09-01</lastmod></url></urlset>"""
    fetched = _fake_site(monkeypatch, {"https://venstre.no/sitemap.xml": sitemap})
    value = {"final_url": "https://venstre.no/lokal/telemark/midt-telemark/", "registered_domain": "venstre.no",
             "identity_assessment": {"site_scope": "/lokal/telemark/midt-telemark/"}, "pages": []}
    read_site_sources(value, reserve=lambda n: True, charge=lambda met: None)
    assert "https://venstre.no/nyheter/nasjonal-sak-om-skatt/" not in fetched
    assert "https://venstre.no/lokal/telemark/midt-telemark/nyheter/lokal-sak-om-skole/" in fetched

    fetched.clear()
    summary = read_site_sources({"final_url": "https://acme.no/", "registered_domain": "acme.no", "pages": []}, reserve=lambda n: False, charge=lambda met: None)
    assert fetched == [] and summary["errors"][0]["error"] == "per-company request cap reached"


def test_unnamed_email_domain_comes_after_the_companys_own_name_domain():
    from norway_company_agent.discovery import generate_company_candidate_sources

    profile = {"name": "Bonheur ASA", "evidence": {"registry": {"value": {"epostadresse": "post@fredolsen.no"}}}}
    urls = [c.url for c in generate_company_candidate_sources(profile)]
    assert urls.index("https://bonheur.no/") < urls.index("https://fredolsen.no/")
    named = {"name": "SIGMA TRADING AS", "evidence": {"registry": {"value": {"epostadresse": "post@sigmabil.no"}}}}
    assert generate_company_candidate_sources(named)[0].url == "https://sigmabil.no/"


def test_name_written_as_one_word_on_a_registry_listed_site_is_recognised():
    from norway_company_agent.identity import assess_website_identity

    def assess(name, url, title):
        profile = {"organisation_number": "912345678", "name": name, "website": url, "evidence": {
            "registry": {"value": {"hjemmeside": url}},
            "website": {"status": "available", "source_url": url, "value": {"final_url": url, "title": title, "main_text_excerpt": "Velkommen " * 20, "pages": []}},
        }}
        return assess_website_identity(profile)

    assert assess("SØGNE DANSEKLUBB", "https://www.sognedanseklubb.com/", "HJEM | sognedanseklubb")["publishable"]
    assert assess("AFRODITES SKJØNNHET AS", "https://www.afrodites.no/", "Afrodite`s Skjønnhet")["publishable"]
    # a domain spelling the name is not the page naming the company, nor is the page echoing its domain
    assert not assess("SØGNE DANSEKLUBB", "https://www.sognedanseklubb.com/", "Velkommen")["publishable"]
    assert not assess("ENERGY CONSULT AS", "https://energyconsult.no/", "energyconsult.no Hjem")["exact_entity"]


def _registry_site(name, municipality, registry_url, final_url, *, email=None, requested=None, title="", text="Velkommen til butikkene våre. " * 10):
    from norway_company_agent.identity import assess_website_identity

    profile = {"organisation_number": "912345678", "name": name, "municipality": municipality, "website": registry_url, "evidence": {
        "registry": {"value": {"hjemmeside": registry_url, "epostadresse": email, "forretningsadresse.kommune": municipality}},
        "website": {"status": "available", "source_url": final_url, "value": {
            "requested_url": requested or final_url, "final_url": final_url, "title": title, "main_text_excerpt": text, "pages": []}},
    }}
    return assess_website_identity(profile)


def test_chain_site_registered_by_a_local_branch_is_its_website_but_not_its_content():
    a = _registry_site("JORDBÆRPIKENE STJØRDAL AS", "STJØRDAL", "www.jordbarpikene.no", "https://www.jordbarpikene.no/", title="Jordbærpikene")
    assert a["publishable"] and not a["content_attributable"]
    # a registered site whose domain spells nothing of the name is still not published
    b = _registry_site("BJØRNEFJORDEN AS", "BJØRNAFJORDEN", "www.privatmegleren.no", "https://privatmegleren.no/", title="PrivatMegleren")
    assert not b["publishable"]


def test_registered_website_redirecting_to_the_registered_mail_domain_is_published():
    a = _registry_site("PALFINGER MARINE NORWAY AS", "BERGEN", "www.palfingermarine.com", "https://www.palfinger.com/worldwide/en/marine.html",
                       email="post@palfinger.com", requested="https://www.palfingermarine.com/", title="Marine | PALFINGER")
    assert a["publishable"] and a["reasons"] == ["the registered website redirects here and the registry e-mail domain is this domain"]
    # without the e-mail agreement a redirect to another domain proves nothing
    b = _registry_site("PALFINGER MARINE NORWAY AS", "BERGEN", "www.palfingermarine.com", "https://www.palfinger.com/worldwide/en/marine.html",
                       requested="https://www.palfingermarine.com/", title="Marine | PALFINGER")
    assert not b["publishable"]


def test_placeholder_criminal_and_bulk_service_posts_are_not_news():
    from norway_company_agent.activity import extract_activity_observations

    def feed_profile(items):
        feed = {"url": "https://acme.no/feed/", "kind": "feed", "feed_items": items}
        return {"organisation_number": "912345678", "name": "ACME AS", "evidence": {"website": {"status": "available", "value": {
            "final_url": "https://acme.no/", "registered_domain": "acme.no", "identity_assessment": {"publishable": True}, "pages": [feed]}}}}

    item = lambda title, slug, day: {"title": title, "url": f"https://acme.no/{slug}/", "published": day}  # noqa: E731
    titles = [obs["metrics"]["title"] for obs in extract_activity_observations(feed_profile([
        item("Hello world!", "hello-world", "2024-06-13"),
        item("Lorem Ipsum", "blog-lorem-ipsum", "2026-01-05"),
        item("Tidligere politimann dømt til fire år", "domt", "2026-08-19"),
        item("Forretningsplan", "forretningsplan", "2018-10-19"),
        item("Bedriftsetablering", "bedriftsetablering", "2018-10-19"),
        item("Styreverv og rådgivning", "styreverv", "2018-10-19"),
        item("// Smoltsporingsprosjektet oppsummert", "smolt", "2026-01-08"),
        item("Ny avdeling åpnet på Kokstad", "ny-avdeling-kokstad", "2026-06-23"),
    ]))]
    assert titles == ["Styreverv og rådgivning", "Smoltsporingsprosjektet oppsummert", "Ny avdeling åpnet på Kokstad"]


def test_links_to_the_bare_domain_are_crawled_on_the_host_that_answered():
    soup = BeautifulSoup('<nav><a href="https://askvvs.no/kontakt">Kontakt</a></nav>', "lxml")
    assert _priority_links("https://www.askvvs.no/", soup) == ["https://www.askvvs.no/kontakt"]


def test_a_sub_page_on_an_unresolvable_host_does_not_sink_the_site(monkeypatch):
    from norway_company_agent import website

    def unresolvable(url, timeout):
        raise website.UnresolvableHost("Hostname did not resolve")

    monkeypatch.setattr(website, "_robots_allowed", unresolvable)
    page, social, requests, size, elapsed, error = website._fetch_secondary_page("https://askvvs.no/kontakt", homepage_domain="askvvs.no", timeout=5, max_bytes=1000)
    assert page is None and error.startswith("UnresolvableHost")


def test_norwegian_parking_page_is_not_a_website():
    from norway_company_agent.identity import assess_website_identity

    profile = {"organisation_number": "912345678", "name": "ØYSLEBØ VEL", "evidence": {"website": {"status": "available", "source_url": "https://oyslebovel.no/", "value": {
        "final_url": "https://oyslebovel.no/", "title": "oyslebovel.no | Parkert Domene",
        "main_text_excerpt": "oyslebovel.no er parkert hos Domene.no. Domene.no er norsk domeneregistrar og leverandør av domenenavn.", "pages": []}}}}
    assessment = assess_website_identity(profile)
    assert not assessment["publishable"] and "parked" in assessment["reasons"][0]
