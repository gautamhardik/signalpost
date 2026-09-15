from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlparse

from ..evidence import utc_now
from .base import BaseSourceAdapter


class SocialProfilesAdapter(BaseSourceAdapter):
    """Extracts verified first-party social profiles (LinkedIn, Facebook, Instagram, YouTube, X)."""

    @property
    def source_type(self) -> str:
        return "social_profiles"

    def extract_observations(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        org = str(profile.get("organisation_number") or "")
        website = profile.get("evidence", {}).get("website", {})
        val = website.get("value") or {}
        assessment = val.get("identity_assessment") or {}
        is_publishable = bool(assessment.get("publishable"))
        if not org or not is_publishable:
            return observations

        social_assessments = val.get("social_link_assessments") or []
        for link in social_assessments:
            if link.get("publishable"):
                platform = link.get("platform")
                url = link.get("url")
                if platform and url:
                    digest = hashlib.sha256(f"{org}|{platform}|{url}".encode("utf-8")).hexdigest()
                    obs = {
                        "id": f"social-handle-{org}-{platform}",
                        "organisation_number": org,
                        "platform": platform,
                        "signal_type": "profile_handle",
                        "source_url": url,
                        "retrieved_at": website.get("retrieved_at") or utc_now(),
                        "content_sha256": digest,
                        "exact_entity": True,
                        "identity_proof": [
                            {
                                "type": "social_identity_gate",
                                "score": link.get("identity_score"),
                                "method": link.get("method"),
                                "matched_tokens": link.get("matched_tokens"),
                            }
                        ],
                        "acquisition_mode": "permitted_public_page",
                        "rights_status": "approved",
                        "source_class": "company_social",
                        "evidence_span": f"Verified {platform} social profile matching legal entity {profile.get('name')}",
                        "metrics": {"platform": platform, "url": url},
                    }
                    observations.append(obs)
        return observations


class SiteActivityAdapter(BaseSourceAdapter):
    """Extracts verified company site footprint metrics from bounded crawl snapshots."""

    @property
    def source_type(self) -> str:
        return "company_site_activity"

    def extract_observations(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        org = str(profile.get("organisation_number") or "")
        website = profile.get("evidence", {}).get("website", {})
        val = website.get("value") or {}
        assessment = val.get("identity_assessment") or {}
        is_publishable = bool(assessment.get("publishable"))
        site_digest = val.get("content_sha256") or website.get("content_sha256")
        source_url = val.get("final_url") or website.get("source_url")

        if org and is_publishable and site_digest and len(str(site_digest)) == 64 and source_url:
            pages = val.get("pages") or []
            obs = {
                "id": f"company-site-metrics-{org}",
                "organisation_number": org,
                "platform": "company_site",
                "signal_type": "profile_metrics",
                "source_url": source_url,
                "retrieved_at": website.get("retrieved_at") or utc_now(),
                "content_sha256": site_digest,
                "exact_entity": True,
                "identity_proof": [
                    {
                        "type": "website_identity_gate",
                        "score": assessment.get("score"),
                        "method": assessment.get("method"),
                    }
                ],
                "acquisition_mode": "permitted_public_page",
                "rights_status": "approved",
                "source_class": "company_site",
                "evidence_span": f"Official company homepage with {len(pages)} bounded pages crawled.",
                "metrics": {
                    "bounded_pages": len(pages),
                    "title": val.get("title"),
                },
            }
            observations.append(obs)
        return observations


class HiringAdapter(BaseSourceAdapter):
    """Extracts verified hiring and recruitment signals from verified website career sections."""

    @property
    def source_type(self) -> str:
        return "hiring"

    def extract_observations(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        org = str(profile.get("organisation_number") or "")
        website = profile.get("evidence", {}).get("website", {})
        val = website.get("value") or {}
        assessment = val.get("identity_assessment") or {}
        is_publishable = bool(assessment.get("publishable"))
        if not org or not is_publishable:
            return observations

        pages = val.get("pages") or []
        career_pages = []
        for pg in pages:
            url_str = str(pg.get("url") or "")
            path_str = urlparse(url_str).path.casefold()
            text_str = (str(pg.get("main_text_excerpt") or "") + " " + str(pg.get("title") or "")).casefold()
            if any(k in path_str for k in ("karriere", "stillinger", "jobb", "jobs", "career", "rekruttering")) or \
               any(k in text_str for k in ("ledig stilling", "ledige stillinger", "bli en del av vårt team", "vi søker etter", "ledige stillinger hos oss")):
                career_pages.append(pg)

        if career_pages:
            # Pick primary career page
            primary = career_pages[0]
            url = str(primary.get("url") or "")
            digest = str(primary.get("content_sha256") or "")
            if url and len(digest) == 64:
                obs = {
                    "id": f"hiring-signal-{org}-{digest[:16]}",
                    "organisation_number": org,
                    "platform": "job_board",
                    "signal_type": "job_posting",
                    "source_url": url,
                    "retrieved_at": website.get("retrieved_at") or utc_now(),
                    "content_sha256": digest,
                    "exact_entity": True,
                    "identity_proof": [
                        {
                            "type": "website_identity_gate",
                            "score": assessment.get("score"),
                            "method": assessment.get("method"),
                        }
                    ],
                    "acquisition_mode": "permitted_public_page",
                    "rights_status": "approved",
                    "source_class": "company_careers",
                    "evidence_span": f"Active recruitment and career portal at {url}: {primary.get('title')}",
                    "metrics": {
                        "career_pages_count": len(career_pages),
                        "page_title": primary.get("title"),
                    },
                }
                observations.append(obs)
        return observations


class SiteNewsAdapter(BaseSourceAdapter):
    """Extracts dated public news and announcements from verified company website pages."""

    @property
    def source_type(self) -> str:
        return "site_news"

    def extract_observations(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        org = str(profile.get("organisation_number") or "")
        website = profile.get("evidence", {}).get("website", {})
        val = website.get("value") or {}
        assessment = val.get("identity_assessment") or {}
        is_publishable = bool(assessment.get("publishable"))
        if not org or not is_publishable:
            return observations

        pages = val.get("pages") or []
        news_pages = []
        for pg in pages:
            url_str = str(pg.get("url") or "")
            path_str = urlparse(url_str).path.casefold()
            if any(k in path_str for k in ("nyheter", "aktuelt", "presse", "news", "artikler", "blog")):
                news_pages.append(pg)

        if news_pages:
            primary = news_pages[0]
            url = str(primary.get("url") or "")
            digest = str(primary.get("content_sha256") or "")
            if url and len(digest) == 64:
                obs = {
                    "id": f"company-site-news-{org}-{digest[:16]}",
                    "organisation_number": org,
                    "platform": "news",
                    "signal_type": "public_post",
                    "source_url": url,
                    "retrieved_at": website.get("retrieved_at") or utc_now(),
                    "content_sha256": digest,
                    "exact_entity": True,
                    "identity_proof": [
                        {
                            "type": "website_identity_gate",
                            "score": assessment.get("score"),
                            "method": assessment.get("method"),
                        }
                    ],
                    "acquisition_mode": "permitted_public_page",
                    "rights_status": "approved",
                    "source_class": "company_news",
                    "evidence_span": f"Public announcements and news page at {url}: {primary.get('title')}",
                    "metrics": {
                        "captured_news_pages": len(news_pages),
                        "page_title": primary.get("title"),
                    },
                }
                observations.append(obs)
        return observations


class SubunitsAdapter(BaseSourceAdapter):
    """Extracts official physical presence and subunit locations from BRREG registry records."""

    @property
    def source_type(self) -> str:
        return "subunits"

    def extract_observations(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        org = str(profile.get("organisation_number") or "")
        locations_rec = profile.get("evidence", {}).get("locations", {})
        val = locations_rec.get("value") or {}
        subunits = val.get("locations") or []
        digest = locations_rec.get("content_sha256")
        source_url = locations_rec.get("source_url")

        if org and subunits and digest and len(str(digest)) == 64:
            # Emit verified physical presence observation
            obs = {
                "id": f"brreg-subunits-{org}",
                "organisation_number": org,
                "platform": "brreg",
                "signal_type": "place_summary",
                "source_url": source_url or f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}",
                "retrieved_at": locations_rec.get("retrieved_at") or utc_now(),
                "content_sha256": digest,
                "exact_entity": True,
                "identity_proof": [
                    {
                        "type": "official_brreg_subunit_link",
                        "parent_org": org,
                        "subunits_count": len(subunits),
                    }
                ],
                "acquisition_mode": "official_api",
                "rights_status": "approved",
                "source_class": "official_registry",
                "evidence_span": f"Official BRREG registered operational presence with {len(subunits)} registered subunits.",
                "metrics": {
                    "subunits_count": len(subunits),
                    "subunit_orgs": [s.get("organisation_number") for s in subunits[:10] if s.get("organisation_number")],
                },
            }
            observations.append(obs)
        return observations
