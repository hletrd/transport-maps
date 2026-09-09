# perf-reviewer — cycle 2

Reviewed: `feat/transport-pipeline` at HEAD `bf9e5cc` ("keep polars out of the forked
workers; snap off-mask airports to land"). Files were read from the working tree,
which at fan-out carried another agent's uncommitted G1 edits in
`src/transport_maps/sources/{_utils,airports,landmask,roads}.py` and two new test
files; none of those edits touch a hot path. Read-only review: no source, `dist/` or
`data/` file was written, no process started or stopped other than two short,
niced, single-threaded micro-benchmarks on synthetic cells (50k) in the scratchpad.

Finding IDs: `PR-1` … `PR-20`. Cycle-1 IDs (`H1`–`H14`, `C*`, `D*`) are referenced,
not re-described, except where there is new evidence or the exit criterion in
`plan/deferred.md` has been met.

## Inventory (every file examined)

Pipeline
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py` (304 lines)
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/config.py`, `validate.py`
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/{nodes,ground,build,air,rail,refine,transfers}.py`
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/solve/dijkstra.py`
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/contour/{bands,grid}.py`
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/{tiles,hover,index,itinerary,modes,rail_detail,routes_json,water,places,borders,airports_json}.py`
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/sources/{_utils,airports,countries,landmask,osm,roads,routes,urban,wikidata}.py`
- `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/calibrate/{fit,ground}.py`
- `/Users/hletrd/flash-shared/transport-maps/scripts/{build_water_tiles,check_ramps,expand_origins,ground_check,calibrate_ground,adsb_extract}.py`, `scripts/{deploy_verify,browser_verify,osm_rail}.sh`
- `/Users/hletrd/flash-shared/transport-maps/pyproject.toml`

Page and deploy
- `/Users/hletrd/flash-shared/transport-maps/web/app.js` (1,126 lines), `web/index.html` (479 lines), `web/vendor/fonts.css`, `web/vendor/pmtiles.js` (Protocol/cache code), `web/vendor/maplibre-gl.js` (marker update path only)
- `/Users/hletrd/flash-shared/transport-maps/deploy/worldmap.atik.kr.conf`, `deploy/worldmap-security-headers.conf`, `deploy/README.md`

Artifacts and live state (read-only)
- `dist/index.json`, `dist/hover_cells.bin`, `dist/origins/*` sizes, PMTiles headers and directories of `dist/water.pmtiles`, `dist/origins/seoul.pmtiles`, `dist/origins/sapporo.pmtiles`
- the running build: `/private/tmp/rebuild16.log`, `ps`/`/usr/bin/top`/`vm_stat`/`sysctl vm.swapusage`, tippecanoe temp files under `$TMPDIR`
- the preview server `http://127.0.0.1:8899/` (HEAD per asset) and the live site (`curl` HEAD/GET with `Accept-Encoding: gzip, br` for compressed sizes)

## Evidence snapshot (2026-09-10 04:37–04:53, during the 553-origin rebuild)

Machine: Apple M4, 10 cores, 32 GB. Build: parent PID 94066 started 04:23, five forked
workers (`_worker_cap` = 5) started ~04:28.

| Measure | Value | Source |
|---|---|---|
| Worker footprint (`top` MEM / CMPRS) | 11–12 GB each, of which 7.9–10 GB compressed; parent 5.7 GB, all compressed | `/usr/bin/top -o mem` |
| Worker RSS (`ps`) | 1.0 / 3.8 / 3.7 / 4.0 / 2.7 GB at 9 min into the first origin | `ps -o rss` |
| Swap | 8.0 of 9.2 GB at 04:37 → 10.7 of 12.3 GB at 04:53; swap-outs +600k pages (9.6 GB) in 16 min | `sysctl vm.swapusage`, `vm_stat` |
| Free memory | 79 MB → 60 MB | `vm_stat` |
| Compressor | 3.1–4.1 M pages stored (48–64 GB logical) in 0.8–0.9 M physical pages | `vm_stat` |
| Origins done | 5 at ~04:36, 10 at ~04:46, chengdu writing at 04:53 → ~9 min per round of five | `rebuild16.log`, `dist/origins` mtimes |
| Projected wall-clock at that rate | 553 origins / 5 × 9 min ≈ 16–17 h (the brief assumed 7–8) | arithmetic |
| tippecanoe input per origin | 629–669 MB GeoJSON (res 5 was 91–107 MB) | `$TMPDIR/tmp*.geojson` |
| tippecanoe concurrency | 4 of 5 workers in tippecanoe at 04:53 | `pgrep tippecanoe` |
| Leaked temp files from 9 Sep 21:06 | 5 GeoJSON (91, 105, 106, 107, 31 MB) + 2 staged PMTiles (16 MB each) = ~470 MB | `$TMPDIR` listing |
| Orphaned workers | 8 × `python -u -m transport_maps.cli build-all`, PPID 1, 9 h 50 m old, 0 % CPU, ~10 MB RSS | `ps` |
| Also on the box | a full `pytest` run (PID 15059) at 3.5 GB; Activity Monitor at 8.4 GB | `top` |
| Per-origin PMTiles at res 6/7 | 24.8–29.5 MB (res-5 mean 12.0 MB, max 27.8) | log, `dist/origins` |

Micro-benchmark (50k synthetic res-6 cells, niced, single thread, on the loaded machine — so
upper-bound-ish; the repo's own idle figure for `roads.cell_class` is 8.7 µs/cell):

| Per-item cost | µs | ×10 M cells |
|---|---|---|
| `h3.cell_to_parent` into a set (`hover_cells`) | 0.72 | 7.2 s |
| `{cell: i}` dict build | 0.28 | 2.8 s (plus ~0.8 GB) |
| `h3.cell_to_latlng` list (`check_coverage`) | 0.91 | 9.1 s |
| `bands._crosses_antimeridian` (one call) | 1.97 | 19.7 s |
| `h3.grid_ring(c, 1)` (`hex_edges`) | 5.3 | 53 s |
| `hover._representative_children` (one call) | 1.27 | 12.7 s |
| `roads.cell_class` loop body (per base cell) | 22.4 (repo: 8.7) | 36–92 s per 4.09 M base cells |
| `refine.ground_adjacent` per cell→cell edge (`modes`) | 1.11 | 11 s |
| `bands._dissolve` on contiguous cells | 6.1 (≈4 of it is the antimeridian test ×2) | — |
| `np.maximum.at` over 6n edges (`_slowest_within`) | 0.01 | 0.7 s per 70 M edges (NOT a problem; `reduceat` was no faster) |

## Findings

Severity: H = sets the build's wall-clock or memory today, or user-visible; M = bounded but
real; L = polish. Confidence and Status as requested. Effort S/M/L.

### High

**PR-1 — The band feature collection is held as a Python object tree (~3–4 GB) and round-tripped through a 650 MB GeoJSON file per origin; this is most of each worker's 11–12 GB footprint (H1, exit criterion met)**
Severity H · Confidence H (sizes measured; footprint attribution M) · Status Confirmed · Effort M
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/contour/bands.py:176-194` (`_feature` calls `mapping(geometry)`), `:302-345`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/tiles.py:28-30` (`json.dump` of the whole collection), `:41-61`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/validate.py:104-105` (`shape(f["geometry"])` re-parses every feature).
Why: at res 6/7 the GeoJSON is 629–669 MB per origin (measured on four concurrent workers), i.e. ~30 M coordinate pairs. `mapping()` materialises those as nested tuples of Python floats (~100 B per pair) so the `fc` dict is ~3 GB of small objects that live from `band_feature_collection` through `check_bands_cover` (which re-parses all of it into GEOS a second time, ~1 GB more) to `json.dump`, and pymalloc keeps most of that address space after it is freed. Five workers at 11–12 GB each plus a 5.7 GB parent on a 32 GB machine is why the build is at 10.7 GB of swap with 60 MB free and 9.6 GB of page-outs per 16 minutes; the parent's own pages are entirely compressed. `plan/deferred.md` reopens H1 when "memory pressure aborts a build" — it has not aborted, but it is paging, and paging is why a round of five origins takes ~9 minutes.
Failure scenario: a sixth process of any size (the concurrent `pytest` at 3.5 GB was one) or a larger origin pushes the compressor past its budget; macOS then kills the largest process, which is a worker; `imap` raises, the pool is terminated and ~N hours of `dist/` output is left partial.
Fix: (1) have `bands` return `(band, lod, shapely geometry)` triples and let `tiles.write_pmtiles` stream one feature line at a time with `shapely.to_geojson(geom)` (C-side, no object tree) — `json.dump` of the properties wrapper only; (2) `check_bands_cover` builds its `STRtree` from those geometries directly instead of `shape(f["geometry"])`; (3) `lod_features` filters the triples. Drops ~4–5 GB per worker and the 20–30 s of `json.dump` + re-parse per origin. Pair with PR-3 for the transient dicts.

**PR-2 — `_dissolve` evaluates `_crosses_antimeridian` twice per cell over ~29 M cell-band memberships per origin: ~115 s of the ~480 s per origin (H4 residual; exit criterion "after the res-6/7 contour code settles" met by 47f0baf)**
Severity H · Confidence H (per-call cost measured; membership count is an estimate from the rim rule) · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/contour/bands.py:62-64`, `:120-125`, `:255-259` (native, `keep` per band), `:226-228`, `:287-288`.
Why: 47f0baf fixed two of H4's three items (`_slowest_within` is once per level, `_dissolve` no longer overlays). The third remains: lines 120–121 run the boundary test twice per cell (`normal` and `wrapping` comprehensions), and line 124 runs a Python `get_resolution` loop over the same cells. A cell appears in every band k from its own band to `slowest[c]`, so per origin the native level passes ~1.3 × 10 M cells, the two base levels ~6 M and ~8 M, and the coarse level ~2 M cumulative: ~29 M cells → ~58 M `cell_to_boundary` calls at ~2 µs ≈ 115 s per origin, plus ~10 s of `get_resolution`. Only a few thousand cells on Earth actually wrap.
Failure scenario: none functional; it is ~111 rounds × 115 s ≈ 3.5 h of the projected 16–17 h build, on the critical path of every origin.
Fix: compute once per build, in `_build_all`'s `shared`, a boolean `wraps` for the index cells and for `cells6` (only cells with |lon| > 170° need the boundary test), and a per-cell resolution/`fine` mask that already exists; `_dissolve(cells_arr[keep], wraps[keep], fine[keep])` then partitions with numpy and loops only over the wrapping handful. Test: mutate `wraps` to all-False and assert the Fiji-area band test in `tests/contour/test_bands.py` goes red.

**PR-3 — The hover-cell family recomputes its origin-independent maps four times per origin and rebuilds a 10 M-entry dict that `NodeIndex` already holds: ~80 s and 4 × ~0.8 GB transient per origin (the half of H2 that bf9e5cc did not do)**
Severity H · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/hover.py:26-28`, `:31-56` (line 41 `cell_pos = {c: i for i, c in enumerate(idx.cells)}` duplicates `idx._cell_pos`; lines 45–48 loop 10 M `cell_to_parent`), `:59-65`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/itinerary.py:58`, `:66`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/modes.py:90`, `:96`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/rail_detail.py:86`, `:94`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:118-124`.
Why: each of the four emitters calls `sorted({cell_to_parent(c, 4) …})` (7.2 s) and `_representative_children` (12.7 s, measured 1.27 µs/cell), which builds a fresh 10 M dict (~0.8 GB: the dict table plus 10 M new int objects) and does another 10 M `cell_to_parent`. Only the "fastest child" fallback depends on `minutes`. Four times per origin ≈ 80 s ≈ 2.5 h over the build, and the dict churn (plus the `INCREF` traffic over every `str` in `idx.cells`, which un-shares the copy-on-write pages) is a share of the worker footprint in PR-1.
Failure scenario: as PR-1 (memory) and wall-clock.
Fix: in `_build_all`, compute once into `shared`: `parents` (sorted list), `parent_pos` (int32 per index cell), `centre_pos` (int64 per parent, −1 where the centre child is not indexed — use `idx._cell_pos`, not a new dict). `_representative_children(shared, minutes)` becomes: `best = np.full(P, -1); order = np.lexsort((minutes, parent_pos)); …` or `np.minimum.at` on minutes — ~0.1 s, no dict. Mutation test: replace `centre_pos` by the fastest child and confirm `tests/emit/test_hover.py` (the centre-child fixture from 498b971) goes red.

**PR-4 — `_worker_cap` sizes the pool from a constant that the measured footprint contradicts by 3×; the pool has no memory-aware bound and no per-origin memory log (new evidence on H5)**
Severity H · Confidence H (measurements) / M (that five is the wrong number after PR-1/PR-3 land) · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:62-82`, `:204-218`.
Why: the docstring's model is "each worker's own arrays" plus refcount un-sharing, and picks 5 for >3 M cells so that "eight workers" stay under 32 GB. Measured: 11–12 GB footprint per worker (7.9–10 GB of it compressed) and 5.7 GB in the parent — 62 GB logical for five workers, on a 32 GB machine already running other work. The constant cannot know this, and nothing records `ru_maxrss` per origin so the next build starts from the same guess.
Failure scenario: as PR-1; also the wall-clock cost of paging is invisible in the log, so the build "looks" CPU-bound (workers at 91 % CPU) while 9.6 GB per 16 min is being written to swap.
Fix: (1) print `resource.getrusage(RUSAGE_SELF).ru_maxrss` in the per-origin row so the per-worker peak is a measured number; (2) derive the cap as `max(1, (physical_memory − parent_footprint − headroom) // measured_worker_peak)` with `os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")`, keeping `5` only as the ceiling; (3) land PR-1 and PR-3 first — with them the peak falls to ~3–4 GB and 5–8 workers become correct rather than accidental.

### Medium

**PR-5 — Origin-independent inputs are recomputed in the serial phase before the fork: `roads.cell_class` 4×, `cell_speed_kmh` 2×, `cell_country` + `zone` 4×**
Severity M · Confidence H (call graph) / M (seconds) · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/nodes.py:138`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/ground.py:37-44`, `:53-59`, `:80`, `:86-88`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/build.py:215-228`, `:250`, `:285`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:169-176`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/sources/roads.py:97-133`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/sources/countries.py:85-99`.
Why: `roads.cell_class(base_cells)` is a 4.09 M-iteration Python loop with an `h3.cell_to_boundary` and a raster window per cell (repo's own figure 8.7 µs/cell ≈ 36 s; 22 µs on the loaded box) with no memo on the cell list; it runs in `build_index`, in `hex_edges → cell_speed_kmh → cell_class`, again for `speeds` in `_build_all` (the comment there says "computed once"), and again for `shared["cell_class"]`. `cell_country` is a parquet cache hit each time but each hit materialises a 10 M-string object array (~600 MB) and is followed by a 10 M-iteration `zone` comprehension (~5 s): in `_build_all`, `hex_edges`, `_rail_edges` and `_ferry_edges` (the last two via `_border_rules`). Roughly 2–3 min of the ~5 min serial phase and ~2.4 GB of transient churn in the parent, all on the critical path.
Fix: compute `cell_class`, `speeds`, `country`, `zone` once in `_build_all` (or memoise on `id(idx)` inside `ground`), pass them into `build_graph(idx, …, country=, zone=, speeds=)`; this is also the injection seam J4 wants.

**PR-6 — Forked pool workers outlive a killed parent indefinitely (8 orphans from the previous, deadlocked run are still alive after 9 h 50 m)**
Severity M · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:210-218` (no `initializer`, no parent-death check).
Why: `multiprocessing.Pool` workers only die with the parent on a clean exit; after a SIGKILL (or the OS memory killer, PR-1) they sit blocked forever with PPID 1. The eight here are the "eight idle processes" of the polars deadlock the bf9e5cc message describes; they are small now only because they never touched anything, but a worker killed mid-origin would keep its multi-GB private pages and a partly written `dist/origins/{slug}.*`. A second `build-all` can start alongside them (nothing detects a running build).
Fix: `Pool(workers, initializer=_watch_parent)` where the initializer starts a daemon thread that calls `os._exit(1)` when `os.getppid()` changes (macOS has no `PR_SET_PDEATHSIG`); write a lock file (`dist/.build.lock` with the parent PID, `fcntl.flock`) so a concurrent build refuses. The orphans themselves are the owner's to kill, not this review's.

**PR-7 — tippecanoe input is 650 MB per origin in `$TMPDIR`, four to five run concurrently and multi-threaded, and a killed worker leaks them (H10 with numbers)**
Severity M · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/tiles.py:28-30`, `:38`, `:41-61`, `:73-75`.
Why: measured 629–669 MB GeoJSON per origin (6.3× res 5) written to the system temp directory — ~360 GB of temp writes over 553 origins, 3.3 GB present at once — and the `finally` only runs for a Python exception, not a killed process: five GeoJSON + two staged PMTiles (~470 MB) from 9 Sep 21:06 are still there. tippecanoe uses all 10 cores by default, so four concurrent runs are ~40 threads on the same cores as the five Python workers. Scheduled for cycle 2 in the build plan; this is the quantification. PR-1's streaming writer is the same file.
Fix: as planned (`data/build/tmp/`, `-P`/thread cap via `TIPPECANOE_MAX_THREADS` or `--threads` if available in v2.79, a start-up sweep of stale `tmp*.geojson`), and delete the input as soon as tippecanoe has read it rather than after the move.

**PR-8 — Origin switches never abort the superseded origin's four fetches (~0.5 MB gzipped plus tile ranges each), so they compete with the new origin over the single HTTP/2 connection (pairs with C5)**
Severity M · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/web/app.js:458-526` (`paintOrigin`: fetches at 483–488, 489–499, 504–519 with no `AbortController`).
Why: walking the list with the arrow keys and Enter, or clicking two labels, starts a new set of five requests each time while the previous sets keep downloading (`seoul.modes.bin` alone is 263 KB on the wire, `.json` 86 KB, `.bin` 130 KB, `.air.bin` 41 KB); the newest origin's `.bin` — the one the readout is waiting on — queues behind them. C5's generation counter discards their results but not their bytes.
Fix: one `AbortController` per `paintOrigin` call, aborted at the top of the next; pass its `signal` to every fetch; the C5 `gen` check then becomes `signal.aborted`. Also removes the "hover data unavailable" console error a cancelled switch would otherwise log.

### Low

**PR-9 — First-load inventory: ~2.5 MB on the wire, of which `gtag.js` (191 KB) is the third-largest asset and ~390 KB of per-origin leg data is needed only after a click (numbers for D13/H8, not a new task)**
Severity L · Confidence H · Status Confirmed · Effort S (reorder) / M (lazy)
Files: `/Users/hletrd/flash-shared/transport-maps/web/index.html:5`, `:77-85`; `/Users/hletrd/flash-shared/transport-maps/web/app.js:54`, `:67`, `:229`, `:332`, `:399`, `:504-519`, `:821`.
Measured on the live site with gzip: `index.html` 6.4 KB · `app.js` 13.5 KB · `maplibre-gl.js` 283 KB · `pmtiles.js` 5.6 KB · `fflate.js` 12.5 KB · `h3.js` 57.8 KB · `maplibre-gl.css` 10.1 KB · fonts 71 KB · `index.json` 4.2 KB · `hover_cells.bin` 125 KB · `places.json` 137 KB · `borders.json` 404 KB · `airports.json` 91 KB · `seoul.bin` 130 KB · `seoul.modes.bin` 263 KB · `seoul.air.bin` 41 KB · `seoul.json` 86 KB · `gtag.js` 191 KB · water tiles at z1 ≈ 453 KB (new build; see PR-14) · bands z1 ≈ 106 KB. The serialisation `index.json → hover_cells.bin → new Map` (D13 reorder, cycle 2) is intact at `app.js:54-67,332`; `places.json` is not even requested until both awaits resolve (line 229). `borders.json` is 404 KB gzipped / 1.28 MB parsed on the main thread (H8, scheduled with D13).

**PR-10 — `fflate.js` is a static import of `pmtiles.js` but is missing from the `modulepreload` list, adding one sequential fetch to the module graph's critical path**
Severity L · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/web/index.html:81-83`; `/Users/hletrd/flash-shared/transport-maps/web/vendor/pmtiles.js` (`from"./fflate.js"`).
Why: `modulepreload` does not fetch a module's dependencies; `fflate.js` (12.5 KB gz) is discovered only after `pmtiles.js` has arrived and been parsed, so `app.js` evaluation waits one extra round trip.
Fix: add `<link rel="modulepreload" href="./vendor/fflate.js">`.

**PR-11 — The weight-500 face is used on first paint (`summary`, `.lbl.origin`, `.leg .d b`, `.results button[aria-current]`, `.btn`, `.legs h2`) but only 400 and 600 are preloaded**
Severity L · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/web/index.html:79-80`, `:115`, `:173`, `:179`, `:201`, `:249`, `:272`; `/Users/hletrd/flash-shared/transport-maps/web/vendor/fonts.css` (`font-display: swap`).
Why: with `swap`, the three panel headings and the origin labels render in the fallback face and re-lay out when the 24 KB 500 face lands after the stylesheet — a small shift in the rail on every cold visit (the fonts are the only long-cached asset, so it is the first visit only).
Fix: preload the 500 face too, or use 600 where 500 is used.

**PR-12 — `nearestPlace` scans 34,135 rows (the comment says 7,000) and runs twice per pointer frame (H6 detail)**
Severity L · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/web/app.js:229-238` (comment at 233), `:313-329`, `:691-701`, `:725`.
Why: the gazetteer moved to GeoNames cities15000 (34,135 rows in `dist/places.json`); `describe()` and the tooltip each call `nearestPlace` in the same `mousemove` frame — 68k iterations, ~0.2 ms, alongside `queryRenderedFeatures`, two `innerHTML` writes, the forced layout at `tip.offsetWidth` (line 732 after the write at 728) and a GeoJSON `setData` per hovered-cell change (line 424). Not jank on its own; H6's exit criterion (a trace showing >16 ms frames) stands.
Fix: call `nearestPlace` once per frame and pass the result to both; correct the comment.

**PR-13 — Three `backdrop-filter` surfaces sit over a canvas that repaints every frame, and one of them (`.tip`) moves every frame**
Severity L · Confidence M · Status Needs manual validation · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/web/index.html:133`, `:143`, `:239`.
Why: `.reading` (306 × ~330 px, `blur(10px)`), `.mast` and `.tip` (`blur(6px)`, repositioned on every pointer frame at `app.js:733-734`) each force the compositor to re-blur their backdrop whenever the WebGL canvas beneath changes — i.e. during every drag, zoom and hover highlight. On Apple silicon this is likely 1–3 ms per frame; on an Intel iGPU laptop it is the kind of thing that turns a 60 fps globe into 30. The cycle-1 changes did not add a surface.
Fix: keep the blur on the two static panels if the design wants it; give `.tip` a solid 92 % scrim (it is 12 px type on a dark ground; blur buys nothing there). Confirm with a Performance-panel trace on the preview before and after.

**PR-14 — The new `water.pmtiles` (867 MB, z0–12, with lakes) carries a 355 KB z0 tile and 453 KB of z1 tiles: 4× the bands' cost at the opening view**
Severity L · Confidence H (sizes decoded from the directories) · Status Confirmed · Effort S (flags) but needs the orchestrator's water rebuild
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/water.py:33`, `:37`, `:102-123`; `/Users/hletrd/flash-shared/transport-maps/web/app.js:340`, `:371-373`.
Why: decoded from `dist/water.pmtiles`: z0 1 tile 355 KB, z1 4 tiles 453 KB, z2 16 tiles 587 KB, z3 56 tiles 836 KB (all gzip inside the archive). The page opens at zoom 1.35 and lands at 1.9, so z1 (453 KB) is on the first paint's path, against 106 KB for the bands' z1 and 125 KB for `hover_cells.bin`; `minZoom: 0.6` means the 355 KB z0 tile is fetched by anyone who zooms out. The live site still serves the 134 MB z11 build, so this lands with the deploy.
Fix: tippecanoe `--low-detail`/`-D 10` (or `--simplification` scaled at z≤2) for the water layer's lowest zooms; the coast at z0–1 is sub-pixel at that detail anyway.

**PR-15 — nginx compresses at the default `gzip_comp_level 1` and per request; pre-compressed `gzip_static` would cut ~13 % off every JS/JSON byte at zero CPU (deploy)**
Severity L · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/deploy/worldmap.atik.kr.conf:43-56`, `:79-81`; `/Users/hletrd/flash-shared/transport-maps/scripts/deploy_verify.sh:54-55`.
Why: measured live, `maplibre-gl.js` 1,053,810 → 283,278 B (26.9 %), which is level-1 output; level 6–9 gives ~245 KB and brotli ~215 KB. Every visit re-fetches it (`no-cache`, H12) unless the ETag matches. `gzip_static on` with `.gz` files written by `deploy_verify.sh` before the rsync gives the best ratio without per-request CPU; `.bin` files gain too (`seoul.modes.bin` 263 KB at level 1).
Fix: `gzip_static on; gzip_vary on;` plus a pre-compression step in the deploy script (`gzip -9k` / `brotli` over `*.js *.css *.json *.bin *.html`); keep `gzip off` for `.pmtiles`.

**PR-16 — `check_coverage` and `_coarse_features` redo origin-independent work per origin (H2 lines with numbers)**
Severity L · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/validate.py:33-37`; `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/contour/bands.py:270-274`, `:335`.
Why: `reachable_in_principle` is 10 M `cell_to_latlng` calls (9 s) per origin ≈ 17 min over the build; `_coarse_features` runs 5 M `cell_to_parent` plus `np.unique` on a 5 M-string object array (~15–25 s) per origin ≈ 30–45 min; `cells6_arr`/`cells_arr` object arrays are rebuilt per origin (~1 s each). All belong in `shared` (as int index arrays, not strings) with the PR-3 items.

**PR-17 — `showLabels` is O(labels × placed) per move frame and projects up to 900 markers (H7, one line)**
Severity L · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/web/app.js:265-309`.
Why: `placed.some(...)` at line 293 makes the collision test quadratic in the visible count (≈150 at zoom 5.5+, so ~100k comparisons per frame), each attached MapLibre `Marker` also re-projects itself on `move`. The D3 change (18 labels at the landing zoom) adds no cost at the opening view. A grid-bucketed collision map and an early `break` when `placed.length` reaches `n` are S; the symbol-layer alternative is the H7 decision.

**PR-18 — `render()` rebuilds up to 553 `<li>` rows and lower-cases 4,008 airport names and codes on every keystroke (H14, one line)**
Severity L · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/web/app.js:825-867`, `:965`.
Why: 2–5 ms per keystroke at 553 cities; below H14's 50 ms trigger. Pre-lower-casing the two lists once and diffing the list would make it free, when someone is in the file for D8.

**PR-19 — `_representative_children` and friends also un-share the copy-on-write graph: every `for c in idx.cells` loop in a worker dirties the refcount of 10 M `str` objects (~0.7 GB) and every `try_cell_index` hit dirties an int (H5 mechanism, measured)**
Severity L (as a separate action; the effect is counted in PR-1/PR-4) · Confidence M · Status Likely · Effort L
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/nodes.py:41-47`, `:142`; every `enumerate(idx.cells)` in `emit/*.py` and `contour/bands.py:245`.
Why: the arrays (`csr`, `native`, `grid.nb`) stay shared; the Python-object parts of `NodeIndex` do not survive a single iteration. H5's `uint64` + `searchsorted` storage is the real fix; PR-3 removes the four worst loops without it.

**PR-20 — `pool.imap` is ordered with `chunksize=1`, so a slow origin (Beijing 29.5 MB vs Sapporo 24.8 MB) holds back the printed progress of the four faster workers (H11, one line)**
Severity L · Confidence H · Status Confirmed · Effort S
Files: `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:217`.
`imap_unordered` is a one-word change; the table then prints in completion order, which is also what a resumable build (A6e) needs.

### Cycle-1 items checked, not re-described

- H1 → PR-1 (reopened). H2 → bf9e5cc did the rail half; PR-3/PR-16 are the rest. H3 open: the `modes` loop's `ground_adjacent` measures 1.1 µs per cell→cell edge, so the loop is ~30–40 s per origin, third behind PR-2 and PR-3. H4 → PR-2. H5 → PR-4/PR-19 (new evidence). H6 → PR-12/PR-13. H7 → PR-17. H8 open (404 KB gz / 1.28 MB parse; borders could be a URL source). H9 open: `hex_edges` is ~10 M × (5.3 µs `grid_ring` + six dict lookups + the `add()` closure with `countries.is_closed`) ≈ 2–3 min of the serial phase; the cached `native_edges` holds the same adjacency. H10 → PR-7. H11 → PR-20. H12 open; measured: the 304 path works, the cost is one RTT per asset. H13 open; on the wire `hover_cells.bin` is 125 KB gzipped, so the payoff is smaller than the raw 726 KB suggested. H14 → PR-18.
- Not findings after measurement: `np.maximum.at` in `_slowest_within` (0.7 s per 70 M edges on NumPy 2.x; `reduceat` was no faster). `pmtiles.Protocol` keeps one small `PMTiles` object per origin URL ever viewed in `this.tiles`, but its directory cache is bounded (`maxCacheEntries`), so origin switching does not leak meaningfully. `esc()` (4 regex replaces on short strings, ≤8 calls per frame) is negligible.

## Regression check — cycle-1 fixes in this angle

| Fix | Where (read) | In place? | Per-frame / start-up cost added? |
|---|---|---|---|
| C9 failure UI (`fatal`, `fetchOk`, `loadJSON`, `loadCells`) | `web/app.js:37-52`, `:54`, `:67` | Yes: odd byte length, non-JSON and non-2xx each write `#time`/`#where` and throw before the map is built | None (one write on the failure path) |
| C10 gesture-gated geolocation | `web/app.js:1097-1126` | Yes: `getCurrentPosition` only inside the `#locate` click handler, `maximumAge: 900000`, `timeout: 8000`; no prompt on load | None; no timers |
| C12 no `.rail.*` fetch unless advertised | `web/app.js:481-488` | Yes: guarded by `meta.railDetail`; the served `index.json` has no `railDetail`, so zero requests (the new build's `index.json` will set it and the files exist) | None |
| D3 labels on the opening view | `web/app.js:265-269` | Yes: 18 labels for 1.2 ≤ z < 2.2, landing zoom 1.9 | The 900-marker loop already ran per move frame (H7); at z 1.9 only 18 `project()` calls, no measurable change |
| D10 reduced motion | `web/app.js:414-415`, `:995`, `:1117-1121` | Yes: `jumpTo` under `prefers-reduced-motion`, compass `duration: 0`, the `moveend` race handled | None |
| esc() on dataset strings (I1) | `web/app.js:31-32`, call sites `:596`, `:600`, `:615`, `:700`, `:716-728` | Yes | ≤8 short-string replaces per pointer frame; negligible |
| Explicit address search (D4/E4) | `web/app.js:869-917`, `:968-980`, `:990` | Yes: only Enter-with-no-local-match or the button; `addressSeq` guards stale results | None per keystroke (the Nominatim request is gone from `input`) |
| bf9e5cc "polars out of the forked workers" (H2 partial) | `cli.py:170-185`, `emit/rail_detail.py:61-110`, `emit/modes.py:47-50` + `cli.py:121`, `validate.py:149-152` + `cli.py:109-110`, `bands.py:318-321` + `cli.py:112-113` | **Verified.** `lookup_tables()` runs in the parent and hands plain dicts; on the worker path (`dijkstra`, `check_coverage`, `check_monotonic_ground` with `country`/`zone` passed, `band_feature_collection` with `grid`/`native` passed, `tiles`, `hover`, `routes_json`, `itinerary`, `modes` with `cell_class` passed, `write_rail_detail`) nothing touches a DataFrame or pyogrio; the `pl` import in `rail_detail.py` is only used by `lookup_tables`. The live run's five workers are at 91–96 % CPU, not the 0 % of the deadlock | — |

## Final sweep

Checked and clear: repeated regex compilation (`routes.py:59` compiles per cargo heading at
crawl time only; page regexes are literals); per-call file reads (`ground._land_border_min`
and `air.load_calibration` read `calibration.toml` per origin / three times per graph — µs);
unbounded page maps (`routes.byId` and the typed arrays are replaced per origin; `labelPool`
is 900 by design; `proto.tiles` bounded as above); listeners never removed (`map.on("move")`,
`map.on("rotate")`, `SMALL.addEventListener` are page-lifetime by design; Markers remove
their own on `.remove()`); images without size hints (no `<img>`; `preview.png` is metadata
only); CSS forcing layout on scroll (none; `.rail` uses `overscroll-behavior`); `will-change`
(none — good); polling timers (none in `app.js`; the crawlers' `time.sleep` are courtesy
pacing); O(n²) loops (PR-17; the `_coarse_features` ring growth and `hex_edges` `cross` set
are dict/set based). No relevant file in the inventory was skipped; `emit/{water,places,
borders,airports_json}.py` and `scripts/*` are one-shot builders with no per-origin or
per-frame role.

Evidence for other lanes, noted in passing: (a) `dist/hover_cells.bin` was rewritten at
04:28 by the running build (`cli.py:196`) while 147 of the 157 per-origin arrays are still
the res-5 build — the live A6b case; the preview server is serving that mix. (b) The
`dist/origins/las-vegas.pmtiles-journal` leftover (I4) is still present. (c) A full `pytest`
was running at 3.5 GB alongside the build (F4: the suite builds real indexes). (d) The
projected `dist/` for 553 origins is ~17 GB (553 × ~30 MB plus 867 MB water), against the
~2.3 GB live today; `deploy_verify.sh`'s single `rsync --delete` will move it in one go.
