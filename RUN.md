# Signalpost Submission Execution Guide (RUN.md)

## Environment Requirements
- Python 3.12+
- `uv` package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `winget install astral-sh.uv`)
- `git-lfs` initialized (`git lfs install && git lfs pull`)

## Quick Setup
```bash
uv sync
```

---

## 🚀 Running the Production Pipeline (Run 10A / v10a-freeze)
The unified command executes the deterministic crawler, applies streaming HTTP decompression (gzip/deflate), validates identity gates, corroborates subpages, and emits terminal execution envelopes:

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

## 📊 Evaluation & Verification Commands

### 1. Independent 100-Company Ground Truth Audit
Audits against the stratified benchmark cohorts (operating large, operating small, operating unlisted, holding abstentions) with decoupled statutory vs external intelligence accounting:

```bash
uv run python scripts/evaluate_independent_ground_truth.py \
  --profiles out/v7_run10_profiles.jsonl \
  --envelopes out/v7_run10_envelopes.jsonl \
  --ground-truth data/ground-truth-100.jsonl \
  --output out/v7_run10_evaluation_report.json
```

### 2. Official Competition Rubric Evaluation (35/30/20/10/5)
```bash
uv run python scripts/evaluate_competition.py \
  --profiles out/v7_run10_profiles.jsonl \
  --envelopes out/v7_run10_envelopes.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --report out/v7_run10_batch_report.json \
  --output out/score.json
```

### 3. External Recall & Precision Evaluation
```bash
uv run python scripts/evaluate_external_recall.py \
  --profiles out/v7_run10_profiles.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --output out/recall.json
```

### 4. Adversarial Identity & Stress Test Suite
Verifies 10/10 adversarial defenses against name collisions, corporate shell hierarchies, sports clubs, and brand boundary leaks:

```bash
uv run python scripts/test_adversarial_identity.py
```

### 5. Full Unit & Regression Suite
```bash
uv run pytest tests/ -q
```

---

## ⚡ Operational Profile & Invariants
- **Outbound HTTP requests**: ~939 requests across 100 companies (Strict budget ceiling: 2,000 requests)
- **External API Cost**: **$0.00** (Zero reliance on commercial search APIs, paid LLM tokens, or credentialed services)
- **Identity Invariant**: **0 wrong-company publications** across all cohorts (100.0% precision target preserved)
- **Transport Safety**: Bounded streaming decompression protects against zip-bombs with hard byte limits
- **Terminal Contract**: 100/100 terminal envelopes emitted with 0 silent drops
