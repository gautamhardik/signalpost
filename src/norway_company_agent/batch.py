from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .evidence import evidence, utc_now
from .official import accounting_obligation_assessment
from .sampling import iter_bulk


TERMINAL_STATES = {
    "complete",
    "not_applicable",
    "not_found",
    "blocked_policy",
    "blocked_robots",
    "source_error",
    "budget_exhausted",
    "submission_error",
}


def read_organisation_inputs(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    values: list[Any]
    if source.suffix == ".json":
        body = json.loads(text)
        values = body if isinstance(body, list) else body.get("organisation_numbers", [])
    elif source.suffix == ".jsonl":
        values = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        values = [line.strip() for line in text.splitlines() if line.strip()]
    records = []
    for value in values:
        org = value.get("organisation_number") if isinstance(value, dict) else value
        org = "".join(character for character in str(org or "") if character.isdigit())
        if len(org) != 9:
            raise ValueError(f"Invalid Norwegian organisation number: {value!r}")
        record = {"organisation_number": org}
        if isinstance(value, dict):
            for key in ("evaluation_split", "sample_slice"):
                if value.get(key) is not None:
                    record[key] = value[key]
        records.append(record)
    orgs = [record["organisation_number"] for record in records]
    if len(orgs) != len(set(orgs)):
        raise ValueError("Organisation-number input contains duplicates")
    return records


def read_organisation_numbers(path: str | Path) -> list[str]:
    return [record["organisation_number"] for record in read_organisation_inputs(path)]


def profiles_from_bulk(path: str | Path, organisation_numbers: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requested = list(organisation_numbers)
    p = Path(path)
    
    # If path is explicitly an SQLite DB or if default SQLite exists when path is provided
    from .identity_store import SQLiteIdentityStore, BulkFileIdentityStore, HybridIdentityStore, get_default_identity_store
    
    try:
        if p.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
            store = SQLiteIdentityStore(p)
            return store.get_batch(requested)
        elif p.exists():
            # Check if default sqlite cache is present to provide hybrid speedup
            from .identity_store import DEFAULT_SQLITE_PATH
            if DEFAULT_SQLITE_PATH.exists():
                primary = SQLiteIdentityStore(DEFAULT_SQLITE_PATH)
                fallback = BulkFileIdentityStore(p)
                hybrid = HybridIdentityStore(primary=primary, fallback=fallback)
                return hybrid.get_batch(requested)
            else:
                store = BulkFileIdentityStore(p)
                return store.get_batch(requested)
        else:
            store = get_default_identity_store()
            return store.get_batch(requested)
    except Exception:
        # Fallback to direct legacy streaming scan to guarantee 100% clean-room compatibility
        wanted = set(requested)
        snapshot_sha256 = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""
        retrieved_at = utc_now()
        found: dict[str, dict[str, Any]] = {}
        scanned = 0
        for profile in iter_bulk(path):
            scanned += 1
            org = profile["organisation_number"]
            if org not in wanted:
                continue
            raw = profile.pop("raw", {})
            profile["evidence"] = {
                "registry": evidence(
                    "registry",
                    "available",
                    "official_registry_bulk",
                    "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
                    value=raw,
                    retrieved_at=retrieved_at,
                    content_sha256=snapshot_sha256,
                    source_row_key=org,
                ),
                "accounting_obligation": accounting_obligation_assessment(profile),
            }
            found[org] = profile
            if len(found) == len(wanted):
                break
        missing = [org for org in requested if org not in found]
        if missing:
            raise ValueError(f"Organisation numbers absent from registry snapshot: {missing[:10]}")
        return [found[org] for org in requested], {
            "registry_snapshot_sha256": snapshot_sha256,
            "registry_rows_scanned": scanned,
            "requested": len(requested),
            "selected": len(found),
        }


def evidence_terminal_state(record: dict[str, Any] | None) -> str:
    if not record:
        return "submission_error"
    status = record.get("status")
    if status == "available":
        # Hard Gate: If an identity assessment exists and is not publishable, website is not available
        val = record.get("value")
        if isinstance(val, dict) and "identity_assessment" in val:
            if not val["identity_assessment"].get("publishable"):
                return "not_found"
        return "complete"
    if status == "not_applicable":
        return "not_applicable"
    if status == "not_found":
        return "not_found"
    if status == "blocked":
        note = str(record.get("note") or "").casefold()
        return "blocked_robots" if "robot" in note else "blocked_policy"
    if status == "source_error":
        return "source_error"
    if status == "budget_exhausted":
        return "budget_exhausted"
    return "submission_error"



def terminal_envelope(
    profile: dict[str, Any],
    *,
    run_id: str,
    modules: Iterable[str],
    started_at: str,
    completed_at: str,
) -> dict[str, Any]:
    module_states = {}
    for module in modules:
        record = profile.get("evidence", {}).get(module)
        module_states[module] = {
            "state": evidence_terminal_state(record),
            "retry_count": int((record or {}).get("retry_count") or 0),
            "final_timestamp": (record or {}).get("retrieved_at") or completed_at,
        }
    entity_state = "submission_error" if any(item["state"] == "submission_error" for item in module_states.values()) else "complete"

    # Compile V7 Decision-Useful Intelligence Summary & Sources
    from .research import synthesize_company_intelligence
    try:
        synthesis = synthesize_company_intelligence(profile)
    except Exception:
        synthesis = {}

    fp_obs = (profile.get("evidence", {}).get("external_footprint", {}).get("value") or {}).get("observations", [])
    verified_jobs = [o for o in fp_obs if o.get("signal_type") == "job_posting"]
    verified_news = [o for o in fp_obs if o.get("platform") == "news"]

    return {
        "run_id": run_id,
        "organisation_number": profile["organisation_number"],
        "state": entity_state,
        "started_at": started_at,
        "completed_at": completed_at,
        "modules": module_states,
        "synthesis": synthesis,
        "activity": {
            "jobs_count": len(verified_jobs),
            "news_count": len(verified_news),
            "latest_jobs": verified_jobs[:5],
            "latest_news": verified_news[:5],
        },
        "profile": profile,
    }


def validate_envelopes(envelopes: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    orgs = [item.get("organisation_number") for item in envelopes]
    invalid_states = [
        {"organisation_number": item.get("organisation_number"), "state": state.get("state")}
        for item in envelopes
        for state in item.get("modules", {}).values()
        if state.get("state") not in TERMINAL_STATES
    ]
    checks = {
        "exact_expected_count": len(envelopes) == expected_count,
        "unique_organisation_numbers": len(orgs) == len(set(orgs)),
        "all_entity_states_terminal": all(item.get("state") in TERMINAL_STATES for item in envelopes),
        "all_module_states_terminal": not invalid_states,
        "zero_silent_drops": len(envelopes) == expected_count and len(orgs) == len(set(orgs)),
    }
    return {"passed": all(checks.values()), "checks": checks, "invalid_states": invalid_states}


def profile_complete_for_modules(profile: dict[str, Any], modules: Iterable[str]) -> bool:
    records = profile.get("evidence", {})
    return all(module in records and records[module].get("status") != "not_fetched" for module in modules)
