# Signalpost Submission Execution Guide (RUN.md)

## Environment Requirements
- Python 3.12+
- `uv` package manager

## Quick Setup
```bash
uv sync
```

## Running the Competition Batch Pipeline
The unified command executes the deterministic crawler, applies adaptive opportunity scoring, validates identity gates, and emits validated terminal envelopes.

```bash
uv run python scripts/run_competition_batch_v2.py \
  --organisations benchmark-100.jsonl \
  --bulk brreg-enheter.csv \
  --profiles-output out/profiles.jsonl \
  --output out/envelopes.jsonl \
  --report out/run-report.json \
  --run-id submission-001 \
  --expected-count 100 \
  --workers 4
```

## Running Automated Evaluation
To compute the official 35/30/20/10/5 score against the frozen benchmark:

```bash
uv run python scripts/evaluate_competition.py \
  --profiles out/profiles.jsonl \
  --envelopes out/envelopes.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --report out/run-report.json \
  --output out/score.json
```

## Running External Recall & Precision Evaluation
To audit weighted external recall ($\ge 60\%$) and external precision ($\ge 95\%$):

```bash
uv run python scripts/evaluate_external_recall.py \
  --profiles out/profiles.jsonl \
  --ground-truth data/discovery-ground-truth.jsonl \
  --output out/recall.json
```

## Running Unit & Regression Tests
```bash
uv run pytest tests/ -q
```

## Expected Cost & Resource Profile
- **Outbound HTTP requests**: ~790 requests per 100 companies (Ceiling: 2,000 requests)
- **Runtime**: ~7-8 minutes per 100 companies on 4 concurrent workers
- **API Cost**: $0.00 (Pure deterministic discovery & public open registries)
- **Model Usage**: 0 token / 0 LLM cost for core identity & evaluation
