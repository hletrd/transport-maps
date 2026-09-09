> Archived 2026-09-10 (cycle 2). Every cycle-1 task in this plan is done; every
> unfinished cycle-2/3 task was carried into `plan/2026-09-10-c2-gates-and-tests.md`
> under its original ID (see `.context/reviews/_aggregate.md` for the cycle-2
> evidence). This file is kept for provenance and is not updated further.

# Plan: lint and test gates

Source findings: `_aggregate.md` section F (F1–F14) and E2's README test.
Per-agent detail: `test-engineer.md` (TE-*), `verifier.md` (VER-*),
`code-reviewer.md` (CR-6, CR-23), `critic.md` (CRIT-7, CRIT-25),
`feature-dev-code-reviewer.md` (FD-3).

Gates for this run: `uv run ruff check .` and `uv run pytest` (run with
`-k "not real_multi_band"` while the res-6 caches are being built; note the
exclusion in the cycle report).

CLAUDE.md testing rule: after adding a guard, mutate the code and confirm the
test goes red. Every task below names its mutation.

## Cycle 1 (this run)

- [x] **F14** Clear the 40 ruff errors (F401, F841, I001, RUF007, RUF012, UP031)
      without suppressions. Unused locals in `emit/hover.py:60`,
      `itinerary.py:58`, `modes.py:53,99` are removed, not renamed.
      Gate: `uv run ruff check .` exits 0.
- [x] **F1a** `tests/sources/test_landmask.py:14-16` — replace the res-5 bound
      with a bound derived from the resolution actually configured
      (`config.SOLVE_RES`): expect 500k–620k at res 5 and 3.5M–4.5M at res 6,
      or better, compare against the measured baseline stored beside the
      cache stamp. Mutation: flip `config.SOLVE_RES` in a monkeypatch and the
      bound must change.
- [x] **F1b** `tests/graph/test_build.py:61-65` — use `idx.cell_at(lat, lon)`
      instead of a hard-coded res-5 cell.
- [x] **F1c / E2** README attribution rows for GeoNames (CC BY 4.0) and
      HydroLAKES (CC BY 4.0) so `tests/emit/test_index.py::test_readme_documents_the_same_sources`
      is green for the right reason (the test already compares against
      `index.ATTRIBUTION`).
- [x] **F12** Remove the `… or True` from `tests/contour/test_bands.py:260` and
      make the assertion real (or delete the test if the property cannot be
      asserted on the fixture).
- [x] **F2** `tests/emit/test_hover.py` — fixtures at `config.SOLVE_RES` so the
      centre-child rule is exercised; assert the centre child's value is
      reported when it differs from the minimum. Mutation: replace
      `_representative_children` with min-over-children and the test must
      fail (the test-engineer's scratchpad mutation was green before).
- [x] **F13/TE-23** Register `real_multi_band` as a pytest marker, mark the
      test, and add it to `addopts` beside `network`, so a plain
      `uv run pytest` is the gate and no one has to remember `-k`.
- [x] **F13/TE-22** Add the missing `__init__.py` to `tests/cli/` and `tests/web/`
      (and `tests/` if needed for the rootdir import mode).
- [x] Run the full suite (`uv run pytest -q`) and record the outcome in the
      cycle report; every failure must be fixed at the root, not skipped.

## Cycle 2

- [ ] **W1 (gate warning, recorded per the warnings rule)** `uv run pytest` emits two
      `DeprecationWarning: This process is multi-threaded, use of fork() may lead
      to deadlocks in the child` from
      `tests/test_cli.py::test_a_gate_failure_in_a_forked_worker_aborts_the_run`
      (Python 3.14 `multiprocessing/popen_fork.py:70`). Severity Low, confidence
      High. Not fixed this cycle: the production build uses the `fork` context
      on purpose (`cli.py` shares the graph through inherited memory) and the
      test exercises that exact path. Exit criterion: `_build_all` moves to a
      `forkserver`/`spawn` context with the graph passed explicitly, or the
      test is marked with a `filterwarnings` limited to that one test with a
      comment quoting this entry.

- [ ] **F3** DMZ cut test: build the chain from `grid_disk` neighbours at
      `config.SOLVE_RES` so every consecutive pair is adjacent, and pick a
      Singapore/Johor pair that is adjacent at res 6; drop the `if` guard in
      the Schengen test (`tests/sources/test_countries.py:38-62,79`).
      Mutation: remove the border cut in `countries.py` → red.
- [ ] **F6** `tests/graph/test_refine.py:30-42` — use non-zero base values so
      zero-fill and carry-down differ. Mutation: zero-fill → red.
- [ ] **F4a** Mark the `build_index()`-backed modules `integration` and add the
      marker to `addopts` (`tests/graph/test_*.py`, `tests/test_golden.py`,
      `tests/sources/test_roads.py`, `tests/contour/test_bands.py`).
- [ ] **F4b** Redirect `config.CACHE` to `tmp_path` in `tests/sources/test_osm.py`,
      `test_countries.py`, `test_urban.py` (autouse fixture) so tests stop
      writing into the real `data/cache/`. Do not delete the existing
      droppings this cycle (orchestrator rule on `data/`); list them for the
      owner.
- [ ] **F8** Stub `osm.rail_routes`/`ferry_links` in `tests/test_cli.py`'s
      `_stub_pipeline`; add `test_index_subcommand_refuses_when_origin_files_are_missing`;
      a forked-path test with `_worker_count` forced to 2 that proves a
      worker failure aborts the run (pairs with build plan A3).
- [ ] **F9** A unit test for the deploy consistency gate (extract the inline
      Python from `scripts/deploy_verify.sh` into `scripts/check_dist.py`
      and test it on a temp `dist/`).

## Cycle 3+

- [ ] **F5** Node/JS-free test of the page's decoding: extract `cellIndex`,
      `legsTo`, legend tick placement and the mode-channel names into a small
      module the page imports, and test them with a Python port of the same
      arithmetic against fixture arrays (or a Node test if Node is available
      on the build host).
- [ ] **F7** Test `write_rail_detail` and a shared-ordering test that the five
      per-origin arrays are indexed by the same parent list; make the emitters
      call one `hover.hover_parents()` (TE-10).
- [ ] **F10** Unit tests for `_air_edges` border charge, `_access_edges`
      direction, `_transfer_edges` max(conn, typical) and "nothing departs
      here → no edge" (`build.py:88-213`).
- [ ] **F11** `tests/emit/test_modes.py` — pass a synthetic `cell_class` and pin
      the road-channel mapping.
- [ ] **F13** rest: TE-18 implied assertion and double graph build, TE-19
      Antarctica in golden threshold, TE-20 ramps parser count guard, TE-24
      tippecanoe skip + layer-name check, TE-26 44-second bound tests.
- [ ] **B3** Tighten the golden bounds (Seoul→Tokyo, Seoul→London) to the
      published shipped values ± a documented tolerance
      (`tests/test_golden.py:32-44`).

## Progress

- 2026-09-10 cycle 1: plan written; cycle-1 tasks implemented in the cycle-1 commits (`test(...)`, `style(...)`, `docs(readme)` entries in git log). Gate results recorded in the cycle report.
- 2026-09-10 cycle 1 gates: `uv run ruff check .` clean; `uv run pytest -q` 251 passed, 4 deselected (3 `network`, 1 `real_multi_band`), 16 min 42 s. The first full run found 7 res-5 fixtures the migration had left behind (`test_ground`, `test_golden` x3, `test_rail_integration` x2, `test_countries` SG/JB pair); fixed at the root in the `test(...)` commits that follow, not skipped.
- 2026-09-10 cycle 1 done: F14 (a3f918f), TE-23/TE-22 (00f40e4), F1a (990febe), F1b (6f63764), F1c/E2 (662f5d3), F12 (84fb110), F2 (498b971); ruff clean; full suite 251 passed, 4 deselected. Res-5 fixture fallout fixed at the root in 6cc60d4, ceebfc2, 3e393b5 (part of F3 landed early).
