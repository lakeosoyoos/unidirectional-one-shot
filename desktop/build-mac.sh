#!/usr/bin/env bash
# ----------------------------------------------------------------------
# build-mac.sh — LOCAL Mac .app preview build of UnidirectionalOneShot.
#
# WHAT THIS IS FOR (read before touching):
#   • This is the maintainer's LOCAL preview.  It lets you double-click
#     a .app in Finder on macOS and see/click the same UI a Windows tech
#     will get from the Release zip.
#   • It also flushes OS-INDEPENDENT packaging bugs (missing
#     hiddenimports for our own modules, the setuptools pin, the
#     Streamlit first-run prompt hang) before we burn a Windows CI cycle.
#   • A green Mac build does NOT prove the Windows build works.  The
#     Mac may have vendored packages installed incidentally and uses a
#     different Python.  The Windows CI BOOT SELF-TEST in
#     ../.github/workflows/build-windows.yml is the only thing that
#     verifies the tech's app.
#
# PYTHON (read before changing this):
#   We use the Mac's BUILT-IN /usr/bin/python3 (currently 3.9.x).  This
#   matches what built the working Secret Sauce Mac app.  Any Python
#   BELOW 3.12 works because we pin setuptools==65.5.1 and 3.12 removed
#   pkgutil.ImpImporter — which 65.5.1's pkg_resources requires.
#   DO NOT install 3.11 or 3.12 just for this build; the system python3
#   is fine and what the maintainer has tested with.
#
# RUN FROM:  desktop/
# OUTPUT:    desktop/dist/UnidirectionalOneShot.app
#            (copied to ~/Desktop/UnidirectionalOneShot.app for easy
#            double-click testing)
# ----------------------------------------------------------------------

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

PY="/usr/bin/python3"
APP_NAME="UnidirectionalOneShot"

# --- Sanity check: not 3.12+ -----------------------------------------
ver_major="$("$PY" -c 'import sys; print(sys.version_info.major)')"
ver_minor="$("$PY" -c 'import sys; print(sys.version_info.minor)')"
echo "Using $PY ($("$PY" -V))"

if [ "$ver_major" -ne 3 ] || [ "$ver_minor" -ge 12 ]; then
    cat <<EOF >&2

ERROR: detected Python $ver_major.$ver_minor.  Mac build needs Python
       BELOW 3.12 because setuptools 65.5.1 depends on pkgutil.ImpImporter
       (removed in 3.12).  On macOS 13/14 the system /usr/bin/python3 is
       3.9.x, which is what we want.  If yours has been replaced, point
       PY in this script at /usr/bin/python3 explicitly or install an
       older python.org build.
EOF
    exit 1
fi

# --- Install build deps to the USER site (no venv) --------------------
# The recipe explicitly calls for --user installs into the system
# python3 — matches the existing Secret Sauce Mac build setup.  This
# means we don't need to manage a venv across rebuilds.
echo "Installing build deps to user site..."
"$PY" -m pip install --user --upgrade pip wheel

# Step 1: pin setuptools FIRST so transitive installs can't pick a newer one
"$PY" -m pip install --user "setuptools==65.5.1"

# Step 2: the rest of requirements-desktop.txt
"$PY" -m pip install --user -r requirements-desktop.txt

# Step 3: re-pin setuptools LAST in case any of the above bumped it
"$PY" -m pip install --user --upgrade --force-reinstall "setuptools==65.5.1"

# --- Locate PyInstaller (installed to --user bin) ---------------------
# /usr/bin/python3 with --user puts entry-point scripts in
# ~/Library/Python/<ver>/bin.  Use python -m PyInstaller to be
# version-independent.
echo "Verifying PyInstaller import..."
"$PY" -m PyInstaller --version

# --- Clean previous artifacts ----------------------------------------
rm -rf build dist

# --- Build ------------------------------------------------------------
echo "Running PyInstaller against ${APP_NAME}-mac.spec ..."
"$PY" -m PyInstaller "${APP_NAME}-mac.spec" --noconfirm --clean

# --- Copy the .app to ~/Desktop/ for easy double-click testing -------
APP_SRC="dist/${APP_NAME}.app"
APP_DST="$HOME/Desktop/${APP_NAME}.app"

if [ ! -d "$APP_SRC" ]; then
    echo "ERROR: $APP_SRC was not produced by PyInstaller." >&2
    exit 1
fi

if [ -d "$APP_DST" ]; then
    echo "Removing previous $APP_DST ..."
    rm -rf "$APP_DST"
fi
cp -R "$APP_SRC" "$APP_DST"

# Strip the quarantine attribute so Gatekeeper doesn't refuse the
# first launch.  Equivalent to right-click → Open → Open.
xattr -dr com.apple.quarantine "$APP_DST" 2>/dev/null || true

cat <<EOF

----------------------------------------------------------
 Mac .app build succeeded.

 Local preview:
   $APP_DST

 Original (in dist/):
   $(cd "$HERE" && pwd)/$APP_SRC

 To launch: double-click in Finder, or:
   open "$APP_DST"

 First launch may still take 10-30 s while the bundle unpacks.
 If macOS Gatekeeper still complains:
   xattr -dr com.apple.quarantine "$APP_DST"
   # then right-click the app in Finder → Open → Open
----------------------------------------------------------
 Reminder: a green Mac build does NOT prove the Windows
 .exe will launch.  The Windows CI BOOT SELF-TEST is the
 only thing that verifies the tech's app.
----------------------------------------------------------
EOF
