# Plan (cycle 2): lint and test gates

Source findings: `.context/reviews/_aggregate.md` section P, K2, L4, L13, plus
every unfinished task carried from
`plan/archive/2026-09-10-c1-gates-and-tests.md` (F3, F4a, F4b, F6, F8, F9, W1;
cycle 3: F5, F7, F10, F11, F13 rest, B3). Per-agent detail: `test-engineer.md`
(TE-1…18 with the mutation table), `verifier.md` (gate results, VER-24, VER-27),
`critic.md` (CRIT-1, CRIT-3), `code-reviewer.md` (CR-3), `architect.md`
(ARCH-9, ARCH-11, ARCH-13), `document-specialist.md` (DOC-24).

Gates for this run: `uv run ruff check .` and `uv run pytest` (default
`addopts` deselects `network` and `real_multi_band`). CLAUDE.md testing rule:
after adding a guard, mutate the code and confirm the test goes red; every task
names its mutation.

Gate state at `bf9e5cc` (verifier): ruff **red** (2 errors), pytest 254 passed /
4 deselected / 1 warning in 26 min 30 s under the rebuild's load.

## Cycle 2 (this run)

- [x] **P1** Restore `for a, b in pairwise(st)` in `emit/rail_detail.py:55`
      (the import at :12 is then used); `uv run ruff check .` exits 0.
- [x] **P2 / F3** Build both DMZ chains with `h3.grid_path_cells(south, north)`
      and assert every consecutive pair is adjacent inside the fixture; replace
      the Schengen `if` with a fixture that resolves the FR cell by
      `countries.cell_country` (TE-1). Mutation: delete the `is_closed` block
      in `ground.hex_edges` → both DMZ tests red; `immigration_zone("CH") →
      "CH"` → Schengen red.
- [x] **P5 / F6** `split[2] = True; values = arange * 10 + 7`; assert seven
      children equal `values[2]` (TE-5). Mutation: zero-fill → red.
- [x] **P6 / F11** Pass a synthetic `cell_class` and pin `ROAD_CHANNEL`
      (class 1 → channel 2, class 0 → 5, class 4 → 4); rename the byte-count
      test to say `len(CHANNELS)` (TE-6). Mutation: swap two channels → red.
- [x] **P8 / F4b** `tests/conftest.py` with an autouse fixture redirecting
      `config.CACHE` to `tmp_path / "cache"` for every test not marked
      `integration`, seeded once per session with copies of the two Natural
      Earth archives (chmod 644) (TE-8). Check: `data/cache` file count is
      unchanged after a run of the fast subset. List the 475 existing droppings
      for the owner (not deleted this cycle — orchestrator rule on `data/`).
- [x] **P10 / F4a** Register `integration` (and `--strict-markers`); mark the
      `build_index()`-backed modules (`tests/graph/test_{build,ground,nodes}.py`,
      `tests/sources/test_{roads,landmask}.py`, `tests/test_golden.py`, the
      full-universe countries test). **Not** added to the default deselection:
      `uv run pytest` stays the whole gate; `-m "not integration"` is the fast
      loop (documented in README). Add `tests/__init__.py`; import
      `check_ramps` through a conftest fixture instead of `sys.path` (TE-11).
- [x] **P9 / F8** `_stub_pipeline` stubs `cli.osm.rail_routes` and `ferry_links`
      (`FileNotFoundError`); tests for `build-all --only` (build plan A7) and
      `_worker_cap` (TE-9). The `index`-subcommand refusal test becomes a
      `check_dist` test (L4).
- [x] **L4 / F9** `tests/web/test_check_dist.py` on a synthetic dist (build plan
      L4). Mutation: widen `.modes.bin`'s width → red.
- [x] **K2** The two bf9e5cc tests made real (build plan K1/K2).
- [x] **P4 (parity half)** `tests/web/test_app_constants.py`: regex-extract from
      `app.js` and assert `names == list(modes.CHANNELS)`, `NO_AIRPORT`,
      `NO_RAIL`, `UNREACHABLE_BAND`, `"source-layer": "bands" == tiles.LAYER`,
      the `airports.json` column order, and that every `meta.<key>` the page
      reads is written by `write_index` (TE-3, TE-15). Mutation: reorder
      `CHANNELS` → red. A Python port of the tick rule asserts the four tick
      edges the new formatter picks (60, 300, 1470, 4320); the on-screen gap
      rule is measured by `browser_verify.sh`.
- [x] **P11** A test that `app.js` sets `attributionControl: false`, constructs
      no `AttributionControl`, and that `web/vendor/maplibre-gl.js` contains the
      patched `Array.from(t.attributes)` loop (security plan Q3) (SEC-22).
      Mutation: revert the vendored token → red.
- [x] **L13** `tests/web/test_csp.py`: sha256 of the first inline `<script>` in
      `index.html` appears in `deploy/worldmap-security-headers.conf` (ARCH-9).
      Mutation: change one character of the snippet → red.
- [x] **P10 (small)** `REQUIRED_ATTRIBUTION` gains GeoNames and HydroLAKES
      (DOC-24); the README test also fails when `app.js`'s `PAGE_CREDITS`
      repeats an `ATTRIBUTION` name other than Nominatim (ARCH-11); the umask
      test sets `umask(0o022)` around itself (TE-12); the mtime fingerprint test
      bumps `st_mtime_ns` explicitly (TE-13); `test_tiles` skips when
      tippecanoe is absent and checks the layer name (TE-18).
- [x] **W1 (gate warning, recorded)** One `DeprecationWarning` class (fork of a
      multi-threaded process), raised five times at the end-of-cycle run by the
      two forked-pool tests in `tests/test_cli.py`:
      `test_a_gate_failure_in_a_forked_worker_aborts_the_run` (2) and
      `test_a_worker_killed_by_a_signal_aborts_the_run_instead_of_hanging` (3,
      added by 53cd8cf for K3). Severity Low, confidence High. Still not
      suppressed: the production build forks on purpose and both tests exercise
      that path; the alarm count per test is halved (TE-14) and the rise from
      one occurrence to five is the new K3 test, not a new defect. Exit
      criterion unchanged: `_build_all` moves to a `forkserver`/`spawn` context
      with the graph passed explicitly (S2 in the build plan), or the tests
      carry a `filterwarnings` limited to themselves quoting this entry.
      *2026-10-02, closed by the second criterion.* By now FOUR tests fork:
      the two above, `test_forked_workers_get_the_build_context_from_the_initializer_unpickled`
      (S2) and `tests/test_progress.py::test_forked_workers_report_each_origin_as_it_finishes`;
      9 warnings in a fast-subset run at `350eff3`. The threads are not ours:
      importing `transport_maps.cli` takes the process from 1 OS thread to 4
      (polars' and pyarrow's native pools start at import). Each of the four
      now carries `forks_a_threaded_process` (`tests/test_cli.py`), an
      `ignore` for that exact message and `DeprecationWarning` only; the
      comment there says why it is safe -- the children run the stubbed
      pipeline with polars/GDAL kept out, and each test's 15 s SIGALRM turns a
      deadlocked pool into a red TimeoutError, so the filter hides the advice,
      not the failure. `test_the_fork_warning_filter_matches_that_warning_and_no_other`
      forks a threaded process for real and checks the filter swallows that
      warning but not another DeprecationWarning nor the same text as a
      RuntimeWarning. Mutations, each red: the pattern reworded (no longer
      matches the real warning); the pattern widened to `.*`; the mark
      removed from the progress test (the warning is back in the summary); a
      second DeprecationWarning raised inside a marked test (still surfaces).
      Note: `-W error::DeprecationWarning` cannot be used to police this --
      CPython reports a fork warning that raises via `PyErr_WriteUnraisable`,
      so the escalated warning is swallowed and the test stays green.
      The production build still prints the warning; moving it off fork
      remains S2's business.
- [x] Run the full suite once at the end of the cycle and record the outcome.
      At `29c6330`, machine loaded by rebuild16: `uv run ruff check .` **All
      checks passed**; `uv run pytest -q` **356 passed, 4 deselected, 5
      warnings in 1298.81 s (21 min 38 s)**, exit 0. No failures, no errors,
      nothing suppressed; the five warnings are W1 above. Compare the plan's
      opening gate state at `bf9e5cc`: ruff red (2 errors), 254 passed.

## Cycle 3

- [x] **P3 / F7** (2026-10-02: three real res-4 cells, centre slower than a
      differently-routed sibling, cells listed in reverse; run through
      `cli._solve_one` and through each writer's defaults; `.over.bin` and
      `.r6.bin` checked against the same representative. Fastest-child in
      itinerary, modes, rail_detail and `representative_array`, reversed
      parents in modes, reversed `base_hover` -> each red.)
      `tests/emit/test_layout_contract.py`: one index at real
      resolutions, a predecessor chain through a sibling, all five files
      written; equal lengths, the hover value is the centre's, `.air.bin`
      decodes to the centre's arrival node, `.modes.bin` row equals the
      centre's accumulator, `.rail.bin` indexes a row naming the centre's
      station (TE-2). Lands with R3's `HoverGrid`. Mutation: fastest-child in
      each writer separately → red.
- [x] **P4 (node half) / F5** (2026-10-02: the `fmtTime`/`fmtDur`/`fmtTick`
      part, run in node by `tests/web/test_time_format.py` with the 59.5 and
      119.6 seams, four mutations red. `esc` already runs in node in
      `test_esc.py`, `legsTo` and `cellIndex` in `test_itinerary_grid.py` and
      `test_tier_disagreement.py`. Done as pytest-driven node, the
      pattern every other web test uses, not a separate `.mjs` suite.)
      `web/tests/app_pure.test.mjs` (`esc`, `fmtTime`
      boundaries incl. the 119.6 seam, `cellIndex`, `legsTo` round trip from a
      Python-written fixture) run by `tests/web/test_app_pure.py` with a visible
      skip when `node` is absent (TE-3).
- [x] **F10** Unit tests for `_air_edges` border charge, `_access_edges`
      direction, `_transfer_edges` `max(conn, wait)` and "nothing departs → no
      edge". (2026-10-02: `tests/graph/test_edge_builders.py`, real builders
      and calibration on seven stubbed airports; 13 mutations, each red.)
  - [x] TE-18 (2026-10-02): one `build_graph` per module, and the isolated
        airports asserted BY NAME against `validate.KNOWN_ISOLATED_AIRPORTS`
        (29 at res 6); dropping one name -> red.
  - [x] TE-19 (2026-10-02): the golden coverage test uses
        `validate.check_coverage`, as the gate does (99.5% gated, 96.9% raw).
- [x] **F13 rest** TE-18 c1 (implied assertion, double graph build), TE-19 c1
      (Antarctica in the golden threshold), TE-20 c1 (ramps parser count
      guard), TE-26 c1 (44-second bound tests); **S5** `native_edges` cache
      branch reachable by a `cache=` parameter (ARCH-13). (2026-10-02: all
      five parts done -- TE-18 and TE-19 are ticked under F10 above.)
  - [x] TE-26 (2026-10-02): the abort proof moved to
        `tests/graph/test_nodes_bounds.py`, `build_index` on a stubbed
        19-cell world (44 s -> <1 s, no data/ needed) plus a counted-drop
        case. Raise removed / `dropped` not reported -> each red.
  - [x] TE-20 (2026-10-02; the cycle-1 finding text is not in the tree, so
        this is reconstructed from the row and the code): `check_ramps.ramps()`
        now counts the declared keys a second, looser way and raises unless
        the strict parse read every one; `tests/web/test_ramps.py` holds the
        parse against node's own evaluation of `RAMPS` (keys, order, name,
        sea, grey, anchors) instead of the literal `== 12`, and measures the
        37 PAINTED bands, `painted()` checked colour-for-colour against
        `expandRamp` run in node. Asserted on the bands: lightness strictly
        decreasing after hex rounding and no two adjacent identical -- what
        the anchor rules guarantee; no ΔE floor is claimed. Measured minimum
        adjacent band ΔE: mono 1.61, warm 1.65, lavender 1.67, forest and sand
        1.69, muted 1.70, twilight 1.77, copper 1.78, rose 1.81, ice 1.83,
        ember 2.12, vivid 2.38 (anchors 6.5-8.9). Mutations, each red: one
        scheme with `grey` before `sea` (parser raises); that plus the looser
        count disabled (node parity red, every other ramp test green -- the
        old failure); anchors truncated to ten; `(n - 1)` -> `n` in `expand`
        and in `expandRamp`; `round` -> `int` in `oklab_to_srgb`; `painted()`
        returning the anchors; either `band_problems` check disabled.
  - [x] S5 (2026-10-02): `grid.native_edges(idx, cache=None|True|False)`;
        tests read back a doctored file and pin the size rule. Read branch
        off, `rows` key renamed, write skipped, always-cache -> each red.
- [x] **B3** Golden bounds tightened to the shipped values ± a documented
      tolerance once the 553-origin build ships. (2026-10-02: Seoul -> Tokyo
      314 min and -> London 904 min, ±15%, measured on the 1,464-origin graph;
      shifted expectations -> red.)
- [x] **K3 test**, **K4 test**, **G1 tests** — with their build-plan tasks if
      they do not land in cycle 2.
      (2026-10-02, verified; all three build-plan tasks are ticked in
      `2026-09-10-c2-build-robustness.md`. **K3** (`53cd8cf`):
      `tests/test_cli.py::test_a_worker_killed_by_a_signal_aborts_the_run_instead_of_hanging`.
      A worker SIGKILLs itself under a 15 s alarm (the plan said 30 s), and
      the run must raise `SystemExit` matching "died without reporting".
      **K4** (`53cd8cf`): `test_a_second_build_refuses_while_the_lock_is_held`,
      `test_a_stale_lock_is_reported_not_reused` and
      `test_the_lock_is_released_after_a_run` in `tests/test_cli.py`, plus
      `tests/web/test_check_dist.py::test_a_held_build_lock_is_refused`
      (`160bb34`). **G1** (`364986b`): the `STAMPED` table and
      `test_the_cache_path_moves_when_a_stamped_constant_moves`, the
      whole-cell-list urban key and the route-network cases in
      `tests/sources/test_cache_provenance.py`. Two parts were later
      replaced on purpose: a legacy `routes.parquet` is now ignored with a
      message rather than adopted (CR13-3), and `MIN/MAX_FERRY_KM` were taken
      out of the ferry key with the reason in `osm._ferry_cache_path`.
      `tests/sources/test_cache_provenance.py` and `tests/test_cli.py` ran
      108 passed on this date.)

## Progress

- 2026-09-10 cycle 2: plan written from the cycle-2 aggregate; carries every
  unfinished task from the cycle-1 gates plan (now archived) under its original
  ID. Vacuity audit at HEAD (test-engineer): 17 mutations run, 15 turned their
  target red, 4 tests shown vacuous (F3 eastern DMZ, F6, F11 mapping, the
  bf9e5cc "nearest" claim).
- 2026-09-10 cycle 2 done: P1 f0c3a4f; P2 7b95407 (is_closed mutant red on both DMZ tests; CH-out-of-zone red on Schengen); P5 69e6222 (zero-fill red); P6 52a1308 (swapped channels red); P8/P10 e7e159d (data/cache count unchanged across a run: 484 before and after); P9 35320bf; L4/F9 160bb34; K2 a30ef1b; P4 parity 1d382c8; P11 773eafe (unpatched loop red); L13 c4b7295 (one hash character red); P10 small f2341dc + c0c6cbf (PAGE_CREDITS parity, fork alarms halved). W1 stays recorded: one DeprecationWarning per gate run from the forked-pool tests, exit criterion unchanged.
- 2026-09-10 cycle 2 gates, final run at `29c6330` (both gates green): `uv run ruff check .` all checks passed; `uv run pytest -q` 356 passed, 4 deselected, 5 warnings, 21 min 38 s, exit 0. The suite grew from the 254 passing at `bf9e5cc` to 356 without a single red; the five warnings are the recorded W1 fork alarm, whose entry above now names both forked-pool tests instead of only the first.
