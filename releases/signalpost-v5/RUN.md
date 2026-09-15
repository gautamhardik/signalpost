# Signalpost Submission Execution Guide (RUN.md)

## Environment Requirements
- Python 3.12+
- `uv` package manager

## Quick Setup
```bash
uv sync
```

## Running the Competition Batch Pipeline
The unified command executes the deterministic crawler, applies adaptive opportunity scoring, validates identity gates, and emits validated terminal envelopes. It operates on any JSONL batch of Norwegian organisation numbers (whether 100 or 1,100+).

```bash
uv run python scripts/run_competition_batch.py \
  --organisations organisation-manifest.jsonl \
  --bulk brreg-enheter.csv \
  --profiles-output out/profiles.jsonl \
  --output out/envelopes.jsonl \
  --report out/run-report.json \
  --run-id submission-001 \
  --expected-count 1100 \
  --workers 16
```

## Validating Corpus & Contract Invariants
To verify 1:1 manifest-to-profile-to-envelope mapping, 100% terminal envelopes, and zero silent drops:

```bash
uv run python scripts/validate_submission_corpus.py \
  --manifest organisation-manifest.jsonl \
  --profiles out/profiles.jsonl \
  --envelopes out/envelopes.jsonl \
  --report out/run-report.json \
  --min-count 1000
```

## Running Automated Rubric Evaluation
To compute the official 35/30/20/10/5 score against the frozen benchmark:

```bash
uv run python scripts/evaluate_competition.py \
  --profiles evaluation/benchmark-100/profiles.jsonl \
  --envelopes evaluation/benchmark-100/envelopes.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --report evaluation/benchmark-100/run-report.json \
  --output out/score.json
```

## Running External Recall & Precision Evaluation
To audit weighted external recall ($\ge 60\%$) and external precision ($\ge 95\%$):

```bash
uv run python scripts/evaluate_external_recall.py \
  --profiles evaluation/benchmark-100/profiles.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --output out/recall.json
```

## Running Regression Test Suite
```bash
uv run pytest tests/ -q
```

## Operational Profile
- **Outbound HTTP requests**: ~600–790 requests per 100 companies (Ceiling: 2,000 requests)
- **API Cost**: $0.00 (Pure deterministic discovery & open sector registries)
- **Model Usage**: 0 token / 0 LLM cost for core identity & evaluation
- **Runtime**: ~18 minutes for 1,100 companies on 16 concurrent workers
