# 🧭 Signalpost: Evidence-First Autonomous Norwegian Company Intelligence

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Package Manager: uv](https://img.shields.io/badge/package%20manager-uv-purple.svg)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **Signalpost** is a production-grade, deterministic intelligence system that discovers, crawls, verifies, and synthesizes operating intelligence for any Norwegian corporate entity (*Foretak / Enhet*) directly from official Brønnøysund registries and corroborated public digital channels.
>
> Built around a strict **"No Evidence, No Claim"** doctrine: external search strings and fuzzy mentions are **never** treated as proof. A website or social profile only enters a company’s profile after a deterministic identity check ties it to that exact company (organisation number on the site, the registry’s own website and e-mail domain, or the name together with the registered address, phone or people), and its source is saved with the run.

---

## 📑 Table of Contents
- [Executive Overview](#-executive-overview)
- [Core Architectural Tenets](#-core-architectural-tenets)
- [End-to-End System Architecture](#-end-to-end-system-architecture)
- [Viewer](#️-viewer)
- [Project Layout](#-project-layout)
- [Quickstart & Execution](#-quickstart--execution)
- [Pipeline Verification](#-pipeline-verification)
- [Source Policy & Data Governance](#-source-policy--data-governance)
- [License](#-license)

---

## 🌟 Executive Overview

Extracting structured business intelligence from public web sources is prone to **entity confusion and stale data**: confusing a sole trader with a multinational of the same name, or treating a directory listing as the company's own site.

Signalpost handles this with a deterministic pipeline:
1. **Official Registry Grounding**: Reads authoritative records from Brønnøysundregistrene (*Enhetsregisteret*, *Regnskapsregisteret*, roles, sub-units). Every supplied company is resolved, from the local snapshot or the live API.
2. **Bounded Website Discovery**: Checks the registry-listed website, then a small set of candidate domains derived from the registry (name, e-mail domain, sub-units), capped at 30 website requests per company.
3. **Deterministic Identity Gate**: A site is published only when it is tied to the exact company. That takes the organisation number on the site, the registry's own website and e-mail domain, or the company name together with the registered address, postcode, city, phone, or a registered CEO or board member.
4. **Transport-Level Resilience**: Bounded streaming decompression (gzip and deflate) with hard byte limits, robots.txt checks once per host, and short timeouts for guessed domains.
5. **No Naked Facts**: Every published fact carries its source URL, retrieval time, source class and the SHA-256 of the exact source bytes, which are saved with the run.
6. **Refresh**: A rerun with `--previous` records what changed since the earlier run and keeps earlier evidence that a source failed to return.

---

## 🛡️ Core Architectural Tenets

### 1. No Naked Facts (Every Claim Audited)
Every evidence record in a profile has this shape (a real `financials` record):
```json
{
  "field": "financials",
  "status": "available",
  "source_class": "official_annual_accounts",
  "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/986093036",
  "retrieved_at": "2026-10-04T00:29:47.389553Z",
  "content_sha256": "bc2b2ea7d7cace4722d82c7b8793093f027935e40ca62738643a19fdf2251538",
  "snapshot_path": "sources/bc2b2ea7d7cace4722d82c7b8793093f027935e40ca62738643a19fdf2251538.json.gz"
}
```
`status` is always one of `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`.

### 2. Strict Deterministic Identity Resolution
A candidate website is **accepted or rejected deterministically**:
* **Direct Match**: The company's 9-digit organisation number appears on the site, including its footer or contact block.
* **Registry Domain Match**: The registry's website field and e-mail domain both point to the site. Shared mail hosts such as gmail.com never count.
* **Corroborated Name Match**: The legal name appears on the site together with the registered street address, postcode, city or phone, or a registered CEO or board member's name.
* **Conflict Rejection**: A different organisation number on the site, a parked or for-sale domain, or a name-only match on an unrelated domain is never published. Name-only matches are reported as `ambiguous`.
* **Aggregator Blocking**: Directory sites (*Proff, 1881, Purehelp, Gulesider, CompanyWall* and others) are never treated as the company's website.

### 3. Refresh and Change Tracking
Run with `--previous <profiles.jsonl>` to compare against an earlier run:
* Each changed field (registry details, roles, accounts, locations, website) is recorded with old and new values and both content hashes.
* When a source fails on the rerun but answered before, the earlier evidence is carried forward and marked as such, never silently dropped.
* Saved sources are content-addressed, so rerunning over unchanged sources stores nothing new.

---

## 🏗️ End-to-End System Architecture

```text
              Organisation numbers supplied at run time
                               │
                               ▼
              Brønnøysund registers (snapshot or live API)
       entity · annual accounts · roles · group · sub-units
                               │
                               ▼
      Website: registry-listed site, then up to 3 candidate domains
            (≤ 30 website requests per company, robots.txt)
                               │
                               ▼
         Deterministic identity gate (org.nr, registry domain,
          name + address / postcode / city / phone / person)
                 │                               │
            verified site                 not tied to company
                 │                       (ambiguous / not_available)
                 ▼                               │
   Social links, job postings and dated          │
   articles read from the verified site          │
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
          Synthesis: what it is, what it does, size, who runs it,
          what changed, what is unknown (each with sources)
                                 │
                                 ▼
     profiles.jsonl · envelopes.jsonl · run-report.json · sources/ · viewer/
```

---

## 🖥️ Viewer

Every run writes a self-contained viewer over **that run's own profiles** to `<output-dir>/viewer/index.html`: a dark, three-column workspace (company explorer, intelligence panel, evidence inspector) with no build step. It works offline and on mobile, where the columns collapse to one at a time and the inspector opens as a drawer.
- **Search and filters**: by name, org number, municipality or industry; filter to companies with a website, social profiles, job postings, dated news, an ambiguous site, no website, or a failed result.
- **Intelligence panel**: status strip, executive summary, at-a-glance cards, a dated "what changed" timeline, digital footprint and hiring signals, and an evidence table of every fact.
- **Evidence inspector**: click any fact to see its source URL, publication and retrieval dates, identity check, SHA-256, a link to the saved copy of the source, and the extracted text.
- **Result states**: every module's state (`available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`) with the reason when it is not available.
- **What changed / what is unknown**: dated, sourced events and an explicit list of what could not be established.
- **Compare and export**: side-by-side comparison of up to four companies; CSV or JSON export of the filtered set.

To browse the latest run in `out/run`, double-click `start.bat` (or open `out/run/viewer/index.html` directly).

---

## 📁 Project Layout

```text
signalpost/
├── pyproject.toml              # Dependencies
├── uv.lock                     # Pinned, reproducible dependency lockfile
├── README.md                   # System documentation
├── RUN.md                      # Run command, outputs, result states and options
├── start.bat                   # Opens the viewer of the latest run (Windows)
├── brreg-enheter.csv           # Brreg bulk registry snapshot (Git LFS, optional)
│
├── data/
│   ├── company_universe_411k.db           # SQLite index of 411,160 Norwegian entities (Git LFS, optional)
│   ├── signalpost-company-universe-*.gz   # Compressed universe export
│   ├── ground-truth-100.jsonl             # 100-company labelled set used for recall checks
│   ├── discovery-ground-truth.jsonl       # Audited website labels
│   ├── operating-sample-35.jsonl          # Operating-company sample
│   └── fresh_10.jsonl, fresh_20.jsonl, genuine_fresh_100.jsonl   # Small test batches
│
├── src/norway_company_agent/   # Core library
│   ├── adapters/               # Social, site, hiring, news, sub-unit and role observations
│   ├── activity.py             # Dated news and announcements from company sites
│   ├── batch.py                # Input reading, live-registry fallback, result envelopes
│   ├── discovery.py            # Candidate website discovery with aggregator blocking
│   ├── evidence.py             # Evidence records and the six result states
│   ├── evidence_store.py       # Content-addressed store of the source bytes behind each fact
│   ├── external_footprint.py   # Observation validation and aggregation
│   ├── history.py, refresh.py  # Change detection between runs
│   ├── http.py                 # JSON fetching with retries
│   ├── identity.py             # Deterministic company identity gate
│   ├── identity_store.py       # Local registry snapshot lookup
│   ├── jobs.py                 # Individual job postings
│   ├── official.py             # Brønnøysund registry and accounts APIs
│   ├── research.py             # Synthesis: what it is, does, size, people, changes, unknowns
│   ├── sampling.py             # Bulk snapshot reading
│   ├── viewer.py               # Builds the per-run HTML viewer
│   └── website.py              # Safe website fetching, decompression and sub-page crawl
│
├── scripts/
│   ├── run_competition_batch.py               # The agent: one result per supplied organisation number
│   ├── evaluate_independent_ground_truth.py   # Website recall and precision on the labelled set
│   ├── test_adversarial_identity.py           # Adversarial identity cases (name collisions, parked domains)
│   ├── validate_submission_corpus.py          # Manifest-to-envelope integrity check
│   ├── build_ground_truth_100.py              # Rebuilds the labelled 100-company set
│   └── run_google_news_rss_connector.py       # Experimental news connector (not used by the agent)
│
├── tests/                      # pytest suite (uv run pytest -q)
│
├── submission/
│   ├── organisation-manifest.jsonl    # 1,100 stratified Norwegian companies for full-size test runs
│   ├── source-policy.md               # Source compliance policy
│   └── RUN.md                         # Submission run notes
│
└── out/run/                    # Default run output (git-ignored)
    ├── profiles.jsonl          # One evidence-backed profile per company, input order
    ├── envelopes.jsonl         # One result envelope per company
    ├── run-report.json         # Counts, module states, request usage, validation checks
    ├── sources/                # Saved source bytes, named by SHA-256
    └── viewer/index.html       # Viewer over this run
```

---

## 🚀 Quickstart & Execution

### 1. Prerequisites
- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `winget install astral-sh.uv`)
- Git LFS is optional: without the large local snapshots the agent reads every company from the live Brønnøysund API.

### 2. Installation
```bash
git clone https://github.com/gautamhardik/signalpost.git
cd signalpost
uv sync
```

### 3. Run the agent
One command. Give it the company list (JSON, JSONL, or one organisation number per line):

```bash
uv run python scripts/run_competition_batch.py --organisations data/fresh_10.jsonl --output-dir out/run
```

It returns exactly one result per input, including companies it has never seen and numbers that are not registered. Each result carries one of six states: `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`. Useful options:

| Option | Default | Purpose |
|:---|:---|:---|
| `--workers` | 12 | Companies researched in parallel |
| `--web-requests-per-company` | 30 | Cap on website and search requests per company (registry calls are not capped) |
| `--budget` | none | Optional run-wide ceiling on website and search requests |
| `--previous` | none | Profiles from an earlier run: records what changed and keeps earlier evidence a source no longer returns |
| `--resume` | off | Continue an interrupted run in the same output directory |

### 4. Open the viewer
Double-click `start.bat`, or open `out/run/viewer/index.html`.

---

## 📊 Pipeline Verification

### 1. Independent 100-Company Ground Truth Audit
Run the agent on the labelled 100-company set, then check website recall and wrong-company publications against the labels:
```bash
uv run python scripts/run_competition_batch.py --organisations data/ground-truth-100.jsonl --output-dir out/gt100
uv run python scripts/evaluate_independent_ground_truth.py \
  --profiles out/gt100/profiles.jsonl \
  --envelopes out/gt100/envelopes.jsonl \
  --ground-truth data/ground-truth-100.jsonl \
  --output out/gt100/evaluation-report.json
```

### 2. Run Adversarial Identity & Stress Tests
Checks the identity gate against name collisions, corporate hierarchies, parked domains and spoofed footers:
```bash
uv run python scripts/test_adversarial_identity.py
```

### 3. Run Unit & Regression Tests
```bash
uv run pytest tests/ -q
```

---

## ⚖️ Source Policy & Data Governance

Signalpost was engineered with ethical and legal data access as a first principle:

1. **Brønnøysund Public Sector Data**: Ingests official registry data under the **Norwegian License for Open Government Data (NLOD)** / **Creative Commons Attribution 4.0 (CC-BY 4.0)**.
2. **Robots.txt & Rate Limiting**: All outbound HTTP fetchers strictly parse and obey `robots.txt` disallow rules, apply host-level rate limiting, and gracefully back off on HTTP 429/403.
3. **Aggregator Protection**: Commercial business directories (*Proff*, *Purehelp*, *1881*, *Gulesider*) are blocked from ingestion, ensuring data integrity and respecting directory terms of service.
4. **Zero Outbound Privacy Leakage**: No private or credentialed APIs are queried. No personal email extraction or GDPR-violating scraping is performed.
5. **Full Provenance Transparency**: Every claim emitted can be traced back to its public origin via its audited URL, timestamp, and immutable SHA-256 payload hash.

---

## 📄 License
Signalpost is licensed under the [MIT License](LICENSE).
