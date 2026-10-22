import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


from scripts.run_restaurants import JOBS, main, run_restaurants


class RunRestaurantsTests(unittest.TestCase):
    def test_job_roster(self):
        self.assertEqual(
            [job["name"] for job in JOBS],
            ["wongnai_bangkok", "wongnai_upcountry"],
        )

    def test_dry_run_does_not_collect(self):
        with tempfile.TemporaryDirectory() as directory:
            result = asyncio.run(run_restaurants(Path(directory), dry_run=True))
        self.assertEqual([item["status"] for item in result], ["dry-run", "dry-run"])
        self.assertTrue(all(item["network"] == "not-used" for item in result))

    def test_failing_job_does_not_block_the_next_one(self):
        calls = []

        async def fake_run(self, max_pages=3, **_kwargs):
            calls.append(self.output_stem)
            if self.output_stem == "wongnai_bangkok":
                raise RuntimeError("page content must not leak")
            return [{"source": self.output_stem, "count": 7}]

        with tempfile.TemporaryDirectory() as directory:
            with patch("restaurants.wongnai_scraper.WongnaiScraper.run", fake_run):
                result = asyncio.run(run_restaurants(Path(directory)))
        self.assertEqual(calls, ["wongnai_bangkok", "wongnai_upcountry"])
        self.assertEqual(result[0], {"job": "wongnai_bangkok", "error": "RuntimeError"})
        self.assertEqual(result[1]["count"], 7)

    def test_cli_rejects_out_of_range_values_before_any_work(self):
        for argv in (
            ["--max-pages", "0"],
            ["--max-pages", "6"],
            ["--min-rows", "0"],
            ["--min-rows", "x"],
        ):
            with self.subTest(argv=argv), patch("sys.stderr"):
                with self.assertRaises(SystemExit) as ctx:
                    main([*argv, "--dry-run"])
                self.assertEqual(ctx.exception.code, 2)

    def test_cli_dry_run_accepts_bounds(self):
        with patch("sys.stdout"):
            self.assertEqual(
                main(["--max-pages", "5", "--min-rows", "500", "--dry-run", "--json"]),
                0,
            )


if __name__ == "__main__":
    unittest.main()
