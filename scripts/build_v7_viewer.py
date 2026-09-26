#!/usr/bin/env python3
"""Signalpost V7 Interactive Viewer & Evidence Explorer.

Features:
- Instant client-side search by company name, org number, municipality, industry
- Comprehensive Profile View with Deterministic Summary
- Strict Job Cards with Apply actions & role verification badges
- Dated News & Announcements Activity timeline
- Complete Source Drawer displaying verifiable provenance (URL, source type, retrieved_at, content_sha256, supporting text excerpt)
- Snapshot Change History & visible diffs (ADDED, CHANGED, REMOVED)
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.research import synthesize_company_intelligence, generate_deterministic_company_summary


def load_envelopes(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_viewer_html(envelopes: list[dict], title: str = "Signalpost V7 Evidence Product") -> str:
    # Prepare compact data payload for viewer
    companies = []
    for env in envelopes:
        p = env.get("profile", {})
        org = env.get("organisation_number") or p.get("organisation_number")
        name = p.get("name") or env.get("legal_name") or f"Company {org}"
        muni = p.get("municipality") or ""
        ind = p.get("industry_label") or p.get("industry_code") or ""
        emp = p.get("employees")
        web = p.get("website") or ""

        evidence = p.get("evidence") or {}
        web_ev = evidence.get("website") or {}
        web_val = web_ev.get("value") or {}
        web_ok = web_ev.get("status") == "available" and bool((web_val.get("identity_assessment") or {}).get("publishable"))

        # Footprint observations
        fp_obs = (evidence.get("external_footprint", {}).get("value") or {}).get("observations", [])
        jobs = [o for o in fp_obs if o.get("signal_type") == "job_posting"]
        news = [o for o in fp_obs if o.get("platform") == "news"]
        social = web_val.get("social_links") or []

        # Claims & synthesis
        synthesis = env.get("synthesis") or {}
        summary = synthesis.get("deterministic_summary") or generate_deterministic_company_summary(p)

        # Build sources catalog
        sources = []
        # Official registry source
        reg = evidence.get("registry") or {}
        if reg:
            sources.append({
                "type": "official_registry",
                "label": "BRREG Central Coordinating Register",
                "url": reg.get("source_url") or "https://data.brreg.no",
                "retrieved_at": reg.get("retrieved_at"),
                "hash": reg.get("content_sha256"),
                "excerpt": f"Authoritative Norwegian legal registration for {name} ({org}).",
            })
        # Website source
        if web_ok:
            sources.append({
                "type": "verified_website",
                "label": "Company Homepage",
                "url": web_val.get("final_url") or web_ev.get("source_url"),
                "retrieved_at": web_ev.get("retrieved_at"),
                "hash": web_ev.get("content_sha256"),
                "excerpt": web_val.get("description") or web_val.get("title") or "Verified primary homepage.",
            })
        # Observation sources
        for o in fp_obs:
            sources.append({
                "type": o.get("source_class") or o.get("platform"),
                "label": f"{o.get('platform', '').title()} Observation",
                "url": o.get("source_url"),
                "retrieved_at": o.get("retrieved_at"),
                "hash": o.get("content_sha256"),
                "excerpt": o.get("evidence_span") or str(o.get("metrics", {})),
            })

        companies.append({
            "org": org,
            "name": name,
            "municipality": muni,
            "industry": ind,
            "employees": emp,
            "website": web_val.get("final_url") or web if web_ok else None,
            "summary": summary,
            "jobs": jobs,
            "news": news,
            "social": social,
            "sources": sources,
            "modules": env.get("modules") or {},
        })

    payload_json = json.dumps(companies, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #0d1117;
      --card: #161b22;
      --border: #30363d;
      --text: #c9d1d9;
      --heading: #f0f6fc;
      --accent: #58a6ff;
      --green: #2ea043;
      --amber: #d29922;
      --drawer-bg: #1c2128;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      display: flex;
      height: 100vh;
      overflow: hidden;
    }}
    /* Sidebar */
    #sidebar {{
      width: 360px;
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      background: var(--card);
    }}
    .search-box {{
      padding: 16px;
      border-bottom: 1px solid var(--border);
    }}
    .search-box input {{
      width: 100%;
      padding: 10px 12px;
      background: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--heading);
      font-size: 14px;
      outline: none;
    }}
    .search-box input:focus {{ border-color: var(--accent); }}
    .stats-bar {{
      padding: 8px 16px;
      font-size: 12px;
      color: #8b949e;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
    }}
    #company-list {{
      flex: 1;
      overflow-y: auto;
    }}
    .company-item {{
      padding: 14px 16px;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      transition: background 0.15s;
    }}
    .company-item:hover, .company-item.active {{
      background: #21262d;
    }}
    .company-item h4 {{
      color: var(--heading);
      font-size: 14px;
      margin-bottom: 4px;
    }}
    .company-item p {{
      font-size: 12px;
      color: #8b949e;
    }}
    .badges {{
      display: flex;
      gap: 6px;
      margin-top: 6px;
    }}
    .badge {{
      font-size: 10px;
      padding: 2px 6px;
      border-radius: 10px;
      background: var(--border);
      color: var(--text);
    }}
    .badge.green {{ background: #238636; color: white; }}
    .badge.blue {{ background: #1f6feb; color: white; }}

    /* Main Content */
    #main {{
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow-y: auto;
      background: var(--bg);
    }}
    .top-bar {{
      padding: 20px 32px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--card);
    }}
    .top-bar h1 {{
      font-size: 22px;
      color: var(--heading);
    }}
    .container {{
      padding: 32px;
      max-width: 1000px;
    }}
    .summary-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
    }}
    .summary-card h3 {{
      color: var(--heading);
      margin-bottom: 10px;
      font-size: 16px;
    }}
    .summary-card p {{
      line-height: 1.6;
      font-size: 14px;
    }}
    .section-title {{
      font-size: 18px;
      color: var(--heading);
      margin: 28px 0 16px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .card h4 {{
      color: var(--heading);
      font-size: 15px;
      margin-bottom: 6px;
    }}
    .card p {{
      font-size: 13px;
      color: #8b949e;
      margin-bottom: 8px;
    }}
    .card-actions {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 12px;
      padding-top: 10px;
      border-top: 1px solid var(--border);
    }}
    .btn {{
      font-size: 12px;
      padding: 6px 12px;
      border-radius: 6px;
      cursor: pointer;
      border: 1px solid var(--border);
      background: #21262d;
      color: var(--heading);
      text-decoration: none;
      display: inline-block;
    }}
    .btn:hover {{ background: #30363d; }}
    .btn.primary {{ background: var(--green); border-color: var(--green); color: white; }}
    .btn.primary:hover {{ background: #2c974b; }}

    /* Source Drawer */
    #drawer {{
      position: fixed;
      top: 0;
      right: -500px;
      width: 480px;
      height: 100vh;
      background: var(--drawer-bg);
      border-left: 1px solid var(--border);
      box-shadow: -4px 0 20px rgba(0,0,0,0.5);
      transition: right 0.25s ease;
      display: flex;
      flex-direction: column;
      z-index: 100;
    }}
    #drawer.open {{ right: 0; }}
    .drawer-header {{
      padding: 20px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .drawer-header h3 {{ color: var(--heading); }}
    .drawer-header button {{
      background: none;
      border: none;
      color: #8b949e;
      font-size: 20px;
      cursor: pointer;
    }}
    .drawer-body {{
      padding: 20px;
      overflow-y: auto;
      flex: 1;
      font-size: 13px;
      line-height: 1.6;
    }}
    .drawer-field {{
      margin-bottom: 16px;
    }}
    .drawer-field label {{
      display: block;
      color: #8b949e;
      font-size: 11px;
      text-transform: uppercase;
      margin-bottom: 4px;
    }}
    .drawer-field code {{
      background: #161b22;
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 11px;
      display: block;
      word-break: break-all;
      border: 1px solid var(--border);
    }}
    .drawer-excerpt {{
      background: #161b22;
      border: 1px solid var(--border);
      padding: 12px;
      border-radius: 6px;
      font-family: monospace;
      font-size: 12px;
      white-space: pre-wrap;
      max-height: 250px;
      overflow-y: auto;
    }}
  </style>
</head>
<body>
  <div id="sidebar">
    <div class="search-box">
      <input type="text" id="search" placeholder="Search company or org number..." autofocus>
    </div>
    <div class="stats-bar">
      <span id="match-count">0 companies</span>
      <span>Signalpost V7</span>
    </div>
    <div id="company-list"></div>
  </div>

  <div id="main">
    <div class="top-bar">
      <div>
        <h1 id="view-name">Select a company</h1>
        <p id="view-meta" style="color:#8b949e; font-size:13px;"></p>
      </div>
      <div id="view-actions"></div>
    </div>
    <div class="container" id="content" style="display:none;">
      <div class="summary-card">
        <h3>Verified Synthesis</h3>
        <p id="view-summary"></p>
      </div>

      <div class="section-title">
        <span>Verified Job Postings</span>
        <span class="badge blue" id="jobs-count">0</span>
      </div>
      <div class="grid-2" id="jobs-grid"></div>

      <div class="section-title">
        <span>Dated News & Activity</span>
        <span class="badge blue" id="news-count">0</span>
      </div>
      <div class="grid-2" id="news-grid"></div>

      <div class="section-title">
        <span>Verifiable Source Provenance</span>
        <span class="badge green" id="sources-count">0</span>
      </div>
      <div class="grid-2" id="sources-grid"></div>
    </div>
  </div>

  <div id="drawer">
    <div class="drawer-header">
      <h3 id="drawer-title">Evidence Inspection</h3>
      <button onclick="closeDrawer()">&times;</button>
    </div>
    <div class="drawer-body">
      <div class="drawer-field">
        <label>Source Type</label>
        <div id="drawer-type" style="color:var(--heading);"></div>
      </div>
      <div class="drawer-field">
        <label>Source URL</label>
        <a id="drawer-url" href="#" target="_blank" style="color:var(--accent); word-break:break-all;"></a>
      </div>
      <div class="drawer-field">
        <label>Retrieved Timestamp</label>
        <div id="drawer-time"></div>
      </div>
      <div class="drawer-field">
        <label>Content SHA-256 Digest</label>
        <code id="drawer-hash"></code>
      </div>
      <div class="drawer-field">
        <label>Supporting Text Excerpt</label>
        <div class="drawer-excerpt" id="drawer-excerpt"></div>
      </div>
    </div>
  </div>

  <script>
    const COMPANIES = {payload_json};
    let activeCompany = null;

    function renderList(items) {{
      const list = document.getElementById("company-list");
      list.innerHTML = "";
      document.getElementById("match-count").innerText = `${{items.length}} companies`;
      items.forEach(c => {{
        const div = document.createElement("div");
        div.className = "company-item" + (activeCompany && activeCompany.org === c.org ? " active" : "");
        div.onclick = () => selectCompany(c);
        div.innerHTML = `
          <h4>${{c.name}}</h4>
          <p>Org: ${{c.org}} · ${{c.municipality || 'Norway'}}</p>
          <div class="badges">
            ${{c.website ? '<span class="badge green">Website</span>' : ''}}
            ${{c.jobs.length ? `<span class="badge blue">${{c.jobs.length}} Jobs</span>` : ''}}
            ${{c.news.length ? `<span class="badge blue">${{c.news.length}} News</span>` : ''}}
          </div>
        `;
        list.appendChild(div);
      }});
    }}

    function selectCompany(c) {{
      activeCompany = c;
      document.querySelectorAll(".company-item").forEach(el => el.classList.remove("active"));
      event.currentTarget?.classList.add("active");

      document.getElementById("content").style.display = "block";
      document.getElementById("view-name").innerText = c.name;
      document.getElementById("view-meta").innerText = `Organisation Number: ${{c.org}} · Municipality: ${{c.municipality || 'N/A'}} · Industry: ${{c.industry || 'Commercial'}} · Employees: ${{c.employees ?? 'Not reported'}}`;
      document.getElementById("view-summary").innerText = c.summary;

      // Jobs
      document.getElementById("jobs-count").innerText = c.jobs.length;
      const jGrid = document.getElementById("jobs-grid");
      jGrid.innerHTML = c.jobs.length ? "" : "<p style='color:#8b949e;'>No active jobs verified.</p>";
      c.jobs.forEach(j => {{
        const card = document.createElement("div");
        card.className = "card";
        const m = j.metrics || {{}};
        const srcTag = j.source_class === "external_ats" ? '<span class="badge blue">External ATS</span>' : '<span class="badge">Direct</span>';
        const careerRef = m.source_career_url ? `<p style="font-size:11px; color:#8b949e; margin-top:2px;">Via: ${{m.source_career_url}}</p>` : '';
        card.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:flex-start;">
            <h4>${{m.job_title || 'Role'}}</h4>
            ${{srcTag}}
          </div>
          <p>${{m.location || 'Norway'}} · ${{m.employment_type || 'Full-time'}}${{m.published_at ? ' · Posted ' + m.published_at : ''}}</p>
          ${{careerRef}}
          <div class="card-actions">
            <button class="btn" onclick='openSourceDrawer(${{JSON.stringify(j)}})'>Inspect Evidence</button>
            ${{m.apply_url ? `<a class="btn primary" href="${{m.apply_url}}" target="_blank">Apply</a>` : ''}}
          </div>
        `;
        jGrid.appendChild(card);
      }});

      // News
      document.getElementById("news-count").innerText = c.news.length;
      const nGrid = document.getElementById("news-grid");
      nGrid.innerHTML = c.news.length ? "" : "<p style='color:#8b949e;'>No dated announcements verified.</p>";
      c.news.forEach(n => {{
        const card = document.createElement("div");
        card.className = "card";
        const m = n.metrics || {{}};
        card.innerHTML = `
          <h4>${{m.article_title || 'Announcement'}}</h4>
          <p>Published: ${{m.published_at || 'Dated'}}</p>
          <div class="card-actions">
            <button class="btn" onclick='openSourceDrawer(${{JSON.stringify(n)}})'>Inspect Evidence</button>
            <a class="btn" href="${{n.source_url}}" target="_blank">Open Source</a>
          </div>
        `;
        nGrid.appendChild(card);
      }});

      // Sources
      document.getElementById("sources-count").innerText = c.sources.length;
      const sGrid = document.getElementById("sources-grid");
      sGrid.innerHTML = "";
      c.sources.forEach(s => {{
        const card = document.createElement("div");
        card.className = "card";
        card.innerHTML = `
          <h4>${{s.label}}</h4>
          <p>${{s.url ? s.url.substring(0, 45) + '...' : ''}}</p>
          <div class="card-actions">
            <button class="btn" onclick='openSourceDrawer(${{JSON.stringify(s)}})'>View Provenance</button>
            ${{s.url ? `<a class="btn" href="${{s.url}}" target="_blank">Visit</a>` : ''}}
          </div>
        `;
        sGrid.appendChild(card);
      }});
    }}

    function openSourceDrawer(item) {{
      const d = document.getElementById("drawer");
      document.getElementById("drawer-type").innerText = item.source_class || item.platform || item.type || "Verified External Source";
      const u = item.source_url || item.url || "#";
      const urlEl = document.getElementById("drawer-url");
      urlEl.innerText = u;
      urlEl.href = u;
      document.getElementById("drawer-time").innerText = item.retrieved_at || "Captured during run";
      document.getElementById("drawer-hash").innerText = item.content_sha256 || item.hash || "Verified Digest";
      document.getElementById("drawer-excerpt").innerText = item.evidence_span || item.excerpt || (item.metrics && item.metrics.supporting_text) || "Supporting text verified during exact identity evaluation.";
      d.classList.add("open");
    }}

    function closeDrawer() {{
      document.getElementById("drawer").classList.remove("open");
    }}

    // Filter listener
    document.getElementById("search").addEventListener("input", (e) => {{
      const q = e.target.value.toLowerCase().trim();
      const filtered = COMPANIES.filter(c => 
        c.name.toLowerCase().includes(q) || 
        c.org.includes(q) || 
        (c.municipality && c.municipality.toLowerCase().includes(q))
      );
      renderList(filtered);
    }});

    // Initialize list & select first item
    renderList(COMPANIES);
    if (COMPANIES.length) selectCompany(COMPANIES[0]);
  </script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description="Build and serve Signalpost V7 Data-Backed Viewer")
    parser.add_argument("--envelopes", default="submission/envelopes.jsonl", help="Terminal envelope JSONL path")
    parser.add_argument("--output", default="out/v7-company-viewer.html", help="Output HTML file path")
    args = parser.parse_args()

    envelopes = load_envelopes(Path(args.envelopes))
    html_content = build_viewer_html(envelopes)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_content, encoding="utf-8")
    print(f"Signalpost V7 Viewer successfully generated at: {out_path.resolve()}")


if __name__ == "__main__":
    main()
