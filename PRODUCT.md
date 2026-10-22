# book-restaurant-scraping — Product brief

**Slug:** `bookchaowalit/food-restaurant-scraper`  
**Tier:** B (catalog label) · target Big Loop L3  
**Status (2026-10-22):** one bounded Wongnai collector with offline tests. Live collection
is **not approved**: the owner rejected Wongnai on 2026-10-15 (BOO-130). Nothing runs on a
schedule from this repository today.

## Purpose

Restaurant / local-business producer: capture a bounded set of public restaurant listings
into contract-shaped CSVs (`restaurant.v1`) for research. While no restaurant source is
approved, the repo is kept as tested code and synthetic fixtures only.

## What exists

- `restaurants/wongnai_scraper.py`: parses Wongnai's embedded `window._wn` state
  (≤ 5 pages × 100, ≤ 500 rows, 2 s between pages, stops on an empty page, second location
  check) and writes `data/exported/<stem>.csv`, `<stem>_history.csv` and a trimmed
  `<stem>_raw.json` (parsed business fields only).
- `restaurants/http.py`: the only network path (identifying User-Agent, timeout, bounded
  retries).
- `scripts/run_restaurants.py`: the runner for jobs `wongnai_bangkok` and
  `wongnai_upcountry` (Khon Kaen, Korat, Pattaya); `--dry-run` prints the plan without
  network or writes; a failed job is reported as `{"job", "error": "<ExceptionClass>"}`
  and exit 1.
- `restaurants/observability.py`: opt-in Sentry (see below).

## Runtime status (verified 2026-10-22)

| What | Status |
|---|---|
| Entry point | `python scripts/run_restaurants.py [--max-pages 1-5] [--min-rows 1-500] [--json] [--dry-run] [--output-dir DIR]` |
| Who schedules it | Nobody verified. `setup_cron.sh install` would add a weekly crontab line (Sunday 00:15), but this WSL host's crontab has no scraper entries on 2026-10-22, installing it is not approved, and book-job-scraping's `config/jobs.yaml` has no Wongnai job. Other hosts / Windows tasks not verified from WSL [ต้องยืนยัน] |
| Hosted deployment | None. No API, no port, no cloud job (scheduler host is owner decision D6) |
| Error reporting | Sentry, opt-in: with `SENTRY_DSN` set, each failed job sends one `error` event (job name + exception class; no page content, no PII; locals, request bodies, exception messages and breadcrumbs are stripped from any event, including uncaught crashes). No DSN is configured for this product yet [ต้องยืนยัน] |
| Contract | `restaurant.v1` (architecture-docs `systems/architecture/scraping-contracts/`): status `draft`, `collection_approval: rejected`. The snapshot header equals its record fields (checked offline by `tests/test_contract.py`) |
| Lake landing | Not wired: no Bronze `restaurant_listings` manifest is produced |
| Quality gates in CI | ruff, ruff format, mypy (gradual), offline pytest with coverage ≥ 91%, dry-run smoke, on Python 3.10 and 3.13; shared security scan (platform-ci-workflows v1.1.1) |

## Limits

- Not production: no approved source, no schedule, no lake landing.
- The Wongnai rejection is a policy; the code does not refuse a live run by itself.

## Docs

- `specs/001-l2-baseline/spec.md`: current spec (acceptance, red/green log, planned schedule).
- `docs/measurement/KPI-PLAN.md`: data-product KPIs (freshness, rows, skips, contract).
- `docs/UPGRADE-PLAN.md`: earlier upgrade notes.
