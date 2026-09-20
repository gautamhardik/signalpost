#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import profile_complete_for_modules, profiles_from_bulk, read_organisation_inputs, terminal_envelope, validate_envelopes  # noqa: E402
from norway_company_agent.evidence import utc_now  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402
from norway_company_agent.discovery import (
    assess_candidate_funnel,
    build_flexible_company_search_queries,
    choose_search_candidate,
    generate_company_candidate_sources,
    normalize_candidate_url,
)
import urllib.parse
import urllib.request


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluator-owned Signalpost batch contract")
    parser.add_argument("--organisations", required=True, help="JSON, JSONL, or text organisation-number list")
    parser.add_argument("--bulk", default="data/company_universe_411k.db", help="Frozen Brreg entity snapshot (SQLite DB, CSV, or JSONL.GZ)")
    parser.add_argument("--output", required=True, help="Terminal envelope JSONL")
    parser.add_argument("--profiles-output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-count", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--modules", default="registry,accounting_obligation,registry_live,financials,roles,group,locations,website")
    args = parser.parse_args()

    started_at = utc_now()
    organisation_inputs = read_organisation_inputs(args.organisations)
    orgs = [item["organisation_number"] for item in organisation_inputs]
    if len(orgs) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} organisations, received {len(orgs)}")
    profiles, registry_metadata = profiles_from_bulk(args.bulk, orgs)
    annotations = {item["organisation_number"]: item for item in organisation_inputs}
    for profile in profiles:
        for key in ("evaluation_split", "sample_slice"):
            if key in annotations[profile["organisation_number"]]:
                profile[key] = annotations[profile["organisation_number"]][key]
    requested_modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    fetch_modules = set(requested_modules) - {"registry", "accounting_obligation", "website"}
    operations = {"requests": 0, "bytes": 0, "latencies_ms": []}

    def enrich(profile: dict) -> tuple[dict, dict]:
        records, metrics = fetch_official_modules(profile["organisation_number"], fetch_modules)
        profile["evidence"].update(records)
        website_metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
        if "website" in requested_modules:
            website_url = profile.get("website")
            website_record, website_metrics = fetch_website(website_url)
            gated = apply_website_identity_gate(profile, website_record)
            
            # If no website or not publishable/available, execute structured candidate discovery funnel
            if gated["website"].get("status") not in ("available", "blocked") or not (gated["assessment"] or {}).get("publishable"):
                candidate_sources = generate_company_candidate_sources(profile)
                unfetched_cands = [c for c in candidate_sources if normalize_candidate_url(c.url) != normalize_candidate_url(website_url)]
                
                def batch_fetch(url: str) -> tuple[dict, dict]:
                    rec, met = fetch_website(url)
                    website_metrics["requests"] += met.get("requests", 0)
                    website_metrics["bytes"] += met.get("bytes", 0)
                    website_metrics["latencies_ms"].extend(met.get("latencies_ms", []))
                    return rec, met

                funnel_result = assess_candidate_funnel(
                    profile,
                    unfetched_cands,
                    fetch_fn=batch_fetch,
                    identity_gate_fn=apply_website_identity_gate,
                    max_fetches=3,
                )
                profile["discovery_funnel"] = funnel_result.get("funnel_metrics")
                if funnel_result.get("verified_sources"):
                    top_verified = funnel_result["verified_sources"][0]
                    v_rec, _ = fetch_website(top_verified["url"])
                    gated = apply_website_identity_gate(profile, v_rec)

            # If still not found or not publishable, attempt Layer 2: Controlled Search Discovery
            if not (gated.get("assessment") or {}).get("publishable"):
                queries = build_flexible_company_search_queries(profile)
                for q_str in queries[:2]:
                    try:
                        q_url = f"http://localhost:8080/search?{urllib.parse.urlencode({'q': q_str, 'format': 'json'})}"
                        req = urllib.request.Request(q_url, headers={"User-Agent": "signalpost-batch/0.1"})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            s_data = json.loads(resp.read().decode("utf-8"))
                            s_results = [{
                                "rank": idx,
                                "url": r.get("url"),
                                "title": r.get("title") or "",
                                "snippet": r.get("content") or ""
                            } for idx, r in enumerate(s_data.get("results", []), start=1)]
                            
                            decision = choose_search_candidate(profile, s_results)
                            sel = decision.get("selected")
                            if sel:
                                s_rec, s_met = fetch_website(sel["url"])
                                website_metrics["requests"] += s_met.get("requests", 0)
                                website_metrics["bytes"] += s_met.get("bytes", 0)
                                website_metrics["latencies_ms"].extend(s_met.get("latencies_ms", []))
                                s_gated = apply_website_identity_gate(profile, s_rec)
                                if s_rec.get("status") == "available" and (s_gated["assessment"] or {}).get("publishable"):
                                    gated = s_gated
                                    break
                                elif s_rec.get("status") == "blocked":
                                    gated = s_gated
                                    break
                    except Exception:
                        pass

            profile["evidence"]["website"] = gated["website"]

        metric = {
            "requests": len(metrics) + website_metrics["requests"],
            "bytes": sum(item.bytes_received for item in metrics) + website_metrics["bytes"],
            "latencies_ms": [item.elapsed_ms for item in metrics] + website_metrics["latencies_ms"],
        }
        profile["run_metrics"] = metric
        return profile, metric

    state: dict[str, dict] = {}
    resumed_profiles = 0
    profiles_output = Path(args.profiles_output)
    if args.resume and profiles_output.exists():
        prior = [json.loads(line) for line in profiles_output.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not set(item["organisation_number"] for item in prior).issubset(set(orgs)):
            raise SystemExit("Resume profile membership is not a subset of this batch")
        state = {
            item["organisation_number"]: item
            for item in prior
            if profile_complete_for_modules(item, requested_modules)
        }
        resumed_profiles = len(state)
    pending_profiles = [profile for profile in profiles if profile["organisation_number"] not in state]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(enrich, profile): profile["organisation_number"] for profile in pending_profiles}
        for index, future in enumerate(as_completed(futures), 1):
            profile, metric = future.result()
            state[profile["organisation_number"]] = profile
            operations["requests"] += metric["requests"]
            operations["bytes"] += metric["bytes"]
            operations["latencies_ms"].extend(metric["latencies_ms"])
            if index % args.checkpoint_every == 0 or index == len(pending_profiles):
                checkpoint = [state[org] for org in orgs if org in state]
                write_jsonl(profiles_output, checkpoint)

    completed_at = utc_now()
    ordered_profiles = [state[org] for org in orgs]
    envelopes = [
        terminal_envelope(profile, run_id=args.run_id, modules=requested_modules, started_at=started_at, completed_at=completed_at)
        for profile in ordered_profiles
    ]
    validation = validate_envelopes(envelopes, args.expected_count)
    write_jsonl(profiles_output, ordered_profiles)
    write_jsonl(Path(args.output), envelopes)
    latencies = sorted(operations.pop("latencies_ms"))
    operations["p50_ms"] = latencies[len(latencies) // 2] if latencies else None
    operations["p95_ms"] = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None
    # Aggregate discovery funnel statistics across profiles
    agg_funnel = {
        "generated": 0,
        "fetched": 0,
        "plausible": 0,
        "verified": 0,
        "rejected": 0,
        "rejection_reasons": {},
        "requests": 0,
        "bytes": 0,
    }
    for p in ordered_profiles:
        df = p.get("discovery_funnel")
        if df:
            agg_funnel["generated"] += df.get("generated", 0)
            agg_funnel["fetched"] += df.get("fetched", 0)
            agg_funnel["plausible"] += df.get("plausible", 0)
            agg_funnel["verified"] += df.get("verified", 0)
            agg_funnel["rejected"] += df.get("rejected", 0)
            agg_funnel["requests"] += df.get("requests", 0)
            agg_funnel["bytes"] += df.get("bytes", 0)
            for reason, count in (df.get("rejection_reasons") or {}).items():
                agg_funnel["rejection_reasons"][reason] = agg_funnel["rejection_reasons"].get(reason, 0) + count

    verified_yield = round(agg_funnel["verified"] / agg_funnel["fetched"], 3) if agg_funnel["fetched"] > 0 else 0.0
    candidate_efficiency = round(agg_funnel["verified"] / agg_funnel["requests"], 3) if agg_funnel["requests"] > 0 else 0.0

    report = {
        "run_id": args.run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "expected_count": args.expected_count,
        "emitted_envelopes": len(envelopes),
        "resumed_profiles": resumed_profiles,
        "profiles_fetched_this_run": len(pending_profiles),
        "modules": requested_modules,
        "registry": registry_metadata,
        "discovery_funnel": {
            **agg_funnel,
            "verified_yield": verified_yield,
            "candidate_efficiency": candidate_efficiency,
        },
        "operations": {
            **operations,
            "p50_ms": latencies[len(latencies) // 2] if latencies else 0,
            "p95_ms": latencies[int(len(latencies) * 0.95)] if latencies else 0,
        },
        "validation": validation,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if validation["passed"] else 1)


if __name__ == "__main__":
    main()
