import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
from norway_company_agent.website import fetch_website
from norway_company_agent.identity import assess_website_identity
import json

url = "https://www.fetsund-tannklinikk.no/"
org = "812605992"
profiles = {json.loads(l)['organisation_number']: json.loads(l) for l in open('out/benchmark-100-profiles.jsonl', encoding='utf-8')}
p = profiles[org]

print(f"Testing FETSUND TANNKLINIKK AS -> {url}")
crawl, m = fetch_website(url)
print(f"Crawl status: {crawl.get('status')}")

test_p = dict(p)
test_p["evidence"] = dict(p.get("evidence", {}))
test_p["evidence"]["website"] = crawl

id_res = assess_website_identity(test_p)
print("=== IDENTITY EVALUATION ===")
print(json.dumps(id_res, indent=2))
