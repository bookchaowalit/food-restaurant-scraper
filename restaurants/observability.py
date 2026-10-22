"""Opt-in Sentry for scheduled runs.

Off unless ``SENTRY_DSN`` is set and ``sentry_sdk`` is importable. The runner isolates
each job and turns an exception into an error row plus exit code 1, so without this a
failing scheduled run only shows up in the cron log. :func:`report_failures` sends one
event per failed job carrying only the job name and the exception class: no page
content, listing data or personal data is attached (``send_default_pii`` is off).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from importlib import import_module
from types import ModuleType
from typing import Any


def init_sentry(component: str) -> ModuleType | None:
    """Initialise Sentry for one run; return the SDK, or None when it is off."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return None
    try:
        sdk = import_module("sentry_sdk")
    except ImportError:
        return None
    sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "local"),
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
    sdk.set_tag("component", component)
    return sdk


def report_failures(
    sdk: ModuleType | None, results: Iterable[Mapping[str, Any]]
) -> int:
    """Send one ``error`` event per result row with an ``error`` key; return how many."""
    if sdk is None:
        return 0
    sent = 0
    for result in results:
        error = result.get("error")
        if not error:
            continue
        sdk.capture_message(
            f"job {result.get('job', '?')} failed: {error}", level="error"
        )
        sent += 1
    if sent:
        sdk.flush(timeout=5)
    return sent
