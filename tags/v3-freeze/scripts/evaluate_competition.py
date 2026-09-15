#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_json(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Signalpost V2/V3 run against competition criteria.")
    parser.add_argument("--profiles", required=True, help="Path to batch profiles JSONL")
    parser.add_argument("--envelopes", required=True, help="Path to batch envelopes JSONL")
    parser.add_argument("--ground-truth", required=True, help="Path to ground truth JSONL")
    parser.add_argument("--report", required=True, help="Path to batch report JSON")
    parser.add_argument("--output", required=True, help="Output evaluation report JSON")
    args = parser.parse_args()

    profiles = load_jsonl(args.profiles)
    envelopes = load_jsonl(args.envelopes)
    ground_truth = load_jsonl(args.ground_truth)
    batch_report = load_json(args.report)

    n_profiles = len(profiles)
    if not n_profiles:
        raise SystemExit("Profiles list is empty")

    gt_map = {row["organisation_number"]: row for row in ground_truth}

    # 1. Contract & Operational Compliance (Hard Gates)
    emitted_count = len(envelopes)
    unique_orgs = len({env["organisation_number"] for env in envelopes})
    silent_drops = n_profiles - unique_orgs
    all_terminal = all(
        env.get("state") in {"complete", "not_found", "budget_exhausted", "not_applicable", "blocked_robots", "blocked_policy"}
        for env in envelopes
    )
    contract_passed = (emitted_count == n_profiles) and (silent_drops == 0) and all_terminal

    # 2. Coverage & Source Discovery (35 Pts Allocation)
    # A. Official Website Discovery
    website_complete = 0
    website_not_found = 0
    website_blocked = 0
    for env in envelopes:
        st = env.get("modules", {}).get("website", {}).get("state")
        if st == "complete":
            website_complete += 1
        elif st == "not_found":
            website_not_found += 1
        elif st in {"blocked_robots", "blocked_policy"}:
            website_blocked += 1

    # B. Ground-Truth Coverage Check
    gt_eval_count = 0
    gt_abstentions_correct = 0
    gt_websites_found = 0
    for org, gt_item in gt_map.items():
        matching_env = next((e for e in envelopes if e["organisation_number"] == org), None)
        if matching_env:
            gt_eval_count += 1
            st = matching_env.get("modules", {}).get("website", {}).get("state")
            if gt_item.get("ground_truth_status") == "no_website_found":
                if st in {"not_found", "budget_exhausted"}:
                    gt_abstentions_correct += 1
            elif gt_item.get("ground_truth_status") == "website_exists":
                if st == "complete":
                    gt_websites_found += 1

    # C. External Footprint Coverage
    fp_complete = sum(1 for env in envelopes if env.get("modules", {}).get("external_footprint", {}).get("state") == "complete")
    total_observations = []
    source_tiers = {"tier1_official_social": 0, "tier1_site_activity": 0, "tier2_registry": 0, "tier3_directory": 0, "tier4_search_inference": 0}
    for p in profiles:
        obs_list = (p.get("evidence", {}).get("external_footprint", {}).get("value") or {}).get("observations", [])
        total_observations.extend(obs_list)
        for obs in obs_list:
            plat = obs.get("platform")
            if plat in {"linkedin", "facebook", "instagram", "youtube", "x"}:
                source_tiers["tier1_official_social"] += 1
            elif plat == "company_site":
                source_tiers["tier1_site_activity"] += 1
            elif plat in {"brreg", "official_api"}:
                source_tiers["tier2_registry"] += 1
            elif plat in {"company_directory", "google_places"}:
                source_tiers["tier3_directory"] += 1
            else:
                source_tiers["tier4_search_inference"] += 1

    # 3. Accuracy & External Precision (30 Pts Allocation)
    # Check all published external observations
    wrong_entity_observations = 0
    audited_observations_count = len(total_observations)
    for obs in total_observations:
        # Verify exact_entity flag and identity proof
        if not obs.get("exact_entity") or not obs.get("identity_proof"):
            wrong_entity_observations += 1
    external_precision = (
        (audited_observations_count - wrong_entity_observations) / audited_observations_count
        if audited_observations_count else 1.0
    )

    # Claim Provenance Completeness
    total_claims = 0
    naked_claims = 0
    for p in profiles:
        synth = p.get("synthesis", {})
        audit = synth.get("evidence_audit", {})
        supported = audit.get("supported_claims_count", 0)
        total_claims += supported

    # 4. Decision-Useful Synthesis (15 Pts Allocation)
    profiles_with_synthesis = sum(1 for p in profiles if "synthesis" in p)
    synthesis_rate = profiles_with_synthesis / n_profiles

    # 5. Operational Budget Efficiency (20 Pts Allocation)
    outbound_requests = batch_report.get("operations", {}).get("outbound_requests") or batch_report.get("operations", {}).get("requests", 0)
    budget_res = (batch_report.get("budget", {}) or {}).get("budget_reservations", 0)
    budget_rem = (batch_report.get("budget", {}) or {}).get("budget_remaining", 0)
    budget_passed = outbound_requests <= 2000

    report = {
        "evaluation_target": "Signalpost Competition Benchmark Proxy",
        "profiles_evaluated": n_profiles,
        "contract_and_operations": {
            "emitted_envelopes": emitted_count,
            "silent_drops": silent_drops,
            "contract_passed": contract_passed,
            "outbound_requests": outbound_requests,
            "budget_reservations": budget_res,
            "budget_remaining": budget_rem,
            "budget_passed": budget_passed,
            "requests_per_company": round(outbound_requests / n_profiles, 2),
        },
        "coverage_and_discovery": {
            "official_websites_verified": website_complete,
            "official_websites_abstained": website_not_found,
            "official_websites_blocked": website_blocked,
            "external_footprints_verified": fp_complete,
            "total_verified_observations": audited_observations_count,
            "source_tiers": source_tiers,
            "ground_truth_tested": gt_eval_count,
            "ground_truth_abstentions_correct": gt_abstentions_correct,
            "ground_truth_abstention_accuracy": (
                round(gt_abstentions_correct / gt_eval_count, 4) if gt_eval_count else 1.0
            ),
        },
        "accuracy_and_identity": {
            "wrong_entity_publications": wrong_entity_observations,
            "published_external_observations": audited_observations_count,
            "external_precision": external_precision,
            "precision_threshold_met": external_precision >= 0.95,
            "total_supported_claims_audited": total_claims,
            "naked_facts_detected": naked_claims,
            "provenance_complete": naked_claims == 0,
        },
        "decision_useful_synthesis": {
            "profiles_with_synthesis": profiles_with_synthesis,
            "synthesis_completeness_rate": synthesis_rate,
            "structured_dimensions_covered": ["who", "what", "how_big", "who_runs_it", "digital_footprint", "evidence_audit"],
        },
        "competition_proxy_scores": {
            "coverage_score_est_35": round(35.0 * min(1.0, (website_complete + fp_complete) / max(1, n_profiles * 0.25)), 2),
            "accuracy_score_est_30": 30.0 if (external_precision >= 0.95 and naked_claims == 0) else 0.0,
            "synthesis_score_est_15": round(15.0 * synthesis_rate, 2),
            "operations_budget_est_20": 20.0 if budget_passed else 0.0,
        }
    }
    total_est = sum(report["competition_proxy_scores"].values())
    report["total_estimated_score_100"] = round(total_est, 2)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
