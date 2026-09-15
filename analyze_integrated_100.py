import json
import collections

envs = [json.loads(l) for l in open('out/benchmark-100-integrated-envelopes.jsonl', encoding='utf-8')]
cat_map = {json.loads(l)['organisation_number']: json.loads(l).get('benchmark_category') for l in open('benchmark-100.jsonl', encoding='utf-8')}

total = len(envs)
web_states = collections.Counter(e['modules']['website']['state'] for e in envs)
print(f"Total Envelopes: {total}")
print(f"Website States: {dict(web_states)}")

by_cat = collections.defaultdict(lambda: collections.Counter())
for e in envs:
    org = e['organisation_number']
    cat = cat_map.get(org, 'unknown')
    st = e['modules']['website']['state']
    by_cat[cat][st] += 1
    by_cat[cat]['total'] += 1

print("\nWebsite Status by Category:")
for cat, counts in sorted(by_cat.items()):
    print(f"  {cat:25s} (N={counts['total']:2d}): complete={counts['complete']}, not_found={counts['not_found']}, blocked={counts['blocked_robots'] + counts['blocked_policy']}, errors={counts['source_error']}")

# Detailed list of discovered/verified websites among the 80 missing-website companies
print("\nDiscovered & Published Sites from Missing-Website Cohort (80 companies):")
discovered_count = 0
for e in envs:
    org = e['organisation_number']
    cat = cat_map.get(org, 'unknown')
    if cat != 'brreg_website_present':
        ev_web = e['profile']['evidence']['website']
        st = e['modules']['website']['state']
        if st == 'complete':
            discovered_count += 1
            name = e['profile']['name']
            url = ev_web.get('source_url') or ev_web.get('value', {}).get('url')
            score = ev_web.get('value', {}).get('identity_assessment', {}).get('score')
            reasons = ev_web.get('value', {}).get('identity_assessment', {}).get('reasons')
            print(f"  * {org} | {name[:28]:28s} [{cat}] -> {url} (score: {score})")
            print(f"    Reasons: {reasons}")

print(f"\nTotal Discovered & Verified Websites from Missing-Website Cohort: {discovered_count}")
