"""
streamlit_app.py — Unidirectional One Shot
==========================================

Web UI for the A-direction-only event finder.  Upload a ZIP (or individual
SOR / JSON files), pick a direction if multiple are detected, click Run.
The app produces the same Excel as ``unidirectional_event_finder.py``
plus an in-page preview of flagged events.

Deployable to Streamlit Community Cloud — only depends on numpy,
pandas, openpyxl, and streamlit.
"""
from __future__ import annotations

import io
import os
import tempfile
import zipfile
from collections import Counter
from typing import Optional

import pandas as pd
import streamlit as st

import unidirectional_event_finder as engine


st.set_page_config(
    page_title="Unidirectional One Shot",
    page_icon="🪢",
    layout="wide",
)

st.title("Unidirectional One Shot")
st.caption(
    "A-direction-only event finder for OTDR splice / bend / break QC. "
    "Upload SOR/JSON files (or a ZIP of them), pick a direction, get a "
    "ribbon-grid Excel and a per-fiber flagged-events table."
)


# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────

def _stage_uploads(uploaded_files) -> str:
    """Write the uploaded files to a temp directory and return its path.
    Any uploaded .zip is left as-is — the engine's _walk_files() will
    descend into it."""
    tmp = tempfile.mkdtemp(prefix="unidir_st_")
    for uf in uploaded_files:
        out_path = os.path.join(tmp, uf.name)
        with open(out_path, "wb") as fh:
            fh.write(uf.getbuffer())
    return tmp


@st.cache_data(show_spinner=False)
def _scan_directions(staged_dir: str) -> dict:
    """Walk the uploaded tree, parse every file, and group fibers by the
    direction signature derived from the file metadata.  Returns a dict
    keyed by signature, value=count.  Cached so re-clicks are instant."""
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
                ribbon_size: int, thresholds: dict) -> dict:
    """Run the full pipeline.  Returns a dict with the Excel bytes,
    rows for the preview table, and run-summary numbers.

    ``thresholds`` is a dict of keys that match the engine's module-level
    constants — they're applied for the duration of this run and restored
    after.  Lets the UI tune values without forking the engine module.
    """
    # Snapshot + override engine constants for this run
    overridable = (
        'BEND_THRESHOLD',
        'CLOSURE_MATCH_KM',
        'OFF_SPLICE_CLUSTER_M',
        'MIN_POP_SPLICE',
        'BREAK_PREMATURE_KM',
    )
    saved = {k: getattr(engine, k) for k in overridable}
    try:
        for k, v in (thresholds or {}).items():
            if k in overridable:
                setattr(engine, k, v)
        return _run_engine_inner(staged_dir, direction, ribbon_size)
    finally:
        for k, v in saved.items():
            setattr(engine, k, v)


def _run_engine_inner(staged_dir: str, direction: Optional[str],
                      ribbon_size: int) -> dict:
    fibers, chosen = engine.load_fibers(staged_dir, direction=direction)
    if not fibers:
        return {'error': 'No fibers loaded for the selected direction.'}

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

    # Site codes from metadata
    sample = next(iter(fibers.values()))
    meta = sample.get('_genparams') or {}
    site_a = engine._short_code(meta.get('orig_loc'))
    site_b = engine._short_code(meta.get('term_loc'))
    if (not site_a or not site_b) and chosen and '->' in chosen:
        a, b = chosen.split('->', 1)
        site_a = site_a or engine._short_code(a)
        site_b = site_b or engine._short_code(b)

    # Write Excel to a temp file, then read bytes back for download
    out_path = os.path.join(tempfile.mkdtemp(prefix="unidir_out_"),
                            "unidirectional_events.xlsx")
    engine.write_xlsx(grid, columns, n_fibers, ribbon_size, span, out_path,
                      site_a=site_a, site_b=site_b)
    with open(out_path, 'rb') as fh:
        xlsx_bytes = fh.read()

    # Build the in-page preview table from the same data the Excel uses
    rows = engine._flagged_event_rows(grid, columns, ribbon_size, n_fibers)
    df = pd.DataFrame([
        {
            'Fiber':         r['fiber'],
            'Ribbon':        r['ribbon'],
            'Column':        r['column_label'],
            'Distance (km)': round(r['column_km'], 2),
            'Loss (dB)':     ('broke' if r['loss'] is None
                              else round(r['loss'], 3)),
            'Kind':          {'splice': 'Splice',
                              'bend_damage': 'Possible Bend/Damage',
                              'break': 'BREAK'}.get(r['column_kind'],
                                                   r['column_kind']),
            'Why flagged':   r['reason'],
        }
        for r in rows
    ])

    return {
        'xlsx_bytes':    xlsx_bytes,
        'preview_df':    df,
        'n_fibers':      len(fibers),
        'direction':     chosen,
        'site_a':        site_a,
        'site_b':        site_b,
        'n_splices':     sum(1 for c in columns if c['kind'] == 'splice'),
        'n_bend':        sum(1 for c in columns if c['kind'] == 'bend_damage'),
        'n_break':       sum(1 for c in columns if c['kind'] == 'break'),
        'n_break_fib':   len(breaks),
        'span_km':       span,
        'n_phantoms':    len(candidates) - len(valid),
    }


# ─────────────────────────────────────────────────────────────────────
#  Sidebar — EXFO-styled OTDR settings panel (mirrors splice-report)
# ─────────────────────────────────────────────────────────────────────
#  The Description / Apply / Fail / Warning table is rendered by a custom
#  Streamlit component (components/otdr_settings/index.html) that matches
#  the EXFO threshold-panel look pixel-for-pixel.  Rows marked
#  supported=True are wired to engine constants; the rest are visual
#  parity with the EXFO panel and tagged "not yet wired" until we have
#  engine code to back them.
# Row list mirrors the splice-report panel byte-for-byte (same labels,
# same defaults, same units, same supported flags).  Visual parity is the
# point — the tech reads the same panel in both apps.
#
# NOTE on `supported`: the flag tells the component whether to decorate
# the row as "not yet wired".  Splice report marks 4 rows supported=True
# (unidir_splice_loss, bidir_splice_loss, bidir_connector_loss,
# reflectance) because IT has engine code for all four.  Uni one shot's
# engine only consumes BEND_THRESHOLD, so only unidir_splice_loss
# actually affects output here.  The other three are kept at
# supported=True for visual identity with splice report; ticking Apply
# on any of them is a no-op for uni until we wire equivalents.
OTDR_ROWS = [
    # (key,                       label,                       fail_default,  unit,    supported)
    ("unidir_splice_loss",        "Unidir. splice loss",        0.250,        "dB",    True),
    ("bidir_splice_loss",         "Bidir splice loss",          0.160,        "dB",    True),
    ("unidir_connector_loss",     "Unidir. connector loss",     0.750,        "dB",    False),
    ("bidir_connector_loss",      "Bidir connector loss",       0.500,        "dB",    True),
    ("splitter_loss",             "Splitter Loss",              4.500,        "dB",    False),
    ("reflectance",               "Reflectance",                -49.9,        "dB",    True),
    ("fiber_section_atten",       "Fiber section attenuation",  0.400,        "dB/km", False),
    ("span_loss",                 "Span loss",                  20.000,       "dB",    False),
    ("span_length",               "Span length",                0.0000,       "km",    False),
    ("span_orl",                  "Span ORL",                   15.00,        "dB",    False),
]
# Pre-checked rows (match splice-report's out-of-the-box flagging).
OTDR_DEFAULT_APPLY = {"unidir_splice_loss", "bidir_splice_loss",
                      "bidir_connector_loss", "reflectance"}


# Customer threshold profiles — copied verbatim from splice-report so
# the same dropdown selections behave the same way across apps.
CUSTOMER_PROFILES = {
    "Default (engine baseline)": {
        "apply":      set(OTDR_DEFAULT_APPLY),
        "thresholds": {},
    },
    "Lumen": {
        "apply":      {"unidir_splice_loss", "bidir_splice_loss",
                        "bidir_connector_loss", "reflectance"},
        "thresholds": {
            "bidir_splice_loss":     0.120,
            "unidir_splice_loss":    0.200,
            "bidir_connector_loss":  0.400,
            "reflectance":          -50.0,
        },
    },
    "Zayo": {
        "apply":      {"bidir_splice_loss", "bidir_connector_loss"},
        "thresholds": {
            "bidir_splice_loss":     0.200,
            "bidir_connector_loss":  0.600,
        },
    },
    "Custom (edit table below)": {  # sentinel — uses session edits as-is
        "apply":      None,
        "thresholds": None,
    },
}


def _otdr_settings_from_profile(profile_name: str) -> dict:
    """Return a fresh otdr_settings dict for the named profile."""
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


# Initialise persisted settings + active profile on first run
if "otdr_profile" not in st.session_state:
    st.session_state.otdr_profile = next(iter(CUSTOMER_PROFILES))
if "otdr_settings" not in st.session_state:
    st.session_state.otdr_settings = _otdr_settings_from_profile(
        st.session_state.otdr_profile)


from components.otdr_settings import otdr_settings as otdr_settings_component


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

    # ── Customer profile dropdown ─────────────────────────────────────
    # Picking a customer rewrites session_state.otdr_settings with that
    # customer's preset and re-mounts the component (a fresh key= forces
    # it to re-render with the new initials).
    st.markdown("**Customer profile**")
    _profile_names = list(CUSTOMER_PROFILES.keys())

    # Defensive cleanup: stale session state from a prior deploy.
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

    # ── Threshold table (custom HTML/CSS/JS component) ─────────────────
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
    # Component key encodes the active profile so switching customers
    # forces a re-mount with the new initial values.
    _commit = otdr_settings_component(
        _otdr_rows_for_component,
        default=None,
        key=f"otdr_component::{st.session_state.otdr_profile}",
    )
    if _commit:
        for key, vals in _commit.items():
            st.session_state.otdr_settings[key] = {
                "apply":   bool(vals.get("apply")),
                "fail":    float(vals.get("fail", 0.0)),
                "warning": float(vals.get("warning", 0.0)),
            }

# Engine defaults for the knobs we no longer expose in the UI.  If you
# want to tune these, edit the constants at the top of
# unidirectional_event_finder.py.
ribbon_size        = int(engine.RIBBON_SIZE)

# ── OTDR settings → engine overrides ────────────────────────────────────
# When a row's Apply checkbox is ticked, its Fail value overrides the
# engine default for that threshold.  Unticked rows fall back to the
# engine value.
otdr = st.session_state.get("otdr_settings", {})


def _otdr_override(key, engine_default):
    row = otdr.get(key) or {}
    if row.get("apply") and row.get("fail") is not None:
        return float(row["fail"])
    return engine_default


bend_thr = _otdr_override("unidir_splice_loss", float(engine.BEND_THRESHOLD))

# Only the wired EXFO row participates in per-run overrides.  Everything
# else (splice match radius, cluster window, min population, break
# premature buffer) falls back to the engine module's default.
thresholds = {
    'BEND_THRESHOLD': float(bend_thr),
}


# ─────────────────────────────────────────────────────────────────────
#  Step 1 — upload
# ─────────────────────────────────────────────────────────────────────
st.subheader("1. Upload")
uploaded = st.file_uploader(
    "Drop in a ZIP — or any combination of SOR / JSON files",
    type=['zip', 'sor', 'json'],
    accept_multiple_files=True,
)

if not uploaded:
    st.info("Drop in a folder zip (one direction's worth of fiber shots) or "
            "individual SOR / JSON files.  Direction is detected from each "
            "file's GenParams metadata — not the filename.")
    st.stop()

# Stage uploads to a temp dir.  Cached by the set of file names+sizes so a
# rerun (e.g. clicking Run again) doesn't restage.
upload_key = tuple((u.name, u.size) for u in uploaded)
if st.session_state.get('_upload_key') != upload_key:
    st.session_state['_upload_key'] = upload_key
    st.session_state['_staged_dir'] = _stage_uploads(uploaded)
    _scan_directions.clear()
staged_dir = st.session_state['_staged_dir']

# ─────────────────────────────────────────────────────────────────────
#  Step 2 — direction
# ─────────────────────────────────────────────────────────────────────
st.subheader("2. Direction")
with st.spinner("Scanning file metadata..."):
    sig_counts = _scan_directions(staged_dir)

if not sig_counts:
    st.error("No usable SOR/JSON files found in the upload.")
    st.stop()

st.caption("Direction signatures from file metadata "
           "(originating → terminating location, or cable id when "
           "the two ends share a name):")

sig_df = pd.DataFrame(
    [{'Direction': k, 'Fibers': v}
     for k, v in sorted(sig_counts.items(), key=lambda kv: -kv[1])]
)
st.dataframe(sig_df, hide_index=True, width="stretch")

if len(sig_counts) == 1:
    chosen_dir = next(iter(sig_counts))
    st.success(f"Single direction detected — running on **{chosen_dir}** "
               f"({sig_counts[chosen_dir]} fibers).")
else:
    chosen_dir = st.selectbox(
        "Two or more directions found — pick which to run on:",
        options=list(sig_counts.keys()),
        index=0,
        format_func=lambda s: f"{s}   ({sig_counts[s]} fibers)",
    )


# ─────────────────────────────────────────────────────────────────────
#  Step 3 — run
# ─────────────────────────────────────────────────────────────────────
st.subheader("3. Run")
run_clicked = st.button("Run unidirectional event finder",
                         type='primary', width="stretch")

if run_clicked:
    with st.spinner(f"Running on {sig_counts.get(chosen_dir, '?')} fibers — "
                    "loading, discovering splices, classifying events..."):
        result = _run_engine(staged_dir, chosen_dir, int(ribbon_size),
                             thresholds)
    if 'error' in result:
        st.error(result['error'])
        st.stop()
    st.session_state['_last_result'] = result

result = st.session_state.get('_last_result')
if not result:
    st.info("Click **Run** to process the selected direction.")
    st.stop()


# ─────────────────────────────────────────────────────────────────────
#  Step 4 — summary + downloads + preview
# ─────────────────────────────────────────────────────────────────────
st.subheader("4. Results")

m = st.columns(6)
m[0].metric("Fibers", result['n_fibers'])
m[1].metric("Cable span (km)", f"{result['span_km']:.2f}")
m[2].metric("Splice columns", result['n_splices'])
m[3].metric("Bend/Damage", result['n_bend'])
m[4].metric("Break columns", result['n_break'])
m[5].metric("Broken fibers", result['n_break_fib'])

dl_name = f"unidir_{result['site_a'] or 'A'}_{result['site_b'] or 'B'}.xlsx"
st.download_button(
    "Download Excel report",
    data=result['xlsx_bytes'],
    file_name=dl_name,
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    type='primary',
    width="stretch",
)

st.markdown("### Flagged events")
st.caption("Filter / sort to find every fiber's reason for being flagged.  "
           "Same content as the **Flagged Events** sheet in the Excel.")

# Built-in filters: by Fiber, Kind, Column
df = result['preview_df']
fcols = st.columns(3)
with fcols[0]:
    fiber_sel = st.multiselect("Fiber #",
                               options=sorted(df['Fiber'].unique()),
                               default=[])
with fcols[1]:
    kind_sel = st.multiselect("Kind",
                              options=df['Kind'].unique().tolist(),
                              default=[])
with fcols[2]:
    col_sel = st.multiselect("Column",
                             options=df['Column'].unique().tolist(),
                             default=[])

filtered = df
if fiber_sel:
    filtered = filtered[filtered['Fiber'].isin(fiber_sel)]
if kind_sel:
    filtered = filtered[filtered['Kind'].isin(kind_sel)]
if col_sel:
    filtered = filtered[filtered['Column'].isin(col_sel)]

st.dataframe(
    filtered,
    hide_index=True,
    width="stretch",
    height=450,
)
st.caption(f"Showing {len(filtered):,} of {len(df):,} flagged-event rows.")
