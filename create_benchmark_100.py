import gzip
import json
import random

UNIVERSE_PATH = "signalpost-universe.jsonl.gz"
OUTPUT_PATH = "benchmark-100.jsonl"
SEED = 20260914

random.seed(SEED)

categories = {
    "brreg_website_present": {"target": 20, "items": []},
    "operating_large_no_web": {"target": 20, "items": []},  # employees >= 10, AS
    "operating_small_no_web": {"target": 25, "items": []},  # 1 <= employees < 10, AS
    "holding_companies": {"target": 15, "items": []},       # holding in name or 64.20
    "housing_entities": {"target": 10, "items": []},        # BRL, ESEK or borettslag/sameiet
    "other_forms_no_web": {"target": 10, "items": []},      # ENK, ANS, DA, NUF, SA
}

all_filled = False

with gzip.open(UNIVERSE_PATH, "rt", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        name = (rec.get("name") or "").upper()
        form = rec.get("legal_form") or ""
        emp = rec.get("employees") or 0
        ind = rec.get("industry_code") or ""
        web = (rec.get("website") or "").strip()

        # Check category matches
        if web and len(categories["brreg_website_present"]["items"]) < categories["brreg_website_present"]["target"] * 5:
            rec["benchmark_category"] = "brreg_website_present"
            categories["brreg_website_present"]["items"].append(rec)
            continue

        if not web:
            if ("HOLDING" in name or ind.startswith("64.20")) and len(categories["holding_companies"]["items"]) < categories["holding_companies"]["target"] * 5:
                rec["benchmark_category"] = "holding_companies"
                categories["holding_companies"]["items"].append(rec)
            elif (form in ("BRL", "ESEK") or "BORETTSLAG" in name or "SAMEIET" in name) and len(categories["housing_entities"]["items"]) < categories["housing_entities"]["target"] * 5:
                rec["benchmark_category"] = "housing_entities"
                categories["housing_entities"]["items"].append(rec)
            elif form in ("ENK", "ANS", "DA", "NUF", "SA") and len(categories["other_forms_no_web"]["items"]) < categories["other_forms_no_web"]["target"] * 5:
                rec["benchmark_category"] = "other_forms_no_web"
                categories["other_forms_no_web"]["items"].append(rec)
            elif form == "AS":
                if emp >= 10 and len(categories["operating_large_no_web"]["items"]) < categories["operating_large_no_web"]["target"] * 5:
                    rec["benchmark_category"] = "operating_large_no_web"
                    categories["operating_large_no_web"]["items"].append(rec)
                elif 1 <= emp < 10 and len(categories["operating_small_no_web"]["items"]) < categories["operating_small_no_web"]["target"] * 5:
                    rec["benchmark_category"] = "operating_small_no_web"
                    categories["operating_small_no_web"]["items"].append(rec)

        if all(len(c["items"]) >= c["target"] * 5 for c in categories.values()):
            break

selected = []
print("Sample extraction summary:")
for cat_name, cat in categories.items():
    pool = cat["items"]
    random.shuffle(pool)
    picked = pool[:cat["target"]]
    print(f"  - {cat_name}: picked {len(picked)} from pool of {len(pool)}")
    selected.extend(picked)

random.shuffle(selected)

with open(OUTPUT_PATH, "w", encoding="utf-8") as out:
    for item in selected:
        out.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"\nTotal selected: {len(selected)} written to {OUTPUT_PATH}")
