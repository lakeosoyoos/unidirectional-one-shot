Test fixtures for Unidirectional One Shot
=========================================

cleyak_mini/
    Subset of YAKCLE432_1550 JSON exports from the Cle Elum to Yakima OTDR
    run (fibers 001-025, ~1.8 MB). Used by tests/test_e2e_run.py to exercise
    the full desktop_app.py "Run" flow end-to-end. The 25-fiber slice was
    chosen so that the engine's MIN_POP_SPLICE = 20 threshold is comfortably
    cleared and splice discovery actually fires.

    Provenance: real EXFO FastReporter exports from the customer's own
    acquisitions. Trailing space before .json is the original filename
    pattern (Pattern 1 from tests/test_fiber_num_sweep.py).

Total fixture size on disk: under 10 MB. Do not add more fixtures here
without checking that the total stays small.
