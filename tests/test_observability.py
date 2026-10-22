"""SPEC-001 AC-01..AC-03: a failed restaurant job reaches Sentry, opt-in only.

``run_restaurants`` isolates each job and turns an exception into
``{"job": ..., "error": "<ExceptionClass>"}`` plus exit code 1, so a failing
scheduled run is invisible unless someone reads the cron log. These tests pin
that, with ``SENTRY_DSN`` set, every failed job becomes one Sentry event that
carries only the job name and the exception class (never page content), and
that nothing is initialised without a DSN. No network: the scraper and
``sentry_sdk`` are fakes.
"""

import sys
import types
from unittest import mock

import pytest

from restaurants.wongnai_scraper import WongnaiScraper
from scripts.run_restaurants import main

SECRET_PAGE_TEXT = "seller phone 081-234-5678"


class FakeSentry(types.ModuleType):
    def __init__(self):
        super().__init__("sentry_sdk")
        self.init_kwargs = None
        self.messages = []
        self.tags = {}

    def init(self, **kwargs):
        self.init_kwargs = kwargs

    def set_tag(self, key, value):
        self.tags[key] = value

    def capture_message(self, message, level=None):
        self.messages.append((message, level))

    def flush(self, timeout=None):
        return None


@pytest.fixture
def sentry(monkeypatch):
    fake = FakeSentry()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
    return fake


async def _failing_run(self, max_pages=3, **_kwargs):
    # Only the Bangkok job fails; the upcountry job still runs and succeeds.
    if self.output_stem == "wongnai_bangkok":
        raise RuntimeError(SECRET_PAGE_TEXT)
    return [{"source": self.output_stem, "count": 3}]


async def _ok_run(self, max_pages=3, **_kwargs):
    return [{"source": self.output_stem, "count": 3}]


def test_failed_job_reaches_sentry(sentry, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    with mock.patch.object(WongnaiScraper, "run", _failing_run):
        code = main(["--output-dir", str(tmp_path)])

    assert code == 1
    assert len(sentry.messages) == 1, sentry.messages
    message, level = sentry.messages[0]
    assert level == "error"
    assert "wongnai_bangkok" in message and "RuntimeError" in message
    assert "wongnai_upcountry" not in message
    assert SECRET_PAGE_TEXT not in message
    assert sentry.init_kwargs["send_default_pii"] is False
    assert sentry.init_kwargs["traces_sample_rate"] == 0.0
    assert sentry.init_kwargs["environment"] == "test"


def test_successful_run_sends_nothing(sentry, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    with mock.patch.object(WongnaiScraper, "run", _ok_run):
        code = main(["--output-dir", str(tmp_path)])

    assert code == 0
    assert sentry.messages == []


def test_without_dsn_sentry_stays_off(sentry, tmp_path):
    with mock.patch.object(WongnaiScraper, "run", _failing_run):
        code = main(["--output-dir", str(tmp_path)])

    assert code == 1
    assert sentry.init_kwargs is None
    assert sentry.messages == []


def test_dry_run_never_initialises_sentry(sentry, monkeypatch, tmp_path):
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    code = main(["--dry-run", "--output-dir", str(tmp_path)])

    assert code == 0
    assert sentry.init_kwargs is None
