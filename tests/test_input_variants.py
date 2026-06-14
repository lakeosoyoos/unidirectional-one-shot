"""
test_input_variants.py — pin the engine's input-side contract.
================================================================

Covers Phase 1 audit findings around how the desktop app + engine
turn an arbitrary user-supplied folder / zip into a list of fibers
to process:

  H1  — _inventory does NOT skip macOS ._* AppleDouble sidecars.
  H3  — Nested zips silently dropped (engine recurses one zip only).
  L1  — A==B / multi-direction folders aren't flagged at Inventory.
  L2  — _extract_zip cache keyed on (path, mtime); stale content wins
        when a zip is overwritten with mtime preserved.
  +   — load_fibers duplicate-fiber WARN with 5-line cap.
  +   — folder == zip equivalence.
  +   — content-sniff rejects garbage .json / .sor.
  +   — Windows backslash zip entries still parse.
  +   — _stage_flat sub-dir basename collision (H2) — XFAIL.

PASS tests pin current behaviour.  Strict-XFAIL tests pin the
DESIRED behaviour — they will flip to PASS once the underlying bug
is fixed, at which point pytest will fail loudly and force this
file to be updated.

NOTE — most of these tests need helpers from ``desktop_app.py``
(``_inventory``, ``_stage_flat``, ``_extract_zip``, ``_is_otdr_json``).
Importing that module normally runs the entire Streamlit UI script
top-to-bottom, which crashes outside a real Streamlit run.  The
``_load_desktop_helpers()`` fixture below monkey-patches
``streamlit.stop`` to raise SystemExit, then imports the module —
the function definitions live above the first ``st.stop()``, so we
get the helpers without paying for the UI.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import shutil
import sys
import tempfile
import zipfile

import openpyxl
import pytest

from conftest import APP_PATH, FIXTURE_DIR, REPO_ROOT  # noqa: F401


# ─────────────────────────────────────────────────────────────────────
#  Helper loader — pulls the pure helpers out of desktop_app.py
#  without running the Streamlit UI script.
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def desktop_helpers():
    """Return the desktop_app module with ``_inventory`` / ``_stage_flat`` /
    ``_extract_zip`` / ``_is_otdr_json`` / ``_is_sor`` available.

    Module load is short-circuited via a monkey-patched ``st.stop`` that
    raises ``SystemExit``; the helpers are all defined above that point.
    """
    import streamlit as st

    real_stop = st.stop

    def _patched_stop():
        raise SystemExit("test-suite halt at st.stop()")

    st.stop = _patched_stop
    try:
        spec = importlib.util.spec_from_file_location(
            "desktop_app_under_test",
            str(APP_PATH),
        )
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass  # expected — we tripped st.stop on purpose
    finally:
        st.stop = real_stop

    # Sanity check — confirm we actually got the helpers.
    for attr in ("_inventory", "_stage_flat", "_extract_zip",
                 "_is_otdr_json", "_is_sor"):
        assert hasattr(mod, attr), (
            f"desktop_app loader did not expose {attr!r} — the module "
            "structure changed; update _load_desktop_helpers."
        )
    return mod


# ─────────────────────────────────────────────────────────────────────
#  Tiny fixture helpers
# ─────────────────────────────────────────────────────────────────────
FIXTURE_JSONS = sorted(FIXTURE_DIR.glob("YAKCLE*_1550 .json"))


def _make_zip_of_fixtures(zip_path: pathlib.Path,
                          n_files: int | None = None) -> None:
    """Write a zip at ``zip_path`` containing the first ``n_files``
    fixture JSONs at the zip root.  ``n_files=None`` → all of them."""
    files = FIXTURE_JSONS if n_files is None else FIXTURE_JSONS[:n_files]
    with zipfile.ZipFile(zip_path, "w") as zf:
        for src in files:
            zf.write(src, arcname=src.name)


# ─────────────────────────────────────────────────────────────────────
#  1. PASS — folder vs zip produce equivalent engine output
# ─────────────────────────────────────────────────────────────────────
def test_folder_and_zip_produce_equivalent_output(tmp_path: pathlib.Path):
    """Same 25 fibers fed once as a folder and once as a single zip
    must produce identical Flagged-Events sheet contents.  Locks in
    the contract that zip handling is engine-internal and lossless."""
    import unidirectional_event_finder as engine

    # ── Folder branch
    folder_out = tmp_path / "folder_out.xlsx"
    fibers_a, _ = engine.load_fibers(str(FIXTURE_DIR))
    engine.normalize_all(fibers_a)
    cand_a   = engine.discover_splices(fibers_a)
    valid_a  = engine.refine_and_validate(fibers_a, cand_a)
    off_a    = engine.find_off_splice_events(fibers_a, valid_a)
    off_col_a = engine.cluster_off_splice(off_a, fibers_a)
    span_a   = engine.auto_detect_span(fibers_a)
    breaks_a = engine.find_breaks(fibers_a, valid_a, span_a)
    bcol_a   = engine.cluster_breaks(breaks_a)
    cols_a   = engine.build_columns(valid_a, off_col_a, bcol_a)
    grid_a   = engine.build_ribbon_grid(fibers_a, cols_a, 12)
    engine.write_xlsx(grid_a, cols_a, max(fibers_a.keys()),
                      12, span_a, str(folder_out),
                      site_a="A", site_b="B", fibers=fibers_a)

    # ── Zip branch
    zip_path = tmp_path / "cleyak_mini.zip"
    _make_zip_of_fixtures(zip_path)

    zip_out = tmp_path / "zip_out.xlsx"
    fibers_b, _ = engine.load_fibers(str(zip_path))
    engine.normalize_all(fibers_b)
    cand_b   = engine.discover_splices(fibers_b)
    valid_b  = engine.refine_and_validate(fibers_b, cand_b)
    off_b    = engine.find_off_splice_events(fibers_b, valid_b)
    off_col_b = engine.cluster_off_splice(off_b, fibers_b)
    span_b   = engine.auto_detect_span(fibers_b)
    breaks_b = engine.find_breaks(fibers_b, valid_b, span_b)
    bcol_b   = engine.cluster_breaks(breaks_b)
    cols_b   = engine.build_columns(valid_b, off_col_b, bcol_b)
    grid_b   = engine.build_ribbon_grid(fibers_b, cols_b, 12)
    engine.write_xlsx(grid_b, cols_b, max(fibers_b.keys()),
                      12, span_b, str(zip_out),
                      site_a="A", site_b="B", fibers=fibers_b)

    # Compare per-fiber flagged-event row COUNTS (canonical
    # "did the engine see the same events" check, immune to xlsx
    # cell-style noise).
    def _flagged_counts(path):
        from collections import Counter
        wb = openpyxl.load_workbook(path, read_only=True)
        try:
            ws = wb["Flagged Events"]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()
        # First row is header.  Find Fiber column.
        if not rows:
            return Counter()
        hdr = rows[0]
        try:
            fib_col = hdr.index("Fiber")
        except ValueError:
            return Counter()
        return Counter(r[fib_col] for r in rows[1:])

    assert _flagged_counts(folder_out) == _flagged_counts(zip_out), (
        "Folder vs zip ingestion produced different per-fiber flagged "
        "event row counts — the zip path is dropping or mangling files."
    )


# ─────────────────────────────────────────────────────────────────────
#  2. PASS — content-sniff rejects a .json that's not OTDR
# ─────────────────────────────────────────────────────────────────────
def test_content_sniff_rejects_garbage_json(desktop_helpers,
                                            tmp_path: pathlib.Path):
    """A .json file whose body is just {"foo": 1} must be classified
    as a stray by _inventory, not counted as a fiber."""
    # One real JSON
    real = FIXTURE_JSONS[0]
    shutil.copy2(real, tmp_path / real.name)
    # One garbage JSON
    (tmp_path / "garbage.json").write_text('{"foo": 1}\n')

    inv = desktop_helpers._inventory(str(tmp_path))
    json_basenames  = {os.path.basename(p) for p in inv["json"]}
    stray_basenames = {os.path.basename(p) for p in inv["strays"]}

    assert real.name in json_basenames, (
        f"real OTDR JSON {real.name!r} was not classified as valid."
    )
    assert "garbage.json" in stray_basenames, (
        "garbage.json containing {\"foo\": 1} should have been "
        f"flagged as a stray; got strays={stray_basenames!r}"
    )


# ─────────────────────────────────────────────────────────────────────
#  3. PASS — content-sniff rejects a .sor that's not Bellcore
# ─────────────────────────────────────────────────────────────────────
def test_content_sniff_rejects_garbage_sor(desktop_helpers,
                                           tmp_path: pathlib.Path):
    """A .sor file whose first 4 bytes aren't ``Map\\x00`` must be
    classified as a stray (and the real fixture JSON still passes)."""
    real = FIXTURE_JSONS[0]
    shutil.copy2(real, tmp_path / real.name)
    (tmp_path / "garbage.sor").write_bytes(b"NOT A SOR FILE")

    inv = desktop_helpers._inventory(str(tmp_path))
    sor_basenames   = {os.path.basename(p) for p in inv["sor"]}
    stray_basenames = {os.path.basename(p) for p in inv["strays"]}

    # The garbage.sor lives in the stray bucket, not the sor bucket.
    assert "garbage.sor" not in sor_basenames
    assert "garbage.sor" in stray_basenames, (
        "garbage.sor without the Map magic-byte header should have "
        f"been a stray; got strays={stray_basenames!r}"
    )


# ─────────────────────────────────────────────────────────────────────
#  4. PASS — Windows-built zip entries with backslash separators
#  are still found by the engine.
# ─────────────────────────────────────────────────────────────────────
def test_windows_backslash_zip_entries_resolved(tmp_path: pathlib.Path):
    """Zips built on Windows can carry ``subdir\\foo.json`` entry names
    with a backslash separator.  ``zipfile.ZipFile.extractall`` on
    POSIX writes those as literally-named files in the root rather than
    making a subdir, so the engine's ``_walk_files`` should still find
    them at the top level."""
    import unidirectional_event_finder as engine

    # Read one fixture's bytes
    real = FIXTURE_JSONS[0]
    payload = real.read_bytes()

    zpath = tmp_path / "winzip.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        # Entry name uses backslash on purpose.
        zf.writestr(f"subdir\\{real.name}", payload)

    extract_dir = tmp_path / "ext"
    extract_dir.mkdir()
    with zipfile.ZipFile(zpath) as zf:
        zf.extractall(extract_dir)

    found = list(engine._walk_files(str(extract_dir)))
    assert found, (
        "engine._walk_files found nothing in the extracted Windows-style "
        "zip — the backslash entry name was likely silently dropped."
    )
    # And that file must be a JSON (otherwise we extracted the literal-
    # backslash filename but missed the .json extension).
    names = [n for _, n in found]
    assert any(n.lower().endswith(".json") for n in names), (
        f"extracted entries were not recognized as JSON: {names!r}"
    )


# ─────────────────────────────────────────────────────────────────────
#  5. PASS — duplicate fnum keeps the first file and emits a WARN
# ─────────────────────────────────────────────────────────────────────
def test_duplicate_fiber_keeps_first_and_warns(tmp_path: pathlib.Path,
                                               capsys):
    """Two real JSONs renamed to the same basename → loader keeps the
    first, skips the second, and prints ``WARN: duplicate fiber``."""
    import unidirectional_event_finder as engine

    src = FIXTURE_JSONS[0]
    payload = src.read_bytes()
    # Same stem (so _extract_fiber_num returns the same number for both),
    # different filename so both land on disk.
    (tmp_path / "YAKCLE001_1550 .json").write_bytes(payload)
    (tmp_path / "OTHER_YAKCLE001_1550 .json").write_bytes(payload)

    capsys.readouterr()  # reset
    fibers, _ = engine.load_fibers(str(tmp_path))
    out = capsys.readouterr().out

    # Only ONE fiber kept (both extract to fnum=1).
    assert len(fibers) == 1, (
        f"expected 1 fiber after dedupe, got {len(fibers)}: "
        f"{sorted(fibers.keys())}"
    )
    assert "WARN: duplicate fiber" in out, (
        "loader did not print a duplicate-fiber WARN.  "
        f"stdout was:\n{out!r}"
    )


# ─────────────────────────────────────────────────────────────────────
#  6. PASS — duplicate WARN cap at 5 lines + 1 "suppressed" line
# ─────────────────────────────────────────────────────────────────────
def test_duplicate_fiber_warn_cap_at_5(tmp_path: pathlib.Path, capsys):
    """Stage 10 collisions on fnum=1.  Loader must print exactly 5
    visible WARNs plus 1 ``+N more ... suppressed`` summary line."""
    import unidirectional_event_finder as engine

    src = FIXTURE_JSONS[0]
    payload = src.read_bytes()
    # 11 files, all extract to fnum=1 — first one kept, 10 collisions.
    for i in range(11):
        (tmp_path / f"PREFIX{i:03d}_YAKCLE001_1550 .json").write_bytes(payload)

    capsys.readouterr()
    fibers, _ = engine.load_fibers(str(tmp_path))
    out = capsys.readouterr().out

    assert len(fibers) == 1, f"expected dedupe to 1 fiber, got {len(fibers)}"

    visible_warns = [
        ln for ln in out.splitlines()
        if "WARN: duplicate fiber" in ln and "suppressed" not in ln
    ]
    suppressed_lines = [
        ln for ln in out.splitlines()
        if "duplicate-fiber" in ln and "suppressed" in ln
    ]

    assert len(visible_warns) == 5, (
        f"expected exactly 5 visible duplicate-fiber WARN lines (the "
        f"DUP_WARN_CAP), got {len(visible_warns)}.\n"
        f"stdout was:\n{out}"
    )
    assert len(suppressed_lines) == 1, (
        f"expected one '+N more ... suppressed' summary line, got "
        f"{len(suppressed_lines)}.\nstdout was:\n{out}"
    )
    # And that summary line must mention 5 (we had 10 collisions; cap 5
    # printed, so 5 suppressed).
    assert "+5" in suppressed_lines[0], (
        f"suppressed-line should report '+5 more...': {suppressed_lines[0]!r}"
    )


# ─────────────────────────────────────────────────────────────────────
#  7. XFAIL (H1) — _inventory should skip macOS AppleDouble sidecars
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason="H1: _inventory does not skip ._* AppleDouble files; "
           "_walk_files and _extract_fiber_num both do.  Mac-extracted "
           "zips inflate the strays count by ~2x.  Fix by adding the "
           "same ._ skip in _inventory.",
)
def test_inventory_skips_appledouble_files(desktop_helpers,
                                           tmp_path: pathlib.Path):
    """Drop one real JSON plus a sibling ``._YAKCLE001_1550 .json``
    sidecar holding AppleDouble magic bytes.  _inventory should NOT
    count the sidecar as a stray (or anything at all)."""
    real = FIXTURE_JSONS[0]
    shutil.copy2(real, tmp_path / real.name)
    # AppleDouble magic: 0x00 0x05 0x16 0x07
    (tmp_path / f"._{real.name}").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 64)

    inv = desktop_helpers._inventory(str(tmp_path))

    # The desired behaviour: zero strays.  Today the AppleDouble file
    # lands in strays, so this assertion fails — hence XFAIL strict.
    assert len(inv["strays"]) == 0, (
        f"AppleDouble sidecar must be invisible to inventory; "
        f"got strays={[os.path.basename(p) for p in inv['strays']]!r}"
    )


# ─────────────────────────────────────────────────────────────────────
#  8. XFAIL (H3) — nested zip-of-zip: inner zip's contents are dropped
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason="H3: engine._walk_files only recurses ONE zip layer.  A "
           "zip-of-zips loses everything inside the inner zip.  Fix "
           "by recursing into any .zip seen during the extracted-tree "
           "walk.",
)
def test_nested_zip_extraction(tmp_path: pathlib.Path):
    """outer.zip contains inner.zip which contains real JSONs.  Loader
    should still find those JSONs."""
    import unidirectional_event_finder as engine

    # Inner zip: 5 real fixtures
    inner = tmp_path / "inner.zip"
    _make_zip_of_fixtures(inner, n_files=5)
    # Outer zip wrapping the inner
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as zf:
        zf.write(inner, arcname="inner.zip")

    fibers, _ = engine.load_fibers(str(outer))
    assert len(fibers) == 5, (
        f"nested-zip recursion broken — expected 5 fibers from "
        f"inner.zip's contents, got {len(fibers)}."
    )


# ─────────────────────────────────────────────────────────────────────
#  9. XFAIL (L1) — _inventory should surface multi-direction folders
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason="L1: A==B / multi-direction folders are only flagged at "
           "Step 3 (Direction).  _inventory has no 'direction_counts' "
           "channel.  Surface it earlier so techs see the mix at "
           "the inventory step.",
)
def test_inventory_reports_multiple_directions(desktop_helpers,
                                               tmp_path: pathlib.Path):
    """Mix two real fibers (Yakima→Cle Elum) with two faked fibers
    pointing the opposite direction.  _inventory should expose the
    split via a ``direction_counts`` key in the result dict."""
    # Drop two real fibers
    for src in FIXTURE_JSONS[:2]:
        shutil.copy2(src, tmp_path / src.name)

    # Two "opposite direction" fakes: clone fixture JSON, swap
    # LocationDirection AB↔BA so direction_signature flips.
    for i, src in enumerate(FIXTURE_JSONS[2:4]):
        obj = json.loads(src.read_text())
        fi = obj.setdefault("FiberInformation", {})
        fi["LocationDirection"] = "AB" if fi.get("LocationDirection") == "BA" else "BA"
        # Avoid basename collisions
        (tmp_path / f"FAKE{i:03d}_1550 .json").write_text(json.dumps(obj))

    inv = desktop_helpers._inventory(str(tmp_path))
    assert "direction_counts" in inv, (
        "Inventory should surface a 'direction_counts' key when the "
        "folder contains files from multiple directions; current "
        f"inventory keys: {sorted(inv.keys())!r}."
    )


# ─────────────────────────────────────────────────────────────────────
#  10. XFAIL (L2) — _extract_zip cache invalidates on content change
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason="L2: _extract_zip is @st.cache_data keyed on (path, mtime). "
           "If a zip is overwritten with new content while mtime is "
           "preserved (rsync --times, tar -p, scripted refresh), the "
           "cache serves stale extracts.  Fix by keying on content "
           "hash or size+mtime.",
)
def test_extract_zip_cache_invalidates_on_content_change(
        desktop_helpers, tmp_path: pathlib.Path):
    """Build zip v1 → extract → overwrite with zip v2 (same path, same
    mtime) → re-extract should return v2's contents, not v1's."""
    zpath = tmp_path / "evolving.zip"

    # v1: just one fixture
    _make_zip_of_fixtures(zpath, n_files=1)
    mtime = zpath.stat().st_mtime

    out1 = desktop_helpers._extract_zip(str(zpath), mtime)
    listing1 = sorted(os.listdir(out1))

    # Overwrite with v2 (different content), preserve mtime.
    _make_zip_of_fixtures(zpath, n_files=3)
    os.utime(zpath, (mtime, mtime))

    out2 = desktop_helpers._extract_zip(str(zpath), mtime)
    listing2 = sorted(os.listdir(out2))

    assert listing1 != listing2, (
        "Cache returned stale extraction after the zip's contents were "
        "changed (mtime preserved).  Listings:\n"
        f"  v1: {listing1}\n  v2: {listing2}"
    )


# ─────────────────────────────────────────────────────────────────────
#  11. XFAIL (H2) — _stage_flat sub-dir collision loses true fiber id
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.xfail(
    strict=True,
    reason="H2: _stage_flat handles basename collisions by suffixing "
           "the second copy with '__1', '__2', etc.  But "
           "_extract_fiber_num then reads the suffix digits ('__2' → "
           "fnum=2) instead of the real fiber number embedded in the "
           "stem.  Fix by preserving the original basename via a "
           "content-hash subdir or by carrying fiber-id metadata across "
           "the rename.",
)
def test_stage_flat_subdir_collision_preserves_fiber_id(
        desktop_helpers, tmp_path: pathlib.Path):
    """Two REAL fibers (#1 and #2) live in sub-dirs that share a
    basename.  After _stage_flat, _extract_fiber_num should still
    return the original fiber numbers, not the rename-derived ones."""
    from unidirectional_event_finder import _extract_fiber_num

    # Build two sub-folders each with a file named "FIBER_1550 .json".
    src1 = FIXTURE_JSONS[0]   # YAKCLE001 → fiber 1
    src2 = FIXTURE_JSONS[1]   # YAKCLE002 → fiber 2

    a = tmp_path / "cableA"; a.mkdir()
    b = tmp_path / "cableB"; b.mkdir()
    # Use a basename that DOES still contain the wavelength suffix so
    # the original extractor would have a chance (i.e. the rename is
    # the only thing that should defeat it).
    name = "FIBER_1550 .json"
    shutil.copy2(src1, a / name)
    shutil.copy2(src2, b / name)

    staged = desktop_helpers._stage_flat([str(a / name), str(b / name)])
    try:
        files = sorted(os.listdir(staged))
        # _stage_flat keeps the first, renames the second with __1.
        assert len(files) == 2, files

        fnums = sorted(_extract_fiber_num(f) for f in files)
        # Desired behaviour: we recover {1, 2} from the original stems
        # via metadata or content hash, NOT from the rename suffix.
        assert fnums == [1, 2], (
            f"after _stage_flat, _extract_fiber_num returned {fnums} "
            f"for staged files {files} — the second file's true fiber "
            f"number was clobbered by the '__1' rename suffix."
        )
    finally:
        shutil.rmtree(staged, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────
#  12. PASS — _walk_files DOES skip ._* sidecars at top level
# ─────────────────────────────────────────────────────────────────────
def test_walk_files_skips_appledouble_at_top_level(tmp_path: pathlib.Path):
    """Pins the existing AppleDouble skip in engine._walk_files
    (separate from the desktop _inventory bug — see test #7)."""
    import unidirectional_event_finder as engine

    real = FIXTURE_JSONS[0]
    shutil.copy2(real, tmp_path / real.name)
    (tmp_path / f"._{real.name}").write_bytes(b"\x00\x05\x16\x07" + b"\x00" * 32)

    names = [n for _, n in engine._walk_files(str(tmp_path))]
    assert real.name in names, "real fiber was not yielded"
    assert not any(n.startswith("._") for n in names), (
        f"_walk_files yielded an AppleDouble sidecar: {names!r}"
    )


# ─────────────────────────────────────────────────────────────────────
#  13. PASS — _extract_fiber_num on AppleDouble basename returns None
#  (Re-pin via pytest, mirrors test_fiber_num_sweep.py case)
# ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "._YAKCLE001_1550 .json",
    "._STRROM0001_1550.sor",
    "._DURSAN001_1550 .json",
])
def test_extract_fiber_num_appledouble_returns_none(name: str):
    from unidirectional_event_finder import _extract_fiber_num
    assert _extract_fiber_num(name) is None, (
        f"AppleDouble sidecar {name!r} must produce fnum=None so the "
        "loader doesn't think it's a real fiber."
    )
