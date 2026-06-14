"""
test_fiber_num_sweep.py — locks in the filename → fiber-number rule
==================================================================

Sibling regression test from splice-report commit 05eabe2.  We hit four
silent-failure patterns in real OTDR filenames (trailing spaces before
``.json``, multi-wavelength concatenated suffixes, macOS AppleDouble
sidecars, multi-cable upload collisions) that produced wrong fiber
numbers OR silently overwrote real fiber data with metadata noise.
All four shipped for months without a visible error — techs only
noticed when the report came out empty.

This sweep makes a future regression of any of those four patterns
fail the build instead of shipping silently.  Run from the repo root::

    python3 tests/test_fiber_num_sweep.py

Or in CI: the build-windows workflow's "Verify filename extractor"
step calls this script before the bundle is built.
"""
from __future__ import annotations

import os
import pathlib
import sys

# Make the repo root importable when this is run as a script.
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from unidirectional_event_finder import _extract_fiber_num   # noqa: E402


# (filename, expected fnum) — the recipe's reference table plus a
# handful of patterns specific to this app's real-world data.
EXPECTED = [
    # ── Plain numeric stems ────────────────────────────────────────
    ("LAGDUR0001.sor",                              1),
    ("DURLAG0001.sor",                              1),
    ("LAGDUR0432.sor",                              432),

    # ── Wavelength-suffixed (single λ) ─────────────────────────────
    ("Norsea001_1550.sor",                          1),
    ("Norsea432_1550.sor",                          432),

    # ── Sentence-style stems with dots / hyphens / spaces ──────────
    ("Seattle to Spokane d.0431.sor",               431),
    ("Seattle-Stevens-d.0001.sor",                  1),
    ("20260520_LAGDUR0001.sor",                     1),
    ("fiber 17.json",                               17),

    # ── Pattern 1: trailing space before extension (EXFO JSON) ─────
    ("DURSAN001_1550 .json",                        1),
    ("ELMMIL1152_1550 .json",                       1152),
    ("SANDUR864_1550 .json",                        864),

    # ── Pattern 2: multi-wavelength concatenated suffix ────────────
    ("VERSLK001_131015501625 .json",                1),
    ("VERSLK018_131015501625.trc",                  18),
    ("TEST0001_155016251310.trc",                   1),

    # ── Short-shot / prefix-tagged stems ───────────────────────────
    ("ELMMILsh0001_1550.sor",                       1),
    ("shortTUCROM445_1550.sor",                     445),

    # ── Big trailing numbers that ARE real fiber ids ───────────────
    ("DNW1DNW50007withstartstop.sor",               50007),
    ("TrimmedCHM1CHM20001.sor",                     20001),

    # ── Hyphen-separated cable codes ───────────────────────────────
    ("CHC-HCH-LS-089.trc",                          89),
    ("DNWRCH-A-271.sor",                            271),

    # ── Pattern 3: macOS AppleDouble sidecars must NOT extract ─────
    ("._STRROM0001_1550.sor",                       None),
    ("._DURSAN001_1550 .json",                      None),

    # ── Truly digit-less / wavelength-only stems → None ────────────
    ("LAGDUR.sor",                                  None),
    ("Norsea_1550.sor",                             None),

    # ── This app's canonical regression dataset ────────────────────
    # (CLEYAK / YAKCLE 432-fiber zip used by every smoke test)
    ("CLEYAK001_1550 .json",                        1),
    ("CLEYAK432_1550 .json",                        432),
    ("YAKCLE001_1550 .json",                        1),
    ("YAKCLE432_1550 .json",                        432),
    ("ELMMIL0001_1550.sor",                         1),
    ("ELMMIL1152_1550.sor",                         1152),
]


def main() -> int:
    failures = []
    for fn, expected in EXPECTED:
        got = _extract_fiber_num(fn)
        if got != expected:
            failures.append((fn, expected, got))

    if failures:
        print(f"FAIL: {len(failures)} of {len(EXPECTED)} filenames "
              "returned the wrong fiber number:\n", file=sys.stderr)
        for fn, expected, got in failures:
            print(f"  {fn!r:48s}  expected {expected!r:>6}  got {got!r}",
                  file=sys.stderr)
        print("\nIf the expected value is wrong, update EXPECTED in this "
              "file AND splice-report's matching sweep (commit 05eabe2).  "
              "If the extractor regressed, fix it in "
              "unidirectional_event_finder._extract_fiber_num.",
              file=sys.stderr)
        return 1

    print(f"OK: all {len(EXPECTED)} filename → fiber-number mappings "
          "match expected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
