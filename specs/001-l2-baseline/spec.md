---
id: SPEC-001
title: L2/L3 baseline for food-restaurant-scraper
status: in review
created: 2026-10-22
owner: bookchaowalit
---

# SPEC-001: L2/L3 baseline

## Document control

| Field | Value |
|---|---|
| Main-only | yes (ADR-0004 v1.1: red run is local, red and green commits pushed together) |
| Maker | Claude session b-data (2026-10-22) |
| Checker / approver | pending (owner) |

## Problem

The Big Loop scorecard (2026-10-22) had this repo at L0: no lockfile, no type check, no
error reporting, no KPI plan and no spec. `scripts/run_restaurants.py` isolates each job
and turns an exception into `{"job": ..., "error": "<ExceptionClass>"}` with exit code 1,
so a failing scheduled run is visible only in `data/logs/cron.log` on whichever host runs
it.

## Behaviour

1. Dependencies resolve from the committed `uv.lock`; CI installs with
   `uv sync --frozen --all-extras`. `requirements.txt` stays (setup_cron.sh installs the
   cron venv from it) and is kept in sync with `pyproject.toml` by hand.
2. `mypy` runs in CI over `restaurants/`, `scripts/` and `tests/` (gradual; strict on
   `restaurants/observability.py`).
3. When `SENTRY_DSN` is set and `sentry-sdk` is installed, every failed job in a
   non-dry run sends exactly one Sentry event (`level=error`) whose message holds the job
   name and the exception class only. Page content, listing data and personal data are
   never attached; `send_default_pii` is false and tracing is off. A run without failures
   sends nothing. Without a DSN, Sentry is never initialised; `--dry-run` never initialises
   it.
4. The snapshot CSV header (`<stem>.csv`) equals the `restaurant.v1` record fields, in order, and every
   row has the contract's required fields.
5. CI fails when total coverage drops below 91%.

## Acceptance

| AC | Given / When / Then | Test |
|---|---|---|
| AC-01 | Given `SENTRY_DSN` is set, when the Bangkok job raises, while the upcountry job succeeds, then one `error` event naming `wongnai_bangkok` and `RuntimeError` is sent, no page text is in it, and the exit code is 1 | `tests/test_observability.py::test_failed_job_reaches_sentry` |
| AC-02 | Given `SENTRY_DSN` is set, when the run succeeds, then no event is sent | `tests/test_observability.py::test_successful_run_sends_nothing` |
| AC-03 | Given no `SENTRY_DSN` (or `--dry-run`), when a run fails, then Sentry is not initialised | `test_without_dsn_sentry_stays_off`, `test_dry_run_never_initialises_sentry` |
| AC-04 | CI on `main` is green on Python 3.10 and 3.13 with ruff, ruff format, mypy and the 91% coverage gate | CI run below |
| AC-05 | Given the saved Wongnai fixture, when a run writes the snapshot, then the header is the `restaurant.v1` record fields and no row misses a required field | `tests/test_contract.py` |

## Red/green log

| AC | Red (sha · command · failure) | Green |
|---|---|---|
| AC-01 | `dc52c1b` · `python -m pytest -q tests/test_observability.py` · `AssertionError: []` / `assert 0 == 1` (no Sentry event for the failed `wongnai_bangkok` job) | GREEN_CI |
| AC-05 | none: written green as a guard (the snapshot already matched the contract) | GREEN_CI |

## Schedule (planned replacement, D6)

No scheduler was changed (owner decision D6 on the schedule host is open).

- Today: `setup_cron.sh install` would add a weekly crontab line (Sunday 00:15) that runs
  `scripts/run_restaurants.py --max-pages 3 --min-rows 20` under `flock`, logging to
  `data/logs/cron.log`. On 2026-10-22 this WSL host's crontab has no such entry, and the
  owner rejected Wongnai collection on 2026-10-15 (BOO-130), so the cron must not be
  installed. book-job-scraping's `config/jobs.yaml` has no Wongnai job either. Other hosts
  and Windows tasks are not verified [ต้องยืนยัน].
- Planned replacement once D6 is decided **and** a restaurant source is approved: one
  hosted weekly job (192-hour freshness SLO in the roadmap) that runs
  `python scripts/run_restaurants.py --json` with `SENTRY_DSN` set, so each failed job is a
  Sentry event, and hands the capture to the parent replay into Bronze
  `restaurant_listings`. `setup_cron.sh` then gains a read-only `plan` mode and a lake guard
  (roadmap rst-t3) or is removed. Until then there is nothing to schedule.

## Out of scope

Live captures (Wongnai is rejected), lake writes to R2, new restaurant sources, a code
guard that refuses live runs (the rejection is policy today, see README), and changes to
`setup_cron.sh`.
