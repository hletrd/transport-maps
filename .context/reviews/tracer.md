# Tracer review — cycle 2

- **HEAD reviewed:** `bf9e5cc` (`fix(build): keep polars out of the forked workers; snap off-mask airports to land`), branch `feat/transport-pipeline`, working tree clean apart from other reviewers' cycle-2 files under `.context/reviews/`. Cycle-1 fixes (`b030d38`…`7cd7d63`) are in.
- **Date:** 2026-09-10 04:51 KST. A `build-all` (parent pid 94066, 5 forked workers, started 04:23) was running throughout; everything below is read-only. `dist/` at review time: `index.json` from Sep 9 23:18 (157 origins, `solveRes: 5`, no `fineRes`/`modeDetail`/`railDetail`), `hover_cells.bin` from 04:28 (90,740 entries), 10 origins rebuilt at 90,740 entries, 147 old ones at 90,659.
- **Method:** each flow states a question, competing hypotheses, the code path read line by line, the evidence that decides it, and a conclusion. Where the code alone could not decide, a read-only probe in the scratchpad was run against the same cached inputs the build reads (no cache written, no repo file touched). Finding IDs are `TR-n`; cycle-1 items still open are cited by their aggregate ID.

## Inventory (files opened)

`CLAUDE.md`; `.context/reviews/cycle-1/_aggregate.md` (A, C, G, J1); `.context/reviews/cycle-1/tracer.md` (IDs only); `plan/README.md`, `plan/2026-09-10-c1-build-robustness.md`, `plan/2026-09-10-c1-gates-and-tests.md`, `plan/2026-09-10-c1-web-ui-detail.md`, `plan/2026-09-10-c1-security-and-policy.md`, `plan/2026-09-10-c1-docs-attribution-calibration.md`, `plan/deferred.md`.

Source: `web/app.js` (all 1,126 lines), `web/index.html` (1–60, 300–477), `src/transport_maps/cli.py`, `config.py`, `validate.py`, `emit/hover.py`, `emit/index.py`, `emit/itinerary.py`, `emit/modes.py`, `emit/rail_detail.py`, `emit/routes_json.py`, `emit/tiles.py`, `graph/build.py`, `graph/ground.py`, `graph/nodes.py`, `graph/refine.py`, `graph/transfers.py`, `contour/grid.py`, `contour/bands.py`, `solve/dijkstra.py`, `sources/_utils.py`, `sources/airports.py`, `sources/landmask.py`, `sources/roads.py`, `sources/urban.py`, `sources/osm.py`, `sources/routes.py`, `sources/countries.py`, `sources/wikidata.py` (cache lines 158–218), `scripts/deploy_verify.sh`, `scripts/browser_verify.sh`, `deploy/worldmap.atik.kr.conf`, `deploy/README.md`.

Tests: `tests/test_cli.py`, `tests/sources/test_cache_provenance.py`, `tests/graph/test_ferry.py` (150–194), `tests/emit/test_hover.py`, `tests/emit/test_rail_detail.py` (names).

Artifacts (read-only): `dist/index.json`, `dist/hover_cells.bin` size, `dist/origins/*` sizes and counts, `data/build/` and `data/cache/` listings, `data/origins.toml` count, `git show bf9e5cc`, `git log ac191db..HEAD`, `ps` for build workers, `mount`, Python 3.14.2 `multiprocessing/pool.py` (grep), an `rsync -n` dry run of `dist/`.

Probes (scratchpad only): `snap_probe.py` (emulates `nodes.build_index`'s off-mask branch from the cached land cells, road grid, populated places and country polygons), `pool_death.py` (SIGKILLs a pool worker under an alarm), three one-line h3 checks.

---

## T1 — Origin switch on the page

**Question.** From a city-row click, an origin label click, "Depart from here", Enter in the search box or the location button, through every fetch to the hover readout: where can a slow earlier origin overwrite a newer one, and what do the handlers see while the arrays are half-swapped?

**Hypotheses.** H1: every per-origin fetch checks `active === o` and the race is closed. H2: only some fetches check, so a late response for origin A lands after origin B was selected. H3: the arrays are nulled at different times, so a handler can pair one origin's times with another's modes even without a late response.

**Trace.**
- Entry points all reach `paintOrigin(o)`: city row `app.js:958-963` (no same-slug guard — clicking the current city re-fetches everything), origin label `:255-259` (guarded by `origin.slug !== active?.slug`), "Depart from here" `:777-781` (sets `pinB = null` first), Enter `:970-973` (clicks the first row), location `:1120-1121`.
- `paintOrigin` `:458-526`: `active = o` (459); tile source removed and re-added synchronously (460-476); `hoverTimes = hoverFailed = railDetail = null` (478-480); `.rail.bin`/`.rail.json` fetched only when `meta.railDetail`, and the result is applied **only if `active === o`** (487); `.bin` fetched (489-499) and applied **unguarded** (494: `hoverTimes = …; renderPins(); renderLegs()`), and its `.catch` writes `hoverFailed = o` and `$("where").textContent` **unguarded** (497-498); `hoverAir = routes = hoverModes = null` (503); `.modes.bin` (504-507), `.air.bin` (508-511), `.json` (512-519) applied **unguarded**.
- Readers: `lookup` `:555-559` (`undefined` while `hoverTimes` is null, `null` off-mask); `legsTo` `:564-580` needs `hoverAir` and `routes`; `renderLegs` `:582-665`; `renderPins` `:752-784` (760); `mousemove` `:705-736`.

**Evidence.** Lines 487 vs 494/506/510/516: one guard, four unguarded. Per switch the page downloads `.bin` 181 KB, `.air.bin` 181 KB, `.modes.bin` 1.09 MB, `.json` 527 KB, `.rail.bin` 181 KB, `.rail.json` 183 KB (sizes from `dist/origins/seoul.*`): about 2.3 MB uncompressed, several seconds on a mobile link — that is the window. No `AbortController` anywhere in `app.js`.

**Conclusion.** H2 holds (H1 refuted; H3 refuted — the nulling at 478 and 503 happens in one synchronous pass before any response can arrive, so a *fresh* switch never pairs mixed arrays). The concrete failure: switch Seoul → Paris while Seoul's `.bin` is still in flight; Seoul's `.then` at 494 sets `hoverTimes` to Seoul's array and calls `renderPins()`, which prints the pin row as "From Paris … Door to door 2 h 10" using Seoul's number. Same for `hoverModes`/`hoverAir`/`routes`: the airport ordinals are shared across origins, so `legsTo` walks Paris's `prev` chain from Seoul's arrival airport and renders a plausible wrong itinerary. A late *failed* Seoul `.bin` writes "Times unavailable for Seoul" into `#where`, which stays until the next `mousemove` — on a coarse pointer there is none, so it stays. → **TR-7** (new evidence for the scheduled C5; the fix is the planned generation counter, and the `.catch` branch must be guarded too).

## T2 — Hover readout, outlined hexagon, painted band

**Question.** Which cell does each of the three come from, where do they disagree, and does the cycle-1 C7 change cover every branch?

**Hypotheses.** H1: all three come from the cell under the cursor. H2: the number comes from the res-4 parent's representative child, the outline from the res-6 cell under the cursor, the colour from the tile feature — three different cells. H3: C7 covers every branch that prints a state word.

**Trace.**
- Number: `lookup` `:555-559` → `cellIndex` `:541-550` → `h3.latLngToCell(lat, lon, HOVER_RES=4)`, binary search in `hoverCells` → `hoverTimes[i]`. The emitter fills that slot from `_representative_children` (`hover.py:31-56`): the res-6 centre child when it is a land cell, else the res-7 centre child (the base was split), else the fastest child. h3 check: `cell_to_center_child(p4, 7) == cell_to_center_child(cell_to_center_child(p4, 6), 7)` is True, so the split fallback picks the cell a pointer at the parent's centre means.
- Outline: `highlight` `:418-426` → `h3.latLngToCell(lat, lon, SOLVE_RES)`; drawn for any masked parent, including a res-6 cell that is itself sea or was split (C3).
- Colour: `bandRangeAt` `:672-689` reads the rendered feature; at zoom ≥ 7 that is the native cell's band (`bands.py:234-263`, with the split parent painted underneath in its slowest child's band, 249-259); at zoom 5-6 and 3-4 the base cell's band is the **fastest** of its children (`bands.py:328-330`, `np.minimum.at`); at zoom ≤ 2 the res-4 parent's fastest.
- C7 branches: `mousemove` `:714-719` distinguishes `undefined` (loading / unavailable) from `null` ("Open water."); `renderPins` `:760` maps `undefined` → "loading…" and `null` → "not on land" **without consulting `hoverFailed`**; `renderLegs` `:588` hides the box for either; `tip` `:723` hides for either. A res-4 parent is in the mask iff it has any res-6 land child (`hover.py:28`), so `null` really is water-or-outside-mask now — but a cursor over the sea inside a masked parent (up to ~22 km from the centre child; a res-4 hexagon's centre-to-vertex distance) still gets that child's number and a white hexagon over water.

**Evidence.** `hover.py:50-55`, `app.js:419, 542`, `bands.py:330`, `app.js:760`.

**Conclusion.** H2 holds; H1 refuted; H3 nearly: the one branch C7 missed is `renderPins`, which says "loading…" for ever after a failed `.bin` fetch while the readout above it says "unavailable". The three-cell disagreement is C3 (scheduled, cycle 3) and shows up as "∞ no route · 5–10 h" when the centre child is unreachable but a sibling is not, or as a number one band off the colour. → **TR-8** (Low) for the `renderPins` gap; C3 referenced.

## T3 — build-all worker failure after A3

**Question.** What happens when a forked worker raises, when the parent gets SIGINT, when a worker is killed by a signal (OOM, segfault, `kill -9`), and what state is `dist/` left in? Why did the recorded deploy refusal see 90,659 against 90,740?

**Hypotheses.** H1: after A3 every worker failure aborts the run. H2: A3 covers Python exceptions only; a worker that dies without reporting still hangs `imap`. H3: `dist/` is consistent after an abort because `index.json` is written last.

**Trace.**
- `cli.py:98-127` `_solve_one` writes, in order, `.pmtiles`, `.bin`, `.json`, `.air.bin`, `.modes.bin`, `.rail.bin`+`.rail.json`, each non-atomically (`hover.py:71-72`, `routes_json.py:56-57`, `itinerary.py:70-71`, `modes.py:100-101`, `rail_detail.py:107-110`); `tiles.py:28-70` stages in the system temp dir (`/var/folders/…`, local APFS) and `shutil.move`s onto `dist/` (NFS: `mount` shows `172.30.60.100:/mnt/mnt/flash/flash-shared` on `/Users/hletrd/flash-shared`) — cross-device, so `move` is `copy2` + `unlink`: the destination is truncated and rewritten over the seconds a 27 MB file takes, and a kill mid-copy leaves a truncated file that the `finally` (73-75) does not remove.
- `cli.py:191-196`: `hover_cells.bin` is written **before** the pool starts; `:224-231` `index.json` after every origin, never with `--limit`.
- `cli.py:205-222`: `GateFailure` (a `RuntimeError`) is pickled back through `imap`, `Pool.__exit__` calls `terminate()` (SIGTERM to the other workers mid-write), then `SystemExit`. Any other `Exception` from a worker (`ValueError` from the monotonic or cover gate, `RuntimeError` from tippecanoe) propagates the same way with a traceback. SIGINT: the parent's `KeyboardInterrupt` leaves the `with` block → `terminate()`; workers in the same process group get SIGINT too and die on their own; tippecanoe children likewise.
- A worker killed by a signal: Python 3.14.2's `multiprocessing/pool.py` has no broken-pool handling (`grep -n Broken` finds nothing; only `exitcode` checks at 218/297/715 that respawn workers); the fix for this (`gh-66587`, PR #16103) was closed unmerged on 2026-06-30 ("not workable"). The scratchpad probe `pool_death.py` (fork context, `imap`, worker calls `os.kill(getpid(), SIGKILL)`) printed `result 0` and then `HUNG … pool respawned workers` at the 8 s alarm. The A3 test (`tests/test_cli.py:196-226`) exercises the exception path only.
- Hover-cell count: `hover.py:26-28` — the sorted set of res-4 parents of `idx.cells`; `idx.cells = refine(land_cells(SOLVE_RES), split)` (`nodes.py:134-139`), and fine children share their base cell's parent, so the count depends on `landmask.land_cells(SOLVE_RES)` alone: the resolution (`config.SOLVE_RES`, 5 → 6 picks up res-4 cells whose only land is a sliver no res-5 cell overlapped) and the landmask stamp (`landmask.py:176-178`). `data/build/` holds `land_cells_r5_*.parquet` (five stamps) and `land_cells_r6_dd95e3b5.parquet`; the old `.bin` files (Sep 9 23:04, 90,659) came from the res-5 universe, `hover_cells.bin` (04:28, 90,740) from the res-6 one. `deploy_verify.sh:12-25` reads `n_cells` from `hover_cells.bin` and compares every origin listed in the **old** `index.json`, which is why the refusal fired.

**Evidence.** `ps`: parent 94066 + workers 4143-4147 (5 = `_worker_cap` for > 3 M cells); also **eight `transport_maps.cli build-all` processes with ppid 1, started Sep 9 18:46:54, 0 % CPU, state `SN`, RSS ~10 MB (paged out)** — the polars-deadlocked build `bf9e5cc` describes, whose parent died without `terminate()` reaching them; they are still there ten hours later. `dist/origins`: 147 `.bin` at 90,659 entries, 10 at 90,740, five `.rail.bin`, one `las-vegas.pmtiles-journal` from Sep 9 07:03.

**Conclusion.** H2 holds and H1 is refuted for signal deaths → **TR-1** (High). H3 refuted: after any abort `dist/` holds the new `hover_cells.bin`, a prefix of new origins, the rest old, possibly one truncated `.pmtiles` per killed worker → A6a/A6b/A6c stand, with **TR-6** for the cross-device copy and **TR-9** for the orphaned workers that nothing detects. The count difference is entirely the `SOLVE_RES`/landmask change to `land_cells`, surfaced because `hover_cells.bin` is written first and `index.json` last.

## T4 — Cross-resolution edges after A4; the airport snap in bf9e5cc

**Question.** Trace a res-7 cell adjacent to an unsplit res-6 neighbour through ferry, ground and refine: any edge duplicated or missing? Where does a snapped airport land, what does it do to access times and to the "18 of 4008 dropped" line, and can a snap cross an immigration zone or water?

**Hypotheses.** For the edges — H1: a cross-resolution pair is still emitted by both `hex_edges` and `_ferry_edges`; H2: the pair is emitted once by `hex_edges` and `_ferry_edges` skips it; H3: the pair is missing from `hex_edges` on one side. For the snap — S1: it can put an airport in another country/zone and charge a border crossing to reach it; S2: it never crosses a country but always crosses unmapped ground; S3: the snap is blind to split base cells, so it drops or mis-places airports beside dense land.

**Trace (edges).** `ground.hex_edges` `:119-130`: for fine `u`, a ring-1 neighbour not in the index is replaced by its res-6 parent; if that parent is indexed (unsplit land) both `(u,v)` and `(v,u)` are added once, guarded by the `cross` set. From the base side, a base `u` whose neighbour is a split cell finds nothing (the split cell is not in `cell_pos`) and adds nothing — but every child of that split cell on the seam adds the pair from its own loop, so the pair exists in both directions exactly once. `refine.ground_adjacent` `:66-83` tests the same rule (same resolution → `are_neighbor_cells`; else any ring-1 neighbour of the fine cell has the base as parent), and `_ferry_edges` `:308-309` skips exactly those pairs; `_ferry_edges` then dedups by `(u,v)` `:327-331`. `grid.native_edges` `:110-124` mirrors `hex_edges`. `tests/graph/test_ferry.py:159-194` assert the pair is in `hex_edges`, absent from the ferry set, and that `build_graph` accepts the result; the second test keeps a far-child ferry — both red under the two plausible regressions.

**Trace (snap).** `nodes.py:145-147` `cell_at`: res-7 cell if the res-6 base is in `split_set`, else the res-6 cell. `:154-173`: when the cell is not in `cell_pos`, `_nearest_land` `:114-128` searches rings 1 and 2 **at the cell's own resolution** and looks each neighbour up in `cell_pos` — which holds unsplit base cells and res-7 children, never a split base cell. The airport's node then uses that cell for both access edges (`build.py:144-154`); `processing_min`/`disembark_min` are per airport size, so the snap adds no minutes on the edge itself — it moves where the airport is reached from. Flight distances use the airport's true coordinates (`build.py:80-82`). The snapped count is `logger.info` (`:175-177`); no `logging.basicConfig` exists anywhere in `src/` or `scripts/`, so only WARNING and above ever print — the "N snapped" line is invisible, the "dropped" WARNING (`:178-184`) is visible.

**Evidence (probe).** `snap_probe.py` re-derives the off-mask branch from `land_cells_r6_dd95e3b5.parquet`, `airports_c35abade.parquet`, `road_class_grid_495d9dd1.npy`, the populated-places zip and the country polygons — the same files the build reads. It reproduces the code's own numbers exactly: **64 airports need the snap (commit message: 64) and 18 are dropped (log line: 18)**. Of the 58 whose res-6 cell is off the mask, 40 snap (31 at ring 1, 9 at ring 2, up to 14.0 km) and 18 drop; **6 of the 18 (DPL, HLE, KKJ, PTF, WLS, WSZ) have split land within two rings** that `_nearest_land` cannot see — KKJ is Kitakyushu, a scheduled-service airport on a reclaimed island 4.8 km from mapped land beside a dense city. BOO (Bodø, *large*): 2 unsplit + 6 split + 10 sea cells within two rings → snapped 11.2 km to a ring-2 unsplit cell past the adjacent dense cells; USH 13.4 km (1 unsplit, 16 split), SIT 9.5 km. A point-in-polygon check against `ne_10m_land.zip` shows BOO/USH/SIT/KKJ/DUT/FRO are all 1.8–5.1 km outside Natural Earth land and their res-6 cells have zero overlap with it — the mask has not regressed; the 1:10m outline omits these spits and reclaimed islands. Country of the snapped cell (nearest polygon, the `_fill_blanks` analogue) equals the airport's `iso_country` for **all 40**; zero cross-zone snaps.

**Conclusion.** Edges: H2 holds, H1 and H3 refuted — A4 is complete for ferry/ground/refine at the fine-vs-unsplit seam; no duplicate, no missing direction. Snap: S1 refuted on this data (0 of 40); S2 holds by construction (an off-mask cell has no land overlap at all, so every snap crosses unmapped ground or water); S3 confirmed → **TR-2** (Medium). The invisible INFO line and the weakened drop bound → **TR-3** (Medium). `nodes.py:30-36` still says "25 of 4,008" (now 18, after a snap the comment does not mention) — fold into TR-3.

## T5 — Cache provenance

**Question.** For each derived cache, which inputs and constants govern its content and does the key include them? What does `tests/sources/test_cache_provenance.py` actually prove?

**Hypotheses.** H1: G1's list is complete. H2: there are further unkeyed inputs. H3: the test suite would go red if a stamp were dropped.

**Trace (key vs governing inputs).**

| Cache | Key (file:line) | Governs content but not in key |
|---|---|---|
| `airports_<h>.parquet` | `AIRPORTS_URL`, `SIZE_BY_TYPE`, `REQUIRED_SOURCE_COLUMNS` (`airports.py:33-41`) | raw `ourairports.csv` content (fixed name, `:23-30`; G2) |
| `land_cells_r{res}_<h>.parquet` | URLs, `ANTARCTICA_MAX_LAT`, `POLE_CLIP_LAT`, `WEDGE_COUNT`, tag (`landmask.py:169-178`) | polyfill method (`h3shape_to_cells_experimental(contain="overlap")` at `:222`; `_cells_touching` `:181-207` is dead code whose docstring describes a different method), `_pole_cells` disk radius, raw zips |
| `road_class_grid_<h>.npy` | `DENSITY_THRESHOLD`, grid shape, `N_TYPES` (`roads.py:52-60`) | `GRIP4_URL`, raw `.asc` content (G1) |
| `urban_mask-<h>.parquet` | pop, radius, `PLACES_URL`, `len(cells)`, first, last (`urban.py:76-77`) | the cell list itself (G1); places zip content |
| `ferry_links-<h>.parquet` | extract fingerprints (`osm.py:151-153`) | `ANTIMERIDIAN_EPS_DEG` (`:134`, G1), `FERRY_SCHEMA` |
| `rail_routes-<h>.parquet` | fingerprints, roles, `MIN_STOPS`, schema (`osm.py:180-183`) | `_is_highspeed` rule (code) — acceptable |
| `routes.parquet` | **bare `.exists()`** (`routes.py:242-244`) | everything: airports table stamp, `_SANITY_PAIRS`, parser constants (G1) |
| `airline_destinations.json`, `wikidata_iata.json` | per item, no stamp (`routes.py:169-187`, `wikidata.py:160-166`) | `parse_destinations` regexes, `_SKIP_PREFIXES`, `_strip_cargo_subsections` — a parser fix never reaches an already-cached airport |
| `cell_country-<h>.parquet` | `COUNTRIES_URL`, tag, sha256 of the full cell list (`countries.py:96`) | — (correct pattern) |
| `render-grid-<h>.npz`, `native-edges-<h>.npz` | version tag, rings, full cell list (`grid.py:42, 95`) | `config.SOLVE_RES` (encoded by the cell ids anyway) |

**Evidence.** `data/build/`: `routes.parquet` dated Sep 3 17:42 while `airports_c35abade.parquet` is Sep 3 22:19 — the route network in use predates the current airport-table stamp, the staleness the rule exists to prevent. `data/cache/`: 26 `urban_mask-*` and roughly 300 `rail_routes-*` files (2.3–2.8 KB each, test droppings; F4b). The test file: `test_hash_*` (stability, dict order, `1 != 1.0`); `_grid_cache_path` moves with `DENSITY_THRESHOLD` and is stable; `road_class_grid()` reads the stamped path and misses after the constant moves; `_table_cache_path` moves with `SIZE_BY_TYPE`/`REQUIRED_SOURCE_COLUMNS` and is read by `scheduled_airports()`; `_cells_cache_path` separates resolutions, moves with `ANTARCTICA_MAX_LAT`, is read by `land_cells()`; every stamped stem carries an 8-char hash; `_atomic_write` output is group/other readable. Dropping any of those three constants from its stamp makes the matching "path moves" test red (the assertion compares paths before/after the monkeypatch), so they are not vacuous — for those three constants only.

**Conclusion.** H1 confirmed and extended (H2): add the per-item parsed caches, the dead `_cells_touching`, and the `routes.parquet`-older-than-airports evidence. H3 holds for `DENSITY_THRESHOLD`, `SIZE_BY_TYPE`/`REQUIRED_SOURCE_COLUMNS`, `ANTARCTICA_MAX_LAT` and for nothing else → **TR-12** (Low; G1 stays the scheduled fix).

## T6 — Deploy path

**Question.** What does a visitor download between rsync starting and finishing, which mixtures the page tolerates, which render a blank globe, and whether the gate's byte widths match the emitters.

**Hypotheses.** H1: rsync's order makes the mixed window short or benign. H2: `index.json`/`hover_cells.bin` go first and the origins over minutes, so the window is the whole origins upload, and the page has no way to detect it. H3: the gate's widths are wrong for some file.

**Trace.** `deploy_verify.sh:9-37` gate: `n_cells` from `hover_cells.bin/8`; for every origin in `index.json`, `.bin/2`, `.air.bin/2`, `.modes.bin/12`, `.rail.bin/2` (optional) must equal it; `.pmtiles` must exist (no size or header check); `{slug}.json` and `.rail.json` are not checked. Emitters: `hover.py:69` `<u2`, `itinerary.py:71` `<u2`, `modes.py:24,99` six `<u2` channels = 12 bytes, `rail_detail.py:108` `<u2`, `index.py:97` `<u8` → widths match. `:54` copies `web/` into `dist/`; `:55` `rsync -a --delete` in place to `/var/www/worldmap/` (per-file temp+rename, `--delete` = delete-during). Page: `app.js:54-67` loads `index.json` then `hover_cells.bin`; `:463` swaps the tile source; `:494` `hoverTimes = new Uint16Array(b)` with **no length check** against `hoverCells.length`; same at 506/510; `index.html:477` loads `./app.js` unversioned (no-cache headers, `worldmap.atik.kr.conf:39-56`).

**Evidence.** `rsync -a -n -v dist/ <scratch>/` lists, in order: `airports.json, app.js, borders.json, hover_cells.bin, index.html, index.json, llms.txt, places.json, preview.png, robots.txt, sitemap.xml, water.pmtiles, origins/…, vendor/…`. So `index.json` and `hover_cells.bin` are live within the first seconds and the 553 × 7 origin files (tens of GB of pmtiles) follow. Current `dist/` reproduces the mixture locally: new ordering, 147 old arrays.

**Conclusion.** H2 holds, H1 refuted, H3 refuted (widths match). Mixtures: (a) new `index.json` + old `origins/*.bin` of a different length → **silently wrong numbers** for every cell (old array read through the new ordering; `undefined` → "Loading…" past its end) — nothing blank, nothing in the console; (b) new `index.json` naming origins not yet uploaded → 404 → "Times unavailable" (tolerated); (c) new `app.js` + old `index.html` (adjacent in the list, sub-second) → a missing element throws before the map exists → blank globe; (d) truncated `.pmtiles` → tile decode errors, bands missing for that origin, globe intact. A6d closes the window; **TR-4** makes (a) loud from the page side regardless. A second blind spot in the gate: `index.json` is read at gate time and is the *old* one until the build's last write, so a deploy run in the final minutes of a build (every origin of the old index already rebuilt) passes the gate and ships the old `index.json` (`solveRes: 5`, 157 origins, no `railDetail`) with the new arrays → **TR-5**.

## T7 — Time formatting and sentinels end to end

**Question.** Where are 65,535, 0 and > 48 h formatted differently along emitter → page → legend → readout → route panel?

**Trace.** `config.py:31` `UNREACHABLE = 65535`; `index.py:123` ships it; `app.js:55` reads it. Emitters: `hover.py:23,67-69` clamps finite values to 65,534 (`np.minimum`) and truncates (`astype`), `inf` → 65,535; `modes.py:28,99` clips to 65,534 and truncates, `inf` → 0; `itinerary.py:18` `NO_AIRPORT = 0xFFFF` in its own array; `rail_detail.py:21,108` `NO_RAIL = 0xFFFF` and `np.minimum(chosen, NO_RAIL)` silently folds any table index ≥ 65,535 into "no rail"; `routes_json.py:27` `round()` with **no clamp**. Page: `fmtTime` `:532-539`: `null`/`undefined` → "—", `≥ 65535` → "∞ no route", < 1 h → "N min", < 48 h → "H h MMm", else "D days Hh"; `bandRangeAt` `:685-688` prints decimal hours ("3.8–4.2 h", "over 72 h"); legend `paintScale` `:180` prints hours with one decimal; `renderLegs` `:588` hides for `≥ UNREACHABLE`, `:591` `dur()` reuses `fmtTime` per leg, `:613` drops modes under one minute; `renderPins` `:760`.

**Evidence.** Seoul's `.rail.json` table has 2,018 rows (far from 65,535). Max shipped time is 16,676 min (cycle-1 A13), so the clamp is latent.

**Conclusion.** Four notations coexist (min / h m / days h / decimal h) — D19 (scheduled). Sentinels: 65,535 is consistent between `.bin` and the page; 65,534 displays as "45 days 12h" (A13, scheduled); a `routes.json` leg ≥ 65,535 min would print "∞ no route" as a *leg* under a finite total (A13's page half); `0` is handled everywhere (`== null` checks, not falsy checks). The one unlisted spot is the silent `NO_RAIL` fold → **TR-10** (Low). C8 (truncate vs round, off-by-one between hover total and route legs) unchanged.

## T8 (discovered) — Split-seam blind spot in the cover gate

`grid.native_edges` `:110-124` marks a base cell `complete = False` whenever a ring neighbour is missing from the index, including when that neighbour is a split base cell whose children *are* joined to it by the cross edges added from the children's side. `validate.check_bands_cover` `:70-73` samples only `complete` cells at the native level, so the unsplit side of every split/unsplit seam — exactly where `_native_features` `:234-243` closes slivers with the parent hexagon — is never sampled. → **TR-11** (Low).

---

## Findings

### High

**TR-1 — A worker that dies without reporting still hangs `build-all` for ever; A3 covers exceptions only**
- Severity High · Confidence High · Status **Confirmed** · Effort S
- Where: `src/transport_maps/cli.py:205-222` (read 98-231); Python 3.14.2 `multiprocessing/pool.py` (no broken-pool path).
- Chain: worker SIGKILLed (memory pressure, a native segfault in GEOS/h3, a stray `kill -9`) → `Pool._maintain_pool` respawns a worker, the task's result never arrives → `imap` blocks with no timeout → parent sits at 0 % CPU with no exit code, the signature of the cycle-1 hang. CPython's fix (PR #16103 for gh-66587) was closed unmerged on 2026-06-30, so no interpreter upgrade removes this.
- Failure: hour six of a 553-origin build, one worker segfaults in `cells_to_h3shape` on a degenerate band; the other four finish their origins and idle; the build never ends and never fails; `dist/` is mixed (T3).
- Evidence: `pool_death.py` → `HUNG: imap never returned after a worker was SIGKILLed; pool respawned workers`.
- Fix: iterate with `it = pool.imap(...); it.next(timeout=T)` in a loop and, on `TimeoutError`, check `[p for p in pool._pool if p.exitcode not in (None, 0)]` (or count live workers) and abort; or use `concurrent.futures.ProcessPoolExecutor(mp_context=ctx)` whose `BrokenProcessPool` covers this. Test: worker calls `os.kill(os.getpid(), SIGKILL)` under an alarm; mutation: remove the liveness check → alarm fires.

**TR-4 — The page never checks a per-origin array's length against `hover_cells.bin`, so a mixed deploy (or the current `dist/`) shows silently wrong times**
- Severity High · Confidence High · Status **Confirmed** · Effort S
- Where: `web/app.js:494, 506, 510` (read 458-526, 541-559); `dist/` at review time.
- Chain: `hoverTimes = new Uint16Array(b)` with no comparison to `hoverCells.length` → `cellIndex` positions from the new ordering index an old array → every cell reads another cell's minutes; positions past the old array's end read `undefined` → "Loading…". No console error, globe painted, legend fine.
- Failure: any visitor during the origins upload of a deploy whose universe changed (T6), and anyone on the local preview right now (147 origins at 90,659 under a 90,740 ordering).
- Fix: after each `arrayBuffer()`, `if (b.byteLength !== hoverCells.length * WIDTH) throw new Error("… does not match hover_cells.bin")` (2 for `.bin`/`.air.bin`/`.rail.bin`, 12 for `.modes.bin`), which routes into the existing "Times unavailable" branch. Check: serve a `.bin` with 10 fewer entries → readout says unavailable, not a number.

### Medium

**TR-2 — `_nearest_land` cannot see split base cells, so airports beside dense land are dropped or snapped past it**
- Severity Medium · Confidence High · Status **Confirmed** (probe reproduces the commit's 64 and the log's 18 exactly) · Effort S
- Where: `src/transport_maps/graph/nodes.py:114-128, 154-173` (read 1-219).
- Chain: the off-mask cell is res 6 (its base is not land, hence not split) → ring neighbours are looked up in `cell_pos`, which contains unsplit base cells and res-7 children but never a split res-6 cell → a split (dense) neighbour is invisible → the snap takes a farther unsplit cell or nothing.
- Failure: KKJ (Kitakyushu) is dropped with land 4.8 km away; DPL, HLE, PTF, WLS, WSZ likewise; BOO (large, Bodø) lands 11.2 km away at ring 2 past six adjacent dense cells, USH 13.4 km, SIT 9.5 km — the airport's ground access starts one or two hexes from where it is, on the wrong side of the city.
- Fix: in `_nearest_land`, when a neighbour is absent from `cell_pos` but in `split_set`, consider its `cell_to_children(n, FINE_RES)` and take the nearest indexed child. Test: fixture with a split ring-1 neighbour and an unsplit ring-2 cell → the child wins; mutation: revert → ring-2 wins.

**TR-3 — The snap is logged at INFO with no logging configured, and the drop bound no longer measures what its comment says**
- Severity Medium · Confidence High · Status Confirmed · Effort S
- Where: `nodes.py:30-36, 175-192`; `cli.py` (no `basicConfig` anywhere in `src/` or `scripts/`).
- Chain: `logger.info` → dropped by Python's last-resort handler (WARNING and above only) → the "64 snapped" line never prints; `MAX_DROPPED_AIRPORT_FRACTION` now bounds only airports with no unsplit land within two rings, so a land-mask regression that removed every coastal cell would snap most airports one hex inland and pass. Comment at `:30-36` still says 25 of 4,008 dropped and does not mention the snap.
- Fix: `logging.basicConfig(level=logging.INFO, format=...)` in `cli.main`; log the snapped list at WARNING with distances; bound `len(snapped)` as well (e.g. 5 %); refresh the comment (18 dropped, 64 snapped at res 6).

**TR-5 — The deploy gate reads an `index.json` the build rewrites last, checks no `.pmtiles` content, and cannot tell a finished build from one still running**
- Severity Medium · Confidence High · Status Confirmed · Effort S
- Where: `scripts/deploy_verify.sh:9-37, 55` (read 1-62); `cli.py:196, 231`.
- Chain: `index.json` is the previous build's until the last write; the gate compares only origins it lists; once those happen to be rebuilt the gate passes and rsync ships the old `index.json` (157 origins, `solveRes: 5`, no `railDetail`/`modeDetail`) with new arrays and tiles — lengths agree, so nothing refuses. `.pmtiles` is checked for existence only, so a truncated copy (TR-6) deploys.
- Failure: a deploy started in the last half hour of the running build. Also: the page then outlines res-5 cells over a res-6/7 surface and omits rail detail with no error.
- Fix (in addition to A6b/A6c): refuse when `pgrep -f 'transport-maps build-all'` (or a `dist/.building` marker written at `cli.py:196` and removed after `:231`) says a build is running; verify each `.pmtiles` starts with the `PMTiles` magic and that its header's directory offsets lie within the file size; require `{slug}.json`, and `.rail.json` beside every `.rail.bin`.

**TR-6 — `tiles.write_pmtiles` copies across filesystems, so the shipped `.pmtiles` is truncated for seconds per origin and permanently if the worker is killed**
- Severity Medium · Confidence High · Status Confirmed · Effort S
- Where: `src/transport_maps/emit/tiles.py:28-38, 68-75` (read 1-78); `mount` (repo on NFS), `tempfile.gettempdir()` = `/var/folders/…` (local).
- Chain: `shutil.move(staged, out)` → `os.rename` fails with EXDEV → `copy2` opens `out` for writing (truncates the previous build's file) and streams 27 MB → a SIGTERM from `Pool.terminate()` or a SIGKILL mid-copy leaves a partial `out` that the `finally` does not remove and the deploy gate accepts.
- Fix: `tmp = out.with_name(f".{out.name}.tmp"); shutil.copy2(staged, tmp); os.replace(tmp, out)` (same directory, atomic on NFS as well); remove `tmp` in `finally`. Pair with A6a for the six small arrays. Test: interrupt the copy with a fake `copy2` that raises halfway → `out` is untouched.

**TR-7 — Origin-switch race: the exact unguarded set and a concrete misattribution (new evidence for C5)**
- Severity Medium · Confidence High · Status Confirmed · Effort S
- Where: `web/app.js:487` (guarded) vs `:494-498, 506, 510, 516` (unguarded).
- Chain and failure: see T1 — a late `.bin` re-renders the pin row with the new origin's name and the old origin's time; a late failed `.bin` writes "Times unavailable for <old>" into `#where`, permanent on a coarse pointer. C5's generation counter is the fix; it must also cover the `.catch` at 495-499 and the `hoverFailed` assignment. One-line reference: **C5** (web plan, cycle 2).

### Low

**TR-8 — C7 missed `renderPins`: the pin row says "loading…" for ever after a failed origin fetch**
- Severity Low · Confidence High · Status Confirmed · Effort S
- Where: `web/app.js:760` (read 752-784) vs `:714-717`.
- Fix: `t === undefined ? (hoverFailed === active ? "unavailable" : "loading…") : …`. Cross-reference C3 for the value/outline/colour disagreement and C13 for the tap path.

**TR-9 — Eight orphaned `build-all` workers from the polars-deadlocked run are still alive; nothing detects stale workers before or during a build**
- Severity Low · Confidence High · Status Confirmed · Effort S
- Where: `cli.py:204-218`; `ps`: pids 12633-12640, ppid 1, started Sep 9 18:46:54, `SN`, 0 % CPU, RSS ~10 MB each (paged out; each inherited the ~1 GB graph copy-on-write).
- Chain: a parent that is SIGKILLed (or dies any way that skips `Pool.__exit__`) never calls `terminate()`; workers blocked in native code keep running under launchd. A later build competes with them for memory and, if one ever wakes, for `dist/origins/*` writes.
- Fix: at the top of `_build_all`, list other `transport-maps build-all` processes and refuse (or warn loudly); in `_solve_one_forked`, exit when `os.getppid() == 1`. Cleaning up the eight is the owner's call (CLAUDE.md destructive-action rule).

**TR-10 — `rail_detail` folds any table index ≥ 65,535 into `NO_RAIL` silently**
- Severity Low · Confidence High · Status Confirmed (latent: Seoul's table is 2,018 rows) · Effort S
- Where: `src/transport_maps/emit/rail_detail.py:108`.
- Fix: `assert len(table) < NO_RAIL` (or raise) before the write.

**TR-11 — `native_edges` marks the unsplit side of every split seam incomplete, so the cover gate never samples it**
- Severity Low · Confidence High · Status Confirmed · Effort S
- Where: `src/transport_maps/contour/grid.py:110-124`; `src/transport_maps/validate.py:70-73`.
- Chain: a base cell whose ring neighbour is a split base cell finds it absent from `pos`, is not `fine`, and is marked `complete = False` even though the cross edges from that cell's children join it; `check_bands_cover` then excludes it from the native-level sample at exactly the seam `_native_features` (`bands.py:234-243`) papers over with the parent hexagon.
- Fix: in the base-cell branch, treat a missing neighbour as resolved when any of its `FINE_RES` children is in `pos`. Mutation: remove the parent-under-children painting in `_native_features` → the gate must go red on a mixed fixture; today it may not.

**TR-12 — Cache provenance: G1 confirmed, plus the parsed per-item caches, the dead polyfill helper and a stale `routes.parquet` in use**
- Severity Low · Confidence High · Status Confirmed · Effort M (folds into G1)
- Where: table in T5; `data/build/routes.parquet` (Sep 3 17:42) older than `airports_c35abade.parquet` (Sep 3 22:19); `landmask.py:181-207` dead; `tests/sources/test_cache_provenance.py` covers three constants.
- Fix: G1 as planned, extended with a `PARSER_VERSION` stamp in `airline_destinations.json`/`wikidata_iata.json` (or a key per entry), deletion of `_cells_touching` or a stamp naming the method, and provenance cases for `urban_mask`, `ferry_links`, `rail_routes`, `routes`, `cell_country`, `grid` — each with the "change the constant, cache still hits" mutation.

### Consolidated table

| ID | Title | Sev | Conf | Status | Effort | Cycle-1 ref |
|---|---|---|---|---|---|---|
| TR-1 | Signal-killed worker still hangs `build-all` | H | H | Confirmed | S | extends A3 |
| TR-4 | Page never checks array length vs `hover_cells.bin` | H | H | Confirmed | S | new (defence for A6/A6d) |
| TR-2 | Snap blind to split cells: KKJ dropped, BOO 11 km off | M | H | Confirmed | S | new (bf9e5cc) |
| TR-3 | Snap invisible at INFO; drop bound weakened; stale comment | M | H | Confirmed | S | new (bf9e5cc) |
| TR-5 | Gate reads last-written `index.json`, no pmtiles check, no build lock | M | H | Confirmed | S | new evidence for A6b/A6c |
| TR-6 | Cross-device `shutil.move` truncates `.pmtiles` | M | H | Confirmed | S | A6a (pmtiles half) |
| TR-7 | Origin-switch race: unguarded set and misattribution | M | H | Confirmed | S | C5 |
| TR-8 | `renderPins` "loading…" after a failed fetch | L | H | Confirmed | S | C7 gap |
| TR-9 | Orphaned workers undetected | L | H | Confirmed | S | new |
| TR-10 | `NO_RAIL` fold silent | L | H | Confirmed | S | new (latent) |
| TR-11 | Cover gate skips the unsplit side of split seams | L | H | Confirmed | S | new |
| TR-12 | Provenance: parsed caches, dead helper, stale routes | L | H | Confirmed | M | G1 |

Cycle-1 items re-confirmed without new severity (one line each): **A6a/b/c/d** (T3, T6 — the mid-build `dist/` and the rsync order are the live evidence), **A13/C8/D19** (T7), **C3/C13** (T2), **C5** (T1 → TR-7), **G1/G2** (T5 → TR-12), **I4** (`las-vegas.pmtiles-journal` still in `dist/origins`), **H10** (tippecanoe temp files; TR-6 is the destination half).

---

## Final sweep

- Every flow has a conclusion: T1 (H2: four unguarded fetches), T2 (three cells; C7 misses `renderPins`), T3 (signal death hangs; `dist/` mixed by construction; count difference = `land_cells` universe), T4 (A4 complete; snap never crosses a country here, always crosses unmapped ground, blind to split cells), T5 (G1 confirmed and extended; test proves three constants), T6 (root files first, origins for minutes; widths match), T7 (four notations; `NO_RAIL` fold), T8 (seam blind spot).
- Files opened: listed in the inventory above; every line range cited was read in this session.
- Could not decide from code alone, and what would decide it:
  - Whether the "seven `console.error("Error")` on load" (D17) are MapLibre tile-fetch errors from a truncated or mid-copy `.pmtiles` (TR-6): a browser session with the network panel open during a rebuild would decide; not run (single browser session held by the designer reviewer).
  - The user-visible size of the TR-7 window on a real mobile link: a throttled-network trace; the code and file sizes bound it at a few seconds.
  - Whether macOS ever signal-kills a worker under memory pressure on this host (it usually swaps): TR-1 is confirmed for any signal death regardless; the OOM path specifically would be decided by a `log show --predicate 'eventMessage contains "memorystatus"'` after a build that ran short.
  - Whether the eight orphans still hold `dist/origins` files open: `lsof -p 12633` would decide; not run (it is harmless to read, but was not needed for the finding).
- Nothing under `dist/`, `data/` or the repo tree was written; the two probe scripts and their outputs live in the scratchpad.
