import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))

import json
import time
import urllib.request
import urllib.parse
from norway_company_agent.discovery import score_search_candidate, choose_search_candidate

PROFILES_PATH = Path("out/benchmark-100-profiles.jsonl")
BENCHMARK_SPEC_PATH = Path("benchmark-100.jsonl")
SERIES_A_PATH = Path("out/series-a-email-domain.jsonl")
OUT_SERIES_B_REPORT = Path("out/series-bc-report.json")
SEARXNG_URL = "http://localhost:8080/search"

def query_searxng(query_str: str, engine: str = None, timeout: int = 8) -> list[dict]:
    params = {"q": query_str, "format": "json"}
    if engine:
        params["engines"] = engine
    url = f"{SEARXNG_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "signalpost-controlled-test/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            return [{
                "rank": idx,
                "url": r.get("url"),
                "title": r.get("title") or "",
                "snippet": r.get("content") or "",
                "engine": r.get("engine") or engine or "unknown"
            } for idx, r in enumerate(results, start=1)]
    except Exception as exc:
        return []

def main():
    print("======================================================================")
    print("=== SERIES B & C: CONTROLLED SEARCH & QUERY STRATEGY BENCHMARK     ===")
    print("======================================================================")

    # 1. Load profiles and Series A results
    series_a = {json.loads(l)["organisation_number"]: json.loads(l) for l in open(SERIES_A_PATH, encoding="utf-8")}
    profiles = {json.loads(l)["organisation_number"]: json.loads(l) for l in open(PROFILES_PATH, encoding="utf-8")}
    cat_map = {json.loads(l)["organisation_number"]: json.loads(l).get("benchmark_category") for l in open(BENCHMARK_SPEC_PATH, encoding="utf-8")}

    # The unresolved cohort = 80 missing minus 3 verified in Series A = 77 companies
    unresolved_orgs = [org for org, rec in series_a.items() if rec.get("resolution") != "verified_publishable"]
    print(f"Total Unresolved Companies for Search: {len(unresolved_orgs)}")

    # Test query strategies on the unresolved cohort:
    # S1 (clean distinctive name + municipality, unquoted)
    # S2 (clean distinctive name + Norway, unquoted)
    # S3 (clean distinctive name + org number, unquoted)
    # S4 (strict quoted legal name - baseline reference)

    query_stats = {
        "S1_name_muni": {"queries": 0, "results_found": 0, "candidates_accepted": 0, "orgs_with_candidates": set()},
        "S2_name_norway": {"queries": 0, "results_found": 0, "candidates_accepted": 0, "orgs_with_candidates": set()},
        "S3_name_org": {"queries": 0, "results_found": 0, "candidates_accepted": 0, "orgs_with_candidates": set()},
        "S4_quoted_baseline": {"queries": 0, "results_found": 0, "candidates_accepted": 0, "orgs_with_candidates": set()},
    }

    per_company_records = []

    # Let's run with 0.15s pacing between requests to maintain engine health
    for idx, org in enumerate(unresolved_orgs, start=1):
        p = profiles[org]
        raw_name = p["name"]
        cat = cat_map.get(org, "unknown")
        muni = p.get("municipality") or ""
        
        # Clean distinctive name: remove legal form suffixes (AS, ASA, ENK, DA, etc.)
        clean_name = raw_name
        for suffix in [" AS", " ASA", " ENK", " DA", " ANS", " NUF", " SA", " BRL", " ESEK"]:
            if clean_name.endswith(suffix):
                clean_name = clean_name[:-len(suffix)].strip()

        strategies = {
            "S1_name_muni": f"{clean_name} {muni}".strip(),
            "S2_name_norway": f"{clean_name} Norway".strip(),
            "S3_name_org": f"{clean_name} {org}".strip(),
            "S4_quoted_baseline": f'"{raw_name}" {org} {muni}'.strip()
        }

        comp_rec = {
            "organisation_number": org,
            "name": raw_name,
            "clean_name": clean_name,
            "category": cat,
            "strategy_results": {}
        }

        print(f"[{idx:2d}/{len(unresolved_orgs)}] {raw_name[:28]:28s} [{cat}]")

        for s_key, q_str in strategies.items():
            results = query_searxng(q_str)
            time.sleep(0.12)  # controlled pacing
            
            decision = choose_search_candidate(p, results)
            sel = decision.get("selected")
            
            query_stats[s_key]["queries"] += 1
            query_stats[s_key]["results_found"] += len(results)
            if sel:
                query_stats[s_key]["candidates_accepted"] += 1
                query_stats[s_key]["orgs_with_candidates"].add(org)

            comp_rec["strategy_results"][s_key] = {
                "query": q_str,
                "result_count": len(results),
                "selected_url": sel.get("url") if sel else None,
                "score": sel.get("score") if sel else None,
                "top_candidates": [c for c in decision.get("candidates", []) if c.get("status") != "rejected"][:3]
            }

        s1_cand = comp_rec["strategy_results"]["S1_name_muni"]["selected_url"]
        s2_cand = comp_rec["strategy_results"]["S2_name_norway"]["selected_url"]
        s3_cand = comp_rec["strategy_results"]["S3_name_org"]["selected_url"]
        s4_cand = comp_rec["strategy_results"]["S4_quoted_baseline"]["selected_url"]
        print(f"     S1(muni): {bool(s1_cand)} | S2(no): {bool(s2_cand)} | S3(org): {bool(s3_cand)} | S4(quoted): {bool(s4_cand)}")
        per_company_records.append(comp_rec)

    # Convert sets to counts for json serialization
    report_stats = {}
    for k, v in query_stats.items():
        report_stats[k] = {
            "queries": v["queries"],
            "results_found": v["results_found"],
            "candidates_accepted": v["candidates_accepted"],
            "distinct_companies_with_candidates": len(v["orgs_with_candidates"]),
            "candidate_companies": list(v["orgs_with_candidates"])
        }

    final_report = {
        "benchmark": "Series B & C: Controlled SearXNG and Query Strategy Benchmark",
        "unresolved_companies_tested": len(unresolved_orgs),
        "strategy_performance": report_stats,
        "companies": per_company_records
    }

    with open(OUT_SERIES_B_REPORT, "w", encoding="utf-8") as f:
        json.dump(final_report, f, indent=2, ensure_ascii=False)

    print("\n======================================================================")
    print("=== SERIES B & C RESULTS SUMMARY                                   ===")
    print("======================================================================")
    print(f"{'Strategy':22s} | {'Total Results':14s} | {'Candidates Found':16s} | {'Distinct Cos':12s}")
    print(f"{'-'*22}-+-{'-'*14}-+-{'-'*16}-+-{'-'*12}")
    for k, v in report_stats.items():
        print(f"{k:22s} | {v['results_found']:14d} | {v['candidates_accepted']:16d} | {v['distinct_companies_with_candidates']:12d}")

if __name__ == "__main__":
    main()
