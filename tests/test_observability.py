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
SECRET_URL = "https://www.wongnai.com/search?q=phone&access_token=tok-abc123"


class FakeLoggingIntegration:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


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
    logging_module = types.ModuleType("sentry_sdk.integrations.logging")
    logging_module.LoggingIntegration = FakeLoggingIntegration  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.logging", logging_module)
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


def test_init_never_sends_locals_bodies_or_messages(sentry, monkeypatch):
    # SPEC-001 AC-06: sentry_sdk.init also installs the excepthook, so an uncaught
    # crash would otherwise carry frame locals and the exception message (page text).
    from restaurants.observability import init_sentry

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    assert init_sentry("test") is not None
    kwargs = sentry.init_kwargs
    assert kwargs["include_local_variables"] is False
    assert kwargs["max_request_body_size"] == "never"
    assert kwargs["send_default_pii"] is False

    event = {
        "message": "ok",
        "request": {"data": SECRET_PAGE_TEXT, "headers": {"Cookie": "token"}},
        "breadcrumbs": {"values": [{"message": SECRET_PAGE_TEXT}]},
        "extra": {"html": SECRET_PAGE_TEXT},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": SECRET_PAGE_TEXT,
                    "stacktrace": {
                        "frames": [
                            {
                                "function": "parse_html",
                                "vars": {"html": SECRET_PAGE_TEXT},
                            }
                        ]
                    },
                }
            ]
        },
        "threads": {
            "values": [{"stacktrace": {"frames": [{"vars": {"token": "secret"}}]}}]
        },
    }
    scrubbed = kwargs["before_send"](event, {})

    assert SECRET_PAGE_TEXT not in repr(scrubbed)
    assert "secret" not in repr(scrubbed)
    assert scrubbed["exception"]["values"][0]["type"] == "ValueError"
    assert (
        scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]["function"]
        == "parse_html"
    )
    assert "request" not in scrubbed


def _before_send(sentry, monkeypatch):
    from restaurants.observability import init_sentry

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    assert init_sentry("test") is not None
    return sentry.init_kwargs["before_send"]


def test_init_turns_off_log_events_and_log_breadcrumbs(sentry, monkeypatch):
    # A logger.error/exception (ours or httpx/urllib3) must not become an event carrying
    # free log text: the logging integration is installed with every level off.
    _before_send(sentry, monkeypatch)
    integrations = sentry.init_kwargs["integrations"]
    logging = [i for i in integrations if isinstance(i, FakeLoggingIntegration)]
    assert len(logging) == 1
    assert logging[0].kwargs == {
        "level": None,
        "event_level": None,
        "sentry_logs_level": None,
    }


def test_sentry_stays_off_without_the_logging_integration(sentry, monkeypatch):
    # Fail closed: if log capture cannot be turned off, do not initialise at all.
    from restaurants.observability import init_sentry

    monkeypatch.delitem(sys.modules, "sentry_sdk.integrations.logging")
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.invalid/1")
    assert init_sentry("test") is None
    assert sentry.init_kwargs is None


def test_scrub_drops_logentry(sentry, monkeypatch):
    before_send = _before_send(sentry, monkeypatch)
    event = {
        "level": "error",
        "logger": "httpx",
        "logentry": {
            "message": "HTTP Request: GET %s",
            "params": [SECRET_URL],
            "formatted": f"HTTP Request: GET {SECRET_URL}",
        },
    }
    scrubbed = before_send(event, {})

    assert "logentry" not in scrubbed
    assert "tok-abc123" not in repr(scrubbed)
    assert scrubbed["level"] == "error"


def test_scrub_keeps_only_the_reporters_own_message(sentry, monkeypatch):
    from restaurants.observability import report_failures

    before_send = _before_send(sentry, monkeypatch)
    assert (
        report_failures(sentry, [{"job": "wongnai_bangkok", "error": "RuntimeError"}])
        == 1
    )
    own = sentry.messages[0][0]
    assert before_send({"message": own}, {})["message"] == own

    foreign = (
        f"HTTP Request: GET {SECRET_URL}",
        f"job wongnai_bangkok failed: {SECRET_PAGE_TEXT}",
        f"job wongnai_bangkok failed: RuntimeError\n{SECRET_PAGE_TEXT}",
        "",
        {"formatted": SECRET_PAGE_TEXT},
    )
    for message in foreign:
        scrubbed = before_send({"message": message, "level": "error"}, {})
        assert "message" not in scrubbed, message
        assert scrubbed["level"] == "error"
