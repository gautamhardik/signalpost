#!/usr/bin/env python3
"""Signalpost batch runner: one result per supplied organisation number.

    uv run python scripts/run_competition_batch.py --organisations <file> --output-dir out/run

Reads the company list Builderr supplies at run time (JSON, JSONL or one number per line),
researches each company and writes, under --output-dir:

    profiles.jsonl     one evidence-backed profile per company, in input order
    envelopes.jsonl    one result envelope per company (contract states only)
    run-report.json    counts, request usage and validation checks
    sources/           the exact source bytes behind every published fact (content-addressed)
    viewer/index.html  a self-contained viewer over this run's profiles
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import traceback
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.batch import load_profiles, profile_complete_for_modules, read_organisation_inputs, terminal_envelope, validate_envelopes  # noqa: E402
from norway_company_agent.discovery import (  # noqa: E402
    assess_candidate_funnel,
    build_flexible_company_search_queries,
    calculate_discovery_opportunity,
    choose_search_candidate,
    generate_company_candidate_sources,
    normalize_candidate_url,
)
from norway_company_agent.evidence import evidence, normalize_evidence_states, utc_now  # noqa: E402
from norway_company_agent.evidence_store import EvidenceStore, attach_observation_snapshots, snapshot_website_pages, strip_transient_bytes  # noqa: E402
from norway_company_agent.external_footprint import aggregate_footprint, extract_profile_footprint_observations  # noqa: E402
from norway_company_agent.http import fetch_json  # noqa: E402
from norway_company_agent.identity import apply_website_identity_gate  # noqa: E402
from norway_company_agent.official import fetch_official_modules, merge_live_registry  # noqa: E402
from norway_company_agent.refresh import diff_profile  # noqa: E402
from norway_company_agent.research import synthesize_company_intelligence  # noqa: E402
from norway_company_agent.viewer import build_viewer  # noqa: E402
from norway_company_agent.website import fetch_website, normalize_homepage, normalize_social_url  # noqa: E402

DEFAULT_MODULES = "registry,accounting_obligation,registry_live,financials,roles,group,locations,website,external_footprint"
NO_REQUESTS = {"requests": 0, "bytes": 0, "latencies_ms": []}


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class WebAllowance:
    """Per-company cap on website and search requests, plus an optional run-wide ceiling.

    Official registry calls are not counted: they are free public APIs and every company
    needs them. A per-company cap stops early companies from starving later ones.
    """

    def __init__(self, per_company: int, global_limit: int | None) -> None:
        self.per_company = per_company
        self.global_limit = global_limit
        self.global_used = 0
        self._lock = threading.Lock()

    def for_company(self) -> "CompanyAllowance":
        return CompanyAllowance(self)

    def take(self, cost: int) -> bool:
        with self._lock:
            if self.global_limit is not None and self.global_used + cost > self.global_limit:
                return False
            self.global_used += cost
            return True


class CompanyAllowance:
    def __init__(self, parent: WebAllowance) -> None:
        self.parent = parent
        self.used = 0

    def can(self, cost: int = 1) -> bool:
        return self.used + cost <= self.parent.per_company

    def charge(self, cost: int) -> None:
        self.used += cost
        self.parent.take(cost)

    def reserve(self, cost: int = 1) -> bool:
        return self.can(cost) and (self.parent.global_limit is None or self.parent.global_used + cost <= self.parent.global_limit)


def demote_unverified_website(record: dict) -> dict:
    """A site that failed the identity gate is never published as the company's website."""
    value = record.get("value") or {}
    assessment = value.get("identity_assessment") or {}
    if record.get("status") != "available" or assessment.get("publishable"):
        return record
    strip_transient_bytes(record)
    score = float(assessment.get("score") or 0)
    return evidence(
        "website",
        "ambiguous" if score >= 0.6 else "not_available",
        record.get("source_type") or "registry_linked_company_website",
        record.get("source_url") or "",
        value={"candidate_url": value.get("final_url") or record.get("source_url"), "identity_assessment": assessment},
        retrieved_at=record.get("retrieved_at"),
        note="Candidate site could not be tied to this exact company; not published." if score >= 0.6 else "Candidate site did not match this company; not published.",
    )


SHAREABLE_SIGNALS = {"job_posting", "public_post", "profile_handle"}


def _canonical_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url or "")
    return f"{(parsed.hostname or '').casefold().removeprefix('www.')}{(parsed.path or '').rstrip('/').casefold()}"


def withhold_shared_observations(profiles: list[dict]) -> dict:
    """A job, article or social profile can belong to only one company. If the same item was
    attributed to two companies in this batch (e.g. branches sharing a national site), it is
    withheld from both rather than published under a company it may not belong to."""
    owners: dict[str, set[str]] = {}
    for profile in profiles:
        for obs in ((profile["evidence"].get("external_footprint") or {}).get("value") or {}).get("observations") or []:
            if obs.get("signal_type") in SHAREABLE_SIGNALS:
                owners.setdefault(_canonical_url(obs.get("source_url")), set()).add(profile["organisation_number"])
    shared = {url for url, orgs in owners.items() if len(orgs) > 1}
    affected = 0
    for profile in profiles:
        record = profile["evidence"].get("external_footprint") or {}
        value = record.get("value") or {}
        observations = value.get("observations") or []
        kept = [obs for obs in observations if not (obs.get("signal_type") in SHAREABLE_SIGNALS and _canonical_url(obs.get("source_url")) in shared)]
        if len(kept) == len(observations):
            continue
        affected += 1
        summary = aggregate_footprint(kept)
        summary["observations"] = kept
        summary["withheld_shared"] = [
            {"source_url": obs.get("source_url"), "signal_type": obs.get("signal_type"), "reason": "Also attributed to another company in this batch; ownership is ambiguous"}
            for obs in observations if obs not in kept
        ]
        record["value"] = summary
        record["status"] = "available" if kept else "not_available"
        profile["synthesis"] = synthesize_company_intelligence(profile)
    return {"shared_items": len(shared), "companies_affected": affected}


def open_viewer(viewer_path: Path) -> bool:
    """Open the run's viewer in the default browser; never fails the run if that is not possible."""
    import webbrowser

    try:
        return bool(webbrowser.open(viewer_path.resolve().as_uri()))
    except Exception:
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Signalpost: one evidence-backed result per Norwegian organisation number")
    parser.add_argument("--organisations", required=True, help="JSON, JSONL, or text file of organisation numbers supplied at run time")
    parser.add_argument("--output-dir", default="out/run", help="Directory for profiles, envelopes, report, sources and viewer")
    parser.add_argument("--output", help="Envelope JSONL path (default: <output-dir>/envelopes.jsonl)")
    parser.add_argument("--profiles-output", help="Profile JSONL path (default: <output-dir>/profiles.jsonl)")
    parser.add_argument("--report", help="Run report path (default: <output-dir>/run-report.json)")
    parser.add_argument("--run-id", default=None, help="Run identifier (default: UTC timestamp)")
    parser.add_argument("--bulk", default=None, help="Optional local Brreg snapshot (SQLite, CSV or JSONL.GZ); the live registry API is used for anything missing")
    parser.add_argument("--expected-count", type=int, default=None, help="Fail fast if the input does not contain exactly this many companies")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--checkpoint-every", type=int, default=25)
    parser.add_argument("--resume", action="store_true", help="Reuse complete profiles from an interrupted run in the same output directory")
    parser.add_argument("--previous", help="Profiles JSONL from an earlier run; enables change detection and carries forward evidence a source no longer returns")
    parser.add_argument("--web-requests-per-company", type=int, default=30, help="Website and search request cap per company (registry calls are not counted)")
    parser.add_argument("--budget", type=int, default=None, help="Optional run-wide ceiling on website and search requests")
    parser.add_argument("--search-endpoint", default=None, help="Optional SearXNG-compatible JSON search endpoint for website discovery")
    parser.add_argument("--modules", default=DEFAULT_MODULES)
    parser.add_argument("--no-viewer", action="store_true", help="Skip building the HTML viewer")
    parser.add_argument("--open", action="store_true", help="Open the viewer in the default browser when the run finishes")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    envelopes_path = Path(args.output) if args.output else output_dir / "envelopes.jsonl"
    profiles_path = Path(args.profiles_output) if args.profiles_output else output_dir / "profiles.jsonl"
    report_path = Path(args.report) if args.report else output_dir / "run-report.json"
    run_id = args.run_id or "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    store = EvidenceStore(output_dir / "sources", link_base=output_dir)

    started_at = utc_now()
    organisation_inputs = read_organisation_inputs(args.organisations)
    orgs = [item["organisation_number"] for item in organisation_inputs]
    if args.expected_count is not None and len(orgs) != args.expected_count:
        raise SystemExit(f"Expected {args.expected_count} organisations, received {len(orgs)}")

    profiles, registry_metadata = load_profiles(args.bulk, orgs)
    annotations = {item["organisation_number"]: item for item in organisation_inputs}
    for profile in profiles:
        for key in ("evaluation_split", "sample_slice"):
            if key in annotations[profile["organisation_number"]]:
                profile[key] = annotations[profile["organisation_number"]][key]

    requested_modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    fetch_modules = set(requested_modules) - {"registry", "accounting_obligation", "website", "external_footprint"}
    allowance = WebAllowance(args.web_requests_per_company, args.budget)
    previous = {row["organisation_number"]: row for row in read_jsonl(Path(args.previous))} if args.previous else {}

    def snapshotting_fetcher(url: str):
        result = fetch_json(url)
        if result.raw:
            snapshotting_fetcher.refs[url] = store.put(result.raw, kind="json")
            result.raw = None
        return result

    snapshotting_fetcher.refs = {}

    def research_website(profile: dict, budget: CompanyAllowance, metrics: dict) -> None:
        cache: dict[str, tuple[dict, dict]] = {}

        def fetch(url: str | None, timeout: float = 15.0) -> tuple[dict, dict]:
            key = normalize_candidate_url(url) if url else ""
            if key and key in cache:
                return cache[key]
            if url and not budget.reserve(1):
                return evidence("website", "failed", "company_website_candidate", url, note="Per-company website request cap reached"), dict(NO_REQUESTS)
            record, met = fetch_website(url, timeout=timeout)
            budget.charge(met.get("requests", 0))
            metrics["requests"] += met.get("requests", 0)
            metrics["bytes"] += met.get("bytes", 0)
            metrics["latencies_ms"].extend(met.get("latencies_ms", []))
            if key:
                cache[key] = (record, met)
            return record, met

        website_url = profile.get("website")
        if website_url and normalize_social_url(normalize_homepage(website_url) or ""):
            # The registered web address is a social profile: publish it as such (see
            # RegistrySocialAdapter) and look for an actual website among the candidates.
            profile["registry_social"] = normalize_homepage(website_url)
            website_url = None
        website_record, _ = fetch(website_url or None)
        if website_url and website_record.get("status") == "source_error" and "timed out" in str(website_record.get("note") or "").casefold():
            # One retry for the registry-listed site, so a single slow response does not lose it.
            cache.pop(normalize_candidate_url(website_url), None)
            website_record, _ = fetch(website_url, timeout=25.0)
        gated = apply_website_identity_gate(profile, website_record)
        opportunity = calculate_discovery_opportunity(profile)

        if gated["website"].get("status") not in ("available", "blocked") or not (gated.get("assessment") or {}).get("publishable"):
            candidates = [
                candidate for candidate in generate_company_candidate_sources(profile)
                if normalize_candidate_url(candidate.url) != normalize_candidate_url(website_url)
            ]
            # Guessed domains get a short timeout: a real company site answers quickly.
            funnel = assess_candidate_funnel(profile, candidates, fetch_fn=lambda url: fetch(url, timeout=8.0), identity_gate_fn=apply_website_identity_gate, max_fetches=5)
            profile["discovery_funnel"] = funnel.get("funnel_metrics")
            if funnel.get("verified_sources"):
                verified_record, _ = fetch(funnel["verified_sources"][0]["url"])
                gated = apply_website_identity_gate(profile, verified_record)

        if args.search_endpoint and not (gated.get("assessment") or {}).get("publishable"):
            max_queries = 3 if opportunity >= 0.70 else 2 if opportunity >= 0.50 else 1
            for query in build_flexible_company_search_queries(profile)[:max_queries]:
                if not budget.reserve(1):
                    break
                try:
                    request = urllib.request.Request(
                        f"{args.search_endpoint}?{urllib.parse.urlencode({'q': query, 'format': 'json'})}",
                        headers={"User-Agent": "signalpost-batch/0.2"},
                    )
                    with urllib.request.urlopen(request, timeout=8) as response:
                        budget.charge(1)
                        body = json.loads(response.read().decode("utf-8"))
                    results = [
                        {"rank": rank, "url": item.get("url"), "title": item.get("title") or "", "snippet": item.get("content") or ""}
                        for rank, item in enumerate(body.get("results", []), start=1)
                    ]
                    selected = choose_search_candidate(profile, results).get("selected")
                    if selected:
                        search_record, _ = fetch(selected["url"])
                        search_gated = apply_website_identity_gate(profile, search_record)
                        if search_record.get("status") == "available" and (search_gated.get("assessment") or {}).get("publishable"):
                            gated = search_gated
                            break
                except Exception:
                    continue

        for cached_record, _ in cache.values():
            if cached_record is not gated["website"]:
                strip_transient_bytes(cached_record)
        landed = (gated["website"].get("value") or {}).get("final_url") or ""
        if gated["website"].get("status") == "available" and normalize_social_url(landed):
            # The company's address redirects to a social profile: that profile is not a website.
            strip_transient_bytes(gated["website"])
            if (gated.get("assessment") or {}).get("publishable"):
                profile["registry_social"] = landed
            profile["evidence"]["website"] = evidence(
                "website", "not_available", "registry_linked_company_website", gated["website"].get("source_url") or landed,
                value={"redirects_to_social_profile": landed}, retrieved_at=gated["website"].get("retrieved_at"),
                note="The company's web address redirects to a social profile, published as such",
            )
            return
        profile["evidence"]["website"] = demote_unverified_website(gated["website"])

    def carry_forward(profile: dict) -> None:
        """Refresh: keep earlier evidence a source failed to return, and record what changed."""
        prior = previous.get(profile["organisation_number"])
        if not prior:
            return
        for module, record in profile["evidence"].items():
            old = (prior.get("evidence") or {}).get(module) or {}
            if record.get("status") == "failed" and old.get("status") == "available":
                profile["evidence"][module] = {
                    **old,
                    "note": f"Carried forward from previous run (retrieved {old.get('retrieved_at')}); refresh attempt failed: {record.get('note')}",
                    "carried_forward": True,
                }
        try:
            profile["changes_since_previous_run"] = diff_profile(prior, profile)
        except ValueError:
            profile["changes_since_previous_run"] = []
        profile["previous_run"] = {
            "run_id": prior.get("run_id"),
            "registry_retrieved_at": ((prior.get("evidence") or {}).get("registry") or {}).get("retrieved_at"),
        }

    def enrich(profile: dict) -> tuple[dict, dict]:
        metrics = {"requests": 0, "bytes": 0, "latencies_ms": [], "registry_requests": 0}
        profile.setdefault("evidence", {})
        try:
            registry_status = (profile["evidence"].get("registry") or {}).get("status")
            if registry_status != "available":
                # Unknown or unreachable organisation number: report it, do not invent a profile.
                state = "not_applicable" if registry_status == "not_available" else "failed"
                for module in requested_modules:
                    profile["evidence"].setdefault(module, evidence(module, state, "official_registry", "https://data.brreg.no/enhetsregisteret/api/enheter/" + profile["organisation_number"], note="No registry entity to research"))
            else:
                records, results = fetch_official_modules(profile["organisation_number"], fetch_modules, fetcher=snapshotting_fetcher)
                for record in records.values():
                    ref = snapshotting_fetcher.refs.pop(record.get("source_url"), None)
                    if ref:
                        record.update(ref)
                profile["evidence"].update(records)
                metrics["registry_requests"] = len(results)
                metrics["bytes"] += sum(item.bytes_received for item in results)
                metrics["latencies_ms"].extend(item.elapsed_ms for item in results)
                merge_live_registry(profile)

                if "website" in requested_modules:
                    research_website(profile, allowance.for_company(), metrics)

                if "external_footprint" in requested_modules:
                    observations = extract_profile_footprint_observations(profile)
                    website_record = profile["evidence"].get("website") or {}
                    page_refs = snapshot_website_pages(store, website_record)
                    attach_observation_snapshots(observations, page_refs, (website_record.get("value") or {}).get("final_url"))
                    summary = aggregate_footprint(observations)
                    summary["observations"] = observations
                    profile["evidence"]["external_footprint"] = evidence(
                        "external_footprint",
                        "available" if observations else "not_available",
                        "external_footprint_aggregator",
                        (website_record.get("value") or {}).get("final_url") or (profile["evidence"].get("registry") or {}).get("source_url") or "https://data.brreg.no",
                        value=summary,
                        retrieved_at=utc_now(),
                    )
                strip_transient_bytes(profile["evidence"].get("website") or {})
        except Exception as exc:  # one broken company must never drop the batch
            profile["run_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            profile["run_error_trace"] = traceback.format_exc(limit=4)[-1500:]
            strip_transient_bytes(profile["evidence"].get("website") or {})

        for module in requested_modules:
            if module not in profile["evidence"]:
                profile["evidence"][module] = evidence(module, "failed", "signalpost_runner", "", note=profile.get("run_error") or "Module produced no result")
        normalize_evidence_states(profile["evidence"])
        carry_forward(profile)
        profile["run_id"] = run_id
        try:
            profile["synthesis"] = synthesize_company_intelligence(profile)
        except Exception as exc:
            profile["synthesis"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        profile["run_metrics"] = metrics
        return profile, metrics

    state: dict[str, dict] = {}
    resumed_profiles = 0
    if args.resume and profiles_path.exists():
        prior_rows = read_jsonl(profiles_path)
        state = {row["organisation_number"]: row for row in prior_rows if row["organisation_number"] in set(orgs) and profile_complete_for_modules(row, requested_modules) and not row.get("run_error")}
        resumed_profiles = len(state)

    totals = {"web_requests": 0, "registry_requests": 0, "bytes": 0, "latencies_ms": []}
    pending = [profile for profile in profiles if profile["organisation_number"] not in state]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(enrich, profile): profile for profile in pending}
        for index, future in enumerate(as_completed(futures), 1):
            try:
                profile, metric = future.result()
            except Exception as exc:  # defensive: enrich already guards, but never lose a row
                profile = futures[future]
                profile["run_error"] = f"{type(exc).__name__}: {exc}"
                normalize_evidence_states(profile.setdefault("evidence", {}))
                metric = {"requests": 0, "registry_requests": 0, "bytes": 0, "latencies_ms": []}
            state[profile["organisation_number"]] = profile
            totals["web_requests"] += metric["requests"]
            totals["registry_requests"] += metric.get("registry_requests", 0)
            totals["bytes"] += metric["bytes"]
            totals["latencies_ms"].extend(metric["latencies_ms"])
            if index % args.checkpoint_every == 0 or index == len(pending):
                write_jsonl(profiles_path, [state[org] for org in orgs if org in state])
                print(f"[{index}/{len(pending)}] profiles checkpointed", file=sys.stderr)

    completed_at = utc_now()
    ordered = [state[org] for org in orgs]
    shared_report = withhold_shared_observations(ordered)
    envelopes = [terminal_envelope(profile, run_id=run_id, modules=requested_modules, started_at=started_at, completed_at=completed_at) for profile in ordered]
    validation = validate_envelopes(envelopes, len(orgs))
    write_jsonl(profiles_path, ordered)
    write_jsonl(envelopes_path, envelopes)

    module_states = {module: dict(Counter(env["modules"][module]["state"] for env in envelopes)) for module in requested_modules}
    observations = [obs for profile in ordered for obs in ((profile["evidence"].get("external_footprint") or {}).get("value") or {}).get("observations", [])]
    companies_with = lambda predicate: len({obs["organisation_number"] for obs in observations if predicate(obs)})  # noqa: E731
    latencies = sorted(totals.pop("latencies_ms"))
    report = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "input_count": len(orgs),
        "emitted_envelopes": len(envelopes),
        "resumed_profiles": resumed_profiles,
        "failed_companies": sum(1 for env in envelopes if env["state"] == "failed"),
        "modules": requested_modules,
        "registry": registry_metadata,
        "module_states": module_states,
        "coverage": {
            "verified_websites": module_states.get("website", {}).get("available", 0),
            "companies_with_social_profiles": companies_with(lambda o: o.get("signal_type") == "profile_handle"),
            "companies_with_job_postings": companies_with(lambda o: o.get("signal_type") == "job_posting"),
            "job_postings": sum(1 for o in observations if o.get("signal_type") == "job_posting"),
            "companies_with_dated_news": companies_with(lambda o: o.get("platform") == "news"),
            "dated_news_items": sum(1 for o in observations if o.get("platform") == "news"),
            "observations_with_source_snapshot": sum(1 for o in observations if o.get("snapshot_sha256")),
            "observations_total": len(observations),
        },
        "operations": {
            **totals,
            "web_requests_per_company_cap": args.web_requests_per_company,
            "web_request_ceiling": args.budget,
            "p50_ms": latencies[len(latencies) // 2] if latencies else 0,
            "p95_ms": latencies[int(len(latencies) * 0.95)] if latencies else 0,
        },
        "withheld_shared_items": shared_report,
        "evidence_store": store.summary(),
        "validation": validation,
    }
    if not args.no_viewer:
        report["viewer"] = build_viewer(ordered, output_dir / "viewer", run_id=run_id).as_posix()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("run_id", "input_count", "emitted_envelopes", "failed_companies", "coverage", "validation")}, ensure_ascii=False, indent=2))
    if args.open and report.get("viewer"):
        viewer = Path(report["viewer"])
        print(f"Opening viewer: {viewer.resolve()}" if open_viewer(viewer) else f"Could not open a browser; open {viewer.resolve()} manually.", file=sys.stderr)
    raise SystemExit(0 if validation["passed"] else 1)


if __name__ == "__main__":
    main()
