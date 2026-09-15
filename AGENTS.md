# Signalpost Starter Kit — Agent Guidelines & Instructions

> **Permanent Rules & Operational Constraints for Antigravity Agents**  
> **Model Default**: Gemini 3.8 Flash (`thinking: low`)  
> **Goal**: 100/100 Benchmark Precision, Zero False Entities, Strict Resource Budgets.

---

## 1. Project Overview & Context

- **Repository**: `signalpost-starter-kit`
- **Competition**: Builderr Signalpost Challenge (Closes October 21, 2026).
- **Mission**: High-recall exact-company intelligence agent covering 411,160 Norwegian BRREG companies within 45 minutes and 2,000 requests.
- **Current Score**: **100.00 / 100.0** (V4 Champion: 35/35 Coverage, 30/30 Accuracy, 20/20 Refresh, 10/10 Synthesis, 5/5 UX, 0 wrong entities).
- **Authoritative Identity Source**: The Norwegian Business Register (Brønnøysundregistrene / BRREG). `data/company_universe_411k.db` is our local indexed high-speed SQLite cache of this universe.

---

## 2. Tech Stack & Environment

- **Runtime**: Python 3.12+ managed via `uv`
- **Virtualenv**: `.venv`
- **Database**: SQLite3 (`data/company_universe_411k.db`) with WAL mode and B-tree indexes
- **Dependencies**: `httpx`, `beautifulsoup4`, `pydantic`, `pytest`, `duckduckgo-search`
- **Execution Command Format**: Always prefix with `uv run`

---

## 3. Directory Structure

```text
signalpost-starter-kit/
├── AGENTS.md                  # This file: rules, constraints, prompt template
├── ARCHITECTURE.md            # System architecture, data flow, component design
├── TASK_STATE.md              # Current task status, completed milestones, decisions
├── data/
│   ├── company_universe_411k.db  # 411,160 indexed BRREG entities (Indexed cache)
│   ├── enhetsregisteret.json.gz  # Raw BRREG upstream dump
│   ├── sample-companies.csv      # Initial test corpus
│   └── underenheter.json.gz      # Raw BRREG sub-units dump
├── src/
│   ├── batch.py               # Batch processor, pipeline coordinator, CLI
│   ├── discovery.py           # Domain guessing, subunit bridge, search fallback
│   ├── fetcher.py             # Rate-limited HTTP client, caching, budgets
│   ├── identity.py            # Strict Norwegian entity verification gate
│   ├── models.py              # Pydantic schemas (Profile, Envelope, Claim, etc.)
│   ├── pipeline.py            # Per-company multi-stage research worker
│   ├── research.py            # Evidence extraction & claim provenance synthesis
│   └── universe.py            # SQLite fast lookup engine (0.4ms / entity)
├── tests/                     # 112+ unit and integration tests
├── scripts/                   # Benchmarking, auditing, and corpus generation scripts
└── submission/                # 1,100 verified profiles, envelopes, and manifest
```

---

## 4. Protected Files — DO NOT EDIT Arbitrarily

1. **`data/company_universe_411k.db`**: Static frozen SQLite universe. Do NOT rebuild unless instructed.
2. **`submission/*.jsonl`**: Competition submission bundle. Never overwrite without explicit user authorization and a full validation pass.
3. **`src/identity.py` (Identity Gate Thresholds)**: Never lower the confidence threshold below `0.90`. Zero wrong entities is non-negotiable.

---

## 5. Coding Conventions & Best Practices

- **Strict Typing**: Use type annotations everywhere (`pydantic` models for data structures).
- **Defensive HTTP**: All network calls must pass through `fetcher.py` to respect request budgets and rate limits.
- **Provenance Integrity**: Every single `Claim` emitted into an `Envelope` MUST have a verifiable `source_url`, `timestamp`, and `evidence_quote`. Never fabricate or synthesize facts without evidence.
- **Minimal Diffs**: Make the smallest change that satisfies the requirements. Prefer targeted patches over broad refactors.
- **Zero Unnecessary Dependencies**: Do not install new packages unless strictly required and approved.

---

## 6. Important Commands

Always run commands via `uv run`:

```bash
# Run test suite (quick)
uv run pytest tests/ -o pythonpath=src -q

# Run benchmark evaluation
uv run python scripts/evaluate_benchmark.py --dataset benchmark-100.jsonl --profiles out/benchmark-profiles.jsonl

# Validate submission bundle integrity
uv run python scripts/validate_submission.py submission/

# Check SQLite universe integrity
uv run python -c "from universe import get_universe_connection; conn=get_universe_connection(); print('Total entities:', conn.execute('SELECT COUNT(*) FROM companies').fetchone()[0])"
```

---

## 7. Mandatory Antigravity Agent Protocol

When prompted with a task, adhere to the **Quota Optimization Standard**:

1. **Check this file (`AGENTS.md`) and `TASK_STATE.md`** first.
2. **Never explore the whole repo** with search tools if the target component is already known.
3. **Keep modifications strictly inside `SCOPE`**.
4. **If you find an unrelated bug, report it in your final response—do NOT fix it.**
5. **Run targeted tests only** during implementation; run the full suite only before concluding.
6. **STOP** immediately once acceptance criteria (`DONE WHEN`) are met.
