import json
import collections

envelopes = [json.loads(l) for l in open('out/benchmark-100-envelopes.jsonl', encoding='utf-8')]
profiles = [json.loads(l) for l in open('out/benchmark-100-profiles.jsonl', encoding='utf-8')]

print(f"Total Envelopes: {len(envelopes)}")
print(f"Total Profiles: {len(profiles)}")

entity_states = collections.Counter(e.get('state') for e in envelopes)
print(f"\nOverall Entity States: {dict(entity_states)}")

web_states = collections.Counter(e['modules']['website']['state'] for e in envelopes)
print(f"Overall Website Module States: {dict(web_states)}")

cat_map = {json.loads(l)['organisation_number']: json.loads(l).get('benchmark_category') for l in open('benchmark-100.jsonl', encoding='utf-8')}

by_category = collections.defaultdict(collections.Counter)
for e in envelopes:
    org = e['organisation_number']
    cat = cat_map.get(org, 'unknown')
    w_state = e['modules']['website']['state']
    by_category[cat][w_state] += 1

print("\nWebsite Status by Stratified Category:")
for cat, counts in sorted(by_category.items()):
    print(f"  {cat:25s} (N={sum(counts.values()):2d}): {dict(counts)}")

# Let's inspect the 20 companies that had BRREG websites
print("\nDeep-dive on brreg_website_present (20 companies):")
for e in envelopes:
    org = e['organisation_number']
    if cat_map.get(org) == 'brreg_website_present':
        name = e['profile']['name']
        site = e['profile'].get('website')
        state = e['modules']['website']['state']
        ev_website = e['profile']['evidence']['website']
        status = ev_website.get('status')
        score = ev_website.get('value', {}).get('identity_assessment', {}).get('score') if ev_website.get('value') else None
        print(f"  {org} | {name[:30]:30s} | state: {state:15s} | status: {str(status):12s} | score: {score} | url: {site}")
