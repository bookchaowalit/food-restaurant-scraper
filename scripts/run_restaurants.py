#!/usr/bin/env python3
"""Run the bounded Wongnai adapters owned by this repository."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

JOBS: tuple[dict[str, Any], ...] = (
    {
        "name": "wongnai_bangkok",
        "locations": ["bangkok"],
        "output_stem": "wongnai_bangkok",
        "source_url": "https://www.wongnai.com/restaurants?locationKey=1",
    },
    {
        "name": "wongnai_upcountry",
        "locations": ["khonkaen", "korat", "pattaya"],
        "output_stem": "wongnai_upcountry",
        "source_url": "https://www.wongnai.com/restaurants?locationKey=6",
    },
)


async def run_restaurants(
    output_dir: Path,
    max_pages: int = 3,
    min_rows: int = 20,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    if dry_run:
        return [
            {
                "job": job["name"],
                "status": "dry-run",
                "source_url": job["source_url"],
                "max_pages": max_pages,
                "min_rows": min_rows,
                "network": "not-used",
                "writes": "not-used",
            }
            for job in JOBS
        ]
    results: list[dict[str, Any]] = []
    from restaurants.wongnai_scraper import WongnaiScraper

    for job in JOBS:
        scraper = WongnaiScraper(
            locations=job["locations"],
            page_size=100,
            min_rows=min_rows,
            output_stem=job["output_stem"],
            source_url=job["source_url"],
            output_dir=output_dir,
        )
        try:
            batch = await scraper.run(max_pages=max_pages)
        except Exception as exc:  # noqa: BLE001 - isolate each job
            # Record only the exception class so page content never leaks.
            results.append({"job": job["name"], "error": type(exc).__name__})
            print(
                f"[run_restaurants] {job['name']}: failed ({type(exc).__name__})",
                file=sys.stderr,
            )
            continue
        results.extend(batch)
        print(
            f"[run_restaurants] {job['name']}: {batch[0].get('count') if batch else 0}"
        )
    return results


def _bounded_int(minimum: int, maximum: int):
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"expected an integer, got {value!r}"
            ) from None
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(f"must be from {minimum} to {maximum}")
        return number

    return parse


def main(argv: list[str] | None = None) -> int:
    # Bounds mirror restaurants.wongnai_scraper (MAX_PAGES=5, MAX_ROWS=500) so
    # bad values fail here, before any network call. Kept literal so the
    # dry-run path does not import the scraper's live dependencies.
    parser = argparse.ArgumentParser(
        description="Run book-restaurant-scraping Wongnai jobs"
    )
    parser.add_argument("--max-pages", type=_bounded_int(1, 5), default=3)
    parser.add_argument("--min-rows", type=_bounded_int(1, 500), default=20)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data" / "exported")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the bounded job plan without collection or writes",
    )
    args = parser.parse_args(argv)
    if args.output_dir.exists() and not args.output_dir.is_dir():
        parser.error(f"--output-dir is not a directory: {args.output_dir}")
    if args.dry_run:
        results = asyncio.run(
            run_restaurants(
                args.output_dir, args.max_pages, args.min_rows, dry_run=True
            )
        )
    else:
        from restaurants.observability import init_sentry, report_failures

        sentry = init_sentry("run_restaurants")
        results = asyncio.run(
            run_restaurants(args.output_dir, args.max_pages, args.min_rows)
        )
        report_failures(sentry, results)
    if args.json:
        print(json.dumps(results, ensure_ascii=False))
    return 1 if any("error" in result for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
