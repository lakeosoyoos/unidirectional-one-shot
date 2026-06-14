#!/usr/bin/env python3
"""
check_port_assignment.py — fail the build if the launcher binds the
wrong port.

Every desktop app in our stack claims a unique loopback port so a tech
who runs more than one doesn't get the wrong app's browser tab on
double-click.  Current registry:

    Secret Sauce      127.0.0.1:8501
    SpliceReport      127.0.0.1:8503
    Unidirectional    127.0.0.1:8505   ← THIS APP

This script greps ``desktop/launcher.py`` for the literal::

    PORT = 8505

and exits non-zero (failing the CI build) if the literal differs or is
missing.  A future maintainer who accidentally sets PORT back to 8501
gets a loud red CI failure instead of shipping a launcher that opens
into Secret Sauce.

Run from the repo root:
    python3 scripts/check_port_assignment.py
"""
from __future__ import annotations

import io
import pathlib
import re
import sys

# Windows' default Python stdout encoding is cp1252; printing any non-
# ASCII character (e.g. ✓ / →) crashes the CI step with
# UnicodeEncodeError before the assertion message lands.  Force UTF-8
# so future maintainers can use whatever characters make the message
# clearest.  No-op on macOS / Linux runners that already use UTF-8.
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


EXPECTED_PORT = 8505
LAUNCHER      = pathlib.Path(__file__).resolve().parent.parent / "desktop" / "launcher.py"

# Ports our other apps claim — flagged here so the message is helpful.
CLAIMED_ELSEWHERE = {
    8501: "Secret Sauce",
    8503: "SpliceReport",
}


def main() -> int:
    if not LAUNCHER.exists():
        print(f"ERROR: {LAUNCHER} not found", file=sys.stderr)
        return 1

    src = LAUNCHER.read_text(encoding="utf-8")
    match = re.search(r"^PORT\s*=\s*(\d+)", src, re.M)
    if not match:
        print(f"ERROR: {LAUNCHER.name} has no ``PORT = <int>`` constant "
              "on its own line.  The launcher's port must live in a "
              "single regex-matchable constant so this check can guard "
              "it.", file=sys.stderr)
        return 1

    port = int(match.group(1))
    if port == EXPECTED_PORT:
        print(f"OK: {LAUNCHER.name} binds PORT = {port} "
              f"(Unidirectional One Shot's reserved port).")
        return 0

    other_app = CLAIMED_ELSEWHERE.get(port)
    if other_app:
        print(f"FAIL: {LAUNCHER.name} has PORT = {port}, which is "
              f"{other_app}'s port.  Launching this app on that port "
              "would open a tab to the wrong app on any tech who already "
              "runs both.  Set PORT back to "
              f"{EXPECTED_PORT}.", file=sys.stderr)
    else:
        print(f"FAIL: {LAUNCHER.name} has PORT = {port}, expected "
              f"{EXPECTED_PORT}.  Don't reuse 8501 (Secret Sauce) or "
              f"8503 (SpliceReport).  If the change was intentional, "
              "update EXPECTED_PORT in scripts/check_port_assignment.py "
              "AND the registry in desktop/README_BUILD.txt.",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
