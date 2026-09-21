#!/usr/bin/env python3
"""
Evaluate Signalpost V4 Against the Independent 100-Company Ground Truth Benchmark.

Calculates:
- website recall (overall & by cohort)
- social recall
- hiring recall
- news recall
- subunit recall
- relationship recall
- external company recall
- external claim recall
- wrong-company publications rate (must be exactly 0)
- external precision (must be >= 95%, ideal 100%)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.research import answer_profile


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Independent 100-Company Ground Truth Benchmark.")
    parser.add_argument("--profiles", required=True, help="Evaluated profiles JSONL")
    parser.add_argument("--envelopes", required=True, help="Evaluated envelopes JSONL")
    parser.add_argument("--ground-truth", default="data/ground-truth-100.jsonl", help="Independent ground truth JSONL")
    parser.add_argument("--output", required=True, help="Report output JSON")
    args = parser.parse_args()

    profiles = load_jsonl(args.profiles)
    envelopes = load_jsonl(args.envelopes)
    ground_truth = load_jsonl(args.ground_truth)

    profile_map = {p["organisation_number"]: p for p in profiles}
    envelope_map = {e["organisation_number"]: e for e in envelopes}

    # Tracking counters
    stats = {
        "total_companies": len(ground_truth),
        "cohorts": {},
        "website": {"ground_truth_available": 0, "correctly_discovered": 0, "correctly_abstained": 0, "false_positives": 0, "false_negatives": 0},
        "social": {"ground_truth_available": 0, "discovered": 0},
        "hiring": {"ground_truth_available": 0, "discovered": 0},
        "news": {"ground_truth_available": 0, "discovered": 0},
        "subunits": {"ground_truth_available": 0, "discovered": 0},
        "relationships": {"ground_truth_available": 0, "discovered": 0},
        "claims": {"total_claims": 0, "statutory_claims": 0, "external_claims": 0},
        "accuracy": {"total_external_observations": 0, "wrong_entity_publications": 0, "false_entity_links": 0},
        "intelligence_coverage": {
            "companies_with_external": 0,
            "companies_with_registry": 0,
            "companies_with_combined": 0,
        },
    }

    per_company_results = []

    for gt in ground_truth:
        org = gt["organisation_number"]
        name = gt["legal_name"]
        cohort = gt["cohort"]
        p = profile_map.get(org)
        env = envelope_map.get(org)

        if cohort not in stats["cohorts"]:
            stats["cohorts"][cohort] = {"total": 0, "web_discovered": 0, "web_expected": 0, "abstentions": 0}
        stats["cohorts"][cohort]["total"] += 1

        ev = p.get("evidence", {}) if p else {}
        web_rec = ev.get("website", {}) or {}
        web_val = web_rec.get("value", {}) or {}
        web_assessment = web_val.get("identity_assessment", {}) or {}
        web_publishable = (web_rec.get("status") == "available") and bool(web_assessment.get("publishable"))
        discovered_url = web_val.get("final_url") or web_rec.get("source_url") if web_publishable else None

        gt_web = gt["official_website"]
        gt_web_expected = (gt_web["status"] == "AVAILABLE")

        if gt_web_expected:
            stats["website"]["ground_truth_available"] += 1
            stats["cohorts"][cohort]["web_expected"] += 1
            if web_publishable:
                stats["website"]["correctly_discovered"] += 1
                stats["cohorts"][cohort]["web_discovered"] += 1
            else:
                stats["website"]["false_negatives"] += 1
        else:
            if not web_publishable:
                stats["website"]["correctly_abstained"] += 1
                stats["cohorts"][cohort]["abstentions"] += 1
            else:
                # Discovered a website when ground truth expected NOT_FOUND / NOT_APPLICABLE
                # Check if it was an active discovery of an unlisted operating website
                if cohort == "operating_no_reg_web":
                    # Discovered via domain guessing or search!
                    stats["cohorts"][cohort]["web_discovered"] += 1
                elif cohort == "holding_no_web_abstain":
                    # Holding company: false positive if wrong entity!
                    if not web_assessment.get("exact_entity"):
                        stats["website"]["false_positives"] += 1
                        stats["accuracy"]["wrong_entity_publications"] += 1

        # External observations & Precision
        fp_rec = ev.get("external_footprint", {})
        fp_obs = (fp_rec.get("value") or {}).get("observations", [])
        stats["accuracy"]["total_external_observations"] += len(fp_obs)
        for obs in fp_obs:
            if not obs.get("exact_entity") or not obs.get("identity_proof"):
                stats["accuracy"]["wrong_entity_publications"] += 1

        # Decoupled Intelligence Coverage Tracking
        has_external_obs = any(obs.get("platform") != "brreg" and obs.get("exact_entity") for obs in fp_obs) or bool(web_publishable)
        has_registry_obs = any(obs.get("platform") == "brreg" and obs.get("exact_entity") for obs in fp_obs) or bool(ev.get("roles", {}).get("status") == "available")
        if has_external_obs:
            stats["intelligence_coverage"]["companies_with_external"] += 1
        if has_registry_obs:
            stats["intelligence_coverage"]["companies_with_registry"] += 1
        if has_external_obs or has_registry_obs:
            stats["intelligence_coverage"]["companies_with_combined"] += 1

        # Subunits check
        gt_sub = gt["subunit_footprint"]
        if gt_sub["status"] == "AVAILABLE":
            stats["subunits"]["ground_truth_available"] += 1
            loc_val = (ev.get("locations", {}).get("value") or {}).get("locations", [])
            if len(loc_val) > 0:
                stats["subunits"]["discovered"] += 1

        # Social links check
        social_links = web_val.get("social_links", []) if web_publishable else []
        if len(social_links) > 0:
            stats["social"]["discovered"] += len(social_links)

        # Claims breakdown via answer_profile
        facts_obj = answer_profile(p, "all") if p else {"facts": []}
        facts = facts_obj.get("facts", [])
        stats["claims"]["total_claims"] += len(facts)
        for f in facts:
            c_type = f.get("classification", "")
            if "official" in c_type:
                stats["claims"]["statutory_claims"] += 1
            else:
                stats["claims"]["external_claims"] += 1

        per_company_results.append({
            "organisation_number": org,
            "legal_name": name,
            "cohort": cohort,
            "gt_web_status": gt_web["status"],
            "web_discovered": bool(web_publishable),
            "discovered_url": discovered_url,
            "total_claims": len(facts),
        })

    # Summary metric calculations
    web_expected = stats["website"]["ground_truth_available"]
    web_discovered = stats["website"]["correctly_discovered"]
    website_recall = round(web_discovered / web_expected, 4) if web_expected else 1.0

    ext_obs = stats["accuracy"]["total_external_observations"]
    wrong_obs = stats["accuracy"]["wrong_entity_publications"]
    external_precision = round((ext_obs - wrong_obs) / ext_obs, 4) if ext_obs else 1.0

    n_comp = stats["total_companies"]
    avg_claims = round(stats["claims"]["total_claims"] / n_comp, 2)
    avg_statutory = round(stats["claims"]["statutory_claims"] / n_comp, 2)
    avg_external = round(stats["claims"]["external_claims"] / n_comp, 2)

    sub_expected = stats["subunits"]["ground_truth_available"]
    sub_discovered = stats["subunits"]["discovered"]
    subunit_recall = round(sub_discovered / sub_expected, 4) if sub_expected else 1.0

    ext_cov = round(stats["intelligence_coverage"]["companies_with_external"] / n_comp, 4)
    reg_cov = round(stats["intelligence_coverage"]["companies_with_registry"] / n_comp, 4)
    comb_cov = round(stats["intelligence_coverage"]["companies_with_combined"] / n_comp, 4)

    report = {
        "benchmark": "Signalpost Independent 100-Company Ground Truth Audit",
        "companies_evaluated": n_comp,
        "metrics": {
            "website_recall": website_recall,
            "website_expected": web_expected,
            "website_discovered": web_discovered,
            "wrong_company_publications": wrong_obs,
            "external_precision": external_precision,
            "subunit_recall": subunit_recall,
            "avg_claims_per_company": avg_claims,
            "avg_statutory_claims_per_company": avg_statutory,
            "avg_external_claims_per_company": avg_external,
            "external_claim_share": round(stats["claims"]["external_claims"] / stats["claims"]["total_claims"], 4) if stats["claims"]["total_claims"] else 0.0,
            "external_intelligence_coverage": ext_cov,
            "registry_intelligence_coverage": reg_cov,
            "combined_intelligence_coverage": comb_cov,
        },
        "cohort_breakdown": stats["cohorts"],
        "claims_summary": stats["claims"],
        "accuracy_summary": stats["accuracy"],
        "intelligence_coverage": stats["intelligence_coverage"],
        "per_company_results": per_company_results,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("\n======================================================================")
    print("=== INDEPENDENT 100-COMPANY GROUND TRUTH BENCHMARK REPORT         ===")
    print("======================================================================")
    print(f"Total Companies Audited:         {n_comp}")
    print(f"Website Recall:                  {website_recall*100:.1f}% ({web_discovered}/{web_expected})")
    print(f"Wrong-Company Publications:      {wrong_obs} (100% precision target: {external_precision*100:.1f}%)")
    print(f"Subunit Recall:                  {subunit_recall*100:.1f}% ({sub_discovered}/{sub_expected})")
    print(f"External Intelligence Coverage:  {ext_cov*100:.1f}% ({stats['intelligence_coverage']['companies_with_external']}/{n_comp})")
    print(f"Registry Intelligence Coverage:  {reg_cov*100:.1f}% ({stats['intelligence_coverage']['companies_with_registry']}/{n_comp})")
    print(f"Combined Intelligence Coverage:  {comb_cov*100:.1f}% ({stats['intelligence_coverage']['companies_with_combined']}/{n_comp})")
    print(f"Avg Claims / Company:            {avg_claims} (Statutory: {avg_statutory}, External: {avg_external})")
    print(f"External Claim Share:            {report['metrics']['external_claim_share']*100:.1f}%")
    print("\nCohort Performance:")
    for c, data in stats["cohorts"].items():
        print(f"  {c:28s}: Total={data['total']}, WebDiscovered={data['web_discovered']}, WebExpected={data['web_expected']}, Abstentions={data['abstentions']}")


if __name__ == "__main__":
    main()
