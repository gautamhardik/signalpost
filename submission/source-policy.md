# Signalpost Source Policy & Data Governance

## 1. Compliance & Principles
Signalpost operates strictly under legal and responsible discovery practices:
1. **Robots.txt & Terms Adherence**: Signalpost strictly respects `robots.txt` disallow instructions and HTTP 429/403 status codes. Blocked targets gracefully produce `blocked_robots` or `blocked_policy` terminal states rather than violating access policies.
2. **Third-Party Directory Blocking**: High-risk business directories (Proff, Purehelp, 1881, Gulesider, Companywall) are hard-blocked as primary discovery anchors to prevent data pollution and third-party scraping violations.
3. **Deterministic Identity Gate**: External company pages (websites, LinkedIn, Facebook, Instagram) are only linked if corroboration passes an exact entity match ($\ge 0.90$ token similarity or registered Brreg corroboration).
4. **No Naked Facts**: Every published claim maintains complete cryptographic and provenance metadata:
   - `source_url`
   - `retrieved_at`
   - `source_class`
   - `content_sha256`

## 2. Source Classification Ladder
- **Tier 1: Official Registries**: Brønnøysundregistrene (Enhetsregisteret, Regnskapsregisteret, Underenheter, Roller). Fully licensed open public sector data (NLOD / CC-BY 4.0).
- **Tier 2: Primary Company Properties**: Verified corporate homepages and official company-operated digital channels.
- **Tier 3: Permitted Outbound Signals**: Verified company careers pages (`/karriere`), official press archives (`/nyheter`), and verified outbound social profiles.
- **Tier 4: Abstention**: If corroboration is ambiguous, the system deterministically emits `not_found` or `not_applicable` with zero speculative hallucinations.
