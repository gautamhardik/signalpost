"""Final submission validation — all checks in one place."""
import json, sys, hashlib
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

SUB = Path(__file__).resolve().parent.parent / "submission"

def sha256f(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def load_jsonl(path):
    return [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]

profiles  = load_jsonl(SUB / "profiles.jsonl")
envelopes = load_jsonl(SUB / "envelopes.jsonl")
manifest  = load_jsonl(SUB / "organisation-manifest.jsonl")

checks = []
def check(ok, msg):
    checks.append((ok, msg))
    tag = "PASS" if ok else "FAIL"
    print(f"  [{tag}] {msg}")

print("Submission Validation Checks:")
print("=" * 60)

check(len(profiles)  == 1100, f"profiles count=1100 (actual={len(profiles)})")
check(len(envelopes) == 1100, f"envelopes count=1100 (actual={len(envelopes)})")
check(len(manifest)  == 1100, f"manifest count=1100 (actual={len(manifest)})")

p_orgs = {p.get("organisation_number") for p in profiles}
e_orgs = {e.get("organisation_number") for e in envelopes}
m_orgs = {m.get("organisation_number") or m.get("org_number") for m in manifest}

check(p_orgs == m_orgs, f"profiles orgs == manifest (missing={len(m_orgs-p_orgs)}, extra={len(p_orgs-m_orgs)})")
check(e_orgs == m_orgs, f"envelopes orgs == manifest (missing={len(m_orgs-e_orgs)}, extra={len(e_orgs-m_orgs)})")
check(len(p_orgs) == 1100, f"no duplicate orgs in profiles (unique={len(p_orgs)})")
check(len(e_orgs) == 1100, f"no duplicate orgs in envelopes (unique={len(e_orgs)})")

all_complete = all(e.get("state") == "complete" for e in envelopes)
check(all_complete, f"all envelopes state=complete")

has_synth = sum(1 for e in envelopes if e.get("synthesis"))
has_act   = sum(1 for e in envelopes if e.get("activity"))
check(has_synth == 1100, f"all envelopes have synthesis block ({has_synth}/1100)")
check(has_act   == 1100, f"all envelopes have activity block ({has_act}/1100)")

# V7 synthesis content spot-check
synth_sample = next((e["synthesis"] for e in envelopes if e.get("synthesis") and e["synthesis"].get("who")), None)
check(synth_sample is not None, "synthesis blocks have 'who' field populated")
check(synth_sample is not None and "what" in synth_sample, "synthesis blocks have 'what' field populated")

# activity content
act_sample = next((e["activity"] for e in envelopes if e.get("activity")), None)
check(act_sample is not None, "activity blocks are non-null")
check(act_sample is not None and "jobs_count" in act_sample, "activity has jobs_count field")
check(act_sample is not None and "news_count" in act_sample, "activity has news_count field")

# external_footprint in evidence
fp_count = sum(
    1 for e in envelopes
    if (e.get("profile") or {}).get("evidence", {}).get("external_footprint") is not None
)
check(fp_count == 1100, f"all profiles have external_footprint in evidence ({fp_count}/1100)")

# viewer
viewer = SUB / "viewer.html"
check(viewer.exists(), "viewer.html present in submission/")
check(viewer.stat().st_size > 1_000_000, f"viewer.html > 1MB ({viewer.stat().st_size:,} B)")

# freeze record
freeze = SUB / "V7_FREEZE_RECORD.md"
check(freeze.exists(), "V7_FREEZE_RECORD.md present")
check("V7" in freeze.read_text(encoding="utf-8"), "V7_FREEZE_RECORD.md contains 'V7'")

# v6 backup
backup = SUB / "v6-backup"
check((backup / "profiles.jsonl").exists(),  "v6-backup/profiles.jsonl preserved")
check((backup / "envelopes.jsonl").exists(), "v6-backup/envelopes.jsonl preserved")

# run-report
run_rep = json.loads((SUB / "run-report.json").read_text(encoding="utf-8"))
val = run_rep.get("validation", {})
check(val.get("passed") is True, "run-report.validation.passed=True")
check(val.get("checks", {}).get("zero_silent_drops") is True, "run-report zero_silent_drops=True")
check(val.get("checks", {}).get("unique_organisation_numbers") is True, "run-report unique_org_numbers=True")

# Hash verification
v7_p_hash = sha256f(SUB / "profiles.jsonl")
v7_e_hash = sha256f(SUB / "envelopes.jsonl")
print()
print("SHA-256 hashes (current submission):")
print(f"  profiles.jsonl  : {v7_p_hash}")
print(f"  envelopes.jsonl : {v7_e_hash}")

print()
print("=" * 60)
passed = sum(1 for ok, _ in checks if ok)
failed = sum(1 for ok, _ in checks if not ok)
print(f"Result: {passed}/{len(checks)} checks passed, {failed} failed")
if failed == 0:
    print("SUBMISSION VALIDATION: ALL CHECKS PASSED -- READY FOR v7-final TAG")
else:
    print("SUBMISSION VALIDATION: FAILURES -- DO NOT TAG")
    for ok, msg in checks:
        if not ok:
            print(f"  FAILED: {msg}")
