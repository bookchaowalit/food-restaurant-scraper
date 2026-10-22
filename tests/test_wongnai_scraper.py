import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from restaurants.wongnai_scraper import (
    build_page_url,
    fetch_pages,
    canonical_url,
    normalize_locations,
    parse_html,
    trimmed_capture,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "wongnai_restaurants.html"
EMPTY_PAGE = '<html><script>window._wn = {"store": {"searchResult": {"value": {"data": []}}}}</script></html>'
SOURCE = "https://www.wongnai.com/restaurants?locationKey=1"


def _page(html: str, url: str = SOURCE) -> httpx.Response:
    return httpx.Response(200, text=html, request=httpx.Request("GET", url))


class WongnaiScraperTests(unittest.TestCase):
    html: str

    @classmethod
    def setUpClass(cls):
        cls.html = FIXTURE.read_text(encoding="utf-8")

    def test_parse_filters_to_bangkok_and_deduplicates(self):
        state, rows = parse_html(
            self.html,
            "https://www.wongnai.com/restaurants?locationKey=1",
            locations=["bangkok"],
            page_number=2,
        )

        self.assertEqual(state["store"]["searchResult"]["value"]["p"], 1)
        self.assertEqual([row["restaurant_id"] for row in rows], ["1001", "1003"])
        self.assertEqual(rows[0]["city"], "กรุงเทพมหานคร")
        self.assertEqual(rows[0]["district"], "ปทุมวัน")
        self.assertEqual(rows[0]["review_count"], 120)
        self.assertEqual(rows[0]["price_range_value"], 2)
        self.assertEqual(rows[0]["page_number"], 2)
        self.assertTrue(all(row["location"] == "bangkok" for row in rows))
        self.assertTrue(
            all(
                row["url"].startswith("https://www.wongnai.com/restaurants/")
                for row in rows
            )
        )
        self.assertFalse(any("Chiang" in row["name"] for row in rows))

    def test_canonical_and_page_urls_strip_tracking_and_bound_pagination(self):
        self.assertEqual(
            canonical_url("/restaurants/123Ab-my-place?_st=tracking"),
            "https://www.wongnai.com/restaurants/123Ab-my-place",
        )
        page_url = build_page_url(
            "https://www.wongnai.com/restaurants?locationKey=1",
            page_number=3,
            page_size=100,
        )
        self.assertIn("page.number=3", page_url)
        self.assertIn("page.size=100", page_url)
        self.assertIn("rerank=false", page_url)

    def test_rejects_missing_or_unknown_contract_values(self):
        with self.assertRaises(ValueError):
            parse_html("<html><body>no embedded state</body></html>")
        with self.assertRaises(ValueError):
            normalize_locations(["mars"])
        with self.assertRaises(ValueError):
            canonical_url("https://example.com/restaurants/123-place")

    def test_fetch_pages_spaces_requests_and_stops_on_empty_page(self):
        sleeps: list[float] = []
        pages = [_page(self.html), _page(EMPTY_PAGE), _page(self.html)]
        with patch("restaurants.http.httpx.get", side_effect=pages) as get:
            raw_pages, rows = fetch_pages(
                SOURCE,
                ["bangkok"],
                max_pages=3,
                page_size=100,
                min_rows=1,
                sleep=sleeps.append,
            )
        self.assertEqual(get.call_count, 2)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(len(raw_pages), 2)
        self.assertEqual([row["restaurant_id"] for row in rows], ["1001", "1003"])

    def test_fetch_pages_deduplicates_across_pages_and_enforces_min_rows(self):
        pages = [_page(self.html), _page(self.html)]
        with patch("restaurants.http.httpx.get", side_effect=pages):
            _raw, rows = fetch_pages(
                SOURCE,
                ["bangkok"],
                max_pages=2,
                page_size=100,
                min_rows=1,
                sleep=lambda _s: None,
            )
        self.assertEqual(len(rows), 2)
        with patch("restaurants.http.httpx.get", side_effect=[_page(self.html)]):
            with self.assertRaises(ValueError):
                fetch_pages(
                    SOURCE,
                    ["bangkok"],
                    max_pages=1,
                    page_size=100,
                    min_rows=5,
                    sleep=lambda _s: None,
                )

    def test_fetch_pages_rejects_unbounded_page_counts(self):
        for bad in (0, 6, True):
            with self.assertRaises(ValueError):
                fetch_pages(SOURCE, ["bangkok"], max_pages=bad, page_size=100)

    def test_parse_tolerates_malformed_business_entries(self):
        html = (
            '<script>window._wn = {"store": {"searchResult": {"value": {"data": ['
            '"junk", {"business": null}, {"business": {"id": "-4"}},'
            '{"business": {"id": "77", "displayName": "No city"}},'
            '{"business": {"id": "78", "displayName": "Ok", "rUrl": "/restaurants/78-ok",'
            ' "rating": "NaN", "lat": 999, "contact": {"address": {"city": {"id": 1}}}}}'
            "]}}}}</script>"
        )
        _state, rows = parse_html(html, SOURCE, ["bangkok"])
        self.assertEqual([row["restaurant_id"] for row in rows], ["78"])
        self.assertEqual(rows[0]["rating"], "")
        self.assertEqual(rows[0]["latitude"], "")

    def test_zero_coordinate_is_kept(self):
        html = (
            '<script>window._wn = {"store": {"searchResult": {"value": {"data": ['
            '{"business": {"id": "5", "displayName": "Equator", "rUrl": "/restaurants/5-eq",'
            ' "lat": 0, "lng": 0.0, "contact": {"address": {"city": {"id": 1}}}}}'
            "]}}}}</script>"
        )
        _state, rows = parse_html(html, SOURCE, ["bangkok"])
        self.assertEqual((rows[0]["latitude"], rows[0]["longitude"]), (0.0, 0.0))

    def test_raw_capture_keeps_only_parsed_business_fields(self):
        state = {
            "session": {"token": "t"},
            "store": {
                "searchResult": {
                    "value": {
                        "data": [
                            {
                                "business": {
                                    "id": 9,
                                    "displayName": "Cafe",
                                    "rUrl": "/restaurants/9-cafe",
                                    "lat": 13.7,
                                    "lng": 100.5,
                                    "contact": {
                                        "address": {"city": {"id": 1}},
                                        "phoneno": "02",
                                        "email": "x@y.z",
                                    },
                                    "statistic": {
                                        "numberOfReviews": 3,
                                        "rating": 4.1,
                                        "topReviewer": "Somchai",
                                    },
                                    "mainPhoto": {
                                        "contentUrl": "https://img/x.jpg",
                                        "uploader": "Somchai",
                                    },
                                    "review": {
                                        "text": "great",
                                        "user": {"name": "Somchai"},
                                    },
                                },
                                "highlight": "user text",
                            }
                        ]
                    }
                }
            },
        }
        trimmed = trimmed_capture(state)
        self.assertEqual(
            trimmed,
            [
                {
                    "id": 9,
                    "displayName": "Cafe",
                    "rUrl": "/restaurants/9-cafe",
                    "lat": 13.7,
                    "lng": 100.5,
                    "contact": {"address": {"city": {"id": 1}}, "phoneno": "02"},
                    "statistic": {"rating": 4.1, "numberOfReviews": 3},
                    "mainPhoto": {"contentUrl": "https://img/x.jpg"},
                }
            ],
        )
        self.assertNotIn("Somchai", repr(trimmed))

    def test_fetch_pages_raw_capture_has_no_page_html(self):
        with patch("restaurants.http.httpx.get", side_effect=[_page(self.html)]):
            raw_pages, rows = fetch_pages(
                SOURCE, ["bangkok"], max_pages=1, page_size=100, min_rows=1
            )
        self.assertNotIn("html", raw_pages[0])
        self.assertGreaterEqual(len(raw_pages[0]["businesses"]), len(rows))


class TextNumberEdgeCaseTests(unittest.TestCase):
    def test_infinite_review_count_does_not_crash(self):
        from restaurants.wongnai_scraper import _integer

        self.assertEqual(_integer(float("inf")), 0)
        self.assertEqual(_integer(float("nan")), 0)
        self.assertEqual(_integer("42"), 42)

    def test_clean_text_drops_zero_width_characters(self):
        from restaurants.wongnai_scraper import _clean_text

        self.assertEqual(_clean_text("\u200bร้าน\u2060อาหาร \ufeff"), "ร้านอาหาร")
        self.assertEqual(_clean_text("\u200b"), "")


if __name__ == "__main__":
    unittest.main()
