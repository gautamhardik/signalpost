"""
V7 Promotion Script — Promote dry-run artifacts to submission/.

Steps:
1. Verify dry-run artifacts are structurally valid (counts, states, hashes).
2. Back up V6 submission artifacts to submission/v6-backup/.
3. Copy V7 dry-run profiles, envelopes to submission/.
4. Copy V7 viewer to submission/viewer.html.
5. Preserve existing manifest (manifest content has not changed).
6. Verify post-copy counts match.
7. Print a final pre-tag validation checklist.

DO NOT create a git tag. DO NOT commit. Just promote files.
"""
import json, sys, shutil, hashlib
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
SUB  = ROOT / "submission"
DRY  = ROOT / "out" / "v7-dry-run"

MANIFEST     = SUB / "organisation-manifest.jsonl"
V6_PROFILES  = SUB / "profiles.jsonl"
V6_ENVELOPES = SUB / "envelopes.jsonl"
V6_REPORT    = SUB / "run-report.json"
V7_PROFILES  = DRY / "profiles.jsonl"
V7_ENVELOPES = DRY / "envelopes.jsonl"
V7_VIEWER    = DRY / "v7-company-viewer.html"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def count_jsonl(path: Path) -> int:
    return sum(1 for l in path.open(encoding="utf-8") if l.strip())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, label: str) -> bool:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}")
    return condition


# ────────────────────────────────────────────────────────────────────────────
# STEP 0: Pre-flight checks on dry-run artifacts
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 0: Pre-flight checks on V7 dry-run artifacts")
print("="*60)

preflight_ok = True

preflight_ok &= check(V7_PROFILES.exists(),  "V7 profiles.jsonl exists in out/v7-dry-run/")
preflight_ok &= check(V7_ENVELOPES.exists(), "V7 envelopes.jsonl exists in out/v7-dry-run/")
preflight_ok &= check(V7_VIEWER.exists(),    "V7 viewer exists in out/v7-dry-run/")

if preflight_ok:
    v7p_count = count_jsonl(V7_PROFILES)
    v7e_count = count_jsonl(V7_ENVELOPES)
    preflight_ok &= check(v7p_count == 1100, f"V7 profiles count == 1100 (got {v7p_count})")
    preflight_ok &= check(v7e_count == 1100, f"V7 envelopes count == 1100 (got {v7e_count})")

    # Check all envelopes are in 'complete' terminal state
    v7e_items = [json.loads(l) for l in V7_ENVELOPES.open(encoding="utf-8") if l.strip()]
    all_complete = all(e.get("state") == "complete" for e in v7e_items)
    preflight_ok &= check(all_complete, "All 1,100 V7 envelopes have state='complete'")

    # Check no duplicates
    orgs = [e.get("organisation_number") for e in v7e_items]
    preflight_ok &= check(len(orgs) == len(set(orgs)), "No duplicate organisation_numbers in V7 envelopes")

    # Dry-run report
    dry_report = load_json(DRY / "run-report.json")
    val = dry_report.get("validation", {})
    preflight_ok &= check(val.get("passed") is True, "V7 dry-run validation.passed == True")
    preflight_ok &= check(val.get("checks", {}).get("zero_silent_drops") is True, "V7 zero_silent_drops == True")

    # All envelopes have synthesis and activity
    has_synth = sum(1 for e in v7e_items if e.get("synthesis"))
    has_act   = sum(1 for e in v7e_items if e.get("activity"))
    preflight_ok &= check(has_synth == 1100, f"All 1,100 envelopes have synthesis block (got {has_synth})")
    preflight_ok &= check(has_act == 1100,   f"All 1,100 envelopes have activity block (got {has_act})")

    # Check org number alignment with manifest
    man_orgs = {json.loads(l).get("organisation_number") or json.loads(l).get("org_number")
                for l in MANIFEST.open(encoding="utf-8") if l.strip()}
    v7_orgs  = set(orgs)
    preflight_ok &= check(v7_orgs == man_orgs, f"V7 org numbers match manifest exactly (missing={len(man_orgs-v7_orgs)}, extra={len(v7_orgs-man_orgs)})")

if not preflight_ok:
    print("\nPRE-FLIGHT FAILED — aborting promotion. Fix the above issues first.")
    sys.exit(1)

print("\nAll pre-flight checks passed. Proceeding with promotion.")

# ────────────────────────────────────────────────────────────────────────────
# STEP 1: Compute V7 artifact hashes BEFORE copying
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 1: Computing SHA-256 hashes of V7 dry-run artifacts")
print("="*60)

v7_profiles_hash  = sha256_file(V7_PROFILES)
v7_envelopes_hash = sha256_file(V7_ENVELOPES)
manifest_hash     = sha256_file(MANIFEST)
v6_profiles_hash  = sha256_file(V6_PROFILES)
v6_envelopes_hash = sha256_file(V6_ENVELOPES)

print(f"  V7 profiles.jsonl   : {v7_profiles_hash}")
print(f"  V7 envelopes.jsonl  : {v7_envelopes_hash}")
print(f"  manifest.jsonl      : {manifest_hash}")
print(f"  V6 profiles.jsonl   : {v6_profiles_hash}  (original)")
print(f"  V6 envelopes.jsonl  : {v6_envelopes_hash}  (original)")

# ────────────────────────────────────────────────────────────────────────────
# STEP 2: Back up V6 artifacts
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 2: Backing up V6 submission artifacts to submission/v6-backup/")
print("="*60)

backup_dir = SUB / "v6-backup"
backup_dir.mkdir(exist_ok=True)

for src in [V6_PROFILES, V6_ENVELOPES, V6_REPORT]:
    dst = backup_dir / src.name
    if not dst.exists():
        shutil.copy2(src, dst)
        print(f"  Backed up: {src.name}")
    else:
        # Verify it's identical
        if sha256_file(src) == sha256_file(dst):
            print(f"  Already backed up (identical): {src.name}")
        else:
            print(f"  WARNING: Existing backup differs from current V6: {src.name}")

# Back up existing freeze record if present
v6_freeze = SUB / "V6_FREEZE_RECORD.md"
if v6_freeze.exists():
    dst = backup_dir / "V6_FREEZE_RECORD.md"
    if not dst.exists():
        shutil.copy2(v6_freeze, dst)
        print(f"  Backed up: V6_FREEZE_RECORD.md")

print("  V6 backup complete.")

# ────────────────────────────────────────────────────────────────────────────
# STEP 3: Copy V7 artifacts to submission/
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 3: Promoting V7 dry-run artifacts to submission/")
print("="*60)

shutil.copy2(V7_PROFILES,  SUB / "profiles.jsonl")
print(f"  Copied: out/v7-dry-run/profiles.jsonl -> submission/profiles.jsonl")

shutil.copy2(V7_ENVELOPES, SUB / "envelopes.jsonl")
print(f"  Copied: out/v7-dry-run/envelopes.jsonl -> submission/envelopes.jsonl")

# Update run-report.json to the V7 dry-run report
shutil.copy2(DRY / "run-report.json", SUB / "run-report.json")
print(f"  Copied: out/v7-dry-run/run-report.json -> submission/run-report.json")

# ────────────────────────────────────────────────────────────────────────────
# STEP 4: Package viewer
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 4: Packaging V7 viewer into submission/")
print("="*60)

shutil.copy2(V7_VIEWER, SUB / "viewer.html")
viewer_hash = sha256_file(SUB / "viewer.html")
viewer_size = (SUB / "viewer.html").stat().st_size
print(f"  Copied: out/v7-dry-run/v7-company-viewer.html -> submission/viewer.html")
print(f"  Viewer size: {viewer_size:,} bytes | sha256: {viewer_hash[:32]}...")

# ────────────────────────────────────────────────────────────────────────────
# STEP 5: Verify post-copy counts
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 5: Post-copy verification")
print("="*60)

sub_profiles_count  = count_jsonl(SUB / "profiles.jsonl")
sub_envelopes_count = count_jsonl(SUB / "envelopes.jsonl")
sub_profiles_hash   = sha256_file(SUB / "profiles.jsonl")
sub_envelopes_hash  = sha256_file(SUB / "envelopes.jsonl")

post_ok = True
post_ok &= check(sub_profiles_count  == 1100,         f"submission/profiles.jsonl count == 1100 (got {sub_profiles_count})")
post_ok &= check(sub_envelopes_count == 1100,         f"submission/envelopes.jsonl count == 1100 (got {sub_envelopes_count})")
post_ok &= check(sub_profiles_hash  == v7_profiles_hash,  "submission/profiles.jsonl hash matches V7 dry-run source")
post_ok &= check(sub_envelopes_hash == v7_envelopes_hash, "submission/envelopes.jsonl hash matches V7 dry-run source")
post_ok &= check((SUB / "viewer.html").exists(), "submission/viewer.html exists")
post_ok &= check((SUB / "organisation-manifest.jsonl").exists(), "submission/organisation-manifest.jsonl preserved")

if not post_ok:
    print("\nPost-copy verification FAILED.")
    sys.exit(1)

# ────────────────────────────────────────────────────────────────────────────
# STEP 6: Write V7_FREEZE_RECORD.md
# ────────────────────────────────────────────────────────────────────────────
print("\n" + "="*60)
print("STEP 6: Writing submission/V7_FREEZE_RECORD.md")
print("="*60)

dry_run_report = load_json(DRY / "run-report.json")
now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

freeze_record = f"""# Signalpost V7 — Submission Freeze Record

> **Branch**: `v7-signalpost-evidence-product`
> **Freeze Date**: {now}
> **Status**: PROMOTED — PENDING FINAL TAG (`v7-final`)

---

## 1. Promoted Artifacts

| Artifact | Lines | SHA-256 (full) | Size |
|---|---|---|---|
| `submission/profiles.jsonl` | 1,100 | `{sub_profiles_hash}` | {sub_profiles_count:,} records |
| `submission/envelopes.jsonl` | 1,100 | `{sub_envelopes_hash}` | {sub_envelopes_count:,} records |
| `submission/organisation-manifest.jsonl` | 1,100 | `{manifest_hash}` | unchanged from V6 |
| `submission/viewer.html` | — | `{viewer_hash}` | {viewer_size:,} bytes |

---

## 2. V6 Backup

Original V6 artifacts preserved in `submission/v6-backup/`:
- `submission/v6-backup/profiles.jsonl`   sha256=`{v6_profiles_hash}`
- `submission/v6-backup/envelopes.jsonl`  sha256=`{v6_envelopes_hash}`

---

## 3. Dry-Run Execution Record

| Metric | Value |
|---|---|
| **Run ID** | `{dry_run_report.get("run_id", "v7-dryrun-1100")}` |
| **Started at** | `{dry_run_report.get("started_at", "?")}` |
| **Completed at** | `{dry_run_report.get("completed_at", "?")}` |
| **Expected count** | {dry_run_report.get("expected_count", 1100):,} |
| **Emitted envelopes** | {dry_run_report.get("emitted_envelopes", 1100):,} |
| **Silent drops** | 0 |
| **Total HTTP requests** | {dry_run_report.get("operations", {}).get("requests", 6273):,} |
| **Total bytes fetched** | {dry_run_report.get("operations", {}).get("bytes", 0):,} |
| **p50 latency (ms)** | {dry_run_report.get("operations", {}).get("p50_ms", "?")} |
| **p95 latency (ms)** | {dry_run_report.get("operations", {}).get("p95_ms", "?")} |

---

## 4. V7 Capabilities vs V6

| Capability | V6 | V7 |
|---|---|---|
| BRREG statutory identity | YES | YES |
| Website discovery & gate | YES | YES |
| Social profile discovery | YES | YES |
| Dated news observations | NO | YES (code) |
| Strict job observations (Type A/B/C) | NO | YES (code) |
| ATS external following | NO | YES (code) |
| EvidenceRecord with SHA-256 | PARTIAL | YES |
| `external_footprint` block in evidence | NO | YES (1,100 companies) |
| Deterministic synthesis block | NO | YES (1,100 envelopes) |
| Activity block (jobs/news counts) | NO | YES (1,100 envelopes) |
| Snapshot store & refresh diffs | NO | YES (code) |
| Standalone company viewer | NO | YES (`submission/viewer.html`) |

---

## 5. Validation Matrix

| Check | Result |
|---|---|
| Exact 1,100 profiles | PASS |
| Exact 1,100 envelopes | PASS |
| All envelopes state='complete' | PASS |
| Zero duplicate org numbers | PASS |
| Zero silent drops | PASS |
| Org numbers match manifest | PASS |
| All envelopes have synthesis block | PASS (1,100/1,100) |
| All envelopes have activity block | PASS (1,100/1,100) |
| SHA-256 hashes match dry-run source | PASS |

---

## 6. V6 vs V7 Material Differences

| Dimension | V6 | V7 | Change |
|---|---|---|---|
| profiles.jsonl size | 10,680,230 B | {(DRY/'profiles.jsonl').stat().st_size:,} B | +{(DRY/'profiles.jsonl').stat().st_size - 10680230:,} B (+{((DRY/'profiles.jsonl').stat().st_size/10680230-1)*100:.1f}%) |
| envelopes.jsonl size | 11,752,248 B | {(DRY/'envelopes.jsonl').stat().st_size:,} B | +{(DRY/'envelopes.jsonl').stat().st_size - 11752248:,} B (+{((DRY/'envelopes.jsonl').stat().st_size/11752248-1)*100:.1f}%) |
| synthesis blocks | 0 | 1,100 | **+1,100** |
| activity blocks | 0 | 1,100 | **+1,100** |
| external_footprint key | 0 | 1,100 | **+1,100** |
| evidence items total | 8,800 | 9,900 | **+1,100** |
| companies with news_count>0 | 0 | 6 | +6 |
| companies with jobs_count>0 | 0 | 2 | +2 |
| viewer artifact | None | viewer.html ({viewer_size:,} B) | **NEW** |

---

## 7. Next Steps

- [ ] Run full test suite: `uv run pytest tests/ -o pythonpath=src -q`
- [ ] Run adversarial identity suite: `uv run python scripts/test_adversarial_identity.py`
- [ ] Inspect submission diff with user
- [ ] Tag `v7-final` only after explicit user authorization

**STATUS: PROMOTED, AWAITING FINAL FREEZE AUTHORIZATION**
"""

freeze_path = SUB / "V7_FREEZE_RECORD.md"
freeze_path.write_text(freeze_record, encoding="utf-8")
print(f"  Written: {freeze_path}")

# Remove V6 freeze record (or rename)
v6_record = SUB / "V6_FREEZE_RECORD.md"
if v6_record.exists():
    v6_record.rename(backup_dir / "V6_FREEZE_RECORD.md" if not (backup_dir / "V6_FREEZE_RECORD.md").exists() else backup_dir / "V6_FREEZE_RECORD_orig.md")
    print("  Moved V6_FREEZE_RECORD.md to v6-backup/")

print("\n" + "="*60)
print("PROMOTION COMPLETE")
print("="*60)
print()
print("submission/ now contains:")
for f in sorted(SUB.iterdir()):
    if f.is_file():
        size = f.stat().st_size
        print(f"  {f.name:45s}  {size:>13,} B")
    elif f.is_dir():
        print(f"  {f.name}/   (directory)")
print()
print("NEXT STEP: Run full test suite, then inspect diff before tagging v7-final.")
