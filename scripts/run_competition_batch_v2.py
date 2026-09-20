#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import (  # noqa: E402
    profile_complete_for_modules,
    profiles_from_bulk,
    read_organisation_inputs,
    terminal_envelope,
    validate_envelopes,
)
from norway_company_agent.budget import RequestBudget  # noqa: E402
from norway_company_agent.discovery import (  # noqa: E402
    assess_candidate_funnel,
    build_flexible_company_search_queries,
    calculate_discovery_opportunity,
    choose_search_candidate,
    generate_company_candidate_sources,
    generate_deterministic_domain_candidates,
    normalize_candidate_url,
)
from norway_company_agent.evidence import evidence, utc_now  # noqa: E402
from norway_company_agent.external_footprint import (  # noqa: E402
    aggregate_footprint,
    extract_profile_footprint_observations,
)
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules  # noqa: E402
from norway_company_agent.research import synthesize_company_intelligence  # noqa: E402
from norway_company_agent.website import fetch_website  # noqa: E402


def write_jsonl(path: Path, rows: list[dict]) -> None:
    import time
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    for attempt in range(5):
        try:
            temporary.replace(path)
            break
        except PermissionError:
            time.sleep(0.2 * (2**attempt))
    else:
        # Fallback if replace is held
        temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Signalpost V2 Competition Batch Pipeline with Budget & Synthesis")
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
    parser.add_argument("--budget", type=int, default=2000, help="Total outbound request budget")
    parser.add_argument("--modules", default="registry,accounting_obligation,registry_live,financials,roles,group,locations,website,external_footprint")
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
    fetch_modules = set(requested_modules) - {"registry", "accounting_obligation", "website", "external_footprint"}
    
    # Initialize central RequestBudget
    budget_mgr = RequestBudget(
        total_budget=args.budget,
        category_budgets={
            "registry": 500,
            "website": 600,
            "external_footprint": 400,
            "search": 400,
            "reserve": 100,
        },
    )

    operations = {"requests": 0, "bytes": 0, "latencies_ms": []}

    def fetch_one(profile: dict) -> tuple[dict, dict]:
        # 1. Fetch Official Registry Modules
        # Ensure budget permits registry calls
        if budget_mgr.can_request("registry", cost=len(fetch_modules)):
            records, metrics = fetch_official_modules(profile["organisation_number"], fetch_modules)
            profile["evidence"].update(records)
            budget_mgr.consume("registry", cost=len(metrics))
        else:
            metrics = []
            for mod in fetch_modules:
                if mod not in profile["evidence"]:
                    profile["evidence"][mod] = evidence(
                        mod,
                        "budget_exhausted",
                        "official_registry",
                        "https://data.brreg.no",
                        note="Request budget limit reached for batch",
                    )

        website_metrics = {"requests": 0, "bytes": 0, "latencies_ms": []}
        if "website" in requested_modules:
            website_url = profile.get("website")
            if website_url:
                if budget_mgr.can_request("website", cost=1):
                    website_record, website_metrics = fetch_website(website_url)
                    budget_mgr.consume("website", cost=website_metrics.get("requests", 1))
                else:
                    website_record = evidence("website", "not_found", "registry_linked_company_website", "https://data.brreg.no/enhetsregisteret/api/enheter", note="Request budget reached")
            else:
                website_record, website_metrics = fetch_website(None)
            gated = apply_website_identity_gate(profile, website_record)

            # Run 4: Structured Multi-Tier Candidate Discovery Funnel (Email, Subunits, Deterministic Name Permutations)
            opportunity = calculate_discovery_opportunity(profile)
            if (
                (gated["website"].get("status") not in ("available", "blocked") or not (gated.get("assessment") or {}).get("publishable"))
                and opportunity >= 0.35
            ):
                candidate_sources = generate_company_candidate_sources(profile)
                # Filter out the initial website if it was already fetched
                unfetched_cands = [c for c in candidate_sources if normalize_candidate_url(c.url) != normalize_candidate_url(website_url)]
                
                def batch_fetch(url: str) -> tuple[dict, dict]:
                    if not budget_mgr.can_request("website", cost=1):
                        return evidence("website", "not_found", "registry_linked_company_website", url, note="Budget limit reached"), {"requests": 0, "bytes": 0, "latencies_ms": []}
                    rec, met = fetch_website(url)
                    budget_mgr.consume("website", cost=met.get("requests", 1))
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
                    # Fetch / assign verified website record
                    v_rec, _ = fetch_website(top_verified["url"])
                    gated = apply_website_identity_gate(profile, v_rec)

            # Layer 2: Adaptive Controlled Search Discovery
            if not (gated.get("assessment") or {}).get("publishable") and opportunity >= 0.35 and budget_mgr.can_request("search", cost=1):
                queries = build_flexible_company_search_queries(profile)
                # Adaptive query budget: high opportunity entities get up to 3 queries; medium get 1 query
                max_queries = 3 if opportunity >= 0.70 else 2 if opportunity >= 0.50 else 1
                for q_str in queries[:max_queries]:
                    if not budget_mgr.can_request("search", cost=1):
                        break
                    try:
                        q_url = f"http://localhost:8080/search?{urllib.parse.urlencode({'q': q_str, 'format': 'json'})}"
                        req = urllib.request.Request(q_url, headers={"User-Agent": "signalpost-batch/0.1"})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            budget_mgr.consume("search", cost=1)
                            s_data = json.loads(resp.read().decode("utf-8"))
                            s_results = [{
                                "rank": idx,
                                "url": r.get("url"),
                                "title": r.get("title") or "",
                                "snippet": r.get("content") or ""
                            } for idx, r in enumerate(s_data.get("results", []), start=1)]
                            
                            decision = choose_search_candidate(profile, s_results)
                            sel = decision.get("selected")
                            if sel and budget_mgr.can_request("website", cost=1):
                                s_rec, s_met = fetch_website(sel["url"])
                                budget_mgr.consume("website", cost=s_met.get("requests", 1))
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

        # Workstream A: External Footprint Extraction
        if "external_footprint" in requested_modules:
            observations = extract_profile_footprint_observations(profile)
            footprint_summary = aggregate_footprint(observations)
            footprint_summary["observations"] = observations
            profile["evidence"]["external_footprint"] = evidence(
                "external_footprint",
                "available" if observations else "not_found",
                "external_footprint_aggregator",
                profile.get("evidence", {}).get("registry", {}).get("source_url") or "https://data.brreg.no",
                value=footprint_summary,
                retrieved_at=utc_now(),
                content_sha256=profile.get("evidence", {}).get("registry", {}).get("content_sha256"),
            )

        # Workstream C: Synthesis Snapshot
        profile["synthesis"] = synthesize_company_intelligence(profile)

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
            raise SystemExit("Prior profiles output does not match requested organisation set")
        resumed = [item for item in prior if profile_complete_for_modules(item, requested_modules)]
        for item in resumed:
            state[item["organisation_number"]] = item
        resumed_profiles = len(state)

    to_fetch = [item for item in profiles if item["organisation_number"] not in state]

    def checkpoint() -> None:
        ordered = [state[org] for org in orgs if org in state]
        write_jsonl(profiles_output, ordered)

    if to_fetch:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_map = {executor.submit(fetch_one, profile): profile["organisation_number"] for profile in to_fetch}
            completed_count = 0
            for future in as_completed(future_map):
                org = future_map[future]
                profile, metric = future.result()
                state[org] = profile
                operations["requests"] += metric["requests"]
                operations["bytes"] += metric["bytes"]
                operations["latencies_ms"].extend(metric["latencies_ms"])
                completed_count += 1
                if completed_count % args.checkpoint_every == 0 or completed_count == len(to_fetch):
                    checkpoint()
    else:
        checkpoint()

    completed_profiles = [state[org] for org in orgs]
    completed_at = utc_now()
    envelopes = [
        terminal_envelope(
            profile,
            run_id=args.run_id,
            modules=requested_modules,
            started_at=started_at,
            completed_at=completed_at,
        )
        for profile in completed_profiles
    ]
    write_jsonl(Path(args.output), envelopes)

    validation = validate_envelopes(envelopes, args.expected_count)
    if not validation["passed"]:
        raise SystemExit(f"Envelope validation failed: {validation['invalid_states'][:5]}")

    latencies = sorted(operations["latencies_ms"])
    n_lat = len(latencies)
    p50 = latencies[n_lat // 2] if n_lat else 0
    p95 = latencies[int(n_lat * 0.95)] if n_lat else 0

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
    for p in completed_profiles:
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
        "profiles_fetched_this_run": len(to_fetch),
        "modules": requested_modules,
        "registry": registry_metadata,
        "discovery_funnel": {
            **agg_funnel,
            "verified_yield": verified_yield,
            "candidate_efficiency": candidate_efficiency,
        },
        "operations": {
            "outbound_requests": operations["requests"],
            "requests": operations["requests"],
            "bytes": operations["bytes"],
            "p50_ms": p50,
            "p95_ms": p95,
        },
        "budget": {
            "total_budget": budget_mgr.total_budget,
            "budget_reservations": budget_mgr.consumed,
            "budget_remaining": budget_mgr.remaining,
            "cache_hits": budget_mgr.cache_hits,
            "category_consumed": dict(budget_mgr.category_consumed),
            "category_budgets": dict(budget_mgr.category_budgets),
            "accounting_note": "outbound_requests represents actual physical HTTP requests sent to external servers; budget_reservations tracks units allocated against the 2,000 ceiling across modules and searches."
        },
        "validation": validation,
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
