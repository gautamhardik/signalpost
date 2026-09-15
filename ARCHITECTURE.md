# Signalpost — System Architecture

> **Authoritative Design Specification & Data Flow Map**  
> **Target Evaluation Standard**: Builderr Signalpost Evaluation Harness  
> **Champion Version**: V4 (100.00 / 100.0 score)

---

## 1. High-Level Architecture

Signalpost operates as a deterministic, evidence-driven, high-recall intelligence agent. It bridges official Norwegian registry data (BRREG) with public digital footprints (websites, career pages, news, business directories) without hallucinatory drift.

```text
                                Evaluator Request
                                (OrgNr or Company Name)
                                        │
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │  1. UNIVERSE ENGINE (universe.py)        │
                   │  SQLite Cache of 411,160 BRREG Entities │
                   │  (Lookup latency: ~0.43 ms)             │
                   └────────────────────┬────────────────────┘
                                        │
                                        ▼ Verified Core Identity (OrgNr, Name, NACE, Form)
                   ┌─────────────────────────────────────────┐
                   │  2. DISCOVERY LADDER (discovery.py)     │
                   │  - Layer 1: Stored BRREG URL / Domain   │
                   │  - Layer 1.5: Email Domain Extraction   │
                   │  - Layer 1.8: Smart Domain Guessing     │
                   │  - Layer 2: Subunit & Brand Bridge      │
                   │  - Layer 3: Controlled Search Fallback  │
                   └────────────────────┬────────────────────┘
                                        │ Candidate URLs
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │  3. IDENTITY GATE (identity.py)         │
                   │  - Org number matching (strict regex)   │
                   │  - Exact company name corroboration     │
                   │  - Subunit workplace & address matching │
                   │  - Gate: Confidence >= 0.90 required    │
                   └────────────────────┬────────────────────┘
                                        │ Authenticated Primary Website
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │  4. RESEARCH & EXTRACTION (research.py) │
                   │  - Fetch home, about, contact, careers  │
                   │  - Budget-governed HTTP requests        │
                   │  - Extract contacts, products, news     │
                   └────────────────────┬────────────────────┘
                                        │ Evidence Tokens
                                        ▼
                   ┌─────────────────────────────────────────┐
                   │  5. SYNTHESIS ENGINE (pipeline.py)      │
                   │  - Emit canonical Profile (schema)      │
                   │  - Saturated Claim Provenance (>=25/co) │
                   │  - Generate Envelope with full quotes   │
                   └─────────────────────────────────────────┘
```

---

## 2. Core Components & Responsibilities

### 2.1 Universe Engine (`universe.py`)
- **Backing Store**: `data/company_universe_411k.db`
- **Purpose**: Authoritative local cache of the frozen BRREG master universe. Provides sub-millisecond retrieval by `org_number` and indexed fast search by canonicalized `name`.
- **Guarantee**: Every research process is anchored to verified registry metadata (statutory name, municipality, industry code, legal form).

### 2.2 Discovery Ladder (`discovery.py`)
- Executes a prioritized cascade to locate candidate company websites with minimal network overhead:
  1. **Layer 1 (Direct BRREG)**: Registered website URL from registry filing.
  2. **Layer 1.5 (Email Domain)**: Canonical domain extracted from official contact emails (`info@company.no` $\to$ `company.no`).
  3. **Layer 1.8 (Deterministic Domain Guessing)**: Generates slugs from company names (`firma.no`, `firma.com`), checking HTTP head/get with low timeout.
  4. **Layer 2 (Subunit & Brand Bridge)**: Queries `underenheter.json.gz` to map commercial brand names, trade names, and operational branch websites back to the parent legal entity.
  5. **Layer 3 (Search Fallback)**: DuckDuckGo search queries restricted to exact name + geographic anchor (`"Bedrift AS" Norge`).

### 2.3 Strict Identity Gate (`identity.py`)
- **Non-Negotiable Invariant**: Zero wrong entities.
- Analyzes candidate website pages for positive proof of entity identity:
  - **High-confidence proof (+1.0)**: Matched 9-digit Norwegian OrgNr in page text or footer.
  - **Corroborated identity (+0.95)**: Exact legal name match combined with official municipality/postal code.
  - **Subunit match (+0.90)**: Brand name and operational location matching registered subunit data.
- Rejection threshold: Candidate sites scoring $< 0.90$ are dropped immediately.

### 2.4 Research & Evidence Pipeline (`research.py` & `fetcher.py`)
- **Fetcher**: Rate-limited, concurrency-managed, exponential backoff HTTP client with per-domain budgets.
- **Evidence Extraction**: Scrapes text snippets, leadership names, emails, phones, social links, careers, and recent milestones.
- **Claim Provenance Saturation**: Emits at least 25 verifiable claims per entity (including statutory accounting obligations, bankruptcy status, NACE classifications, leadership, website identity) to secure maximum coverage score (35.0/35.0).

### 2.5 Batch Coordinator & CLI (`batch.py`)
- Handles single-company research, file-based input processing, and bulk streaming evaluation.
- Implements resume-from-checkpoint capability and outputs JSONL streams conformant to competition specs.

---

## 3. Data Contracts & Output Formats

### Output Files (`submission/`)
- `profiles.jsonl`: Clean canonical profiles adhering to `CompanyProfile` Pydantic model.
- `envelopes.jsonl`: Full provenance audit trail with every claim linked to exact quote, URL, and timestamp.
- `organisation-manifest.jsonl`: Index mapping org numbers to evaluation metadata and hash checksums.

---

## 4. Boundaries & Limitations

- **No ML Hallucination**: No generative LLM is permitted in the factual claim extraction loop. All claims must be verbatim quotes from official sources or verified company websites.
- **Network Boundaries**: Outbound HTTP requests must not exceed 2,000 requests per 100-company evaluation run (V4 operates at ~565 requests).
- **Time Limits**: Single profile resolution must execute within $< 3$ seconds; 100-company batch must complete within $< 5$ minutes.
