from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSourceAdapter(ABC):
    """Base contract for modular external source discovery adapters."""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Name of the source platform/type."""
        ...

    @abstractmethod
    def extract_observations(self, profile: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract validated, publishable ExternalObservation objects for a profile."""
        ...
