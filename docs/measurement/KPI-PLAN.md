---
title: KPI and Instrumentation Plan — food-restaurant-scraper
created: 2026-10-22
updated: 2026-10-22
status: draft
template: architecture-docs templates/sdlc/kpi-and-instrumentation-plan.md
---

# book-restaurant-scraping — KPI and Instrumentation Plan

This is a data producer, not a user-facing product, so its KPIs are data-product KPIs:
freshness, volume, parse quality and contract conformance. **Live collection is not
approved** (Wongnai rejected by the owner on 2026-10-15, BOO-130; `restaurant.v1` has
`collection_approval: rejected`), so no production baseline can be measured. Every
production figure below is `baseline: not yet measured`, and the targets apply only if a
restaurant source is approved.

## Document control

| Field | Value |
|---|---|
| Project / product ID | book-restaurant-scraping (`bookchaowalit/food-restaurant-scraper`) |
| Version | 0.1 |
| Status | draft |
| Metric owner | bookchaowalit (owner) |
| AI maker | Claude session b-data (2026-10-22) |
| AI reviewer | pending [ต้องยืนยัน] |
| Charter objectives | Roadmap `data-scrapers.yaml` rst-g1..rst-g4 (no charter) |
| Analytics / data source of truth | Run output (`--json` result rows, `data/exported/*.csv`), Sentry events from `restaurants/observability.py`; Bronze `restaurant_listings` once wired |
| Dashboard | none yet [ต้องยืนยัน] |
| Next review | when restaurant.v1 leaves `rejected`, or 2026-12-31 (roadmap horizon) |

## KPI tree

```text
OBJ-01 A contract-valid, fresh restaurant listing feed (only if a source is approved)
  └─ KPI-O-01 Bronze freshness (hours since last successful capture)
       ├─ KPI-L-01 Rows per run
       ├─ KPI-L-02 Business skip rate (businesses dropped by the parser)
       ├─ KPI-G-01 Contract violations per run
       ├─ KPI-G-02 Failed runs not reported
       └─ KPI-G-03 Personal-data fields in exports
```

## KPI definitions

| KPI ID | Type | Name | Objective | Formula (numerator / denominator) | Unit | Min volume for a rate | Segment / filter | Data source and event(s) | Baseline (value, period, evidence) | Target (value, by date) | Alert threshold | Cadence | Owner |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| KPI-O-01 | outcome | Bronze freshness | OBJ-01 | now − max(`captured_at`) of `restaurant_listings` | hours | N/A | jobs wongnai_bangkok, wongnai_upcountry (or the approved successor) | Bronze manifest (not wired) | not yet measured (collection rejected) | ≤ 192 h (weekly), from the first approved schedule [ต้องยืนยัน] | > 192 h | per run | owner |
| KPI-L-01 | leading | Rows per run | OBJ-01 | `count` in the run's result row | rows | N/A | per job | `scripts/run_restaurants.py --json` | not yet measured | ≥ 20 per job (the run fails below `--min-rows`, default 20; cap 500) | 0 rows (the run already fails then) | per run | owner |
| KPI-L-02 | leading | Business skip rate | OBJ-01 | businesses dropped by `parse_html` (bad id, no name, off-location, bad URL) / businesses on the page | % | ≥ 50 businesses | per page | not instrumented (the parser does not count skips yet) | not yet measured | ≤ 10% [ต้องยืนยัน] | > 25% | per run | owner |
| KPI-G-01 | guardrail | Contract violations | OBJ-01 | rows missing a `restaurant.v1` required field, or a header that differs from the record fields | rows | N/A | snapshot CSV | `tests/test_contract.py` (offline, every CI run) | 0 on the saved fixture, 2026-10-22, CI | must stay 0 | ≥ 1 (CI fails) | every CI run | owner |
| KPI-G-02 | guardrail | Failed runs not reported | OBJ-01 | failed jobs without a Sentry event / failed jobs | % | N/A | runs with `SENTRY_DSN` set | `restaurants/observability.py` → Sentry; `tests/test_observability.py` | 0 in tests; production not measured (no DSN configured) | must stay 0 | ≥ 1 | per run | owner |
| KPI-G-03 | guardrail | Personal data beyond venue contact | OBJ-01 | reviewer names, review text or session state present in snapshot or raw JSON (venue address/phone/homepage are allowed by the contract) | fields | N/A | all exports | `tests/test_wongnai_scraper.py::test_raw_capture_keeps_only_parsed_business_fields`, `test_fetch_pages_raw_capture_has_no_page_html` | 0 on fixtures, 2026-10-22 | must stay 0 | ≥ 1 | every CI run | owner |

Rules from the template apply: no KPI without a baseline is used to claim a benefit, and
rates below the minimum volume are reported as `not measurable`.

## Event and data specification

| Event / field | Trigger (exact user or system action) | Properties | Personal data (incl. IDs / IP)? | Emitted by | Requirement / story | Status |
|---|---|---|---|---|---|---|
| run result row | each job in `run_restaurants` finishes or fails | `job`/`source`, `count`, `output`, `history`, `raw` or `error` (exception class) | no | `scripts/run_restaurants.py` | SPEC-001 | implemented |
| Sentry `error` event | a job fails in a non-dry run with `SENTRY_DSN` set | message `job <name> failed: <ExceptionClass>`, tag `component=run_restaurants`, `environment` | no (`send_default_pii=False`) | `restaurants/observability.py` | SPEC-001 AC-01 | implemented, not live (no DSN) |
| `captured_at` | snapshot write | UTC ISO-8601, seconds, `Z` | no | `restaurants/wongnai_scraper.py` | restaurant.v1 | implemented |
| business skip counter | parser drops a business | page URL, reason | no | not implemented | KPI-L-02 | planned |

Privacy: rows keep only venue contact data Wongnai publishes for the business; raw captures
keep only the parsed business fields (`trimmed_capture`), no reviews or reviewer names. Sentry events carry no listing data. Retention of exports is
`pending_operator_approval` in the contract [ต้องยืนยัน].

## Dashboards and alerts

| Dashboard / alert | KPIs shown | Audience | Location | Refresh | Alert channel | Status |
|---|---|---|---|---|---|---|
| Sentry project for this collector | KPI-G-02 | owner | not created [ต้องยืนยัน] | per event | Sentry → owner | planned (owner action) |
| Lake freshness monitor | KPI-O-01, KPI-L-01 | owner | parent `task scraping:coverage` | per run | [ต้องยืนยัน] | planned (needs an approved source and lake landing) |

## Instrumentation verification (before G10)

| # | Check | Evidence | Result |
|---|---|---|---|
| 1 | Events fire once per real action | `tests/test_observability.py` (one event per failed job) | pass (offline) |
| 2 | Counts reconcile with the system of record | needs a live run | not run (collection rejected) |
| 3 | No PII in payloads | `tests/test_wongnai_scraper.py::test_raw_capture_keeps_only_parsed_business_fields` | pass (offline) |
| 4 | Dashboard renders each KPI | no dashboard | not run |
| 5 | Alerts reach the channel | no Sentry DSN configured | not run |
| 6 | Baselines captured | not yet measured | waived until a source is approved |
| 7 | Consent | not applicable (no end users) | N/A |

## Change history of definitions

| Date | KPI ID | Change | Reason | Baseline restated? | Approved by |
|---|---|---|---|---|---|
| 2026-10-22 | all | First draft | Big Loop L3 baseline | no | pending |

## Quality gate and approval

| Gate | Condition | Decision | Approver | Date | Evidence |
|---|---|---|---|---|---|
| G5 | KPI definitions accepted | pending | owner | — | this file |
| G10 | Instrumentation checks pass | blocked: no approved source, no DSN | owner | — | — |
| G11 | Dashboard live | blocked | owner | — | — |
