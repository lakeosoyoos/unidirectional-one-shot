"""
conftest.py — shared scaffolding for the test-suite.
=====================================================

This file is intentionally bare-bones:

* It puts the repo root on ``sys.path`` so any test can do
  ``from unidirectional_event_finder import _extract_fiber_num`` (or any
  other engine module) without having to know where the test file lives.
* It exports a handful of well-known paths the rest of the suite can
  import (``APP_PATH``, ``WEB_APP_PATH``, ``FIXTURE_DIR``, ``REPO_ROOT``).
* It provides one helper, ``run_streamlit``, that builds a
  ``streamlit.testing.v1.AppTest`` for an app, runs it once, and hands
  it back — so individual tests don't have to repeat that boilerplate.

Phase 2 Agents B / C / D will import the same helpers from here.
"""
from __future__ import annotations

import pathlib
import sys

import pytest


# ─────────────────────────────────────────────────────────────────────
#  Well-known paths
# ─────────────────────────────────────────────────────────────────────
REPO_ROOT    = pathlib.Path(__file__).resolve().parent.parent
TESTS_DIR    = pathlib.Path(__file__).resolve().parent
APP_PATH     = REPO_ROOT / "desktop" / "desktop_app.py"
WEB_APP_PATH = REPO_ROOT / "streamlit_app.py"
FIXTURE_DIR  = TESTS_DIR / "fixtures" / "cleyak_mini"


# ─────────────────────────────────────────────────────────────────────
#  Make engine modules importable from any test.
#
#  This is the single place that mutates sys.path; individual test
#  files can just `from unidirectional_event_finder import ...` and
#  trust that the repo root is on the path.
# ─────────────────────────────────────────────────────────────────────
for _p in (REPO_ROOT, TESTS_DIR):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)


# ─────────────────────────────────────────────────────────────────────
#  Don't let pytest collect script-style files in tests/.
#
#  test_fiber_num_sweep.py is run as ``python tests/test_fiber_num_sweep.py``
#  from the CI workflow's "Filename → fiber-number regression sweep" step,
#  not via pytest.  It has no ``def test_*`` functions and — fatally —
#  its module-level body reassigns ``sys.stdout`` to force UTF-8.  If
#  pytest imports it for collection that wrecks pytest's capture
#  machinery and the whole run dies before any test executes.
#
#  The standalone script remains green in CI; we just keep it out of
#  pytest's collection pass.
# ─────────────────────────────────────────────────────────────────────
collect_ignore = [
    "test_fiber_num_sweep.py",
]


# ─────────────────────────────────────────────────────────────────────
#  run_streamlit helper
# ─────────────────────────────────────────────────────────────────────
def run_streamlit(app_path, default_timeout: float = 60, **kwargs):
    """Build an ``AppTest`` for ``app_path``, run it once, and return it.

    Parameters
    ----------
    app_path : str | pathlib.Path
        Path to the Streamlit entrypoint module (e.g. ``APP_PATH``).
    default_timeout : float
        Forwarded to ``AppTest.from_file(default_timeout=...)``.
    **kwargs
        Extra keyword args forwarded to ``AppTest.from_file``.

    Notes
    -----
    AppTest reruns the script every time you call ``at.run()`` and uses
    the same ``sys.path`` the test process has, so we don't need to
    re-prepend the repo root here — the module-level loop above already
    did it once per process.
    """
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(app_path), default_timeout=default_timeout, **kwargs)
    at.run()
    return at


# ─────────────────────────────────────────────────────────────────────
#  pytest fixtures — thin wrappers so tests can ask for them by name
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture
def app_path() -> pathlib.Path:
    return APP_PATH


@pytest.fixture
def web_app_path() -> pathlib.Path:
    return WEB_APP_PATH


@pytest.fixture
def fixture_dir() -> pathlib.Path:
    return FIXTURE_DIR
