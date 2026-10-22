"""Crash-safe export writes and runner output-dir validation."""

import csv
import io
from contextlib import redirect_stderr
from unittest.mock import patch

import pytest


from restaurants.atomic_io import append_csv_atomic, write_text_atomic
from restaurants.wongnai_scraper import HISTORY_FIELDS, append_history, write_snapshot
from scripts.run_restaurants import main as restaurants_main

ROW = {"restaurant_id": "1", "name": 'Khao "Man" Gai, Pratunam', "rating": 4.5}


def test_write_text_atomic_keeps_previous_file_when_replace_fails(tmp_path):
    target = tmp_path / "snap.csv"
    target.write_text("previous", encoding="utf-8")
    with patch("restaurants.atomic_io.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            write_text_atomic(target, "partial")
    assert target.read_text(encoding="utf-8") == "previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snap.csv"]


def test_snapshot_render_failure_keeps_old_snapshot(tmp_path):
    path = write_snapshot([ROW], "2026-09-01T00:00:00Z", tmp_path, "demo")
    before = path.read_text(encoding="utf-8")
    with patch(
        "restaurants.wongnai_scraper.render_csv", side_effect=RuntimeError("boom")
    ):
        with pytest.raises(RuntimeError):
            write_snapshot([ROW], "2026-09-02T00:00:00Z", tmp_path, "demo")
    assert path.read_text(encoding="utf-8") == before


def test_history_appends_with_single_header_and_quotes(tmp_path):
    append_history([ROW], "2026-09-01T00:00:00Z", tmp_path, "demo")
    path = append_history(
        [{**ROW, "restaurant_id": "2"}], "2026-09-02T00:00:00Z", tmp_path, "demo"
    )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["restaurant_id"] for r in rows] == ["1", "2"]
    assert rows[0]["name"] == 'Khao "Man" Gai, Pratunam'


def test_history_append_repairs_missing_trailing_newline(tmp_path):
    path = tmp_path / "h.csv"
    path.write_text(",".join(HISTORY_FIELDS), encoding="utf-8")
    append_csv_atomic(path, [{"restaurant_id": "9"}], HISTORY_FIELDS)
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["restaurant_id"] for r in rows] == ["9"]


def test_main_rejects_output_dir_that_is_a_file(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit) as ctx:
            restaurants_main(["--output-dir", str(blocker), "--dry-run"])
    assert ctx.value.code == 2
