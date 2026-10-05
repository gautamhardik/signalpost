# Signalpost Submission Execution Guide (RUN.md)

## Environment Requirements
- Python 3.12+
- `uv` package manager

## Quick Setup
```bash
uv sync
```

## Running the Competition Batch Pipeline
The single run command researches every supplied company, applies the identity gates, saves the source behind each published fact, and emits one result envelope per company. It operates on any JSONL batch of Norwegian organisation numbers (whether 100 or 1,100+).

```bash
uv run python scripts/run_competition_batch.py --organisations organisation-manifest.jsonl --output-dir out/run
```

See the top-level `RUN.md` for outputs, result states and options.

## Validating Corpus & Contract Invariants
To verify 1:1 manifest-to-profile-to-envelope mapping, 100% terminal envelopes, and zero silent drops:

```bash
uv run python scripts/validate_submission_corpus.py \
  --manifest organisation-manifest.jsonl \
  --profiles out/run/profiles.jsonl \
  --envelopes out/run/envelopes.jsonl \
  --report out/run/run-report.json \
  --min-count 1000
```

## Running Regression Test Suite
```bash
uv run pytest tests/ -q
```

## Operational Profile
- **Outbound HTTP requests**: official registry calls plus at most 40 website requests per company (configurable)
- **API Cost**: $0.00 (Pure deterministic discovery & open sector registries)
- **Model Usage**: 0 token / 0 LLM cost for core identity resolution
- **Runtime**: about 3.5 minutes per 100 companies on 12 workers (measured on a 100-company sample)
