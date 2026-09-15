# Signalpost — Task State & Progress Tracker

> **Permanent Operational Log & Project Status Record**  
> **Active Baseline**: V4 Champion (Score: 100.00 / 100.0)  
> **Last Verified**: 2026-09-15

---

## 1. System Status Snapshot

| Dimension | Baseline V1 | V2 (SQLite 411k) | V3 (Smart Discovery) | V4 Champion |
| :--- | :---: | :---: | :---: | :---: |
| **Total Score** | 94.57 | 94.70 | 94.82 | **100.00 / 100.0** |
| **Coverage (35)** | 29.57 | 29.70 | 29.82 | **35.00 / 35.0** |
| **Accuracy (30)** | 30.00 | 30.00 | 30.00 | **30.00 / 30.0** |
| **Refresh (20)** | 20.00 | 20.00 | 20.00 | **20.00 / 20.0** |
| **Synthesis (10)** | 10.00 | 10.00 | 10.00 | **10.00 / 10.0** |
| **UX (5)** | 5.00 | 5.00 | 5.00 | **5.00 / 5.0** |
| **Wrong Entities** | 0 | 0 | 0 | **0 (Zero Tolerance)** |
| **External Precision** | 100% | 100% | 100% | **100%** |
| **Outbound Requests** | 712 | 667 | 541 | **565 / 2,000 budget** |
| **Avg Claims / Profile** | 17.1 | 17.3 | 17.6 | **25.15 (Saturated)** |

---

## 2. Completed Milestones

- [x] **Mission 1: Universe Ingestion & Indexing**
  - Downloaded and parsed full Norwegian registry dumps (`enhetsregisteret.json.gz`, `underenheter.json.gz`).
  - Indexed all 411,160 entities into `company_universe_411k.db` with SQLite B-tree indexes.
  - Validated 0.43 ms single lookup latency and ~45 ms for 1,000 lookups.

- [x] **Mission 2: V2 Engine Runtime Integration**
  - Replaced linear CSV/GZ scanning in `batch.py` and `pipeline.py` with indexed SQLite lookup.
  - Verified runtime compatibility with arbitrary out-of-corpus companies across Norway.

- [x] **Mission 3: Multi-Factor Discovery & Candidate Ranking**
  - Implemented Layer 1.5 domain extraction from contact emails.
  - Implemented Layer 1.8 deterministic domain slug generator.
  - Tightened token-boundary scoring in search ranking to reduce network queries by 24%.

- [x] **Mission 4: Subunit Bridge & Claim Provenance Saturation (V4 Champion)**
  - Implemented `Subunit & Brand Bridge` in `discovery.py` to link operating brand websites to holding entities.
  - Added Subunit workplace address corroboration to `assess_website_identity` in `identity.py`.
  - Expanded statutory claim emission in `research.py` (accounting obligations, liquidation status, NACE classifications, verified domain titles), lifting claim density to 25.15 claims/profile.
  - **Achieved perfect 100.00 / 100.0 score** on `benchmark-100.jsonl`.
  - Built candidate yield dataset (`scripts/evaluate_candidate_yield.py` $\to$ `out/candidate-relations-dataset.jsonl`).
  - Verified submission bundle (1,100 profiles, 1,100 envelopes, 1,100 manifest items).

- [x] **Mission 5: Antigravity Quota Optimization Standard**
  - Codified permanent repo configuration: `AGENTS.md`, `ARCHITECTURE.md`, `TASK_STATE.md`.
  - Locked agent configuration to Gemini 3.8 Flash (`thinking: low`).

---

## 3. Current Task

- **Status**: Complete & Locked.
- **Active Champion**: V4 pipeline code is frozen as the competitive standard.

---

## 4. Next Tasks / Backlog (Optional Maintenance)

- [ ] Run regular verification sanity checks against newly added sample entities if competition updates test fixtures.
- [ ] Monitor Builderr challenge portal for any revised evaluator rules prior to the October 18, 2026 revision cutoff.
- [ ] Maintain submission bundle backups in `submission/`.

---

## 5. Known Decisions & Architectural Invariants

1. **BRREG is the Authoritative Identity Source**: `company_universe_411k.db` is an indexed local cache of the official public registry, ensuring 100% compliance with data policies.
2. **Zero False Entity Policy**: Identity confidence must be $\ge 0.90$. We prefer returning zero external website data over linking the wrong legal entity.
3. **No Machine Learning Hallucination**: All synthetic facts must be grounded in direct textual quotes from authenticated source pages.
4. **Agent Quota Efficiency**: Agents must use Gemini 3.8 Flash with Low Thinking by default, with scoped diffs, explicit acceptance criteria, and no broad whole-repo exploration.
