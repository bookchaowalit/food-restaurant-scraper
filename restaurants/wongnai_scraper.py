#!/usr/bin/env python3
"""Capture bounded Wongnai restaurant listings from public HTML.

Wongnai does not expose a source-specific API in this workflow. The public
restaurant page embeds its server-rendered state in ``window._wn``; this
adapter reads that payload, paginates conservatively, and applies a second
location check because the landing page can contain nationwide suggestions
even when a location query is present.

This repository is the collection producer. Durable restaurant lake/API
ownership remains with the downstream data product.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

try:
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover - requirements.txt supplies both
    raise RuntimeError(
        "httpx and beautifulsoup4 are required for Wongnai capture"
    ) from exc

from restaurants.atomic_io import append_csv_atomic, render_csv, write_text_atomic
from restaurants.http import PAGE_DELAY_SECONDS, polite_get


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "exported"
SOURCE_URL = "https://www.wongnai.com/restaurants?locationKey=1"
SOURCE_NAME = "Wongnai"
DEFAULT_LOCATIONS = ["bangkok"]
DEFAULT_PAGE_SIZE = 100
MAX_PAGES = 5
MAX_PAGE_SIZE = 100
MAX_ROWS = 500
MIN_ROWS = 5
ALLOWED_HOST = re.compile(r"(?:www\.)?wongnai\.com", re.IGNORECASE)
LOCATION_ALIASES = {
    "bangkok": {"กรุงเทพมหานคร", "กรุงเทพฯ", "กรุงเทพ", "bangkok"},
    "chiangmai": {"เชียงใหม่", "chiang mai", "chiangmai"},
    "phuket": {"ภูเก็ต", "phuket"},
    "khonkaen": {"ขอนแก่น", "khon kaen", "khonkaen"},
    "korat": {"นครราชสีมา", "โคราช", "nakhon ratchasima", "korat"},
    "pattaya": {"พัทยา", "ชลบุรี", "pattaya", "chon buri"},
}
SNAPSHOT_FIELDS = [
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
HISTORY_FIELDS = [
    "captured_at",
    "restaurant_id",
    "name",
    "rating",
    "review_count",
    "price_range",
    "city",
    "district",
    "url",
    "location",
    "source",
]


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _clean_text(value: Any, limit: int = 500) -> str:
    if isinstance(value, dict):
        value = (
            value.get("primary")
            or value.get("name")
            or value.get("thai")
            or value.get("english")
        )
    # Zero-width space / word joiner / BOM survive strip() and \s.
    text = re.sub("[\u200b\u2060\ufeff]", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _as_values(values: Iterable[str] | str | None, default: list[str]) -> list[str]:
    if values is None:
        values = default
    if isinstance(values, str):
        values = values.split(",")
    result: list[str] = []
    for value in values:
        normalized = str(value).strip().casefold()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def normalize_locations(values: Iterable[str] | str | None) -> list[str]:
    locations = _as_values(values, DEFAULT_LOCATIONS)
    if not locations or len(locations) > 6:
        raise ValueError("locations must contain 1-6 Wongnai locations")
    unknown = [location for location in locations if location not in LOCATION_ALIASES]
    if unknown:
        raise ValueError(f"unsupported Wongnai location(s): {', '.join(unknown)}")
    return locations


def normalize_source_url(value: str = SOURCE_URL) -> str:
    parts = urlsplit(str(value).strip())
    host = (parts.hostname or "").lower()
    path = parts.path.rstrip("/") or "/"
    if (
        parts.scheme.lower() != "https"
        or not ALLOWED_HOST.fullmatch(host)
        or path != "/restaurants"
    ):
        raise ValueError("Wongnai source URL must be an HTTPS /restaurants page")
    query = urlencode(parse_qsl(parts.query, keep_blank_values=True))
    return urlunsplit(("https", host, path, query, ""))


def build_page_url(
    source_url: str, page_number: int, page_size: int = DEFAULT_PAGE_SIZE
) -> str:
    if (
        isinstance(page_number, bool)
        or not isinstance(page_number, int)
        or page_number < 1
    ):
        raise ValueError("page_number must be a positive integer")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= MAX_PAGE_SIZE
    ):
        raise ValueError(f"page_size must be an integer from 1 to {MAX_PAGE_SIZE}")
    base = normalize_source_url(source_url)
    query = dict(parse_qsl(urlsplit(base).query, keep_blank_values=True))
    query.update(
        {
            "page.number": str(page_number),
            "page.size": str(page_size),
            "rerank": "false",
        }
    )
    return urlunsplit(
        (
            "https",
            urlsplit(base).hostname or "www.wongnai.com",
            "/restaurants",
            urlencode(query),
            "",
        )
    )


def canonical_url(value: str) -> str:
    candidate = urljoin("https://www.wongnai.com/", str(value).strip())
    parts = urlsplit(candidate)
    host = (parts.hostname or "").lower()
    path = parts.path.rstrip("/") or "/"
    if parts.scheme.lower() != "https" or not ALLOWED_HOST.fullmatch(host):
        raise ValueError("Wongnai restaurant URL must use an HTTPS wongnai.com host")
    if not re.fullmatch(r"/restaurants/[^/]+", path):
        raise ValueError("Wongnai URL must point to a restaurant detail page")
    return urlunsplit(("https", host, path, "", ""))


def _window_state(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        marker = "window._wn ="
        if marker not in text:
            continue
        start = text.index(marker) + len(marker)
        try:
            state, _ = json.JSONDecoder().raw_decode(text[start:].lstrip())
        except json.JSONDecodeError as exc:
            raise ValueError("Wongnai window._wn is not valid JSON") from exc
        if not isinstance(state, dict):
            raise ValueError("Wongnai window._wn must be a JSON object")
        return state
    raise ValueError("Wongnai page is missing window._wn")


def _businesses(state: dict[str, Any]) -> list[dict[str, Any]]:
    store = state.get("store")
    value = (
        store.get("searchResult", {}).get("value") if isinstance(store, dict) else None
    )
    entries = value.get("data") if isinstance(value, dict) else None
    if not isinstance(entries, list):
        raise ValueError("Wongnai page is missing searchResult data")
    return [
        entry["business"]
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("business"), dict)
    ]


# Business keys kept in the raw capture: exactly what ``parse_html`` reads.
# Everything else in ``window._wn`` (review snippets, reviewer names, ads,
# session state) is dropped so raw files hold only the evidence we parse.
RAW_BUSINESS_KEYS = (
    "id",
    "displayName",
    "name",
    "nameOnly",
    "branch",
    "categories",
    "rating",
    "priceRange",
    "lat",
    "lng",
    "rUrl",
    "url",
    "verifiedLocation",
)
RAW_CONTACT_KEYS = ("address", "phoneno", "callablePhoneno", "homepage")
RAW_STATISTIC_KEYS = ("rating", "numberOfReviews")
RAW_PHOTO_KEYS = ("contentUrl",)


def _pick(value: Any, keys: Iterable[str]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in keys if key in value}


def trimmed_capture(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the parsed fields of each search-result business only."""

    trimmed: list[dict[str, Any]] = []
    for business in _businesses(state):
        item = _pick(business, RAW_BUSINESS_KEYS) or {}
        for key, keys in (
            ("contact", RAW_CONTACT_KEYS),
            ("statistic", RAW_STATISTIC_KEYS),
        ):
            picked = _pick(business.get(key), keys)
            if picked is not None:
                item[key] = picked
        for key in ("mainPhoto", "defaultPhoto"):
            picked = _pick(business.get(key), RAW_PHOTO_KEYS)
            if picked:
                item[key] = picked
        trimmed.append(item)
    return trimmed


def _coordinate(value: Any, limit: float) -> float | str:
    number = _number(value, minimum=-limit, maximum=limit)
    # Compare with None: a real 0.0 coordinate must not become empty.
    return "" if number is None else number


def _number(value: Any, *, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < minimum or number > maximum:
        return None
    return number


def _integer(value: Any) -> int:
    if isinstance(value, bool) or value in (None, ""):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):  # int(Infinity) overflows
        return 0
    return number if number >= 0 else 0


def _mapping(value: Any) -> dict[str, Any]:
    """Return ``value`` when it is a JSON object, else an empty dict."""
    return value if isinstance(value, dict) else {}


def _address(business: dict[str, Any]) -> dict[str, Any]:
    contact = business.get("contact")
    address = contact.get("address") if isinstance(contact, dict) else None
    return address if isinstance(address, dict) else {}


def _location_matches(address: dict[str, Any], location: str) -> bool:
    city = address.get("city")
    if not isinstance(city, dict):
        return False
    if location == "bangkok" and city.get("id") == 1:
        return True
    names = {
        _clean_text(value).casefold()
        for value in (
            city.get("name"),
            address.get("district"),
            address.get("subDistrict"),
        )
    }
    return bool(names & {alias.casefold() for alias in LOCATION_ALIASES[location]})


def _image_url(business: dict[str, Any]) -> str:
    for key in ("mainPhoto", "defaultPhoto"):
        photo = business.get(key)
        if isinstance(photo, dict) and photo.get("contentUrl"):
            return _clean_text(photo.get("contentUrl"), 1000)
    return ""


def _categories(business: dict[str, Any]) -> str:
    values: list[str] = []
    for category in business.get("categories") or []:
        if not isinstance(category, dict):
            continue
        name = _clean_text(category.get("name"), 100)
        if name and name not in values:
            values.append(name)
    return ",".join(values[:10])


def parse_html(
    html: str,
    source_url: str = SOURCE_URL,
    locations: Iterable[str] | str | None = None,
    page_number: int = 1,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Parse Wongnai's embedded state and keep only location-matched rows."""

    normalized_source = normalize_source_url(source_url)
    requested_locations = normalize_locations(locations)
    state = _window_state(html)
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for business in _businesses(state):
        restaurant_id = str(business.get("id") or "").strip()
        if (
            not restaurant_id.isdigit()
            or int(restaurant_id) <= 0
            or restaurant_id in seen_ids
        ):
            continue
        address = _address(business)
        location = next(
            (
                value
                for value in requested_locations
                if _location_matches(address, value)
            ),
            None,
        )
        if location is None:
            continue
        name = _clean_text(
            business.get("displayName")
            or business.get("name")
            or business.get("nameOnly"),
            300,
        )
        if not name:
            continue
        try:
            url = canonical_url(business.get("rUrl") or business.get("url") or "")
        except ValueError:
            continue
        price_range = _mapping(business.get("priceRange"))
        contact = _mapping(business.get("contact"))
        statistic = _mapping(business.get("statistic"))
        city = _mapping(address.get("city"))
        district = _mapping(address.get("district"))
        subdistrict = _mapping(address.get("subDistrict"))
        rating = _number(
            business.get("rating") or statistic.get("rating"), minimum=0, maximum=5
        )
        rows.append(
            {
                "restaurant_id": restaurant_id,
                "name": name,
                "branch": _clean_text(business.get("branch"), 200),
                "categories": _categories(business),
                "rating": rating if rating is not None else "",
                "review_count": _integer(statistic.get("numberOfReviews")),
                "price_range": _clean_text(price_range.get("name"), 100),
                "price_range_value": _integer(price_range.get("value")),
                "address": _clean_text(address.get("street"), 500),
                "district": _clean_text(district, 100),
                "subdistrict": _clean_text(subdistrict, 100),
                "city": _clean_text(city, 100),
                "phone": _clean_text(
                    contact.get("phoneno") or contact.get("callablePhoneno"), 80
                ),
                "homepage": _clean_text(contact.get("homepage"), 500),
                "latitude": _coordinate(business.get("lat"), 90),
                "longitude": _coordinate(business.get("lng"), 180),
                "url": url,
                "image_url": _image_url(business),
                "verified_location": bool(business.get("verifiedLocation")),
                "location": location,
                "source": SOURCE_NAME,
                "source_url": normalized_source,
                "page_number": page_number,
            }
        )
        seen_ids.add(restaurant_id)
    return state, rows


def _dedupe_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("restaurant_id") or row.get("url") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def fetch_pages(
    source_url: str,
    locations: list[str],
    max_pages: int,
    page_size: int,
    min_rows: int = MIN_ROWS,
    *,
    page_delay: float = PAGE_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch up to ``max_pages`` pages politely.

    Pages are spaced by ``page_delay`` seconds and collection stops early once
    a page has no search results, so an exhausted listing is not re-requested.
    """
    if (
        isinstance(max_pages, bool)
        or not isinstance(max_pages, int)
        or not 1 <= max_pages <= MAX_PAGES
    ):
        raise ValueError(f"max_pages must be an integer from 1 to {MAX_PAGES}")
    if (
        isinstance(min_rows, bool)
        or not isinstance(min_rows, int)
        or not 1 <= min_rows <= MAX_ROWS
    ):
        raise ValueError(f"min_rows must be an integer from 1 to {MAX_ROWS}")
    normalized_source = normalize_source_url(source_url)
    raw_pages: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for page_number in range(1, max_pages + 1):
        if page_number > 1 and page_delay > 0:
            sleep(page_delay)
        page_url = build_page_url(normalized_source, page_number, page_size)
        response = polite_get(
            page_url, source=f"Wongnai page {page_number}", sleep=sleep
        )
        state, page_rows = parse_html(
            response.text, normalized_source, locations, page_number
        )
        raw_pages.append(
            {
                "page_number": page_number,
                "url": str(response.url),
                "businesses": trimmed_capture(state),
            }
        )
        rows.extend(page_rows)
        if not _businesses(state):
            break
    rows = _dedupe_rows(rows)[:MAX_ROWS]
    if len(rows) < min_rows:
        raise ValueError(
            f"Wongnai capture produced only {len(rows)} location-matched restaurants; need at least {min_rows}"
        )
    return raw_pages, rows


def write_raw(raw_pages: list[dict[str, Any]], output_dir: Path, stem: str) -> Path:
    path = output_dir / f"{stem}_raw.json"
    write_text_atomic(path, json.dumps(raw_pages, ensure_ascii=False))
    return path


def write_snapshot(
    rows: list[dict[str, Any]], captured_at: str, output_dir: Path, stem: str
) -> Path:
    path = output_dir / f"{stem}.csv"
    write_text_atomic(
        path,
        render_csv(
            ({**row, "captured_at": captured_at} for row in rows), SNAPSHOT_FIELDS
        ),
    )
    return path


def append_history(
    rows: list[dict[str, Any]], captured_at: str, output_dir: Path, stem: str
) -> Path:
    path = output_dir / f"{stem}_history.csv"
    append_csv_atomic(
        path, ({**row, "captured_at": captured_at} for row in rows), HISTORY_FIELDS
    )
    return path


class WongnaiScraper:
    """Scheduler adapter for bounded, location-validated Wongnai capture."""

    def __init__(
        self,
        locations: Iterable[str] | str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        min_rows: int = MIN_ROWS,
        output_stem: str = "wongnai_bangkok",
        source_url: str = SOURCE_URL,
        output_dir: str | Path | None = None,
        **_: Any,
    ) -> None:
        self.locations = normalize_locations(locations)
        if (
            isinstance(page_size, bool)
            or not isinstance(page_size, int)
            or not 1 <= page_size <= MAX_PAGE_SIZE
        ):
            raise ValueError(f"page_size must be an integer from 1 to {MAX_PAGE_SIZE}")
        if (
            isinstance(min_rows, bool)
            or not isinstance(min_rows, int)
            or not 1 <= min_rows <= MAX_ROWS
        ):
            raise ValueError(f"min_rows must be an integer from 1 to {MAX_ROWS}")
        if not re.fullmatch(r"[a-z0-9_]+", output_stem):
            raise ValueError(
                "output_stem must contain only lowercase letters, numbers, and underscores"
            )
        self.page_size = page_size
        self.min_rows = min_rows
        self.output_stem = output_stem
        self.source_url = normalize_source_url(source_url)
        self.output_dir = Path(output_dir) if output_dir else OUTPUT_DIR

    async def run(self, max_pages: int = 3, **_: Any) -> list[dict[str, Any]]:
        raw_pages, rows = fetch_pages(
            self.source_url,
            self.locations,
            max_pages=max_pages,
            page_size=self.page_size,
            min_rows=self.min_rows,
        )
        captured_at = _utc_now()
        raw_path = write_raw(raw_pages, self.output_dir, self.output_stem)
        snapshot_path = write_snapshot(
            rows, captured_at, self.output_dir, self.output_stem
        )
        history_path = append_history(
            rows, captured_at, self.output_dir, self.output_stem
        )
        print(f"[{self.output_stem}] {len(rows)} restaurants -> {snapshot_path}")
        return [
            {
                "source": self.output_stem,
                "count": len(rows),
                "output": str(snapshot_path),
                "history": str(history_path),
                "raw": str(raw_path),
            }
        ]


if __name__ == "__main__":
    import asyncio

    asyncio.run(WongnaiScraper().run())
