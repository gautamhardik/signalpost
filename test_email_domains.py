import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
from norway_company_agent.website import fetch_website
from norway_company_agent.identity import assess_website_identity
import json

domains = [
    ("810034882", "SANDNES ELEKTRISKE AS", "https://sandneselektriske.no/"),
    ("812160532", "BWOOD AS", "https://b-wood.no/"),
    ("813587912", "FUSA LYD & LYS AS", "https://fusalydlys.com/"),
    ("813816342", "AKTIV VEILEDNING AS", "https://aktivveiledning.no/"),
    ("812675192", "HILLESVÅG ULLVAREFABRIKK AS", "https://ull.no/"),
    ("811974242", "BRAUTE HOLDING AS", "https://braute.no/"),
]

profiles = {json.loads(l)['organisation_number']: json.loads(l) for l in open('out/benchmark-100-profiles.jsonl', encoding='utf-8')}

print("=== TESTING DIRECT CRAWL ON BRREG EMAIL-DERIVED DOMAINS ===\n")
for org, name, url in domains:
    p = profiles[org]
    rec, m = fetch_website(url)
    status = rec.get("status")
    print(f"{name} ({org}) -> {url}")
    print(f"  Crawl status: {status} (Note: {rec.get('note')})")
    if status == "available":
        test_p = dict(p)
        test_p["evidence"] = dict(p.get("evidence", {}))
        test_p["evidence"]["website"] = rec
        id_res = assess_website_identity(test_p)
        print(f"  Identity Score: {id_res['score']} | Status: {id_res['status']} | Publishable: {id_res['publishable']}")
        print(f"  Reasons: {id_res['reasons']}")
        if id_res.get("registry_identity"):
            print(f"  Registry Corroboration: {id_res['registry_identity']}")
    print()
