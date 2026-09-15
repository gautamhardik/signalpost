# Signalpost V5 Coverage Gap Analysis Report (Phase 2)

## 1. Executive Summary

This report analyzes the coverage across all 100 benchmark companies in `out/benchmark-100-v5-profiles.jsonl` to pinpoint the exact source of missing coverage points.

### Aggregate Coverage Gaps (100 Companies)

| Evidence Dimension | Present Count | Missing Count | Coverage % | Opportunity Assessment |
| :--- | :--- | :--- | :--- | :--- |
| **Financial Accounts** | 100 / 100 | 0 | **100.0%** | Saturated (All 100 entities possess submitted financial data) |
| **Roles & Key People** | 100 / 100 | 0 | **100.0%** | Saturated (All 100 entities possess registered roles) |
| **Subunits / Workplaces**| 82 / 100 | 18 | **82.0%** | Near ceiling (The 18 missing are mostly holding companies with 0 employees) |
| **Registered Employees**| 52 / 100 | 48 | **52.0%** | Structural (Holding companies and housing cooperatives have 0 registered staff) |
| **Official Websites** | 14 / 100 | 86 | **14.0%** | **Targetable Gap**: 10 missing in `brreg_website_present` due to redirect/blocking/strict matching |
| **Social Footprints** | 8 / 100 | 92 | **8.0%** | Dependent on verified company websites & primary pages |
| **Hiring Signals** | 3 / 100 | 97 | **3.0%** | Present only on verified websites with active career sections |
| **News / Press Signals** | 3 / 100 | 97 | **3.0%** | Present only on verified websites with news/blog archives |

---

## 2. Category Stratification Breakdown

| Benchmark Category | Total Entities | Verified Websites | Verified Subunits | Verified Social | Notes & Gap Causes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`brreg_website_present`** | 20 | **10** (50%) | 19 (95%) | 5 (25%) | **The primary gap**: 10 companies have listed websites in Brreg that failed publication (2 blocked, 3 source error, 5 strict match failure). |
| **`operating_large_no_web`** | 20 | **3** (15%) | 20 (100%) | 3 (15%) | Discovery found 3 websites; 17 truly have no registered or discoverable independent web domain. |
| **`operating_small_no_web`** | 25 | **1** (4%) | 25 (100%) | 0 (0%) | 1 website discovered; 24 have zero independent web presence. |
| **`holding_companies`** | 15 | **0** (0%) | 0 (0%) | 0 (0%) | Correctly abstained (passive asset holdings with 0 employees and no public footprint). |
| **`housing_entities`** | 10 | **0** (0%) | 10 (100%) | 0 (0%) | Correctly abstained from websites; 100% have verified physical property subunits. |
| **`other_forms_no_web`** | 10 | **0** (0%) | 8 (80%) | 0 (0%) | Enk/Nuf forms; zero public website footprint exists. |

---

## 3. The 5.43 Missing Coverage Points Breakdown

In `evaluate_competition.py`:
$$\text{Coverage Score} = 35.0 \times \left(0.5 \times \text{Company Recall} + 0.5 \times \text{Claim Recall}\right)$$
* **Company Recall**: $\min(1.0, 82 / 35) = 1.0 \implies 17.50 / 17.50$ points.
* **Claim Recall**: $\min(1.0, 17.24 / 25.0) = 0.6896 \implies 12.07 / 17.50$ points.
* **Gap**: $17.50 - 12.07 = 5.43$ points.

### Decision Rule for V5.1
The only legitimate way to increase claim recall without risking wrong-company errors is:
1. Recover legitimate registered websites in `brreg_website_present` that encountered domain redirects or www canonicalization issues (e.g. `autobjorn.no`, `goeran.no`).
2. Extract rich structured metadata from verified websites (contact email, phone, visiting address, organization number corroboration).
3. Do NOT relax identity thresholds or hallucinate websites on holding/real estate entities.
