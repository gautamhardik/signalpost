from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
import pytest

from norway_company_agent.history import (
    ChangeEvent,
    EvidenceRef,
    SnapshotRecord,
    SnapshotStore,
    canonicalize_snapshot_payload,
    compute_profile_hash,
    create_snapshot_record,
    diff_snapshots,
    summarize_history,
)
from norway_company_agent.refresh import refresh_company_snapshot


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d)


def test_canonicalize_snapshot_excludes_volatile_timestamps():
    claims1 = {"name": "Test AS", "employees": 10, "retrieved_at": "2026-09-20T10:00:00Z"}
    claims2 = {"name": "Test AS", "employees": 10, "retrieved_at": "2026-09-21T18:30:00Z"}

    jobs1 = [{"job_id": "job-1", "title": "Developer", "retrieved_at": "2026-09-20T10:00:00Z"}]
    jobs2 = [{"job_id": "job-1", "title": "Developer", "retrieved_at": "2026-09-21T18:30:00Z"}]

    acts1 = [{"activity_id": "act-1", "title": "Launch", "retrieved_at": "2026-09-20T10:00:00Z"}]
    acts2 = [{"activity_id": "act-1", "title": "Launch", "retrieved_at": "2026-09-21T18:30:00Z"}]

    sources1 = [{"url": "https://example.no/", "retrieved_at": "2026-09-20T10:00:00Z"}]
    sources2 = [{"url": "https://example.no/", "retrieved_at": "2026-09-21T18:30:00Z"}]

    hash1 = compute_profile_hash(claims1, jobs1, acts1, sources1)
    hash2 = compute_profile_hash(claims2, jobs2, acts2, sources2)

    # Identical semantic content must yield identical hashes despite retrieval timestamp differences
    assert hash1 == hash2


def test_snapshot_creation_and_fields():
    profile = {
        "organisation_number": "912345678",
        "name": "TEST NORDIC AS",
        "legal_form": "Aksjeselskap",
        "employees": 25,
        "municipality": "Oslo",
        "website": "https://testnordic.no/",
        "evidence": {
            "roles": {
                "value": {
                    "roles": [
                        {"type": "daglig_leder", "name": "KARI NORDMANN"},
                    ]
                }
            }
        }
    }
    snap = create_snapshot_record(profile)
    assert snap.organisation_number == "912345678"
    assert snap.snapshot_id.startswith("snap-912345678-")
    assert snap.claims["name"] == "TEST NORDIC AS"
    assert snap.claims["employees"] == 25
    assert len(snap.claims["roles"]) == 1
    assert snap.profile_hash is not None


def test_idempotent_diff_snapshots():
    profile = {
        "organisation_number": "912345678",
        "name": "TEST NORDIC AS",
        "employees": 25,
    }
    snap1 = create_snapshot_record(profile, captured_at="2026-09-20T10:00:00Z")
    snap2 = create_snapshot_record(profile, captured_at="2026-09-21T12:00:00Z")

    diffs = diff_snapshots(snap1, snap2)
    # Identical snapshot content produces 0 change events
    assert len(diffs) == 0


def test_detect_claim_changes_with_evidence():
    snap1 = SnapshotRecord(
        snapshot_id="snap-1",
        organisation_number="912345678",
        captured_at="2026-09-20T10:00:00Z",
        profile_hash="hash-1",
        claims={"employees": 10, "municipality": "Bergen"},
    )
    snap2 = SnapshotRecord(
        snapshot_id="snap-2",
        organisation_number="912345678",
        captured_at="2026-09-21T10:00:00Z",
        profile_hash="hash-2",
        claims={"employees": 15, "municipality": "Oslo"},
    )

    diffs = diff_snapshots(snap1, snap2)
    assert len(diffs) == 2

    emp_change = next(d for d in diffs if d.field_name == "employees")
    assert emp_change.change_type == "CHANGED"
    assert emp_change.before_value == 10
    assert emp_change.after_value == 15
    assert len(emp_change.evidence) > 0
    assert emp_change.evidence[0].source_type == "registry"
    assert emp_change.effective_date is None  # Stated effective date unknown unless explicitly registered
    assert emp_change.detected_at == "2026-09-21T10:00:00Z"


def test_detect_role_changes():
    snap1 = SnapshotRecord(
        snapshot_id="snap-1",
        organisation_number="912345678",
        captured_at="2026-09-20T10:00:00Z",
        profile_hash="hash-1",
        claims={
            "roles": [
                {"type": "daglig_leder", "name": "ALICE HANSEN"},
            ]
        },
    )
    snap2 = SnapshotRecord(
        snapshot_id="snap-2",
        organisation_number="912345678",
        captured_at="2026-09-21T10:00:00Z",
        profile_hash="hash-2",
        claims={
            "roles": [
                {"type": "daglig_leder", "name": "BOB OLSEN", "elected_date": "2026-09-15"},
            ]
        },
    )

    diffs = diff_snapshots(snap1, snap2)
    assert len(diffs) == 2  # 1 removed, 1 added
    added = next(d for d in diffs if d.change_type == "ADDED")
    removed = next(d for d in diffs if d.change_type == "REMOVED")

    assert added.entity_type == "role"
    assert added.after_value["name"] == "BOB OLSEN"
    assert added.effective_date == "2026-09-15"  # Stated date preserved

    assert removed.entity_type == "role"
    assert removed.before_value["name"] == "ALICE HANSEN"


def test_detect_job_added_and_removed():
    snap1 = SnapshotRecord(
        snapshot_id="snap-1",
        organisation_number="912345678",
        captured_at="2026-09-20T10:00:00Z",
        profile_hash="hash-1",
        jobs=[
            {"job_id": "job-101", "title": "Data Analyst", "source_url": "https://test.no/careers", "posted_date": "2026-09-01"},
        ],
        sources=[{"url": "https://test.no/careers"}],
    )
    snap2 = SnapshotRecord(
        snapshot_id="snap-2",
        organisation_number="912345678",
        captured_at="2026-09-21T10:00:00Z",
        profile_hash="hash-2",
        jobs=[
            {"job_id": "job-102", "title": "DevOps Engineer", "source_url": "https://test.no/careers", "posted_date": "2026-09-18"},
        ],
        sources=[{"url": "https://test.no/careers"}],
    )

    diffs = diff_snapshots(snap1, snap2)
    assert len(diffs) == 2
    added = next(d for d in diffs if d.change_type == "ADDED")
    removed = next(d for d in diffs if d.change_type == "REMOVED")

    assert added.entity_type == "job"
    assert added.after_value["title"] == "DevOps Engineer"
    assert added.effective_date == "2026-09-18"

    assert removed.entity_type == "job"
    assert removed.before_value["title"] == "Data Analyst"


def test_detect_activity_added_with_strict_temporal_distinction():
    snap1 = SnapshotRecord(
        snapshot_id="snap-1",
        organisation_number="912345678",
        captured_at="2026-09-20T10:00:00Z",
        profile_hash="hash-1",
        activities=[],
    )
    snap2 = SnapshotRecord(
        snapshot_id="snap-2",
        organisation_number="912345678",
        captured_at="2026-09-21T10:00:00Z",
        profile_hash="hash-2",
        activities=[
            {
                "activity_id": "act-201",
                "activity_type": "press_release",
                "title": "Expansion into Nordic Markets",
                "activity_date": "2026-09-15",
                "source_url": "https://test.no/news/expansion",
            }
        ],
    )

    diffs = diff_snapshots(snap1, snap2)
    assert len(diffs) == 1
    ev = diffs[0]
    assert ev.change_type == "ADDED"
    assert ev.entity_type == "activity"
    assert ev.effective_date == "2026-09-15"  # Explicitly distinct from detected_at
    assert ev.detected_at == "2026-09-21T10:00:00Z"
    assert len(ev.evidence) > 0
    assert ev.evidence[0].source_url == "https://test.no/news/expansion"


def test_snapshot_store_append_only_and_replay_safety(temp_dir):
    store = SnapshotStore(storage_dir=temp_dir)
    profile = {
        "organisation_number": "912345678",
        "name": "TEST CORP AS",
        "employees": 10,
    }
    snap1 = create_snapshot_record(profile, captured_at="2026-09-20T10:00:00Z")
    
    # Save 1
    assert store.save_snapshot(snap1) is True
    assert len(store.get_snapshots("912345678")) == 1

    # Replay simulation: saving the exact same snapshot again
    assert store.save_snapshot(snap1) is False
    assert len(store.get_snapshots("912345678")) == 1  # No duplicate appended

    # Update profile
    profile["employees"] = 12
    snap2 = create_snapshot_record(profile, captured_at="2026-09-21T10:00:00Z")
    assert store.save_snapshot(snap2) is True
    assert len(store.get_snapshots("912345678")) == 2

    latest = store.get_latest_snapshot("912345678")
    assert latest is not None
    assert latest.claims["employees"] == 12


def test_refresh_company_snapshot_pipeline(temp_dir):
    store = SnapshotStore(storage_dir=temp_dir)
    prof = {
        "organisation_number": "987654321",
        "name": "SOLARTECH NORGE AS",
        "employees": 5,
        "website": "https://solartech.no/",
    }

    # Pass 1: Baseline snapshot
    s1, diffs1 = refresh_company_snapshot(prof, store, captured_at="2026-09-20T12:00:00Z")
    assert len(diffs1) == 0
    assert s1.organisation_number == "987654321"

    # Pass 2: Identical snapshot
    s2, diffs2 = refresh_company_snapshot(prof, store, captured_at="2026-09-21T12:00:00Z")
    assert len(diffs2) == 0  # 100% Idempotent

    # Pass 3: Modified snapshot
    prof["employees"] = 9
    new_jobs = [{"job_id": "job-99", "title": "Field Technician", "posted_date": "2026-09-22"}]
    s3, diffs3 = refresh_company_snapshot(prof, store, jobs=new_jobs, captured_at="2026-09-22T12:00:00Z")
    assert len(diffs3) == 2  # employees changed + job added

    summary = summarize_history(diffs3)
    assert summary["total_events"] == 2
    assert summary["change_breakdown"]["CHANGED"] == 1
    assert summary["change_breakdown"]["ADDED"] == 1
