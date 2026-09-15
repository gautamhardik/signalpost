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


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate weighted external company and claim recall.")
    parser.add_argument("--profiles", required=True, help="Path to profile outputs JSONL")
    parser.add_argument("--ground-truth", required=True, help="Path to ground truth / benchmark JSONL")
    parser.add_argument("--output", required=True, help="Path to output recall report JSON")
    args = parser.parse_args()

    profiles = load_jsonl(args.profiles)
    truth = load_jsonl(args.ground_truth)

    profile_map = {p.get("organisation_number"): p for p in profiles}

    # Dimensions tracked per company
    weights = {
        "website": 0.35,
        "social": 0.25,
        "hiring": 0.15,
        "news": 0.10,
        "subunits": 0.15,
    }

    results = []
    total_weighted_recall = 0.0
    evaluated_companies = 0

    known_websites_total = 0
    discovered_websites_count = 0

    known_social_total = 0
    discovered_social_count = 0

    known_hiring_total = 0
    discovered_hiring_count = 0

    for item in truth:
        org = item.get("organisation_number")
        name = item.get("name")
        p = profile_map.get(org)
        if not p:
            continue

        evaluated_companies += 1
        ev = p.get("evidence") or {}

        # 1. Website Discovery Check
        has_known_web = bool(item.get("website"))
        web_rec = ev.get("website") or {}
        web_val = web_rec.get("value") or {}
        has_disc_web = (web_rec.get("status") == "available") and bool((web_val.get("identity_assessment") or {}).get("publishable"))

        if has_known_web:
            known_websites_total += 1
            if has_disc_web:
                discovered_websites_count += 1

        # 2. Footprint Observations Check
        fp_rec = ev.get("external_footprint") or {}
        fp_obs = (fp_rec.get("value") or {}).get("observations") or []

        has_social = any(o.get("platform") in {"linkedin", "facebook", "instagram", "youtube", "x"} for o in fp_obs)
        has_hiring = any(o.get("signal_type") == "job_posting" for o in fp_obs)
        has_news = any(o.get("signal_type") == "public_post" and o.get("platform") == "news" for o in fp_obs)
        has_subunits = any(o.get("signal_type") == "place_summary" and o.get("platform") == "brreg" for o in fp_obs)

        # Company Weighted Recall for this entity
        # Entities with known websites are expected to have active web/social presence
        # Entities with no web are expected to have subunit presence
        if has_known_web:
            comp_score = (
                (weights["website"] if has_disc_web else 0.0) +
                (weights["social"] if has_social else 0.0) +
                (weights["hiring"] if has_hiring else 0.0) +
                (weights["news"] if has_news else 0.0) +
                (weights["subunits"] if has_subunits else 0.0)
            )
        else:
            # For sparse/holding/no-web companies, finding external subunits + any verified presence satisfies recall
            comp_score = 1.0 if (has_subunits or has_disc_web or has_social) else 0.0

        total_weighted_recall += comp_score
        results.append({
            "organisation_number": org,
            "name": name,
            "has_known_web": has_known_web,
            "has_disc_web": has_disc_web,
            "has_social": has_social,
            "has_hiring": has_hiring,
            "has_news": has_news,
            "has_subunits": has_subunits,
            "weighted_recall": round(comp_score, 4),
        })

    avg_weighted_recall = total_weighted_recall / evaluated_companies if evaluated_companies else 0.0

    report = {
        "benchmark_name": "Signalpost Weighted External Recall Benchmark",
        "evaluated_companies": evaluated_companies,
        "qualification_gate": ">= 60% weighted external company recall",
        "weighted_external_company_recall": round(avg_weighted_recall, 4),
        "qualification_gate_met": avg_weighted_recall >= 0.60,
        "website_recall": round(discovered_websites_count / known_websites_total, 4) if known_websites_total else 0.0,
        "sample_evaluations": results[:15],
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
