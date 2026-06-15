"""
test_error_reporter.py — pin the Slack-alert helper's contract

Sibling fix from Secret Sauce 44bce61.  These tests guarantee the four
properties that matter for error_reporter.report_error():

    1. NO-OP without a webhook  — a build that ships without the secret
       must not raise, must not block, must not record a dedup entry.
    2. Records the first call  — a fresh signature is sent immediately.
    3. Dedups within DEDUP_WINDOW_SECS — same (where, type, msg) triple
       does NOT send a second message within the window.
    4. Distinct signatures bypass dedup  — every new (where, type, msg)
       fires immediately, even within the window.
    5. Never raises on bad context — non-JSON-serialisable values,
       enormous strings, None, must all be tolerated.

Uses an UNREACHABLE webhook URL (127.0.0.1 port 9) so the tests never
hit the real Slack endpoint.  We assert against the in-process dedup
table, not against the network — Slack POSTs happen on a daemon thread
that may or may not have run by the time assertions execute.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

# Add repo root so `import error_reporter` works regardless of how
# pytest was invoked.
HERE = os.path.abspath(os.path.dirname(__file__))
ROOT = os.path.abspath(os.path.join(HERE, os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import error_reporter as er


# Unreachable URL — port 9 (discard) on loopback.  Any POST is dropped
# silently; the daemon thread eats the resulting ConnectionRefusedError.
UNREACHABLE = "http://127.0.0.1:9/none"


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Reset the dedup table AND the env var around every test so
    state from one test never bleeds into another."""
    er._reset_dedup_for_tests()
    monkeypatch.delenv(er.ENV_KEY, raising=False)
    yield
    er._reset_dedup_for_tests()


# ─────────────────────────────────────────────────────────────────────
#  1. NO-OP without a webhook
# ─────────────────────────────────────────────────────────────────────

def test_no_op_without_webhook():
    """Empty env → call returns immediately, no dedup entry recorded."""
    # ENV_KEY already deleted by the fixture.
    try:
        raise RuntimeError("simulated failure")
    except RuntimeError as exc:
        er.report_error("test.path", exc)
    assert er._peek_dedup_for_tests() == {}, (
        "report_error recorded a dedup entry when the webhook was unset"
    )


def test_no_op_with_blank_webhook(monkeypatch):
    """Whitespace-only env value is treated as unset."""
    monkeypatch.setenv(er.ENV_KEY, "   \n  ")
    try:
        raise ValueError("blank webhook")
    except ValueError as exc:
        er.report_error("test.path", exc)
    assert er._peek_dedup_for_tests() == {}


# ─────────────────────────────────────────────────────────────────────
#  2 + 3. Record then dedup
# ─────────────────────────────────────────────────────────────────────

def test_first_call_records_then_dedups(monkeypatch):
    """Same (where, type, str) within DEDUP_WINDOW_SECS sends once."""
    monkeypatch.setenv(er.ENV_KEY, UNREACHABLE)

    try:
        raise RuntimeError("oops")
    except RuntimeError as exc:
        er.report_error("desktop._run_engine", exc)

    snap1 = er._peek_dedup_for_tests()
    assert len(snap1) == 1, "first call should have recorded one entry"
    key = ("desktop._run_engine", "RuntimeError", "oops")
    assert key in snap1, f"expected dedup key {key!r}, got {list(snap1)}"
    first_time = snap1[key]

    # Second call with the same triple within the window — must be
    # suppressed (timestamp unchanged).
    try:
        raise RuntimeError("oops")
    except RuntimeError as exc:
        er.report_error("desktop._run_engine", exc)
    snap2 = er._peek_dedup_for_tests()
    assert len(snap2) == 1, "second call should not have added a new entry"
    assert snap2[key] == first_time, (
        "second call within window should NOT have refreshed the timestamp"
    )


# ─────────────────────────────────────────────────────────────────────
#  4. Distinct signatures bypass dedup
# ─────────────────────────────────────────────────────────────────────

def test_distinct_errors_each_record(monkeypatch):
    """Different (where, type, msg) triples each fire immediately."""
    monkeypatch.setenv(er.ENV_KEY, UNREACHABLE)

    try:
        raise RuntimeError("oops")
    except RuntimeError as exc:
        er.report_error("desktop._run_engine", exc)

    try:
        raise ValueError("different type")
    except ValueError as exc:
        er.report_error("desktop._run_engine", exc)

    try:
        raise RuntimeError("oops")
    except RuntimeError as exc:
        er.report_error("write_xlsx.audit_sheet", exc)   # different where

    try:
        raise RuntimeError("oops two")
    except RuntimeError as exc:
        er.report_error("desktop._run_engine", exc)      # different msg

    snap = er._peek_dedup_for_tests()
    assert len(snap) == 4, (
        f"expected 4 distinct dedup entries, got {len(snap)}: {list(snap)}"
    )


def test_dedup_expires_after_window(monkeypatch):
    """Once DEDUP_WINDOW_SECS has elapsed, the same signature fires."""
    monkeypatch.setenv(er.ENV_KEY, UNREACHABLE)

    try:
        raise RuntimeError("expiry test")
    except RuntimeError as exc:
        er.report_error("desktop._run_engine", exc)

    key = ("desktop._run_engine", "RuntimeError", "expiry test")
    snap = er._peek_dedup_for_tests()
    assert key in snap

    # Manually age the recorded timestamp past the window.
    with er._LOCK:
        er._LAST_SENT[key] = time.time() - (er.DEDUP_WINDOW_SECS + 10)

    try:
        raise RuntimeError("expiry test")
    except RuntimeError as exc:
        er.report_error("desktop._run_engine", exc)

    snap_after = er._peek_dedup_for_tests()
    # Same key, but the timestamp is now FRESH (not the aged value).
    assert snap_after[key] > time.time() - 10, (
        "post-window call should have refreshed the timestamp"
    )


# ─────────────────────────────────────────────────────────────────────
#  5. Bad context never raises
# ─────────────────────────────────────────────────────────────────────

class _BadRepr:
    """An object whose repr() blows up — emulates a context value that
    a careless caller might pass."""
    def __repr__(self):
        raise RuntimeError("repr() exploded")


def test_never_raises_on_bad_context(monkeypatch):
    """Non-serialisable / explosive context values must be swallowed."""
    monkeypatch.setenv(er.ENV_KEY, UNREACHABLE)

    weird_contexts = [
        ("none",       None),
        ("empty",      {}),
        ("bad_repr",   {"x": _BadRepr()}),           # repr() raises
        ("giant_str",  {"big": "X" * 10_000}),        # giant string
        ("many_keys",  {str(i): i for i in range(500)}),
        ("nested",     {"none_value": None, "nested": {"a": [1, 2]}}),
    ]
    for label, ctx in weird_contexts:
        try:
            # Unique error message per ctx so dedup doesn't collapse
            # them (NoneType / dict / dict / dict / dict / dict would
            # all share a TypeError signature otherwise).
            raise TypeError(f"ctx={label}")
        except TypeError as exc:
            # Must not raise.
            er.report_error("test.bad_context", exc, context=ctx)

    # All six distinct messages → 6 entries.
    snap = er._peek_dedup_for_tests()
    assert len(snap) == 6, f"expected 6 distinct entries, got {len(snap)}"


# ─────────────────────────────────────────────────────────────────────
#  6. Network failure is silently swallowed (URL unreachable)
# ─────────────────────────────────────────────────────────────────────

def test_unreachable_webhook_does_not_raise(monkeypatch):
    """A reachable-but-bad URL must NOT propagate a connection error
    back into the caller's path.  The whole point of the daemon
    thread + bare-except in _post is to absorb network failures."""
    monkeypatch.setenv(er.ENV_KEY, UNREACHABLE)

    try:
        # In Python 3 IOError is an alias for OSError; the recorded
        # type name is "OSError".
        raise OSError("network test")
    except OSError as exc:
        er.report_error("test.network", exc)

    # If we got here, _post's swallow-everything worked.
    # The dedup entry is recorded BEFORE the network attempt — that's
    # the intended order so a flapping network doesn't unsilence
    # the dedup.
    assert ("test.network", "OSError", "network test") in er._peek_dedup_for_tests()
