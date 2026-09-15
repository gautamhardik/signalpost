import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
import json
from norway_company_agent.sampling import iter_bulk

print("Scanning brreg-enheter.csv to extract exactly 1,000 valid companies for stress testing...")
valid_1000 = []
seen = set()

for rec in iter_bulk("brreg-enheter.csv"):
    org = rec["organisation_number"]
    if org and org not in seen and rec.get("name"):
        seen.add(org)
        clean_rec = {
            "organisation_number": org,
            "name": rec["name"],
            "legal_form": rec.get("legal_form"),
            "employees": rec.get("employees"),
            "bankrupt": rec.get("bankrupt", False),
            "liquidating": rec.get("liquidating", False),
            "municipality": rec.get("municipality"),
            "municipality_number": rec.get("municipality_number"),
            "industry_code": rec.get("industry_code"),
            "industry_label": rec.get("industry_label"),
            "website": rec.get("website", ""),
            "latest_submitted_accounts": rec.get("latest_submitted_accounts")
        }
        valid_1000.append(clean_rec)
        if len(valid_1000) == 1000:
            break

with open("stress-1000.jsonl", "w", encoding="utf-8") as f:
    for item in valid_1000:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"Successfully generated stress-1000.jsonl with {len(valid_1000)} companies guaranteed present in brreg-enheter.csv.")
