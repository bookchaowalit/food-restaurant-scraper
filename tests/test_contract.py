"""SPEC-001 AC-05: the snapshot CSV matches the restaurant.v1 contract, offline.

The contract lives in the private architecture-docs repository
(``systems/architecture/scraping-contracts/restaurant.v1.yaml``), which CI cannot
read, so the fields this producer must honour are copied here. If the contract
changes, update ``CONTRACT_*`` from that file in the same commit as the code.
Copied 2026-10-22 from contract status ``draft``, ``collection_approval: rejected``.
"""

import csv
import re
from pathlib import Path

from restaurants.wongnai_scraper import (
    SNAPSHOT_FIELDS,
    _utc_now,
    parse_html,
    write_snapshot,
)

CONTRACT_RECORD_FIELDS = [
    "captured_at",
    "restaurant_id",
    "name",
    "branch",
    "categories",
    "rating",
    "review_count",
    "price_range",
    "price_range_value",
    "address",
    "district",
    "subdistrict",
    "city",
    "phone",
    "homepage",
    "latitude",
    "longitude",
    "url",
    "image_url",
    "verified_location",
    "location",
    "source",
    "source_url",
    "page_number",
]
CONTRACT_REQUIRED = ["captured_at", "restaurant_id", "name", "url", "source_url"]
UTC_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

FIXTURE = Path(__file__).parent / "fixtures" / "wongnai_restaurants.html"
SOURCE = "https://www.wongnai.com/restaurants?locationKey=1"


def _rows():
    _state, rows = parse_html(
        FIXTURE.read_text(encoding="utf-8"), SOURCE, locations=["bangkok"]
    )
    return rows


def test_snapshot_fields_are_the_contract_record_fields_in_order():
    assert SNAPSHOT_FIELDS == CONTRACT_RECORD_FIELDS


def test_written_snapshot_header_and_required_fields(tmp_path):
    rows = _rows()
    assert rows
    path = write_snapshot(rows, _utc_now(), tmp_path, "wongnai_bangkok")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        header, written = reader.fieldnames, list(reader)

    assert header == CONTRACT_RECORD_FIELDS
    for row in written:
        missing = [field for field in CONTRACT_REQUIRED if not row[field]]
        assert missing == [], f"restaurant {row['restaurant_id']} misses {missing}"
        assert UTC_SECONDS.match(row["captured_at"]), row["captured_at"]
        assert row["source"] == "Wongnai"
        assert row["url"].startswith("https://www.wongnai.com/restaurants/")


def test_identity_is_unique_within_one_capture():
    # Identity is <source>|<restaurant_id>; duplicate_policy picks the latest
    # capture downstream, so one capture must not repeat an identity.
    keys = [f"{row['source']}|{row['restaurant_id']}" for row in _rows()]
    assert len(keys) == len(set(keys))
    assert all(row["restaurant_id"].isdigit() for row in _rows())
