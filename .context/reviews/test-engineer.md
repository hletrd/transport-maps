# Test-engineer review — transport-maps

Reviewed at HEAD `ac191db` (`feat/transport-pipeline`), 2026-09-10. Read-only: no file in the
repository was modified; every experiment ran under the session scratchpad
(`/private/tmp/claude-501/-Users-hletrd-flash-shared-transport-maps/aacce825-…/scratchpad/mut/`).
Note: other agents committed three times while this review ran (the git-status snapshot at
start showed `fcb4d2a` with uncommitted `sources/*` edits; the suite below ran against the
files on disk at `ac191db`). Re-run the suite after any concurrent commit before acting on the
counts.

## Summary

**Suite result** (`uv run pytest -q -k "not real_multi_band" -rA -p no:cacheprovider`, 273.9 s):
**22 failed, 199 passed, 21 errors, 4 deselected** (3 `network`-marked + the single
`real_multi_band` test), 0 skipped, 0 pytest warnings. Exit 1. Log in the scratchpad
(`full_suite.log`).

Root causes of the red: (a) `src/transport_maps/graph/nodes.py` uses `np` without importing
numpy, so every `NodeIndex(...)` construction and every `build_index()` raises `NameError`
(41 of the 43 red tests); (b) `tests/sources/test_landmask.py::test_cell_count_matches_measured_baseline`
still asserts the resolution-5 count (500k–620k) against a res-6 universe of 4,091,715 cells;
(c) `tests/emit/test_index.py::test_readme_documents_the_same_sources` — README omits
GeoNames' licence and HydroLAKES entirely.

| Severity | Count | IDs |
|---|---|---|
| Critical | 2 | TE-1, TE-2 |
| High | 4 | TE-3, TE-4, TE-5, TE-6 |
| Medium | 11 | TE-7 … TE-17 |
| Low | 9 | TE-18 … TE-26 |

Mutation experiments (all via a pytest plugin loaded with `-p` from the scratchpad, so the repo
was untouched):

| Mutation | Target tests | Result |
|---|---|---|
| `hover._representative_children` → plain minimum over children (the behaviour hover.py says it replaced) | `tests/emit/test_hover.py` | **4 passed — vacuous** (TE-3) |
| `refine.expand` → zero-fill every child of a split cell | `tests/graph/test_refine.py` | **3 passed — vacuous** (TE-9) |
| `bands.band_of` → `bisect_right` (control) | `test_band_boundaries_are_inclusive_of_the_lower_band` | 1 failed — plugin mechanism works |
| `multiprocessing` fork-pool worker raising `SystemExit` (what `cli._solve_one` does on low coverage) | standalone probe, 8 s alarm | **`imap` never returned — HANG** (TE-2) |

Computed facts used below: the eastern DMZ chain in `test_countries.py` has 4 non-adjacent
consecutive pairs at `SOLVE_RES=6` (none at res 5); the Singapore/Johor fixture cells are
not neighbours at res 6; the Schengen fixture resolves to CHE/FRA (its `if` guard fires today);
`check_ramps.ramps()` parses 12 of 12 schemes; `data/origins.toml` has 553 origins while
`dist/index.json` and the live site have 157 and `scripts/browser_verify.sh` hard-codes 157.

## Coverage matrix

"Exercised" means a test asserts on that function's behaviour with a fixture that would
change the outcome; "imported/incidental" means it merely runs on the way to something else.
Real-data rows depend on `data/cache` + `data/build` (see TE-5).

| Production module | Meaningfully exercised by | Not exercised / weak |
|---|---|---|
| `cli.py` | `tests/test_cli.py` (serial `_build_all` sequencing, every collaborator stubbed), `tests/cli/test_entrypoint.py` (argparse only) | fork path (`workers > 1`, `_solve_one_forked`, `_CTX`, `pool.imap`), `_worker_count`, `_worker_cap`, `main()` `solve`/`index` subcommands, `_load_rail`/`_load_ferries` "included" branch (TE-2, TE-13) |
| `config.py` | `tests/test_config.py` | `FINE_RES > SOLVE_RES` never asserted |
| `validate.py` | `tests/test_validate.py` (coverage, Antarctica, `check_bands_cover` hole/missing-level/full, `check_monotonic_ground` accept/reject, connectivity incl. largest-component choice), `test_build.py` (gate on live graph) | `check_monotonic_ground` closed-border skip and zone-crossing branches (`country`/`zone` args) never hit; 2-cell fixtures with `stride=997` check only `pos 0` |
| `solve/dijkstra.py` | `tests/solve/test_dijkstra.py` | `with_predecessors=True`, `origin_node` ValueError |
| `graph/nodes.py` | `test_nodes.py` (real index), direct `NodeIndex(...)` in `test_ferry/_countries/_urban/_rail_integration` | **all red (TE-1)**; `cell_at` split-cell path, station accessors, dropped-station count |
| `graph/build.py` | `test_build.py` (duplicate guard, plausibility, unknown-pair bound, live-graph shape), `test_ferry.py` (`_ferry_edges`, thorough), `test_rail_integration.py` (`_rail_edges` ride/boarding — mis-wired, TE-1) | `_air_edges` border charge, `_access_edges`, `_transfer_edges` (`max(conn, wait)`, "no departures → no edge"), `_rail_edges` closed-border cut / zone crossing, `_border_rules` (TE-15) |
| `graph/ground.py` | `test_ground.py` (speed range, destination-speed rule), `test_countries.py` (border cut, crossing — TE-4), `test_urban.py` (factor) | fine↔base cross-edge dedup (`cross` set), `cell_class`/`urban_mask` via `refine.expand` on `base_cells` |
| `graph/air.py` | `test_air.py` (16 tests, thorough incl. knee) | — |
| `graph/rail.py` | `test_rail.py` (partition by route, platform merge, fastest wins, TGV plausibility) | `load_rail_calibration`/`load_ferry_calibration` only via real `build_graph` |
| `graph/refine.py` | `test_refine.py`, `test_native_grid.py`, `test_bands.py` split test | `expand` for children **vacuous (TE-9)** |
| `graph/transfers.py` | `test_transfers.py` (17) | pins dead duplicate constants (TE-21) |
| `contour/bands.py` | `test_bands.py` (13 + 1 deselected: `band_of`, LOD features, ordering, `max_minutes`, antimeridian, fringe, unreachable, split cell, random-junction cover) | `_coarse_features` ring growth only indirectly; `_polygonal` GeometryCollection path; "render grid does not match" ValueError; line 260 dead assertion (TE-17) |
| `contour/grid.py` | `test_grid.py` (rings, symmetry, cache keyed on cell list), `test_native_grid.py` | `native_edges` cache branch never taken (< `MIN_CELLS_TO_CACHE`) |
| `emit/hover.py` | `test_hover.py` | **centre-child rule vacuous (TE-3)**; endianness only via `10 in values` |
| `emit/index.py` | `test_index.py` (sorted ids, attribution records, README parity — red, TE-8) | `load_origins` duplicate-slug guard, `mode_detail`, `write_index` keys app.js reads (`solveRes`, `fineRes`, `hoverCellsUrl`, `modeDetail`) |
| `emit/itinerary.py` | `test_itinerary.py` (5, good chain logic) | ordinal arithmetic vs app.js `legsTo` (TE-6, TE-10) |
| `emit/modes.py` | `test_modes.py` (adjacency, rail accumulation, air excluded, byte size) | `ROAD_CHANNEL` mapping, clip/NaN, cross-resolution `_ground_adjacent`; real-GRIP4 dependency (TE-16) |
| `emit/rail_detail.py` | `test_rail_detail.py` (`last_station_per_node`, `_line_between`) | **`write_rail_detail` entirely (TE-10)** |
| `emit/routes_json.py` | `test_routes_json.py` (offsets, both sides, sentinel→null) | — |
| `emit/tiles.py` | `test_tiles.py` (magic bytes; needs tippecanoe) | layer name `bands` that app.js requires (TE-25) |
| `emit/airports_json.py`, `borders.py`, `places.py`, `water.py` | none | `places.build` parsing/ordering, `airports_json` field order consumed by app.js `a[0..5]` |
| `sources/_utils.py` | `test_cache_provenance.py` (`_params_hash`, `_atomic_write` mode) | `_retry_after_seconds` HTTP-date branch, `_validated_json` error/continue/batchcomplete branches |
| `sources/airports.py` | `test_airports.py` (real table), provenance stamps | filter rules on a synthetic CSV (offline) |
| `sources/countries.py` | `test_countries.py` (closed table, real resolution, blank-fill over universe) | **DMZ chain vacuous at res 6, SG/JB fixture not adjacent (TE-4)**; `_fill_blanks` nearest fallback on synthetic input |
| `sources/landmask.py` | `test_landmask.py` (real; cache-free islands), provenance | baseline red (TE-7); `_cells_touching` (new, unwired) has no equivalence test; `_antarctic_wedges`, `_without_lakes`, `_pole_cells` |
| `sources/osm.py` | `test_osm.py` (10, synthetic PBFs incl. antimeridian ferry) | cross-extract longest-sequence dedup; writes into repo cache (TE-12) |
| `sources/roads.py` | `test_roads.py` (real grid, antimeridian fallback, row/col), provenance | `road_class_grid` from synthetic rasters / threshold semantics |
| `sources/routes.py` | `test_routes.py` (10; parse, cargo, refuse-partial, absent-vs-unreturned) | `_wikipedia_titles`; 20k-floor and sanity-pair raise paths; bare `.exists()` cache (TE-11) |
| `sources/urban.py` | `test_urban.py` (real places) — red via TE-1 | cache key weakness (TE-11) |
| `sources/wikidata.py` | `test_wikidata.py` (4 offline) + 3 `network` (deselected) | redirect/normalize logic offline with a fake client |
| `calibrate/fit.py`, `calibrate/ground.py` | `test_fit.py`, `test_ground.py` (recover known coefficients, support guard, budget, key, empty route) | `drive_minutes` duration parsing |
| `scripts/check_ramps.py` | `tests/web/test_ramps.py` | `respace`, `oklab_to_srgb` round-trip; parser count guard (TE-20) |
| `scripts/deploy_verify.sh`, `browser_verify.sh` | none (post-deploy only) | consistency gate untested and partial (TE-14); hard-coded 157/37/12 (TE-6) |
| `scripts/build_water_tiles.py`, `calibrate_ground.py`, `ground_check.py`, `expand_origins.py`, `adsb_extract.py`, `osm_rail.sh` | none | pure helpers `expand_origins.slugify/km`, `adsb_extract.legs_from_trace` are testable offline |
| `web/app.js`, `web/index.html` | `test_ramps.py` (RAMPS block only); `browser_verify.sh` post-deploy | all data decoding (TE-6) |

## Findings

### TE-1 — `graph/nodes.py` uses numpy without importing it; 43 tests red, and two positional constructors outlived the dataclass change
- **Severity:** Critical  **Confidence:** High  **Status:** Confirmed (suite log; on-disk grep at `ac191db`: `grep -c '^import numpy' nodes.py` → 0)
- **Where:** `src/transport_maps/graph/nodes.py:61-62` (`field(default_factory=lambda: np.zeros(...))`), `:124` (`np.flatnonzero(split)`), `:184-187` (`return NodeIndex(cells, codes, cell_pos, airport_pos, airport_cell, tuple(dropped), tuple(station_keys), station_pos, station_cell, base_cells=base_cells, ...)`); `tests/graph/test_rail_integration.py:35-36` (`NodeIndex(cells, [], cell_pos, {}, {}, (), tuple(keys), station_pos, station_cell)`).
- **Why:** Python 3.14 defers annotation evaluation, so the class body imports fine and the `NameError` only fires when a default factory runs (`NodeIndex(...)` with defaults — every fixture in `test_ferry`, `test_countries`, `test_urban`, `test_rail_integration`) or when `build_index` reaches line 124 (every module-scoped `idx` fixture: `test_build`, `test_ground`, `test_nodes`, `test_roads`, `test_golden`, `test_landmask` via `cells`). Log: `src/transport_maps/graph/nodes.py:124: NameError: name 'np' is not defined`, and `:62`. Two further defects are masked behind it: (i) `build_index` passes nine positionals, so `station_pos` / `station_cell` land in `base_cells` / `base_index` and the `base_cells=` keyword then raises `TypeError: multiple values for argument 'base_cells'`; (ii) `test_rail_integration._index` does the same, so `_station_pos` stays empty and `idx.station_cell_index(...)` raises `KeyError` — a stub that outlived a signature change, the exact case CLAUDE.md names. `test_the_dropped_airport_bound_actually_aborts` also fails for the wrong reason (`pytest.raises(RuntimeError)` sees `NameError`).
- **Failure scenario:** `transport-maps build-all` cannot construct a `NodeIndex` at all; the suite's red is the only thing that says so, and it was committed anyway.
- **Suggested tests:** `tests/graph/test_nodes.py::test_node_index_constructs_with_stations_by_keyword` — arrange a two-cell index with `stations=("s",)`, `_station_pos={"s": 2}`, `_station_cell={"s": 0}` passed **by keyword**; assert `idx.n == 3`, `station_index("s") == 2`, `station_cell_index("s") == 0`, `len(idx.fine) == 0`. And `test_build_index_is_cheap_to_unit_test`: monkeypatch `landmask.land_cells`, `roads.cell_class`, `urban.urban_mask`, `airports.scheduled_airports` to a 7-cell/1-airport fixture and a 2-stop `rail_routes` frame; assert the returned index round-trips `station_index`/`airport_arr_index`/`cell_at` on a split cell. Mutation that must go red: reorder any dataclass field, or drop the numpy import. Also switch every positional `NodeIndex(...)` in tests to keywords.

### TE-2 — The forked build path is untested, and the coverage gate's `SystemExit` hangs it forever
- **Severity:** Critical  **Confidence:** High  **Status:** Confirmed (scratchpad probe: worker printed the exit message, `imap` never returned within the 8 s alarm)
- **Where:** `src/transport_maps/cli.py:83-87` (`raise SystemExit(...)` inside `_solve_one`), `:109-112` (`_solve_one_forked`), `:182-191` (`ctx.Pool(workers)` / `pool.imap`), `:64-65` (`if n_origins < 4: return 1` — "the test stubs record their writes into a list that a forked child cannot append to"); `tests/test_cli.py:107-125`.
- **Why:** `multiprocessing.pool.worker` catches `Exception`, not `BaseException`; a `SystemExit` kills the worker process, the pool respawns a worker, and the job result is never delivered, so `pool.imap` blocks indefinitely (classic bpo-22393 behaviour). `test_index_json_is_not_written_when_an_origin_aborts_partway` asserts `SystemExit` — but only on the serial path, because `_worker_count` was written to return 1 for the two-origin fixture. Every real build (157 or 553 origins on a multi-core machine) takes the fork path, where the same gate becomes a silent hang instead of an abort. The `ValueError`s from `check_monotonic_ground`/`check_bands_cover` propagate correctly; only the coverage gate has this shape.
- **Failure scenario:** One origin drops below `MIN_COVERAGE` in an overnight 553-origin build; the parent prints the finished rows, then sits at 0 % CPU forever (compare the 37-minute polars stall in the file header) with no error and no index.json.
- **Suggested test:** `tests/test_cli.py::test_a_failing_origin_aborts_the_forked_build` — reuse `_stub_pipeline` with **four** origins (`coverages=[1.0, 0.0, 1.0, 1.0]`), monkeypatch `cli._worker_count` to `lambda n: 2`, run `cli._build_all()` inside `pytest.raises((SystemExit, RuntimeError))` under a hard deadline (`signal.alarm(20)` on POSIX, or run in a thread and `join(20)` then assert it finished); assert `not (tmp_path / "index.json").exists()`. Use the on-disk files written by `_fake_write` as the evidence, not the `written` list (it cannot cross the fork). Today this test hangs until the deadline → red; it goes green once the worker raises a plain `Exception` (or `_solve_one_forked` converts `SystemExit`). Companion: `test_forked_workers_solve_every_origin` — four passing origins, `_worker_count → 2`, assert 28 files exist and index.json lists all four.

### TE-3 — `tests/emit/test_hover.py` is vacuous for the centre-child rule the module exists to enforce
- **Severity:** High  **Confidence:** High  **Status:** Confirmed by mutation (min-over-children → 4 passed)
- **Where:** `tests/emit/test_hover.py:9-12` (res-5 fixture cells `8530e08ffffffff`, `8530e087fffffff`, `85754e63fffffff`), `:23-27` (`test_parent_cell_takes_the_minimum_of_its_children`, asserts `10 in values`); `src/transport_maps/emit/hover.py:48-54`.
- **Why:** `_representative_children` looks for `h3.cell_to_center_child(parent, SOLVE_RES=6)` and then `FINE_RES=7`; the fixture holds res-5 cells, so `cell_pos.get(centre)` is always `None` and the code always takes the `best_pos` (minimum) fallback. The test's name and assertion encode the *old* semantics that hover.py's docstring calls a bug ("read South Korean times ten kilometres inside the North"). Reverting the module to a pure minimum leaves all four tests green. `test_writes_uint16_little_endian` additionally asserts `raw.dtype.itemsize == 2` on a dtype the test itself chose.
- **Failure scenario:** Someone "simplifies" `_representative_children` back to the minimum, or breaks the centre-child lookup (`SOLVE_RES` vs `FINE_RES` order, wrong parent); the readout silently borrows the fastest child across a border again and the suite stays green.
- **Suggested test:** `test_the_readout_reports_the_centre_child_not_the_fastest`: arrange `parent = h3.latlng_to_cell(37.5, 127.0, HOVER_RES)`, `centre = h3.cell_to_center_child(parent, SOLVE_RES)`, `sibling = next(c for c in h3.cell_to_children(parent, SOLVE_RES) if c != centre)`; `Idx.cells = [centre, sibling]`, `minutes = [50.0, 10.0]`; act `write_hover`; assert the single value is **50**. Companion `test_a_water_centre_falls_back_to_the_fastest_child`: cells `[sibling]` only, minutes `[10.0]` → value 10. Mutation that must go red: replace the picked position with `best_pos[p]` unconditionally (the plugin in the scratchpad does exactly this). Same fixture should be reused by `test_itinerary`/`test_modes` so the "same child as the hover time" promise in their docstrings is actually checked.

### TE-4 — DMZ ground-cut test is vacuous at `SOLVE_RES=6`; Singapore/Johor fixture is no longer adjacent
- **Severity:** High  **Confidence:** High  **Status:** Confirmed by computation (currently masked by TE-1)
- **Where:** `tests/sources/test_countries.py:38-40` (`np.arange(37.6, 39.2, 0.05)` at `config.SOLVE_RES`), `:46-51`; `:60-62` (`assert jb in h3.grid_disk(sg, 1)`).
- **Why:** A 0.05° latitude step (≈5.56 km) equals the centre-to-centre spacing of adjacent res-6 hexes, so the sampled chain skips cells: at res 6 the eastern chain has **4 consecutive pairs at grid distance 2** (indices 2, 14, 15, 26); at res 5 it had none. `ground.hex_edges` only joins neighbours, so `north` is unreachable from `south` **whether or not the border cut exists** — `assert not np.isfinite(...)` passes for the wrong reason. Mutation: delete the `countries.is_closed` check in `hex_edges.add` — this test stays green (the western chain, 0.04° step, is still contiguous and would catch it, which is the only reason the cut is protected at all). Separately, `sg`/`jb` (1.44,103.78)/(1.49,103.74) are distinct non-adjacent res-6 cells, so `test_a_land_border_between_immigration_zones_costs_a_crossing` fails on its own fixture assertion once TE-1 is fixed.
- **Failure scenario:** The eastern DMZ cut regresses (e.g. a `CLOSED_BORDERS` edit or a `_fill_blanks` change reintroducing a blank Han-estuary cell) and only the western test can notice.
- **Suggested tests:** build the chain with `h3.grid_path_cells(south_cell, north_cell)` (guaranteed contiguous) and add `assert all(h3.are_neighbor_cells(a, b) for a, b in itertools.pairwise(cells))` as a fixture self-check in both DMZ tests; for SG/JB pick `jb = next(c for c in h3.grid_ring(sg, 1) if countries.cell_country([c])[0] == "MYS")`. Mutation that must go red: remove the `is_closed` guard in `ground.hex_edges` (east and west tests both red), and remove the `crossing_min` addition (SG test red).

### TE-5 — Most of the "unit" suite is unmarked integration: real caches, cold-checkout downloads, 4.4 of the 4.6 minutes
- **Severity:** High  **Confidence:** High  **Status:** Confirmed (durations: six `build_index` setups at 42–47 s each; `pyproject.toml` `addopts = "-m 'not network'"` covers only the 3 wikidata tests)
- **Where:** module-scoped `nodes.build_index()` fixtures in `tests/graph/test_build.py:7-9`, `test_ground.py:7-9`, `test_nodes.py:6-8`, `tests/sources/test_roads.py:14-16`, `tests/test_golden.py:20-25`; `tests/sources/test_landmask.py:9-11`, `test_airports.py:6-8`, `test_countries.py:93-97`, `test_urban.py`, `tests/emit/test_modes.py` (via `roads.cell_class`), `tests/test_licence_firewall.py:39-40` (`dist/`).
- **Why:** These reach `landmask.land_cells(6)` (millions of cells; `_download` of three Natural Earth zips), `roads.road_class_grid()` (five GRIP4 zips), `airports.scheduled_airports()` (OurAirports CSV), `countries._polygons()`, `osm.rail_routes()` (`test_cli.py`, TE-13). On a checkout without `data/cache` + `data/build` they download and compute for a long time — with the default `-m 'not network'` promising otherwise. Marker is by name only; nothing stops a new test from adding another 45 s setup. Also `test_the_dropped_airport_bound_actually_aborts` spends 44 s of real `build_index` to test a two-airport bound.
- **Failure scenario:** CI or a fresh clone runs `uv run pytest`: dozens of tests error on missing data or hang on downloads; developers learn to ignore red, which is how TE-1 got committed.
- **Suggested change:** register `integration` (or `data`) in `[tool.pytest.ini_options].markers`, mark the modules above (`pytestmark = pytest.mark.integration`), and extend `addopts` to `-m 'not network and not integration'`; add a session-scoped autouse fixture that fails fast with a clear message when `data/build` is absent and the marker is selected. Convert the bound tests to stubbed fixtures (`landmask.land_cells` → 7 cells) so they run in milliseconds. Mutation that must go red for the fast versions: raise `MAX_DROPPED_AIRPORT_FRACTION` to 1.0.

### TE-6 — The web page's data decoding has no automated test; the post-deploy script hard-codes numbers that already drifted
- **Severity:** High  **Confidence:** High  **Status:** Confirmed (553 origins in `data/origins.toml`; 157 in `dist/index.json`; `browser_verify.sh:19` requires `"cities":157`)
- **Where:** `web/app.js:133-143` (legend ticks at `(i+1)/BANDS.length`, nearest-hour dedup), `:453-462` (`cellIndex`: `BigInt("0x"+h3id)` binary search over `hover_cells.bin`), `:473-489` (`legsTo`: `airports + count + ordinal` mirrors `itinerary.py:68`), `:520-522` (`names` hard-coded copy of `modes.CHANNELS`, `hoverModes[i*n+k]`), `:444-451` (`fmtTime` 48 h boundary), `:578-595` (`bandRangeAt`), `:911-925` (scheme switch), `:728-770` (search ordering rule for 3-letter codes), `:707-714` (`originNear` 80 km); `scripts/browser_verify.sh:18-19,41`.
- **Why:** CLAUDE.md records two blank deploys caused by mismatched assets; the only check is a manual/browser script that runs *after* rsync to production. Nothing ties `app.js` constants to their Python producers: `names` vs `modes.CHANNELS`, `NO_AIRPORT`/`NO_RAIL` vs `itinerary.NO_AIRPORT`/`rail_detail.NO_RAIL`, `UNREACHABLE`, the `airports.json` column order (`a[0..5]`), the PMTiles layer name `bands`. The legend rule CLAUDE.md calls out ("ticks sit at their true band boundaries") is unverified. `browser_verify.sh` will fail the next full deploy on `"cities":157` alone.
- **Failure scenario:** `modes.CHANNELS` gains a seventh channel; `deploy_verify.sh` (width 12) and `app.js` (`n = 6`) disagree; every surface breakdown reads the wrong cell and no gate notices.
- **Suggested tests:** (1) `tests/web/test_app_constants.py` — parse `web/app.js` with the same regex approach `check_ramps.ramps()` uses and assert `names == list(modes.CHANNELS)`, `NO_AIRPORT == itinerary.NO_AIRPORT`, `NO_RAIL == rail_detail.NO_RAIL`, `UNREACHABLE_BAND == bands.UNREACHABLE_BAND`, `source-layer: "bands" == tiles.LAYER`; mutation: change any one constant. (2) A Python re-implementation check of the tick rule: for `config.BAND_EDGES_MIN`, ticks land at `(i+1)/37` for edges 60, 125, 225, 465, 955, 1470, 3020, 4320 — assert against a table so an evenly-spaced regression goes red. (3) If Node is available, `node --test` on the pure functions (`expandRamp`, `fmtTime`, `cellIndex`, `legsTo`) extracted into an ES module; (4) make `browser_verify.sh` derive `cities`/`tints`/`schemes` from `dist/index.json` and the parsed RAMPS count instead of literals.

### TE-7 — Resolution-5 assumptions left behind in tests after `SOLVE_RES` became 6
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (landmask baseline red: `assert 4091715 < 620000`)
- **Where:** `tests/sources/test_landmask.py:14-16`; `tests/emit/test_hover.py:11` (TE-3); `tests/sources/test_countries.py:38,60` (TE-4); `tests/contour/test_bands.py:144,175,213-214` and `tests/contour/test_grid.py:8,19,37-38` (literal `5`; still valid because bands/grid are resolution-agnostic, but they no longer test the shipped resolution); comments citing "548,557 cells"/"res-5" throughout (`validate.py:2-8`, `roads.py`, `hover.py`, `config.py:11`).
- **Why:** The "measured baseline" is a res-5 number asserted against `land_cells(config.SOLVE_RES)`; the test cannot pass at 6. A test that hard-codes a resolution different from the config tests a universe the build never uses.
- **Suggested test:** keep a per-resolution table `{5: (500_000, 620_000), 6: (3_800_000, 4_400_000)}` keyed on `config.SOLVE_RES` and fail loudly for an unknown resolution; replace literal `5` in bands/grid fixtures with `config.SOLVE_RES`. Mutation that must go red: set `SOLVE_RES = 5` with the res-6 cache present (the table lookup mismatches the count).

### TE-8 — README attribution drifted from `index.ATTRIBUTION`; shipped `dist/index.json` is behind both
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (`AssertionError: README.md omits GeoNames's licence`; `grep HydroLAKES README.md` → none; `dist/index.json` has 7 attribution entries vs 9 in code)
- **Where:** `src/transport_maps/emit/index.py:59-70` (GeoNames CC BY 4.0, HydroLAKES CC BY 4.0), `README.md:48-56` (table lacks both), `tests/emit/test_index.py:76-83`.
- **Why:** The test does its job — this is a real CC-BY obligation gap — but note the ordering: the loop stops at the first missing licence, so HydroLAKES' absence is hidden until GeoNames is fixed. `deploy_verify.sh:31` prints the attribution list but compares it with nothing.
- **Suggested test:** collect all missing entries and assert the list is empty (one failure names every gap). Add to `deploy_verify.sh`'s Python block: `assert {a["name"] for a in idx["attribution"]} == {a["name"] for a in index.ATTRIBUTION}` so a stale dist cannot deploy. Mutation: delete an ATTRIBUTION entry from the dist file → red.

### TE-9 — `test_base_values_carry_down_to_children` cannot tell carry-down from zero-fill
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by mutation (zero-fill children → 3 passed)
- **Where:** `tests/graph/test_refine.py:30-42` (`split[0] = True`, `values = np.arange(len(base)) * 10`, `assert (out[fine] == 0).all()`).
- **Why:** The split cell is index 0 whose value is 0, so children carrying the parent value and children being zeroed are indistinguishable. Only the unsplit mapping (`out[0] == values[base_index[0]]`) is real.
- **Suggested test:** `split[2] = True`; assert `(out[fine] == values[2]).all()` and `out[fine].size == 7`. Mutation that must go red: the scratchpad plugin (`out[dup] = 0`).

### TE-10 — Emit binary layouts: `write_rail_detail` untested; no test that the five per-origin arrays share one ordering
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by reading
- **Where:** `src/transport_maps/emit/rail_detail.py:60-93` (no test calls `write_rail_detail`); `emit/itinerary.py:57-58`, `emit/modes.py:98-99`, `emit/rail_detail.py:65` each recompute `parents = sorted({cell_to_parent(...)})` instead of calling `hover.hover_cells`; `scripts/deploy_verify.sh:18` is the only place the lengths are compared, after the build.
- **Why:** CLAUDE.md's "never deploy a partial dist" rule exists because a mismatched ordering renders a blank globe with no error; the contract is enforced only at deploy time. `write_rail_detail` contains the table dedup, the `came_from` line lookup, the `NO_RAIL` clamp and the JSON schema the page reads — none asserted. `test_written_array_is_one_uint16_per_hover_cell` and `test_written_file_is_three_uint16_per_hover_cell` (whose name says three; `CHANNELS` has six) check byte counts only.
- **Suggested tests:** `tests/emit/test_layout_contract.py`: one small index at real resolutions (centre child + sibling, one airport, two stations, a predecessor chain through both), write all five files, assert `len(hover) == len(air) == len(modes)//6 == len(rail) == len(hover_cells.bin)//8`, and that the parent's ordinal decodes back to the expected airport (`ordinal + n_cells + n_airports` is the arrival node) and station table row. Mutations that must go red: `astype("<u4")` in any writer; `node - first_arrival + 1`; using `best_pos` in one writer only.

### TE-11 — Cache-provenance rule not applied to `urban_mask`, `route_network`, `ferry_links` (and untested there)
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by reading
- **Where:** `src/transport_maps/sources/urban.py:51-52` (key = `URBAN_POP_MIN, URBAN_RADIUS_KM, len(cells), cells[0], cells[-1]` — not the cell list, not `PLACES_ZIP`; contrast `countries.py:93-96` "Hash every cell, not just the count and the ends"); `sources/routes.py:242-244` (bare `routes.parquet .exists()`, no stamp of `_SANITY_PAIRS`, the 20,000 floor or the airport-table stamp); `sources/osm.py:151-155` (`ferry_links` fingerprint omits `ANTIMERIDIAN_EPS_DEG`/`FERRY_SCHEMA` while `rail_routes:182` includes its constants); `tests/sources/test_cache_provenance.py` covers only roads/airports/landmask.
- **Why:** CLAUDE.md: "Derived caches key on `_params_hash` of the constants and inputs that govern them, never on a bare `.exists()`." Two universes with equal length and end cells share an urban mask; a change to the ferry antimeridian rule reads the stale parquet.
- **Suggested tests:** mirror the existing pattern — `test_urban_mask_path_moves_when_the_cell_list_changes_inside` (same length/ends, different middle) and `..._when_places_zip_moves`; `test_ferry_links_path_moves_when_the_antimeridian_eps_moves`; `test_route_network_path_carries_a_hash`. Mutations: revert the key → red.

### TE-12 — Tests write into the repository's `data/cache`
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (`ls data/cache`: 294 `rail_routes-*.parquet`, 18 `ferry_links-*.parquet`, 31 `cell_country-*.parquet`)
- **Where:** `tests/sources/test_osm.py` (every test: `osm.rail_routes(extracts_dir=tmp_path)` caches under real `config.CACHE`, fingerprint includes `str(tmp_path)` + mtime so a new file per run), `tests/sources/test_countries.py`, `tests/sources/test_urban.py`, `tests/emit/test_modes.py` (via `cell_country`/`urban_mask`/road grid); no root `conftest.py` exists.
- **Why:** Droppings accumulate forever on an NFS mount; they also make provenance reasoning harder (which parquet is the real one?). `test_replacing_an_extract_of_the_same_name_is_a_cache_miss` relies on `st_mtime_ns` differing between two same-size writes — fine on APFS/ext4 (`tmp_path` is local), flaky on a 1 s-granularity filesystem.
- **Suggested change:** `tests/conftest.py` with an autouse fixture that points `config.CACHE`/`config.BUILD` at `tmp_path` for modules not marked `integration`; for the mtime test, `os.utime` the replaced file to `+1 s` explicitly so the miss is by construction.

### TE-13 — `tests/test_cli.py` reads the real OSM extracts; `solve`/`index` subcommands untested
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by reading (`data/cache/osm/` holds seven `*-rail.osm.pbf`; the parquet was warm so it did not show in durations)
- **Where:** `tests/test_cli.py:27-104` (`_stub_pipeline` never stubs `cli.osm.rail_routes`/`ferry_links`; only test 4 at `:178-181` does), `src/transport_maps/cli.py:233-263`.
- **Why:** Three "pure sequencing" tests depend on the machine's OSM cache; on a cold cache they parse ~300 MB of PBF. The `solve` subcommand writes `{name}.hover.bin`/`{name}.routes.json` at `dist/` root — a layout the page cannot load — and the `index` subcommand rewrites `index.json` from `origins.toml` regardless of which per-origin files exist (the very hazard `_build_all` guards against). Neither has a test.
- **Suggested tests:** stub `osm.rail_routes`/`ferry_links` in `_stub_pipeline` (raise `FileNotFoundError`); `test_index_subcommand_refuses_when_origin_files_are_missing` (arrange an empty dist, run `main()` with `sys.argv = [.., "index"]`, expect `SystemExit`) — red today; `test_solve_writes_the_same_layout_build_all_does`. Mutation: rename an output → red.

### TE-14 — The deploy consistency gate is untested and misses the drift that just happened
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by reading
- **Where:** `scripts/deploy_verify.sh:9-37` (inline Python), `:40-41` (rsync happens right after).
- **Why:** The gate compares per-origin array lengths to `hover_cells.bin` but does not check that `index.json` origins match `data/origins.toml` (157 vs 553 today — a stale dist deploys "consistently"), that `.rail.json` accompanies `.rail.bin`, that `water.pmtiles` is non-empty, or that `app.js` constants match (TE-6). None of it has a unit test; a typo in the widths tuple would pass silently.
- **Suggested change:** move the block to `transport_maps/deploy_check.py` (`check_dist(dist: Path, origins: list[dict]) -> list[str]`) called by the script, with tests on a synthetic dist tree: truncate one `.bin` by 2 bytes → error; drop `.rail.json` with `.rail.bin` present → error; index.json missing an origin from `origins.toml` → error. Mutations: change a width → red.

### TE-15 — Graph edge builders other than ferry are untested at the unit level
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by reading
- **Where:** `src/transport_maps/graph/build.py:88-93` (`_air_edges` border charge with `max(size1, size2, key=_SIZE_RANK.get)`), `:136-160` (`_access_edges` direction), `:163-213` (`_transfer_edges`: `max(conn, typical)`, "nothing departs here → no edge"), `:251-263` (`_rail_edges` closed-border cut and zone crossing), `:216-230` (`_border_rules`).
- **Why:** `test_ferry.py` pins every rule for ferries (cut, crossing, dedup) but the identical rules in `_rail_edges` — added in the same commit `9fc4dd1` — have no test; `_transfer_edges` is the only place a connection is charged and its `max` rule is asserted nowhere. Real-graph tests cannot see a swapped `_SIZE_RANK` or a `min` for `max`.
- **Suggested tests:** with the `test_rail_integration._index` fixture (fixed per TE-1) add a Seoul→Kaesong two-stop route → `_rail_edges` emits no ride; SG→JB stations → ride minutes include `_land_border_min()`. For `_transfer_edges`, monkeypatch `routes.route_network` to a 3-pair frame and `airports.scheduled_airports` to sizes; assert the edge equals `max(connection_min, median wait)` and that an airport with no outbound pair has no arr→dep edge. Mutations: `max`→`min`; drop `is_closed` in `_rail_edges`.

### TE-16 — `tests/emit/test_modes.py` depends on the real GRIP4 grid and never pins the road-channel mapping
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by reading
- **Where:** `tests/emit/test_modes.py:34,47,59,69` (`cell_class=None` → `roads.cell_class(idx.cells)` → `road_class_grid()`), `:36` (`acc[1][2:].sum() == 30.0`); `src/transport_maps/emit/modes.py:26` (`ROAD_CHANNEL`).
- **Why:** An emit unit test silently loads a 9 MB raster-derived grid (or downloads five zips), and summing channels 2..5 hides which channel received the minutes — mutation `ROAD_CHANNEL = {…, 1: 4, …}` stays green.
- **Suggested test:** pass `cell_class=np.array([1, 1, 0])` explicitly and assert `acc[1][2] == 30.0` (highway) and the rest zero; a second case with class 0 → channel 5 ("track"). Mutation: any `ROAD_CHANNEL` swap → red.

### TE-17 — Dead assertion `… or True` in the split-cell band test
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by reading
- **Where:** `tests/contour/test_bands.py:260` (`assert by_band[5].contains(Point(lo, la)) and not by_band[0].contains(Point(lo, la)) or True`).
- **Why:** Operator precedence makes the whole assertion `True`; the intended property (the parent hexagon is *not* claimed by the fast band outside its fast child) is unverified. It reads like an assertion that failed and was silenced — probably because `kids[0]` may be the centre child, in which case the parent centroid legitimately lies in band 0.
- **Suggested test:** pick a point inside a *slow* sibling child (`h3.cell_to_latlng(cells[kids[1]])`) and assert it is in `by_band[5]` and not in `by_band[0]`; delete the `or True`. Mutation that must go red: paint the parent in the *fastest* child's band (`np.minimum.at` instead of `np.maximum.at` at `bands.py:243`).

### TE-18 — Real-graph connectivity assertion is implied by the call; graph built twice per module
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed by reading
- **Where:** `tests/graph/test_build.py:128-137` (`assert 0 <= len(isolated) <= limit` after a call that already raises above `limit`), `:12-16` and `:102-106` (two module-scoped `build_graph` calls, ~40 s each).
- **Suggested change:** assert the *named* permanent isolates (`set(isolated) <= {"AGJ","AJN",…}` from `validate.py:14-15`) so a new orphan is visible; collect `rejected` and `unknown` in the one `build_graph` call.

### TE-19 — `test_golden.py` reachability threshold counts Antarctica; production gate does not
- **Severity:** Low  **Confidence:** Medium  **Status:** Likely
- **Where:** `tests/test_golden.py:47-50` (`np.isfinite(minutes[:n_cells]).mean() > 0.90`) vs `validate.check_coverage` allowlist (`validate.py:33-39`, "would drag a perfect build to about 92 %").
- **Suggested change:** use `validate.check_coverage(minutes, idx) > validate.MIN_COVERAGE` so the golden test measures what the build gates on.

### TE-20 — `test_ramps.py` count guard and regex parser can silently skip a scheme; interpolation unmeasured
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (12 of 12 parsed today)
- **Where:** `tests/web/test_ramps.py:10-11` (`>= 6`), `scripts/check_ramps.py:40` (single-line `name, sea, c` order regex); `web/app.js:90-97` (`expandRamp` to 37 bands never measured).
- **Suggested test:** assert `len(check_ramps.ramps()) == number of top-level keys in the RAMPS block` (count `^\s+(\w+):\s*\{`); port `expandRamp` to Python in the test and assert the 37 interpolated bands are strictly decreasing in OKLab L for every scheme. Mutation: add a ramp with keys reordered → red.

### TE-21 — `test_station_constants_exist_for_task_9` pins dead, duplicated constants
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `src/transport_maps/graph/transfers.py:8-9` and `:53-54` (defined twice, "Intentionally unused"), `tests/graph/test_transfers.py:90-92`.
- **Suggested change:** delete both definitions and the test (rail uses `RailCalibration.boarding_min/alighting_min`).

### TE-22 — Missing `__init__.py` in `tests/`, `tests/cli/`, `tests/web/`
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Why it matters:** under the default prepend import mode a rootless test file is imported by basename (`test_entrypoint`, `test_ramps`) with its directory on `sys.path`, while packaged dirs import as `emit.test_index`, `graph.test_build` (rooted at `tests/` because `tests/` itself has no `__init__.py`). Unique today, so harmless; adding `tests/web/test_config.py` or `tests/cli/test_index.py` would collide (`import file mismatch`). Either add `__init__.py` everywhere (including `tests/`) or set `--import-mode=importlib`.

### TE-23 — `real_multi_band` is a name convention, not a registered marker
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (`pyproject.toml` registers only `network`)
- **Where:** `tests/contour/test_bands.py:126`; exclusion depends on the caller remembering `-k "not real_multi_band"`. A plain `uv run pytest` runs a full Seoul solve (minutes). Register a marker and add it to `addopts` alongside `network`/`integration` (TE-5).

### TE-24 — `test_tiles.py` needs tippecanoe with no skip, and does not check the layer name
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed by reading
- **Where:** `tests/emit/test_tiles.py:15-19`; `src/transport_maps/emit/tiles.py:20` (`LAYER = "bands"`), `web/app.js:381` (`"source-layer": "bands"`).
- **Suggested test:** `pytest.importorskip`-style skip when `shutil.which("tippecanoe")` is None; read the PMTiles metadata JSON (`vector_layers[0].id`) and assert it equals `tiles.LAYER`, and assert `tiles.MAX_ZOOM >= max(l["minzoom"] for l in bands.LODS)` so the native level is actually tiled.

### TE-25 — `test_a_schengen_border_costs_nothing_extra` is guarded by an `if` that can turn it into a silent pass
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (guard fires today: CHE/FRA)
- **Where:** `tests/sources/test_countries.py:79`.
- **Suggested change:** replace the `if` with `pytest.skip(...)` (visible) or choose cells by country lookup so the assertion always runs. Mutation: make `immigration_zone` return the country code for CH → red.

### TE-26 — 44-second tests for two-airport bounds
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (durations)
- **Where:** `tests/graph/test_nodes.py:47-63` (`test_the_dropped_airport_bound_actually_aborts`, 43.97 s), `:31-44`.
- **Suggested change:** stub `landmask.land_cells`, `roads.cell_class`, `urban.urban_mask` to a handful of cells; the bound logic is independent of the universe size.

## Final sweep

**Flaky patterns**
- Time: none use wall-clock; `wikidata.time.sleep` is stubbed in `test_wikidata.py`. Fine.
- Network: only 3 tests marked; real downloads reachable from ~10 modules on a cold cache (TE-5). `test_entrypoint.py` spawns `sys.executable -m transport_maps.cli` — depends on the venv being the interpreter (true under `uv run`).
- Ordering of dicts/sets: `set(zip(r, c))` comparisons in `test_ferry.py` are order-insensitive; `_ferry_edges` builds `best` from a dict whose insertion order is deterministic. `rail_detail._line_between` uses `maintain_order=True`. No hazard found.
- Temp dirs / global state: `roads._grid_cache` module global is monkeypatched correctly in `test_cache_provenance.py` (restore order verified); `countries.A3_TO_A2` is a mutable module global filled on first `_polygons()` call and never reset — a test that redirects `config.CACHE` before any `iso2` call sees whichever archive loaded first. `config.CACHE`/`config.BUILD` are monkeypatched per test in some modules and left real in others (TE-12).
- Tests depending on `data/cache`, `data/build`, `dist/`: TE-5 list plus `test_licence_firewall.py` (skips on empty dist — correct) and `test_cli.py` (TE-13). `dist/` is currently stale versus `origins.toml` (157 vs 553) and versus `index.ATTRIBUTION` (7 vs 9).
- mtime-based cache keys: `osm.rail_routes`/`ferry_links` fingerprint `st_mtime_ns` — sound on APFS/ext4; the replaced-extract test would be flaky on coarse-mtime filesystems (TE-12).

**pytest warnings:** none emitted in the run (`-rA` summary has no warnings section).

**`-m 'not network'` addopts:** excludes exactly `test_resolves_article_titles_to_iata_codes`, `test_resolves_underscore_titles_under_the_exact_key_passed_in`, `test_resolves_both_titles_when_two_collapse_to_the_same_page`. The name promises an offline suite it does not deliver (TE-5). `real_multi_band` is not a marker (TE-23).

**Missing `__init__.py`:** `tests/`, `tests/cli/`, `tests/web/` — harmless today, collision-prone (TE-22).

**TDD opportunities (write the test first, watch it fail):**
1. `landmask._cells_touching` is committed "ready to replace overlap containment" (`ac191db`) but unwired and untested: on the two-islands fixture from `test_islands_survive_a_cache_free_run`, assert `_cells_touching(poly, 6) == set(h3shape_to_cells_experimental(..., contain="overlap"))` before switching, plus a pentagon-crossing ring for the `except Exception` branch.
2. The forked-abort test (TE-2) — red today.
3. `index` subcommand refusing a partial dist (TE-13) — red today.
4. `deploy_check.check_dist` (TE-14).
5. `app.js`/Python constant parity (TE-6).
6. `_validated_json` and `_retry_after_seconds` HTTP-date branches (`sources/_utils.py:13-58`) — pure functions, no test.
7. `expand_origins.slugify`/`km` and `adsb_extract.legs_from_trace` — pure, untested.

## Coverage

Every file below was read in full unless noted.

Tests (45 files): `tests/test_cli.py`, `tests/test_config.py`, `tests/test_golden.py`, `tests/test_licence_firewall.py`, `tests/test_validate.py`, `tests/cli/test_entrypoint.py`, `tests/calibrate/{__init__,test_fit,test_ground}.py`, `tests/contour/{__init__,test_bands,test_grid,test_native_grid}.py`, `tests/emit/{__init__,test_hover,test_index,test_itinerary,test_modes,test_rail_detail,test_routes_json,test_tiles}.py`, `tests/graph/{__init__,test_air,test_build,test_ferry,test_ground,test_nodes,test_rail,test_rail_integration,test_refine,test_transfers}.py`, `tests/solve/{__init__,test_dijkstra}.py`, `tests/sources/{__init__,test_airports,test_cache_provenance,test_countries,test_landmask,test_osm,test_roads,test_routes,test_urban,test_wikidata}.py`, `tests/web/test_ramps.py`; `tests/fixtures/icn_wikitext.txt` (existence and use only). No `conftest.py` exists anywhere in the repo.

Production (41 files): `src/transport_maps/{__init__,cli,config,validate}.py`, `calibrate/{__init__,fit,ground}.py`, `contour/{__init__,bands,grid}.py`, `emit/{__init__,airports_json,borders,hover,index,itinerary,modes,places,rail_detail,routes_json,tiles,water}.py`, `graph/{__init__,air,build,ground,nodes,rail,refine,transfers}.py`, `solve/{__init__,dijkstra}.py`, `sources/{__init__,_utils,airports,countries,landmask,osm,roads,routes,urban,wikidata}.py`.

Scripts (9): `scripts/deploy_verify.sh`, `browser_verify.sh`, `check_ramps.py`, `build_water_tiles.py`, `expand_origins.py`, `ground_check.py`, `calibrate_ground.py`, `osm_rail.sh` in full; `adsb_extract.py` header, constants and function signatures (lines 1–60 read, remainder skimmed for structure).

Web: `web/app.js` in full; `web/index.html` — head, preload/CSP-relevant links, every element id, and a grep for the design-policy properties (`letter-spacing`, `text-transform`, `tabular-nums`, serif) which returned nothing; the 245-line `<style>` block was not read line by line.

Config/data: `pyproject.toml`, `calibration.toml` (listing), `CLAUDE.md`, `README.md` attribution table, `data/origins.toml` (count), `dist/index.json` (counts), `data/build` and `data/cache` listings (read-only).
