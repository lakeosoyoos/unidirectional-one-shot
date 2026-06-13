UnidirectionalOneShot — Desktop build (Windows + macOS)
=======================================================

This folder is everything needed to package the UnidirectionalOneShot
Streamlit app as a downloadable desktop app.  The Windows .exe is the
production artifact; the matching macOS build exists so the maintainer
can test the exact UX a Windows tech will see.

FOLDER CONTENTS
---------------
  desktop_app.py            Local Streamlit UI (folder picker, no upload).
  launcher.py               PyInstaller entry point + auto-updater.
  UnidirectionalOneShot.spec PyInstaller spec.
  requirements-desktop.txt  Pinned build deps.
  build.bat                 One-click Windows build.
  build_mac.sh              One-click macOS build (matches Windows UX).
  README_BUILD.txt          This file.

  ../.github/workflows/build-windows.yml
                            CI: builds + MANDATORY BOOT SELF-TEST +
                            publishes to permanent `windows-build`
                            Release tag.


PERMANENT DOWNLOAD URL (for techs)
----------------------------------
  https://github.com/lakeosoyoos/unidirectional-one-shot/releases/download/windows-build/UnidirectionalOneShot-Windows.zip

The URL never changes.  Every successful CI build replaces the asset
behind it.  Techs bookmark this URL once; they never need to know about
versions or tags.

A tech who already downloaded a non-working build CANNOT have it
auto-update into a working one — the auto-updater runs only AFTER the
bundle boots successfully.  If the bundle is DOA they must redownload
from the URL above.


PORT ASSIGNMENT — 8505 (don't change without coordinating)
----------------------------------------------------------
Each of our desktop apps claims a unique loopback port so a tech who
runs more than one of them doesn't get the wrong app's browser tab on
a double-click.  Current registry:

    Secret Sauce         127.0.0.1:8501
    SpliceReport         127.0.0.1:8503
    Unidirectional       127.0.0.1:8505   ← THIS APP

A static check (``scripts/check_port_assignment.py``, called from CI
before the PyInstaller build) greps for ``^PORT\s*=\s*(\d+)`` in
``desktop/launcher.py`` and fails the build if the literal isn't 8505.
If you genuinely need a different port, update BOTH the launcher
constant AND the check script's expected value, and remember to pick
a port that doesn't appear in the registry above (8525/8535/8545 are
already reserved as fallbacks here too).

The bundle's own self-tests (CI ``Boot self-test`` step, local
``build_mac.sh`` test) all hit http://127.0.0.1:8505/_stcore/health
- they're derived from the same PORT constant in launcher.py.


PYTHON VERSION — 3.11 ONLY
--------------------------
The build MUST use Python 3.11.  Do not use 3.12 or newer.

Why: setuptools 65.5.1 (see below) uses pkgutil.ImpImporter.  Python
3.12 removed that class.  On Python 3.12 the packaged app crashes at
launch with:

    AttributeError: module 'pkgutil' has no attribute 'ImpImporter'

You will not see this on the dev machine if 3.12's site-packages happen
to ship a different setuptools — the crash only manifests in the frozen
bundle on a clean target machine.  Stick to 3.11.


SETUPTOOLS PIN — 65.5.1
-----------------------
requirements-desktop.txt pins setuptools==65.5.1 and the CI workflow
re-installs that exact version as its LAST install step.  Don't relax
this pin.

Why: newer setuptools makes pkg_resources strict about parsing what
looks like a Python "version" out of arbitrary strings.  The packaged
app's MEI bundle path looks like a version to it and the app crashes at
launch with:

    pkg_resources.extern.packaging.version.InvalidVersion: ...

65.5.1 keeps the lenient parsing and the bundle launches cleanly.


JARACO / PKG_RESOURCES VENDORED PACKAGES
----------------------------------------
Streamlit imports pkg_resources at startup, which imports its vendored
copies of jaraco.text, jaraco.functools, jaraco.context, packaging,
platformdirs, appdirs, more_itertools, and ordered_set.  On a clean
build machine these live ONLY inside setuptools' _vendor tree and
PyInstaller does not detect them, so the frozen app crashes at launch
with:

    ModuleNotFoundError: the jaraco package is required

We defend against this in three places, on purpose:

  1. requirements-desktop.txt installs all of them as real top-level
     packages, so pkg_resources' extern-importer has a working runtime
     fallback.
  2. UnidirectionalOneShot.spec collect_submodules("pkg_resources"),
     collect_submodules("setuptools"), collect_data_files() for both,
     and collect_all() of every vendored package.
  3. The .spec also lists every vendored package by name in
     hiddenimports.

Each layer alone has failed at some point.  Keep all three.


VALIDATION ORDER — read this
----------------------------
A successful PyInstaller exit code tells you NOTHING about whether the
packaged app launches.  Every DOA build in our history compiled green.

The verification order is:

  1. (OPTIONAL) Run build_mac.sh locally.  Flushes OS-independent bugs
     — the setuptools pin, the first-run-prompt hang, missing
     hiddenimports for your own modules.  Fast feedback (~5 min).

     A green Mac build does NOT prove the Windows build works.  Mac may
     already have jaraco/etc. installed incidentally and uses a
     different Python.  This step de-risks; it does not verify.

  2. Push to GitHub and let .github/workflows/build-windows.yml run.
     The BOOT SELF-TEST step actually launches the .exe on a clean
     windows-latest runner and polls /_stcore/health for up to 90 s.
     If the bundle doesn't serve, the step exits 1 and the Release
     publish is skipped — a DOA build never reaches a tech.

  3. After the CI run is green, double-check the Release asset's
     "Updated" timestamp on github.com to confirm the new build was
     actually published.

  4. Finally, fresh-download the zip to a test machine (or download to
     ~/Downloads and unblock + extract on the dev machine) and run it.
     This catches the very rare class of bug where CI's environment
     differs from a real user's machine.


DEV RUN (no packaging)
----------------------
You can run desktop_app.py directly without packaging:

    cd /Users/robertcolbert/Desktop/unidirectional-one-shot
    pip install -r desktop/requirements-desktop.txt
    pip install --upgrade --force-reinstall setuptools==65.5.1
    python -m streamlit run desktop/desktop_app.py

This boots Streamlit against the dev checkout — the auto-updater is
disabled in unfrozen runs, so the engine files come straight from the
working tree.  Useful for iterating on the UI without rebuilding.


LOCAL BUILD — Windows
---------------------
  1. Install Python 3.11 from python.org.
  2. Open a CMD prompt in this folder.
  3. Run:

         build.bat

  4. Output: dist\UnidirectionalOneShot\UnidirectionalOneShot.exe

REMEMBER: a green local build only proves the spec is well-formed.  The
CI BOOT SELF-TEST is the only thing that proves the bundle launches.


LOCAL BUILD — macOS
-------------------
  1. Install Python 3.11:

         brew install python@3.11

  2. From this folder, run:

         ./build_mac.sh

  3. Output: dist/UnidirectionalOneShot/UnidirectionalOneShot

     Double-click that binary in Finder; the Streamlit UI opens in your
     default browser at http://127.0.0.1:8505.

     macOS may refuse to launch an unsigned binary on first run with
     "cannot be opened because the developer cannot be verified".  Fix:
     right-click the binary in Finder, choose Open, click Open in the
     confirmation dialog.  Subsequent launches are unprompted.


TECH FIRST-RUN SEQUENCE (Windows)
---------------------------------
Send this verbatim to a tech who's about to install:

  1. Open the download URL in a browser:
       https://github.com/lakeosoyoos/unidirectional-one-shot/releases/download/windows-build/UnidirectionalOneShot-Windows.zip

  2. Save the .zip to Downloads.

  3. In File Explorer, RIGHT-CLICK the zip → Properties.  At the bottom
     of the General tab, check the **Unblock** box and click Apply.  If
     you skip this step Windows quarantines every .dll in the bundle
     and the app shows a "this app can't run on your PC" dialog.

  4. Right-click the zip again → Extract All → Extract.  A folder named
     `UnidirectionalOneShot` appears.

  5. Open that folder.  Double-click **UnidirectionalOneShot.exe**.

  6. Windows SmartScreen will show "Windows protected your PC" — click
     **More info** → **Run anyway**.

  7. The first launch takes 10-30 s while the bundle unpacks.  There
     is no progress bar (we suppress the console window).  When it's
     ready, your default browser opens to the app at
     http://127.0.0.1:8505 — that's the UI.

  8. Every subsequent launch is fast (~2 s).  On launches with internet,
     the engine files auto-update from GitHub silently; offline, the
     bundled copies are used.  The sidebar shows which source is active.


AUTO-UPDATE — WHAT IT CAN AND CAN'T DO
--------------------------------------
The launcher downloads these files from main on each launch:

  • sor_reader324802a.py
  • json_reader.py
  • unidirectional_event_finder.py
  • components/otdr_settings/__init__.py
  • components/otdr_settings/index.html
  • desktop/desktop_app.py

If every file downloads, validates (non-empty, contains "def ", parses
via compile()), AND passes an isolated-subprocess import smoke check,
they overwrite the bundled copies for that session and the sidebar
reads "latest (auto-updated)".  Any failure → fall back to the bundled
copies, sidebar reads "bundled (offline)".

The updater CAN ship:
  • Engine bugfixes / new threshold defaults
  • UI tweaks to desktop_app.py
  • EXFO settings panel changes

The updater CANNOT ship:
  • Changes to launcher.py (it's running)
  • Changes to UnidirectionalOneShot.spec (already used)
  • New runtime dependencies
  • Anything that would change what's inside the frozen bundle

Those require a fresh download from the windows-build Release.


CODE SIGNING (not yet done)
---------------------------
The build is unsigned, so Windows SmartScreen shows the "this might
have been malware" warning until enough installs accumulate.  A code-
signing cert (~$200-400/yr from a CA) removes the warning entirely.
That's a separate purchase + workflow change; not blocking here.
