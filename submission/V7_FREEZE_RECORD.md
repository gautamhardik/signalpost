# Signalpost V7 — Submission Freeze Record

> **Branch**: `v7-signalpost-evidence-product`
> **Freeze Date**: 2026-09-26T05:46:44Z
> **Status**: PROMOTED — PENDING FINAL TAG (`v7-final`)

---

## 1. Promoted Artifacts

| Artifact | Lines | SHA-256 (full) | Size |
|---|---|---|---|
| `submission/profiles.jsonl` | 1,100 | `81822a25dc2e4464378874324d970e95b85d55623153cd0423a5d16ac660685b` | 1,100 records |
| `submission/envelopes.jsonl` | 1,100 | `a9df4e8fff4220a349711bc9a3c45c83efcd5bbc84fb7977b76bdec882cd40b1` | 1,100 records |
| `submission/organisation-manifest.jsonl` | 1,100 | `27c802a4febe757b3cb76a63bd3222abe6a96f5fa2bd365d9e086f1c3fe3f3e6` | unchanged from V6 |
| `submission/viewer.html` | — | `e1d00f79e00a23170be73e3a3cb818c8faf11234d6b4fea32b7e0b21a92827b2` | 2,624,734 bytes |

---

## 2. V6 Backup

Original V6 artifacts preserved in `submission/v6-backup/`:
- `submission/v6-backup/profiles.jsonl`   sha256=`e361832dfd1e78010ea36274170fd518c265ce8ee159b048403337cffcbdc6d5`
- `submission/v6-backup/envelopes.jsonl`  sha256=`090fb933b9165288426f76b1ebb3fbbc051b7ba29ac3fc80c98cffa5db3c9eca`

---

## 3. Dry-Run Execution Record

| Metric | Value |
|---|---|
| **Run ID** | `v7-dryrun-1100` |
| **Started at** | `2026-09-25T18:29:01.000022Z` |
| **Completed at** | `2026-09-25T18:46:27.935287Z` |
| **Expected count** | 1,100 |
| **Emitted envelopes** | 1,100 |
| **Silent drops** | 0 |
| **Total HTTP requests** | 6,273 |
| **Total bytes fetched** | 55,349,327 |
| **p50 latency (ms)** | 937 |
| **p95 latency (ms)** | 2187 |

---

## 4. V7 Capabilities vs V6

| Capability | V6 | V7 |
|---|---|---|
| BRREG statutory identity | YES | YES |
| Website discovery & gate | YES | YES |
| Social profile discovery | YES | YES |
| Dated news observations | NO | YES (code) |
| Strict job observations (Type A/B/C) | NO | YES (code) |
| ATS external following | NO | YES (code) |
| EvidenceRecord with SHA-256 | PARTIAL | YES |
| `external_footprint` block in evidence | NO | YES (1,100 companies) |
| Deterministic synthesis block | NO | YES (1,100 envelopes) |
| Activity block (jobs/news counts) | NO | YES (1,100 envelopes) |
| Snapshot store & refresh diffs | NO | YES (code) |
| Standalone company viewer | NO | YES (`submission/viewer.html`) |

---

## 5. Validation Matrix

| Check | Result |
|---|---|
| Exact 1,100 profiles | PASS |
| Exact 1,100 envelopes | PASS |
| All envelopes state='complete' | PASS |
| Zero duplicate org numbers | PASS |
| Zero silent drops | PASS |
| Org numbers match manifest | PASS |
| All envelopes have synthesis block | PASS (1,100/1,100) |
| All envelopes have activity block | PASS (1,100/1,100) |
| SHA-256 hashes match dry-run source | PASS |

---

## 6. V6 vs V7 Material Differences

| Dimension | V6 | V7 | Change |
|---|---|---|---|
| profiles.jsonl size | 10,680,230 B | 13,211,838 B | +2,531,608 B (+23.7%) |
| envelopes.jsonl size | 11,752,248 B | 15,655,635 B | +3,903,387 B (+33.2%) |
| synthesis blocks | 0 | 1,100 | **+1,100** |
| activity blocks | 0 | 1,100 | **+1,100** |
| external_footprint key | 0 | 1,100 | **+1,100** |
| evidence items total | 8,800 | 9,900 | **+1,100** |
| companies with news_count>0 | 0 | 6 | +6 |
| companies with jobs_count>0 | 0 | 2 | +2 |
| viewer artifact | None | viewer.html (2,624,734 B) | **NEW** |

---

## 7. Next Steps

- [ ] Run full test suite: `uv run pytest tests/ -o pythonpath=src -q`
- [ ] Run adversarial identity suite: `uv run python scripts/test_adversarial_identity.py`
- [ ] Inspect submission diff with user
- [ ] Tag `v7-final` only after explicit user authorization

**STATUS: PROMOTED, AWAITING FINAL FREEZE AUTHORIZATION**
