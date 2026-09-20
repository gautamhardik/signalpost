"""
Persistent, append-only company snapshot and temporal history engine.

Architecture Principles:
1. Immutable point-in-time snapshots (SnapshotRecord).
2. Canonical snapshot hashing (excluding volatile retrieval/capture timestamps).
3. Deterministic diff engine classifying semantic mutations:
   - ADDED
   - REMOVED
   - CHANGED
   - UNCHANGED / OBSERVATION_GAP
4. Multi-reference evidence (EvidenceRef) - never mandatory single URL.
5. Strict separation of detected_at (when agent observed change) and effective_date (when event actually occurred).
6. Idempotent and replay-safe append-only persistence (SnapshotStore).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence
import urllib.parse


@dataclass(frozen=True)
class EvidenceRef:
    """Provenance pointer anchoring a claim or change event."""
    source_type: str  # "registry", "website", "jobs", "activity", "financials", "roles"
    retrieved_at: str
    content_sha256: str
    source_url: str | None = None
    claim_id: str | None = None
    evidence_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChangeEvent:
    """A discrete, evidence-grounded semantic change between snapshots."""
    change_id: str  # Deterministic hash: SHA256(orgnr + prev_hash + curr_hash + entity_key)
    organisation_number: str
    change_type: str  # "ADDED", "REMOVED", "CHANGED", "OBSERVATION_GAP"
    entity_type: str  # "company", "role", "job", "activity", "source", "subunit"
    field_name: str
    before_value: Any
    after_value: Any
    detected_at: str  # ISO-8601 when observation occurred
    effective_date: str | None = None  # Historical/stated date if corroborated, else None
    evidence: list[EvidenceRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = [e.to_dict() if isinstance(e, EvidenceRef) else e for e in self.evidence]
        return d


@dataclass
class SnapshotRecord:
    """Point-in-time immutable record of a company's complete profile."""
    snapshot_id: str  # Deterministic: SHA256(orgnr + profile_hash)
    organisation_number: str
    captured_at: str  # ISO-8601 timestamp of snapshot generation
    profile_hash: str  # SHA256 of canonical snapshot identity payload
    claims: dict[str, Any] = field(default_factory=dict)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    activities: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonicalize_snapshot_payload(
    claims: dict[str, Any],
    jobs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> str:
    """Generate a canonical, deterministic JSON representation of semantic company state.
    
    Excludes volatile runtime fields (retrieved_at, captured_at, query_time, durations)
    so identical company states always yield identical hashes.
    """
    clean_claims = {}
    volatile_keys = {"retrieved_at", "captured_at", "as_of_retrieval", "fetch_time", "query_time"}
    for k, v in sorted(claims.items()):
        if k in volatile_keys:
            continue
        if isinstance(v, dict):
            # Strip volatile fields from nested claim dictionaries
            clean_v = {
                vk: vv for vk, vv in sorted(v.items())
                if vk not in volatile_keys
            }
            clean_claims[k] = clean_v
        else:
            clean_claims[k] = v

    # Canonicalize jobs: sort by stable job_id, exclude retrieval timestamp
    clean_jobs = []
    for j in sorted(jobs, key=lambda x: str(x.get("job_id") or "")):
        clean_j = {
            k: v for k, v in sorted(j.items())
            if k not in ("retrieved_at", "captured_at")
        }
        clean_jobs.append(clean_j)

    # Canonicalize activities: sort by stable activity_id, exclude retrieval timestamp
    clean_acts = []
    for a in sorted(activities, key=lambda x: str(x.get("activity_id") or "")):
        clean_a = {
            k: v for k, v in sorted(a.items())
            if k not in ("retrieved_at", "captured_at")
        }
        clean_acts.append(clean_a)

    # Canonicalize sources: sort by normalized URL
    clean_sources = []
    for s in sorted(sources, key=lambda x: str(x.get("url") or "")):
        clean_s = {
            k: v for k, v in sorted(s.items())
            if k not in ("retrieved_at", "captured_at")
        }
        clean_sources.append(clean_s)

    payload = {
        "claims": clean_claims,
        "jobs": clean_jobs,
        "activities": clean_acts,
        "sources": clean_sources,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_profile_hash(
    claims: dict[str, Any],
    jobs: list[dict[str, Any]],
    activities: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> str:
    """Compute SHA-256 hash over canonical semantic snapshot state."""
    canonical_json = canonicalize_snapshot_payload(claims, jobs, activities, sources)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def create_snapshot_record(
    profile: dict[str, Any],
    *,
    captured_at: str | None = None,
    jobs: list[dict[str, Any]] | None = None,
    activities: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> SnapshotRecord:
    """Factory creating an immutable SnapshotRecord from a verified company profile."""
    orgnr = str(profile.get("organisation_number") or "").strip()
    if not orgnr:
        raise ValueError("Cannot create snapshot without organisation_number")

    now_iso = captured_at or datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Extract claims
    claims: dict[str, Any] = {
        "name": profile.get("name"),
        "legal_form": profile.get("legal_form"),
        "employees": profile.get("employees"),
        "municipality": profile.get("municipality"),
        "website": profile.get("website"),
        "industry_code": profile.get("industry_code"),
        "status": profile.get("status"),
    }
    # Include structured sub-claims if present
    evidence = profile.get("evidence") or {}
    if "roles" in evidence:
        roles_val = (evidence["roles"].get("value") or {}).get("roles") or []
        claims["roles"] = roles_val
    if "locations" in evidence:
        locs_val = (evidence["locations"].get("value") or {}).get("locations") or []
        claims["subunits"] = locs_val
    if "financials" in evidence:
        fin_val = (evidence["financials"].get("value") or {}).get("records") or []
        claims["financials"] = fin_val

    active_jobs = jobs or profile.get("jobs") or []
    active_acts = activities or profile.get("activities") or []
    active_sources = sources or profile.get("sources") or []

    profile_hash = compute_profile_hash(claims, active_jobs, active_acts, active_sources)
    snapshot_id = hashlib.sha256(f"{orgnr}:{profile_hash}".encode("utf-8")).hexdigest()[:16]

    return SnapshotRecord(
        snapshot_id=f"snap-{orgnr}-{snapshot_id}",
        organisation_number=orgnr,
        captured_at=now_iso,
        profile_hash=profile_hash,
        claims=claims,
        jobs=active_jobs,
        activities=active_acts,
        sources=active_sources,
        metadata={
            "created_by": "signalpost-history-engine",
            "evidence_keys": list(evidence.keys()),
        },
    )


def _build_change_id(orgnr: str, prev_hash: str, curr_hash: str, entity_key: str) -> str:
    seed = f"{orgnr}:{prev_hash}:{curr_hash}:{entity_key}"
    return f"chg-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def diff_snapshots(
    previous: SnapshotRecord,
    current: SnapshotRecord,
    *,
    detected_at: str | None = None,
) -> list[ChangeEvent]:
    """Perform deterministic semantic diffing between two snapshots.
    
    Guarantees:
    - Identical snapshots produce 0 change events (idempotency).
    - Detects ADDED, REMOVED, CHANGED.
    - Uses stable job_id, activity_id, role keys, and canonical URLs.
    - Attaches complete EvidenceRef provenance.
    - Never fabricates effective_date.
    """
    if previous.organisation_number != current.organisation_number:
        raise ValueError("Cannot diff snapshots across different organisation numbers")

    orgnr = current.organisation_number
    prev_hash = previous.profile_hash
    curr_hash = current.profile_hash

    # Fast-path idempotency: identical semantic hash yields no changes
    if prev_hash == curr_hash:
        return []

    det_at = detected_at or current.captured_at
    changes: list[ChangeEvent] = []

    # 1. Diff Core Claims
    prev_claims = previous.claims or {}
    curr_claims = current.claims or {}

    claim_fields = [
        "name", "legal_form", "employees", "municipality",
        "website", "industry_code", "status",
    ]
    for field in claim_fields:
        old_val = prev_claims.get(field)
        new_val = curr_claims.get(field)
        if old_val != new_val:
            change_type = "ADDED" if old_val is None else ("REMOVED" if new_val is None else "CHANGED")
            ev_ref = EvidenceRef(
                source_type="registry" if field != "website" else "website",
                retrieved_at=det_at,
                content_sha256=curr_hash[:16],
                source_url=str(curr_claims.get("website") or ""),
                claim_id=f"{orgnr}:{field}",
                evidence_text=f"{field}: {old_val} -> {new_val}",
            )
            changes.append(ChangeEvent(
                change_id=_build_change_id(orgnr, prev_hash, curr_hash, f"company:{field}"),
                organisation_number=orgnr,
                change_type=change_type,
                entity_type="company",
                field_name=field,
                before_value=old_val,
                after_value=new_val,
                detected_at=det_at,
                effective_date=None,  # Stated effective date unknown unless explicitly registered
                evidence=[ev_ref],
            ))

    # 2. Diff Roles (Board & Management)
    prev_roles = {
        f"{r.get('type')}:{r.get('name')}": r
        for r in (prev_claims.get("roles") or [])
        if r.get("type") and r.get("name")
    }
    curr_roles = {
        f"{r.get('type')}:{r.get('name')}": r
        for r in (curr_claims.get("roles") or [])
        if r.get("type") and r.get("name")
    }

    # Added roles
    for r_key, r_data in curr_roles.items():
        if r_key not in prev_roles:
            ev_ref = EvidenceRef(
                source_type="roles",
                retrieved_at=det_at,
                content_sha256=curr_hash[:16],
                evidence_text=f"New role appointed: {r_data.get('type')} - {r_data.get('name')}",
            )
            changes.append(ChangeEvent(
                change_id=_build_change_id(orgnr, prev_hash, curr_hash, f"role:{r_key}:added"),
                organisation_number=orgnr,
                change_type="ADDED",
                entity_type="role",
                field_name=r_data.get("type") or "role",
                before_value=None,
                after_value=r_data,
                detected_at=det_at,
                effective_date=r_data.get("elected_date"),
                evidence=[ev_ref],
            ))

    # Removed roles
    for r_key, r_data in prev_roles.items():
        if r_key not in curr_roles:
            ev_ref = EvidenceRef(
                source_type="roles",
                retrieved_at=det_at,
                content_sha256=curr_hash[:16],
                evidence_text=f"Role ceased or replaced: {r_data.get('type')} - {r_data.get('name')}",
            )
            changes.append(ChangeEvent(
                change_id=_build_change_id(orgnr, prev_hash, curr_hash, f"role:{r_key}:removed"),
                organisation_number=orgnr,
                change_type="REMOVED",
                entity_type="role",
                field_name=r_data.get("type") or "role",
                before_value=r_data,
                after_value=None,
                detected_at=det_at,
                effective_date=None,
                evidence=[ev_ref],
            ))

    # 3. Diff Jobs (Using canonical JobRecord.job_id)
    prev_jobs = {
        str(j.get("job_id")): j for j in previous.jobs
        if j.get("job_id")
    }
    curr_jobs = {
        str(j.get("job_id")): j for j in current.jobs
        if j.get("job_id")
    }

    # Added jobs
    for j_id, j_data in curr_jobs.items():
        if j_id not in prev_jobs:
            ev_ref = EvidenceRef(
                source_type="jobs",
                retrieved_at=det_at,
                content_sha256=str(j_data.get("content_sha256") or curr_hash[:16]),
                source_url=j_data.get("source_url") or j_data.get("application_url"),
                claim_id=j_id,
                evidence_text=f"Job posting opened: {j_data.get('title')}",
            )
            changes.append(ChangeEvent(
                change_id=_build_change_id(orgnr, prev_hash, curr_hash, f"job:{j_id}:added"),
                organisation_number=orgnr,
                change_type="ADDED",
                entity_type="job",
                field_name="position",
                before_value=None,
                after_value=j_data,
                detected_at=det_at,
                effective_date=j_data.get("posted_date"),
                evidence=[ev_ref],
            ))

    # Removed / Delisted jobs
    # Note Constraint #3: distinguish semantic removal from observation gap
    curr_source_urls = {s.get("url") for s in current.sources if s.get("url")}
    for j_id, j_data in prev_jobs.items():
        if j_id not in curr_jobs:
            j_src = j_data.get("source_url")
            # If the carrier source was re-crawled and the job was absent -> REMOVED
            # If carrier source was unavailable/blocked/absent -> OBSERVATION_GAP
            was_carrier_crawled = bool(j_src and any(s in j_src for s in curr_source_urls))
            chg_type = "REMOVED" if was_carrier_crawled or not j_src else "OBSERVATION_GAP"

            ev_ref = EvidenceRef(
                source_type="jobs",
                retrieved_at=det_at,
                content_sha256=str(j_data.get("content_sha256") or curr_hash[:16]),
                source_url=j_src,
                claim_id=j_id,
                evidence_text=f"Job position no longer observed: {j_data.get('title')}",
            )
            changes.append(ChangeEvent(
                change_id=_build_change_id(orgnr, prev_hash, curr_hash, f"job:{j_id}:{chg_type.lower()}"),
                organisation_number=orgnr,
                change_type=chg_type,
                entity_type="job",
                field_name="position",
                before_value=j_data,
                after_value=None,
                detected_at=det_at,
                effective_date=None,
                evidence=[ev_ref],
            ))

    # 4. Diff Activities (Using canonical ActivityRecord.activity_id)
    prev_acts = {
        str(a.get("activity_id")): a for a in previous.activities
        if a.get("activity_id")
    }
    curr_acts = {
        str(a.get("activity_id")): a for a in current.activities
        if a.get("activity_id")
    }

    # Added activities
    for a_id, a_data in curr_acts.items():
        if a_id not in prev_acts:
            ev_ref = EvidenceRef(
                source_type="activity",
                retrieved_at=det_at,
                content_sha256=str(a_data.get("content_sha256") or curr_hash[:16]),
                source_url=a_data.get("source_url"),
                claim_id=a_id,
                evidence_text=f"{a_data.get('activity_type')}: {a_data.get('title')}",
            )
            changes.append(ChangeEvent(
                change_id=_build_change_id(orgnr, prev_hash, curr_hash, f"activity:{a_id}:added"),
                organisation_number=orgnr,
                change_type="ADDED",
                entity_type="activity",
                field_name=a_data.get("activity_type") or "activity",
                before_value=None,
                after_value=a_data,
                detected_at=det_at,
                effective_date=a_data.get("activity_date"),  # Stricly preserve stated activity_date
                evidence=[ev_ref],
            ))

    # 5. Diff External Sources (Using canonical URL)
    prev_srcs = {str(s.get("url")): s for s in previous.sources if s.get("url")}
    curr_srcs = {str(s.get("url")): s for s in current.sources if s.get("url")}

    for s_url, s_data in curr_srcs.items():
        if s_url not in prev_srcs:
            ev_ref = EvidenceRef(
                source_type=s_data.get("source_type") or "website",
                retrieved_at=det_at,
                content_sha256=curr_hash[:16],
                source_url=s_url,
                evidence_text=f"New verified corporate source: {s_url}",
            )
            changes.append(ChangeEvent(
                change_id=_build_change_id(orgnr, prev_hash, curr_hash, f"source:{s_url}:added"),
                organisation_number=orgnr,
                change_type="ADDED",
                entity_type="source",
                field_name=s_data.get("source_type") or "source",
                before_value=None,
                after_value=s_data,
                detected_at=det_at,
                effective_date=None,
                evidence=[ev_ref],
            ))

    return changes


class SnapshotStore:
    """File-backed, append-only JSONL repository for immutable company snapshots."""

    def __init__(self, storage_dir: str | Path = "data/snapshots") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, orgnr: str) -> Path:
        clean_org = "".join(c for c in orgnr if c.isalnum())
        return self.storage_dir / f"{clean_org}.jsonl"

    def save_snapshot(self, snapshot: SnapshotRecord) -> bool:
        """Append snapshot to organization history.
        
        Guarantees replay safety: if a snapshot with the exact same snapshot_id
        is already the head of the file, do not append a duplicate.
        Returns True if appended, False if skipped as duplicate.
        """
        path = self._file_path(snapshot.organisation_number)
        existing = self.get_snapshots(snapshot.organisation_number)
        if existing and existing[-1].snapshot_id == snapshot.snapshot_id:
            return False  # Already present and identical

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot.to_dict(), ensure_ascii=False) + "\n")
        return True

    def get_snapshots(self, orgnr: str) -> list[SnapshotRecord]:
        """Retrieve complete chronological snapshot sequence for an organization."""
        path = self._file_path(orgnr)
        if not path.exists():
            return []

        records: list[SnapshotRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                records.append(SnapshotRecord(
                    snapshot_id=data["snapshot_id"],
                    organisation_number=data["organisation_number"],
                    captured_at=data["captured_at"],
                    profile_hash=data["profile_hash"],
                    claims=data.get("claims") or {},
                    jobs=data.get("jobs") or [],
                    activities=data.get("activities") or [],
                    sources=data.get("sources") or [],
                    metadata=data.get("metadata") or {},
                ))
            except Exception:
                continue
        return records

    def get_latest_snapshot(self, orgnr: str) -> SnapshotRecord | None:
        """Get the most recent snapshot for an organization."""
        snaps = self.get_snapshots(orgnr)
        return snaps[-1] if snaps else None


def summarize_history(events: Sequence[ChangeEvent]) -> dict[str, Any]:
    """Generate concise, structured temporal timeline summary."""
    by_type: dict[str, int] = {}
    timeline: list[dict[str, Any]] = []

    for ev in events:
        by_type[ev.change_type] = by_type.get(ev.change_type, 0) + 1
        timeline.append({
            "change_id": ev.change_id,
            "change_type": ev.change_type,
            "entity_type": ev.entity_type,
            "field": ev.field_name,
            "detected_at": ev.detected_at,
            "effective_date": ev.effective_date,
            "summary": f"{ev.change_type} {ev.entity_type}.{ev.field_name}",
            "evidence_count": len(ev.evidence),
        })

    return {
        "total_events": len(events),
        "change_breakdown": by_type,
        "timeline": timeline,
    }
