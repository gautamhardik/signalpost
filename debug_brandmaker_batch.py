import json
import urllib.parse
import urllib.request
import sys
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))
from norway_company_agent.discovery import build_flexible_company_search_queries, choose_search_candidate

profiles = [json.loads(l) for l in open('out/smoke-profiles.jsonl', encoding='utf-8')]
p = [x for x in profiles if "BRANDMAKER" in x["name"]][0]

queries = build_flexible_company_search_queries(p)
print("Brandmaker queries generated:", queries)

for q_str in queries[:3]:
    q_url = f"http://localhost:8080/search?{urllib.parse.urlencode({'q': q_str, 'format': 'json'})}"
    req = urllib.request.Request(q_url, headers={"User-Agent": "test"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            results = [{
                'rank': idx,
                'url': r.get('url'),
                'title': r.get('title') or '',
                'snippet': r.get('content') or ''
            } for idx, r in enumerate(data.get('results', []), start=1)]
            print(f"\nQuery '{q_str}': {len(results)} results")
            for r in results[:3]:
                print(f"  {r['rank']}: {r['url']} | {r['title']}")
            decision = choose_search_candidate(p, results)
            print("  Selected candidate:", decision.get("selected"))
    except Exception as e:
        print(f"Error on {q_str}: {e}")
