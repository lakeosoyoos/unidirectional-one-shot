"""
launcher.py — PyInstaller entry point for Unidirectional One Shot (Desktop)
==========================================================================

Boots a local Streamlit server on http://127.0.0.1:8501, opens the
default browser once the server actually responds, and (when the network
is available) auto-updates the small engine + UI .py files from
``main`` on GitHub before launching.

Every line in here exists because a previous build crashed without it.
See ``README_BUILD.txt`` for the failure-mode catalog.

Boundary note (read before editing the auto-updater):
    The auto-updater runs AFTER bootstrap is finished — i.e. after the
    frozen PyInstaller bundle has successfully unpacked, after
    pkg_resources has been imported, after Streamlit has been imported.
    That means the updater can only ship engine + UI changes.  It can
    NEVER fix a bundle that crashes BEFORE this file runs.  Changes to
    launcher.py, .spec, or requirements-desktop.txt require the tech
    to download a fresh zip from the windows-build Release.
"""
from __future__ import annotations

# ── Standard library only at module top: no pkg_resources, no streamlit ──
import hashlib
import http.client
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
import webbrowser


APP_NAME       = "UnidirectionalOneShot"
SERVER_HOST    = "127.0.0.1"
# 8502 — NOT 8501 — so we don't clash with Splice Report or any other
# Streamlit app the maintainer / tech might already be running on the
# default port.  Every "is anything already on this port" check uses
# /_stcore/health, which is the same answer for ANY Streamlit app, so
# we have to use a unique port to disambiguate.
SERVER_PORT    = 8502
HEALTH_PATH    = "/_stcore/health"
HEALTH_TIMEOUT = 90.0   # seconds the first cold boot may take
GH_OWNER       = "lakeosoyoos"
GH_REPO        = "unidirectional-one-shot"
GH_BRANCH      = "main"


# ─────────────────────────────────────────────────────────────────────
#  1. Redirect stdout / stderr — windowed apps have None streams
# ─────────────────────────────────────────────────────────────────────

def _user_dir() -> pathlib.Path:
    """User-writable directory for logs, auto-updated engine, etc."""
    p = pathlib.Path.home() / f".{APP_NAME.lower()}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _redirect_output_to_log() -> None:
    """In a windowed PyInstaller build, sys.stdout / sys.stderr can be
    None.  Any print() or traceback then raises AttributeError before
    our error handler can show a message.  Capture both into a log file
    in ~/.unidirectionaloneshot/unidirectionaloneshot.log so we always
    have a post-mortem.
    """
    log_path = _user_dir() / f"{APP_NAME.lower()}.log"
    try:
        fh = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
        fh.write("\n" + "-" * 60 + "\n")
        fh.write(f"Launcher start  pid={os.getpid()}  frozen={getattr(sys, 'frozen', False)}\n")
        sys.stdout = fh
        sys.stderr = fh
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────
#  2. Silence Streamlit's first-run email prompt
# ─────────────────────────────────────────────────────────────────────

def _silence_first_run_prompt() -> None:
    """Streamlit asks for an email on first launch by reading stdin.
    A windowed bundle has no stdin → the app hangs forever with no
    visible UI.  Pre-seed an empty credentials file and the related env
    flags so the prompt is skipped entirely.
    """
    cred_dir = pathlib.Path.home() / ".streamlit"
    try:
        cred_dir.mkdir(parents=True, exist_ok=True)
        cred = cred_dir / "credentials.toml"
        if not cred.exists() or cred.stat().st_size == 0:
            cred.write_text('[general]\nemail = ""\n', encoding="utf-8")
        cfg = cred_dir / "config.toml"
        if not cfg.exists():
            cfg.write_text(
                '[browser]\ngatherUsageStats = false\n'
                '[server]\nheadless = true\n',
                encoding="utf-8",
            )
    except Exception:
        pass
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_GLOBAL_DEVELOPMENT_MODE", "false")


# ─────────────────────────────────────────────────────────────────────
#  3. Health probe + browser open
# ─────────────────────────────────────────────────────────────────────

def _health_ok(timeout: float = 2.0) -> bool:
    try:
        conn = http.client.HTTPConnection(SERVER_HOST, SERVER_PORT, timeout=timeout)
        conn.request("GET", HEALTH_PATH)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace").strip()
        return resp.status == 200 and body == "ok"
    except Exception:
        return False
    finally:
        try: conn.close()
        except Exception: pass


def _open_browser_when_ready(deadline_s: float = HEALTH_TIMEOUT) -> None:
    """Poll /_stcore/health until it returns "ok" or we run out of
    runway, then open the browser.  Opening on a fixed delay shows a
    "connection refused" page on slow cold boots — don't do that."""
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if _health_ok():
            try:
                webbrowser.open_new_tab(f"http://{SERVER_HOST}:{SERVER_PORT}")
            except Exception:
                pass
            return
        time.sleep(1.0)


# ─────────────────────────────────────────────────────────────────────
#  4. Single-instance guard
# ─────────────────────────────────────────────────────────────────────

def _already_running() -> bool:
    """If a previous launcher of OURS is still serving, just open a new
    tab pointing at it and bail.  Stops a double double-click from
    spawning a second dead server on a port that's already taken.

    Important: a positive /_stcore/health response could be ANY Streamlit
    app, not necessarily ours — every Streamlit serves that endpoint.
    By binding to port 8502 (not the Streamlit default 8501) we already
    avoid the splice-report / other-app collision, and a hit on our
    health endpoint at our port is good enough to call it the same app.
    """
    return _health_ok(timeout=1.0)


# ─────────────────────────────────────────────────────────────────────
#  5. Auto-update from GitHub
# ─────────────────────────────────────────────────────────────────────

# Files we ship in the bundle AND are willing to refresh on launch.
# Order matters only for the smoke-check import.
AUTO_UPDATE_FILES = [
    "sor_reader324802a.py",
    "json_reader.py",
    "unidirectional_event_finder.py",
    "components/otdr_settings/__init__.py",
    "components/otdr_settings/index.html",
    "desktop/desktop_app.py",
]


def _download(rel_path: str, dest: pathlib.Path,
              timeout: float = 10.0) -> bytes | None:
    url = (f"https://raw.githubusercontent.com/{GH_OWNER}/{GH_REPO}/"
           f"{GH_BRANCH}/{rel_path}")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def _validate_python_blob(blob: bytes, rel_path: str) -> bool:
    """Cheap sanity check that doesn't actually import the module:
    non-empty + contains 'def ' + parses + compile() succeeds."""
    if not blob or len(blob) < 64:
        return False
    if rel_path.endswith(".py") and b"def " not in blob:
        return False
    if rel_path.endswith(".py"):
        try:
            compile(blob, rel_path, "exec")
        except SyntaxError:
            return False
    return True


def _import_smoketest_via_subprocess(engine_dir: pathlib.Path,
                                     timeout: float = 30.0) -> bool:
    """Re-invoke OUR OWN frozen executable with SS_SMOKETEST set so it
    imports the freshly-downloaded modules in an isolated child process.
    If the imports raise, the child exits non-zero and we discard the
    download.  We can't import them in this process because they could
    poison module state for the real run."""
    if not getattr(sys, "frozen", False):
        # In a dev (unfrozen) launch, just trust the compile() check.
        return True
    env = os.environ.copy()
    env["SS_SMOKETEST"]    = str(engine_dir)
    env["SS_ENGINE_SOURCE"] = "smoketest"
    try:
        proc = subprocess.run(
            [sys.executable],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode == 0
    except Exception:
        return False


def _handle_smoketest_mode() -> None:
    """If SS_SMOKETEST is set we are running as a child smoke-check.
    Import the candidate engine modules and exit 0/1.  Don't start the
    server, don't open a browser, don't redirect logs."""
    target = os.environ.get("SS_SMOKETEST", "")
    if not target:
        return
    try:
        sys.path.insert(0, target)
        import importlib
        for modname in ("sor_reader324802a", "json_reader",
                        "unidirectional_event_finder"):
            importlib.import_module(modname)
        sys.exit(0)
    except Exception:
        sys.exit(1)


def _try_auto_update(bundle_root: pathlib.Path) -> tuple[pathlib.Path, str]:
    """Try to refresh the engine + UI files from GitHub.  All-or-nothing:
    if anything fails to download, fails validation, or fails the import
    smoke-check, fall back to the bundled copies and tag the source as
    "bundled".  On success, returns (engine_dir, "latest")."""
    if os.environ.get("SS_DISABLE_AUTO_UPDATE", "").strip().lower() in ("1", "true", "yes"):
        return bundle_root, "bundled"

    staging = pathlib.Path(tempfile.mkdtemp(prefix="unidir_update_"))
    try:
        for rel in AUTO_UPDATE_FILES:
            blob = _download(rel, staging / rel)
            if blob is None or not _validate_python_blob(blob, rel):
                return bundle_root, "bundled"
            out_path = staging / rel
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(blob)
        if not _import_smoketest_via_subprocess(staging):
            return bundle_root, "bundled"
        # Persist into ~/.unidirectionaloneshot/engine so the next launch
        # can also run from there even without network.
        live_root = _user_dir() / "engine"
        if live_root.exists():
            for child in live_root.rglob("*"):
                if child.is_file():
                    try: child.unlink()
                    except Exception: pass
        for rel in AUTO_UPDATE_FILES:
            src = staging / rel
            dst = live_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
        return live_root, "latest"
    except Exception:
        return bundle_root, "bundled"


# ─────────────────────────────────────────────────────────────────────
#  6. Streamlit boot
# ─────────────────────────────────────────────────────────────────────

def _bundle_root() -> pathlib.Path:
    """When frozen, sys._MEIPASS points at the unpacked one-folder bundle.
    Otherwise we're running from the dev checkout — use the repo root."""
    if getattr(sys, "frozen", False):
        return pathlib.Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return pathlib.Path(__file__).resolve().parent.parent


def _script_path(engine_dir: pathlib.Path) -> str:
    """Path to the Streamlit script we want to run.  Prefer the auto-
    updated desktop_app.py; fall back to the bundled copy."""
    candidates = [
        engine_dir / "desktop" / "desktop_app.py",
        engine_dir / "desktop_app.py",
        _bundle_root() / "desktop" / "desktop_app.py",
        _bundle_root() / "desktop_app.py",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise FileNotFoundError("desktop_app.py not found in bundle or auto-update tree.")


def _boot_streamlit(script: str, engine_dir: pathlib.Path,
                    engine_source: str) -> int:
    """Final step: hand off to Streamlit's CLI.  We use the CLI rather
    than the bootstrap API because the CLI is the only entry point
    Streamlit officially supports across versions, and it correctly
    initialises the runtime."""
    # Ensure auto-updated engine modules win over the bundled ones.
    sys.path.insert(0, str(engine_dir))
    os.environ["SS_ENGINE_SOURCE"] = engine_source

    from streamlit.web import cli as stcli
    sys.argv = [
        "streamlit", "run", script,
        f"--server.headless=true",
        f"--server.port={SERVER_PORT}",
        f"--server.address={SERVER_HOST}",
        "--browser.gatherUsageStats=false",
        "--global.developmentMode=false",
    ]
    return stcli.main()


# ─────────────────────────────────────────────────────────────────────
#  7. main()
# ─────────────────────────────────────────────────────────────────────

def main() -> int:
    # SS_SMOKETEST has to be the very first thing we check — it bypasses
    # logging redirection / browser opening / Streamlit boot.
    _handle_smoketest_mode()

    _redirect_output_to_log()
    _silence_first_run_prompt()

    if _already_running():
        webbrowser.open_new_tab(f"http://{SERVER_HOST}:{SERVER_PORT}")
        return 0

    engine_dir, engine_source = _try_auto_update(_bundle_root())

    # Open the browser on a background thread so the main thread can run
    # Streamlit's blocking event loop.
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    try:
        script = _script_path(engine_dir)
        return _boot_streamlit(script, engine_dir, engine_source)
    except SystemExit as e:
        return int(e.code or 0)
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
