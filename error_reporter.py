"""
error_reporter.py — real-time Slack alerts for tech-side failures
=================================================================

Sibling fix from Secret Sauce, commit 44bce61.  Same shape as splice-
report's own reporter so all three apps surface in the same channel,
disambiguated by APP_NAME.

Behaviour, in order:
    1. ``report_error(where, exc, context=None)`` is called from every
       user-visible failure path (Run / Generate / write_xlsx / launcher
       boot).
    2. The function reads SS_ERROR_WEBHOOK from the environment.  Empty /
       unset → NO-OP.  A build that ships without the webhook silently
       runs reporting OFF.
    3. The function dedups by ``(where, type(exc).__name__, str(exc))``.
       The same triple within ``DEDUP_WINDOW_SECS`` is sent ONCE.
       Distinct errors fire immediately.
    4. A daemon thread POSTs the message via urllib with a 4 s timeout.
       Wrapped in try/except so reporting can NEVER raise into the
       caller's path.

NEVER include customer-identifying or trace-content data in the message.
Counts, modes, and engine-source tags are fine.  File paths inside the
tech's machine (e.g. /Users/X/Desktop/) WILL leak the username — pass a
sanitised version in ``context`` if you care.

No new dependencies.  urllib + stdlib only.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import threading
import time
import traceback
import urllib.request
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────
#  Tunables
# ─────────────────────────────────────────────────────────────────────

APP_NAME           = "Unidirectional One Shot"
DEDUP_WINDOW_SECS  = 60 * 60      # 1 hour — anti-flood window
POST_TIMEOUT_SECS  = 4.0          # HTTP timeout; longer would block UI
TRACEBACK_TAIL     = 1400         # chars of traceback to send
ENV_KEY            = "SS_ERROR_WEBHOOK"


# ─────────────────────────────────────────────────────────────────────
#  Module-private state (thread-safe dedup)
# ─────────────────────────────────────────────────────────────────────
#
# {(where, exc_type, exc_str): epoch_when_last_sent}
#
# Guarded by _LOCK.  Inspected by tests.

_LAST_SENT: dict = {}
_LOCK     = threading.Lock()


def _get_username() -> str:
    """Tolerant whoami — getpass.getuser() can raise on some Windows
    setups when no $USER / $USERNAME is exposed (rare CI runner edge
    case)."""
    try:
        import getpass
        return getpass.getuser() or "(unknown)"
    except Exception:
        return os.environ.get("USERNAME") or os.environ.get("USER") or "(unknown)"


def _build_text(where: str, exc: BaseException,
                context: Optional[dict]) -> str:
    r"""Compose the Slack message body.  Plain text — Slack renders the
    minimal markdown we use here (bold ``*…*``, monospace ``\`…\``)."""
    exc_type = type(exc).__name__
    exc_msg  = str(exc) or "(no message)"

    # Tail of the traceback only — the head is usually framework
    # bootstrap that's the same for every alert.
    try:
        tb_full = "".join(traceback.format_exception(type(exc), exc,
                                                     exc.__traceback__))
    except Exception:
        tb_full = "(traceback unavailable)"
    if len(tb_full) > TRACEBACK_TAIL:
        tb = "...\n" + tb_full[-TRACEBACK_TAIL:]
    else:
        tb = tb_full

    parts = [
        f":rotating_light: *{APP_NAME} error* — {where}",
        f"*{exc_type}*: {exc_msg}",
        f"_host_  `{socket.gethostname()}`  _user_  `{_get_username()}`",
        f"_os_  `{platform.platform()}`",
        f"_engine source_  `{os.environ.get('SS_ENGINE_SOURCE', 'unknown')}`",
    ]
    if context:
        # ``context`` is intentionally small — counts/modes only.  We
        # cap the rendered length so a misbehaving caller can't blow
        # past Slack's 40 KB body limit.
        try:
            ctx_lines = []
            for k, v in list(context.items())[:24]:
                vs = repr(v)
                if len(vs) > 120:
                    vs = vs[:117] + "..."
                ctx_lines.append(f"  {k} = {vs}")
            parts.append("_context_\n" + "\n".join(ctx_lines))
        except Exception:
            parts.append("_context_  (failed to render)")
    parts.append("```\n" + tb + "\n```")
    return "\n".join(parts)


def _post(webhook_url: str, text: str) -> None:
    """One-shot POST to the Slack webhook.  Caller runs this in a
    daemon thread; any exception here is swallowed."""
    try:
        body = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=POST_TIMEOUT_SECS):
            pass
    except Exception:
        # Reporting must not break a run.  Swallow + carry on.
        pass


def report_error(where: str, exc: BaseException,
                 context: Optional[dict] = None) -> None:
    """Best-effort Slack alert.  Safe to call from any except: block.

    Parameters
    ----------
    where : str
        Short, stable label for the failure site.  Used in the message
        AND as a dedup key — keep it consistent across calls so repeat
        crashes collapse correctly (e.g. "desktop._run_engine",
        "launcher.boot", "write_xlsx.audit_sheet").
    exc : BaseException
        The caught exception.  Type, message, and traceback are sent;
        the traceback is tail-trimmed to ~1400 chars.
    context : dict, optional
        Small dict of run state — counts, modes, engine source.
        DO NOT pass customer / trace / PII data here.

    Never raises.  Returns immediately (work happens on a daemon
    thread).
    """
    try:
        webhook = os.environ.get(ENV_KEY, "").strip()
        if not webhook:
            return  # build shipped without the webhook → reporting OFF

        exc_type_name = type(exc).__name__
        signature     = (where, exc_type_name, str(exc) or "")
        now           = time.time()

        with _LOCK:
            last = _LAST_SENT.get(signature, 0.0)
            if now - last < DEDUP_WINDOW_SECS:
                return  # silenced for now — same triple within window
            _LAST_SENT[signature] = now

        text = _build_text(where, exc, context)

        # Fire on a daemon thread so the caller never blocks waiting
        # for the Slack POST, and so a slow Slack response never
        # delays shutdown.
        t = threading.Thread(target=_post, args=(webhook, text),
                              daemon=True)
        t.start()
    except Exception:
        # Last-resort guard — even building the message must not raise.
        return


# ─────────────────────────────────────────────────────────────────────
#  Testing hooks (importable from tests/test_error_reporter.py)
# ─────────────────────────────────────────────────────────────────────

def _reset_dedup_for_tests() -> None:
    """Clear the in-process dedup table.  Test-only."""
    with _LOCK:
        _LAST_SENT.clear()


def _peek_dedup_for_tests() -> dict:
    """Return a snapshot of the dedup table.  Test-only."""
    with _LOCK:
        return dict(_LAST_SENT)
