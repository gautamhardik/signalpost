# Signalpost Source Policy & Data Governance

## 1. Compliance & Principles
Signalpost operates strictly under legal and responsible discovery practices:
1. **Robots.txt & Terms Adherence**: Signalpost respects `robots.txt` (pages, sitemaps and feeds alike) and treats HTTP 401/403/429/451 as a refusal. A refused source produces the `blocked` state rather than a retry around the refusal.
2. **Third-Party Directory Blocking**: Business directories (Proff, Purehelp, 1881, Gulesider, CompanyWall and others) are never treated as a company's website or used as a discovery anchor.
3. **Deterministic Identity Gate**: A website is published only when it is tied to the exact company: its organisation number on the site, the registry's own website and e-mail domain, or the company name together with the registered address, postcode, city, phone or a registered CEO or board member. A social profile linked from the verified site is published when its handle carries the company's legal name or is the verified site's own name; a local branch on a parent organisation's site does not inherit the parent's profiles.
4. **No Naked Facts**: Every published claim keeps its provenance:
   - `source_url`
   - `retrieved_at`
   - `source_class`
   - `content_sha256`, plus `snapshot_sha256` and `snapshot_path` pointing at the saved source bytes

## 2. Source Classification Ladder
- **Tier 1: Official Registries**: Brønnøysundregistrene (Enhetsregisteret, Regnskapsregisteret, Underenheter, Roller). Open public sector data (NLOD).
- **Tier 2: Primary Company Properties**: The verified company website, read page by page and through its own sitemap and RSS/Atom feed.
- **Tier 3: Signals from the Verified Site**: Individual dated articles, individual job postings, the link from the company's site into its own job board on an applicant-tracking system, and social profiles the site links to. A careers or news index page by itself is never published as a fact, and a news publisher's editorial articles are not treated as news about the company.
- **Tier 4: Abstention**: When identity cannot be established, the result is `ambiguous` or `not_available`, with the reason, and nothing is inferred in its place.

## 3. Facts and Inference
Growth signals in the synthesis are facts read from a cited source (filed accounts, the register, the verified site). Anything concluded from them is listed separately, labelled as inference, and names the signals it rests on.
