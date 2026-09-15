#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import validate_envelopes  # noqa: E402


def validate_corpus(
    manifest_path: str | Path,
    profiles_path: str | Path,
    envelopes_path: str | Path,
    report_path: str | Path,
    expected_min_count: int = 1000,
) -> dict:
    manifest_lines = [json.loads(l) for l in Path(manifest_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    profiles_lines = [json.loads(l) for l in Path(profiles_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    envelopes_lines = [json.loads(l) for l in Path(envelopes_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    report = json.loads(Path(report_path).read_text(encoding="utf-8"))

    m_orgs = [m["organisation_number"] for m in manifest_lines]
    p_orgs = [p["organisation_number"] for p in profiles_lines]
    e_orgs = [e["organisation_number"] for e in envelopes_lines]

    total_manifest = len(m_orgs)
    total_profiles = len(p_orgs)
    total_envelopes = len(e_orgs)

    unique_manifest = len(set(m_orgs))
    unique_profiles = len(set(p_orgs))
    unique_envelopes = len(set(e_orgs))

    # Invariants
    count_sufficient = total_profiles >= expected_min_count
    counts_match = (total_manifest == total_profiles == total_envelopes)
    unique_match = (unique_manifest == unique_profiles == unique_envelopes == total_manifest)
    order_identical = (m_orgs == p_orgs == e_orgs)

    # Validate envelopes terminal states
    envelope_val = validate_envelopes(envelopes_lines, total_manifest)

    # Check evidence & provenance integrity
    missing_evidence_count = 0
    missing_timestamps_count = 0
    missing_source_urls_count = 0
    wrong_company_observations = 0

    for p in profiles_lines:
        ev = p.get("evidence", {})
        if not ev.get("registry"):
            missing_evidence_count += 1
        for mod, rec in ev.items():
            if rec.get("status") == "available":
                if not rec.get("retrieved_at"):
                    missing_timestamps_count += 1
                if not rec.get("source_url"):
                    missing_source_urls_count += 1

        # Check website identity assessment
        w_rec = ev.get("website", {})
        if w_rec.get("status") == "available":
            val = w_rec.get("value") or {}
            ida = val.get("identity_assessment") or {}
            if ida.get("publishable") and not ida.get("score", 0) >= 0.90:
                wrong_company_observations += 1

    audit_result = {
        "corpus_validation": "PASSED" if (count_sufficient and counts_match and unique_match and envelope_val["passed"] and wrong_company_observations == 0) else "FAILED",
        "counts": {
            "manifest_records": total_manifest,
            "profile_records": total_profiles,
            "envelope_records": total_envelopes,
            "minimum_required": expected_min_count,
            "count_sufficient": count_sufficient,
            "counts_exact_match": counts_match,
            "order_identical": order_identical,
        },
        "envelope_compliance": {
            "passed": envelope_val["passed"],
            "silent_drops": total_manifest - total_envelopes,
            "all_terminal": envelope_val["checks"].get("all_entity_states_terminal", False),
            "invalid_states": envelope_val.get("invalid_states", []),
        },
        "evidence_integrity": {
            "missing_registry_evidence": missing_evidence_count,
            "missing_retrieval_timestamps": missing_timestamps_count,
            "missing_source_urls": missing_source_urls_count,
            "wrong_company_publications": wrong_company_observations,
            "perfect_provenance": (missing_evidence_count == 0 and missing_timestamps_count == 0 and missing_source_urls_count == 0 and wrong_company_observations == 0),
        },
        "operations": {
            "run_id": report.get("run_id"),
            "outbound_requests": report.get("operations", {}).get("requests", 0),
            "p50_ms": report.get("operations", {}).get("p50_ms"),
            "p95_ms": report.get("operations", {}).get("p95_ms"),
        }
    }
    return audit_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Signalpost 1,000+ Corpus Rigorous Validator")
    parser.add_argument("--manifest", required=True, help="Path to organisation-manifest JSONL")
    parser.add_argument("--profiles", required=True, help="Path to profiles JSONL")
    parser.add_argument("--envelopes", required=True, help="Path to envelopes JSONL")
    parser.add_argument("--report", required=True, help="Path to run-report JSON")
    parser.add_argument("--min-count", type=int, default=1000, help="Expected minimum count (default 1000)")
    parser.add_argument("--output", default="out/corpus-1100-validation.json", help="Output report JSON")
    args = parser.parse_args()

    result = validate_corpus(args.manifest, args.profiles, args.envelopes, args.report, expected_min_count=args.min_count)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["corpus_validation"] != "PASSED":
        sys.exit(1)


if __name__ == "__main__":
    main()
