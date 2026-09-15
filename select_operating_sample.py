import json
import collections

# Load benchmark-100 specifications and V1 integrated results
specs = {json.loads(l)["organisation_number"]: json.loads(l) for l in open("benchmark-100.jsonl", encoding="utf-8")}
envs = {json.loads(l)["organisation_number"]: json.loads(l) for l in open("out/benchmark-100-integrated-envelopes.jsonl", encoding="utf-8")}

unresolved_operating = []
for org, e in envs.items():
    spec = specs[org]
    cat = spec.get("benchmark_category")
    if cat in ("operating_large_no_web", "operating_small_no_web"):
        st = e["modules"]["website"]["state"]
        if st != "complete":
            unresolved_operating.append({
                "organisation_number": org,
                "name": spec["name"],
                "category": cat,
                "municipality": spec.get("municipality"),
                "industry_label": spec.get("industry_label"),
                "employees": spec.get("employees")
            })

print(f"Total Unresolved Operating Companies: {len(unresolved_operating)}")
# Pick 35 operating companies
sample_cohort = unresolved_operating[:35]
with open("data/operating-sample-35.jsonl", "w", encoding="utf-8") as f:
    for item in sample_cohort:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"Saved 35 operating companies to data/operating-sample-35.jsonl")
