#!/usr/bin/env python3
import json
from pathlib import Path

p_path = Path("out/v7-dry-run/profiles.jsonl")
e_path = Path("out/v7-dry-run/envelopes.jsonl")
r_path = Path("out/v7-dry-run/run-report.json")
v_path = Path("out/v7-dry-run/v7-company-viewer.html")
m_path = Path("submission/organisation-manifest.jsonl")

profiles = [json.loads(l) for l in p_path.open(encoding="utf-8") if l.strip()]
envelopes = [json.loads(l) for l in e_path.open(encoding="utf-8") if l.strip()]
manifest = [json.loads(l) for l in m_path.open(encoding="utf-8") if l.strip()]
report = json.loads(r_path.read_text(encoding="utf-8"))

print("=== V7 DRY-RUN STRUCTURAL INSPECTION ===")
print(f"Profiles count:           {len(profiles)} (expected: 1100)")
print(f"Envelopes count:          {len(envelopes)} (expected: 1100)")
print(f"Manifest count:           {len(manifest)} (expected: 1100)")

all_complete = all(e.get("state") == "complete" for e in envelopes)
print(f"All complete:             {all_complete}")

p_orgs = [p["organisation_number"] for p in profiles]
e_orgs = [e["organisation_number"] for e in envelopes]
m_orgs = [m.get("organisation_number") or m.get("org_number") for m in manifest]

print(f"Unique profile orgs:      {len(set(p_orgs))} == 1100: {len(set(p_orgs)) == 1100}")
print(f"Unique envelope orgs:     {len(set(e_orgs))} == 1100: {len(set(e_orgs)) == 1100}")
print(f"Manifest exact match:     {p_orgs == m_orgs and e_orgs == m_orgs}")

has_synth = sum(1 for e in envelopes if e.get("synthesis"))
has_act   = sum(1 for e in envelopes if e.get("activity"))
print(f"Synthesis present:        {has_synth}/1100")
print(f"Activity present:         {has_act}/1100")

has_who   = sum(1 for e in envelopes if (e.get("synthesis") or {}).get("who"))
has_what  = sum(1 for e in envelopes if (e.get("synthesis") or {}).get("what"))
has_sum   = sum(1 for e in envelopes if (e.get("synthesis") or {}).get("deterministic_summary"))
print(f"Synthesis who blocks:     {has_who}/1100")
print(f"Synthesis what blocks:    {has_what}/1100")
print(f"Deterministic summaries:  {has_sum}/1100")

has_jobs  = sum(1 for e in envelopes if (e.get("activity") or {}).get("jobs_count") is not None)
has_news  = sum(1 for e in envelopes if (e.get("activity") or {}).get("news_count") is not None)
print(f"Activity jobs_count:      {has_jobs}/1100")
print(f"Activity news_count:      {has_news}/1100")

news_nonzero = sum(1 for e in envelopes if (e.get("activity") or {}).get("news_count", 0) > 0)
jobs_nonzero = sum(1 for e in envelopes if (e.get("activity") or {}).get("jobs_count", 0) > 0)
print(f"Companies with news:      {news_nonzero}")
print(f"Companies with jobs:      {jobs_nonzero}")

has_fp = sum(1 for p in profiles if "external_footprint" in p.get("evidence", {}))
print(f"External footprint ev:    {has_fp}/1100")

print(f"Viewer file exists:       {v_path.exists()} ({v_path.stat().st_size:,} bytes)")
print(f"Run report valid:         {report.get('validation', {}).get('passed')}")
print(f"Zero silent drops:        {report.get('validation', {}).get('checks', {}).get('zero_silent_drops')}")
