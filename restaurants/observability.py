"""Opt-in Sentry for scheduled runs.

Off unless ``SENTRY_DSN`` is set and ``sentry_sdk`` is importable. The runner isolates
each job and turns an exception into an error row plus exit code 1, so without this a
failing scheduled run only shows up in the cron log. :func:`report_failures` sends one
event per failed job carrying only the job name and the exception class.

``sentry_sdk.init`` also installs the excepthook, so an uncaught crash is reported too.
Such an event must not carry page content, listing data, tokens or personal data, so
init turns off local variables and request bodies, and :func:`scrub_event` drops frame
variables, exception messages, request data, breadcrumbs and extras from every event
(only exception types, function names and tags remain). ``send_default_pii`` is off.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from importlib import import_module
from types import ModuleType
from typing import Any

_DROPPED_EVENT_KEYS = ("request", "breadcrumbs", "extra", "user", "contexts")


def _strip_frames(container: Any) -> None:
    stacktrace = container.get("stacktrace") if isinstance(container, dict) else None
    frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else None
    for frame in frames if isinstance(frames, list) else []:
        if isinstance(frame, dict):
            for key in ("vars", "pre_context", "context_line", "post_context"):
                frame.pop(key, None)


def scrub_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """``before_send``: keep exception types, frames' locations and tags; drop the rest."""
    for key in _DROPPED_EVENT_KEYS:
        event.pop(key, None)
    for section in ("exception", "threads"):
        block = event.get(section)
        values = block.get("values") if isinstance(block, dict) else None
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                continue
            if section == "exception":
                value["value"] = ""
            _strip_frames(value)
    return event


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
        include_local_variables=False,
        max_request_body_size="never",
        before_send=scrub_event,
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
