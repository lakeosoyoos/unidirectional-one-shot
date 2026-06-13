# -*- mode: python ; coding: utf-8 -*-
# ----------------------------------------------------------------------
# UnidirectionalOneShot.spec — PyInstaller spec for the local desktop
# build of Unidirectional One Shot.
#
# This file is the result of multiple production failures.  Each block
# below is annotated with the failure mode it prevents — please leave
# the comments and the belt-and-braces redundancy in place.
#
# Reference: ../README_BUILD.txt
# ----------------------------------------------------------------------
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_submodules,
)


APP_NAME    = "UnidirectionalOneShot"
HERE        = Path(SPECPATH).resolve()
REPO_ROOT   = HERE.parent


# ─────────────────────────────────────────────────────────────────────
#  Layer 1: collect_all for each heavy 3rd-party package Streamlit
#  reaches into at import time.  collect_all returns (datas,
#  binaries, hiddenimports) — we merge them all.
# ─────────────────────────────────────────────────────────────────────
datas, binaries, hiddenimports = [], [], []


def _safe_collect_all(pkg):
    """Some packages aren't installed on every dev machine (e.g.
    pyarrow on Apple Silicon when Streamlit isn't using it).  Don't
    crash the build on those — collect what we can."""
    try:
        d, b, h = collect_all(pkg)
        datas.extend(d); binaries.extend(b); hiddenimports.extend(h)
    except Exception as exc:
        print(f"[spec] collect_all skipped for {pkg!r}: {exc}")


for pkg in (
    "streamlit",
    "altair",
    "pyarrow",
    "numpy",
    "pandas",
    "openpyxl",
    "reportlab",
):
    _safe_collect_all(pkg)


# ─────────────────────────────────────────────────────────────────────
#  Layer 2: bundle pkg_resources + setuptools and their _vendor tree.
#
#  Failure prevented: at first launch the windowed app crashes with
#       "the jaraco package is required"
#  because Streamlit imports pkg_resources, pkg_resources tries to load
#  its vendored jaraco.text / jaraco.functools / packaging /
#  platformdirs / appdirs / more_itertools / ordered_set, and PyInstaller
#  missed the _vendor subtree.  Belt-and-braces fix:
#    a) collect every submodule of pkg_resources + setuptools
#    b) collect their data files (where _vendor lives)
#    c) install the vendored packages as REAL top-level packages so
#       pkg_resources' extern-importer has a runtime fallback (this is
#       done in requirements-desktop.txt; here we just add them as
#       hiddenimports)
#    d) collect_all each one too for good measure
# ─────────────────────────────────────────────────────────────────────
hiddenimports += collect_submodules("pkg_resources")
hiddenimports += collect_submodules("setuptools")
datas         += collect_data_files("pkg_resources")
datas         += collect_data_files("setuptools")

for vendored in (
    "jaraco", "jaraco.text", "jaraco.functools", "jaraco.context",
    "more_itertools", "packaging", "platformdirs", "appdirs",
    "ordered_set",
):
    _safe_collect_all(vendored)
    hiddenimports.append(vendored)


# ─────────────────────────────────────────────────────────────────────
#  Layer 3: hiddenimports for OUR engine + UI modules and the standard-
#  library bits Streamlit / launcher reach into.  PyInstaller's static
#  analysis misses anything imported via importlib.
# ─────────────────────────────────────────────────────────────────────
hiddenimports += [
    # Engine + readers
    "unidirectional_event_finder",
    "sor_reader324802a",
    "json_reader",
    "acquisition_audit",
    # Custom Streamlit component
    "components",
    "components.otdr_settings",
    # Folder picker
    "tkinter",
    "tkinter.filedialog",
    # Streamlit reaches in via importlib at runtime
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
]


# ─────────────────────────────────────────────────────────────────────
#  Bundle our own source files as data
# ─────────────────────────────────────────────────────────────────────
#  These live at the bundle ROOT so the launcher can find them whether
#  it's running auto-updated copies or the bundled copies.
datas += [
    (str(REPO_ROOT / "unidirectional_event_finder.py"), "."),
    (str(REPO_ROOT / "sor_reader324802a.py"),           "."),
    (str(REPO_ROOT / "json_reader.py"),                 "."),
    (str(REPO_ROOT / "acquisition_audit.py"),           "."),
    (str(HERE      / "desktop_app.py"),                 "desktop"),
    # Custom component — both .py AND the index.html
    (str(REPO_ROOT / "components" / "otdr_settings" / "__init__.py"),
        "components/otdr_settings"),
    (str(REPO_ROOT / "components" / "otdr_settings" / "index.html"),
        "components/otdr_settings"),
]


# ─────────────────────────────────────────────────────────────────────
#  Excludes — keep the bundle from accidentally pulling in stuff we
#  don't use.  weasyprint and PyQt are the usual offenders for size
#  blow-up and native-lib pain.
# ─────────────────────────────────────────────────────────────────────
excludes = [
    "weasyprint",
    "PyQt5", "PyQt6",
    "PySide2", "PySide6",
    "tk_test", "test", "unittest", "tests",
]


# ─────────────────────────────────────────────────────────────────────
#  Analysis
# ─────────────────────────────────────────────────────────────────────
a = Analysis(
    [str(HERE / "launcher.py")],
    pathex=[str(REPO_ROOT), str(HERE)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)


pyz = PYZ(a.pure, a.zipped_data, cipher=None)


# ─────────────────────────────────────────────────────────────────────
#  EXE — console=False is critical.  A console=True build prints
#  bootstrap diagnostics but Windows users will see a black terminal
#  window every launch.  We want the windowed UX with logs redirected
#  to ~/.unidirectionaloneshot/unidirectionaloneshot.log (handled in
#  launcher._redirect_output_to_log).
# ─────────────────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # UPX has historically corrupted bundled .pyd
                          # files on Windows — leave it off.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)


# ─────────────────────────────────────────────────────────────────────
#  COLLECT — one-folder build.  One-file (--onefile) sometimes runs
#  the whole bundle through a self-extracting stub that fails on
#  Windows AV scanners.  One-folder is slower to copy but boots
#  faster and survives EDR.
# ─────────────────────────────────────────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
