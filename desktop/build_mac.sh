#!/usr/bin/env bash
# ----------------------------------------------------------------------
# build_mac.sh — one-click LOCAL macOS build of UnidirectionalOneShot.
#
# WHY THIS EXISTS:
#   The production target is Windows.  But every "windowed bundle won't
#   launch" failure mode we've ever hit (setuptools InvalidVersion, the
#   jaraco-not-found cascade, the first-run-email hang) is OS-independent
#   — it crashes the macOS build for the same reason.  So building a
#   matching Mac .app on your laptop is the fastest way to flush those
#   bugs without waiting on a Windows CI cycle.
#
#   IMPORTANT: a green Mac build does NOT prove the Windows build works.
#   The Mac build de-risks; the Windows CI boot self-test verifies.  See
#   README_BUILD.txt section "VALIDATION ORDER".
#
# PREREQS:
#   • Python 3.11 installed (NOT 3.12 or newer).  Easiest path:
#         brew install python@3.11
#     or download from https://www.python.org/downloads/release/python-3119/
#
# RUN FROM:  desktop/
# OUTPUT:    desktop/dist/UnidirectionalOneShot/UnidirectionalOneShot
# ----------------------------------------------------------------------

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# --- Find Python 3.11 -------------------------------------------------
PY=""
for cand in python3.11 \
            /opt/homebrew/bin/python3.11 \
            /usr/local/bin/python3.11 \
            /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then
        PY="$cand"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Python 3.11 not found.  Install it:  brew install python@3.11"
    echo "Do NOT use 3.12 or newer — pkgutil.ImpImporter was removed and"
    echo "our setuptools pin (65.5.1) depends on it."
    exit 1
fi
echo "Using $PY ($("$PY" -V))"

# --- Fresh venv -------------------------------------------------------
if [ -d .venv ]; then
    echo "Removing previous .venv..."
    rm -rf .venv
fi
"$PY" -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip wheel
pip install -r requirements-desktop.txt

# --- Re-pin setuptools LAST so transitive installs can't bump it ------
pip install --upgrade --force-reinstall setuptools==65.5.1

# --- Clean previous artifacts ----------------------------------------
rm -rf build dist

# --- Build ------------------------------------------------------------
pyinstaller UnidirectionalOneShot.spec --noconfirm --clean

cat <<EOF

----------------------------------------------------------
 Build succeeded.
 Run:  dist/UnidirectionalOneShot/UnidirectionalOneShot
----------------------------------------------------------
 Reminder: a green Mac build does NOT prove the Windows
 .exe will launch.  Push to GitHub and watch the
 windows-latest CI job's BOOT SELF-TEST step before
 sharing the Release URL with anyone.
----------------------------------------------------------
EOF
