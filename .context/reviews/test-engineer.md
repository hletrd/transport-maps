# Test-engineer review — transport-maps, cycle 2

Reviewed at HEAD `bf9e5cc` (`feat/transport-pipeline`), 2026-09-10. Read-only: no file in
the repository was written except this one (`git status` after every experiment showed only
another agent's `.context/reviews/security-reviewer.md`). Nothing under `data/` or `dist/`
was written, deleted or renamed: every test I ran went through a scratchpad pytest plugin
(`/private/tmp/claude-501/-Users-hletrd-flash-shared-transport-maps/aacce825-…/scratchpad/tm_mut.py`)
that (a) points `config.CACHE` at a scratch directory pre-seeded with copies of the two
Natural Earth archives, and (b) applies a named source mutation to one module **in memory**
(`exec` of the edited source into the module's namespace), so the tree stayed untouched.
`data/cache` held 475 files before and after every run. Logs and mutation specs are in the
scratchpad (`logs/*.log`, `mut/*.json`, `pt.sh`, `app_pure.test.mjs`).

Scope honoured: no `build-all`, no `uv run transport-maps`, no graph-building fixture
(`tests/graph/test_{build,ground,nodes}.py`, `tests/sources/test_roads.py`,
`tests/test_golden.py`, `tests/sources/test_landmask.py`, the `real_multi_band` test,
`tests/sources/test_countries.py::test_no_land_cell_is_left_without_a_country`) was executed;
those are audited by reading and labelled accordingly. No browser, no git state change.

**Baseline** (`uv run pytest -p tm_mut -p no:cacheprovider -q` over every fast module,
`-k "not no_land_cell_is_left"`): **206 passed, 5 deselected, 2 warnings, 18.0 s**. The two
warnings are the Python 3.14 fork `DeprecationWarning` from
`test_a_gate_failure_in_a_forked_worker_aborts_the_run` (W1). Collection of the whole tree:
258 collected, 4 deselected by `addopts` (3 `network`, 1 `real_multi_band`) → 254 in the gate.

| Severity | Count | IDs |
|---|---|---|
| High | 4 | TE-1, TE-2, TE-3, TE-4 |
| Medium | 6 | TE-5 … TE-10 |
| Low | 8 | TE-11 … TE-18 |

Read first, as instructed: `CLAUDE.md`, `_aggregate.md` §F/§G, the c1 gates-and-tests plan
(cycle-2 items F3, F6, F4a, F4b, F8, F9; cycle-3 F5, F7, F10, F11, F13, B3), `deferred.md`,
`pyproject.toml`. Note that `tests/sources/test_cache_provenance.py` is **not** new since
`ac191db` (`fd5da85` is an ancestor of `ac191db`; `git diff ac191db..HEAD -- tests/` does not
list it); it was untracked in the stale status snapshot only. It is audited in full below
regardless, as asked.

---

## 1. Inventory

45 files, 3,708 lines (`__init__.py` files are empty). "Covers" is the production module the
file asserts on; "runs" is what the file needs to execute.

| File | Lines | Tests | Covers | Runs on |
|---|---|---|---|---|
| `tests/calibrate/test_fit.py` | 55 | 4 | `calibrate/fit.py` | synthetic frames |
| `tests/calibrate/test_ground.py` | 74 | 6 | `calibrate/ground.py` | synthetic arrays, fake client |
| `tests/cli/test_entrypoint.py` | 36 | 3 | `cli.main` (argparse only) | subprocess ×3 (~7 s) |
| `tests/contour/test_bands.py` | 281 | 13 (+1 `real_multi_band`) | `contour/bands.py` | small fixtures; one full graph fixture (deselected) |
| `tests/contour/test_grid.py` | 43 | 3 | `contour/grid.universe` | small fixtures, `tmp_path` |
| `tests/contour/test_native_grid.py` | 38 | 1 | `contour/grid.native_edges` | small fixture |
| `tests/emit/test_hover.py` | 95 | 7 | `emit/hover.py` | fixtures at `SOLVE_RES`/`FINE_RES` |
| `tests/emit/test_index.py` | 90 | 5 | `emit/index.py`, `README.md` parity | `tmp_path` |
| `tests/emit/test_itinerary.py` | 71 | 5 | `emit/itinerary.py` | fixtures |
| `tests/emit/test_modes.py` | 73 | 4 | `emit/modes.py` | **real GRIP4 grid** (`data/build/road_class_grid_*.npy`) |
| `tests/emit/test_rail_detail.py` | 51 | 3 | `rail_detail.last_station_per_node`, `_line_between`, `lookup_tables` | fixtures |
| `tests/emit/test_routes_json.py` | 49 | 2 | `emit/routes_json.py` | fixtures |
| `tests/emit/test_tiles.py` | 19 | 1 | `emit/tiles.py` | **tippecanoe**, no skip |
| `tests/graph/test_air.py` | 127 | 16 | `graph/air.py` | `calibration.toml` |
| `tests/graph/test_build.py` | 139 | 10 | `graph/build.py` | **full `build_index` + `build_graph` ×2** |
| `tests/graph/test_ferry.py` | 194 | 11 | `build._ferry_edges`, mixed grid | real countries/places archives, GRIP4 grid |
| `tests/graph/test_ground.py` | 75 | 4 | `graph/ground.py` | **full `build_index`** |
| `tests/graph/test_nodes.py` | 63 | 6 | `graph/nodes.py` | **full `build_index` ×2** (one per abort test) |
| `tests/graph/test_rail.py` | 74 | 5 | `graph/rail.py` | fixtures |
| `tests/graph/test_rail_integration.py` | 78 | 3 | `build._rail_edges`, `build_graph` refusal | countries archive |
| `tests/graph/test_refine.py` | 78 | 5 | `graph/refine.py`, `nodes._nearest_land` | pure h3 |
| `tests/graph/test_transfers.py` | 88 | 16 | `graph/transfers.py` | `calibration.toml` |
| `tests/solve/test_dijkstra.py` | 23 | 2 | `solve/dijkstra.solve_from` | fixtures |
| `tests/sources/test_airports.py` | 31 | 4 | `sources/airports.py` | real `data/build/airports_*.parquet` |
| `tests/sources/test_cache_provenance.py` | 149 | 16 | `_utils._params_hash`, `_atomic_write`, roads/airports/landmask stamps | `tmp_path` |
| `tests/sources/test_countries.py` | 116 | 13 | `sources/countries.py`, `ground.hex_edges` border rules | countries archive; one **full-universe** test |
| `tests/sources/test_landmask.py` | 79 | 10 | `sources/landmask.py` | **4.09 M-cell parquet** (module fixture) + one cache-free test |
| `tests/sources/test_osm.py` | 132 | 10 | `sources/osm.py` | synthetic PBFs; **writes parquet into real `data/cache`** |
| `tests/sources/test_roads.py` | 132 | 9 | `sources/roads.py` | real GRIP4 grid; **full `build_index`** |
| `tests/sources/test_routes.py` | 266 | 10 (3 `network`) | `sources/routes.py` | fixture wikitext, fakes |
| `tests/sources/test_urban.py` | 138 | 6 | `sources/urban.py`, `ground.cell_speed_kmh` | places archive, GRIP4 grid |
| `tests/sources/test_wikidata.py` | 83 | 4 | `sources/wikidata.iata_for_titles` | fakes, `tmp_path` |
| `tests/test_cli.py` | 224 | 8 | `cli._slug`, `cli._build_all` (serial + forked) | stubs; **real OSM extract cache** (see TE-9) |
| `tests/test_config.py` | 21 | 3 | `config.py` | — |
| `tests/test_golden.py` | 49 | 4 | end-to-end Seoul solve | **full graph** |
| `tests/test_licence_firewall.py` | 72 | 4 | `dist/` scan, `calibration.toml` | reads `dist/` |
| `tests/test_validate.py` | 265 | 14 | `validate.py` (all four gates) | small fixtures; countries archive |
| `tests/web/test_ramps.py` | 37 | 4 | `scripts/check_ramps.py` over `web/app.js` | — |
| `tests/fixtures/icn_wikitext.txt` | — | — | fixture for `test_routes.py` | — |

No `conftest.py` exists anywhere. `__init__.py` exists in every subdirectory but **not** in
`tests/` itself.

---

## 2. Coverage map (HEAD `bf9e5cc`)

"Direct" = a test asserts on that function with a fixture that would change the outcome.
"Incidental" = it runs only on the way to something else (module-scoped `build_index()`
fixtures, real `build_graph`). "None" = no test executes it.

| Module | Direct | Incidental only | None |
|---|---|---|---|
| `cli.py` | `_slug`; `_build_all` serial sequencing (index.json ordering, `--limit`, rail/ferry report); **forked path + `GateFailure` (new, real: M7)**; `main --help`/unknown/none | — | `solve` and `index` subcommands (`main():264-294`); `_worker_cap`; `_load_rail`/`_load_ferries` "included" branch; `_solve_one` file set with real emitters |
| `config.py` | edges monotonic, sentinel, `HOVER_RES < SOLVE_RES` | — | `FINE_RES > SOLVE_RES` |
| `validate.py` | `check_coverage` (fraction, threshold, Antarctica, **NaN→0 (new, real: M3)**), `check_bands_cover` (hole, missing level, full), `check_monotonic_ground` (accept/reject), `check_airport_connectivity` (wired, severed, names, **largest component (real: M16)**) | `check_monotonic_ground` closed-border/zone branches via `test_build`'s live graph only | the `country=`/`zone=` pass-through the forked build actually uses |
| `solve/dijkstra.py` | `solve_from` (2) | `with_predecessors=True`, `origin_node` via graph fixtures | `origin_node` ValueError |
| `graph/nodes.py` | `NodeIndex` accessors (real index); `MAX_DROPPED_AIRPORT_FRACTION` gate (real index, 2× build); **`_nearest_land` ring bound (new; "nearest" not pinned — TE-10)** | `cell_at` split path via `test_build`/`test_golden` | `build_index` **snapping** wiring (`snapped`, `:155-165`), dropped-station count, `station_*` accessors |
| `graph/build.py` | duplicate-pair refusal; `is_geographically_plausible`; unknown-pair bound; `_ferry_edges` (range, self-loop, dedup, mask, adjacency, sealed, zone, **mixed grid (new, real: M6)**); `_rail_edges` boarding/symmetry; stations-without-frame refusal | `_air_edges`, `_access_edges`, `_transfer_edges` via live graph shape/positivity | `_air_edges` border charge and `_SIZE_RANK`; `_access_edges` direction; `_transfer_edges` `max(conn, wait)` and "nothing departs → no edge"; `_rail_edges` closed-border cut / zone charge; `_border_rules` (F10) |
| `graph/ground.py` | destination-speed rule; speed range; DMZ cut (**western only — TE-1**); SG/MY crossing; urban factor; roadless floor | fine↔base `cross` dedup via `test_ferry` mixed fixture | `SPEED_BY_ROAD_CLASS_KMH` values vs `calibration.toml` (B2) |
| `graph/air.py` | 16 tests incl. knee | — | — |
| `graph/rail.py` | partition, platform merge, fastest wins, TGV plausibility | `load_*_calibration` via live graph | — |
| `graph/refine.py` | `dense_mask`; `refine` shape; **`ground_adjacent` (new, real: M6)** | `expand` children (**vacuous — TE-5**) | — |
| `graph/transfers.py` | 16 tests | — | — |
| `contour/bands.py` | `band_of`, LOD features, order, `max_minutes`, antimeridian, fringe, unreachable, **split-cell parent (real: M8)**, random-junction cover | `_coarse_features` ring growth | `_polygonal` GeometryCollection path; "render grid does not match" ValueError |
| `contour/grid.py` | `universe` rings/symmetry/cache key; `native_edges` cross pairs | — | `native_edges` cache branch (never ≥ `MIN_CELLS_TO_CACHE` in a test) |
| `emit/hover.py` | uint16 layout; **centre child, water fallback, split centre (real: M1)**; sentinel; clamp | — | — |
| `emit/index.py` | sorted ids; attribution records; README parity; `railDetail` literal | `load_origins` duplicate guard, `mode_detail` | `write_index` key set vs what `app.js` reads (`hoverCellsUrl`, `solveRes`, `fineRes`, `modeDetail`) |
| `emit/itinerary.py` | `arrival_airport_per_node` (4, good) | `write_itinerary` byte count only | ordinal arithmetic vs `app.js legsTo`; **agreement with hover's chosen child (TE-2)** |
| `emit/modes.py` | adjacency→ferry, rail accumulation, air excluded | byte count | **`ROAD_CHANNEL` mapping (TE-6)**; clip/NaN; agreement with hover's child (TE-2) |
| `emit/rail_detail.py` | `last_station_per_node`, `_line_between`, **`lookup_tables` (new)** | — | **`write_rail_detail` entirely** (`:80-110`) |
| `emit/routes_json.py` | offsets, both sides, sentinel→null | — | — |
| `emit/tiles.py` | magic bytes (needs tippecanoe) | — | layer name `bands` that `app.js:465` requires; `MAX_ZOOM` vs LOD minzoom |
| `emit/airports_json.py`, `borders.py`, `places.py`, `water.py` | — | — | everything (field order `a[0..5]` read by `app.js:595`) |
| `sources/_utils.py` | `_params_hash` (3), `_atomic_write` mode (umask-dependent — TE-12), `_refuse_partial` via routes/wikidata | — | `_retry_after_seconds` HTTP-date branch; `_validated_json` error/continue/batchcomplete branches |
| `sources/airports.py` | stamp moves for `SIZE_BY_TYPE`, `REQUIRED_SOURCE_COLUMNS`; stamped path is the one read; real-table shape | — | stamp for `AIRPORTS_URL`; filter rules on a synthetic CSV (offline) |
| `sources/countries.py` | closed table; 4-point resolution; SG/MY; blank fill over full universe (integration) | `_fill_blanks` nearest fallback | **cache-key provenance (hash of cells) — no test (TE-7)**; `iso2` empty-table re-read |
| `sources/landmask.py` | baseline count (per-res table); islands/ocean; cache-free islands; stamp moves for res, `ANTARCTICA_MAX_LAT`; stamped path read | `_antarctic_wedges`, `_without_lakes`, `_pole_cells` via the cached universe | stamp for the URLs/`POLE_CLIP_LAT`/`WEDGE_COUNT`; **`_cells_touching` still unwired and untested** (`:181-207`) |
| `sources/osm.py` | 10 tests incl. content-keyed cache miss, antimeridian ferry | — | cross-extract longest-sequence dedup (`:199-207`); `ferry_links` key omits `ANTIMERIDIAN_EPS_DEG`/`MIN_FERRY_KM`/`MAX_FERRY_KM` (TE-7) |
| `sources/roads.py` | grid shape; sampling; footprint > centroid; antimeridian fallback; row/col; stamp for `DENSITY_THRESHOLD`; stamped path read | — | `road_class_grid` from synthetic rasters; stamp for `GRIP4_URL` (absent from stamp — G1) |
| `sources/routes.py` | parse (4), refuse-partial (3), absent-vs-unreturned (3) | — | `_wikipedia_titles`; 20 k floor / sanity-pair raise paths; **`routes.parquet` bare `.exists()` (`:242-244`, G1) has no provenance test** |
| `sources/urban.py` | mask marks cities; factor divides; roadless floor; **fresh-cache download (A5, real by reading)**; **key moves with `PLACES_URL` (real: M10)** | — | key on `len/first/last` instead of the cell list (G1; no test — TE-7) |
| `sources/wikidata.py` | 4 offline refusal/resume tests | — | `_resolve_batch` redirect/normalize logic offline (3 `network` tests only) |
| `calibrate/fit.py`, `calibrate/ground.py` | recover known coefficients; support guard; budget; key; empty route | — | `drive_minutes` duration parsing on a populated response |
| `scripts/check_ramps.py` | `ramps()`, `problems()`, sea lightness | — | `respace`, `oklab_to_srgb` round trip; parser count guard (TE-20 c1) |
| `scripts/deploy_verify.sh` | — | — | step 1 inline Python (F9); **step 1b is inert (TE-4)** |
| `scripts/browser_verify.sh` | — | — | post-deploy only |
| `scripts/expand_origins.py`, `adsb_extract.py`, `ground_check.py`, `calibrate_ground.py`, `build_water_tiles.py`, `osm_rail.sh` | — | — | everything (`expand_origins.slugify/km`, `adsb_extract.legs_from_trace` are pure) |
| `web/app.js` (1,126 lines), `web/index.html` | `RAMPS` block via `test_ramps.py` | — | `esc`, `fmtTime`, `cellIndex`, `lookup`, `legsTo`, `paintScale` ticks, `bandRangeAt`, `expandRamp`, `names`/`NO_AIRPORT`/`NO_RAIL`/`UNCHARTED` parity with Python (TE-3) |

---

## 3. Findings

### High

#### TE-1 — The eastern DMZ cut test is still vacuous at HEAD; deleting the border cut leaves it green (F3, new evidence)
- **Severity:** High  **Confidence:** High  **Status:** Confirmed by mutation  **Effort:** S
- **Where:** `tests/sources/test_countries.py:31-51` (`np.arange(37.6, 39.2, 0.05)` at `config.SOLVE_RES`), `:77-88` (Schengen `if` guard); `src/transport_maps/graph/ground.py:103-113`.
- **Why:** Computed at HEAD with pure h3: the eastern chain has 32 cells and **four consecutive pairs at grid distance 2** (indices 2, 14, 15, 26); the western chain (0.04° step) has none. `hex_edges` only joins neighbours, so `north` is unreachable from `south` whether or not the cut exists. Mutation **M5** (delete the `countries.is_closed` block in `hex_edges.add`): `test_the_western_dmz_is_cut_too` → **red**, `test_the_inter_korean_border_is_not_traversable_on_the_ground` → **green**. Only the western test protects the cut. `test_a_schengen_border_costs_nothing_extra` still wraps its only assertion in `if len(set(codes)) == 2 and …`; the fixture resolves to CHE/FRA today so it runs, but a country-table change turns it into a silent pass. The plan schedules F3 for this cycle; it has not landed.
- **Failure scenario:** a `CLOSED_BORDERS` edit or a `_fill_blanks` regression reopens the eastern DMZ; the suite shows one red test instead of two, and none if the western chain ever skips a cell too.
- **Suggested test:** build both chains with `h3.grid_path_cells(south, north)` and add the fixture self-check `assert all(h3.are_neighbor_cells(a, b) for a, b in pairwise(cells))`; replace the Schengen `if` with `pytest.skip(...)` or pick the FR cell by `countries.cell_country` over the ring as the SG/JB test now does. Mutation that must go red: M5 (both chains), and `immigration_zone("CH") → "CH"` for the Schengen test.

#### TE-2 — Nothing pins that `.air.bin`, `.modes.bin` and `.rail.bin` describe the same solver cell as `.bin`; `write_rail_detail` has no test at all (F7, new evidence)
- **Severity:** High  **Confidence:** High  **Status:** Confirmed by mutation  **Effort:** M
- **Where:** `src/transport_maps/emit/itinerary.py:49-71` (docstring promises "the SAME solver cell the hover time came from"), `emit/modes.py:82-101`, `emit/rail_detail.py:80-110`; `tests/emit/test_itinerary.py:52-71`, `tests/emit/test_modes.py:65-73`, `tests/emit/test_rail_detail.py` (no call to `write_rail_detail`).
- **Why:** Mutation **M1** (`_representative_children` → always the fastest child): `tests/emit/test_hover.py` goes red (2 tests, the F2 fix is real) but `test_itinerary.py` (5) and `test_modes.py` (4) stay **green** — their file-level tests assert only byte counts and all-sentinel content. The user-visible contract (C3: readout, route panel and mode breakdown from three different cells) is asserted in one emitter of four. `write_rail_detail` — table dedup, `came_from` line lookup, `NO_RAIL` clamp, the JSON schema `app.js:742-751` reads — runs only in the build.
- **Failure scenario:** someone "optimises" `write_modes` to use `best_pos` directly; the route panel itemises a different journey from the headline time; every test stays green.
- **Suggested test:** `tests/emit/test_layout_contract.py` — one index at real resolutions (the `test_hover.py` PARENT/CENTRE/SIBLINGS fixture plus one airport and two stations), a predecessor chain through the *sibling* (not the centre), write all five files, and assert (i) equal lengths (`len(bin) == len(air) == len(modes)//6 == len(rail) == len(hover_cells.bin)//8`), (ii) the hover value is the centre's, (iii) `.air.bin` ordinal + `n_cells + n_airports` decodes to the centre's arrival node (or `NO_AIRPORT`) and *not* the sibling's, (iv) `.modes.bin` row equals the centre's accumulator, (v) `.rail.bin` indexes a `.rail.json` row naming the centre's station. Mutations that must go red: M1 applied to each writer separately; `astype("<u4")`; `node - first_arrival + 1`.

#### TE-3 — The page's pure decoding still has no test; a Node harness works on this host in 66 ms and the tick rule ports to Python (F5, new evidence — pull forward)
- **Severity:** High  **Confidence:** High  **Status:** Confirmed (harness run)  **Effort:** M (S for the constants-parity half)
- **Where:** `web/app.js:31-32` (`esc`), `:532-539` (`fmtTime`), `:541-550` (`cellIndex`), `:555-560` (`lookup`), `:564-580` (`legsTo`: `airports + count + ordinal`), `:179-198` (`paintScale`), `:610-612` (`names` mirrors `modes.CHANNELS`), `:145` (`NO_AIRPORT = 0xFFFF`), `:742` (`NO_RAIL = 0xFFFF`), `:465` (`"source-layer": "bands"`), `:19` (`UNCHARTED`).
- **Why:** `node` v24.14.0 is on the host. A 40-line `node --test` file in the scratchpad (`app_pure.test.mjs`) lifts `esc`, `fmtTime` and `cellIndex` out of `app.js` by regex and runs them: **4 passed, 66 ms**. It already documents one seam: `fmtTime(119.6)` → `["1", "h 60m"]` (latent — hover minutes are uint16 and `routes.json` minutes are rounded, so no integer input hits it today, but the `total - landed.min` subtraction would if either side ever became fractional). A Python port of `paintScale` against `config.BAND_EDGES_MIN` gives ticks at edges 60/125/225/465/955/1470/3020/4320 → labels `1, 2.1, 3.8, 7.8, 15.9, 24.5, 50.3, 72+` at `(i+1)/37` — the C4 fix is verifiably on true edges, but nothing in CI says so, and `names`, `NO_AIRPORT`, `NO_RAIL`, the layer name and the `airports.json` column order are re-typed in JS with no parity check (J1).
- **Suggested tests:** (1) `tests/web/test_app_constants.py` (pure Python, S): regex-extract from `app.js` and assert `names == list(modes.CHANNELS)`, `NO_AIRPORT == itinerary.NO_AIRPORT`, `NO_RAIL == rail_detail.NO_RAIL`, `UNREACHABLE_BAND == bands.UNREACHABLE_BAND`, `"source-layer": "bands" == tiles.LAYER`, and that `airports_json.build`'s `fields` order matches the `a[0..5]` reads. Mutation: change any one constant. (2) `tests/web/test_app_pure.py`: `pytest.importorskip`-style skip when `shutil.which("node")` is None, else `subprocess.run(["node", "--test", …])` on a checked-in `web/tests/app_pure.test.mjs`; port `paintScale` and assert the eight tick indices above so an evenly-spaced regression goes red. (3) A Python round-trip: `write_routes` + `write_itinerary` on a fixture, then decode with the `legsTo` arithmetic.

#### TE-4 — `deploy_verify.sh` step 1b is inert: the copy it greps for no longer exists, so the gate always passes; step 1's inline Python is still untested (F9, new evidence)
- **Severity:** High  **Confidence:** High  **Status:** Confirmed by reading  **Effort:** S
- **Where:** `scripts/deploy_verify.sh:39-51` (`grep -oE '[0-9]{3} (cities|departure)' web/index.html`), `web/index.html:411` (`<span id="n-cities">…</span> charted cities`), `web/app.js:216` (`$("n-cities").textContent = String(meta.origins.length)`); `scripts/deploy_verify.sh:9-37`.
- **Why:** Commit `d84217f` made the page derive the city count from `index.json`, so `index.html` now contains no `NNN cities` literal; the grep yields nothing, `for s in $stated` runs zero times, and the step prints "agrees" for every build — including one whose copy says "553 cities" in a form the regex does not match (`1,000`, two digits, "departures from 553"). It is a gate that passes when broken, the shape CLAUDE.md's testing rule forbids. Step 1 (per-origin widths, required files) has never had a unit test; a typo in the widths tuple (`.modes.bin` = 12 = 6 channels × 2) would pass silently, and it does not check that `index.json`'s origins equal `data/origins.toml`, that `.rail.json` accompanies `.rail.bin`, or that `water.pmtiles` is non-empty.
- **Suggested test:** move step 1 into `scripts/check_dist.py` (`check_dist(dist: Path, origins: list[dict], n_channels: int) -> list[str]`) called from the script, with `tests/web/test_check_dist.py` on a synthetic `tmp_path` dist: truncate one `.bin` by 2 bytes → error; `.rail.bin` without `.rail.json` → error; an origin in `origins.toml` missing from `index.json` → error; `n_channels` from `modes.CHANNELS` so a seventh channel cannot drift. Delete step 1b or replace it with an assertion that `index.html` contains **no** hard-coded three-digit count (`! grep -qE '[0-9]{3} (cities|departure)'`), which is what the page change actually promised.

### Medium

#### TE-5 — `test_base_values_carry_down_to_children` is still vacuous at HEAD (F6, scheduled this cycle, not landed)
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by mutation  **Effort:** S
- **Where:** `tests/graph/test_refine.py:30-42` (`split[0] = True`, `values = np.arange(len(base)) * 10`, `assert (out[fine] == 0).all()`); `src/transport_maps/graph/refine.py:61-63`.
- **Why:** Mutation **M2** (zero-fill every child whose base index is duplicated): **5 passed**. The split cell is index 0 whose value is 0, so carry-down and zero-fill are indistinguishable; the assertion literally asserts the zero. `ground.cell_class`/`urban_mask` carry road class and the urban mask through `expand` for millions of children (`ground.py:42-50`), so a zero-fill there would make every fine cell roadless-and-rural with a green suite.
- **Suggested test:** `split[2] = True; values = np.arange(len(base)) * 10 + 7`; assert `out[fine].size == 7` and `(out[fine] == values[2]).all()`; keep the unsplit identity check. Mutation that must go red: M2.

#### TE-6 — `tests/emit/test_modes.py` never pins the road-channel mapping; a swapped `ROAD_CHANNEL` stays green (F11, new evidence)
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by mutation  **Effort:** S
- **Where:** `tests/emit/test_modes.py:30-40` (`road = acc[1][2:].sum()`), `:65` (name says "three uint16"; `CHANNELS` has six); `src/transport_maps/emit/modes.py:27`.
- **Why:** Mutation **M19** (`ROAD_CHANNEL = {…, 1: 4, …, 5: 2}` — highway booked as minor road and local as highway): **4 passed**. Summing channels 2–5 hides which channel received the minutes, and `cell_class=None` makes every test load the real 9 MB GRIP4 grid (`road_class_grid_495d9dd1.npy`) — an emit unit test that downloads five GRIP4 zips on a cold clone.
- **Suggested test:** pass `cell_class=np.array([1, 1, 0])` and assert `acc[1][2] == 30.0` with the other channels zero; a second case with class 0 → channel 5 and class 4 → channel 4. Rename the byte-count test to say `len(CHANNELS)`. Mutation that must go red: M19.

#### TE-7 — `test_cache_provenance.py` proves the key moves for five of the fourteen constants in the three stamps, and no provenance test exists for four other derived caches (G1, new evidence)
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by mutation and reading  **Effort:** S
- **Where:** `tests/sources/test_cache_provenance.py:37-47` (roads), `:71-94` (airports), `:100-117` (landmask), `:120-130` (hash-shape test); `src/transport_maps/sources/roads.py:59`, `airports.py:40`, `landmask.py:176-178`, `countries.py:96`, `osm.py:151-153`, `urban.py:76-77`, `routes.py` (bare `routes.parquet .exists()`), `contour/grid.py:95-99`.
- **Why (per case, answering the brief's question):**
  - The **"path moves"** tests are real for the constant they name: M4a (drop `DENSITY_THRESHOLD`) → 2 red; M14 (drop `SIZE_BY_TYPE`) → 2 red; M13 (drop `ANTARCTICA_MAX_LAT`) → 2 red. `REQUIRED_SOURCE_COLUMNS` and the resolution are likewise pinned.
  - The **"reads the stamped path"** tests are the strong half: they prove the stamped path is the one the loader actually consults (a sentinel file is found, then not found after the constant moves). They went red under every stamp mutation.
  - **Not proven**: `GRID_ROWS`, `GRID_COLS`, `N_TYPES` (roads); `AIRPORTS_URL` (airports); `LAND_URL`, `ICE_URL`, `LAKES_URL`, `POLE_CLIP_LAT`, `WEDGE_COUNT` (landmask). Reading confirms they are in the stamps today, but nothing would notice their removal. The landmask stamp also carries a hand-typed literal `"pole-cells+shelves-lakes"` as the polyfill-method version; switching `land_cells` to the committed-but-unwired `_cells_touching` would not move the key (G1's "lacks the polyfill method").
  - `test_every_stamped_path_carries_a_hash` only proves an 8-character alphanumeric segment exists: M4b (a constant `"deadbeef"` stamp) leaves it **green**. It is redundant with the "moves" tests rather than wrong.
  - **Missing entirely**: `countries.cell_country` (key = hash of the cell list — the one place that does it right, unguarded); `osm.ferry_links` (key omits `ANTIMERIDIAN_EPS_DEG`, `MIN_FERRY_KM`, `MAX_FERRY_KM`, although `_ferries` filters on the first at parse time, so the parquet content depends on it); `routes.route_network` (bare `.exists()`, no stamp); `urban_mask` keys on `len/first/last` (M10 shows `PLACES_URL` is pinned; a same-length, same-ends, different-middle universe is not); `grid.native_edges` cache branch is never executed by a test (`MIN_CELLS_TO_CACHE = 5_000`).
- **Suggested test:** one parametrised test per module listing `[(module, "CONSTANT", new_value), …]` for **every** name in the stamp, asserting the path moves for each — the list then documents the governing set and a dropped name goes red. Add `test_urban_mask_key_covers_the_whole_cell_list` (same length and ends, different middle → two parquets), `test_ferry_links_key_moves_with_the_antimeridian_eps`, `test_cell_country_key_moves_with_the_cell_list`, and `test_route_network_path_carries_a_stamp` (red today). Mutations: revert each key.

#### TE-8 — Tests still write into the real `data/cache/`; 35 parquet files per run of the fast subset, and a `CACHE` redirect makes the whole subset hermetic in 18 s (F4b, new evidence)
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (counts; redirect experiment)  **Effort:** S
- **Where (exact tests → files):**
  - `tests/sources/test_osm.py` — every `osm.rail_routes(extracts_dir=tmp_path)` call (8 tests) writes `data/cache/rail_routes-<hash>.parquet` and `test_a_ferry_clipped_at_the_antimeridian_is_dropped` writes `ferry_links-<hash>.parquet`, **with a new name every run** (the fingerprint includes `str(tmp_path)` and `st_mtime_ns`). Count today: **358** `rail_routes-*` (294 at cycle 1, +64 since) and **26** `ferry_links-*`.
  - `tests/sources/test_countries.py` (`test_known_places…`, both DMZ tests, SG/JB, Schengen, full-universe) → `data/cache/cell_country-<hash>.parquet` (stable names; 45 present).
  - `tests/graph/test_ferry.py` (every `_index`/`_mixed_index` through `hex_edges` and `_border_rules`) → `cell_country-*` and `urban_mask-*` (26 present).
  - `tests/sources/test_urban.py` (`_idx` fixtures via `cell_speed_kmh`) → `urban_mask-*`; `tests/test_validate.py::test_{in,}consistent_neighbour_time…` → `cell_country-*` + `urban_mask-*`; `tests/graph/test_rail_integration.py` (2) → `cell_country-*`.
  - `tests/test_cli.py` reads the real OSM parquet and would re-parse and write it if an extract's mtime changed (TE-9).
  - Would download and write on a cold checkout: the four module-scoped `build_index()` fixtures, `test_golden`, `test_landmask`, `test_airports`, `test_modes` (GRIP4), `test_urban`/`test_countries` (archives).
- **Why:** The scratch plugin set `config.CACHE = <scratch>/cache` with copies of `ne_10m_admin_0_countries.zip` and `ne_10m_populated_places_simple.zip`: 206 tests passed in 18.0 s, the scratch cache received 16 `cell_country`, 10 `urban_mask`, 8 `rail_routes`, 1 `ferry_links`, and the real `data/cache` count stayed at 475. That is the F4b fix, demonstrated: an autouse `conftest.py` fixture redirecting `CACHE` (and `BUILD` for tests that do not need the real universe) is enough. Note the two archives in the real cache are mode `0600` (`ne_10m_populated_places_simple.zip`, `ourairports.csv` — written before the `_atomic_write` chmod fix); a fixture that copies them must `chmod 644`.
- **Suggested change:** `tests/conftest.py` with an autouse, function-scoped fixture: `monkeypatch.setattr(config, "CACHE", tmp_path / "cache")` for every test not marked `integration`; a session-scoped helper that copies the two NE archives into the scratch cache once; `test_osm.py` needs nothing else. List the 475 existing droppings for the owner (the orchestrator rule forbids deleting them this cycle).

#### TE-9 — `tests/test_cli.py` still reads the real OSM extract cache and runs a 2.75 s polars UDF per `_build_all`; `solve`/`index` untested (F8, scheduled this cycle, not landed)
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (timed, read-only)  **Effort:** S
- **Where:** `tests/test_cli.py:29-112` (`_stub_pipeline` never stubs `cli.osm.rail_routes`/`ferry_links`; only `:185-188` does), `src/transport_maps/cli.py:158-159,185` (`_load_rail()` → `rail_detail.lookup_tables(rail_routes)`), `:264-294` (`solve`, `index`).
- **Why:** With the real cache present, `osm.rail_routes()` is a 0.01 s parquet hit but `rail_detail.lookup_tables()` (a `map_elements` UDF over 257,007 rows → 150,761 line pairs, 57,286 stops) costs **2.75 s per call**, and `_build_all` runs the unstubbed path five times across four of the five sequencing tests (`test_the_build_reports_…` is the one that stubs it; the `--limit` test calls `_build_all` twice) — about 14 s of unrelated work per suite run, plus a hard dependence on `data/cache/osm/*.pbf` and its fingerprinted parquet). Under my `CACHE` redirect the same tests ran in well under a second because `_load_rail` raised `FileNotFoundError` — which is exactly the stub F8 asks for. `index` can still publish an `index.json` for origins with no files (A7), untested; `solve` writes a layout the page cannot load, untested; `_worker_cap` has no test.
- **Suggested tests:** in `_stub_pipeline`, `monkeypatch.setattr(cli.osm, "rail_routes", …raise FileNotFoundError)` and the same for `ferry_links`; `test_index_subcommand_refuses_when_origin_files_are_missing` (empty `DIST`, `sys.argv = [..., "index"]`, expect `SystemExit`) — red today; `test_worker_cap_drops_to_five_above_three_million_cells`.

#### TE-10 — The new `_nearest_land` test does not test "nearest", and `build_index`'s snapping path is untested (new at HEAD `bf9e5cc`)
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed by mutation  **Effort:** S
- **Where:** `tests/graph/test_refine.py:69-78` (`assert pos is not None and ring2[pos] in ring2` — the second conjunct is a tautology for any valid index); `src/transport_maps/graph/nodes.py:114-128`, `:154-165`.
- **Why:** Mutation **M9a** (take the first indexed cell found instead of the nearest): **1 passed**. Mutation **M9b** (search three rings): red — so the two-ring bound is real, the distance rule is not. The wiring in `build_index` (an airport whose `cell_at` cell is off the mask is snapped, counted in `snapped`, and *not* dropped) has no test: `test_the_dropped_airport_bound_actually_aborts` uses mid-ocean airports (nothing within two rings), and the loose real-index bound cannot tell "64 snapped" from "64 dropped".
- **Suggested test:** put land only on two ring-2 cells at different distances from the airport's coordinate (offset the point toward one of them) and assert the nearer is chosen; a stubbed `build_index` (`landmask.land_cells` → seven cells, `roads.cell_class`/`urban.urban_mask` → zeros, `airports.scheduled_airports` → one airport one ring off the mask) asserting `dropped_airports == ()` and `airport_cell_index` equals the neighbour. Mutation: M9a → red; drop the `_nearest_land` call → red.

### Low

#### TE-11 — pytest layout hygiene: no `tests/__init__.py`, so `tests/cli` and `tests/web` are top-level packages named `cli` and `web`; `test_ramps.py` mutates `sys.path` at import; no `integration` marker yet
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed  **Effort:** S
- **Where:** `tests/` (no `__init__.py`; every subdirectory has one after `00f40e4`), `tests/web/test_ramps.py:5`, `pyproject.toml:37-44`.
- **Why:** Under the default `prepend` import mode the packaged subdirectories are rooted at `tests/`, so the session imports `cli.test_entrypoint`, `web.test_ramps`, `graph.test_build`, `sources.test_osm`, … — generic top-level names that shadow any installed `cli`/`web` module and collide the moment a second `tests/<x>/` tree appears. `test_ramps.py`'s `sys.path.insert(0, scripts/)` is a session-wide side effect (J6). `addopts` registers `network` and `real_multi_band` only; F4a's `integration` marker is scheduled for this cycle and absent.
- **Suggested change:** add `tests/__init__.py` (or `--import-mode=importlib` in `addopts`); import `check_ramps` via a `conftest.py` fixture or make `scripts/` a package; register `integration` and mark the modules in §1 marked "full `build_index`".

#### TE-12 — `test_atomically_written_files_are_readable_by_other_users` depends on the invoking shell's umask
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (real under umask 022: M12 → red)  **Effort:** S
- **Where:** `tests/sources/test_cache_provenance.py:133-149`; `src/transport_maps/sources/_utils.py:85`.
- **Why:** The code honours the umask (`0o666 & ~umask`), so under `umask 077` the file is `0600` by design and the test fails with the code correct; under `022` it is a real guard (mutation M12 removing the `chmod` → red). Set the umask inside the test (`old = os.umask(0o022)` … `finally: os.umask(old)`) so the verdict is about the code.

#### TE-13 — `test_replacing_an_extract_of_the_same_name_is_a_cache_miss` relies on `st_mtime_ns` alone
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed by reading (still open from c1 TE-12)  **Effort:** S
- **Where:** `tests/sources/test_osm.py:94-111`; `src/transport_maps/sources/osm.py:180`.
- **Why:** The two PBFs differ only in one-character names, so their sizes coincide and the fingerprint's only moving part is the nanosecond mtime — fine on APFS, flaky on a coarse-mtime filesystem. `os.utime(p, ns=(t+1e9, t+1e9))` after the rewrite makes the miss by construction.

#### TE-14 — Forked-build guard: real (M7 → red), but a regression costs the suite 30 s of `SIGALRM` wait and emits the Python 3.14 fork `DeprecationWarning` (W1)
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (M7: `TimeoutError` after 30.23 s)  **Effort:** S
- **Where:** `tests/test_cli.py:196-224`; `src/transport_maps/cli.py:85-95,210-222`.
- **Why:** The guard is meaningful: with `GateFailure` reverted to `SystemExit` the pool hangs and the alarm fires. Two `DeprecationWarning: This process is multi-threaded, use of fork()` per gate run (three under the mutation) come from this one test; `signal.alarm` is POSIX-main-thread-only. Halve the alarm (the happy path takes < 1 s) and add a per-test `@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")` quoting the W1 plan entry, or move to `forkserver` as the plan's exit criterion says.

#### TE-15 — `test_index_json_advertises_rail_detail` pins a literal; `write_index`'s key set has no parity test with what `app.js` reads
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed by reading  **Effort:** S
- **Where:** `tests/emit/test_index.py:76-80`; `src/transport_maps/emit/index.py:120-140`; `web/app.js:55-67,125,216`.
- **Why:** The test asserts `["railDetail"] is True` — it fails only if the key is deleted, which is fine, but the keys the page consumes (`unreachable`, `hoverRes`, `solveRes`, `fineRes`, `modeDetail`, `hoverCellsUrl`, `bandEdgesMin`, `attribution`, `origins`) are asserted nowhere; `app.js` has a fallback for each so a dropped key degrades silently (C12 shape). Fold into the TE-3 constants-parity test: assert `set(payload) ⊇ {keys app.js reads}` by grepping `meta\.(\w+)` from `app.js`.

#### TE-16 — Heavy fixtures are still unmarked integration (F4a, scheduled this cycle, not landed)
- **Severity:** Low (High in aggregate as F4)  **Confidence:** High  **Status:** Confirmed by reading  **Effort:** S
- One line, no new evidence beyond §1: four separate module-scoped `build_index()` fixtures (`test_build`, `test_ground`, `test_nodes` ×2 with the abort test, `test_roads`) plus `test_golden`; `test_landmask`'s `set()` of 4,091,715 ids; `test_no_land_cell_is_left_without_a_country` runs `cell_country` (STRtree + `_fill_blanks` Python loop) over the full universe. These were excluded from every run here.

#### TE-17 — Golden bounds (B3) and the Antarctica-counting reachability threshold (c1 TE-19) unchanged
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed by reading  **Effort:** S
- `tests/test_golden.py:31-49`: `120 < Tokyo < 720`, `London < 2880`, `isfinite().mean() > 0.90` (counts Antarctica, unlike `validate.check_coverage`). Cycle 3 per the plan; no new evidence.

#### TE-18 — `test_tiles.py` still needs tippecanoe with no skip and does not check the layer name (c1 TE-24)
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed by reading  **Effort:** S
- `tests/emit/test_tiles.py:15-19`; tippecanoe is at `/opt/homebrew/bin/tippecanoe` on this host so it passed here. Add `pytest.skip` when `shutil.which("tippecanoe") is None` and read the PMTiles metadata `vector_layers[0].id == tiles.LAYER`.

Still open from cycle 1 with no new evidence (one line each, aggregate IDs): **F10** graph edge builders `_air_edges`/`_access_edges`/`_transfer_edges`/`_rail_edges` border rules untested at unit level (`build.py:46-275`); **F13** c1 TE-18 (implied connectivity assertion, graph built twice in `test_build`), TE-19, TE-20 (`test_ramps` `>= 6` guard, 12 of 12 parse), TE-26 (44 s+ tests for a two-airport bound); **G1** `routes.parquet` bare `.exists()` and `urban_mask` key (folded into TE-7); **J4** no injection seams (tests monkeypatch module attributes, as every stub here does).

---

## 4. Vacuity audit

Every test file changed since `ac191db` (`git diff --stat`: 21 files), plus the cycle-1 tests
the plan claims were shown red (F1a, F1b, F2, F12, A3, A4, A5, A8), plus
`test_cache_provenance.py`. "Ran" means the mutation was executed in the scratchpad against
HEAD; "Reasoned" means judged from the code because the test needs a graph build or the
mutation is not cheap.

| Test (file:lines) | Guard | Named mutation | Expected | Observed | Verdict |
|---|---|---|---|---|---|
| `test_bands.py::test_a_split_cell_is_painted…` (231-281) — **F12** | parent hexagon in slowest child's band | M8: `parent_band` init `int64.max` + `np.minimum.at` (paint in fastest) | red | **red** (1.06 s) | Real |
| `test_bands.py` other 12 | LODs, order, antimeridian, fringe, unreachable | c1 control `band_of → bisect_right` | red | red (c1) | Real |
| `test_hover.py::test_parent_reports_its_centre_child…`, `…split_centre…` (51-81) — **F2** | centre child, not min | M1: `picked[p] = best_pos[p]` | red | **red ×2** | Real (was vacuous at c1) |
| `test_hover.py::…water_falls_back…` (62-67) | fallback | M1 | green (fallback unchanged) | green | Real by construction |
| `test_hover.py::…uint16…`, sentinel, clamp | layout | `astype("<u4")` / drop `np.minimum` | red | Reasoned | Real |
| `test_index.py::test_index_json_advertises_rail_detail` (76-80) | key present | delete `"railDetail"` | red (`KeyError`) | Reasoned | Real but literal (TE-15) |
| `test_index.py::test_readme_documents_the_same_sources` (83-90) — **F1c/E2** | README parity | delete a README row | red | Reasoned (green at HEAD, both rows present) | Real |
| `test_itinerary.py::test_written_array…` (52-71) | byte count | M1 (child choice) | *should* be red for the contract | **green** | Vacuous for child agreement (TE-2) |
| `test_itinerary.py` chain tests (17-49) | last-arrival propagation | `last[node] = -1` instead of `last[prev]` | red | Reasoned | Real |
| `test_modes.py` (30-73) | mode attribution | M19: `ROAD_CHANNEL` swap | *should* be red | **green ×4** | Vacuous for the mapping (TE-6) |
| `test_modes.py::test_road_and_ferry…` | adjacency | `ground_adjacent → True` | red (`acc[2][1]`) | Reasoned | Real |
| `test_rail_detail.py::test_lookup_tables_are_plain_dicts…` (40-51, new at HEAD) | plain dicts | return the polars frame | red (`isinstance`) | Reasoned | Real, shallow |
| `test_rail_detail.py` — `write_rail_detail` | — | any | — | no test | Gap (TE-2) |
| `test_build.py::test_neighbouring_land_cells_are_connected` (61-67) — **F1b** | Seoul cell via `cell_at` | `cell_at` returns base for split cells | red (`KeyError`) | Reasoned; needs graph | Real — needs manual validation |
| `test_ferry.py::…fine_cell_and_its_adjacent_base_cell_is_skipped` (159-176) — **A4** | mixed-grid adjacency | M6: base-parent comparison | green (still skipped) | green | Real by construction (pairs with next row) |
| `test_ferry.py::…is_kept_on_the_mixed_grid` (179-194) — **A4** | far child is a real crossing | M6 | red | **red** | Real |
| `test_ferry.py` sealed/zone (102-131) | `_ferry_edges` border rules | drop `is_closed` in `_ferry_edges` | red | Reasoned | Real |
| `test_ground.py::test_roadless_terrain…` (24-30) | `cell_at` resolution | literal `5` | red | Reasoned; needs graph | Real — needs manual validation |
| `test_rail_integration.py::_index` keyword fix (28-39) | station maps by keyword | pass positionally | red (`KeyError`) | Reasoned | Real |
| `test_refine.py::test_base_values_carry_down_to_children` (30-42) — **F6** | carry-down | M2: zero-fill children | *should* be red | **green** (5 passed) | **Vacuous** (TE-5) |
| `test_refine.py::test_ground_adjacency_is_judged…` (45-66, new) | mixed adjacency | M6 | red | **red** | Real |
| `test_refine.py::test_an_airport_off_the_mask_snaps…` (69-78, new at HEAD) | nearest within two rings | M9a first-found / M9b three rings | red / red | **green / red** | Half vacuous (TE-10) |
| `test_transfers.py` | — | (deletion of dead-constant test only) | — | — | n/a |
| `test_countries.py::test_the_inter_korean_border…` (31-51) — **F3** | eastern DMZ cut | M5: delete `is_closed` in `hex_edges` | red | **green** | **Vacuous** (TE-1) |
| `test_countries.py::test_the_western_dmz_is_cut_too` (105-116) | western DMZ cut | M5 | red | **red** | Real |
| `test_countries.py::…costs_a_crossing` (54-74) | SG→MY charge | drop `extra[m] = crossing_min` | red (7 min < 33) | Reasoned | Real |
| `test_countries.py::test_a_schengen_border_costs_nothing_extra` (77-88) | no charge inside a zone | `immigration_zone("CH") → "CH"` | red only if the `if` holds | Reasoned (guard true today) | Conditionally vacuous (TE-1) |
| `test_landmask.py::test_cell_count_matches_measured_baseline` (14-28) — **F1a** | per-res bound | `land_cells` returns the res-5 list under `SOLVE_RES=6` | red | Reasoned (fixture too heavy to run here) | Real; ±7 % window |
| `test_landmask.py::test_islands_survive_a_cache_free_run` (58-79) | `contain="overlap"` | `contain="center"` | red | Reasoned | Real |
| `test_osm.py` | (import removal only) | — | — | — | n/a; TE-13 fragility |
| `test_urban.py::test_places_reads_the_archive_it_downloaded` (96-126) — **A5** | own download | call `emit.places._download()` | red (`TypeError`) | Reasoned | Real |
| `test_urban.py::test_urban_mask_cache_key_includes_the_source_archive` (129-138) | key covers `PLACES_URL` | M10 | red | **red** | Real (but see TE-7: cell list not covered) |
| `test_cli.py::test_a_gate_failure_in_a_forked_worker_aborts_the_run` (196-224) — **A3** | worker failure reaches parent | M7: `GateFailure → SystemExit` | red | **red** (`TimeoutError`, 30.23 s) | Real (TE-14 cost) |
| `test_cli.py` serial sequencing (115-194) | index.json ordering | write index before the loop | red | Reasoned | Real; unstubbed rail path (TE-9) |
| `test_golden.py::_minutes_at` (26-28) | `cell_at` | literal res | red | Reasoned; needs graph | Real — needs manual validation (B3 loose) |
| `test_validate.py::test_an_all_excluded_universe…` (251-265) — **A8** | NaN → 0 | M3: delete the guard | red | **red** | Real |
| `test_validate.py::test_the_gate_keys_on_the_largest_component…` (211-226) | largest component | M16: first airport's component | red | **red** | Real |
| `test_validate.py::test_a_hole_between_bands_is_rejected` (69-78) | vertex gap | buffer back to 0.0005 | green (hole inside the 3 % pull-in) | Reasoned | Real (the 0.004 change made it so) |
| `test_cache_provenance.py` roads (37-65) | `DENSITY_THRESHOLD` in stamp; stamped path read | M4a / M4b | red / red | **red ×2 / red ×2** | Real |
| `test_cache_provenance.py` airports (71-94) | `SIZE_BY_TYPE`, columns; stamped path read | M14 | red | **red ×2** | Real |
| `test_cache_provenance.py` landmask (100-117) | res, `ANTARCTICA_MAX_LAT`; stamped path read | M13 | red | **red ×2** | Real |
| `test_cache_provenance.py::test_every_stamped_path_carries_a_hash` (120-130) | a hash is present | M4b constant `"deadbeef"` | red | **green** | Weak (redundant, TE-7) |
| `test_cache_provenance.py::…readable_by_other_users` (133-149) | chmod after mkstemp | M12: delete `os.chmod` | red | **red** | Real under umask 022 (TE-12) |
| `test_cache_provenance.py` `_params_hash` (20-31) | stability, order, `1 vs 1.0` | `json.dumps(values)` without `sort_keys` | red | Reasoned | Real |

---

## 5. Side effects, flakiness, ordering

- **Writes into the repository** during `uv run pytest`: listed per test in TE-8 (`data/cache/{rail_routes,ferry_links,cell_country,urban_mask}-*.parquet`). Nothing writes under `dist/`; `data/build` receives files only on a cold cache (`land_cells_r*`, `airports_*`, `road_class_grid_*`, `render-grid-*`, `native-edges-*` — 14 present). `.pytest_cache` and `__pycache__` are written into the tree by default (I ran with `-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE=1`).
- **Network without a skip** (cold cache): `landmask._download` ×3, `roads._ensure_raster` ×5, `airports._download`, `countries._download`, `urban._download`, `places._download` ×3 — reachable from `test_landmask`, `test_roads`, `test_airports`, `test_countries`, `test_urban`, `test_ferry`, `test_validate`, `test_modes`, every `build_index` fixture. Only the three `wikidata` tests are marked `network`.
- **External binaries without a skip**: `tippecanoe` (`test_tiles.py`); `sys.executable` (`test_entrypoint.py`, fine under `uv run`).
- **Time bounds**: `signal.alarm(30)` in the forked test (TE-14); `timeout=120` on the entrypoint subprocesses. No wall-clock assertions; `wikidata.time.sleep` is stubbed.
- **Forked pool**: one test forks the pytest process (2 `DeprecationWarning`s per run, W1). Under fork, `monkeypatch` state is inherited by the children and restored only in the parent — correct here because the children never write back.
- **Module-level caches / ordering**: `roads._grid_cache` is monkeypatched with correct LIFO restore in `test_cache_provenance.py:50-65` (verified). `countries.A3_TO_A2` fills on first `_polygons()` and is never reset: harmless today, but a test that redirects `CACHE` *before* the first `iso2` call would trigger a download; put the archive copy in the conftest fixture (TE-8). `config.CACHE`/`BUILD` are monkeypatched per test in `test_routes`, `test_wikidata`, `test_urban`, `test_cache_provenance`, `test_landmask`, `test_grid` and left real elsewhere — the inconsistency TE-8 removes. `test_ramps.py` mutates `sys.path` for the session (TE-11).
- **Dict/set ordering**: `set(zip(r, c))` comparisons in `test_ferry` and `_ferry_edges`' `best` dict are order-safe; `rail_detail._line_between` uses `maintain_order=True`. No hazard found.
- **mtime-keyed caches**: `osm.rail_routes`/`ferry_links` (TE-13).
- **Reads of live build artefacts**: `test_licence_firewall.py` scans `dist/` — during the running rebuild it reads files mid-write; a partial JSON still cannot contain a forbidden token, so it is not flaky, but it is slow on a 553-origin dist (every `routes.json`).

---

## 6. Tests worth writing for the page (item 5 of the brief)

Evidence: `scratchpad/app_pure.test.mjs` — `node --test`, 4 tests, 66 ms, extracting `esc`,
`fmtTime` and `cellIndex` from `web/app.js` by regex (no bundler, no browser). What can be
tested without a browser, in order of value:

1. **Constants parity** (Python, 20 lines): `names` (`app.js:610`) vs `modes.CHANNELS`; `NO_AIRPORT`/`NO_RAIL` vs `itinerary.NO_AIRPORT`/`rail_detail.NO_RAIL`; `UNREACHABLE_BAND` vs `bands.UNREACHABLE_BAND`; `"source-layer": "bands"` vs `tiles.LAYER`; `airports.json` `fields` order vs `a[0..5]`; `meta.<key>` reads vs `write_index` keys. Mutation: change any one side.
2. **Legend ticks** (Python port of `paintScale`): with `config.BAND_EDGES_MIN`, ticks at indices `[5, 10, 14, 19, 24, 27, 32, 35]`, labels `1, 2.1, 3.8, 7.8, 15.9, 24.5, 50.3, 72+`, positions `(i+1)/37`. Mutation: evenly spaced `i/N` or nearest-round-hour labelling (the C4 bug) → red.
3. **`fmtTime`** boundaries (0, 59, 60, 125, 2879, 2880, 65534, 65535, null) and the `119.6 → "1 h 60m"` seam (fix: compute `m` first and carry into `h`).
4. **`cellIndex`/`lookup`/`legsTo` round trip**: write `hover_cells.bin`, `.bin`, `.air.bin`, `routes.json` from a Python fixture (`index.write_hover_cells`, `hover.write_hover`, `itinerary.write_itinerary`, `routes_json.write_routes`), then decode in Node with the extracted functions (or a Python port of the `airports + count + ordinal` arithmetic) and assert the chain names the fixture's airports. This is the pipeline↔page contract (J1) as a test.
5. **`esc`** on the five characters; `bandRangeAt`'s label formatting (`lo`/`hi` from `EDGES`) as a pure function once the `queryRenderedFeatures` call is split out.
6. **`expandRamp`** to 37 bands: strictly decreasing OKLab L for every scheme (c1 TE-20/D20).

Harness shape: keep `web/tests/app_pure.test.mjs` in the repo, run from
`tests/web/test_app_pure.py` via `subprocess.run(["node", "--test", …], check=True)` with a
visible `pytest.skip` when `node` is absent; the constants and tick tests need no Node.

---

## 7. Final sweep

- **pytest config** (`pyproject.toml:37-44`): markers `network`, `real_multi_band` registered; `addopts = "-m 'not network and not real_multi_band'"` deselects exactly 4 of 258; no `testpaths`, no `filterwarnings`, no `import-mode`, no `--strict-markers` (an unregistered marker typo would pass silently — add `--strict-markers`). `integration` (F4a) not registered.
- **Package layout**: `__init__.py` present in `calibrate/ cli/ contour/ emit/ graph/ solve/ sources/ web/`; **absent in `tests/`** (TE-11). No `conftest.py` anywhere; no shared fixtures, so the four `build_index()` module fixtures cannot share one index.
- **`tmp_path`**: used correctly wherever files are written by a test; the exceptions are the derived caches keyed under `config.CACHE` (TE-8).
- **Warnings**: 2 per gate run (fork, W1). `-W error` is not set, so they are cosmetic today.
- **Every test file was read in full**: the 38 non-empty files in §1 plus the seven empty `__init__.py`; nothing was sampled. Every production module under `src/transport_maps/` was read in full this cycle except `sources/routes.py` and `sources/wikidata.py`, which I did **not** read beyond a grep confirming the cache checks at HEAD (`routes.py:242-243` — `out = config.BUILD / "routes.parquet"; if out.exists():` with no stamp; `wikidata.py:161,186` — fixed-name `wikidata_iata.json`); their tests were read in full, and everything else said about them comes from the cycle-1 review. Scripts other than the three named below were not re-read this cycle. Scripts read in full: `deploy_verify.sh`, `browser_verify.sh`, `check_ramps.py`. `web/app.js` read for lines 1-230 and 529-700 (constants, ramps, legend, `fmtTime`, `cellIndex`, `lookup`, `legsTo`, `renderLegs`, `bandRangeAt`) plus a grep of the remainder; `web/index.html` grepped for the city-count copy only.
- **Experiments run** (all in the scratchpad, tree untouched): baseline over 206 tests; 17 mutation specs (M1–M4b, M5–M10, M12–M14, M16, M19; M7 separately with its alarm); pure-h3 DMZ adjacency and tick-placement ports; the Node harness; a read-only timing of the unstubbed rail path (parquet for the current fingerprint existed, so nothing was written).
