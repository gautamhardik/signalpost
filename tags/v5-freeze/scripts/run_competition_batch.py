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
from norway_company_agent.discovery import choose_search_candidate, build_flexible_company_search_queries  # noqa: E402
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
    parser.add_argument("--bulk", required=True, help="Frozen Brreg entity snapshot")
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
            
            # If no website or not publishable/available, attempt Layer 1: Deterministic Email Domain
            if gated["website"].get("status") not in ("available", "blocked") or not (gated["assessment"] or {}).get("publishable"):
                reg_val = profile.get("evidence", {}).get("registry", {}).get("value") or {}
                raw_email = str(reg_val.get("epostadresse") or reg_val.get("epost") or "").strip().casefold()
                if raw_email and "@" in raw_email:
                    email_domain = raw_email.rsplit("@", 1)[-1].removeprefix("www.")
                    generic = {"gmail.com", "googlemail.com", "hotmail.com", "hotmail.no", "outlook.com", "live.com", "live.no", "yahoo.com", "yahoo.no", "icloud.com", "online.no", "telenor.no"}
                    if email_domain not in generic and "." in email_domain and len(email_domain) >= 4:
                        for cand_url in [f"https://{email_domain}/", f"https://www.{email_domain}/"]:
                            c_rec, c_met = fetch_website(cand_url)
                            website_metrics["requests"] += c_met.get("requests", 0)
                            website_metrics["bytes"] += c_met.get("bytes", 0)
                            website_metrics["latencies_ms"].extend(c_met.get("latencies_ms", []))
                            c_gated = apply_website_identity_gate(profile, c_rec)
                            if c_rec.get("status") == "available" and (c_gated["assessment"] or {}).get("publishable"):
                                gated = c_gated
                                break
                            elif c_rec.get("status") in ("blocked_robots", "blocked_policy") and "disallow" in str(c_rec.get("note") or "").lower():
                                gated = c_gated
                                break

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
        "operations": operations,
        "validation": validation,
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if validation["passed"] else 1)


if __name__ == "__main__":
    main()
