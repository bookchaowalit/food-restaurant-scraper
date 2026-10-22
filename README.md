# book-restaurant-scraping

**Tier:** B (catalog label; Big Loop target L3)  
**Owner path:** `bookchaowalit/book-apps/tools/book-restaurant-scraping`

> **Source terms (2026-10-15):** Wongnai was rejected by the owner; live collection and the weekly cron below are not approved. Offline fixtures/tests only. See [Source terms decision](#source-terms-decision-2026-10-15).

## Purpose

Bounded Wongnai restaurant listing collector (restaurant.v1 producer); offline fixtures only while Wongnai is rejected.

## Entry points

- `scripts/run_restaurants.py` -> `restaurants/wongnai_scraper.py` (jobs `wongnai_bangkok`, `wongnai_upcountry`)

## Stack

Python

## How to run (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Live Wongnai collection and cron are NOT approved (owner decision 2026-10-15):
# python3 scripts/run_restaurants.py --max-pages 3 --min-rows 20
# bash setup_cron.sh install
```

Output stays in this repository's `data/exported/`.

## Polite collection

`restaurants/http.py` is the only network path: an identifying `User-Agent`
(`book-restaurant-scraping/1.0`), a 30 s timeout, and at most three attempts
with exponential backoff that retry only timeouts, connection errors, HTTP 429
(honouring `Retry-After` as seconds or an HTTP-date, capped at 60 s) and
5xx; 403/404 fail at once. The helper is kept identical to
book-ecommerce-scraping's `ecommerce/http.py` apart from the User-Agent.
`fetch_pages` waits 2 s between pages, is capped at 5 pages x 100 rows, and
stops as soon as a page returns no results. `scripts/run_restaurants.py`
isolates jobs: a failing job is reported as `{"job": ..., "error":
"<ExceptionClass>"}` and the exit code is 1. Raw JSON, snapshot CSV and
history CSV are written atomically (`restaurants/atomic_io.py`: temp file +
fsync + `os.replace`), so a killed cron run never leaves a truncated export
or a torn history row.

Rows keep only business contact data that Wongnai publishes for the venue
(address, business phone, homepage). The raw capture
(`<stem>_raw.json`, under git-ignored `data/`) is no longer full page HTML: it
keeps, per page, only the search-result business fields the parser reads
(`trimmed_capture`), so review snippets, reviewer names and page/session state
are never stored. `--max-pages` (1-5) and `--min-rows` (1-500) are validated
before any request.

## Checks (offline)

```bash
uv sync --frozen --all-extras          # runtime deps + dev extra (pytest, ruff, mypy) from uv.lock
uv run ruff check . && uv run ruff format --check .
uv run mypy                            # scope and strictness: [tool.mypy] in pyproject.toml
uv run python -m pytest -q --cov       # CI gate: total coverage >= 91%
uv run python scripts/run_restaurants.py --dry-run --json   # plan only, no network
```

Tests replay `tests/fixtures/` and mock the HTTP layer; a conftest guard fails any real
socket connection. CI (`.github/workflows/ci.yml`, shared platform-ci-workflows v1.1.1)
runs the same checks on Python 3.10 and 3.13. `requirements.txt` is kept because
`setup_cron.sh` installs the cron venv from it; keep it in sync with `pyproject.toml`.

## Error reporting (opt-in)

With `SENTRY_DSN` set (optionally `SENTRY_ENVIRONMENT`), `scripts/run_restaurants.py`
sends one Sentry `error` event per failed job, carrying the job name and exception class
only (`restaurants/observability.py`; no page content, `send_default_pii=False`, tracing
off). Uncaught crashes reach Sentry through the SDK excepthook, but `include_local_variables=False`,
`max_request_body_size="never"` and `before_send=scrub_event` drop locals, exception text,
request data and breadcrumbs. Without a DSN nothing is initialised; `--dry-run` never initialises it.

## Boundaries

- Producer for `restaurant.v1` (draft, collection rejected); it does **not** land data in the lake. The Bronze `restaurant_listings` replay belongs to the parent pipeline and is not wired.
- **Not** coupled to Solo Empire monorepo runtime. Nested Git repo; commit only inside this tree.
- Never commit `.env`, cookies, session dumps, or scraped PII dumps to Git.

## Source terms decision (2026-10-15)

**Wongnai: rejected by the owner on 2026-10-15 (BOO-130).** Wongnai terms
section 2(3) bars collecting restaurant information, location/maps, user data
and images for any purpose without written Wongnai permission; sections 5 and
11.4 reserve IP and limit personal-data use. A working smoke test is not
permission. Do not run live Wongnai collection or activate the weekly cron (policy, not enforced in code);
`restaurant.v1` stays non-approved and the coverage registry marks restaurant
permission `blocked`. Offline synthetic fixtures and tests are unaffected.
Reopening requires written permission covering venue metadata, storage/history
and downstream API exposure, or a separately licensed source. This is an owner
decision based on the published terms, not legal advice. Record: architecture-docs `systems/ai-data/source-terms-decisions-2026-10-15.md` (private repository).
Source: [Wongnai terms](https://www.wongnai.com/terms?locale=en).

## Limitations (honest)

Prototype only. Respect ToS. Not a consumer app backend.

## Related

- Active collection product: `book-job-scraping` (Tier A tool)
- Lake products: `book-crypto-data`, `book-fx-data`, `book-stock-data`, …
- Solo Empire catalog: `repository-catalog/BOOK-DEV-BACKLOG-BD.md` (BD-012)
