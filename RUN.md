# Signalpost Execution Guide (RUN.md)

## Environment
- Python 3.12+
- `uv` package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `winget install astral-sh.uv`)
- Git LFS is optional. Without the large local snapshots, every company is read from the live Brønnøysund API.

## Install
```bash
uv sync
```

## Run command
```bash
uv run python scripts/run_competition_batch.py --organisations <company-list> --output-dir out/run
```

`<company-list>` is the batch supplied at run time: a JSON list, JSONL rows with `organisation_number`, or a text file with one organisation number per line. The agent researches every company in the file, including companies it has never seen, and writes:

| File | Contents |
|:---|:---|
| `out/run/envelopes.jsonl` | One result envelope per input company, in input order |
| `out/run/profiles.jsonl` | One evidence-backed profile per company |
| `out/run/run-report.json` | Module states, coverage counts, request usage and validation checks |
| `out/run/sources/` | The exact source bytes behind each published fact, named by SHA-256 |
| `out/run/viewer/index.html` | Viewer over this run (search, filters, sources, compare, export) |

The process exits with code 0 when every input has exactly one result envelope.

## Result states
Every module of every company carries exactly one of:

| State | Meaning |
|:---|:---|
| `available` | Found, with source URL, retrieval time and saved source |
| `not_available` | Looked, nothing there |
| `blocked` | The source refused the request (HTTP 401/403/429, robots.txt) |
| `not_applicable` | Does not apply (for example, an organisation number that is not registered) |
| `ambiguous` | A candidate was found but could not be tied to this exact company, so it is not published |
| `failed` | The fetch or the run broke for this item |

## Publication rules
- **Website**: published only after the identity check ties it to the company: organisation number on the site, the registry's own website and e-mail domain, or the company name together with the registered address, postcode, city, phone or a registered CEO/board member named on the site. A name match alone on an unrelated domain is `ambiguous`.
- **Social profiles**: linked from the verified site, with a handle that carries the company's legal name or is the site's own name. A local branch on a parent organisation's site does not inherit the parent's profiles.
- **Hiring**: individual postings (a structured `JobPosting`, or a role-specific listing with a deadline, posting terms or an applicant-tracking link), plus one hiring signal when the verified site links into the company's own job board on an applicant-tracking system (an apply action). A careers page by itself is never a hiring fact.
- **News**: only individual, dated articles from the verified company site, found on its pages, its sitemap or its RSS/Atom feed. The date is the one the article states about itself (structured data, publish meta tags, a "Publisert" label) or the one in its URL; a page is never dated in the future. Index pages, menus, undated pages and a news publisher's editorial articles are not published.
- **Growth signals**: sourced facts (revenue trend, registered employees, postings or job board, recent articles, management changes) are kept apart from inferences drawn from them, which are labelled as such.
- **Evidence**: every published website, social profile, job and news item links to the stored page it was read from (`snapshot_sha256`, `snapshot_path`).

## Options
| Option | Default | Purpose |
|:---|:---|:---|
| `--workers` | 12 | Companies researched in parallel |
| `--web-requests-per-company` | 40 | Cap on website and search requests per company (registry calls are not capped) |
| `--budget` | none | Optional run-wide ceiling on website and search requests |
| `--previous <profiles.jsonl>` | none | Refresh: record changes since that run and carry forward evidence a source no longer returns |
| `--resume` | off | Continue an interrupted run in the same output directory |
| `--open` | off | Open the viewer in the default browser when the run finishes |
| `--expected-count N` | none | Fail fast if the input does not contain exactly N companies |
| `--bulk <file>` | auto | Local Brreg snapshot to read first (SQLite, CSV or JSONL.GZ) |

## Refresh run
```bash
uv run python scripts/run_competition_batch.py --organisations <company-list> --output-dir out/run-2 --previous out/run/profiles.jsonl
```

## Tests
```bash
uv run pytest -q
```

## Operational profile
- **External API cost**: $0.00. No paid APIs, LLM tokens or credentialed services.
- **Sources**: Brønnøysund open APIs (NLOD) and the company's own public website (pages, sitemap, RSS/Atom feed), respecting robots.txt.
- **Failure handling**: an error on one company marks that company `failed` and the run continues; no input is dropped.
