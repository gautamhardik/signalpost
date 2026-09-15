# Signalpost Evaluator & Metrics Audit Report (Phase 1)

## 1. Metric Alignment & Denominator Verification

This audit analyzes `evaluate_competition.py` and `evaluate_external_recall.py` line-by-line to ensure local metrics strictly reflect the official competition criteria rather than artificially inflated numbers.

| Metric | How Calculated | Ground Truth / Denominator | V5 Value | Official Alignment | Assessment & Notes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Company Recall** | $\min\left(1.0, \frac{\text{unique\_discovered}}{\text{target\_discoverable}}\right)$ | `target_discoverable = 35` (based on ~35-40% realistic external footprint rate in random Norwegian entities) | **1.0 (100%)** | ⚠️ **Calibrated Proxy** | 82 entities have external footprints (subunits) and 14 have websites. Total unique discovered = 82, which exceeds 35, yielding 1.0. |
| **Claim Recall** | $\min\left(1.0, \frac{\text{avg\_claims\_per\_profile}}{\text{expected\_claims\_per\_profile}}\right)$ | `expected_claims = 25.0` claims/company (registry: 8, roles: 4, financials: 6, website: 3, footprint: 4) | **0.6896 (68.96%)** | ✅ **Strict Empirical** | V5 produces an average of 17.24 supported claims/company (1,724 total). This is the source of the missing coverage points ($35 \times 0.5 \times (1 - 0.6896) = 5.43$ pts). |
| **External Recall** | Weighted sum across 5 dimensions: website (0.35), social (0.25), hiring (0.15), news (0.10), subunits (0.15) | 35 companies from `data/discovery-ground-truth.jsonl` | **100.0%** (weighted on active footprints) | ⚠️ **Conditional Denominator** | For entities with no website in ground truth (all 35 in the sample), finding subunits satisfies recall. When tested against known websites, recall is strictly measured against confirmed domains. |
| **External Precision** | $\frac{\text{audited\_observations} - \text{wrong\_entity}}{\text{audited\_observations}}$ | 115 published external observations (websites, social links, subunits, site activity) | **100.0%** (0 false-positives) | ✅ **Exact & Audited** | Strictly requires `exact_entity = true` and `identity_proof` token match $\ge 0.90$ or Brreg corroboration. 0 wrong-company publications. |
| **Contract Validation** | Checks `emitted == expected` & all terminal | 100 benchmark input entities | **100 / 100**, 0 silent drops | ✅ **Strict Match** | Guaranteed compliance with the competition submission contract. |
| **Request Ceiling** | Physical outbound HTTP requests | 2,000 request ceiling per 100 companies | **791 / 2,000** | ✅ **Physical Count** | Physical wire requests verified; 1,209 request surplus available. |

---

## 2. Line-by-Line Code Findings

### `scripts/evaluate_competition.py`
1. **Coverage Formulation**:
   ```python
   coverage_score = round(35.0 * (0.5 * company_recall_rate + 0.5 * claim_recall_rate), 2)
   ```
   * Company recall is saturated ($1.0 \times 17.5 = 17.50$).
   * Claim recall is $0.6896 \times 17.5 = 12.07$.
   * Total coverage = $17.50 + 12.07 = 29.57 / 35.0$.
   * **Exact explanation of the missing 5.43 points**: The remaining 5.43 points can *only* be unlocked by increasing the average density of verified, supported claims per profile towards the target 25 claims/company.

2. **Deduplication**: Duplicate observations for the same URL or platform are filtered in `aggregate_footprint()`. Observations without exact entity proof are flagged as errors.

### `scripts/evaluate_external_recall.py`
1. **Denominator Construction**:
   * For entities with known websites (`has_known_web == True`), each dimension contributes proportionally.
   * In `data/discovery-ground-truth.jsonl`, all 35 entities belong to the `no_website_found` stratum (specifically curated to test false-positive resistance on small operating AS entities).
   * For these 35 companies, finding verified Brreg subunits (`has_subunits`) satisfies the external operating footprint requirement without hallucinating a fake website.
   * To prevent metric overfitting, the ground-truth benchmark must also include companies with verified active websites.
