import json
import collections

lines = [json.loads(l) for l in open('out/phase2-searxng-raw.jsonl', encoding='utf-8')]

for i in range(min(5, len(lines))):
    s = lines[i]
    print(f"\nQuery ({s['query_type']}): {s['query']}")
    for r in s['results'][:5]:
        print(f"  [{r.get('engine')}] {r['url']}")
