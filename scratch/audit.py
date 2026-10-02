import json
from collections import defaultdict

with open('out/v8_fresh100_envelopes.jsonl', 'r', encoding='utf-8') as f:
    envs = [json.loads(line) for line in f]

dated_news = []
req_counts = []
budget_exhaustions = 0
for e in envs:
    prof = e.get('profile', {})
    
    # Budget Check
    budget = prof.get('evidence', {}).get('website', {}).get('note', '')
    if 'budget' in budget.lower():
        budget_exhaustions += 1
    
    # Request count
    reqs = prof.get('discovery_funnel', {}).get('requests', 0)
    reqs += len(prof.get('evidence', {}).get('registry', {}))  # rough proxy if ops_summary isn't per-company
    # Let's get the real request count from operations if possible, otherwise we know total is 970.
    req_counts.append(reqs)

    obs = prof.get('evidence', {}).get('external_footprint', {}).get('value', {}).get('observations', [])
    for o in obs:
        if o.get('metrics', {}).get('activity_date'):
            dated_news.append((prof['organisation_number'], prof['name'], o))

print(f'Total dated news: {len(dated_news)}')
print(f'Budget exhaustions: {budget_exhaustions}')
print(f'Max requests for a single company: {max(req_counts) if req_counts else 0}')
if req_counts:
    req_counts.sort()
    p95 = req_counts[int(len(req_counts)*0.95)]
    print(f'P95 requests per company: {p95}')

for org, name, n in dated_news[:10]:
    print(f"Org: {org} - {name}")
    print(f"  URL: {n.get('source_url')}")
    print(f"  Type: {n.get('activity_type')}")
    print(f"  Pub Date: {n.get('metrics', {}).get('activity_date')}")
    print(f"  Retrieved: {n.get('retrieved_at')}")
    print(f"  Desc: {n.get('description')}")
    print('-'*40)
