import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
import json
import collections
from norway_company_agent.discovery import score_search_candidate, choose_search_candidate, BLOCKED_DISCOVERY_HOSTS

searches = [json.loads(l) for l in open('out/phase2-searxng-raw.jsonl', encoding='utf-8')]
profiles = {json.loads(l)['organisation_number']: json.loads(l) for l in open('out/benchmark-100-profiles.jsonl', encoding='utf-8')}

# Look at 5 operating companies
operating_searches = [s for s in searches if s['category'] in ('operating_large_no_web', 'operating_small_no_web')]

print(f"Total operating searches: {len(operating_searches)}")

# Sample a few well known names
sample_orgs = list(dict.fromkeys(s['organisation_number'] for s in operating_searches))[:10]

for org in sample_orgs:
    p = profiles[org]
    name = p['name']
    cat = p.get('benchmark_category', '')
    print(f"\n=======================================================")
    print(f"ORG: {org} | {name} [{cat}]")
    org_searches = [s for s in operating_searches if s['organisation_number'] == org]
    for s in org_searches:
        q_type = s['query_type']
        q = s['query']
        results = s['results']
        print(f"\n--- {q_type}: {q} (Results: {len(results)}) ---")
        for r in results[:5]:
            score_info = score_search_candidate(p, r)
            print(f"  Rank {r['rank']}: {r['url']}")
            print(f"    Title: {r['title'][:50]}")
            print(f"    Status: {score_info['status']} | Score: {score_info['score']} | NameInHost: {score_info.get('name_in_host')} | Reasons: {score_info['reasons']}")
