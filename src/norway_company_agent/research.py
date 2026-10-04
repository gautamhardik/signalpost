from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def _claim(label: str, value: Any, record: dict[str, Any], classification: str) -> dict[str, Any]:
    return {
        "claim": label,
        "value": value,
        "classification": classification,
        "source_url": record.get("source_url"),
        "retrieved_at": record.get("retrieved_at"),
        "source_class": record.get("source_class") or record.get("source_type"),
        "content_sha256": record.get("content_sha256"),
    }


def answer_profile(row: dict[str, Any], question: str) -> dict[str, Any]:
    """Deterministic retrieval/answer layer; it never invents a missing field."""
    q = question.casefold()
    financial_terms = ("financial", "finance", "account", "revenue", "income", "profit", "result", "debt", "asset", "regnskap")
    all_topics = not any(term in q for term in (*financial_terms, "lead", "role", "location", "where", "social", "sentiment", "employee"))
    evidence = row.get("evidence", {})
    facts: list[dict[str, Any]] = []
    unsupported: list[str] = []

    registry = evidence.get("registry", {})
    if all_topics or "employee" in q or "industry" in q or "activity" in q:
        for label, value in (
            ("Registered name", row.get("name")),
            ("Organisation number", row.get("organisation_number")),
            ("Legal form", row.get("legal_form")),
            ("Municipality", row.get("municipality")),
            ("Registry employee count", row.get("employees")),
            ("Industry code", row.get("industry_code")),
            ("Industry label", row.get("industry_label")),
            ("Latest submitted accounts year", row.get("latest_submitted_accounts")),
            ("Bankruptcy status", "In bankruptcy" if row.get("bankrupt") else "Not bankrupt"),
            ("Liquidation status", "In liquidation" if row.get("liquidating") else "Not liquidating"),
        ):
            if value not in (None, ""):
                facts.append(_claim(label, value, registry, "official_registry_fact"))

    accounting_obligation = evidence.get("accounting_obligation", {})
    if all_topics or any(term in q for term in ("account", "obligation", "audit", "regnskap")):
        acc_val = accounting_obligation.get("value") or {}
        if acc_val.get("classification"):
            facts.append(_claim("Accounting obligation classification", acc_val["classification"], accounting_obligation, "official_rule_interpretation"))
        if acc_val.get("reason"):
            facts.append(_claim("Accounting obligation statutory basis", acc_val["reason"], accounting_obligation, "official_rule_interpretation"))

    financial = evidence.get("financials", {})
    if all_topics or any(term in q for term in financial_terms):
        records = (financial.get("value") or {}).get("records") or []
        if records:
            latest = records[0]
            for label, key in (
                ("Reporting period", "period"),
                ("Revenue", "revenue"),
                ("Operating result", "operating_result"),
                ("Annual result", "annual_result"),
                ("Assets", "assets"),
                ("Debt", "debt"),
            ):
                if latest.get(key) is not None:
                    facts.append(_claim(label, latest[key], financial, "official_annual_account"))
        else:
            unsupported.append("No normalized annual-account record was returned; missing values are not interpreted as zero.")

    roles = evidence.get("roles", {})
    if all_topics or any(term in q for term in ("lead", "role")):
        people = [item for item in (roles.get("value") or {}).get("roles", []) if not item.get("inactive")]
        for person in people[:12]:
            facts.append(_claim(person.get("role") or person.get("group") or "Registered role", person.get("name") or person.get("organisation_number"), roles, "official_role_record"))
        if not people:
            unsupported.append("No active public role holder was returned.")

    locations = evidence.get("locations", {})
    if all_topics or any(term in q for term in ("location", "where")):
        items = (locations.get("value") or {}).get("locations", [])
        for item in items[:12]:
            facts.append(_claim("Registered subunit", {"name": item.get("name"), "address": item.get("address")}, locations, "official_subunit_record"))
        if not items:
            unsupported.append("No registered subunit was returned; this does not prove the company has no physical presence.")

    website = evidence.get("website", {})
    if all_topics or "social" in q or "website" in q:
        value = website.get("value") or {}
        website_publishable = (value.get("identity_assessment") or {}).get("publishable", True)
        if website.get("status") == "available" and website_publishable:
            if value.get("final_url") or website.get("source_url"):
                facts.append(_claim("Official company website", value.get("final_url") or website.get("source_url"), website, "company_verified_homepage"))
            if value.get("title"):
                facts.append(_claim("Website title", value["title"], website, "company_reported_claim"))
            if value.get("description"):
                facts.append(_claim("Website description", value["description"], website, "company_reported_claim"))
            for item in (value.get("social_links") or []):
                facts.append(_claim(f"Declared {item['platform']} profile", item["url"], website, "company_linked_social_profile"))
        elif website.get("status") == "available" and not website_publishable:
            unsupported.append("A registry-linked website was fetched, but exact legal-entity identity was not established; its claims and social links are quarantined.")
        elif website.get("status") != "available":
            unsupported.append("The registry-linked company website was not available to this run.")

    footprint = evidence.get("external_footprint", {})
    if all_topics or "social" in q or "footprint" in q:
        fp_val = footprint.get("value") or {}
        if footprint.get("status") == "available":
            for obs in fp_val.get("observations") or []:
                if obs.get("exact_entity"):
                    plat = obs.get("platform")
                    is_official = plat == "brreg" or obs.get("source_class") == "official_registry"
                    classification = f"official_registry_{obs.get('signal_type')}" if is_official else f"external_{plat}_observation"
                    facts.append({
                        "claim": f"Verified {plat} presence" if not is_official else f"Verified {plat} {obs.get('signal_type')}",
                        "value": obs.get("source_url"),
                        "classification": classification,
                        "source_url": obs.get("source_url"),
                        "retrieved_at": obs.get("retrieved_at"),
                        "source_class": obs.get("source_class") or plat,
                        "content_sha256": obs.get("content_sha256"),
                    })

    if "sentiment" in q:
        unsupported.append("Sentiment is not scored: no labelled Norwegian news/social evaluation corpus has been run, and company-owned pages are structurally promotional.")

    return {
        "organisation_number": row.get("organisation_number"),
        "company_name": row.get("name"),
        "question": question,
        "facts": facts,
        "unsupported_or_uncertain": unsupported,
        "answer_policy": "Retrieval and deterministic filtering precede prose; only source-linked facts are returned.",
    }


UNSUPPORTED_SCREEN_TERMS = {
    "sentiment": "sentiment is not qualified",
    "glassdoor": "Glassdoor data is not available through a permitted connector",
    "linkedin": "LinkedIn-derived employee data is not available through a permitted connector",
    "traffic": "website traffic is not available through a qualified provider",
    "reviews": "review data is not available through a qualified provider",
    "buzz": "social buzz is not available through a qualified provider",
    "without a website": "missing or unverified website evidence does not prove that a company has no website",
}


def _latest_financial(row: dict[str, Any]) -> dict[str, Any]:
    records = ((row.get("evidence", {}).get("financials", {}).get("value") or {}).get("records") or [])
    return records[0] if records else {}


def _numeric_operator(phrase: str) -> str:
    return {
        "more than": ">", "over": ">", "above": ">", "at least": ">=",
        "fewer than": "<", "less than": "<", "under": "<", "at most": "<=",
    }.get(phrase.casefold(), phrase)


def parse_screen_query(query: str) -> dict[str, Any]:
    """Parse a deliberately closed company-screen grammar into an inspectable plan."""
    text = " ".join(query.strip().split())
    lower = text.casefold()
    filters: list[dict[str, Any]] = []
    unsupported = [message for term, message in UNSUPPORTED_SCREEN_TERMS.items() if term in lower]

    municipality = re.search(r"\b(?:in|municipality(?:\s+is|\s*=)?)\s+([a-zæøåéü .'-]+?)(?=\s+(?:with|and|having|that|where)\b|$)", lower)
    if municipality:
        filters.append({"field": "municipality", "operator": "eq", "value": municipality.group(1).strip().upper(), "evidence_module": "registry"})

    legal_form = re.search(r"\b(?:legal\s+form|organisation\s+form)\s*(?:is|=)?\s*(asa|as|enk|nuf|ans|da|sa|sti|brl)\b", lower)
    if legal_form:
        filters.append({"field": "legal_form", "operator": "eq", "value": legal_form.group(1).upper(), "evidence_module": "registry"})

    employees = re.search(r"\b(more than|over|above|at least|fewer than|less than|under|at most)\s+(\d+)\s+(?:registered\s+)?employees?\b", lower)
    if not employees:
        employees = re.search(r"\bemployees?\s*(>=|<=|>|<|=)\s*(\d+)\b", lower)
    if employees:
        filters.append({"field": "employees", "operator": _numeric_operator(employees.group(1)), "value": int(employees.group(2)), "evidence_module": "registry"})

    revenue = re.search(r"\brevenue\s*(>=|<=|>|<|=|more than|over|above|at least|fewer than|less than|under|at most)\s*(?:nok\s*)?([\d.,]+)\s*(billion|million|bn|m)?\b", lower)
    if not revenue:
        revenue = re.search(r"\b(more than|over|above|at least|fewer than|less than|under|at most)\s*(?:nok\s*)?([\d.,]+)\s*(billion|million|bn|m)?\s+revenue\b", lower)
    if revenue:
        amount = float(revenue.group(2).replace(",", "."))
        unit = revenue.group(3)
        amount *= 1_000_000_000 if unit in {"billion", "bn"} else 1_000_000 if unit in {"million", "m"} else 1
        filters.append({"field": "revenue", "operator": _numeric_operator(revenue.group(1)), "value": amount, "evidence_module": "financials"})

    if re.search(r"\bunprofitable|loss[- ]making|negative annual result\b", lower):
        filters.append({"field": "annual_result", "operator": "<", "value": 0, "evidence_module": "financials"})
    elif re.search(r"\bprofitable|positive annual result\b", lower):
        filters.append({"field": "annual_result", "operator": ">", "value": 0, "evidence_module": "financials"})

    if re.search(r"\b(?:with|has|have)\s+(?:an?\s+)?(?:official\s+)?website\b", lower):
        filters.append({"field": "website", "operator": "present", "value": True, "evidence_module": "website"})
    if re.search(r"\b(?:with|has|have)\s+(?:annual\s+)?accounts\b", lower):
        filters.append({"field": "financials", "operator": "available", "value": True, "evidence_module": "financials"})

    industry = re.search(r"\bindustry(?:\s+contains|\s+is|\s*=)?\s+[\"']([^\"']+)[\"']", text, flags=re.IGNORECASE)
    if industry:
        filters.append({"field": "industry", "operator": "contains", "value": industry.group(1).casefold(), "evidence_module": "registry"})

    sort = None
    top = re.search(r"\btop\s+(\d+)\s+by\s+(revenue|employees)\b", lower)
    if top:
        sort = {"field": top.group(2), "direction": "desc", "limit": min(int(top.group(1)), 100)}
    return {
        "version": "closed_company_screen_v1",
        "query": text,
        "filters": filters,
        "sort": sort,
        "unsupported": unsupported,
        "executable": bool(filters or sort) and not unsupported,
    }


def _compare(actual: Any, operator: str, expected: Any) -> bool:
    if operator == "eq":
        return str(actual or "").casefold() == str(expected or "").casefold()
    if operator == "present":
        return bool(actual) is bool(expected)
    if operator == "available":
        return bool(actual) is bool(expected)
    if operator == "contains":
        return str(expected).casefold() in str(actual or "").casefold()
    if actual is None:
        return False
    return {">": actual > expected, ">=": actual >= expected, "<": actual < expected, "<=": actual <= expected, "=": actual == expected}[operator]


def _screen_value(row: dict[str, Any], field: str) -> Any:
    if field in {"municipality", "legal_form", "employees"}:
        return row.get(field)
    if field in {"revenue", "annual_result"}:
        return _latest_financial(row).get(field)
    if field == "website":
        record = row.get("evidence", {}).get("website", {})
        return record.get("status") == "available" and bool((record.get("value") or {}).get("identity_assessment", {}).get("publishable", True))
    if field == "financials":
        return row.get("evidence", {}).get("financials", {}).get("status") == "available"
    if field == "industry":
        return " ".join(filter(None, [str(row.get("industry_code") or ""), str(row.get("industry_label") or "")]))
    return None


def screen_profiles(rows: list[dict[str, Any]], query: str) -> dict[str, Any]:
    plan = parse_screen_query(query)
    if not plan["executable"]:
        return {"query": query, "plan": plan, "results": [], "result_count": 0, "abstained": True, "reason": "; ".join(plan["unsupported"]) or "No supported criterion was recognized."}
    results = []
    for row in rows:
        if not all(_compare(_screen_value(row, item["field"]), item["operator"], item["value"]) for item in plan["filters"]):
            continue
        citations = []
        evidence_modules = {item["evidence_module"] for item in plan["filters"]}
        if plan.get("sort"):
            evidence_modules.add("financials" if plan["sort"]["field"] == "revenue" else "registry")
        for module in sorted(evidence_modules):
            record = row.get("evidence", {}).get(module, {})
            citations.append({
                "module": module,
                "source_url": record.get("source_url"),
                "retrieved_at": record.get("retrieved_at"),
                "content_sha256": record.get("content_sha256"),
            })
        results.append({
            "organisation_number": row.get("organisation_number"),
            "name": row.get("name"),
            "municipality": row.get("municipality"),
            "employees": row.get("employees"),
            "revenue": _latest_financial(row).get("revenue"),
            "annual_result": _latest_financial(row).get("annual_result"),
            "citations": citations,
        })
    sort = plan.get("sort")
    if sort:
        results.sort(key=lambda item: (item.get(sort["field"]) is None, -(item.get(sort["field"]) or 0), item.get("organisation_number") or ""))
        results = results[: sort["limit"]]
    else:
        results.sort(key=lambda item: item.get("organisation_number") or "")
    return {"query": query, "plan": plan, "results": results, "result_count": len(results), "abstained": False}


LEGAL_FORM_LABELS = {
    "AS": "private limited company (AS)",
    "ASA": "public limited company (ASA)",
    "ENK": "sole proprietorship (ENK)",
    "ANS": "general partnership (ANS)",
    "DA": "partnership with shared liability (DA)",
    "SA": "cooperative (SA)",
    "STI": "foundation (STI)",
    "NUF": "Norwegian branch of a foreign company (NUF)",
    "BRL": "housing cooperative (BRL)",
    "ESEK": "condominium (ESEK)",
    "FLI": "association (FLI)",
    "IKS": "inter-municipal company (IKS)",
    "HF": "health trust (HF)",
    "KF": "municipal enterprise (KF)",
    "SF": "state enterprise (SF)",
}

MODULE_LABELS = {
    "registry_live": "live registry entry",
    "financials": "annual accounts",
    "roles": "registered roles (CEO, board)",
    "group": "group structure",
    "locations": "registered locations (sub-units)",
    "website": "official website",
}


def _source(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_url": record.get("source_url"),
        "retrieved_at": record.get("retrieved_at"),
        "content_sha256": record.get("content_sha256"),
    }


def _date_only(value: Any) -> str | None:
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return match.group(1) if match else None


def _what_changed(profile: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dated, sourced events: company news, new postings, registry updates and refresh diffs."""
    evidence = profile.get("evidence") or {}
    events: list[dict[str, Any]] = []

    for obs in observations:
        metrics = obs.get("metrics") or {}
        if obs.get("platform") == "news" and metrics.get("activity_date"):
            events.append({
                "date": metrics["activity_date"],
                "type": "news." + str(metrics.get("activity_type") or "update"),
                "description": metrics.get("title") or "Company announcement",
                "source_url": obs.get("source_url"),
                "retrieved_at": obs.get("retrieved_at"),
                "snapshot_sha256": obs.get("snapshot_sha256"),
            })
        elif obs.get("signal_type") == "job_posting" and metrics.get("published_at"):
            events.append({
                "date": metrics["published_at"],
                "type": "hiring.posting",
                "description": "Job posted: " + str(metrics.get("job_title")),
                "source_url": obs.get("source_url"),
                "retrieved_at": obs.get("retrieved_at"),
                "snapshot_sha256": obs.get("snapshot_sha256"),
            })

    roles_rec = evidence.get("roles") or {}
    if roles_rec.get("status") == "available":
        seen_groups: set[tuple[str, str]] = set()
        for role in (roles_rec.get("value") or {}).get("roles") or []:
            changed = _date_only(role.get("last_changed"))
            group = role.get("group") or role.get("group_code") or "Roles"
            if changed and (group, changed) not in seen_groups:
                seen_groups.add((group, changed))
                events.append({"date": changed, "type": "registry.roles", "description": f"{group} last updated in the register", **_source(roles_rec)})

    live_rec = evidence.get("registry_live") or {}
    live = (live_rec.get("value") or {}) if live_rec.get("status") == "available" else {}
    for item in live.get("historical_names") or []:
        changed = _date_only(item.get("tilDato"))
        if changed and item.get("navn"):
            events.append({"date": changed, "type": "registry.name", "description": f"Name changed from {item['navn']} to {profile.get('name')}", **_source(live_rec)})
    if _date_only(live.get("employees_registered_at")) and live.get("employees") is not None:
        events.append({"date": _date_only(live["employees_registered_at"]), "type": "registry.employees", "description": f"Employee count registered as {live['employees']}", **_source(live_rec)})

    fin_rec = evidence.get("financials") or {}
    fin_records = ((fin_rec.get("value") or {}).get("records") or []) if fin_rec.get("status") == "available" else []
    for record in fin_records[:1]:
        period_end = _date_only((record.get("period") or {}).get("tilDato"))
        if period_end:
            revenue = record.get("revenue")
            currency = record.get("currency") or "NOK"
            suffix = f": revenue {currency} {revenue:,.0f}" if isinstance(revenue, (int, float)) else ""
            events.append({"date": period_end, "type": "financials.period", "description": f"Annual accounts for period ending {period_end}{suffix}", **_source(fin_rec)})

    for change in profile.get("changes_since_previous_run") or []:
        events.append({
            "date": _date_only(change.get("retrieved_at")),
            "type": "refresh." + str(change.get("field")),
            "description": f"{change.get('field')} changed since the previous run",
            "previous_value": change.get("old_value"),
            "current_value": change.get("new_value"),
            "source_url": change.get("source_url"),
            "retrieved_at": change.get("retrieved_at"),
            "previous_content_sha256": change.get("old_content_sha256"),
            "content_sha256": change.get("new_content_sha256"),
        })

    today = datetime.now(timezone.utc).date().isoformat()
    # Upcoming events are not changes; keep only things that have already happened.
    events = [event for event in events if event.get("date") and event["date"] <= today]
    events.sort(key=lambda event: event["date"], reverse=True)
    return events[:20]


def _what_is_unknown(profile: dict[str, Any], website_ok: bool, ceo: Any, chair: Any, fin_record: dict[str, Any], observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """State plainly what could not be established, with the result state that explains why."""
    evidence = profile.get("evidence") or {}
    unknown: list[dict[str, Any]] = []
    for module, label in MODULE_LABELS.items():
        record = evidence.get(module)
        if not record:
            continue
        status = record.get("status")
        if module == "website":
            if website_ok:
                continue
            reason = {
                "ambiguous": "A candidate site was found but could not be tied to this exact company.",
                "blocked": "The site refused automated access.",
                "failed": "The site could not be fetched.",
            }.get(status, "No website is registered and none could be verified.")
            unknown.append({"topic": label, "state": status, "reason": reason, "source_url": record.get("source_url")})
        elif status != "available":
            unknown.append({"topic": label, "state": status, "reason": record.get("note") or f"{label} not available", "source_url": record.get("source_url")})
    roles_rec = evidence.get("roles") or {}
    if roles_rec.get("status") == "available":
        if not ceo:
            unknown.append({"topic": "CEO", "state": "not_available", "reason": "No daily manager (DAGL) is registered.", "source_url": roles_rec.get("source_url")})
        if not chair:
            unknown.append({"topic": "board chair", "state": "not_available", "reason": "No board chair (LEDE) is registered.", "source_url": roles_rec.get("source_url")})
    fin_rec = evidence.get("financials") or {}
    if fin_rec.get("status") == "available" and fin_record.get("revenue") is None:
        unknown.append({"topic": "revenue", "state": "not_available", "reason": "The filed accounts do not report revenue.", "source_url": fin_rec.get("source_url")})
    platforms = {obs.get("platform") for obs in observations}
    checked = "verified company sources" if website_ok else "any verified company source (no verified website)"
    if not any(obs.get("signal_type") == "job_posting" for obs in observations):
        unknown.append({"topic": "hiring", "state": "not_available", "reason": f"No individual job posting found on {checked}."})
    if "news" not in platforms:
        unknown.append({"topic": "news", "state": "not_available", "reason": f"No dated company article found on {checked}."})
    if not platforms & {"linkedin", "facebook", "instagram", "x", "youtube", "tiktok"}:
        unknown.append({"topic": "social profiles", "state": "not_available", "reason": f"No social profile linked from {checked}."})
    return unknown


def synthesize_company_intelligence(profile: dict[str, Any]) -> dict[str, Any]:
    """Synthesize a structured, decision-useful intelligence snapshot derived strictly from evidence."""
    evidence = profile.get("evidence") or {}
    live_rec = evidence.get("registry_live") or {}
    live = (live_rec.get("value") or {}) if live_rec.get("status") == "available" else {}
    registry_rec = evidence.get("registry") or {}
    reg = registry_rec.get("value") or {}
    fin_record = _latest_financial(profile)
    roles_val = (evidence.get("roles") or {}).get("value") or {}
    roles = (roles_val.get("roles") if isinstance(roles_val, dict) else []) or []
    website_rec = evidence.get("website") or {}
    website_val = website_rec.get("value") or {}
    website_ok = website_rec.get("status") == "available" and bool((website_val.get("identity_assessment") or {}).get("publishable"))

    ceo = next((r.get("name") for r in roles if isinstance(r, dict) and r.get("role_code") == "DAGL" and not r.get("inactive")), None)
    chair = next((r.get("name") for r in roles if isinstance(r, dict) and r.get("role_code") == "LEDE" and not r.get("inactive")), None)

    social_links = (website_val.get("social_links") or []) if website_ok else []
    observations = ((evidence.get("external_footprint") or {}).get("value") or {}).get("observations") or []

    activity_text = live.get("activity_description") or reg.get("aktivitet")
    what_does_it_do_source = live_rec if live.get("activity_description") else registry_rec

    evidence_list = []
    if website_ok:
        evidence_list.append({
            "claim": "Official website verified",
            "value": website_val.get("final_url"),
            "source_url": website_val.get("final_url"),
            "publication_date": None,
            "retrieval_date": website_rec.get("retrieved_at"),
            "snapshot_sha256": website_val.get("snapshot_sha256"),
        })
    for obs in observations:
        metrics = obs.get("metrics") or {}
        evidence_list.append({
            "claim": obs.get("evidence_span") or obs.get("signal_type"),
            "value": metrics.get("title") or metrics.get("job_title") or metrics.get("url"),
            "source_url": obs.get("source_url"),
            "publication_date": metrics.get("activity_date") or metrics.get("published_at"),
            "retrieval_date": obs.get("retrieved_at"),
            "snapshot_sha256": obs.get("snapshot_sha256"),
        })

    return {
        "what_is_this_company": f"{profile.get('name')} (Org.nr {profile.get('organisation_number')}) is a Norwegian {LEGAL_FORM_LABELS.get(str(profile.get('legal_form') or ''), (str(profile.get('legal_form')) + ' entity') if profile.get('legal_form') else 'entity')} registered in {profile.get('municipality') or 'Norway'}.",
        "what_does_it_do": activity_text or profile.get("industry_label") or "No activity description is registered.",
        "what_does_it_do_source": _source(what_does_it_do_source),
        "how_big_is_it": {
            "employees": live.get("employees") if live.get("employees") is not None else profile.get("employees"),
            "currency": fin_record.get("currency") or ("NOK" if fin_record else None),
            "revenue": fin_record.get("revenue"),
            "operating_result": fin_record.get("operating_result"),
            "reporting_period": fin_record.get("period"),
            "source": _source(evidence.get("financials") or {}),
        },
        "who_runs_it": {
            "ceo": ceo or "Not registered",
            "board_chair": chair or "Not registered",
            "source": _source(evidence.get("roles") or {}),
        },
        "what_changed": _what_changed(profile, observations),
        "digital_footprint": {
            "website": website_val.get("final_url") if website_ok else None,
            "website_state": "available" if website_ok else (website_rec.get("status") or "not_available"),
            "social_platforms": [item.get("platform") for item in social_links],
            "job_postings": sum(1 for obs in observations if obs.get("signal_type") == "job_posting"),
            "dated_news": sum(1 for obs in observations if obs.get("platform") == "news"),
        },
        "what_is_unknown": _what_is_unknown(profile, website_ok, ceo, chair, fin_record, observations),
        "evidence": evidence_list,
    }


def generate_deterministic_company_summary(profile: dict[str, Any]) -> str:
    """Generate accurate, evidence-backed company intelligence summary without LLM hallucination."""
    name = profile.get("name") or "The company"
    org = profile.get("organisation_number") or ""
    ind = profile.get("industry_label") or profile.get("industry_code") or "commercial operations"
    muni = profile.get("municipality") or "Norway"
    emp = profile.get("employees")

    evidence = profile.get("evidence") or {}
    web_val = (evidence.get("website") or {}).get("value") or {}
    web_ok = (evidence.get("website") or {}).get("status") == "available" and bool((web_val.get("identity_assessment") or {}).get("publishable"))

    fp_obs = (evidence.get("external_footprint", {}).get("value") or {}).get("observations", [])
    jobs = [o for o in fp_obs if o.get("signal_type") == "job_posting"]
    news = [o for o in fp_obs if o.get("platform") == "news"]

    parts = [f"{name} (Org.nr {org}) is registered in {muni}, operating in {ind}."]
    if emp is not None and emp > 0:
        parts.append(f"It has {emp} registered employees.")
    
    if web_ok:
        parts.append("Its official website and digital footprint have been verified against Norwegian business register identity records.")
    
    if jobs:
        sample_job = jobs[0].get("metrics", {}).get("job_title") or "active recruitment"
        parts.append(f"Recent verified hiring activity includes postings for: {sample_job}.")

    if news:
        sample_news = news[0].get("metrics", {}).get("title") or "public announcements"
        parts.append(f"Latest verified company announcement: {sample_news}.")

    return " ".join(parts)

