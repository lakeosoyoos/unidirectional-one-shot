#!/usr/bin/env python3
"""
send_test_alert.py — one-shot Slack-alert smoke test
====================================================

Usage::

    SS_ERROR_WEBHOOK="<your webhook url>" \\
        python3 scripts/send_test_alert.py

The webhook URL is read from the environment ONCE for this process,
sent through error_reporter.report_error with a synthetic
``RuntimeError``, and then discarded.  Nothing is written to disk.

This is the same helper Secret Sauce uses to verify the alert format
lands in Slack the first time the webhook is set up — confirm one
message arrives in the channel, then never run this script again
(subsequent runs in the same hour will dedup silently anyway).

Exit code 0 on send-attempt scheduled, 1 if the webhook env var was
missing.
"""
from __future__ import annotations

import os
import pathlib
import sys
import time


HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import error_reporter   # noqa: E402


def main() -> int:
    if not os.environ.get(error_reporter.ENV_KEY, "").strip():
        print(f"ERROR: ${error_reporter.ENV_KEY} is not set.  Pipe your "
              "Slack webhook URL in for one run:")
        print(f"  {error_reporter.ENV_KEY}=\"https://hooks.slack.com/...\" "
              "python3 scripts/send_test_alert.py")
        return 1

    # Reset the dedup table in this process so the alert always fires.
    error_reporter._reset_dedup_for_tests()

    # Mark this as a smoke test in the message so it's obvious to
    # anyone reading the channel that it's not a real failure.
    try:
        raise RuntimeError(
            "Smoke test from scripts/send_test_alert.py — confirms the "
            "webhook is wired correctly and the message format renders.  "
            "If you see this in #alerts (or wherever the channel is), "
            "Slack error reporting is ON."
        )
    except RuntimeError as exc:
        error_reporter.report_error(
            where="smoke_test.manual",
            exc=exc,
            context={
                "purpose":   "verify webhook + format",
                "app":       error_reporter.APP_NAME,
                "instructions": "no follow-up needed; safe to delete",
            },
        )

    # Give the daemon thread a couple of seconds to send before we exit.
    time.sleep(3)
    print(f"Sent one alert via report_error to Slack.  Check the channel "
          f"the webhook is wired to.  (App tag: {error_reporter.APP_NAME!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
