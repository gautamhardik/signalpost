from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODULE_LABELS = {
    "registry": "Registry entry",
    "registry_live": "Live registry",
    "financials": "Annual accounts",
    "roles": "Roles",
    "group": "Group structure",
    "locations": "Locations",
    "website": "Website",
    "external_footprint": "Web footprint",
}

SOCIAL_PLATFORMS = {"linkedin", "facebook", "instagram", "x", "youtube", "tiktok"}
REGISTRY_IDENTITY = "Official Enhetsregisteret record for this organisation number"


def _ref(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_url": record.get("source_url"),
        "retrieved_at": record.get("retrieved_at"),
        "sha": record.get("snapshot_sha256") or record.get("content_sha256"),
        "snapshot": record.get("snapshot_path"),
    }


def _fact(
    kind: str,
    label: str,
    value: Any,
    record: dict[str, Any],
    *,
    date: str | None = None,
    date_label: str | None = None,
    identity: str | None = None,
    extract: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label,
        "value": value,
        "date": date,
        "date_label": date_label,
        "identity": identity,
        "extract": extract,
        **_ref(record),
    }


def _address(value: dict[str, Any]) -> str:
    street = value.get("adresse")
    street = " ".join(street) if isinstance(street, list) else street
    return ", ".join(filter(None, [street, value.get("postnummer"), value.get("poststed")]))


def _proof_reason(obs: dict[str, Any]) -> str:
    proof = (obs.get("identity_proof") or [{}])[0] or {}
    if proof.get("reason"):
        return str(proof["reason"])
    if proof.get("matched_tokens"):
        return "Linked from the verified company website; handle matches " + ", ".join(proof["matched_tokens"])
    return str(proof.get("method") or "Linked from the verified company website")


def company_view(profile: dict[str, Any]) -> dict[str, Any]:
    """Reduce a full profile to what the viewer shows: facts with sources, states, synthesis."""
    evidence = profile.get("evidence") or {}
    synthesis = profile.get("synthesis") or {}
    live_record = evidence.get("registry_live") or {}
    registry = live_record if live_record.get("status") == "available" else evidence.get("registry") or {}
    live = (live_record.get("value") or {}) if live_record.get("status") == "available" else {}
    facts: list[dict[str, Any]] = []

    if live.get("business_address"):
        facts.append(_fact("registry", "Business address", _address(live["business_address"]), registry, identity=REGISTRY_IDENTITY))
    if profile.get("industry_label"):
        facts.append(_fact("registry", "Industry", f"{profile.get('industry_code')} {profile.get('industry_label')}", registry, identity=REGISTRY_IDENTITY))
    employees = live.get("employees") if live.get("employees") is not None else profile.get("employees")
    if employees is not None:
        facts.append(_fact("registry", "Employees", employees, registry, date=live.get("employees_registered_at"), date_label="Registered", identity=REGISTRY_IDENTITY))
    if live.get("founded_at"):
        facts.append(_fact("registry", "Founded", live["founded_at"], registry, identity=REGISTRY_IDENTITY))
    if live.get("activity_description"):
        facts.append(_fact("registry", "Registered activity", live["activity_description"], registry, identity=REGISTRY_IDENTITY, extract=live["activity_description"]))

    roles = evidence.get("roles") or {}
    for role in ((roles.get("value") or {}).get("roles") or [])[:12]:
        if role.get("name") and not role.get("inactive"):
            name = role["name"] if isinstance(role["name"], str) else " ".join(map(str, role["name"]))
            facts.append(_fact("people", role.get("role") or role.get("role_code") or "Role", name, roles,
                               date=role.get("last_changed"), date_label="Last updated", identity="Registered role in Enhetsregisteret"))

    financials = evidence.get("financials") or {}
    for record in ((financials.get("value") or {}).get("records") or [])[:1]:
        period = (record.get("period") or {}).get("tilDato")
        currency = record.get("currency") or "NOK"
        for key, label in (("revenue", "Revenue"), ("operating_result", "Operating result"), ("annual_result", "Annual result"), ("equity", "Equity")):
            if record.get(key) is not None:
                facts.append(_fact("financials", f"{label} ({currency})", record[key], financials,
                                   date=period, date_label="Period ending", identity="Filed annual accounts in Regnskapsregisteret"))

    locations = evidence.get("locations") or {}
    for location in ((locations.get("value") or {}).get("locations") or [])[:10]:
        facts.append(_fact("locations", location.get("name") or "Location", _address(location.get("address") or {}), locations,
                           identity="Registered sub-unit of this organisation number"))

    website = evidence.get("website") or {}
    website_value = website.get("value") or {}
    assessment = website_value.get("identity_assessment") or {}
    if website.get("status") == "available":
        facts.append(_fact("website", "Official website", website_value.get("final_url"), website,
                           identity="; ".join(assessment.get("reasons") or []) or "Identity check passed",
                           extract=" — ".join(filter(None, [website_value.get("title"), website_value.get("description")])) or None))

    observations = ((evidence.get("external_footprint") or {}).get("value") or {}).get("observations") or []
    for obs in observations:
        metrics = obs.get("metrics") or {}
        platform = obs.get("platform")
        if platform in SOCIAL_PLATFORMS:
            facts.append(_fact("social", "X" if platform == "x" else platform.capitalize(), obs.get("source_url"), obs,
                               identity=_proof_reason(obs), extract=obs.get("evidence_span")))
        elif obs.get("signal_type") == "job_posting":
            extract = obs.get("evidence_span")
            if obs.get("posting_evidence"):
                extract = f"{extract}\nPosting evidence: {', '.join(obs['posting_evidence'])}"
            if metrics.get("deadline"):
                extract = f"{extract}\nDeadline: {metrics['deadline']}"
            facts.append(_fact("jobs", metrics.get("job_title") or "Job posting", obs.get("source_url"), obs,
                               date=metrics.get("published_at"), date_label="Posted", identity=_proof_reason(obs), extract=extract))
        elif platform == "news":
            facts.append(_fact("news", metrics.get("title") or "News", obs.get("source_url"), obs,
                               date=metrics.get("activity_date"), date_label="Published", identity=_proof_reason(obs), extract=obs.get("evidence_span")))

    modules = {}
    for module, label in MODULE_LABELS.items():
        record = evidence.get(module)
        if record:
            modules[module] = {"label": label, "state": record.get("status"), "note": record.get("note"), **_ref(record)}

    return {
        "org": profile.get("organisation_number"),
        "name": profile.get("name") or "(unregistered organisation number)",
        "form": profile.get("legal_form"),
        "municipality": profile.get("municipality"),
        "industry": profile.get("industry_label"),
        "employees": employees,
        "error": profile.get("run_error"),
        "website_state": website.get("status") or "not_available",
        "website_reason": "; ".join(assessment.get("reasons") or []),
        "candidate_url": website_value.get("candidate_url"),
        "flags": sorted({fact["kind"] for fact in facts}),
        "summary": {
            "what": synthesis.get("what_is_this_company"),
            "does": synthesis.get("what_does_it_do"),
            "size": synthesis.get("how_big_is_it"),
            "runs": synthesis.get("who_runs_it"),
        },
        "changed": synthesis.get("what_changed") or [],
        "unknown": synthesis.get("what_is_unknown") or [],
        "modules": modules,
        "facts": facts,
    }


def build_viewer(profiles: list[dict[str, Any]], out_dir: str | Path, *, run_id: str = "") -> Path:
    """Write a self-contained viewer (no build step; works offline) over this run's profiles."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    data = [company_view(profile) for profile in profiles]
    payload = json.dumps({"run_id": run_id, "companies": data}, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = TEMPLATE.replace("/*__DATA__*/null", payload)
    target = out / "index.html"
    target.write_text(html, encoding="utf-8")
    return target


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIGNALPOST — Workspace</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0a0a0a;--panel:#121212;--line:#262626;--muted:#737373;--ink:#ededed;--ink-2:#d4d4d4;--ink-3:#a3a3a3;--white:#fff;
  --brand:#b8ff5b;--brand-10:rgba(184,255,91,.1);--blue:#60a5fa;--emerald:#34d399;--amber:#fbbf24;--violet:#a78bfa;--red:#f87171;
  --sans:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Consolas,monospace;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 var(--sans);-webkit-font-smoothing:antialiased;display:flex;flex-direction:column;overflow:hidden}
a{color:var(--blue);text-decoration:none;word-break:break-all}
a:hover{text-decoration:underline}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}
:focus-visible{outline:2px solid var(--brand);outline-offset:2px}
::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#333;border-radius:10px}::-webkit-scrollbar-thumb:hover{background:#555}
.mono{font-family:var(--mono)}
.label{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}

/* nav */
nav{min-height:64px;border-bottom:1px solid var(--line);background:var(--panel);display:flex;align-items:center;gap:24px;padding:0 24px;flex-shrink:0;z-index:20}
.logo{font-weight:700;letter-spacing:.2em;display:flex;align-items:center;gap:8px;color:var(--white);white-space:nowrap}
.logo i{width:8px;height:8px;border-radius:50%;background:var(--brand);box-shadow:0 0 8px var(--brand)}
.search{position:relative;flex:1;max-width:440px}
.search svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);width:16px;height:16px;color:var(--muted)}
.search input{width:100%;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:7px 12px 7px 36px;color:var(--ink-2);font:inherit;transition:border-color .2s}
.search input:focus{outline:none;border-color:var(--brand);box-shadow:0 0 0 1px var(--brand)}
.nav-right{margin-left:auto;display:flex;align-items:center;gap:20px}
#meta{font-size:10px;letter-spacing:.08em;color:var(--muted);white-space:nowrap}
.btns{display:flex;gap:8px}
.btn{padding:6px 12px;border-radius:6px;background:var(--bg);border:1px solid var(--line);color:var(--ink-2);transition:border-color .2s,color .2s,background .2s;white-space:nowrap;min-height:34px}
.btn:hover{border-color:#6b6b6b;color:var(--white)}
.btn.on{background:var(--brand);border-color:var(--brand);color:#000}

/* workspace */
.workspace{flex:1;min-height:0;display:grid;grid-template-columns:320px minmax(0,1fr) 380px}
.explorer{background:var(--panel);border-right:1px solid var(--line);display:flex;flex-direction:column;min-height:0;min-width:0;z-index:10}
.filters{padding:16px;border-bottom:1px solid var(--line)}
.filters .label{margin-bottom:12px}
.fbtn{width:100%;display:flex;justify-content:space-between;align-items:center;padding:6px 12px;border-radius:6px;color:var(--muted);transition:background .15s}
.fbtn span:first-child{font-size:12px;font-weight:500;color:var(--ink-2);letter-spacing:.04em}
.fbtn span:last-child{font-family:var(--mono);font-size:10px}
.fbtn:hover{background:rgba(255,255,255,.05)}
.fbtn.on{background:var(--brand-10);color:var(--brand)}.fbtn.on span:first-child{color:var(--brand)}
.cmp-hint{margin-top:12px;font-size:11px;color:var(--brand);display:none}
body.compare .cmp-hint{display:block}
#cmpGo{display:none;margin-top:8px;width:100%}
#list{flex:1;overflow-y:auto}
.row{display:block;width:100%;text-align:left;padding:16px;border-bottom:1px solid var(--line);border-left:2px solid transparent;transition:background .2s,transform .3s cubic-bezier(.25,1,.5,1),box-shadow .3s}
.row:hover{background:rgba(255,255,255,.04);transform:translateX(4px);box-shadow:-2px 0 0 var(--brand)}
.row.on{background:rgba(255,255,255,.05);border-left-color:var(--brand)}
.row .n{font-weight:600;color:#f5f5f5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row .m{font-size:12px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.tags{display:flex;flex-wrap:wrap;gap:12px;font-family:var(--mono);font-size:10px;color:var(--ink-2);margin-top:12px}
.tags span{display:flex;align-items:center;gap:5px}
.dot{width:6px;height:6px;border-radius:50%;display:inline-block}
.d-web{background:var(--blue)}.d-news{background:var(--emerald)}.d-jobs{background:var(--amber)}.d-social{background:var(--violet)}.d-amb{background:var(--amber);opacity:.6}.d-fail{background:var(--red)}
.row .ev{font-size:10px;color:var(--muted);margin-top:8px}
.more{padding:16px;text-align:center}

/* intelligence */
.intel{overflow-y:auto;position:relative;background-color:var(--bg);background-size:40px 40px;background-image:linear-gradient(to right,rgba(255,255,255,.03) 1px,transparent 1px),linear-gradient(to bottom,rgba(255,255,255,.03) 1px,transparent 1px)}
.empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--muted);font-style:italic;text-align:center;padding:24px}
.empty svg{width:48px;height:48px;margin-bottom:16px}
.wrap{max-width:1040px;margin:0 auto;padding:48px 32px}
.back{display:none;margin-bottom:20px}
h1{font-size:36px;line-height:1.15;font-weight:700;letter-spacing:-.02em;color:var(--white);margin:0 0 8px}
.sub{color:var(--ink-3);margin-bottom:32px}
.alert{border:1px solid rgba(248,113,113,.4);background:rgba(248,113,113,.08);color:var(--red);border-radius:8px;padding:12px 16px;margin-bottom:24px}
.strip{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:rgba(255,255,255,.02);font-family:var(--mono);font-size:12px;margin-bottom:40px}
.strip>div{flex:1;text-align:center;padding:12px 4px;border-right:1px solid var(--line);min-width:0}
.strip>div:last-child{border-right:0}
.strip .label{margin-bottom:4px}
.strip b{font-size:14px}
.strip small{display:block;font-size:10px;color:var(--muted);margin-top:2px}
.s-available{color:var(--emerald)}.s-not_available,.s-not_applicable{color:var(--muted)}.s-ambiguous,.s-blocked{color:var(--amber)}.s-failed{color:var(--red)}
section{margin-bottom:48px}
h2{font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.12em;border-bottom:1px solid var(--line);padding-bottom:8px;margin:0 0 16px}
.summary{font-size:15px;line-height:1.7;color:#e5e5e5}
.summary p{margin:0 0 12px}
.glance{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px}
.card{padding:16px;border-radius:8px;background:rgba(255,255,255,.02);border:1px solid var(--line)}
.card .label{margin-bottom:8px}
.card .v{font-weight:500;color:#f5f5f5;overflow-wrap:anywhere}
.card .s{font-size:12px;color:var(--ink-3);margin-top:4px}
.timeline{margin-left:8px;border-left:2px solid var(--line);padding-left:24px}
.ti{position:relative;margin-bottom:28px}
.ti:last-child{margin-bottom:0}
.ti::before{content:"";position:absolute;left:-31px;top:6px;width:10px;height:10px;border-radius:50%;background:var(--bg);border:2px solid var(--brand);box-shadow:0 0 8px rgba(184,255,91,.5)}
.ti .d{font-family:var(--mono);font-size:11px;color:var(--muted);margin-bottom:4px}
.ti .t{font-weight:600;color:#f5f5f5;margin-bottom:6px;overflow-wrap:anywhere}
.link{font-size:11px;font-weight:500;color:var(--brand);transition:color .2s}
.link:hover{color:var(--white)}
.italic{color:var(--muted);font-style:italic}
.two{display:grid;grid-template-columns:1fr 1fr;gap:48px}
.ok{display:flex;align-items:flex-start;gap:8px;font-size:12px;color:var(--emerald);margin:8px 0 12px}
.ok svg,.warn svg{width:16px;height:16px;flex-shrink:0;margin-top:1px}
.warn{display:flex;align-items:flex-start;gap:8px;font-size:12px;color:var(--amber);margin:8px 0 12px}
.site{font-family:var(--mono);font-size:13px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;border:1px solid var(--line);font-size:12px;color:var(--ink-2);background:rgba(255,255,255,.02);transition:border-color .2s}
.chip:hover{border-color:var(--violet)}
.stack>*+*{margin-top:12px}
.hint{font-size:11px;color:#8a8a8a;line-height:1.6;margin-top:6px}
.table{border:1px solid var(--line);border-radius:8px;overflow:hidden;background:rgba(255,255,255,.02)}
table{width:100%;border-collapse:collapse;font-size:13px}
thead{background:rgba(0,0,0,.2)}
th{font-family:var(--mono);font-size:10px;text-transform:uppercase;color:var(--muted);font-weight:500;text-align:left;padding:12px 16px;border-bottom:1px solid var(--line)}
td{padding:12px 16px;border-bottom:1px solid var(--line);vertical-align:top;overflow-wrap:anywhere}
tbody tr:last-child td{border-bottom:0}
tr.click{cursor:pointer;transition:background .15s}
tr.click:hover{background:rgba(255,255,255,.04)}
td.dim{color:var(--ink-3);white-space:nowrap}
td.src{color:var(--muted)}
.badge{display:inline-block;padding:3px 8px;border-radius:4px;font-family:var(--mono);font-size:10px;white-space:nowrap}
.b-blue{background:rgba(96,165,250,.1);color:var(--blue)}.b-emerald{background:rgba(52,211,153,.1);color:var(--emerald)}.b-amber{background:rgba(251,191,36,.1);color:var(--amber)}
.b-violet{background:rgba(167,139,250,.1);color:var(--violet)}.b-brand{background:var(--brand-10);color:var(--brand)}.b-muted{background:rgba(255,255,255,.06);color:var(--ink-3)}
.states{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
.gap{display:flex;gap:12px;align-items:baseline;padding:10px 0;border-bottom:1px solid var(--line)}
.gap:last-child{border-bottom:0}
.gap .k{min-width:150px;color:var(--ink-2);font-weight:500}
.gap .r{color:var(--ink-3);font-size:13px}
.pill{font-family:var(--mono);font-size:10px;padding:2px 8px;border-radius:999px;border:1px solid currentColor;white-space:nowrap}
.cmpwrap{max-width:1280px;margin:0 auto;padding:48px 32px}
.cmpgrid{display:flex;gap:24px;overflow-x:auto;padding-bottom:16px}
.ccard{flex:1;min-width:260px;background:rgba(255,255,255,.02);border:1px solid var(--line);border-radius:12px;padding:24px}
.ccard .h{font-weight:700;font-size:17px;color:var(--white);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ccard .o{font-family:var(--mono);font-size:11px;color:var(--muted);border-bottom:1px solid var(--line);padding-bottom:16px;margin:4px 0 24px}
.ccard .stack>*+*{margin-top:20px}

/* inspector */
.inspector{background:var(--panel);border-left:1px solid var(--line);box-shadow:-10px 0 30px rgba(0,0,0,.5);display:flex;flex-direction:column;min-height:0;z-index:10;transition:background .3s}
.ihead{padding:16px;border-bottom:1px solid var(--line);font-family:var(--mono);font-size:11px;letter-spacing:.12em;color:var(--muted);text-transform:uppercase;display:flex;align-items:center;gap:8px}
.ihead svg{width:16px;height:16px;color:var(--brand)}
.ihead .x{margin-left:auto;display:none;font-size:18px;line-height:1;color:var(--ink-2);padding:4px 8px}
#ibody{flex:1;overflow-y:auto;padding:24px}
.iempty{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;opacity:.5;color:var(--muted)}
.iempty svg{width:48px;height:48px;margin-bottom:16px}
.ititle{padding-bottom:24px;border-bottom:1px solid var(--line);margin-bottom:24px}
.ititle .big{font-size:20px;font-weight:700;color:#f5f5f5;margin:8px 0;line-height:1.25;overflow-wrap:anywhere}
.ititle .v{color:var(--ink-2);overflow-wrap:anywhere}
.ifield{margin-bottom:22px}
.ifield .label{margin-bottom:4px}
.ifield .val{font-size:13px;color:#e5e5e5;overflow-wrap:anywhere}
.idbox{display:flex;align-items:flex-start;gap:8px;font-size:13px;padding:8px 12px;border-radius:6px;color:var(--emerald);background:rgba(52,211,153,.1)}
.idbox svg{width:16px;height:16px;flex-shrink:0;margin-top:2px}
.extract{background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:6px;padding:12px;font-size:12px;color:var(--ink-3);font-style:italic;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.6}
.open{margin-top:32px;display:flex;align-items:center;justify-content:center;gap:8px;width:100%;background:#fff;color:#000;padding:10px;border-radius:6px;font-weight:600;font-size:13px}
.open:hover{background:#e5e5e5;text-decoration:none}
.open svg{width:16px;height:16px}
.scrim{display:none}

/* motion */
@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
@keyframes slide{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:none}}
.anim>*{animation:rise .5s cubic-bezier(.2,.9,.3,1.1) both}
.anim>*:nth-child(2){animation-delay:.05s}.anim>*:nth-child(3){animation-delay:.1s}.anim>*:nth-child(4){animation-delay:.15s}.anim>*:nth-child(5){animation-delay:.2s}.anim>*:nth-child(n+6){animation-delay:.25s}
#list .row{animation:slide .3s ease-out both}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}

/* compare mode uses the full width; the inspector has nothing to show */
@media (min-width:1201px){
  body.compare .workspace{grid-template-columns:320px minmax(0,1fr)}
  body.compare .inspector{display:none}
}
.ccard{min-width:240px}

/* tablet: inspector becomes a drawer */
@media (max-width:1200px){
  .workspace{grid-template-columns:300px minmax(0,1fr)}
  .inspector{position:fixed;top:0;right:0;bottom:0;width:min(420px,100vw);transform:translateX(100%);transition:transform .3s ease;z-index:40}
  body.inspecting .inspector{transform:none}
  .ihead .x{display:block}
  .scrim{display:block;position:fixed;inset:0;background:rgba(0,0,0,.55);opacity:0;pointer-events:none;transition:opacity .3s;z-index:30}
  body.inspecting .scrim{opacity:1;pointer-events:auto}
  .glance{grid-template-columns:repeat(2,minmax(0,1fr))}
}
/* phone: one column at a time */
@media (max-width:760px){
  body{overflow:auto}
  nav{flex-wrap:wrap;gap:12px;padding:12px 16px}
  .search{order:3;flex-basis:100%;max-width:none}
  .nav-right{gap:8px}
  #meta{display:none}
  .btn{padding:6px 10px}
  .workspace{grid-template-columns:minmax(0,1fr)}
  .explorer{border-right:0}
  .intel{display:none}
  body.show-detail .explorer{display:none}
  body.show-detail .intel{display:block}
  .back{display:inline-flex}
  .wrap,.cmpwrap{padding:20px 16px 48px}
  h1{font-size:26px}
  .strip{flex-wrap:wrap}
  .strip>div{flex:1 0 33%;border-bottom:1px solid var(--line)}
  .glance,.two{grid-template-columns:1fr;gap:16px}
  .two{gap:32px}
  thead{display:none}
  table,tbody,tr,td{display:block;width:100%}
  tr{border-bottom:1px solid var(--line);padding:8px 0}
  td{border:0;padding:3px 16px}
  .gap{flex-direction:column;gap:4px}
  .gap .k{min-width:0}
  body.compare.picked #cmpGo{display:block}
}
</style>
</head>
<body>
<nav>
  <div class="logo"><i></i>SIGNALPOST</div>
  <label class="search">
    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
    <input id="q" type="search" placeholder="Search companies, organisation numbers..." aria-label="Search companies">
  </label>
  <div class="nav-right">
    <div id="meta" class="mono"></div>
    <div class="btns">
      <button class="btn" id="compare" aria-pressed="false">Compare</button>
      <button class="btn" id="csv">CSV ⬇</button>
      <button class="btn" id="json">JSON ⬇</button>
    </div>
  </div>
</nav>
<div class="workspace">
  <aside class="explorer" aria-label="Company explorer">
    <div class="filters">
      <div class="label">Filters</div>
      <div id="filters"></div>
      <div class="cmp-hint">Compare mode: pick up to 4 companies.</div>
      <button class="btn on" id="cmpGo">Show comparison</button>
    </div>
    <div id="list"></div>
  </aside>
  <main class="intel" id="intel" aria-live="polite">
    <div class="empty"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>Select a company from the explorer to view intelligence.</div>
  </main>
  <aside class="inspector" id="inspector" aria-label="Evidence inspector">
    <div class="ihead">
      <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
      Evidence Inspector
      <button class="x" id="iclose" aria-label="Close evidence inspector">✕</button>
    </div>
    <div id="ibody"></div>
  </aside>
</div>
<div class="scrim" id="scrim"></div>
<script>
const DATA = /*__DATA__*/null;
const companies = DATA.companies;
const FILTERS = [["all","All"],["website","Website"],["social","Social"],["news","News"],["jobs","Hiring"],["ambiguous","Ambiguous"],["none","Abstained"],["failed","Failed"]];
const KIND = {registry:["REGISTRY","b-blue"],people:["PEOPLE","b-violet"],financials:["FINANCIALS","b-brand"],locations:["LOCATION","b-muted"],website:["WEBSITE","b-blue"],social:["SOCIAL","b-violet"],news:["NEWS","b-emerald"],jobs:["HIRING","b-amber"],change:["CHANGE","b-brand"]};
const STATE = {available:["✓","available"],not_available:["—","not available"],not_applicable:["n/a","not applicable"],ambiguous:["?","ambiguous"],blocked:["⊘","blocked"],failed:["✕","failed"]};
const FORMS = {AS:"private limited company (AS)",ASA:"public limited company (ASA)",ENK:"sole proprietorship (ENK)",ANS:"general partnership (ANS)",DA:"partnership with shared liability (DA)",SA:"cooperative (SA)",STI:"foundation (STI)",NUF:"Norwegian branch of a foreign company (NUF)",BRL:"housing cooperative (BRL)",ESEK:"condominium (ESEK)",FLI:"association (FLI)",IKS:"inter-municipal company (IKS)",HF:"health trust (HF)",KF:"municipal enterprise (KF)",SF:"state enterprise (SF)"};
const ICON_OK = '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
const ICON_WARN = '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/></svg>';
const ICON_EXT = '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>';
const PAGE = 300;
let filter = "all", query = "", compareMode = false, picked = [], current = null, evidence = [], shown = PAGE;
const EMPTY = document.querySelector("#intel").innerHTML;
const $ = s => document.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const day = v => v ? String(v).slice(0, 10) : "";
const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return u || ""; } };
const isUrl = v => typeof v === "string" && /^https?:\/\//.test(v);
const num = v => typeof v === "number" ? v.toLocaleString("en") : v;
const money = (v, cur) => { if (v == null) return null; const a = Math.abs(v); const s = a >= 1e9 ? (v/1e9).toFixed(1)+"B" : a >= 1e6 ? (v/1e6).toFixed(1)+"M" : a >= 1e3 ? (v/1e3).toFixed(0)+"k" : String(v); return `${cur || "NOK"} ${s}`; };
const has = (c, k) => c.flags.includes(k);
const facts = (c, k) => c.facts.filter(f => f.kind === k);
const evCount = c => c.facts.length;
const CHANGE_LABELS = {"registry.employees":"Employee count","registry.roles":"Roles updated","registry.name":"Name change","financials.period":"Annual accounts","hiring.posting":"Job posted"};
const changeLabel = t => CHANGE_LABELS[t] || (String(t).startsWith("news.") ? "News · " + String(t).slice(5).replace(/_/g, " ") : String(t).startsWith("refresh.") ? "Changed since last run" : String(t || "Change"));
const pill = s => `<span class="pill s-${esc(s)}">${esc((STATE[s] || [0, s])[1])}</span>`;

function matches(c, f) {
  switch (f) {
    case "website": return c.website_state === "available";
    case "social": case "news": case "jobs": return has(c, f);
    case "ambiguous": return c.website_state === "ambiguous";
    case "none": return c.website_state !== "available" && !has(c, "news") && !has(c, "jobs") && !has(c, "social");
    case "failed": return !!c.error || Object.values(c.modules).some(m => m.state === "failed");
    default: return true;
  }
}
const searchHit = c => !query || `${c.name} ${c.org} ${c.municipality} ${c.industry}`.toLowerCase().includes(query);
const visible = () => companies.filter(c => searchHit(c) && matches(c, filter));

function renderFilters() {
  $("#filters").innerHTML = FILTERS.map(([k, l]) => `<button class="fbtn${k === filter ? " on" : ""}" data-f="${k}" aria-pressed="${k === filter}"><span>${l.toUpperCase()}</span><span>${companies.filter(c => matches(c, k)).length}</span></button>`).join("");
}

function renderList() {
  const rows = visible();
  const html = rows.slice(0, shown).map(c => {
    const on = compareMode ? picked.includes(c.org) : current === c.org;
    let tags = "";
    if (c.website_state === "available") tags += '<span><i class="dot d-web"></i>Web</span>';
    if (has(c, "news")) tags += '<span><i class="dot d-news"></i>News</span>';
    if (has(c, "jobs")) tags += '<span><i class="dot d-jobs"></i>Hiring</span>';
    if (has(c, "social")) tags += '<span><i class="dot d-social"></i>Social</span>';
    if (c.website_state === "ambiguous") tags += '<span><i class="dot d-amb"></i>Ambiguous</span>';
    if (c.error) tags += '<span><i class="dot d-fail"></i>Failed</span>';
    if (!tags) tags = '<span style="color:var(--muted)">No web footprint</span>';
    return `<button class="row${on ? " on" : ""}" data-org="${c.org}" aria-pressed="${on}">
      <div class="n">${esc(c.name)}</div>
      <div class="m">${esc(c.municipality || "Unknown")}, Norway · ${esc(c.org)}</div>
      <div class="tags">${tags}</div>
      <div class="ev">${evCount(c)} evidence</div></button>`;
  }).join("");
  $("#list").innerHTML = (html || '<div class="more italic">No companies match.</div>') +
    (rows.length > shown ? `<div class="more"><button class="btn" id="more">Show more (${rows.length - shown} left)</button></div>` : "");
  document.body.classList.toggle("picked", picked.length >= 2);
}

function summaryText(c) {
  const s = c.summary || {}, size = s.size || {}, runs = s.runs || {};
  const form = FORMS[c.form] || (c.form ? `${c.form} entity` : "entity");
  const parts = [`<p>${esc(c.name)} is a Norwegian ${esc(form)} registered in ${esc(c.municipality || "Norway")}${c.industry ? `, classified under “${esc(c.industry)}”` : ""}.</p>`];
  if (s.does && s.does !== c.industry) parts.push(`<p>Registered activity: ${esc(s.does)}</p>`);
  const scale = [];
  if (size.employees != null) scale.push(`${num(size.employees)} registered employees`);
  if (size.revenue != null) scale.push(`revenue of ${esc(money(size.revenue, size.currency))}${size.reporting_period && size.reporting_period.tilDato ? ` for the period ending ${esc(size.reporting_period.tilDato)}` : ""}`);
  parts.push(`<p>${scale.length ? `It reports ${scale.join(" and ")}.` : "Its size could not be established from filed accounts."}${runs.ceo && runs.ceo !== "Not registered" ? ` ${esc(runs.ceo)} is registered as CEO` : " No CEO is registered"}${runs.board_chair && runs.board_chair !== "Not registered" ? ` and ${esc(runs.board_chair)} as board chair.` : "."}</p>`);
  const n = facts(c, "news").length, j = facts(c, "jobs").length;
  if (c.website_state === "available" || n || j) parts.push(`<p>${c.website_state === "available" ? "Its official website is verified against the register." : ""}${n ? ` ${n} dated news item${n > 1 ? "s" : ""} found.` : ""}${j ? ` ${j} open position${j > 1 ? "s" : ""} found.` : ""}</p>`);
  return parts.join("");
}

function ev(item) { evidence.push(item); return evidence.length - 1; }

function strip(c) {
  const mod = k => (c.modules[k] || {}).state || "not_available";
  const flag = k => has(c, k) ? "available" : "not_available";
  const cells = [["Website", c.website_state], ["Registry", mod("registry")], ["Accounts", mod("financials")], ["People", mod("roles")], ["News", flag("news")], ["Hiring", flag("jobs")], ["Social", flag("social")]];
  return `<div class="strip">${cells.map(([l, s]) => `<div><div class="label">${l}</div><b class="s-${esc(s)}">${(STATE[s] || ["?"])[0]}</b><small>${esc((STATE[s] || [0, s])[1])}</small></div>`).join("")}</div>`;
}

function renderCompany(org) {
  const c = companies.find(x => x.org === org); if (!c) return;
  current = org; evidence = [];
  const s = c.summary || {}, size = s.size || {}, runs = s.runs || {};
  const web = facts(c, "website")[0], social = facts(c, "social"), jobs = facts(c, "jobs");
  const unknown = topic => (c.unknown.find(u => u.topic === topic) || {}).reason;
  const latest = c.changed[0];

  let html = `<div class="wrap anim">
    <div><button class="btn back" data-back>← All companies</button>
      <h1>${esc(c.name)}</h1>
      <div class="sub">${esc(c.municipality || "Unknown")}, Norway · Org No. ${esc(c.org)}${c.form ? ` · ${esc(c.form)}` : ""}</div>
      ${c.error ? `<div class="alert">This company failed during the run: ${esc(c.error)}</div>` : ""}
      ${strip(c)}</div>
    <section><h2>Executive Summary</h2><div class="summary">${summaryText(c)}</div></section>
    <section><h2>At a Glance</h2><div class="glance">
      <div class="card"><div class="label">Business</div><div class="v">${esc(c.industry || "Not registered")}</div></div>
      <div class="card"><div class="label">Scale</div><div class="v">${size.employees != null ? `${num(size.employees)} employees` : "Not available"}</div>${size.revenue != null ? `<div class="s">Revenue ${esc(money(size.revenue, size.currency))}</div>` : ""}</div>
      <div class="card"><div class="label">Leadership</div><div class="v">${esc(runs.ceo && runs.ceo !== "Not registered" ? runs.ceo : "No registered CEO")}</div>${runs.board_chair && runs.board_chair !== "Not registered" ? `<div class="s">Chair ${esc(runs.board_chair)}</div>` : ""}</div>
      <div class="card"><div class="label">Activity</div><div class="v">${c.changed.length} dated change${c.changed.length === 1 ? "" : "s"}</div>${latest ? `<div class="s">Latest ${esc(latest.date)}</div>` : ""}</div>
    </div></section>
    <section><h2>What Changed</h2>`;
  if (c.changed.length) {
    html += `<div class="timeline">${c.changed.map(e => {
      const i = ev({kind: "change", label: changeLabel(e.type), value: e.description, date: e.date, date_label: "Date", source_url: e.source_url, retrieved_at: e.retrieved_at, sha: e.snapshot_sha256 || e.content_sha256, identity: e.type && e.type.startsWith("registry") ? "Official register record for this organisation number" : null, extract: e.previous_value !== undefined ? `Before: ${JSON.stringify(e.previous_value)}\nAfter: ${JSON.stringify(e.current_value)}` : null});
      return `<div class="ti"><div class="d">${esc(e.date)} · ${esc(changeLabel(e.type))}</div><div class="t">${esc(e.description)}</div><button class="link" data-ev="${i}">View evidence →</button></div>`;
    }).join("")}</div>`;
  } else html += `<div class="italic">No dated changes found in the checked sources.</div>`;
  html += `</section><section class="two"><div><h2>Digital Footprint</h2>`;
  if (web) {
    const i = ev(web);
    html += `<div class="card"><div class="label">Official Website</div><div class="site">${isUrl(web.value) ? `<a href="${esc(web.value)}" target="_blank" rel="noopener noreferrer">${esc(web.value)}</a>` : esc(web.value)}</div>
      <div class="ok">${ICON_OK}<span>Company identity verified — ${esc(web.identity)}</span></div><button class="link" data-ev="${i}">Inspect evidence →</button></div>`;
  } else if (c.website_state === "ambiguous") {
    html += `<div class="card"><div class="label">Candidate website · not published</div><div class="site">${esc(c.candidate_url || "")}</div>
      <div class="warn">${ICON_WARN}<span>Could not be tied to this exact company. ${esc(c.website_reason)}</span></div></div>`;
  } else {
    html += `<div class="italic">No official website verified.</div><div class="hint">${esc(unknown("official website") || "")}</div>`;
  }
  if (social.length) html += `<div class="chips">${social.map(f => `<button class="chip" data-ev="${ev(f)}"><i class="dot d-social"></i>${esc(f.label)}</button>`).join("")}</div>`;
  else html += `<div class="hint">${esc(unknown("social profiles") || "No verified social profiles.")}</div>`;
  html += `</div><div><h2>Hiring Signals</h2>`;
  if (jobs.length) {
    html += `<div style="font-weight:700;color:#f5f5f5;margin-bottom:16px">${jobs.length} VERIFIED</div><div class="stack">${jobs.map(f => `<div class="card">
      <div class="d mono" style="font-size:10px;color:var(--muted)">${f.date ? `Posted ${esc(day(f.date))}` : "Open position"}</div>
      <div style="font-weight:600;color:#f5f5f5;margin:4px 0">${esc(f.label)}</div>
      <div class="ok" style="margin:6px 0 10px">${ICON_OK}<span>Identity verified</span></div>
      <button class="link" data-ev="${ev(f)}">Inspect →</button></div>`).join("")}</div>`;
  } else {
    html += `<div class="italic">No verified hiring signal found.</div><div class="hint">${esc(unknown("hiring") || "")}<br>Careers pages alone are not counted; only individual postings are.</div>`;
  }
  html += `</div></section>`;

  html += `<section><h2>Evidence Explorer</h2><div class="table"><table><thead><tr><th>Type</th><th>Date</th><th>Finding</th><th>Source</th></tr></thead><tbody>${c.facts.map(f => {
    const i = ev(f); const [lbl, cls] = KIND[f.kind] || [f.kind.toUpperCase(), "b-muted"];
    const value = isUrl(f.value) ? host(f.value) : num(f.value);
    return `<tr class="click" data-ev="${i}" tabindex="0"><td><span class="badge ${cls}">${lbl}</span></td><td class="dim">${esc(day(f.date)) || "—"}</td><td><span style="color:var(--ink-3)">${esc(f.label)}:</span> <span style="color:#e5e5e5">${esc(value)}</span></td><td class="src">${esc(host(f.source_url))}</td></tr>`;
  }).join("") || `<tr><td colspan="4" class="italic">No published facts.</td></tr>`}</tbody></table></div></section>`;

  html += `<section><h2>Source States</h2><div class="states">${Object.values(c.modules).map(m => `<div class="card"><div class="label">${esc(m.label)}</div>${pill(m.state)}${m.note && m.state !== "available" ? `<div class="s" style="font-size:12px;color:var(--ink-3);margin-top:8px">${esc(m.note)}</div>` : ""}</div>`).join("")}</div></section>`;

  html += `<section><h2>Evidence Gaps</h2>${c.unknown.length ? c.unknown.map(u => `<div class="gap"><div class="k">${esc(u.topic)}</div>${pill(u.state)}<div class="r">${esc(u.reason)}</div></div>`).join("") : `<div class="italic">Nothing flagged.</div>`}</section></div>`;

  $("#intel").innerHTML = html;
  $("#intel").scrollTop = 0;
  clearInspector();
  document.body.classList.add("show-detail");
  renderList();
}

function renderCompare() {
  const cs = picked.map(o => companies.find(c => c.org === o)).filter(Boolean);
  if (!cs.length) {
    $("#intel").innerHTML = `<div class="empty"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>Select companies from the explorer to compare their evidence.</div>`;
    return;
  }
  const line = (label, value, cls) => `<div><div class="label" style="margin-bottom:6px">${label}</div><div class="${cls || ""}" style="font-weight:500">${value}</div></div>`;
  $("#intel").innerHTML = `<div class="cmpwrap anim"><div><button class="btn back" data-back>← All companies</button><h1>Compare Evidence</h1><div class="sub">Side-by-side verification signals</div></div>
    <div class="cmpgrid">${cs.map(c => {
      const s = c.summary || {}, size = s.size || {}, runs = s.runs || {};
      const web = facts(c, "website")[0];
      return `<div class="ccard"><div class="h">${esc(c.name)}</div><div class="o">${esc(c.org)} · ${esc(c.industry || "Unknown")}</div><div class="stack">
        ${line("Web footprint", web ? `✓ <a href="${esc(web.value)}" target="_blank" rel="noopener noreferrer">${esc(host(web.value))}</a>` : `— ${esc((STATE[c.website_state] || [0, c.website_state])[1])}`, web ? "s-available" : "s-" + c.website_state)}
        ${line("Social", facts(c, "social").map(f => esc(f.label)).join(", ") || "— none verified", has(c, "social") ? "" : "s-not_available")}
        ${line("Hiring intent", has(c, "jobs") ? `${facts(c, "jobs").length} verified roles` : "— no postings", has(c, "jobs") ? "" : "s-not_available")}
        ${line("Recent activity", has(c, "news") ? `${facts(c, "news").length} news items` : "— no dated news", has(c, "news") ? "" : "s-not_available")}
        ${line("Reported scale", size.employees != null ? `${num(size.employees)} employees` : "N/A")}
        ${line("Revenue", size.revenue != null ? esc(money(size.revenue, size.currency)) : "N/A")}
        ${line("CEO", esc(runs.ceo || "Not registered"))}
        ${line("Latest change", c.changed[0] ? `${esc(c.changed[0].date)} · ${esc(c.changed[0].description)}` : "—")}
      </div></div>`;
    }).join("")}</div></div>`;
  document.body.classList.add("show-detail");
}

function clearInspector() {
  $("#ibody").innerHTML = `<div class="iempty"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M10 21h7a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v11m0 5l4.879-4.879m0 0a3 3 0 104.243-4.242 3 3 0 00-4.243 4.242z"/></svg><p>Select an evidence item<br>to inspect claims.</p></div>`;
  document.body.classList.remove("inspecting");
}

function inspect(i) {
  const f = evidence[i]; if (!f) return;
  const [lbl] = KIND[f.kind] || [String(f.kind).toUpperCase()];
  const field = (label, value) => value ? `<div class="ifield"><div class="label">${label}</div><div class="val">${value}</div></div>` : "";
  const valueHtml = isUrl(f.value) ? `<a href="${esc(f.value)}" target="_blank" rel="noopener noreferrer">${esc(f.value)}</a>` : esc(num(f.value));
  $("#ibody").innerHTML = `<div class="anim">
    <div class="ititle"><span class="badge b-brand">${esc(lbl)}</span><div class="big">${esc(f.label)}</div><div class="v">${valueHtml}</div></div>
    ${field("Source", f.source_url ? `<a class="mono" href="${esc(f.source_url)}" target="_blank" rel="noopener noreferrer">${esc(f.source_url)}</a>` : "")}
    ${field(esc(f.date_label || "Date"), esc(day(f.date)))}
    ${field("Retrieved", esc(f.retrieved_at ? f.retrieved_at.replace("T", " ").slice(0, 19) + " UTC" : ""))}
    ${f.identity ? `<div class="ifield"><div class="label" style="margin-bottom:8px">Identity</div><div class="idbox">${ICON_OK}<span>${esc(f.identity)}</span></div></div>` : ""}
    ${field("Saved copy", f.snapshot ? `<a href="../${esc(f.snapshot)}">${esc(f.snapshot.split("/").pop())}</a>` : "")}
    ${field("SHA-256", f.sha ? `<span class="mono" style="font-size:11px">${esc(f.sha)}</span>` : "")}
    ${f.extract ? `<div class="ifield"><div class="label">Extract</div><div class="extract">${esc(f.extract)}</div></div>` : ""}
    ${f.source_url ? `<a class="open" href="${esc(f.source_url)}" target="_blank" rel="noopener noreferrer">OPEN ORIGINAL SOURCE ${ICON_EXT}</a>` : ""}
  </div>`;
  $("#ibody").scrollTop = 0;
  document.body.classList.add("inspecting");
  const panel = $("#inspector"); panel.style.background = "#171717"; setTimeout(() => { panel.style.background = ""; }, 300);
}

function download(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type}));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
function exportCsv() {
  const out = [["organisation_number","company","kind","fact","value","date","state","source_url","retrieved_at","snapshot_sha256"]];
  for (const c of visible()) {
    for (const f of c.facts) out.push([c.org, c.name, f.kind, f.label, f.value, f.date || "", "available", f.source_url || "", f.retrieved_at || "", f.sha || ""]);
    for (const m of Object.values(c.modules)) if (m.state !== "available") out.push([c.org, c.name, "state", m.label, "", "", m.state, m.source_url || "", m.retrieved_at || "", ""]);
  }
  download("signalpost-export.csv", out.map(r => r.map(v => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\n"), "text/csv");
}

function setCompare(on) {
  compareMode = on; picked = [];
  document.body.classList.toggle("compare", on);
  $("#compare").classList.toggle("on", on);
  $("#compare").setAttribute("aria-pressed", on);
  if (on) { clearInspector(); renderCompare(); document.body.classList.remove("show-detail"); }
  else if (current) renderCompany(current);
  else { $("#intel").innerHTML = EMPTY; document.body.classList.remove("show-detail"); }
  renderList();
}

$("#meta").textContent = `${companies.length} COMPANIES · ${companies.reduce((a, c) => a + c.facts.length, 0)} EVIDENCE${DATA.run_id ? ` · RUN: ${DATA.run_id.toUpperCase()}` : ""}`;
$("#filters").addEventListener("click", e => { const b = e.target.closest("[data-f]"); if (!b) return; filter = b.dataset.f; shown = PAGE; renderFilters(); renderList(); });
$("#q").addEventListener("input", e => { query = e.target.value.trim().toLowerCase(); shown = PAGE; renderList(); });
$("#list").addEventListener("click", e => {
  if (e.target.closest("#more")) { shown += PAGE; renderList(); return; }
  const row = e.target.closest(".row"); if (!row) return;
  if (compareMode) {
    const o = row.dataset.org;
    if (picked.includes(o)) picked = picked.filter(x => x !== o);
    else if (picked.length < 4) picked.push(o);
    renderList(); if (window.innerWidth > 760) renderCompare();
  } else renderCompany(row.dataset.org);
});
document.addEventListener("click", e => {
  const t = e.target.closest("[data-ev]"); if (t) { inspect(Number(t.dataset.ev)); return; }
  if (e.target.closest("[data-back]")) { document.body.classList.remove("show-detail"); clearInspector(); }
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") clearInspector();
  if (e.key === "Enter" && e.target.matches("tr[data-ev]")) inspect(Number(e.target.dataset.ev));
});
$("#iclose").addEventListener("click", clearInspector);
$("#scrim").addEventListener("click", clearInspector);
$("#compare").addEventListener("click", () => setCompare(!compareMode));
$("#cmpGo").addEventListener("click", renderCompare);
$("#csv").addEventListener("click", exportCsv);
$("#json").addEventListener("click", () => download("signalpost-export.json", JSON.stringify(visible(), null, 2), "application/json"));
renderFilters(); renderList(); clearInspector();
</script>
</body>
</html>
"""
