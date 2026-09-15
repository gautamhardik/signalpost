import urllib.request
import urllib.parse
import json

queries = [
    'ERIK KEISERUD OSLO',
    'FETSUND TANNKLINIKK LILLESTRØM',
    'SPIRIT FRISØR BØMLO',
    'SI-JA AS ASKØY'
]

for q in queries:
    url = f"http://localhost:8080/search?q={urllib.parse.quote(q)}&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "test"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            print(f"\nQuery: {q} (Results: {len(results)})")
            for r in results[:4]:
                print(f"  [{r.get('engine')}] {r.get('url')} | {r.get('title')}")
    except Exception as e:
        print(f"Error for {q}: {e}")
