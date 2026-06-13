"""
desktop_app.py — Unidirectional One Shot (LOCAL desktop edition)
================================================================

Same engine + same flag categories (Splice / Possible Bend/Damage /
Break) as the Streamlit Community Cloud web app, repackaged for a
local-only Windows / macOS run:

  • No upload widget — the tech picks a local folder via the native
    file dialog or pastes a path.
  • Recursive os.walk inventory with content-sniff for JSON (skips
    EXFO results files, project metadata, and any other JSON that
    isn't an actual OTDR acquisition).
  • Output written to a subfolder next to the inputs AND offered via
    st.download_button.
  • Sidebar shows the engine source ("latest (auto-updated)" vs
    "bundled (offline)") taken from the SS_ENGINE_SOURCE env var the
    launcher sets, plus a Quit button that hard-exits the process.

DO NOT import this module on Streamlit Cloud — the web app uses
``streamlit_app.py``, which expects uploads.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from typing import Optional

import pandas as pd
import streamlit as st

import unidirectional_event_finder as engine


# ─────────────────────────────────────────────────────────────────────
#  Page chrome
# ─────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Unidirectional One Shot (Desktop)",
    page_icon="🪢",
    layout="wide",
)

st.title("Unidirectional One Shot — Desktop")
st.caption(
    "A-direction-only event finder for OTDR splice / bend / break QC. "
    "Pick a local folder of SOR / JSON files; the Excel report is "
    "written next to your inputs and also offered for download."
)


# ─────────────────────────────────────────────────────────────────────
#  Engine helpers (mirrors of streamlit_app.py but folder-driven)
# ─────────────────────────────────────────────────────────────────────

def _is_otdr_json(path: str) -> bool:
    """Cheap content sniff: does this JSON look like an EXFO OTDR
    acquisition?  We require the `Measurement.OtdrMeasurements` key
    that every FastReporter export carries.  This stops stray result
    files / project metadata / FastReporter sidecars from being mis-
    counted as fiber traces by the inventory."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(65536)
        if b'"OtdrMeasurements"' not in head:
            return False
        # Lightweight check: tolerate truncation by trying to parse
        # only the head; if that fails, parse the whole file.
        try:
            obj = json.loads(head.decode("utf-8", errors="replace"))
        except Exception:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                obj = json.load(fh)
        return bool(((obj.get("Measurement") or {}).get("OtdrMeasurements")))
    except Exception:
        return False


def _is_sor(path: str) -> bool:
    """Bellcore SOR files always start with `Map\\0` — a 4-byte magic
    that no random `.sor`-named file shares accidentally."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) == b"Map\x00"
    except Exception:
        return False


def _inventory(folder: str) -> dict:
    """Walk ``folder`` recursively, content-sniff every .sor / .json,
    and return a summary dict with the list of valid acquisition files
    and counts of strays that were skipped."""
    sor, jsons, strays, zips = [], [], [], []
    for dirpath, _, files in os.walk(folder):
        for fn in files:
            full = os.path.join(dirpath, fn)
            low = fn.lower()
            if low.endswith(".sor"):
                (sor if _is_sor(full) else strays).append(full)
            elif low.endswith(".json"):
                (jsons if _is_otdr_json(full) else strays).append(full)
            elif low.endswith(".zip"):
                zips.append(full)
    return {
        "sor": sor, "json": jsons, "zip": zips, "strays": strays,
    }


def _stage_flat(paths: list) -> str:
    """Copy every file in ``paths`` into a fresh temp directory with
    de-duplicated basenames.  Necessary because the engine's
    ``_walk_files`` keys by basename when extracting fiber numbers, and
    two ribbons in different subfolders can share filenames."""
    tmp = tempfile.mkdtemp(prefix="unidir_desktop_")
    seen: Counter = Counter()
    for p in paths:
        base = os.path.basename(p)
        stem, ext = os.path.splitext(base)
        seen[base] += 1
        if seen[base] > 1:
            base = f"{stem}__{seen[base] - 1}{ext}"
        shutil.copy2(p, os.path.join(tmp, base))
    return tmp


@st.cache_data(show_spinner=False)
def _scan_directions(staged_dir: str) -> dict:
    sig_counts: Counter = Counter()
    for filepath, name in engine._walk_files(staged_dir):
        try:
            if name.lower().endswith(".json"):
                meta = engine._read_json_genparams(filepath)
            else:
                meta = engine._read_sor_genparams(filepath)
            sig = engine.direction_signature(meta)
            sig_counts[sig] += 1
        except Exception:
            continue
    return dict(sig_counts)


def _run_engine(staged_dir: str, direction: Optional[str],
                ribbon_size: int, thresholds: dict,
                output_dir: str) -> dict:
    """Same overrideable-constants dance as the web app's _run_engine,
    but writes the Excel into ``output_dir`` (the subfolder next to the
    user's inputs) and reads bytes back for the download button."""
    overridable = (
        "BEND_THRESHOLD",
        "CLOSURE_MATCH_KM",
        "OFF_SPLICE_CLUSTER_M",
        "MIN_POP_SPLICE",
        "BREAK_PREMATURE_KM",
    )
    saved = {k: getattr(engine, k) for k in overridable}
    try:
        for k, v in (thresholds or {}).items():
            if k in overridable:
                setattr(engine, k, v)

        fibers, chosen = engine.load_fibers(staged_dir, direction=direction)
        if not fibers:
            return {"error": "No fibers loaded for the selected direction."}

        engine.normalize_all(fibers)
        candidates = engine.discover_splices(fibers)
        valid = engine.refine_and_validate(fibers, candidates)
        off_evs = engine.find_off_splice_events(fibers, valid)
        off_cols = engine.cluster_off_splice(off_evs, fibers)
        n_fibers = max(fibers.keys())
        span = engine.auto_detect_span(fibers)
        breaks = engine.find_breaks(fibers, valid, span)
        break_cols = engine.cluster_breaks(breaks)
        columns = engine.build_columns(valid, off_cols, break_cols)
        grid = engine.build_ribbon_grid(fibers, columns, ribbon_size)

        sample = next(iter(fibers.values()))
        meta = sample.get("_genparams") or {}
        site_a = engine._short_code(meta.get("orig_loc"))
        site_b = engine._short_code(meta.get("term_loc"))
        if (not site_a or not site_b) and chosen and "->" in chosen:
            a, b = chosen.split("->", 1)
            site_a = site_a or engine._short_code(a)
            site_b = site_b or engine._short_code(b)

        out_name = (
            f"{site_a or 'A'}_{site_b or 'B'}_unidir.xlsx"
        )
        os.makedirs(output_dir, exist_ok=True)
        out_path = os.path.join(output_dir, out_name)
        engine.write_xlsx(grid, columns, n_fibers, ribbon_size, span,
                          out_path, site_a=site_a, site_b=site_b,
                          fibers=fibers)
        with open(out_path, "rb") as fh:
            xlsx_bytes = fh.read()

        rows = engine._flagged_event_rows(grid, columns, ribbon_size, n_fibers)
        df = pd.DataFrame([
            {
                "Fiber":         r["fiber"],
                "Ribbon":        r["ribbon"],
                "Column":        r["column_label"],
                "Distance (km)": round(r["column_km"], 2),
                "Loss (dB)":     ("broke" if r["loss"] is None
                                  else round(r["loss"], 3)),
                "Kind":          {"splice": "Splice",
                                  "bend_damage": "Possible Bend/Damage",
                                  "break": "BREAK"}.get(r["column_kind"],
                                                        r["column_kind"]),
                "Why flagged":   r["reason"],
            }
            for r in rows
        ])

        return {
            "xlsx_bytes":     xlsx_bytes,
            "xlsx_path":      out_path,
            "preview_df":     df,
            "n_fibers":       len(fibers),
            "direction":      chosen,
            "site_a":         site_a,
            "site_b":         site_b,
            "n_splices":      sum(1 for c in columns if c["kind"] == "splice"),
            "n_bend":         sum(1 for c in columns if c["kind"] == "bend_damage"),
            "n_break":        sum(1 for c in columns if c["kind"] == "break"),
            "n_break_fib":    len(breaks),
            "span_km":        span,
            "n_phantoms":     len(candidates) - len(valid),
        }
    finally:
        for k, v in saved.items():
            setattr(engine, k, v)


# ─────────────────────────────────────────────────────────────────────
#  Native folder picker (tkinter)
# ─────────────────────────────────────────────────────────────────────

def _native_pick_folder() -> Optional[str]:
    """Pop the OS folder dialog and return the chosen path or None.

    Wrapped in try/except because (a) the dialog can fail on headless
    runs (CI boot-test, SSH session) and (b) Streamlit reruns the whole
    script on every interaction, so leaving a dead tk root behind would
    leak memory.
    """
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(parent=root,
                                       title="Choose folder containing SOR / JSON files")
        root.destroy()
        return path or None
    except Exception:
        return None


def _native_pick_zip() -> Optional[str]:
    """Same dance as _native_pick_folder but filtered to .zip files."""
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            parent=root,
            title="Choose a ZIP archive of SOR / JSON files",
            filetypes=[("ZIP archives", "*.zip"),
                       ("All files",    "*.*")],
        )
        root.destroy()
        return path or None
    except Exception:
        return None


@st.cache_data(show_spinner="Extracting ZIP...")
def _extract_zip(zip_path: str, mtime: float) -> str:
    """Extract ``zip_path`` to a fresh temp directory and return its
    path.  Cache key includes ``mtime`` so a modified zip re-extracts
    (and an unmodified zip on a Streamlit rerun returns the same temp
    dir instantly, no repeat unzip)."""
    import zipfile
    tmp = tempfile.mkdtemp(prefix="unidir_zip_")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(tmp)
    return tmp


def _normalize_input(path: str) -> tuple[str, bool]:
    """Return (working_directory, was_extracted).  If ``path`` is a
    ``.zip`` file, extract it (cached) and return the temp directory.
    Otherwise return ``path`` unchanged."""
    if os.path.isfile(path) and path.lower().endswith(".zip"):
        return _extract_zip(path, os.path.getmtime(path)), True
    return path, False


# ─────────────────────────────────────────────────────────────────────
#  Sidebar — version indicator, Quit, EXFO threshold panel
# ─────────────────────────────────────────────────────────────────────
from components.otdr_settings import otdr_settings as otdr_settings_component


def _engine_source_label() -> str:
    """Human-readable version source set by the launcher."""
    src = (os.environ.get("SS_ENGINE_SOURCE") or "bundled").strip().lower()
    if src in ("latest", "auto", "live"):
        return "latest (auto-updated)"
    return "bundled (offline)"


# EXFO threshold panel — same VISUAL layout as the splice-report panel
# (same 10 rows, same labels, same column ordering, same customer
# profile dropdown above the table) but uni-only behaviour: only the
# Unidir. splice loss row is actually wired to the engine's
# BEND_THRESHOLD constant.  Every other row renders identically for
# visual parity but is a no-op here.
OTDR_ROWS = [
    # (key,                       label,                       fail_default,  unit,    supported)
    ("unidir_splice_loss",        "Unidir. splice loss",        0.100,        "dB",    True),
    ("bidir_splice_loss",         "Bidir splice loss",          0.160,        "dB",    False),
    ("unidir_connector_loss",     "Unidir. connector loss",     0.750,        "dB",    False),
    ("bidir_connector_loss",      "Bidir connector loss",       0.500,        "dB",    False),
    ("splitter_loss",             "Splitter Loss",              4.500,        "dB",    False),
    ("reflectance",               "Reflectance",                -49.9,        "dB",    False),
    ("fiber_section_atten",       "Fiber section attenuation",  0.400,        "dB/km", False),
    ("span_loss",                 "Span loss",                  20.000,       "dB",    False),
    ("span_length",               "Span length",                0.0000,       "km",    False),
    ("span_orl",                  "Span ORL",                   15.00,        "dB",    False),
]
OTDR_DEFAULT_APPLY = {"unidir_splice_loss"}

CUSTOMER_PROFILES = {
    "Default (engine baseline)": {
        "apply":      set(OTDR_DEFAULT_APPLY),
        "thresholds": {},
    },
    "Lumen": {
        "apply":      {"unidir_splice_loss"},
        "thresholds": {
            "unidir_splice_loss": 0.200,
        },
    },
    "Custom (edit table below)": {  # sentinel — uses session edits as-is
        "apply":      None,
        "thresholds": None,
    },
}


def _otdr_settings_from_profile(profile_name: str) -> dict:
    prof = CUSTOMER_PROFILES.get(profile_name) or {}
    apply_set    = prof.get("apply")
    overrides    = prof.get("thresholds") or {}
    out = {}
    for key, _, fail_default, _, _ in OTDR_ROWS:
        fail = float(overrides.get(key, fail_default))
        applied = ((apply_set is not None and key in apply_set)
                    if apply_set is not None
                    else (key in OTDR_DEFAULT_APPLY))
        out[key] = {"apply": applied, "fail": fail, "warning": fail}
    return out


if "otdr_profile" not in st.session_state:
    st.session_state.otdr_profile = next(iter(CUSTOMER_PROFILES))
if "otdr_settings" not in st.session_state:
    st.session_state.otdr_settings = _otdr_settings_from_profile(
        st.session_state.otdr_profile)


with st.sidebar:
    # Widen the sidebar so the EXFO-styled table fits cleanly.
    st.markdown("""
    <style>
      section[data-testid="stSidebar"],
      section[data-testid="stSidebar"][aria-expanded="true"] {
        width: 620px !important;
        min-width: 620px !important;
        max-width: 620px !important;
      }
      section[data-testid="stSidebar"] > div {
        width: 620px !important;
        min-width: 620px !important;
      }
    </style>
    """, unsafe_allow_html=True)

    # Engine version + Quit at the very top
    st.markdown(f"**Engine source:** {_engine_source_label()}")
    if st.button("Quit Unidirectional One Shot", use_container_width=True):
        os._exit(0)
    st.divider()

    # ── Customer profile dropdown ─────────────────────────────────────
    st.markdown("**Customer profile**")
    _profile_names = list(CUSTOMER_PROFILES.keys())
    if st.session_state.get("otdr_profile") not in _profile_names:
        st.session_state.otdr_profile = _profile_names[0]
    if st.session_state.get("otdr_profile_select") not in _profile_names:
        st.session_state.pop("otdr_profile_select", None)
    _cur = st.session_state["otdr_profile"]
    _picked = st.selectbox(
        "Customer",
        _profile_names,
        index=_profile_names.index(_cur),
        label_visibility="collapsed",
        key="otdr_profile_select",
        help=("Each profile selects a different bundle of Apply / Fail "
              "values for the OTDR settings table below.  Pick 'Custom' "
              "to keep your own manual edits."),
    )
    if _picked != _cur:
        st.session_state.otdr_profile = _picked
        if "Custom" not in _picked:
            st.session_state.otdr_settings = _otdr_settings_from_profile(_picked)
        st.rerun()

    # ── EXFO threshold panel (the custom component) ───────────────────
    _otdr_rows_for_component = [
        {
            "key":       key,
            "label":     label,
            "unit":      unit,
            "supported": supported,
            "initial":   st.session_state.otdr_settings[key],
        }
        for key, label, _fail, unit, supported in OTDR_ROWS
    ]
    panel = otdr_settings_component(
        _otdr_rows_for_component,
        default=None,
        key=f"otdr_component::{st.session_state.otdr_profile}",
    )
    if panel:
        for key, vals in panel.items():
            st.session_state.otdr_settings[key] = {
                "apply":   bool(vals.get("apply")),
                "fail":    float(vals.get("fail", 0.0)),
                "warning": float(vals.get("warning", 0.0)),
            }


# ── OTDR settings → engine overrides ────────────────────────────────────
otdr = st.session_state.get("otdr_settings", {})


def _otdr_override(key: str, default: float) -> float:
    row = otdr.get(key) or {}
    if row.get("apply") and row.get("fail") is not None:
        try:
            return float(row["fail"])
        except (TypeError, ValueError):
            return default
    return default


bend_thr = _otdr_override("unidir_splice_loss", float(engine.BEND_THRESHOLD))
thresholds = {"BEND_THRESHOLD": float(bend_thr)}
ribbon_size = int(engine.RIBBON_SIZE)


# ─────────────────────────────────────────────────────────────────────
#  Step 1 — pick a folder OR a .zip
# ─────────────────────────────────────────────────────────────────────
st.subheader("1. Pick a folder or a ZIP")

if "_folder" not in st.session_state:
    st.session_state["_folder"] = ""

c1, c2, c3 = st.columns([1, 1, 4])
with c1:
    if st.button("Browse folder…", use_container_width=True):
        chosen = _native_pick_folder()
        if chosen:
            st.session_state["_folder"] = chosen
with c2:
    if st.button("Pick a ZIP…", use_container_width=True):
        chosen = _native_pick_zip()
        if chosen:
            st.session_state["_folder"] = chosen
with c3:
    pasted = st.text_input(
        "or paste a folder or .zip path",
        value=st.session_state["_folder"],
        placeholder=r"C:\OTDR\YAKCLE   |   C:\OTDR\YAKCLE.zip",
        label_visibility="collapsed",
    )
    if pasted != st.session_state["_folder"]:
        st.session_state["_folder"] = pasted

raw_input = (st.session_state["_folder"] or "").strip().strip('"')
if not raw_input:
    st.info("Click **Browse folder…**, **Pick a ZIP…**, or paste a path to begin.")
    st.stop()
if not (os.path.isfile(raw_input) or os.path.isdir(raw_input)):
    st.error(f"Path doesn't exist: `{raw_input}`")
    st.stop()
if os.path.isfile(raw_input) and not raw_input.lower().endswith(".zip"):
    st.error(f"Single files must be .zip — got `{os.path.basename(raw_input)}`")
    st.stop()

# Normalize: if user picked a single .zip, extract it (cached) and run
# the inventory against the extracted folder.  Otherwise pass through.
folder, was_extracted = _normalize_input(raw_input)
if was_extracted:
    st.caption(f"Extracted **{os.path.basename(raw_input)}** → `{folder}`")


# ─────────────────────────────────────────────────────────────────────
#  Step 2 — inventory
# ─────────────────────────────────────────────────────────────────────
st.subheader("2. Inventory")

with st.spinner(f"Scanning {folder}..."):
    inv = _inventory(folder)

c1, c2, c3, c4 = st.columns(4)
c1.metric("SOR (valid)",  len(inv["sor"]))
c2.metric("JSON (valid)", len(inv["json"]))
c3.metric("ZIP archives", len(inv["zip"]))
c4.metric("Skipped strays", len(inv["strays"]))

if inv["strays"]:
    with st.expander(f"Strays skipped by content sniff ({len(inv['strays'])})"):
        st.caption(
            "These files have a .sor or .json extension but their content "
            "doesn't match an EXFO/Bellcore OTDR acquisition.  They are "
            "ignored — usually FastReporter result files, project metadata, "
            "or sidecar JSONs."
        )
        for p in inv["strays"][:200]:
            st.write(f"• `{os.path.relpath(p, folder)}`")
        if len(inv["strays"]) > 200:
            st.write(f"...and {len(inv['strays']) - 200} more.")

n_valid = len(inv["sor"]) + len(inv["json"]) + len(inv["zip"])
if n_valid == 0:
    st.error("Nothing to run.  No valid SOR / JSON / ZIP files found in this folder.")
    st.stop()
if len(inv["sor"]) and len(inv["json"]):
    st.warning(
        "Mixed input formats: both SOR and JSON files were found.  "
        "The engine handles both, but if these are TWO separate jobs you "
        "probably want to point at one folder at a time."
    )


# ─────────────────────────────────────────────────────────────────────
#  Step 3 — direction
# ─────────────────────────────────────────────────────────────────────
st.subheader("3. Direction")

# Stage valid files (deduped basenames) into a fresh temp dir for the
# engine to walk.  Zips are passed through unmodified — engine handles
# them.
inputs = inv["sor"] + inv["json"] + inv["zip"]
staged_dir = _stage_flat(inputs)

with st.spinner("Reading direction metadata..."):
    sig_counts = _scan_directions(staged_dir)

if not sig_counts:
    st.error("Could not extract direction metadata from any file.")
    st.stop()

sig_df = pd.DataFrame(
    [{"Direction": k, "Fibers": v}
     for k, v in sorted(sig_counts.items(), key=lambda kv: -kv[1])]
)
st.dataframe(sig_df, hide_index=True, use_container_width=True)

if len(sig_counts) == 1:
    chosen_dir = next(iter(sig_counts))
    st.success(f"Single direction detected — running on **{chosen_dir}** "
               f"({sig_counts[chosen_dir]} fibers).")
else:
    chosen_dir = st.selectbox(
        "Multiple directions found — pick which to run:",
        options=list(sig_counts.keys()),
        index=0,
        format_func=lambda s: f"{s}   ({sig_counts[s]} fibers)",
    )


# ─────────────────────────────────────────────────────────────────────
#  Step 4 — run
# ─────────────────────────────────────────────────────────────────────
st.subheader("4. Run")

# Output goes into a subfolder next to the inputs.  When the user
# picked a .zip we extracted it to a temp dir — we don't want the
# Excel buried in there, so write next to the original zip instead.
output_root = os.path.dirname(raw_input) if was_extracted else folder
output_dir  = os.path.join(output_root, "_unidir_output")

run_clicked = st.button("Run unidirectional event finder",
                        type="primary", use_container_width=True)

if run_clicked:
    with st.spinner(f"Running on {sig_counts.get(chosen_dir, '?')} fibers..."):
        result = _run_engine(staged_dir, chosen_dir, ribbon_size,
                             thresholds, output_dir)
    if "error" in result:
        st.error(result["error"]); st.stop()
    st.session_state["_last_result"] = result

result = st.session_state.get("_last_result")
if not result:
    st.info("Click **Run** to process the selected direction.")
    st.stop()


# ─────────────────────────────────────────────────────────────────────
#  Step 5 — results
# ─────────────────────────────────────────────────────────────────────
st.subheader("5. Results")

m = st.columns(6)
m[0].metric("Fibers",            result["n_fibers"])
m[1].metric("Cable span (km)",   f"{result['span_km']:.2f}")
m[2].metric("Splice columns",    result["n_splices"])
m[3].metric("Bend/Damage",       result["n_bend"])
m[4].metric("Break columns",     result["n_break"])
m[5].metric("Broken fibers",     result["n_break_fib"])

st.success(f"Saved Excel to:  `{result['xlsx_path']}`")

st.download_button(
    "Download Excel report",
    data=result["xlsx_bytes"],
    file_name=os.path.basename(result["xlsx_path"]),
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    use_container_width=True,
)

st.markdown("### Flagged events")
df = result["preview_df"]
fcols = st.columns(3)
with fcols[0]:
    fiber_sel = st.multiselect("Fiber #", sorted(df["Fiber"].unique()), default=[])
with fcols[1]:
    kind_sel = st.multiselect("Kind", df["Kind"].unique().tolist(), default=[])
with fcols[2]:
    col_sel = st.multiselect("Column", df["Column"].unique().tolist(), default=[])

filtered = df
if fiber_sel: filtered = filtered[filtered["Fiber"].isin(fiber_sel)]
if kind_sel:  filtered = filtered[filtered["Kind"].isin(kind_sel)]
if col_sel:   filtered = filtered[filtered["Column"].isin(col_sel)]
st.dataframe(filtered, hide_index=True, use_container_width=True, height=450)
st.caption(f"Showing {len(filtered):,} of {len(df):,} flagged-event rows.")
