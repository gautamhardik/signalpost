import sys
from pathlib import Path
sys.path.insert(0, str(Path('src').resolve()))
import json
from norway_company_agent.discovery import choose_search_candidate
from norway_company_agent.website import fetch_website
from norway_company_agent.identity import assess_website_identity

profiles = {json.loads(l)['organisation_number']: json.loads(l) for l in open(r'out\smoke-profiles.jsonl', encoding='utf-8')}
searches = [json.loads(l) for l in open(r'C:\signalpost-searxng\signalpost-discovery-results.jsonl', encoding='utf-8')]

print('======================================================================')
print('=== 9-COMPANY BENCHMARK: DISCOVERY GATE -> CRAWL -> IDENTITY V3 ===')
print('======================================================================\n')

results_summary = []

for s in searches:
    org = s['organisation_number']
    profile = profiles[org]
    results = s['results']
    decision = choose_search_candidate(profile, results)
    sel = decision.get('selected')
    
    if not sel:
        print(f"[ABSTAIN] {profile['name']} ({org})")
        cands = [c for c in decision.get('candidates', []) if c.get('status') != 'rejected']
        if cands:
            top = cands[0]
            print(f"   Rejected/Review URL: {top.get('url')} (score: {top.get('score')})")
            print(f"   Reason: {top.get('reasons')}")
        else:
            print(f"   All search candidates were directories/aggregators (safe rejection)")
        results_summary.append({
            "name": profile["name"],
            "org": org,
            "stage": "discovery",
            "outcome": "abstain",
            "url": None
        })
        print()
        continue

    # Candidate was discovered and accepted by search discovery gate
    cand_url = sel['url']
    print(f"[DISCOVERED] {profile['name']} ({org})")
    print(f"   Candidate URL: {cand_url} (discovery score: {sel['score']})")
    print(f"   Attempting retrieval & verification...")

    crawl_record, metrics = fetch_website(cand_url)
    crawl_status = crawl_record.get("status")
    
    if crawl_status == "blocked":
        print(f"   [BLOCKED] by robots.txt (status: blocked)")
        print(f"   Note: {crawl_record.get('note')}")
        results_summary.append({
            "name": profile["name"],
            "org": org,
            "stage": "retrieval",
            "outcome": "blocked",
            "url": cand_url
        })
        print()
        continue
    elif crawl_status != "available":
        print(f"   [ERROR] Retrieval status: {crawl_status}")
        print(f"   Note: {crawl_record.get('note')}")
        results_summary.append({
            "name": profile["name"],
            "org": org,
            "stage": "retrieval",
            "outcome": crawl_status,
            "url": cand_url
        })
        print()
        continue

    # Website crawled successfully - now assess identity
    test_profile = dict(profile)
    test_profile["evidence"] = dict(profile.get("evidence", {}))
    test_profile["evidence"]["website"] = crawl_record
    
    identity_res = assess_website_identity(test_profile)
    
    print(f"   Identity Status: {identity_res['status']} (score: {identity_res['score']})")
    print(f"   Publishable: {identity_res['publishable']}")
    print(f"   Reasons: {identity_res['reasons']}")
    if identity_res.get('registry_identity'):
        print(f"   Registry Identity Corroboration: {identity_res['registry_identity']}")

    results_summary.append({
        "name": profile["name"],
        "org": org,
        "stage": "identity",
        "outcome": "verified_available" if identity_res['publishable'] else f"uncertain_{identity_res['status']}",
        "url": cand_url,
        "identity_score": identity_res['score']
    })
    print()

print('======================================================================')
print('=== SUMMARY COMPARISON (V1 vs V2 vs V3) ===')
print('======================================================================')
for r in results_summary:
    print(f"• {r['name']} ({r['org']}): {r['outcome']} | URL: {r['url']}")
