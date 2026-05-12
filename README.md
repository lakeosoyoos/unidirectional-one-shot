# Unidirectional One Shot

A-direction-only OTDR event finder. Streamlit web UI on top of an event-discovery engine that pulls every fiber's events from SOR / JSON / ZIP, groups them into splice / possible bend-damage / break columns, and produces a ribbon-grid Excel.

## What it does

1. **Auto-detects SOR vs JSON** per file. Auto-extracts ZIPs.
2. **Filters by direction from file metadata** (not filename). Reads the Bellcore `GenParams` block for SOR or `Identification.LocationA/B` + `FiberInformation.LocationDirection` for EXFO JSON. Multiple directions in the upload → user picks one.
3. **Discovers splice closure positions** from the A-side fiber population (1 km bins, ≥ 20 fibers, mode-peak refinement, phantom rejection).
4. **Classifies every event ≥ 0.100 dB** into one of three categories:
   - **Splice** — within ±150 m of a validated closure.
   - **Possible Bend / Damage** — anywhere else; clusters merge events within 100 m of each other.
   - **Break** — fiber's trace dies > 3 km short of the cable span and not at a splice.
5. **Writes a ribbon-grid Excel** (Calibri 12) with three sheets:
   - **Unidir Events** — ribbons × columns, shaded cells labeled with fiber numbers and the worst loss in the group.
   - **Legend** — color/cell key + cell-label format key.
   - **Flagged Events** — one row per fiber × event, with auto-filter and a "Why flagged" reason column.

## Run locally

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy

The repo runs on Streamlit Community Cloud as-is — no native dependencies, no API keys required. Point Streamlit at `streamlit_app.py`.

## Tunables

All thresholds live at the top of [`unidirectional_event_finder.py`](unidirectional_event_finder.py):

| Constant | Default | Used for |
|---|---|---|
| `BEND_THRESHOLD` | 0.100 dB | Universal flag threshold. Events below this are silent. |
| `CLOSURE_MATCH_KM` | 0.150 km | Splice-proximity radius — events inside this go in the splice column. |
| `OFF_SPLICE_CLUSTER_M` | 100 m | Off-splice / break clustering window. |
| `MIN_POP_SPLICE` | 20 fibers | Minimum population to call a candidate splice. |
| `BREAK_PREMATURE_KM` | 3.0 km | Fiber EOF must be at least this far short of the cable end to count as a break. |

## Files

- `streamlit_app.py` — the UI (upload → direction → run → preview → download).
- `unidirectional_event_finder.py` — engine. Has its own CLI: `python unidirectional_event_finder.py <dir-or-zip> --output report.xlsx`.
- `sor_reader324802a.py` — Bellcore SOR parser (trace + events + EXFO proprietary extras).
- `json_reader.py` — EXFO FastReporter JSON parser.
