import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
import json
from norway_company_agent.refresh import diff_profile, diff_datasets

# Load profiles from benchmark-100-v0 baseline and benchmark-100-integrated-v1
p_v0 = [json.loads(l) for l in open("out/benchmark-100-profiles.jsonl", encoding="utf-8")]
p_v1 = [json.loads(l) for l in open("out/benchmark-100-integrated-profiles.jsonl", encoding="utf-8")]

print("=== TESTING REFRESH & DIFF ENGINE (SERIES K) ===")
# 1. Idempotency test (A == A -> 0 changes)
same_changes = diff_datasets(p_v1, p_v1)
print(f"Idempotency Test (V1 vs V1): {len(same_changes)} changes detected (Expected: 0)")

# 2. Meaningful update test (V0 vs V1 -> exactly the newly discovered/verified websites)
v0_v1_changes = diff_datasets(p_v0, p_v1)
print(f"Update Diff Test (V0 vs V1): {len(v0_v1_changes)} field-level changes detected across 100 companies.")

print("\nAuditable Discovered Changes in Refresh Engine:")
for ch in v0_v1_changes:
    org = ch["organisation_number"]
    field = ch["field"]
    old_val = ch["old_value"]
    new_val = ch["new_value"]
    src = ch["source_url"]
    print(f"  * Org: {org} | Field: {field} | Source: {src}")
    print(f"    Old: {str(old_val)[:40]} -> New: {str(new_val)[:40]}")

report = {
    "test": "Series K: Refresh Engine Verification",
    "idempotency_check_passed": len(same_changes) == 0,
    "total_changes_detected": len(v0_v1_changes),
    "changes": v0_v1_changes
}

with open("out/series-k-refresh-report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print("\nSaved refresh verification report to out/series-k-refresh-report.json")
