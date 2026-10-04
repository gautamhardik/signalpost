from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

EvidenceStatus = Literal[
    "available",
    "not_available",
    "blocked",
    "not_applicable",
    "ambiguous",
    "failed",
    # Legacy internal states; normalize_status() maps them before anything is written.
    "not_found",
    "not_fetched",
    "source_error",
    "budget_exhausted",
]

# The only result states the Builderr evaluation contract accepts.
PUBLISHED_STATES = ("available", "not_available", "blocked", "not_applicable", "ambiguous", "failed")

_LEGACY_STATE_MAP = {
    "not_found": "not_available",
    "source_error": "failed",
    "not_fetched": "failed",
    "budget_exhausted": "failed",
    "submission_error": "failed",
    "complete": "available",
    "blocked_policy": "blocked",
    "blocked_robots": "blocked",
}


def normalize_status(status: Any) -> str:
    """Map any internal status onto the six published contract states."""
    value = str(status or "")
    if value in PUBLISHED_STATES:
        return value
    return _LEGACY_STATE_MAP.get(value, "failed")


def normalize_evidence_states(evidence_map: dict[str, Any]) -> dict[str, Any]:
    """Rewrite every evidence record's status in place to a published contract state."""
    for record in evidence_map.values():
        if isinstance(record, dict) and "status" in record:
            record["status"] = normalize_status(record["status"])
            value = record.get("value")
            if isinstance(value, dict) and "status" in value and isinstance(value["status"], str):
                value["status"] = normalize_status(value["status"])
    return evidence_map


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Evidence:
    field: str
    status: EvidenceStatus
    source_type: str
    source_class: str
    source_url: str
    retrieved_at: str
    value: Any = None
    as_of: str | None = None
    note: str | None = None
    content_sha256: str | None = None
    source_row_key: str | None = None
    effective_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evidence(
    field: str,
    status: EvidenceStatus,
    source_type: str,
    source_url: str,
    *,
    value: Any = None,
    as_of: str | None = None,
    note: str | None = None,
    retrieved_at: str | None = None,
    content_sha256: str | None = None,
    source_row_key: str | None = None,
    effective_at: str | None = None,
) -> dict[str, Any]:
    return Evidence(
        field=field,
        status=status,
        source_type=source_type,
        source_class=source_type,
        source_url=source_url,
        retrieved_at=retrieved_at or utc_now(),
        value=value,
        as_of=as_of,
        note=note,
        content_sha256=content_sha256,
        source_row_key=source_row_key,
        effective_at=effective_at,
    ).to_dict()
