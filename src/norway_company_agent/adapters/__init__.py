from __future__ import annotations

from typing import Any
from .base import BaseSourceAdapter
from .sources import (
    GovernanceRolesAdapter,
    HiringAdapter,
    SiteActivityAdapter,
    SiteNewsAdapter,
    SocialProfilesAdapter,
    SubunitsAdapter,
)

DEFAULT_ADAPTERS: list[BaseSourceAdapter] = [
    SocialProfilesAdapter(),
    SiteActivityAdapter(),
    HiringAdapter(),
    SiteNewsAdapter(),
    SubunitsAdapter(),
    GovernanceRolesAdapter(),
]


def extract_all_adapter_observations(
    profile: dict[str, Any],
    adapters: list[BaseSourceAdapter] | None = None,
) -> list[dict[str, Any]]:
    """Execute configured adapters and collect unique, validated ExternalObservation objects."""
    active_adapters = adapters or DEFAULT_ADAPTERS
    results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for adapter in active_adapters:
        for obs in adapter.extract_observations(profile):
            obs_id = str(obs.get("id") or "")
            if obs_id and obs_id not in seen_ids:
                seen_ids.add(obs_id)
                results.append(obs)

    return results
