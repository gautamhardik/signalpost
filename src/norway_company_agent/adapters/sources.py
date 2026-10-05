from __future__ import annotations

import hashlib
from typing import Any

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
        is_publishable = bool(assessment.get("publishable")) and assessment.get("content_attributable", True)
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
                                "reason": f"Linked from the verified company website; {link.get('reason')}" if link.get("reason") else None,
                            }
                        ],
                        "acquisition_mode": "permitted_public_page",
                        "rights_status": "approved",
                        "source_class": "company_social",
                        "evidence_span": f"{platform.capitalize()} profile linked from the verified website of {profile.get('name')}: {link.get('reason')}",
                        "found_on_url": link.get("found_on") or None,
                        "metrics": {"platform": platform, "url": url},
                    }
                    observations.append(obs)
        return observations


class RegistrySocialAdapter(BaseSourceAdapter):
    """A company whose registered web address is a social profile (a Facebook page, say):
    that profile is an official registry fact about the company, not its website."""

    @property
    def source_type(self) -> str:
        return "registry_social"

    def extract_observations(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        from ..website import normalize_social_url

        org = str(profile.get("organisation_number") or "")
        link = profile.get("registry_social")
        record = profile.get("evidence", {}).get("registry_live") or {}
        if record.get("status") != "available":
            record = profile.get("evidence", {}).get("registry") or {}
        digest = record.get("snapshot_sha256") or record.get("content_sha256")
        if not org or not link or not digest or len(str(digest)) != 64:
            return []
        normalized = normalize_social_url(link) or {}
        if not normalized.get("platform"):
            return []
        return [{
            "id": f"registry-social-{org}-{normalized['platform']}",
            "organisation_number": org,
            "platform": normalized["platform"],
            "signal_type": "profile_handle",
            "source_url": normalized["url"],
            "retrieved_at": record.get("retrieved_at") or utc_now(),
            "content_sha256": digest,
            "snapshot_sha256": record.get("snapshot_sha256"),
            "snapshot_path": record.get("snapshot_path"),
            "registry_source_url": record.get("source_url"),
            "exact_entity": True,
            "identity_proof": [{
                "type": "registry_listed_web_address",
                "reason": "Registered as the company's web address in Enhetsregisteret",
                "method": "official_registry_field",
            }],
            "acquisition_mode": "official_api",
            "rights_status": "approved",
            "source_class": "official_registry",
            "evidence_span": f"{normalized['platform'].capitalize()} profile registered as the web address of {profile.get('name')} in Enhetsregisteret",
            "metrics": {"platform": normalized["platform"], "url": normalized["url"]},
        }]


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
        is_publishable = bool(assessment.get("publishable")) and assessment.get("content_attributable", True)
        if not org or not is_publishable:
            return observations

        # Individual postings, plus one hiring signal when the verified site opens the company's
        # job board (an apply action). A careers page by itself is not a hiring fact.
        from ..jobs import extract_hiring_signal_observations, extract_job_observations
        return extract_job_observations(profile) + extract_hiring_signal_observations(profile)


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
        is_publishable = bool(assessment.get("publishable")) and assessment.get("content_attributable", True)
        if not org or not is_publishable:
            return observations

        # Only dated, individual articles count as news. An index page ("Nyheter",
        # "Blog") by itself is not a news fact.
        from ..activity import extract_activity_observations
        return extract_activity_observations(profile)


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
                "snapshot_sha256": locations_rec.get("snapshot_sha256"),
                "snapshot_path": locations_rec.get("snapshot_path"),
                "metrics": {
                    "subunits_count": len(subunits),
                    "subunit_orgs": [s.get("organisation_number") for s in subunits[:10] if s.get("organisation_number")],
                },
            }
            observations.append(obs)
        return observations


class GovernanceRolesAdapter(BaseSourceAdapter):
    """Extracts verified corporate governance and board leadership intelligence from official BRREG records."""

    @property
    def source_type(self) -> str:
        return "governance_roles"

    def extract_observations(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        org = str(profile.get("organisation_number") or "")
        roles_rec = profile.get("evidence", {}).get("roles", {})
        val = roles_rec.get("value") or {}
        roles = [item for item in (val.get("roles") or []) if not item.get("inactive")]
        digest = roles_rec.get("content_sha256")
        source_url = roles_rec.get("source_url")

        if org and roles and digest and len(str(digest)) == 64:
            # Emit verified corporate leadership summary
            key_leaders = [
                f"{r.get('role', 'Role')}: {r.get('name')}"
                for r in roles[:5]
                if r.get("name")
            ]
            obs = {
                "id": f"brreg-governance-{org}",
                "organisation_number": org,
                "platform": "brreg",
                "signal_type": "company_profile",
                "source_url": source_url or f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}/roller",
                "retrieved_at": roles_rec.get("retrieved_at") or utc_now(),
                "content_sha256": digest,
                "exact_entity": True,
                "identity_proof": [
                    {
                        "type": "official_brreg_role_registry",
                        "organisation_number": org,
                        "active_roles_count": len(roles),
                    }
                ],
                "acquisition_mode": "official_api",
                "rights_status": "approved",
                "source_class": "official_registry",
                "evidence_span": f"Official BRREG registered governance leadership ({len(roles)} active roles): {', '.join(key_leaders)}",
                "snapshot_sha256": roles_rec.get("snapshot_sha256"),
                "snapshot_path": roles_rec.get("snapshot_path"),
                "metrics": {
                    "active_roles_count": len(roles),
                    "key_leaders": key_leaders,
                },
            }
            observations.append(obs)
        return observations

