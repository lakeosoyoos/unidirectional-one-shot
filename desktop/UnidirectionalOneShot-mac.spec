# -*- mode: python ; coding: utf-8 -*-
# ----------------------------------------------------------------------
# UnidirectionalOneShot-mac.spec — PyInstaller spec for the LOCAL Mac
# preview build.
#
# This is byte-for-byte the same defensive bundling as the production
# Windows spec (3-layer pkg_resources / jaraco / vendored-package
# coverage, identical hiddenimports, identical excludes, identical
# collect_all targets) with ONE addition: a BUNDLE() step that wraps
# the one-folder COLLECT into a proper .app the developer can double-
# click in Finder.
#
# Purpose: catch OS-INDEPENDENT packaging bugs (the setuptools pin,
# missing hiddenimports for our own modules, the Streamlit first-run
# prompt hang) on the dev laptop BEFORE we burn a Windows CI cycle.
#
# A green Mac build does NOT prove the Windows build works.  The Mac
# may have vendored packages installed incidentally and uses a
# different Python.  The Windows CI BOOT SELF-TEST is the only thing
# that verifies the tech's app.
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
#  Layer 1: collect_all for every heavy 3rd-party package Streamlit
#  reaches into at import time.
# ─────────────────────────────────────────────────────────────────────
datas, binaries, hiddenimports = [], [], []


def _safe_collect_all(pkg):
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
#  Layer 2: bundle pkg_resources + setuptools + their _vendor tree.
#  Without all three approaches, the windowed app crashes at startup
#  with "the jaraco package is required".  See spec comments in the
#  Windows version for the full failure-mode catalog.
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
#  library bits Streamlit / launcher reach into via importlib.
# ─────────────────────────────────────────────────────────────────────
hiddenimports += [
    "unidirectional_event_finder",
    "sor_reader324802a",
    "json_reader",
    "acquisition_audit",
    "components",
    "components.otdr_settings",
    "tkinter",
    "tkinter.filedialog",
    "streamlit.web.cli",
    "streamlit.runtime.scriptrunner.magic_funcs",
]


# ─────────────────────────────────────────────────────────────────────
#  Bundle our own source files as data
# ─────────────────────────────────────────────────────────────────────
datas += [
    (str(REPO_ROOT / "unidirectional_event_finder.py"), "."),
    (str(REPO_ROOT / "sor_reader324802a.py"),           "."),
    (str(REPO_ROOT / "json_reader.py"),                 "."),
    (str(REPO_ROOT / "acquisition_audit.py"),           "."),
    (str(HERE      / "desktop_app.py"),                 "desktop"),
    (str(REPO_ROOT / "components" / "otdr_settings" / "__init__.py"),
        "components/otdr_settings"),
    (str(REPO_ROOT / "components" / "otdr_settings" / "index.html"),
        "components/otdr_settings"),
]


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
#  EXE — console=False, just like the Windows build.  Logs are
#  captured into ~/.unidirectionaloneshot/unidirectionaloneshot.log
#  by launcher._redirect_output_to_log().
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
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)


# ─────────────────────────────────────────────────────────────────────
#  COLLECT — same one-folder layout as Windows.
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


# ─────────────────────────────────────────────────────────────────────
#  BUNDLE — the only thing the Mac spec adds.  Wraps the COLLECT
#  output into a proper double-clickable .app so the developer can
#  put it on the Desktop and test exactly what the tech will see on
#  Windows.  icon=None means PyInstaller's stock generic icon —
#  drop an .icns into this folder + reference it here to brand it.
# ─────────────────────────────────────────────────────────────────────
app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=None,
    bundle_identifier="com.lakeosoyoos.unidirectionaloneshot",
    info_plist={
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion":            "1.0.0",
        "NSHighResolutionCapable":    True,
        # Stop the .app from showing a Dock icon for the (invisible)
        # launcher process — it's a server, not a normal Mac app.
        "LSUIElement":                False,
    },
)
