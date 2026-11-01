# Project Chronicle: Signalpost

Authoritative historical record of architecture, experiments, debugging sessions, verification outcomes, and operational decisions.

---

## 2026-11-01: Zero External Footprint Root Cause Resolution, Deterministic Search Fallback, and Identity Recall Upgrades

### Request & Problem Statement
Feedback from competition evaluator Soham Sinha indicated:
1. **Strong Core Performance**: Narrative synthesis and the offline provenance viewer scored high marks for clear company summaries, sizes with percentage trends, executive leadership, and local snapshot provenance.
2. **Critical Discovery Gap**: Batch runs returned official Brreg registry facts, but **zero external company websites, social profiles, news articles, or hiring signals**.
3. **Financial Statement Precision**: Failed financial lookups must explicitly state lookup failure rather than claiming revenue is "pending or not filed."
4. **Core Evaluator Mandate**: (1) Search for each company's own website and social pages, keeping a page only if it names the company or shows its company number ("A blank beats a wrong match"); (2) do the same for recent news and open jobs.

### Empirical Diagnostics & Root Cause Analysis
A live diagnostic run on a representative 3-company batch (`EQUINOR ASA` [923609016], `TOMRA SYSTEMS ASA` [927124238], `BEWE SLEDS AS` [827467782]) isolated the 4 underlying bottlenecks that caused zero external facts:
1. **Uncaught `http.client.IncompleteRead` on Chunked Responses**:
   Large corporate websites like `equinor.com` stream responses using chunked HTTP/1.1 transfer encoding. When truncated by the buffer cap or server termination, `urllib.request` raises `http.client.IncompleteRead`. Unhandled, this crashed the fetcher and marked the website `failed`.
2. **Premature `EOFError` on Decompression of Partial Gzip Streams**:
   Handling partial byte streams exposed secondary `EOFError` crashes when `gzip.decompress` reached a stream without a trailing gzip checksum.
3. **Single-Token Identity Gate Gatekeeper Trap (`len(core) == 1`)**:
   Companies like `EQUINOR ASA` have core legal tokens reduced to `['equinor']`. While `equinor.com` is registered in Brreg, its modern JavaScript-rendered homepage yielded <100 characters of raw HTML main text (`len == 26`), failing `substantive_homepage` and demoting the authentic domain to score 0.3.
4. **Corporate Stem Matching and `.com` TLD Rejection**:
   Companies like `TOMRA SYSTEMS ASA` on `tomra.com` failed because `.com` domains were not considered `named_domain` and generic corporate suffixes (`SYSTEMS`) were not stripped from the stem comparison.
5. **Inactive Search Fallback (`--search-endpoint` Defaulting to `None`)**:
   In the competition environment, `--search-endpoint` was not passed, skipping search entirely when domain candidate probing missed. Companies without active websites (e.g., `BEWE SLEDS AS`) were denied discovery of their verified Facebook and Instagram presences.
6. **Financial Status Wording**:
   The placeholder `"annual accounts revenue pending or not filed"` did not distinguish true unfiled accounts from registry lookup errors (`status == "failed"`).

### Actions Performed & Files Changed
1. **`src/norway_company_agent/research.py`**:
   - Replaced `"annual accounts revenue pending or not filed"` with explicit status handling: distinguishes `fin_status == "failed"` (`"Financial lookup failed; registered with {emp_count} employees."`), `fin_status == "blocked"`, and unfiled accounts (`"annual accounts not filed"`).
   - In `_what_is_unknown`, emitted state `"failed"` with `"Official annual accounts lookup failed."` when `fin_rec.status == "failed"`.
   - Populated `claim_level_narrative_examples` with explicit failure receipts.
   - Updated `generate_deterministic_company_summary` and `synthesize_company_intelligence` to surface verified social profiles discovered via search when no website is available.
2. **`src/norway_company_agent/website.py`, `site_sources.py`, `http.py`**:
   - Handled `http.client.IncompleteRead` across all network read loops (`fetch_website`, `_fetch_secondary_page`, `_robots_allowed`, `_fetch_document`, and `fetch_json`), capturing `exc.partial` bytes safely.
   - Enhanced `safe_decompress_body` with `zlib.decompressobj(16 + zlib.MAX_WBITS)` fallback to safely decompress partial gzip payloads without `EOFError`.
3. **`src/norway_company_agent/identity.py`**:
   - Robust `legal_form` extraction deriving from profile, registry codes, or legal name suffixes (`ASA`/`AS`).
   - Enhanced `stem_matches` with generic tail stripping (`systems`, `group`, `holding`, `solutions`, etc.).
   - Extended `named_domain` to accept `.com` domains for `AS`/`ASA` entities with length >= 4.
   - Permitted subpage OrgNr recognition (`compact_candidate`).
   - Patched single-token identity evaluation (`len(core) == 1`) to allow `(substantive_homepage or (substantive_site and registry_domain_match))`, enabling authentic corporate websites with multi-page crawls to verify cleanly.
4. **`src/norway_company_agent/discovery.py`**:
   - Implemented `search_lite_duckduckgo(query, timeout=3.5)`: keyless, zero-cost web search returning structured items and raw HTML bytes for SHA-256 evidence snapshotting.
   - Implemented `SearchCircuitBreaker`: in-memory caching and failure threshold (3 consecutive failures trip 60s cooldown) to ensure zero batch hangs or slowdowns.
   - Prioritized exact legal name `f'"{name}"'` in `build_flexible_company_search_queries` to surface first-party corporate and social pages.
5. **`src/norway_company_agent/adapters/sources.py`**:
   - Updated `SocialProfilesAdapter` to publish verified social profiles discovered via search (`discovered_social_links`) with full identity proofs (`score >= 0.90`) and SHA-256 evidence snapshot hashes.
6. **`scripts/run_competition_batch.py`**:
   - Integrated built-in search fallback into `research_website` when `--search-endpoint` is None and domain probing does not find a publishable site.
   - Persisted raw search HTML into the `EvidenceStore` with cryptographic SHA-256 hashes.
   - Fed search-discovered social candidates through `assess_social_identity` before attaching them to the profile.

### Verification Results
1. **Pytest Unit Test Suite**:
   - **141 / 141 passed** in 1.97s across all modules (`test_activity`, `test_discovery`, `test_history`, `test_jobs`, `test_recall_signals`, `test_review_fixes`, `test_synthesis_workspace`, `test_website_decompression`).
2. **Adversarial Identity Stress Suite (Mission 5D)**:
   - **10 / 10 passed** with **100.0% precision** and **0 wrong-company publications** across identity collisions, holding boundaries, parked pages, and sports clubs.
3. **Live 3-Company Verification Batch (`run_competition_batch.py`)**:
   - `input_count`: 3, `emitted_envelopes`: 3, `failed_companies`: 0.
   - `verified_websites`: 2 (`equinor.com` and `tomra.com`).
   - `companies_with_social_profiles`: 3 / 3 (100.0%)!
   - `companies_with_job_postings`: 1 (3 job postings).
   - `companies_with_hiring_signal`: 1.
   - `companies_with_dated_news`: 2 (64 dated news items).
   - `observations_with_source_snapshot`: **88 / 88 (100.0% Cryptographic SHA-256 Provenance)**.
   - `validation.passed`: **True** (zero silent drops, all terminal states).

### Lessons Learned & Invariants
- **Website Gate as Chokepoint**: Secondary adapters (`SocialProfilesAdapter`, `SiteActivityAdapter`, `HiringAdapter`, `SiteNewsAdapter`) depend on a publishable website. By allowing `SocialProfilesAdapter` to consume identity-gated search discoveries (`score >= 0.90`), companies with only social footprints (e.g. niche sporting goods manufacturers) gain full, verified digital representation.
- **Single-Word Company Names on Modern Stacks**: High-market-cap enterprises frequently render homepages with clientside frameworks, leaving minimal raw body text on the root URL. Verifying `substantive_site` across crawled subpages when the domain is registry-matched prevents false rejections of flagship corporations.
- **Provenanced Zero-Cost Search**: Zero external paid APIs are needed when keyless endpoints (DuckDuckGo Lite) are backed by circuit breakers and store snapshots directly into the evidence repository.
