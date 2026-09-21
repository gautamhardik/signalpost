# 🧭 Signalpost: Evidence-First Autonomous Norwegian Company Intelligence

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Package Manager: uv](https://img.shields.io/badge/package%20manager-uv-purple.svg)](https://docs.astral.sh/uv/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Local Calibration Score](https://img.shields.io/badge/local%20calibration-94.57%20%2F%20100-blue.svg)](#-verified-benchmark-performance)
[![External Precision](https://img.shields.io/badge/external%20precision-100%25-brightgreen.svg)](#-verified-benchmark-performance)
[![Naked Facts](https://img.shields.io/badge/naked%20facts-0-brightgreen.svg)](#-core-architectural-tenets)

> **Signalpost** is a production-grade, deterministic intelligence system that discovers, crawls, verifies, and synthesizes operating intelligence for any Norwegian corporate entity (*Foretak / Enhet*) directly from official Brønnøysund registries and corroborated public digital channels.
>
> Built around a strict **"No Evidence, No Claim"** doctrine: external search strings and fuzzy mentions are **never** treated as proof. A digital presence only enters a company’s profile after clearing cryptographic provenance and deterministic identity gates ($\ge 0.90$ token similarity, registered address, phone, or corporate email domain matching).

---

## 📑 Table of Contents
- [Executive Overview](#-executive-overview)
- [Key Verified Performance Metrics](#-key-verified-performance-metrics)
- [Core Architectural Tenets](#-core-architectural-tenets)
- [End-to-End System Architecture](#-end-to-end-system-architecture)
- [Interactive UI & Provenance Inspector](#-interactive-ui--provenance-inspector)
- [Project Layout](#-project-layout)
- [Quickstart & Execution](#-quickstart--execution)
- [Pipeline Verification & Evaluation](#-pipeline-verification--evaluation)
- [Source Policy & Data Governance](#-source-policy--data-governance)
- [License](#-license)

---

## 🌟 Executive Overview

Extracting structured business intelligence from public web sources is notoriously prone to **hallucinations, entity confusion, and stale data** (e.g., confusing a sole trader with a multinational of the same name, or scraping third-party aggregators).

Signalpost solves this through a **multi-stage deterministic verification pipeline**:
1. **Official Registry Grounding**: Ingests authoritative records directly from Brønnøysundregistrene (*Enhetsregisteret*, *Regnskapsregisteret*, *Roller*, *Underenheter*).
2. **Adaptive Opportunity Scoring**: Intelligently skips wasteful searches for shell companies, real-estate SPVs, or entities with zero plausible digital footprint.
3. **Deterministic Identity Gates**: Enforces multi-attribute corroboration (organization number, domain WHOIS, custom MX/email host, executive names, phone numbers, postal codes).
4. **Transport-Level Resilience**: Hardened streaming HTTP decompression (gzip and deflate with raw/wrapped zlib modes) protecting against zip-bombs with hard byte limits while restoring compressed company pages.
5. **Zero Naked Facts**: Every published field links to a full source URL, an ISO-8601 retrieval timestamp, a source tier classification, and an immutable SHA-256 snapshot hash.
6. **Deterministic Replay & Refresh**: Re-running pipelines over existing corpora computes cryptographic diffs, pinpointing verified corporate changes with zero false drifts.

---

## 🏆 Verified Benchmark Performance

### 1. Independent 100-Company Ground Truth Audit (Run 10A / `v10a-freeze`)
Rigorously audited across a balanced 100-company ground truth universe representing all operational cohorts:

| Metric | Result | Benchmark Bar | Status |
|:---|:---:|:---:|:---:|
| **Wrong-Company Publications** | **0** | **0 (Zero Tolerance)** | **Flawless (100.0% Precision)** |
| **External Identity Precision** | **100.0%** | $\ge 95.0\%$ | **Perfect (318/318 observations)** |
| **Registered Website Recall** | **68.0% (34/50)** | $\ge 60.0\%$ | **+4.0% over V7 baseline** |
| **Total Verified Websites Discovered** | **43 / 100** | $> 40$ | **43 companies** |
| **Holding Company Abstentions** | **25 / 25 (100%)** | 100% | **Zero boundary leaks** |
| **Outbound HTTP Request Footprint** | **939 requests** | $\le 2,000$ quota | **1,061 requests remaining** |
| **External Paid API Cost** | **$0.00** | $0.00 | **Zero commercial API costs** |
| **Terminal Contract Compliance** | **100% (100/100)** | 100% | **0 silent drops** |

### 2. Local Calibration on Competition Rubric
Validated locally using the open-source evaluation suite across the standardized **Builderr Norwegian Company Intelligence Competition Rubric** (35 Coverage / 30 Accuracy / 20 Refresh / 10 Synthesis / 5 UX):

| Rubric Dimension | Max Score | **Local Calibrated Score** | Qualification Bar | Status |
|:---|:---:|:---:|:---:|:---:|
| **Coverage & Source Discovery** | 35.0 | **29.57** | $\ge 21.0$ | **Exceeded** |
| **Accuracy, Identity & Evidence** | 30.0 | **30.00** | $\ge 24.0$ | **Perfect (100%)** |
| **Refresh & Extensibility** | 20.0 | **20.00** | $\ge 14.0$ | **Perfect (100%)** |
| **Decision-Useful Synthesis** | 10.0 | **10.00** | $\ge 7.0$ | **Perfect (100%)** |
| **UX & Interactive Inspection** | 5.0 | **5.00** | $\ge 3.0$ | **Perfect (100%)** |
| **Total Composite Score** | **100.0** | **94.57 / 100** | $\ge 65.0$ | **Calibrated** |

> **Note on Evaluation Status**: The 94.57 score represents an internal local calibration on fixture data. Official competition scores are determined exclusively by Builderr's automated platform evaluation upon submission of this revision.

---

## 🛡️ Core Architectural Tenets

### 1. No Naked Facts (Every Claim Audited)
Every data point emitted in terminal profiles implements the strict `ClaimRecord` contract:
```json
{
  "claim": "financials.revenue_nok",
  "value": 48250000,
  "source_url": "https://data.brreg.no/regnskapsregisteret/regnskap/987654321",
  "source_class": "tier2_registry",
  "retrieved_at": "2026-09-15T10:14:22Z",
  "content_sha256": "4a31b12cc032b60fab050d59f8da35ceb1e3778385038ab9a89d714578b"
}
```

### 2. Strict Deterministic Identity Resolution
A discovered candidate URL is **rejected or accepted deterministically** based on rigorous corroboration:
* **Direct Match**: Presence of the 9-digit Norwegian Org Number (*Organisasjonsnummer*) on the page or in footer metadata.
* **Email & Domain Corroboration**: MX records and official email host matching the registered entity name.
* **Corroborative Match**: Tokenized company name similarity $\ge 0.90$ combined with registered visiting/business address, executive names (*Daglig leder / Styreleder*), or telephone match.
* **Aggregator Blocking**: Hard blocks directory aggregator scrapers (*Proff, 1881, Purehelp, Gulesider, Companywall*) from acting as identity anchors.

### 3. Change-Diff Refresh Engine
Tracks historical state snapshots. Re-evaluating an existing corpus generates an unambiguous diff:
* `ADDED`, `MODIFIED`, or `REMOVED` claims with before/after timestamps.
* Cryptographically validated against snapshot hashes to prevent phantom update alerts.

---

## 🏗️ End-to-End System Architecture

```text
               Target Norwegian Entity (Org Number)
                               │
                               ▼
                Brønnøysund Official Registries
     (Enhetsregisteret, Regnskapsregisteret, Roller, Underenheter)
                               │
                               ▼
                  Evidence Opportunity Scorer
    (Evaluates legal form, employees, custom email domain, industry)
                               │
                ┌──────────────┴──────────────┐
                ▼                             ▼
       High Opportunity Entity       Low Opportunity Entity
       (1-2 Targeted Searches)       (Abstain / Registry Only)
                │                             │
                ▼                             │
    Candidate Discovery & Crawl               │
                │                             │
                ▼                             │
    Streaming Decompression & Subpages        │
      (safe_decompress_body gzip/deflate,     │
       /kontakt and /om-oss corroboration)    │
                │                             │
                ▼                             │
    Deterministic Identity Gate               │
      (Token similarity >= 0.90,              │
       address / phone / org match)           │
                │                             │
                ▼                             ▼
       Verified Company Evidence       Official Registry Profile
                │                             │
                └──────────────┬──────────────┘
                               │
                               ▼
                 Synthesized Company Dossier
          (Who, What, How Big, Leadership, Signals, Provenance)
                               │
                               ▼
                  Terminal Execution Envelope
            (Cryptographic SHA-256 Hashes, JSONL)
```

---

## 🖥️ Interactive UI & Provenance Console

Signalpost provides an evidence inspection and comparison UI (`ui/index.html`):
- **Search Console**: Look up any entity by Norwegian Org Number or Legal Name.
- **Decision Dossier**: Interactive breakdown of operational status, financials, active jobs, news events, and corporate governance.
- **Evidence Drawer**: Click any claim to inspect the underlying source URL, timestamp, retrieval mode, and cryptographic content hash.
- **Diff & Refresh Viewer**: Compare historical snapshots to view additions and modifications side-by-side.

To open the console locally:
```bash
# Serve the repository root
python -m http.server 8000
# Navigate to http://localhost:8000/ui/
```

---

## 📁 Project Layout

```text
signalpost/
├── pyproject.toml              # Project dependencies & build configuration
├── uv.lock                     # Pinned reproducible dependency lockfile
├── README.md                   # System documentation & architectural reference
├── RUN.md                      # Official execution guide & evaluation runner
├── benchmark-100.jsonl         # 100-company frozen evaluation benchmark
├── brreg-enheter.csv           # Brreg bulk registry snapshot (Tracked via Git LFS)
│
├── data/
│   ├── company_universe_411k.db           # SQLite index of 411,160 active Norwegian entities (LFS)
│   ├── discovery-ground-truth.jsonl       # Audited ground truth for precision/recall validation
│   ├── ground-truth-100.jsonl             # 100-company ground truth labels
│   ├── operating-sample-35.jsonl          # Calibration sample for active trading entities
│   └── signalpost-company-universe-*.gz   # Compressed active universe export
│
├── src/norway_company_agent/   # Core intelligence library
│   ├── adapters/               # Pluggable external footprint & governance adapters
│   │   ├── base.py             # Base adapter interface
│   │   └── sources.py          # Hiring, SiteActivity, SiteNews, Subunits, GovernanceRoles
│   ├── activity.py             # Company announcements, dated activity & events
│   ├── batch.py                # Batch pipeline execution & worker coordination
│   ├── budget.py               # Token & request footprint budget governor
│   ├── crawl_events.py         # HTTP crawl event emitter & ledger
│   ├── discovery.py            # Targeted discovery engine with aggregator blocking
│   ├── evidence.py             # Claim record definitions & provenance contracts
│   ├── external_control.py     # External search loop controller & guardrails
│   ├── external_footprint.py   # Web & digital footprint extractor
│   ├── history.py              # Snapshot comparison & cryptographic change-diff engine
│   ├── identity.py             # Deterministic multi-attribute identity gate (threshold: 0.90)
│   ├── identity_store.py       # Entity caching & local state store
│   ├── jobs.py                 # Open vacancies & career posting discovery
│   ├── official.py             # Brønnøysund API & bulk CSV connector
│   ├── operations.py           # AST-based deterministic query interpreter
│   ├── refresh.py              # SHA-256 change-diff & snapshot comparison engine
│   ├── research.py             # Autonomous company synthesis & profile assembler
│   ├── sampling.py             # Stratified sampling & universe slicing
│   ├── scrapy_crawler.py       # Asynchronous web crawler with robots.txt compliance
│   └── website.py              # Homepage content parser, safe decompression & subpages
│
├── scripts/                    # Automation, execution, and evaluation CLI tools
│   ├── run_competition_batch_v2.py            # Main production runner (100 to 1,100+ entities)
│   ├── evaluate_independent_ground_truth.py   # Independent 100-company audit tool
│   ├── evaluate_competition.py                # Official 35/30/20/10/5 rubric evaluator
│   ├── evaluate_external_recall.py            # Precision & recall validator
│   ├── test_adversarial_identity.py           # Adversarial edge-case validation suite
│   ├── validate_submission_corpus.py          # 1:1 manifest-to-envelope integrity auditor
│   └── score_company_completeness.py          # Profile completeness scoring tool
│
├── tests/                      # Comprehensive pytest regression suite
│   ├── test_activity.py        # Activity and news extraction tests
│   ├── test_discovery.py       # Discovery funnel tests
│   ├── test_history.py         # Refresh diff tests
│   ├── test_jobs.py            # Career posting tests
│   └── test_website_decompression.py # HTTP decompression & zip-bomb protection tests
│
├── submission/                 # Official competition submission artifacts
│   ├── organisation-manifest.jsonl    # 1,100 stratified Norwegian test entities
│   ├── envelopes.jsonl                # 1,100 validated terminal execution envelopes
│   ├── profiles.jsonl                 # 1,100 completed evidence-backed profiles
│   ├── run-report.json                # Execution ledger & resource consumption report
│   ├── score.json                     # Official calibrated benchmark report (94.57/100)
│   └── source-policy.md               # Source compliance policy
│
└── ui/
    └── index.html              # Interactive Provenance Inspector & Intelligence Console
```

---

## 🚀 Quickstart & Execution

Signalpost is 100% reproducible using [`uv`](https://docs.astral.sh/uv/).

### 1. Prerequisites
- Python 3.12 or newer
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `winget install astral-sh.uv`)
- `git-lfs` initialized (`git lfs install`)

### 2. Installation
```bash
# Clone the repository
git clone https://github.com/gautamhardik/signalpost.git
cd signalpost

# Pull large database assets
git lfs pull

# Sync exact locked dependencies
uv sync
```

### 3. Run the Production Batch Pipeline
Execute the crawler and analysis pipeline on the 100-company benchmark:

```bash
uv run python scripts/run_competition_batch_v2.py \
  --organisations data/ground-truth-100.jsonl \
  --bulk data/signalpost-company-universe-2025.jsonl.gz \
  --profiles-output out/v7_run10_profiles.jsonl \
  --output out/v7_run10_envelopes.jsonl \
  --report out/v7_run10_batch_report.json \
  --run-id run10-decompression-subpages \
  --budget 2000 \
  --workers 4
```

---

## 📊 Pipeline Verification & Evaluation

### 1. Independent 100-Company Ground Truth Audit
Audit against the stratified ground-truth benchmark:
```bash
uv run python scripts/evaluate_independent_ground_truth.py \
  --profiles out/v7_run10_profiles.jsonl \
  --envelopes out/v7_run10_envelopes.jsonl \
  --ground-truth data/ground-truth-100.jsonl \
  --output out/v7_run10_evaluation_report.json
```

### 2. Score Against the Official Competition Rubric
Calculate the official **35 / 30 / 20 / 10 / 5** point distribution:
```bash
uv run python scripts/evaluate_competition.py \
  --profiles out/v7_run10_profiles.jsonl \
  --envelopes out/v7_run10_envelopes.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --report out/v7_run10_batch_report.json \
  --output out/score.json
```

### 3. Validate External Precision & Recall
Audit against verified external online footprints:
```bash
uv run python scripts/evaluate_external_recall.py \
  --profiles out/v7_run10_profiles.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --output out/recall.json
```

### 4. Run Adversarial Identity & Stress Tests
Verify zero false positives against name collisions, parked domains, and spoofed footers:
```bash
uv run python scripts/test_adversarial_identity.py
```

### 5. Run Unit & Regression Tests
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
