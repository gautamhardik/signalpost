> **Official Status**: **V6 CANDIDATE CHAMPION**  
> **Git Tag**: `v6-candidate`  
> **Commit SHA**: `c161bde`  
> **Previous Baseline**: `v5-final` (`515753f`)  
> **Independent GT-100 Website Recall**: **64.0% (32/50)** (vs. 58.0% V5 baseline, **+6.0% lift**)  
> **External Precision**: **100.0% (0 Wrong Entities across all evaluated cohorts)**  
> **Adversarial Suite**: **10 / 10 passed**  
> **Pytest Suite**: **115 / 115 passed**  

---

## 1. Reproducibility & Environment Record

- **Runtime**: Python 3.12+ / 3.13
- **Environment & Dependency Manager**: `uv`
- **Execution Command**: Always prefixed with `uv run`
- **Universe Identity Engine**: `data/company_universe_411k.db` (Indexed SQLite cache, 411,160 Norwegian BRREG entities)
- **External API & Model Cost**: **$0.00 / 0 LLM tokens** for core identity verification and claim emission (pure deterministic discovery & verified public registers)
- **Request Budget**: 806 requests / 2,000 budget on GT-100 benchmark (zero request budget inflation).

---

## 2. Submission Artifact Hashes (SHA-256)

All files in the submission bundle have been verified and sealed under V6:

| File | Size (Bytes) | SHA-256 Checksum |
| :--- | :---: | :--- |
| `submission/organisation-manifest.jsonl` | 299,268 | `27c802a4febe757b3cb76a63bd3222abe6a96f5fa2bd365d9e086f1c3fe3f3e6` |
| `submission/profiles.jsonl` | 10,680,230 | `e361832dfd1e78010ea36274170fd518c265ce8ee159b048403337cffcbdc6d5` |
| `submission/envelopes.jsonl` | 11,752,248 | `090fb933b9165288426f76b1ebb3fbbc051b7ba29ac3fc80c98cffa5db3c9eca` |
| `submission/run-report.json` | 1,042 | `2e0c62986dcdc2e8ad1500b170e8f205be81873813fbf44f2766538eaf98bdea` |

---

## 3. Multi-Layer Regression Gate Summary (All Green)

```text
[PASS] Unit & Contract Suite (tests/)          -> 115 passed, 5 subtests passed (9.01s)
[PASS] Adversarial Identity Suite (scripts/)    -> 10/10 passed, 0 collisions, 100.0% precision
[PASS] Refresh & Snapshot Replay                -> 100% precision, 100% recall, 100% idempotent
[PASS] Network & SSRF Security Audit           -> 4/4 security & terminal contract tests passed
[PASS] Independent Ground Truth (100 Cos)       -> 64.0% website recall (+6.0%), 0 wrong entities
[PASS] Final Submission Corpus Validation       -> 1,100 / 1,100 terminal envelopes, 0 silent drops
```

---

## 4. Rollback Reference

The immutable baseline `v5-final` (commit `515753f`) remains untouched in Git history as the emergency rollback reference.
