import json
import urllib.request
import sys
import os

# Add src to sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from norway_company_agent.website import fetch_website
from norway_company_agent.identity import assess_website_identity

# Fetch BRREG for BRANDMAKER AS (982942942)
url = "https://data.brreg.no/enhetsregisteret/api/enheter/982942942"
req = urllib.request.Request(url, headers={"User-Agent": "signalpost-test"})
with urllib.request.urlopen(req) as resp:
    brreg_data = json.loads(resp.read().decode("utf-8"))

# Crawl Brandmaker contact page
print("Crawling https://brandmaker.no/kontakt-oss/ ...")
record, metrics = fetch_website("https://brandmaker.no/kontakt-oss/")
website_val = record.get("value") or {}

# Build flat registry values
flat_brreg = {}
for k, v in brreg_data.items():
    if isinstance(v, dict):
        for sub_k, sub_v in v.items():
            if isinstance(sub_v, list) and sub_v:
                flat_brreg[f"{k}.{sub_k}"] = " ".join(str(item) for item in sub_v)
            else:
                flat_brreg[f"{k}.{sub_k}"] = sub_v
    elif isinstance(v, list) and v:
        flat_brreg[k] = " ".join(str(item) for item in v)
    else:
        flat_brreg[k] = v

profile = {
    "name": brreg_data.get("navn"),
    "organisation_number": brreg_data.get("organisasjonsnummer"),
    "evidence": {
        "registry": {
            "value": flat_brreg
        },
        "website": {
            "value": website_val
        }
    }
}

identity = assess_website_identity(profile)
print("=== BRANDMAKER IDENTITY RESULT ===")
print(json.dumps(identity, indent=2))
