import json
import urllib.request
import urllib.parse
import time
from pathlib import Path

sample = [json.loads(l) for l in open("data/operating-sample-35.jsonl", encoding="utf-8")]
SEARXNG_URL = "http://localhost:8080/search"

def query_searxng(q, timeout=8):
    url = f"{SEARXNG_URL}?{urllib.parse.urlencode({'q': q, 'format': 'json'})}"
    req = urllib.request.Request(url, headers={"User-Agent": "signalpost-ground-truth/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [{
                "rank": idx,
                "url": r.get("url"),
                "title": r.get("title") or "",
                "snippet": r.get("content") or "",
                "engine": r.get("engine") or ""
            } for idx, r in enumerate(data.get("results", []), start=1)]
    except Exception as e:
        return []

ground_truth = []

print(f"Investigating {len(sample)} unresolved operating companies for Ground Truth...")

for idx, c in enumerate(sample, start=1):
    org = c["organisation_number"]
    name = c["name"]
    muni = c.get("municipality") or ""
    clean = name
    for s in [" AS", " ASA", " ENK"]:
        if clean.endswith(s): clean = clean[:-len(s)].strip()

    # Query with clean name + municipality
    q = f"{clean} {muni}".strip()
    res = query_searxng(q)
    time.sleep(0.1)

    # Inspect top 10 results for plausible official company domains
    # Ignore directories: proff, 1881, purehelp, gulesider, linkedin, facebook, etc.
    candidate_domains = []
    ignored = {"proff.no", "1881.no", "purehelp.no", "gulesider.no", "facebook.com", "linkedin.com", "instagram.com", "kart.gulesider.no", "regnskapstall.no", "bedriftsdatabasen.no"}
    
    genuine_domain = None
    rank_found = None
    status = "no_website_found"

    for r in res:
        u = r.get("url", "")
        host = u.split("://")[-1].split("/")[0].split(":")[0].removeprefix("www.").casefold()
        if host and not any(host == ign or host.endswith("." + ign) for ign in ignored):
            candidate_domains.append((r["rank"], host, u, r["title"]))
            # Simple heuristic check for company name match in domain or title
            clean_tokens = [t.lower() for t in clean.split() if len(t) > 2]
            if clean_tokens and all(t in host or t in r["title"].lower() for t in clean_tokens[:2]):
                if not genuine_domain:
                    genuine_domain = host
                    rank_found = r["rank"]
                    status = "website_exists"

    rec = {
        "organisation_number": org,
        "name": name,
        "clean_name": clean,
        "municipality": muni,
        "industry_label": c.get("industry_label"),
        "employees": c.get("employees"),
        "ground_truth_status": status,
        "official_domain": genuine_domain,
        "search_rank": rank_found,
        "query_used": q,
        "total_results": len(res),
        "non_directory_candidates": candidate_domains[:5]
    }
    ground_truth.append(rec)
    print(f"[{idx:2d}/35] {name[:25]:25s} -> Status: {status:16s} | Domain: {str(genuine_domain):20s} | Rank: {str(rank_found)}")

with open("data/discovery-ground-truth.jsonl", "w", encoding="utf-8") as f:
    for item in ground_truth:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")

print(f"\nSaved Ground Truth evaluation to data/discovery-ground-truth.jsonl")
