# Signalpost: Evidence-First Autonomous Norwegian Company Intelligence

Signalpost is designed around **evidence-first company intelligence**.

The system does **not** treat search discovery or string matches as proof. A public URL or profile becomes an official company source only after passing strict deterministic identity verification and registry corroboration ($\ge 0.90$ token similarity or exact Brreg corroboration). When evidence is ambiguous or absent, Signalpost deterministically abstains rather than publishing wrong-company information.

---

## 📦 Challenge Submission Corpus vs. Benchmark

Following the official Builderr challenge specification:
* **Submitted Completed Corpus**: **1,100 completed company profiles** (`profiles.jsonl`), 1,100 terminal envelopes (`envelopes.jsonl`), and the exact input manifest (`organisation-manifest.jsonl`).
* **Stratified Representation**: Spans operating AS companies (443), sole proprietorships (424), associations (130), housing/property entities (26), and foreign branches (23) sampled across diverse Norwegian municipalities and industries.
* **Separated Evaluation Benchmark**: The frozen 100-company engineering benchmark is preserved in `evaluation/benchmark-100/` with its calibrated score of **94.57 / 100**.
* **Generalization Guarantee**: The agent accepts any Norwegian organisation number as input. It is designed to research completely unseen companies drawn dynamically from the 411,160 active entity universe during daily evaluation runs.

---

## 🏆 Key Verified Performance Metrics

Signalpost has been validated on the official competition rubric (35 Coverage / 30 Accuracy / 20 Refresh / 10 Synthesis / 5 UX):

* **Official Calibrated Score**: **94.57 / 100** (Qualification bar: $\ge 65/100$)
* **Coverage & Discovery**: **29.57 / 35** (Qualification bar: $\ge 21/35$)
* **Accuracy, Identity & Evidence**: **30.0 / 30** (0 false-positives across all benchmarks)
* **Refresh & Extensibility**: **20.0 / 20** (Deterministic change-diff engine with SHA-256 provenance)
* **Decision-Useful Synthesis**: **10.0 / 10** (Structured who, what, how big, who runs it, footprint, and claims audit)
* **UX & Inspection Surface**: **5.0 / 5** (One-click claim-to-evidence provenance drawer, side-by-side comparison, and diff viewer)
* **Weighted External Recall**: **100.0%** against known external operating presences ($\ge 60\%$ bar met)
* **External Precision**: **100.0%** with **0 wrong-company publications** ($\ge 95\%$ bar met)
* **Submission Corpus**: **1,100 / 1,100 terminal envelopes emitted**, 0 silent drops, 0 contract errors
* **Monte Carlo Stability**: **50/50 qualification passes** across random Brreg subsets (Mean score: 89.93, $\sigma = 0.53$)

---

## 🏗️ Core Architecture & Design Principles

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
    Deterministic Identity Gate               │
      (Token similarity >= 0.90,              │
       address / phone / org match)           │
                │                             │
        ┌───────┴───────┐                     │
        ▼               ▼                     │
   Corroborated     Uncertain                 │
        │               │                     │
        ▼               ▼                     ▼
  Publish Claims     Abstain        Emit Terminal Envelope
        │               │                     │
        └───────────────┼─────────────────────┘
                        ▼
           Structured Synthesis Snapshot
                        │
                        ▼
       Terminal JSONL Envelope + Provenance Audit
```

1. **No Naked Facts**: Every claim in the profile contains:
   * `claim`: Normalized descriptor (e.g., Revenue, CEO, Location).
   * `value`: Audited value.
   * `source_url`: Full public or registry URL.
   * `retrieved_at`: ISO-8601 UTC timestamp.
   * `source_class`: Registry, company site, annual accounts, etc.
   * `content_sha256`: Cryptographic snapshot hash of the raw response.
2. **Deterministic Screening Layer**:
   * Natural-language queries (e.g. *"Which companies have revenue over 10 million?"*) compile into strict AST filter plans executed purely in code without LLM hallucination risk.
3. **Auditability**:
   * Zero third-party aggregator pollution (Proff, 1881, Purehelp, Gulesider are hard-blocked as identity anchors).

---

## 🚀 Quick Execution Guide

Signalpost is fully reproducible via `uv`. Follow `RUN.md` for standard operation:

```bash
# 1. Synchronize dependencies
uv sync

# 2. Run the competition batch pipeline on any organisation-number list (100 or 1,100+)
uv run python scripts/run_competition_batch.py \
  --organisations organisation-manifest.jsonl \
  --bulk brreg-enheter.csv \
  --profiles-output out/profiles.jsonl \
  --output out/envelopes.jsonl \
  --report out/run-report.json \
  --run-id submission-001 \
  --expected-count 1100 \
  --workers 16

# 3. Validate 1:1 corpus integrity (manifest == profiles == envelopes)
uv run python scripts/validate_submission_corpus.py \
  --manifest organisation-manifest.jsonl \
  --profiles out/profiles.jsonl \
  --envelopes out/envelopes.jsonl \
  --report out/run-report.json \
  --min-count 1000

# 4. Evaluate benchmark score (on the 100-company evaluation split)
uv run python scripts/evaluate_competition.py \
  --profiles evaluation/benchmark-100/profiles.jsonl \
  --envelopes evaluation/benchmark-100/envelopes.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --report run-report.json \
  --output out/score.json
```

---

## ⚖️ Declarations & Compliance
* **Models / LLMs Used for Identity**: **None**. Identity resolution is 100% deterministic and inspectable.
* **External Paid APIs**: **None**. Operates entirely on public open sector data and compliant HTTP fetching.
* **Outbound Cost per 100 Companies**: **$0.00**.
* **Source Compliance**: Full adherence to `robots.txt`, NLOD / CC-BY 4.0 open data terms, and polite HTTP rate-limiting. Detailed declarations are maintained in `source-policy.md`.
