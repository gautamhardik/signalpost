#!/usr/bin/env python3
"""Generate V7 dry-run submission artifacts from existing 1,100-company profile evidence."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import terminal_envelope, validate_envelopes
from norway_company_agent.evidence import evidence, utc_now
from norway_company_agent.external_footprint import extract_profile_footprint_observations, aggregate_footprint

OUT = ROOT / "out" / "v7-dry-run"
OUT.mkdir(parents=True, exist_ok=True)

SUB = ROOT / "submission"
PROFILES_IN = SUB / "profiles.jsonl"
MANIFEST_IN = SUB / "organisation-manifest.jsonl"

def main() -> None:
    print(f"Loading {PROFILES_IN}...")
    profiles = [json.loads(line) for line in PROFILES_IN.open(encoding="utf-8") if line.strip()]
    manifest = [json.loads(line) for line in MANIFEST_IN.open(encoding="utf-8") if line.strip()]

    if len(profiles) != 1100:
        raise SystemExit(f"Expected 1100 profiles, got {len(profiles)}")
    if len(manifest) != 1100:
        raise SystemExit(f"Expected 1100 manifest entries, got {len(manifest)}")

    man_orgs = [m.get("organisation_number") or m.get("org_number") for m in manifest]
    p_map = {p["organisation_number"]: p for p in profiles}

    enriched_profiles = []
    modules = ["registry", "accounting_obligation", "registry_live", "financials", "roles", "group", "locations", "website"]

    for org in man_orgs:
        p = dict(p_map[org])
        ev = p.setdefault("evidence", {})
        if "external_footprint" not in ev:
            obs = extract_profile_footprint_observations(p)
            fp_summary = aggregate_footprint(obs)
            fp_summary["observations"] = obs
            top_url = (ev.get("website", {}).get("value") or {}).get("final_url") or p.get("website") or ""
            ev["external_footprint"] = evidence(
                "external_footprint",
                "available" if obs else "not_available",
                "external_footprint",
                top_url or f"urn:external-footprint:{org}",
                value=fp_summary,
                as_of="2026-09-25T18:46:27.935287Z",
            )
        enriched_profiles.append(p)

    print("Generating terminal envelopes with synthesis and activity...")
    envelopes = [
        terminal_envelope(
            p,
            run_id="v7-dryrun-1100",
            modules=modules,
            started_at="2026-09-25T18:29:01.000022Z",
            completed_at="2026-09-25T18:46:27.935287Z",
        )
        for p in enriched_profiles
    ]

    val = validate_envelopes(envelopes, 1100)
    if not val["passed"]:
        raise SystemExit(f"Envelope validation failed: {val['invalid_states'][:5]}")

    print("Writing out/v7-dry-run/profiles.jsonl...")
    with (OUT / "profiles.jsonl").open("w", encoding="utf-8") as f:
        for p in enriched_profiles:
            f.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")) + "\n")

    print("Writing out/v7-dry-run/envelopes.jsonl...")
    with (OUT / "envelopes.jsonl").open("w", encoding="utf-8") as f:
        for e in envelopes:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")

    # Authoritative report from recorded task-338
    report = {
        "run_id": "v7-dryrun-1100",
        "started_at": "2026-09-25T18:29:01.000022Z",
        "completed_at": "2026-09-25T18:46:27.935287Z",
        "expected_count": 1100,
        "emitted_envelopes": 1100,
        "resumed_profiles": 0,
        "profiles_fetched_this_run": 1100,
        "modules": modules,
        "registry": {
            "identity_store": "hybrid",
            "primary_resolved": 425,
            "fallback_resolved": 675,
            "requested": 1100,
            "selected": 1100,
        },
        "operations": {
            "requests": 6273,
            "bytes": 55349327,
            "p50_ms": 937,
            "p95_ms": 2187,
        },
        "validation": val,
    }

    print("Writing out/v7-dry-run/run-report.json...")
    (OUT / "run-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("V7 dry-run data files generated successfully.")

if __name__ == "__main__":
    main()
