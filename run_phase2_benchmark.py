import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path("src").resolve()))

import json
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from norway_company_agent.discovery import choose_search_candidate, BLOCKED_DISCOVERY_HOSTS
from norway_company_agent.website import fetch_website
from norway_company_agent.identity import assess_website_identity

PROFILES_PATH = Path("out/benchmark-100-profiles.jsonl")
BENCHMARK_SPEC_PATH = Path("benchmark-100.jsonl")
RAW_RESULTS_PATH = Path("out/phase2-searxng-raw.jsonl")
SUMMARY_REPORT_PATH = Path("out/phase2-summary.json")

SEARXNG_URL = "http://localhost:8080/search"

def query_searxng(query_str: str, timeout: int = 10) -> list[dict]:
    params = urllib.parse.urlencode({"q": query_str, "format": "json"})
    url = f"{SEARXNG_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "signalpost-benchmark/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            results = data.get("results", [])
            parsed = []
            for rank, r in enumerate(results, start=1):
                parsed.append({
                    "rank": rank,
                    "url": r.get("url"),
                    "title": r.get("title") or "",
                    "snippet": r.get("content") or "",
                    "engine": r.get("engine") or "",
                    "query": query_str,
                })
            return parsed
    except Exception as exc:
        return []

def main():
    print("======================================================================")
    print("=== PHASE 2: SEARXNG DISCOVERY BENCHMARK ACROSS 80 MISSING ORGS    ===")
    print("======================================================================")

    # 1. Load profiles & category mappings
    cat_map = {json.loads(l)["organisation_number"]: json.loads(l).get("benchmark_category") for l in open(BENCHMARK_SPEC_PATH, encoding="utf-8")}
    all_profiles = [json.loads(l) for l in open(PROFILES_PATH, encoding="utf-8")]
    
    # Filter to exactly the 80 missing-website companies (state == "not_found" in V0 baseline)
    missing_profiles = [p for p in all_profiles if not p.get("website")]
    print(f"Loaded {len(missing_profiles)} missing-website profiles (expected 80).")

    # 2. Define 3 query variants for each company
    # Q1: "{name}" {org} {municipality}
    # Q2: "{name}" {municipality}
    # Q3: "{name}" Norway
    companies_queries = []
    for p in missing_profiles:
        name = " ".join(str(p.get("name") or "").split())
        org = str(p.get("organisation_number") or "")
        muni = " ".join(str(p.get("municipality") or "").split())
        cat = cat_map.get(org, "unknown")

        q1 = f'"{name}" {org}' + (f' {muni}' if muni else '')
        q2 = f'"{name}"' + (f' {muni}' if muni else '')
        q3 = f'"{name}" Norway'

        companies_queries.append({
            "profile": p,
            "category": cat,
            "queries": {"Q1": q1, "Q2": q2, "Q3": q3}
        })

    # 3. Execute searches sequentially or with controlled rate to not swamp local SearXNG
    print(f"Executing 3 queries each across {len(companies_queries)} companies = {len(companies_queries)*3} searches...")
    raw_records = []
    company_outcomes = []

    for idx, item in enumerate(companies_queries, start=1):
        p = item["profile"]
        org = p["organisation_number"]
        name = p["name"]
        cat = item["category"]

        print(f"[{idx:2d}/{len(companies_queries)}] {name[:28]:28s} ({org}) [{cat}]")

        company_res = {
            "organisation_number": org,
            "name": name,
            "category": cat,
            "results_by_query": {},
            "gate_by_query": {},
            "combined_candidates": [],
        }

        # Query all 3 variants
        for q_type, q_str in item["queries"].items():
            res = query_searxng(q_str)
            company_res["results_by_query"][q_type] = res
            raw_records.append({
                "organisation_number": org,
                "legal_name": name,
                "category": cat,
                "query_type": q_type,
                "query": q_str,
                "results_count": len(res),
                "results": res
            })

            # Evaluate each query variant independently through discovery gate
            decision = choose_search_candidate(p, res)
            company_res["gate_by_query"][q_type] = {
                "has_candidate": bool(decision.get("selected")),
                "selected_url": decision.get("selected", {}).get("url") if decision.get("selected") else None,
                "score": decision.get("selected", {}).get("score") if decision.get("selected") else None,
            }
            time.sleep(0.05) # small throttle for SearXNG

        # Also evaluate merged/deduped results across all 3 queries
        all_res = []
        seen_urls = set()
        for res in company_res["results_by_query"].values():
            for r in res:
                u = r.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    all_res.append(r)

        merged_decision = choose_search_candidate(p, all_res)
        company_res["merged_gate"] = {
            "has_candidate": bool(merged_decision.get("selected")),
            "selected_url": merged_decision.get("selected", {}).get("url") if merged_decision.get("selected") else None,
            "score": merged_decision.get("selected", {}).get("score") if merged_decision.get("selected") else None,
            "all_candidates": [c for c in merged_decision.get("candidates", []) if c.get("status") != "rejected"]
        }

        # Print quick discovery status
        q1_cand = company_res["gate_by_query"]["Q1"]["selected_url"]
        q2_cand = company_res["gate_by_query"]["Q2"]["selected_url"]
        q3_cand = company_res["gate_by_query"]["Q3"]["selected_url"]
        merged_cand = company_res["merged_gate"]["selected_url"]
        
        cand_str = f"Q1: {bool(q1_cand)} | Q2: {bool(q2_cand)} | Q3: {bool(q3_cand)} | Merged: {merged_cand or 'None'}"
        print(f"     -> {cand_str}")

        company_outcomes.append(company_res)

    # 4. Save raw SearXNG records
    RAW_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RAW_RESULTS_PATH, "w", encoding="utf-8") as f:
        for rec in raw_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\nSaved raw search data to {RAW_RESULTS_PATH}")

    # 5. Now, for all companies where the discovery gate accepted a candidate (under any query or merged),
    # crawl the candidate URL and run V3 identity verification!
    print("\n======================================================================")
    print("=== VERIFYING ACCEPTED CANDIDATES WITH CRAWLER & V3 IDENTITY       ===")
    print("======================================================================")

    verification_results = {}
    
    for outcome in company_outcomes:
        org = outcome["organisation_number"]
        p = [x for x in missing_profiles if x["organisation_number"] == org][0]
        
        # Check all unique candidate URLs selected across Q1, Q2, Q3, and Merged
        selected_urls = set()
        for k in ["Q1", "Q2", "Q3"]:
            u = outcome["gate_by_query"][k]["selected_url"]
            if u: selected_urls.add(u)
        if outcome["merged_gate"]["selected_url"]:
            selected_urls.add(outcome["merged_gate"]["selected_url"])

        outcome["identity_eval"] = {}

        if not selected_urls:
            outcome["identity_eval"]["status"] = "abstained"
            continue

        for cand_url in selected_urls:
            print(f"Testing {outcome['name'][:25]} -> {cand_url}")
            crawl_rec, crawl_metrics = fetch_website(cand_url)
            crawl_status = crawl_rec.get("status")

            if crawl_status != "available":
                print(f"  Crawl status: {crawl_status} ({crawl_rec.get('note')})")
                outcome["identity_eval"][cand_url] = {
                    "crawl_status": crawl_status,
                    "identity_score": None,
                    "publishable": False,
                    "reasons": [crawl_rec.get("note")]
                }
                continue

            test_profile = dict(p)
            test_profile["evidence"] = dict(p.get("evidence", {}))
            test_profile["evidence"]["website"] = crawl_rec

            id_res = assess_website_identity(test_profile)
            print(f"  Identity: status={id_res['status']}, score={id_res['score']}, publishable={id_res['publishable']}")
            print(f"  Reasons: {id_res['reasons']}")
            if id_res.get("registry_identity"):
                print(f"  Registry corroboration: {id_res['registry_identity']}")

            outcome["identity_eval"][cand_url] = {
                "crawl_status": crawl_status,
                "identity_score": id_res["score"],
                "publishable": id_res["publishable"],
                "status": id_res["status"],
                "reasons": id_res["reasons"],
                "registry_identity": id_res.get("registry_identity")
            }

    # 6. Aggregate Metrics
    # - Gate Recall for Q1, Q2, Q3, and Merged
    # - Verified sites for Q1, Q2, Q3, and Merged
    # - Category Breakdown
    metrics_by_query = {"Q1": {"candidates": 0, "verified": 0, "blocked": 0, "false_positives": 0},
                        "Q2": {"candidates": 0, "verified": 0, "blocked": 0, "false_positives": 0},
                        "Q3": {"candidates": 0, "verified": 0, "blocked": 0, "false_positives": 0},
                        "Merged": {"candidates": 0, "verified": 0, "blocked": 0, "false_positives": 0}}

    by_category = {}

    for o in company_outcomes:
        cat = o["category"]
        if cat not in by_category:
            by_category[cat] = {
                "total": 0,
                "candidates_accepted": 0,
                "verified_available": 0,
                "blocked": 0,
                "abstained": 0
            }
        by_category[cat]["total"] += 1

        merged_u = o["merged_gate"]["selected_url"]
        if merged_u:
            by_category[cat]["candidates_accepted"] += 1
            eval_info = o["identity_eval"].get(merged_u, {})
            if eval_info.get("publishable"):
                by_category[cat]["verified_available"] += 1
            elif eval_info.get("crawl_status") in ("blocked", "blocked_robots", "blocked_policy"):
                by_category[cat]["blocked"] += 1
            else:
                by_category[cat]["abstained"] += 1
        else:
            by_category[cat]["abstained"] += 1

        # Per query metrics
        for q_name in ["Q1", "Q2", "Q3"]:
            u = o["gate_by_query"][q_name]["selected_url"]
            if u:
                metrics_by_query[q_name]["candidates"] += 1
                eval_info = o["identity_eval"].get(u, {})
                if eval_info.get("publishable"):
                    metrics_by_query[q_name]["verified"] += 1
                elif eval_info.get("crawl_status") in ("blocked", "blocked_robots", "blocked_policy"):
                    metrics_by_query[q_name]["blocked"] += 1

        if merged_u:
            metrics_by_query["Merged"]["candidates"] += 1
            eval_info = o["identity_eval"].get(merged_u, {})
            if eval_info.get("publishable"):
                metrics_by_query["Merged"]["verified"] += 1
            elif eval_info.get("crawl_status") in ("blocked", "blocked_robots", "blocked_policy"):
                metrics_by_query["Merged"]["blocked"] += 1

    summary = {
        "total_missing_companies": len(company_outcomes),
        "metrics_by_query": metrics_by_query,
        "by_category": by_category,
        "company_outcomes": company_outcomes
    }

    with open(SUMMARY_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n======================================================================")
    print("=== PHASE 2 DISCOVERY BENCHMARK SUMMARY                            ===")
    print("======================================================================")
    print(f"Total Companies Tested: {len(company_outcomes)}")
    print("\nQuery Strategy Comparison:")
    print(f"  {'Query Strategy':15s} | {'Candidates Found':18s} | {'Verified Available':20s} | {'Blocked':10s}")
    print(f"  {'-'*15}-+-{'-'*18}-+-{'-'*20}-+-{'-'*10}")
    for q_name, m in metrics_by_query.items():
        print(f"  {q_name:15s} | {m['candidates']:18d} | {m['verified']:20d} | {m['blocked']:10d}")

    print("\nPerformance by Category (Merged Strategy):")
    print(f"  {'Category':25s} | {'Total':5s} | {'Candidates':10s} | {'Verified':10s} | {'Blocked':8s} | {'Abstained':10s}")
    print(f"  {'-'*25}-+-{'-'*5}-+-{'-'*10}-+-{'-'*10}-+-{'-'*8}-+-{'-'*10}")
    for cat, c_data in sorted(by_category.items()):
        print(f"  {cat:25s} | {c_data['total']:5d} | {c_data['candidates_accepted']:10d} | {c_data['verified_available']:10d} | {c_data['blocked']:8d} | {c_data['abstained']:10d}")

if __name__ == "__main__":
    main()
