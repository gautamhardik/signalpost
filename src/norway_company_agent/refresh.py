from __future__ import annotations

from typing import Any


TRACKED_FIELDS: dict[str, tuple[str, ...]] = {
    "registry.name": ("name",),
    "registry.legal_form": ("legal_form",),
    "registry.employees": ("employees",),
    "registry.municipality": ("municipality",),
    "registry.website": ("website",),
    "registry.latest_submitted_accounts": ("latest_submitted_accounts",),
    "financials.records": ("evidence", "financials", "value", "records"),
    "financial_history.years": ("evidence", "financial_history", "value", "years"),
    "roles.roles": ("evidence", "roles", "value", "roles"),
    "locations.locations": ("evidence", "locations", "value", "locations"),
    "website.title": ("evidence", "website", "value", "title"),
    "website.description": ("evidence", "website", "value", "description"),
    "website.social_links": ("evidence", "website", "value", "social_links"),
}


def _read(value: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _evidence_for(profile: dict[str, Any], field: str) -> dict[str, Any]:
    module = field.split(".", 1)[0]
    records = profile.get("evidence", {})
    if module == "registry":
        return records.get("registry_live") or records.get("registry", {})
    return records.get(module, {})


def diff_profile(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    old_org = previous.get("organisation_number")
    new_org = current.get("organisation_number")
    if not old_org or old_org != new_org:
        raise ValueError("Refresh comparison requires the same exact organisation number")
    changes = []
    for field, path in TRACKED_FIELDS.items():
        old_value = _read(previous, path)
        new_value = _read(current, path)
        if old_value == new_value:
            continue
        record = _evidence_for(current, field)
        previous_record = _evidence_for(previous, field)
        changes.append({
            "organisation_number": new_org,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "source_url": record.get("source_url"),
            "retrieved_at": record.get("retrieved_at"),
            "effective_at": record.get("effective_at") or record.get("as_of"),
            "source_class": record.get("source_class") or record.get("source_type"),
            "old_content_sha256": previous_record.get("content_sha256"),
            "new_content_sha256": record.get("content_sha256"),
            "status": record.get("status"),
        })
    return changes


def diff_datasets(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    old_by_org = {row["organisation_number"]: row for row in previous}
    new_by_org = {row["organisation_number"]: row for row in current}
    if set(old_by_org) != set(new_by_org):
        raise ValueError("Refresh datasets must have identical organisation-number membership")
    return [
        change
        for org in sorted(old_by_org)
        for change in diff_profile(old_by_org[org], new_by_org[org])
    ]


from .history import (
    ChangeEvent,
    EvidenceRef,
    SnapshotRecord,
    SnapshotStore,
    create_snapshot_record,
    diff_snapshots,
    summarize_history,
)


def refresh_company_snapshot(
    current_profile: dict[str, Any],
    store: SnapshotStore,
    *,
    jobs: list[dict[str, Any]] | None = None,
    activities: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
    captured_at: str | None = None,
) -> tuple[SnapshotRecord, list[ChangeEvent]]:
    """Refresh a company's persistent state:
    1. Loads the latest historical snapshot if available.
    2. Builds the new immutable SnapshotRecord.
    3. Computes deterministic ChangeEvents.
    4. Appends the new snapshot to the append-only store (replay-safe).
    Returns (current_snapshot, change_events).
    """
    orgnr = current_profile.get("organisation_number")
    if not orgnr:
        raise ValueError("Refreshing company requires an organisation_number")

    previous_snapshot = store.get_latest_snapshot(orgnr)
    current_snapshot = create_snapshot_record(
        current_profile,
        captured_at=captured_at,
        jobs=jobs,
        activities=activities,
        sources=sources,
    )

    if previous_snapshot is not None:
        changes = diff_snapshots(previous_snapshot, current_snapshot)
    else:
        changes = []

    store.save_snapshot(current_snapshot)
    return current_snapshot, changes


def summarize_profile_changes(diffs: list[dict[str, Any]]) -> dict[str, Any]:
    """Produce a concise, human-readable and structured change summary for temporal intelligence."""
    by_org: dict[str, list[dict[str, Any]]] = {}
    for item in diffs:
        org = item.get("organisation_number")
        if org:
            by_org.setdefault(org, []).append(item)

    summaries: list[dict[str, Any]] = []
    for org, changes in by_org.items():
        field_notes = []
        for c in changes:
            field = c.get("field", "")
            old_val = c.get("old_value")
            new_val = c.get("new_value")
            if "employees" in field:
                field_notes.append(f"Employees updated: {old_val} -> {new_val}")
            elif "financials" in field:
                field_notes.append("Annual financial accounts updated")
            elif "roles" in field:
                field_notes.append("Board or management role modifications observed")
            elif "website" in field:
                field_notes.append(f"Website updated: {old_val} -> {new_val}")
            else:
                field_notes.append(f"{field} updated")

        summaries.append({
            "organisation_number": org,
            "change_count": len(changes),
            "changes_detected": field_notes,
            "provenance_verified": all(bool(c.get("new_content_sha256")) for c in changes),
        })

    return {
        "total_changed_organisations": len(by_org),
        "total_field_changes": len(diffs),
        "organisation_change_summaries": summaries,
    }

