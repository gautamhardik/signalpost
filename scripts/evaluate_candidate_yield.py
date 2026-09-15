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
    parser = argparse.ArgumentParser(description="Evaluate marginal discovery yield per channel.")
    parser.add_argument("--profiles", required=True, help="Path to profiles JSONL")
    parser.add_argument("--report", required=True, help="Path to batch run report JSON")
    parser.add_argument("--output", required=True, help="Path to output yield JSON")
    parser.add_argument("--dataset-output", default="out/candidate-relations-dataset.jsonl", help="Dataset output path")
    args = parser.parse_args()

    profiles = load_jsonl(args.profiles)
    report = json.loads(Path(args.report).read_text(encoding="utf-8")) if Path(args.report).exists() else {}

    channels = {
        "brreg_website": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
        "email_domain": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
        "domain_guessing": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
        "search_legal_name": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
        "subunit_brand_bridge": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
        "social_links": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
        "careers_hiring": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
        "site_news": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
        "subunits_official": {"candidates": 0, "verified": 0, "rejected": 0, "requests": 0},
    }

    dataset_rows: list[dict[str, Any]] = []

    for p in profiles:
        org = p.get("organisation_number")
        name = p.get("name")
        ev = p.get("evidence") or {}
        w_rec = ev.get("website") or {}
        w_val = w_rec.get("value") or {}
        w_pub = bool((w_val.get("identity_assessment") or {}).get("publishable"))

        # 1. BRREG Website
        if p.get("website"):
            channels["brreg_website"]["candidates"] += 1
            if w_pub and p.get("website") in str(w_val.get("final_url") or ""):
                channels["brreg_website"]["verified"] += 1
            else:
                channels["brreg_website"]["rejected"] += 1

        # 2. Discovered websites
        if w_pub:
            fin_url = w_val.get("final_url")
            dataset_rows.append({
                "target_org": org,
                "target_name": name,
                "candidate_url": fin_url,
                "candidate_type": "official_website",
                "identity_score": (w_val.get("identity_assessment") or {}).get("score"),
                "label": 1,
                "relation": "verified_exact_entity",
            })
        elif w_val.get("final_url"):
            # Hard negative (parked, parent conglomerate, or unverified)
            dataset_rows.append({
                "target_org": org,
                "target_name": name,
                "candidate_url": w_val.get("final_url"),
                "candidate_type": "official_website",
                "identity_score": (w_val.get("identity_assessment") or {}).get("score"),
                "label": 0,
                "relation": "unverified_or_different_entity",
            })

        # 3. Social
        discovered_socials = w_val.get("discovered_social_links") or []
        verified_socials = w_val.get("social_links") or []
        channels["social_links"]["candidates"] += len(discovered_socials)
        channels["social_links"]["verified"] += len(verified_socials)
        channels["social_links"]["rejected"] += max(0, len(discovered_socials) - len(verified_socials))

        for s in discovered_socials:
            is_pub = any(vs.get("url") == s.get("url") for vs in verified_socials)
            dataset_rows.append({
                "target_org": org,
                "target_name": name,
                "candidate_url": s.get("url"),
                "candidate_type": f"social_{s.get('platform')}",
                "label": 1 if is_pub else 0,
                "relation": "verified_social" if is_pub else "quarantined_social",
            })

        # 4. Hiring & News
        fp_obs = (ev.get("external_footprint", {}).get("value") or {}).get("observations") or []
        for o in fp_obs:
            sig = o.get("signal_type")
            plat = o.get("platform")
            if sig == "job_posting":
                channels["careers_hiring"]["verified"] += 1
            elif sig == "public_post" and plat == "news":
                channels["site_news"]["verified"] += 1
            elif sig == "place_summary" and plat == "brreg":
                channels["subunits_official"]["verified"] += 1

    # Request allocations from batch report
    budget_info = report.get("budget", {}).get("category_consumed") or {}
    channels["search_legal_name"]["requests"] = budget_info.get("search", 0)
    channels["brreg_website"]["requests"] = min(20, budget_info.get("website", 0))

    yield_report = {
        "report_title": "Signalpost Marginal Discovery Yield by Channel",
        "profiles_analyzed": len(profiles),
        "channels": channels,
        "efficiency_metrics": {
            "verified_discoveries_per_request": round(
                sum(c["verified"] for c in channels.values()) / max(1, report.get("operations", {}).get("outbound_requests", 1)),
                4
            ),
            "total_outbound_requests": report.get("operations", {}).get("outbound_requests", 0),
        },
        "dataset_summary": {
            "total_pairs": len(dataset_rows),
            "positive_pairs": sum(1 for r in dataset_rows if r["label"] == 1),
            "hard_negative_pairs": sum(1 for r in dataset_rows if r["label"] == 0),
        },
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(yield_report, indent=2, ensure_ascii=False), encoding="utf-8")

    Path(args.dataset_output).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.dataset_output).open("w", encoding="utf-8") as h:
        for r in dataset_rows:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(json.dumps(yield_report, indent=2))


if __name__ == "__main__":
    main()
