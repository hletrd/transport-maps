# Code review — cycle 2 (code-reviewer, prefix CR)

Reviewed: `feat/transport-pipeline` at `bf9e5cc80f06d29b6609d974bef98ac38d8d11f9` (working tree clean).
Angle: code quality, logic bugs, edge cases, error handling, invariants, data flow across
pipeline ↔ page ↔ scripts. Read-only: no source file, `dist/` or `data/` was touched; the
two measurement scripts ran from the scratchpad and wrote nothing.

Gate evidence gathered (light selections only, per the CPU constraint):

| Check | Result |
|---|---|
| `uv run ruff check .` | **2 errors** (F401, RUF007, both `src/transport_maps/emit/rail_detail.py`) — regression from bf9e5cc; the cycle-1 report recorded ruff clean |
| `uv run pytest -q tests/test_cli.py tests/graph/test_ferry.py tests/test_validate.py tests/emit/test_hover.py tests/graph/test_refine.py tests/sources/test_urban.py -k "not urban_cell and not factor and not roadless and not cities_are_marked"` | 47 passed, 4 deselected, 44 s (includes the forked-worker abort test) |
| Read-only measurement of the bf9e5cc airport snap against `land_cells_r6_dd95e3b5.parquet` + the cached GRIP4 grid + the NE places zip | 58 airports have an off-mask res-6 cell; **6 are still dropped although a split neighbour is within two rings; 9 are snapped 4–13 km away when a fine cell 1–6 km away exists** (CR-1) |
| Read-only check of every `data/origins.toml` origin against the land mask | all 553 base cells are on the mask (no `origin_node` ValueError waiting in the running build) |
| Rail stations without a land cell (largest `rail_routes-*.parquet`, 57,286 stations) | 5 dropped (0.0 %) — station snapping is not needed |

## Inventory (every file read in full unless noted)

Pipeline: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/{__init__,cli,config,validate}.py`,
`graph/{__init__,air,build,ground,nodes,rail,refine,transfers}.py`,
`emit/{__init__,airports_json,borders,hover,index,itinerary,modes,places,rail_detail,routes_json,tiles,water}.py`,
`contour/{__init__,bands,grid}.py`, `solve/dijkstra.py`,
`sources/{__init__,_utils,airports,countries,landmask,osm,roads,routes,urban,wikidata}.py`
(`calibrate/{fit,ground}.py` skimmed: calibration-only, not on the build path).
Scripts: `scripts/{adsb_extract,build_water_tiles,calibrate_ground,check_ramps,expand_origins,ground_check}.py`,
`scripts/{browser_verify,deploy_verify,osm_rail}.sh`.
Page: `web/app.js` (all 1,126 lines), `web/index.html` (head, body, small-screen CSS; the desktop
CSS block at lines 120–300 was grepped for policy items only — the designer's angle),
`web/llms.txt`, `web/README.md`, `web/vendor/fonts.css`.
Config/deploy/docs: `calibration.toml`, `pyproject.toml`, `data/origins.toml` (head + counts),
`deploy/{README.md,worldmap.atik.kr.conf,worldmap-security-headers.conf}`, `README.md`,
`plan/*.md`, `.context/reviews/cycle-1/_aggregate.md`, `docs/superpowers/*` (status lines only, E10).
Tests read for behaviour claims: `tests/test_cli.py`, `tests/graph/{test_ferry,test_refine}.py`,
`tests/emit/{test_hover,test_rail_detail}.py`, `tests/sources/test_cache_provenance.py` (head),
`tests/test_validate.py` (names).
Not reviewed: `web/vendor/{maplibre-gl,pmtiles,h3}.js` bundles (excluded by the brief).

---

## Findings

### High

#### CR-1 — bf9e5cc's airport snap cannot see split neighbours: 6 airports still dropped, 9 snapped to the wrong cell
- Severity **High** · Confidence **High** · Status **Confirmed (measured)** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/nodes.py:114-128` (`_nearest_land`), `:154-171` (call site); test `/Users/hletrd/flash-shared/transport-maps/tests/graph/test_refine.py:69-78`
- Why: `_nearest_land` walks `h3.grid_ring(cell, 1|2)` at the airport cell's own resolution and looks each neighbour up in `cell_pos`. `cell_pos` holds unsplit base cells and the res-7 *children* of split cells (`refine.refine`, `nodes.py:139-142`), never a split base cell's own id — so every neighbour that is dense (exactly the coast of a city, where reclaimed-land airports are) is invisible to the search. An off-mask cell is never itself split (`dense_mask` runs over land cells only), so the call is always made with a res-6 cell and the blind spot always applies.
- Measured against the real caches: of the 58 off-mask airports, **DPL, HLE, KKJ (Kitakyushu), PTF, WLS, WSZ are dropped** although a fine land cell lies 1.3–7.9 km away; **BOO (11.2 km instead of 1.1), BYW, DUT, FRO, INQ, NRL (10.2 vs 2.0), PPW, SIT (9.5 vs 1.3), USH (Ushuaia, 13.4 vs 2.2)** are wired to a farther unsplit cell. The commit message's "snaps to the nearest indexed cell within two rings" is untrue for 15 of 58. The docstring's "a few kilometres" is also wrong: two rings at res 6 reach ~13 km.
- Failure scenario: Kitakyushu's airport is absent from the graph, so every journey to northern Kyushu is routed through FUK plus 60–90 minutes of ground; Ushuaia's access edge starts 13 km outside town. Neither trips any gate (18 dropped of 4,008 is under the 2 % bound) and the INFO line that would say "snapped … dropped …" is never printed (CR-4). The rebuild running now bakes this in.
- The regression test is weak under the CLAUDE.md rule: `ring2[pos] in ring2` is tautological and there is no split-neighbour case, so the current code passes it.
- Fix: give `_nearest_land` the split set (or `idx`-style `cell_at`): for a ring neighbour absent from `cell_pos`, if it is a split base cell, consider its `h3.cell_to_children(n, FINE_RES)` as candidates (nearest by distance). Add a test whose fixture has a split ring-1 neighbour and an unsplit ring-2 neighbour and asserts the fine child wins; mutate back to the current code and confirm it goes red. Needs a rebuild to take effect.

#### CR-2 — `tiles.write_pmtiles` is a cross-filesystem copy, not an atomic rename; a killed worker leaves a truncated `.pmtiles` that the deploy gate accepts
- Severity **High** · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/tiles.py:28-38,68-75`; `/Users/hletrd/flash-shared/transport-maps/scripts/deploy_verify.sh:26-27`
- Why: the file is staged in the (local) system temp directory precisely because the repo lives on NFS, so `shutil.move(staged, out)` is always a copy + unlink, never a rename — the code's own comment says so. `cli._build_all` terminates sibling workers on the first `GateFailure` (`Pool.__exit__`), and `deploy_verify.sh` checks the pmtiles only with `.exists()`.
- Failure scenario: worker B is 40 % through copying `paris.pmtiles` when worker A's origin fails coverage; B is SIGTERMed; `dist/origins/paris.pmtiles` is a 1.5 MB prefix of a 3.8 MB archive; the next deploy passes step 1 and ships it; the page shows a blank or half-tiled globe for Paris with only a pmtiles.js range error in the console.
- This corrects the premise of plan task A6a ("`tiles.py` already moves atomically — verify") — it does not.
- Fix: copy the staged archive into a same-directory temp file and `os.replace` it — i.e. `_atomic_write(out, lambda tmp: shutil.copyfile(staged, tmp))` — and have `deploy_verify.sh` sanity-check each pmtiles header (magic `PMTiles`, byte 7 = version) or at least a minimum size.

### Medium

#### CR-3 — ruff is red again: bf9e5cc left an unused `pairwise` import and the `zip(st, st[1:])` it replaced
- Severity **Medium** (gate) · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/rail_detail.py:12,55`
- Why: F14 was closed in a3f918f with "`uv run ruff check .` exits 0"; the unreviewed commit reverted `pairwise(st)` to `zip(st, st[1:])` (RUF007) while keeping the import (F401). Nothing gates on ruff, so it regressed silently within hours.
- Fix: `for a, b in pairwise(st)`; add `uv run ruff check .` to the pre-commit/CI step the gates plan lists.

#### CR-4 — Logging is never configured, so every `logger.info` diagnostic the pipeline relies on is silently discarded
- Severity **Medium** · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:234-297` (no `logging.basicConfig` anywhere in `src/` or `scripts/`); INFO sites at `graph/nodes.py:140-141,176-177,213-214`, `graph/ground.py:132-136`, `graph/build.py:261-262,319-320`
- Why: with no handler installed, Python's last-resort handler prints WARNING and above only. The messages the code says it "reports rather than assumes" — how many base cells were split, how many stations were dropped, which airports were snapped (CR-1), how many ground/rail/ferry edges were cut at closed borders, how many crossings were charged — never appear in the build output. Only the two WARNINGs (`_air_edges` unknown pairs, dropped airports) do.
- Failure scenario: a land-mask regression drops 1.9 % of airports (under the bound) and snaps 300 more; the run prints one warning about the dropped ones and nothing about the snapped ones; the split count that would show a broken urban mask (0 cells split) is never seen.
- Fix: `logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")` in `main()` (workers inherit it through fork); or turn the load-bearing INFO lines into `print`s like the rail/ferry inclusion lines.

#### CR-5 — City search does no diacritic folding and origins carry no ASCII alias: "Sao Paulo", "Zurich", "Bogota", "Mosul" match nothing
- Severity **Medium** (ease of use) · Confidence **High** · Status **Confirmed** · Effort **S** (fold) / **M** (aliases)
- `/Users/hletrd/flash-shared/transport-maps/web/app.js:825-829` (`render`: `c.name.toLowerCase().includes(f)`), `:968-980` (Enter falls through to Nominatim); `/Users/hletrd/flash-shared/transport-maps/scripts/expand_origins.py:84-91` (has `r["ascii"]`, writes only `name`)
- Why: 30 of the 553 origin names are non-ASCII (`São Paulo`, `Bogotá`, `Zürich`-style, `Ürümqi`, `İzmir`, `Al Mawşil al Jadīdah` for Mosul). A visitor types what they can type; nothing matches; Enter then runs an *address* search and the first result sets a **destination**, not a departure — the opposite of what the hint "Enter departs from the first city match" promises.
- Fix: normalise both sides with `s.normalize("NFD").replace(/\p{M}/gu, "")` (and fold `ı/İ`) in `render()`; longer term ship an `alt` (GeoNames `asciiname`, e.g. "Mosul") per origin through `origins.toml` → `index.json` and match on it too.

#### CR-6 — `browser_verify.sh`'s "borders" assertion is vacuous: it checks that the map canvas exists, not that the borders layer rendered
- Severity **Medium** (a gate that cannot fail) · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/scripts/browser_verify.sh:26,31`
- Why: `borders:!!q(".maplibregl-canvas")` is true whenever the map exists; the message "no map canvas for the borders layer" would never print for a missing `borders.json` or a failed `addLayer`. FD-5 was ticked on the strength of this line.
- Fix: `borders: !!m.getLayer("borders") && m.queryRenderedFeatures({layers:["borders"]}).length > 0` after a `jumpTo` over a land border (the zoom-3 Korea view already used later is fine).

#### CR-7 — `deploy_verify.sh` never checks the per-origin routes file or the rail JSON, so a route-less origin deploys clean
- Severity **Medium** · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/scripts/deploy_verify.sh:16-27`
- Why: the gate lists `.bin/.air.bin/.modes.bin/.rail.bin/.pmtiles`; `{slug}.json` (the only thing `legsTo` can walk) and `{slug}.rail.json` (required whenever `.rail.bin` exists, `app.js:483-488`) are not checked, nor is `index.json`'s `railDetail: true` reconciled with the files. `_solve_one` writes the pmtiles first and the JSONs last, so an interrupted origin is exactly one with a pmtiles and no `.json`.
- Failure scenario: an origin whose `.json` is missing renders every flight journey as "No flight on this route — surface travel" (`app.js:618-625`) with no console error.
- Fix: add `(".json", None)` and the `.rail.json` pair to the loop; parse each JSON; fail when `railDetail` is advertised and any origin lacks the pair.

#### CR-8 — `mode_detail()` ships "a city over 200,000.0" in every road tooltip
- Severity **Low/Medium** (user-visible copy in every route) · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/index.py:108` — `f"{urban.URBAN_POP_MIN:,}"` with `URBAN_POP_MIN = 200_000.0` prints `200,000.0` (verified). The three road tooltips on the page read "halved inside cities (within 40 km of a city over 200,000.0)". Also part of B2: the rail and ferry sentences hard-code 200/75/35/30 rather than reading `calibration.toml`.
- Fix: `:,.0f`; read the rail/ferry figures from the calibration objects (B2, cycle 2).

### Low

#### CR-9 — E9 was ticked but res-5 / "Task 9" language survives in five modules
- Severity **Low** · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/tiles.py:12` ("H3 res-5 hexes (~8.5 km edge)"), `graph/build.py:380` ("Task 9's future station edges" — rail exists), `graph/ground.py:55`, `sources/roads.py:100`, `sources/countries.py:91` ("at resolution 5 is about 8 km"), `validate.py:134` ("157 times in a full build"). Cell-size figures also disagree *between the page's own two documents*: `web/index.html:46` (JSON-LD) says 5.6 km / 2.1 km, `web/llms.txt:26-27` and `config.py:12-16` say 6.5 km / 2.4 km (the h3 v4 values); `contour/bands.py:148-155` and `graph/refine.py:3-7` use the old figures. E8 (cycle 2) covers the numbers; the JSON-LD/llms.txt split is new evidence.

#### CR-10 — Every origin switch flies back to zoom 1.9, even from a label clicked at zoom 6
- Severity **Low** (ease of use) · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/web/app.js:521` (`moveTo({center, zoom: 1.9, …})` unconditionally in `paintOrigin`)
- Why: the "click a city name on the globe to depart" and "Depart from X" paths are used while zoomed in on a region; both yank the viewer out to the world view and lose the place they were reading. Fix: keep the current zoom when it exceeds 1.9 and the new origin is on the near side (`onNearSide`), or only recentre.

#### CR-11 — Gazetteer labels within 80 km of an origin become "Depart from <origin>" buttons under the *gazetteer's* name
- Severity **Low** (ease of use) · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/web/app.js:244-260` (`originNear(r[3], r[4])`, default 80 km)
- Why: "Incheon", "Suwon", "Yokohama", "Kawasaki" render as buttons that depart from Seoul / Tokyo; the label text says one city, the title and the surface say another. Fix: match by name (or ≤ 15 km) for the button, or render the button text as the origin's name.

#### CR-12 — Clicking open water or an unreachable cell still opens the Route panel and calls Nominatim
- Severity **Low** · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/web/app.js:786-795,921-937`
- Why: `map.on("click")` sets the pin, opens `#route` and fires `reverseGeocode` before knowing whether `lookup()` is `null`; the panel then says "not on land". Nominatim's policy caps at 1 req/s and asks for no needless requests. Fix: return early when `lookup(lat, lng) === null` (say "Open water" in `#where`), and rate-limit reverse geocodes to one in flight.

#### CR-13 — `searchAddress` throws on a non-array Nominatim body and stays silent for queries under three characters
- Severity **Low** · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/web/app.js:876-917`
- Why: a Nominatim error body (`{"error": …}`) passes `r.ok` on some proxies; `hits.length` is `undefined` (falsy → "No address found") and then `for (const h of hits)` throws inside the async function — an unhandled rejection in the console. Pressing "Search address" with "Se" typed does nothing at all (`q.length < 3` returns after removing the previous list). Fix: `Array.isArray(hits) || (hits = [], failed = true)`; show "Type at least three characters".

#### CR-14 — `write_index` accepts zero origins and the page then crashes on `cities[0]`
- Severity **Low** · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/index.py:81-88,120-140`; `/Users/hletrd/flash-shared/transport-maps/web/app.js:1080,1094`
- Why: `load_origins` validates duplicates only; an `origins.toml` with an empty `[[origin]]` list writes a valid `index.json`; `FALLBACK = bySlug.get("seoul") ?? cities[0]` is `undefined` and `paintOrigin(undefined)` throws `Cannot read properties of undefined (reading 'slug')` — the blank-globe class CLAUDE.md's deploy rule is about. Fix: `load_origins` raises on an empty list; `fatal("index.json lists no departure cities")` on the page.

#### CR-15 — `countries.cell_country` and the zone list are derived four times per build (~10 M-cell Python loops each)
- Severity **Low** (perf, parent process only) · Confidence **High** · Status **Confirmed** · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/ground.py:86-88`, `graph/build.py:215-228` (called from `_rail_edges` and `_ferry_edges`), `cli.py:173-175`
- Why: the parquet read is cached, but each call rebuilds the 10 M-entry `zone` array through `countries.iso2()`; four of them cost a couple of minutes and ~1 GB of transient memory in the parent before the fork. Compute once in `_build_all` (it already does) and thread `country`/`zone` into `build_graph`.

#### CR-16 — `osm_rail.sh` keeps every `type=route` relation, not only trains
- Severity **Low** · Confidence **Medium** · Status **Likely** (osmium's comma is OR) · Effort **S**
- `/Users/hletrd/flash-shared/transport-maps/scripts/osm_rail.sh:42-44` — `r/type=route,route=train` matches relations with *either* tag, so bus, hiking, bicycle and road routes (and their referenced nodes/ways) survive the filter. `osm._relations` re-checks both tags, so correctness holds; the extracts are larger than they need to be. Fix: `r/route=train` alone.

#### CR-17 — Test droppings in the real cache have grown to 358 `rail_routes-*` + 45 `cell_country-*` + 26 `ferry_links-*` + 26 `urban_mask-*` parquet files
- Severity **Low** · Confidence **High** · Status **Confirmed** (`ls data/cache`) · Effort **S**
- F4b (gates plan, cycle 2) is still open and every test run adds files, because the fingerprint includes `str(extracts_dir)` (`osm.py:151,180`) which is a fresh `tmp_path` each run; there is no GC (G1). Also worth knowing for the orchestrator: `data/build/routes.parquet` is still a bare-name cache (G1, scheduled), and `dist/origins/las-vegas.pmtiles-journal` is still present (I4, scheduled).

#### CR-18 — Seven orphaned `python -u -m transport_maps.cli build-all` processes from an earlier run are still resident
- Severity **Low** (housekeeping; evidence for A3) · Confidence **High** · Status **Confirmed** (`ps`, PIDs 12633–12639, elapsed ~9 h 55 m, 0 % CPU, ~10 MB RSS each) · Effort **S**
- They predate the console-script invocation of the current build (PIDs 4143–4147) and match the "idle workers whose result never arrived" signature A3 describes. Not killed here (the brief forbids touching processes I did not start); the orchestrator should reap them after the current rebuild.

### Still open from cycle 1, no new evidence (one line each)

- A6a/A6b/A6c/A6d — non-atomic emitters (`hover.py:71-72`, `itinerary.py:70-71`, `modes.py:100-101`, `rail_detail.py:107-110`, `routes_json.py:56-57`, `index.py:98-99,139-140`), eager `hover_cells.bin`, no build identity; CR-2 adds the pmtiles case. Scheduled cycle 2.
- A7 `solve`/`index` subcommands diverge (`cli.py:264-294`). Scheduled.
- A10 unstable secondary key in `osm.rail_routes` (`osm.py:202-207`; polars `sort` is not stable by default). Scheduled.
- A12 ferry drops uncounted (`build.py:292-299`). Scheduled.
- A13 65,534 clamp displays as a duration (`hover.py:23,67-69`, `app.js:534`). Scheduled.
- A14 monotonic gate blind to cross-resolution edges (`validate.py:162-166`). Scheduled.
- A17 slugs unvalidated on the build-all path; `expand_origins.py:97` writes names unescaped. Scheduled.
- B2 calibration provenance and hard-coded figures in `mode_detail()` (see CR-8). Scheduled.
- C1/C2/C3/C5/C8/C13 page data issues — confirmed unchanged in `app.js:458-526` (C5), `564-580` (C1), `618-648` (C2), `417-426` (C3), `1049-1078` (C13); C5 note: the `.bin` failure handler (`app.js:495-499`) also overwrites `#where` for a stale origin, so the generation counter must guard the catch branch too.
- F6 `test_base_values_carry_down_to_children` still cannot tell carry-down from zero-fill (`tests/graph/test_refine.py:30-42`: split cell 0 carries `values[0] == 0`). Scheduled cycle 2.
- F7 the five per-origin emitters still each re-derive `parents` and `_representative_children` (10 M-entry dict ×4 per origin per worker — this is a large share of each worker's 1–2 GB RSS). Scheduled cycle 3 / H2.
- G1 `urban_mask` key (`urban.py:76-77`), `ferry_links` key (`osm.py:151-153`), bare `routes.parquet` (`routes.py:242-244`). Scheduled cycle 2.
- H10 tippecanoe temp files leak on a terminated worker (`tiles.py:28-30`). Scheduled.
- J9 `urban_mask` equirectangular distance ignores the antimeridian (`urban.py:87-88`). Deferred.

---

## Regression check — cycle-1 fixes in this angle marked [x]

| Task | Commit | Verified how | Verdict |
|---|---|---|---|
| A3 forked gate failure aborts | b030d38 | `cli.py:85-95,106-108,219-222` `GateFailure` → `SystemExit`; `test_a_gate_failure_in_a_forked_worker_aborts_the_run` passes (alarm-bounded) | In place |
| A4 ferry vs mixed-grid adjacency | b38fb8b | `refine.ground_adjacent` (`refine.py:66-83`) used by `_ferry_edges` (`build.py:308`) and `modes.py:69`; `tests/graph/test_ferry.py` passes | In place |
| A5 `urban._download` | 599dc60 | `urban.py:43-58` own URL through `_utils`; `test_places_reads_the_archive_it_downloaded` passes | In place |
| A8 NaN coverage | be2cc94 | `validate.py:42-43`; `test_an_all_excluded_universe_has_zero_coverage_not_nan` passes | In place |
| E1 verify half | cea16ca | `browser_verify.sh:11-17` derives counts from `index.json`; `deploy_verify.sh:39-51` grep | In place |
| D14/FD-5 disclaimer + borders | 4d74cbe | `.disclaimer` visibility check is real; **borders check is vacuous** | Partial — CR-6 |
| F14 ruff clean | a3f918f | `uv run ruff check .` → 2 errors after bf9e5cc | **Regressed — CR-3** |
| F2 hover centre-child test | 498b971 | `tests/emit/test_hover.py:9-27,54-60` fixtures at `SOLVE_RES`, asserts 20 not 10 | In place |
| E9 stale comments (Python half) | fa89fbc | `config.py`, `transfers.py`, `__init__.py`, `routes_json.py` clean; five other modules not | Partial — CR-9 |
| C4 legend ticks on true edges | b7da35f | `app.js:178-198`: nearest-edge snap, label = edge value, ≥3-band spacing | In place |
| C6/C7/C9/C10/C12 | b7da35f, f943964, d84217f | `app.js:161-169,552-559,37-52,1097-1126,128-137,483-488` | In place |
| D4/E4 explicit search, Enter, arrows | 1305ba7 | `app.js:965-990`; Nominatim only from Enter-with-no-match or the button | In place |
| D10 reduced motion | f943964 | `app.js:414-415` `moveTo`; compass `easeTo` duration 0 | In place |
| I1 escaping | f943964 | every `innerHTML` site traced: `esc()` on dataset strings (`app.js:31-32,592-600,700,716-720,728`) | In place |
| E3 repo half | 03988a5 | `deploy/worldmap.atik.kr.conf:29,41,45,52,64,72` includes in every location | In place |
| bf9e5cc polars out of workers | bf9e5cc | `rail_detail.lookup_tables` built in the parent (`cli.py:184-185`); worker path touches only dicts; `test_lookup_tables_are_plain_dicts_a_fork_can_use` | In place |
| bf9e5cc airport snap | bf9e5cc | measured against the real caches | **Wrong for 15 of 58 — CR-1** |

## Final sweep

- Index arithmetic: `airport_arr_index = pos + n_air` (`nodes.py:99-101`), `.air.bin` ordinal `node - (n_cells + n_air)` (`itinerary.py:61,68`), page `airports + count + ordinal` with `count = (stations - airports)/2` (`app.js:571-573`) — consistent. Legend tick position `(i+1)/N_BANDS` for upper edge `i` — correct. `band_indices` `searchsorted(side="left")` agrees with `band_of` and with the page's `[EDGES[b-1], EDGES[b]]` range.
- Sentinels: 65535 / 0xFFFF handled on both sides; the 65,534 clamp is A13. `NO_PREDECESSOR = -9999` handled in all four consumers.
- Antimeridian / poles: `_split_at_antimeridian` and `roads.cell_class` wrap guard fine; `urban_mask` (J9) and the south-pole cap (A9) remain as recorded.
- Empty inputs: `_ferry_edges` empty → typed empty arrays; `check_coverage` empty → 0.0; `write_index` empty origins → CR-14.
- Exception swallowing: page's optional fetches swallow by design; `searchAddress` non-array → CR-13; `landmask` BLE001 justified in place.
- Resource leaks: `NamedTemporaryFile` unlinked in `finally` (ok); tippecanoe subprocess/temp on terminate (H10); orphaned processes CR-18.
- Mutable defaults: none (`field(default_factory=…)` throughout).
- Ordering between parallel emitters: all five derive `sorted({cell_to_parent(c, 4)})` identically; still no shared helper or test (F7).
- Logging: no handler anywhere → CR-4.
- Files not reviewed: vendored JS bundles (by brief); `web/index.html` desktop CSS 120–300 grepped only (designer's lane); `docs/superpowers/*` status lines only (E10 already scheduled); `calibrate/*.py` skimmed (off the build path).
