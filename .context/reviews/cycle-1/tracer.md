# Tracer review — causal traces of the transport-maps pipeline

Read-only review of `/Users/hletrd/flash-shared/transport-maps` at commit `fcb4d2a`
(branch `feat/transport-pipeline`, working tree with uncommitted edits to
`sources/_utils.py`, `sources/airports.py`, `sources/landmask.py`, `sources/roads.py`).
Every claim below was validated against the code, not the comments or the tests.
Where a hypothesis could be checked with a read-only probe (Python against
`dist/`, an in-process synthetic graph, a throwaway multiprocessing pool), it was;
the probe results are quoted inline. Nothing under `dist/`, `data/` or the source
tree was modified.

Key context discovered while tracing: `dist/` (index.json `solveRes: 5`, files dated
2026-09-09 22:28–23:18) predates the resolution-6/7 refinement commits
(`1a4d66b`, `1b5333c`, 23:44–23:57). The refined pipeline has never produced a
`dist/` and, as shipped, cannot (TR-1).

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 1 | TR-1 |
| High | 3 | TR-2, TR-3, TR-4 |
| Medium | 7 | TR-5, TR-6, TR-7, TR-8, TR-9, TR-10, TR-11 |
| Low | 9 | TR-12 … TR-20 |

Top five: **TR-1** `graph/nodes.py` uses `np` without importing numpy — `build_index()` and every default-constructed `NodeIndex` raise `NameError` (probe-confirmed); **TR-2** a ferry between a fine cell and its adjacent unsplit base cell duplicates the ground cross edge and `build_graph` aborts (probe-confirmed); **TR-3** the coverage gate's `SystemExit` inside a forked pool worker hangs `build-all` forever (probe-confirmed); **TR-4** `build-all` writes `hover_cells.bin` before any origin and overwrites `dist/origins/*` in place, so `dist/` is a mixed build during every run and permanently after an abort; **TR-5** the page's "Onward from X, of which:" itemises surface minutes accumulated over the *whole* journey, so the parts exceed the header in 84 % of Seoul's flight-reached cells.

---

## Flow traces

Notation: each hop is `file:line` → what it must guarantee (invariant) → where it can break.
"H1/H2" are the competing hypotheses considered at the most suspicious hop, with the one
the code supports marked.

### (a) Cell identity: land mask → refine → index → solve → hover array → page lookup

1. `sources/landmask.py:210-235` `land_cells(res)` — the universe is every H3 cell at
   `res` that *overlaps* Natural Earth land (minus lakes, plus ice shelves and a
   pole disk), returned **sorted by string** and cached at
   `land_cells_r{res}_{stamp}.parquet` (`:169-178`, stamp covers URLs and the
   Antarctic constants). Invariant: deterministic, sorted, one resolution.
   `_cells_touching` (`:181-207`) is dead code — never called.
2. `graph/nodes.py:116-122` `build_index` — base cells at `config.SOLVE_RES` (6),
   `refine.dense_mask` on `roads.cell_class(base)` | `urban.urban_mask(base)`,
   then `refine.refine` (`graph/refine.py:34-53`): unsplit base cells first in base
   order, then the 7 res-7 children of each split cell grouped by parent;
   `base_index[i]` maps every cell to its base position; `fine[i]` flags children.
   Invariant: `cells` is a partition of the base universe (each base cell either
   present itself or as exactly 7 children). Holds by construction.
   **Break: `nodes.py:124` `np.flatnonzero(split)` — `np` is never imported in
   this module** (imports at `:21-27`; `git log -S"import numpy"` shows it never
   was). Probe: `NodeIndex([], [], {}, {}, {})` → `NameError: name 'np' is not
   defined` from the `default_factory` at `:61`; `build_index.__code__.co_names`
   contains `np` and `nodes.__dict__` does not. → **TR-1**.
   H1 "annotations are lazy in 3.14 so it works": the module *imports*, but the
   lambda at `:61` and the call at `:124` execute at runtime — refuted.
   H2 "some caller monkeypatches `nodes.np`": grep finds none — refuted.
3. `nodes.py:82-88 / 126-128` `cell_at(lat, lon)` — the fine cell where the base
   cell is split, else the base cell. Used for airports (`:135`), stations
   (`:173`), origins (`solve/dijkstra.py:23-29`) and ferry endpoints
   (`graph/build.py:295-296`). Invariant: every lat/lon maps to the one cell of
   the mixed grid that contains it. Holds.
4. `graph/ground.py:120-130` `hex_edges` — same-resolution ring neighbours, plus
   for a fine cell whose res-7 neighbour is absent, the edge to that neighbour's
   res-6 parent, both directions, de-duplicated by `cross`. Invariant: the mixed
   grid is connected across the split/unsplit boundary exactly once per pair.
   Holds (the unsplit side never sees the split cell — `try_cell_index` of a split
   base returns `None` — so the pair is only ever added from the fine side).
   `contour/grid.py:108-122 native_edges` mirrors this rule for rendering.
5. `solve/dijkstra.py:11-20` — `scipy` Dijkstra over the CSR, `distances[:n_cells]`
   is the surface (nodes.py layout: cells, dep airports, arr airports, stations).
6. `emit/hover.py:25-27` `hover_cells(idx)` — `sorted({cell_to_parent(c, 4)})`,
   and `emit/index.py:91-99` writes the same list as little-endian `uint64`
   (8-byte entries). `hover.py:30-55` picks, per res-4 parent, the res-6 centre
   child; if that base cell was split, its res-7 centre child (`:53`); else the
   fastest child. `hover.py:67-69` encodes `min(minutes, 65534)` or `65535`.
   Invariant: `.bin[i]` describes `hover_cells[i]`; H3 string order equals
   numeric order (fixed 15-char lowercase hex). Probe on `dist/`: 90,659 entries,
   strictly increasing as `uint64`, all res 4; `seoul.bin` has 90,659 `uint16`.
   `modes.py:98`, `itinerary.py:57`, `rail_detail.py:65` recompute the identical
   expression instead of calling `hover.hover_cells` (duplication, see sweep).
7. `web/app.js:38-41` reads `hover_cells.bin` as `BigUint64Array` (platform
   endianness — little-endian everywhere the page runs); `:453-463 cellIndex`
   computes `h3.latLngToCell(lat, lon, HOVER_RES)` with `HOVER_RES =
   meta.hoverRes ?? 4` (`:30`), converts via `BigInt("0x"+…)` and binary-searches;
   `:465-468 lookup` returns `hoverTimes[i]`; `:446` treats `>= UNREACHABLE`
   (`meta.unreachable ?? 65535`, `:29`) as "no route".
   Hypotheses tested:
   - Mixed-resolution grid vs a page assuming one resolution — the page only uses
     `solveRes` to draw the hover outline (`:335-336`); with `solveRes: 6` after
     the next build it will outline a 5.6 km hex over a surface solved at 2.1 km
     in every refined region (`fineRes` is emitted at `index.py:126` but unused).
     Cosmetic → **TR-15**. The lookup itself is resolution-agnostic (res 4). ✔
   - Ordering mismatch — refuted (sorted string == sorted numeric; verified). ✔
   - Sentinel — `65535` flows from `config.UNREACHABLE` → `index.json` → page. ✔
     `emit/modes.py:27`, `itinerary.py:18`, `rail_detail.py:20` and
     `app.js:106, 645` hard-code `65534/0xFFFF` instead (sweep).
   - uint16 overflow — times > 65,534 min are clamped to 65,534 and the page
     shows "45 days 10h" rather than "no route" (`hover.py:22, 67`;
     `app.js:446-451`). Seoul's largest finite time today is 16,676 min so it is
     latent → **TR-14**.

### (b) Bands: `contour/bands.py` → `emit/tiles.py` → page style and legend

1. `config.py:24` `BAND_EDGES_MIN` — 36 upper edges, 30 min … 4320 min (72 h);
   `bands.band_indices` (`bands.py:50-56`) gives k ∈ [0, 36] with 36 the open
   band and 37 "unreachable". `_feature` (`:170-188`) emits `band = k`, or `-1`
   for unreachable, and `max_minutes` (never read by the page). The design spec
   (`docs/superpowers/specs/…design.md:248-252`) still specifies eleven bands
   with 10 edges; CLAUDE.md says 37 bands; `config.py:19` still says "The 11th
   band is open-ended". The 36-edge ladder is the code's truth and `index.json`
   carries it (`emit/index.py:122`), so the page and the emitter cannot disagree
   on the *values* — only the prose is stale.
2. Nesting and rims: `_base_features` (`:213-223`) emits, per LOD, the cumulative
   region `band <= k` minus `_interior` (`:191-202`, cells whose own band and
   every neighbour's band within `rim` hops are faster); `_native_features`
   (`:226-254`) does the same on the mixed grid and underlays each split parent
   painted in the *slowest* of its children's bands; `_coarse_features`
   (`:257-282`) is fully cumulative at res 4. Invariant: neighbouring bands
   overlap by whole cells so smoothing cannot open a gap; `validate.check_bands_cover`
   samples hex vertices per LOD (`validate.py:48-95`). Consistent.
3. `LODS` (`bands.py:155-160`): native z7+, base z5-6 and z3-4, coarse z0-2, via
   per-feature `tippecanoe.minzoom/maxzoom`; `emit/tiles.py:19` stores z0-8 in
   layer `"bands"` (`:20`). The page overzooms to 11 (`app.js:260`).
4. Page: `paintOrigin` (`app.js:375-393`) adds source `pmtiles://./origins/{slug}.pmtiles`,
   `"source-layer": "bands"`, `fill-sort-key` = `-band` (unreachable `-1000`) so
   faster paints on top; `bandColorExpression` (`:368-373`) matches
   `band ∈ [0, 36]` to `BANDS[i]` and `-1` to `UNCHARTED`. `N_BANDS =
   edges.length + 1 = 37` (`:98`), `expandRamp` (`:90-97`) interpolates each
   11-anchor scheme to 37 colours in OKLab, `paintLegend` (`:122-127`) draws 37
   swatches. So the ramp has exactly as many steps as bands. ✔
5. Legend ticks (`app.js:132-143`): fed from `index.json` (`EDGES`), not
   hard-coded; each tick at `left = (i+1)/37` which *is* edge i's true boundary.
   **Break:** the label chosen for a tick is the nearest round hour within 8 %,
   and the de-duplication keeps the *first* edge within 8 % of that hour. Probe
   (replicating the JS on the shipped edges): "4" at 225 min (3.75 h), "8" at
   465 min (7.75 h), "48" at 3020 min (50.3 h) and **"72+" at edge 34 = 4025 min
   (67.1 h, left 94.6 %) instead of edge 35 = 4320 min (72 h, 97.3 %)** — the
   "72+" label sits one band left of where the open band starts → **TR-7**.
   H1 "the ladder has no 72 h edge so approximation is unavoidable": refuted,
   4320 = 72 h exactly; the dedupe picks 4025 because it is *also* within 8 %.

### (c) Modes and itinerary: `emit/modes.py`, `emit/itinerary.py`, `emit/rail_detail.py`, `emit/routes_json.py`, `emit/airports_json.py` → page

1. `modes.py:41-88` `mode_minutes_per_node` walks nodes in distance order,
   `acc[node] = acc[prev]` then adds the edge cost to a channel by node kinds:
   cell→cell is road (channel by `cell_class[node]`, `ROAD_CHANNEL` `:26`) when
   `_ground_adjacent` (`:30-38`, base-parent adjacency) else ferry; any station
   endpoint is rail; airport edges are not counted. `write_modes` (`:91-110`)
   takes the same representative child as hover and writes 6 × `uint16` = 12
   bytes per hover cell in `CHANNELS` order (`:23`). Page reads
   `hoverModes[i*6+k]` with an identical literal `names` array (`app.js:520-523`).
   Invariant: the six numbers describe the surface part of *the* journey the
   hover time refers to. Holds for the accumulation; **breaks at presentation**:
   because `acc` is inherited through `A_dep`/`B_arr` nodes, `acc[dest]` includes
   the drive/rail to the *first* airport, yet the page prints the parts under
   "Onward from <landed>, of which:" with header `total − landed.min`
   (`app.js:545-550`). Probe on Seoul: 81,626 flight-reached hover cells, in
   **68,794 (84.3 %)** the itemised parts exceed the header (e.g. LYR: header
   2 793 min, parts rail 56 + ferry 116 + track 2 655 = 2 827) → **TR-5**.
   H1 "the page subtracts pre-flight ground": no such code — refuted.
   H2 "modes are onward-only by construction": `acc[node] = acc[prev]` at `:71`
   applies to every node kind — refuted.
2. Ferry-vs-road classification (`modes.py:30-38`): two fine cells in adjacent
   base parents that are *not* res-7 ring neighbours can be joined by a real
   ferry (`build.py:306` only skips same-resolution ring neighbours) and are
   then reported as road → **TR-13** (Low).
3. `itinerary.py:21-46` records per node the last arrival-airport node on its
   path; `write_itinerary` emits `node − first_arrival` (`:68`) or `0xFFFF`.
   `routes_json.py:31-37` emits dep *and* arr nodes with `prev`; `offsets`
   (`:42-50`) give `airports = n_cells`, `stations = n_cells + 2·n_air`. Page
   `legsTo` (`app.js:473-489`) rebuilds the arr id as `airports + count + ordinal`
   with `count = (stations − airports)/2` — consistent with `nodes.py:94-100` —
   and walks `prev` until it meets an id not in the file (a cell).
   **Break:** when a departure airport is reached *overland from a previous
   flight's arrival* (`B_arr → cell → … → C_dep`, the only way to change airport
   since `_transfer_edges` joins arr→dep of the *same* airport only,
   `build.py:206-207`), the walk stops at `C_dep` and the earlier flight(s)
   vanish; the first row then reads "To C, and through the airport — 6h24".
   Probe on Seoul: **779 dep airports** are entered from a cell whose hover cell
   was itself reached by an earlier flight into a different airport (IZO via YGJ,
   ITM via KIX, NKM via NGO, …), and **1,991 of 81,626** flight-reached hover
   cells display a truncated chain → **TR-6**. Rail nodes are never emitted
   (`routes_json.py:38-39` still says "added in Task 9"), so a rail leg between
   flights is likewise invisible.
4. `rail_detail.py:60-93`: `.rail.bin` is a `uint16` index into `.rail.json`'s
   `[station, line]` table, station name = first OSM stop name for that res-9 key
   (`:73-74`, falling back to the *route* name when the stop node is unnamed,
   `osm.py:89`), line = route name of the `(came_from, station)` pair (`:43-57`).
   Index ≥ 65,535 collides with `NO_RAIL` (`:91`) — only if an origin uses more
   than 65,535 distinct (station, line) pairs; not a realistic size. The page
   (`app.js:646-653`) appends " via <station> (<line>)" to the rail row. Optional
   on the page and in `deploy_verify.sh:18-23`. Sound.
5. `airports_json.py:16-19` columns `[iata, name, country, lat, lon, size]`;
   page `ap()` (`app.js:505-508`) reads `[1]`, `[2]` → "Incheon International
   Airport, KR". Sound. Leg times telescope (`dep.min − arr.min` etc.,
   `app.js:538-556`) so rows always sum to "Door to door" — except the
   "of which" parts (TR-5).

### (d) Air model: crawl → Wikidata → OurAirports → block time / frequency → transfers

1. `sources/routes.py:240-286` `route_network` — pairs are added in **both**
   directions (`:270-271`), a 20,000-pair floor and the ICN–NRT sanity pair
   guard the result; `_refuse_partial` (`_utils.py:92-109`) aborts if any
   airport (`:251-254`) or title (`wikidata.py:213-216`) is unresolved, so a
   partial crawl never reaches `routes.parquet`. ✔ (Cache keying: TR-9.)
2. `sources/airports.py:45-75` — size from OurAirports `type`, `country` is the
   ISO-2 `iso_country`.
3. `graph/build.py:47-133` `_air_edges` — per directed pair: great-circle
   distance, `is_geographically_plausible` (`:40-44`), `air.block_time_min`
   (`graph/air.py:48-52`: taxi-out[dep] + 15 + 60·d/844 + taxi-in[arr]), plus
   `transfers.border_min(max size)` when `transfers.crosses_border(country1,
   country2)` (`transfers.py:30-31`, Schengen and CTA collapsed). Edge
   `A_dep → B_arr`. Because the network is symmetric and `crosses_border` is
   symmetric, both directions carry the same border charge. ✔
4. `_access_edges` (`:136-160`): `cell → A_dep` = processing[size],
   `A_arr → cell` = disembark[size]. Once per airport, trip-independent. ✔
5. `_transfer_edges` (`:163-213`): `A_arr → A_dep` = `max(MCT[size],
   median(expected wait over A's outbound routes))`, where
   `air.frequency_model` (`air.py:82-96`) is `base·w·w·max(d, 400)^-1.10`
   floored at 0.5/week and `expected_wait_min` (`:55-60`) is headway/2. Only
   here, so a first flight pays no wait (documented "leave now" semantics,
   `index.html:407-408`). ✔ Knee: `max(distance_km, KNEE_KM)` — bounded at both
   ends as claimed.
   Penalty ledger for `cell → A_dep → B_arr → B_dep → C_arr → cell`:
   processing once, block+border per flight, connection once at B, disembark
   once. Nothing is double-charged; nothing is charged in the wrong direction.
   Two modelling caveats, not bugs: the connection wait is B's *median* outbound
   headway rather than the specific onward route's (a thin long-haul connection
   at a busy hub is under-waited), and border control is charged on every
   zone-crossing flight so a transit passenger (ICN→NRT→FRA) pays two desks
   → **TR-17** (Low).
   H1 "border charged on access edges and flight edges both": refuted —
   `_access_edges` charges only processing/disembark (`:151-152`).

### (e) Ground / rail / ferry: `sources/roads.py`, `sources/osm.py`, `graph/ground.py`, `graph/rail.py`, `graph/build.py`

1. `roads.py:63-94` — best GRIP4 class per 5-arcmin pixel (cached,
   stamped with threshold/shape); `cell_class` (`:97-133`) takes the best class in
   the cell's bounding box; `ground.cell_class` (`ground.py:37-44`) computes it on
   the base grid and expands through `base_index`. `cell_speed_kmh` (`:53-71`)
   = `SPEED_BY_ROAD_CLASS_KMH[class]`, halved where urban and class > 0.
2. `ground.hex_edges` (`:74-141`) — edge `u→v` costs `haversine(centroids)/speed[v]·60`
   plus `land_border.crossing_min` when the immigration zones differ, and is
   *cut* when `countries.is_closed`. Both directions arise from the outer loop;
   cross-resolution pairs are added once each way. `validate.check_monotonic_ground`
   (`validate.py:98-161`) re-derives the same cost but only for same-resolution
   neighbours (`:142-147`), so it never inspects a cross-resolution edge →
   **TR-19** (Low).
3. `graph/rail.py:68-113` — stations merged at res 9, `ride_edges` between
   consecutive stops *within* a route (`shift(-1).over("route_id")`), fastest
   service per pair; `build._rail_edges` (`build.py:232-276`) symmetrises with the
   faster direction, applies the same border rules, adds `cell→station` boarding
   and `station→cell` alighting once per station. Every station has exactly one
   boarding and one alighting edge; rides are undirected pairs → no duplicates.
   ✔
4. Ferries. `tests/graph/test_ferry.py` exists; the code is
   `sources/osm.py:95-163` (`ferry_links`, endpoints of `route=ferry` ways) and
   `graph/build.py:279-334` `_ferry_edges` (direct cell↔cell edges, quickest per
   direction, terminal + border once). **Break at `build.py:306`:** the
   "already joined by the ground network" test is
   `idx.cells[v] in h3.grid_disk(idx.cells[u], 1)`, evaluated at *u's*
   resolution. A fine cell (res 7) and its adjacent unsplit base cell (res 6)
   are joined by `hex_edges` (`ground.py:125-130`) but `grid_disk` of a res-7
   cell can never contain a res-6 id, so the ferry edge is emitted as well and
   `build_graph`'s duplicate check (`build.py:381-386`) raises. Probe with a
   synthetic index (one split base cell beside one unsplit, ferry between the
   3.5 km-apart centroids, border/speed functions stubbed in-process): ground
   cross edge present, ferry emits `(5,0),(0,5)`, 2 duplicate keys →
   `RuntimeError` → **TR-2**. `emit/modes._ground_adjacent` already encodes the
   correct test and says "adjacent" for the same pair.
   H1 "MIN_FERRY_KM keeps such crossings out": refuted — 1 km floor
   (`osm.py:101`) vs 2.1–5.6 km cells.
   H2 "the duplicate check is what should catch it": it does, by aborting the
   whole build — that is the failure, not the safeguard.
   Silent drops: endpoints off the land mask, same cell, same-res neighbours and
   out-of-range crossings are `continue`d without a counter (`:293-307`); only
   closed-border cuts are logged (`:317-318`) → **TR-12** (Low).
5. `build_graph` (`:337-389`): all parts concatenated, non-positive/non-finite
   weights refused, duplicates refused. No class is dropped silently *here*;
   the silent drops live upstream (nodes.py airports — now bounded; ferries —
   not).

### (f) CLI and parallelism: `cli.py`, `dist/` assembly, `deploy_verify.sh`, `browser_verify.sh`

1. `cli.py:132-201` `_build_all` — graph built once, gates run
   (`validate.check_airport_connectivity`), shared arrays computed in the parent,
   `index.write_hover_cells` written **immediately** (`:175`), then origins are
   solved either serially or by a **forked** `multiprocessing.Pool`
   (`:187-191`, `pool.imap`, chunksize 1 → dynamic partitioning, results in
   order), and `index.json` last (`:201`), skipped under `--limit`.
   Workers are not `python -m transport_maps.cli` spawns; they are forks that
   read `globals()["_CTX"]` (`:110-113`).
   **Break 1:** `_solve_one` raises `SystemExit` when coverage is below 90 %
   (`:84-87`). `multiprocessing.pool.worker` catches only `Exception`; a
   `SystemExit` kills the worker process, the pool respawns a worker, and the
   lost task's result never arrives, so `imap` blocks forever. Probe (2-worker
   fork pool, one task raising `SystemExit`): `imap` hung after the first
   result; `next(timeout=6)` timed out → **TR-3**. Every other gate raises
   `ValueError`/`RuntimeError`, which does propagate and abort.
   **Break 2:** every per-origin writer overwrites `dist/origins/{slug}.*` in
   place, non-atomically (`hover.py:71 write_bytes`, `itinerary.py:71`,
   `modes.py:110`, `rail_detail.py:91-92`, `routes_json.py:54`; `tiles.py:70`
   `shutil.move` from local tmp onto NFS is a copy — the destination is
   truncated then refilled), and `hover_cells.bin` is rewritten first. From the
   first second of a run until the last origin is rewritten, `dist/` pairs a new
   ordering with old arrays; an abort (e.g. TR-1, TR-2, TR-3, a tippecanoe
   failure) leaves it that way permanently, and `dist/origins/las-vegas.pmtiles-journal`
   is a fossil of exactly such an abort. Not resumable: a re-run re-solves all
   origins. → **TR-4**.
2. `cli.py:253-263` `index` subcommand rewrites `index.json` from
   `data/origins.toml` (**553** entries today) and `hover_cells.bin` from a fresh
   index without checking that any per-origin file exists or matches →
   **TR-11**.
3. `scripts/deploy_verify.sh:9-37` — checks every listed origin has
   `.bin/.air.bin/.modes.bin` of `size/width == len(hover_cells)` and a
   `.pmtiles`; `.rail.bin` optional. This catches a *count* mismatch (and would
   catch the res-5→6 change), not a same-count different-set mismatch, and it
   never runs against the local preview. Then `rsync web/ dist/` and
   `rsync --delete dist/ → server`.
4. `scripts/browser_verify.sh:18-19,41` hard-codes **157 cities, 37 swatches,
   12 schemes**. Today: `dist/index.json` has 157 origins, `app.js` has 12
   `RAMPS` and 37 = 36+1 swatches → all match the shipped dist. But
   `data/origins.toml` now has 553 `[[origin]]` blocks and `web/index.html`
   already claims "553 cities" in seven places (`:15,23,31,41,42,375,421`) while
   the live/preview `index.json` says 157 → **TR-8**.

### (g) Cache provenance: `_params_hash` and every cache under `sources/*`

| Cache | Key | Verdict |
|---|---|---|
| `landmask` cells parquet (`landmask.py:169-178`) | res in name + URLs, Antarctic constants | ✔ |
| `landmask` raw zips (`:49-56`), `airports` raw csv (`airports.py:23-31`), `countries` zip, `places`, `borders`, `water` | fixed filename, bare `.exists()` | raw downloads — acceptable, but the *derived* caches stamp the URL while the raw file does not, so a URL change rebuilds from the stale download → **TR-16** (Low) |
| `airports` table (`airports.py:33-42`) | URL, `SIZE_BY_TYPE`, required columns | ✔ |
| `routes.parquet` (`routes.py:242-244`) | **bare `.exists()`** | ✗ **TR-9** |
| `airline_destinations.json` (`routes.py:169-187, 227`) | per IATA, stores *parsed* titles | ✗ parser constants (`_SECTION_RE`, `_CARGO_RE`, `_SKIP_PREFIXES`, `_strip_cargo_subsections`) never invalidate it → **TR-9** |
| `wikidata_iata.json` (`wikidata.py:160-165`) | per title | acceptable (raw resolution result); `IATA_PROPERTY` not stamped |
| `road_class_grid_*.npy` (`roads.py:52-60`) | threshold, shape, N_TYPES | ✔ (URL not stamped, Low) |
| `urban_mask-*.parquet` (`urban.py:49-55`) | pop, radius, **len(cells), first, last** | ✗ not the cell list; `countries.py:93-96` rejects this very pattern → **TR-10** |
| `cell_country-*.parquet` (`countries.py:93-99`) | URL, fill method, sha256 of all cells | ✔ |
| `rail_routes-*.parquet` (`osm.py:175-185`) | file fingerprints + parse constants | ✔ |
| `ferry_links-*.parquet` (`osm.py:151-155`) | file fingerprints only | `ANTIMERIDIAN_EPS_DEG` applied at parse time is not stamped (Low, folded into TR-16) |
| `render-grid-*.npz`, `native-edges-*.npz` (`contour/grid.py:42-47, 95-99`) | version + all cells | ✔ |

---

## Findings (ordered by severity)

### TR-1 — `graph/nodes.py` uses `np` without importing numpy; `build_index()` cannot run
- **Severity:** Critical · **Confidence:** High · **Status:** Confirmed (probe)
- **Trace:** `cli.py:140 / :237 / :256` → `nodes.build_index` → `nodes.py:119-122` (fine) → **`nodes.py:124` `np.flatnonzero(split)` → `NameError`**. Also `nodes.py:61-62` default factories `lambda: np.zeros(...)` → any `NodeIndex(...)` constructed without explicit `base_index`/`fine` raises the same error: `tests/graph/test_ferry.py`, `test_rail_integration.py`, `tests/sources/test_countries.py`, `test_urban.py` (7 constructions) and every module calling `build_index()` (`tests/test_golden.py`, `contour/test_bands.py`, `graph/test_build.py`, `test_ground.py`, `test_nodes.py`, `sources/test_roads.py`, `scripts/ground_check.py`, `scripts/calibrate_ground.py`).
- **Invariant violated:** the node index is constructible.
- **Failure scenario:** `transport-maps build-all` downloads/reads the land mask, spends the `roads.cell_class` and `urban_mask` passes, then dies with `NameError: name 'np' is not defined`. `data/build/land_cells_r6_dd95e3b5.parquet` (2026-09-10 00:07) shows the res-6 mask has been built; no res-6 `dist/` exists.
- **Fix:** add `import numpy as np` to `graph/nodes.py`; add a test that constructs `NodeIndex(cells, [], pos, {}, {})` with defaults and one that imports every module under `transport_maps` and instantiates each dataclass.

### TR-2 — Ferry between a fine cell and an adjacent unsplit base cell duplicates the ground edge; `build_graph` aborts
- **Severity:** High · **Confidence:** High · **Status:** Confirmed (synthetic probe)
- **Trace:** `osm.ferry_links` → `build._ferry_edges` `build.py:295-296` (endpoints via `cell_at`, one res 7, one res 6) → `:306` `grid_disk(u, 1)` at u's resolution cannot contain v → ferry edge `(u,v),(v,u)` emitted → `ground.hex_edges` `ground.py:125-130` emitted the same pair → `build_graph` `build.py:381-386` duplicate keys → `RuntimeError`.
- **Invariant violated:** "cells the ground network already joins are skipped" (`build.py:301-307`).
- **Failure scenario:** any OSM ferry ≥ 1 km whose terminals fall in a refined (urban/major-road) cell and the neighbouring unrefined cell — a harbour or river crossing from a town to its rural bank. The entire `build-all` dies after the graph is assembled.
- **Fix:** replace the `grid_disk` test with `emit.modes._ground_adjacent(idx.cells[u], idx.cells[v])` (move it to `graph/refine.py`), or build the set of ground `(row, col)` pairs once and skip any ferry pair in it; add a mixed-resolution case to `tests/graph/test_ferry.py`.

### TR-3 — `SystemExit` inside a forked pool worker hangs `build-all` forever
- **Severity:** High · **Confidence:** High · **Status:** Confirmed (probe)
- **Trace:** `cli.py:188-191` `ctx.Pool(workers).imap(_solve_one_forked, origins)` → `_solve_one_forked` `:110-113` → `_solve_one` → coverage gate `:84-87` `raise SystemExit(...)` → `multiprocessing.pool.worker` catches only `Exception` → worker exits → task lost → `imap` never yields.
- **Invariant violated:** "Aborts on the first failing gate" (`cli.py:134`).
- **Failure scenario:** one origin under 90 % coverage (an island origin, a bad land mask) — with ≥ 4 origins the run prints nothing more and never exits; with < 4 origins (serial path) it aborts correctly, so the smoke test cannot reproduce it.
- **Fix:** raise `ValueError` like the other gates; additionally wrap `_solve_one_forked` in `try/except BaseException as e: raise RuntimeError(...) from e`.

### TR-4 — `dist/` is a mixed build during every run and after every abort
- **Severity:** High · **Confidence:** High · **Status:** Confirmed (code + `dist/` timestamps and the `.pmtiles-journal` fossil)
- **Trace:** `cli.py:175` `write_hover_cells` before any origin → `cli.py:96-104` per-origin writers overwrite `dist/origins/*` in place (`hover.py:71`, `itinerary.py:71`, `modes.py:110`, `rail_detail.py:91-92`, `routes_json.py:54`, `tiles.py:70` cross-device `shutil.move` = truncate + copy) → `index.json` only at the end (`:201`).
- **Invariant violated:** CLAUDE.md "The per-origin arrays and `hover_cells.bin` must come from the same build"; `cli.py:134` "a partially written dist/ is worse than none".
- **Failure scenario:** the next `build-all` (res 6/7, different res-4 parent set) rewrites `hover_cells.bin` in the first minute; for the following hours the preview at `:8899` maps every old origin's `.bin` through the new ordering (wrong times, blank hover where lengths differ), and if the run aborts (TR-1/2/3, tippecanoe) that state is permanent. A `deploy_verify.sh` run during that window fails only if the *count* changed.
- **Fix:** write all outputs to a staging directory (`dist/.stage/`), write `hover_cells.bin` and `index.json` there last, and `os.rename` the origins directory + the two files into place at the end; use `_atomic_write` for every emitter (it exists in `sources/_utils.py`); delete `dist/origins/las-vegas.pmtiles-journal`.

### TR-5 — Route summary itemises whole-journey surface minutes under "Onward from X, of which:"
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed (84.3 % of Seoul's flight-reached hover cells)
- **Trace:** `modes.py:71` `acc[node] = acc[prev]` for every node kind → `acc[cell]` includes road/rail before the first `A_dep` → `write_modes :104-106` → page `app.js:517-526 surface()` → `:545-550` printed under a header of `total − landed.min`.
- **Invariant violated:** rows under "of which" must sum to at most the "Onward" header; times must add up.
- **Failure scenario:** Seoul → LYR: header "1 day 22h" (2 793 min), parts "1 day 20h by track, 1h56 by ferry, 56 min by rail" (2 827 min) — the reader sees a breakdown larger than its total; for short onward legs the parts can be several times the header.
- **Fix:** either reset the accumulator at arrival-airport nodes so the file is onward-only (and show the pre-flight ground separately from `chain[0].min`), or emit two 6-channel blocks (before first flight / after last), or relabel the page rows "Surface travel on this route" and drop the "of which" framing.

### TR-6 — Route chain drops earlier flights when the traveller changes airport overland
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed (779 dep airports, 1,991 hover cells from Seoul)
- **Trace:** `build.py:206-207` connection edges only within one airport → cross-airport transfer is `B_arr → cell → … → C_dep` → `routes_json.py:31-37` emits only airport nodes → `app.js:483-489` walk ends at the cell → `itinerary.py:41` records only the *last* arrival.
- **Invariant violated:** the displayed chain is the journey that produced the number.
- **Failure scenario:** Seoul → destination via KIX then a drive to ITM and an onward flight: the page prints "6h24 To ITM, and through the airport · Fly ITM → …", omitting ICN→KIX; the "To" row silently absorbs a flight.
- **Fix:** in `write_routes`, add `"via": <arr node id>` to each dep node whose access path passed through an arrival (use `itinerary.arrival_airport_per_node` on the dep node's cell predecessor); on the page, when `node.kind === "dep"` and `node.via` exists, continue the walk from `via` and print "Transfer <B> → <C> by surface". Emit station nodes too (`routes_json.py:38-39` is stale).

### TR-7 — Legend labels sit at the wrong band boundaries ("72+" one band early)
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed (JS replicated on shipped edges)
- **Trace:** `config.py:24` edges → `index.json` → `app.js:133-143`: `nearest` = first shown hour within 8 %; dedupe keeps the first edge within 8 % of that hour (`:139`).
- **Invariant violated:** CLAUDE.md "its ticks sit at their true band boundaries".
- **Failure scenario:** "72+" is drawn at the 4025-min (67 h) boundary at 94.6 % while the open band begins at 97.3 %; "4" marks 3 h 45, "8" marks 7 h 45, "48" marks 50 h 20. Every legend on the site is off by up to one band / 8 %.
- **Fix:** for each shown hour pick the edge with the smallest relative error (`argmin |edge/60 − h|/h`) instead of the first within 8 %, which alone moves "72+" to edge 35; then either label with the edge's true value (`3¾`, `7¾`, `50`) or choose `SHOWN_HOURS` from values that are exact edges (1, 2, 5, 24.5≈24, 72). Add a test in `tests/web/` that parses `SHOWN_HOURS` and asserts each label's edge is the nearest one.

### TR-8 — Hard-coded verification numbers and page copy disagree with `index.json` / `origins.toml`
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed
- **Trace:** `data/origins.toml` (553 origins, extended by `scripts/expand_origins.py`) → `emit/index.write_index` → `dist/index.json` (157, from the old build) → `browser_verify.sh:19` `"cities":157`; `web/index.html:15,23,31,41,42,375,421` "553 cities"; `:18-19, :41` 37 / 12 also literal.
- **Failure scenario:** the next full build ships 553 origins and `browser_verify.sh` fails on `cities`; meanwhile the deployed page's meta description, JSON-LD dataset and route hint promise 553 cities while 157 are selectable.
- **Fix:** have `browser_verify.sh` read `origins.length`, `bandEdgesMin.length+1` from the served `index.json` and count `Object.keys(RAMPS)` from the page; make the "N cities" copy a runtime substitution from `meta.origins.length` (or remove the number). Also fix the Route hint, which describes a two-click flow the page does not implement (`index.html:373-376` vs `app.js:689-698`).

### TR-9 — Route network caches are not provenance-keyed
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed
- **Trace:** `routes.py:242-244` `routes.parquet` bare `.exists()`; `routes.py:227` caches `parse_destinations(wikitext)` output per IATA in `airline_destinations.json`; neither is keyed on `_SECTION_RE`, `_CARGO_RE`, `_SKIP_PREFIXES`, the cargo-stripping logic, the airports table stamp or `wikidata.IATA_PROPERTY`.
- **Invariant violated:** CLAUDE.md "Derived caches key on `_params_hash` of the constants and inputs that govern them, never on a bare `.exists()`."
- **Failure scenario:** `_strip_cargo_subsections` was added after the crawl (the JSON is dated 2026-09-03 17:38, `routes.parquet` 17:42); every airport crawled before it keeps its cargo destinations as passenger routes until someone deletes both files by hand — and a re-crawl is the expensive step the cache exists to avoid.
- **Fix:** name the parquet `routes_{_params_hash(parser constants, airports._table_cache_path().name, IATA_PROPERTY)}.parquet`; store raw wikitext (or a `parser_version` alongside parsed titles) in the destination cache and re-parse on version change.

### TR-10 — `urban_mask` cache keyed on count and end cells, not the cell list
- **Severity:** Medium · **Confidence:** Medium · **Status:** Likely
- **Trace:** `urban.py:51-52` key = `(POP_MIN, RADIUS, len(cells), cells[0], cells[-1])`; `countries.py:93-96` explicitly hashes every cell for the same reason. `PLACES_ZIP` is not stamped either.
- **Failure scenario:** a land-mask change that keeps the first and last cell and the count (lake subtraction swapping interior cells, a changed pole disk) silently reuses the mask built for the old universe, mis-assigning urban congestion to the wrong cells.
- **Fix:** `_params_hash(URBAN_POP_MIN, URBAN_RADIUS_KM, PLACES_ZIP, hashlib.sha256("".join(cells)))`.

### TR-11 — `index` subcommand can publish an `index.json` for origins that have no files
- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed (code)
- **Trace:** `cli.py:253-263` → `index.load_origins()` (553) → `write_index` and a fresh `write_hover_cells` with no look at `dist/origins`.
- **Failure scenario:** run after `expand_origins.py` → page lists 553 cities, 396 of them 404 on click ("Hover data unavailable"); combined with a grid change it pairs a new ordering with old arrays (TR-4 without even running a build).
- **Fix:** make `index` verify every origin's `.bin` exists and has `len(hover_cells)` entries (the `deploy_verify.sh` check, moved into Python), or remove the subcommand and let only `build-all` write `index.json`.

### TR-12 — Ferry crossings are dropped silently and unbounded
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Trace:** `build.py:293-307` four `continue`s without a counter; only `cut` is logged (`:317-318`).
- **Failure scenario:** a land-mask regression that puts piers in sea cells, or an `osm_rail.sh` filter change, removes hundreds of crossings with no log line; the connectivity gate counts airports, not islands.
- **Fix:** count each reason, log, expose like `rejected_air_pairs`, and bound the "endpoint off the land mask" fraction.

### TR-13 — Ferry minutes classed as road when the two cells' base parents are adjacent
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed (code)
- **Trace:** `modes.py:30-38` `_ground_adjacent` returns True for fine cells in adjacent base parents; `build.py:306` keeps a ferry between such cells when they are not res-7 ring neighbours.
- **Fix:** classify by membership in the ground edge set (pass the CSR or a set of ground pairs to `mode_minutes_per_node`), which also makes TR-2's test and this one the same code path.

### TR-14 — Times above 65,534 min display as a real duration, not "no route"
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed (latent; Seoul max 16,676 min)
- **Trace:** `hover.py:22, 67-68` clamp → `app.js:446-451` prints "45 days 10h".
- **Fix:** treat `>= MAX_MINUTES` as "over 72 h" on the page (the last band already is), or document the clamp in `index.json`.

### TR-15 — Hover outline drawn at `solveRes` on a mixed-resolution surface
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed (code)
- **Trace:** `index.py:125-126` emits `solveRes: 6`, `fineRes: 7` → `app.js:34-35, 335-336` uses only `solveRes`.
- **Fix:** ship the split base cells (a small `uint64` array) or highlight at `hoverRes` consistently; update the res-5 comment at `app.js:30-34`.

### TR-16 — Raw downloads cached by fixed name while derived caches stamp the URL
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Trace:** `airports.py:25-31` vs `:41`; `landmask.py:49-56` vs `:176-178`; `roads.py:31` (GRIP4_URL absent from `:59`); `osm.py:151-155` (`ANTIMERIDIAN_EPS_DEG` unstamped).
- **Fix:** include `_params_hash(url)` in the raw filename; stamp parse-time constants.

### TR-17 — Border control charged on every zone-crossing flight, including transits
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed (design)
- **Trace:** `build.py:92-93`; a Seoul → NRT → FRA journey pays 45 + 45 min although NRT is airside.
- **Fix:** document in `calibration.toml`; if modelled, charge the *arrival* half on `arr → cell` egress and the *departure* half on `cell → dep` access using the cell's country vs the airport's country (both known at edge-build time), which removes the transit double count.

### TR-18 — `solve` subcommand bypasses every gate and writes a different layout
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Trace:** `cli.py:233-252` writes `dist/{name}.pmtiles`, `.hover.bin`, `.routes.json` (not `origins/{slug}.bin`), no coverage/monotonic/cover checks, no modes/air/rail files.
- **Fix:** route it through `_solve_one` with an explicit output directory, or document it as a debug path that never touches `dist/`.

### TR-19 — Monotonic-ground gate is blind to cross-resolution edges
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- **Trace:** `validate.py:142-147` `h3.grid_disk(cell, 1)` at the cell's own resolution; `try_cell_index` returns None for the split/unsplit boundary, so the fine↔base edges of `ground.py:125-130` are never checked.
- **Fix:** reuse `contour.grid.native_edges` (already computed and shared) as the neighbour list.

### TR-20 — Dead code and stale constants that will mislead the next reader
- **Severity:** Low · **Confidence:** High · **Status:** Confirmed
- `landmask._cells_touching` (`landmask.py:181-207`) unused, and its docstring contradicts the polyfill actually used at `:226`; `transfers.STATION_ACCESS_MIN/EGRESS_MIN` defined twice (`transfers.py:8-9, 53-54`), unused; `band-seams` layer referenced (`app.js:376, 923-925`) but never created; `config.py:11` "548,557 land cells at ~253 km²" and `:19` "The 11th band" are res-5/11-band numbers; `hover.py:7`, `modes.py:95`, `itinerary.py:52`, `tiles.py:11`, `roads.py:100`, `countries.py:91`, `app.js:30-34, 573-576` still say res 5; `routes_json.py:38-39` says rail nodes come "in Task 9" although stations exist; `dist/origins/las-vegas.pmtiles-journal` is litter that `deploy_verify.sh` will rsync to production.

---

## Final sweep — cross-file constants, units, ordering

**Constants defined in two places (must be kept equal by hand):**
- Sentinel `65535`: `config.UNREACHABLE` ✔ → `index.json` → `app.js:29`; but `modes.py:27` (`65534`), `itinerary.py:18`, `rail_detail.py:20`, `app.js:106, 645` (`0xFFFF`) are literals.
- Hover ordering `sorted({cell_to_parent(c, HOVER_RES)})`: `hover.py:27`, `modes.py:98`, `itinerary.py:57`, `rail_detail.py:65` — four copies of the single contract that `index.py:97` also relies on. Make the three emitters call `hover.hover_cells`.
- Mode channel order: `modes.CHANNELS` (`modes.py:23`) vs `app.js:520` `names` vs `index.mode_detail()` keys (`index.py:109-116`) — three copies; ship `CHANNELS` in `index.json` and have the page read it.
- Layer/property names: `tiles.LAYER = "bands"` vs `app.js:381` `"source-layer": "bands"` and `browser_verify.sh:24,56`; `water.LAYER = "water"` vs `app.js:292`; property `"band"` (`bands.py:180`) vs `app.js:370, 387, 587`.
- Node layout (cells, dep, arr, stations): `nodes.py:94-100`, `routes_json.py:42-50`, `itinerary.py:32-33`, `modes.py:53-54`, `rail_detail.py:28`, `app.js:481-483` — six derivations of the same arithmetic, all currently consistent.
- Verification literals: `browser_verify.sh` 157 / 37 / 12 (TR-8); `index.html` "553".
- Byte widths: `deploy_verify.sh:18` `(.bin 2, .air.bin 2, .modes.bin 12, .rail.bin 2)` — matches the emitters today; a seventh mode channel would silently break it.
- Slug rules: `cli._SLUG_RE` `[A-Za-z0-9_-]` vs `expand_origins.slugify` `[a-z0-9-]` — compatible.

**Unit conversions at module boundaries (all checked, all minutes):** `air.block_time_min` (km, km/h → min, rounded to int); `expected_wait_min` (flights/week → min); `rail.ride_edges` `60·km·detour/kmh`; `_ferry_edges` `60·km/kmh + terminal`; `ground.hex_edges` `km/kmh·60`; `calibration.toml` section keys match the dataclass fields (`FerryCalibration(**…)`, `RailCalibration(**…)`) — a renamed TOML key would fail loudly. Hover/modes/itinerary encode minutes as `uint16`; the page never rescales.

**Ordering assumptions between emitters and the page:** `hover_cells.bin` sorted `uint64` ✔ (verified on `dist/`); `.bin/.air.bin/.modes.bin/.rail.bin` in that order ✔; `routes.json` `nodes` keyed by `id` (order irrelevant) ✔; `places.json` largest-first — the page uses row index as rank (`app.js:164-167`) ✔ (`places.py:69-71`); `airports.json` sorted by IATA — the page does linear `find` ✔.

**Fork/parallelism sanity:** `POLARS_MAX_THREADS=1` set before imports ✔; everything polars/pyogrio-derived is computed in the parent ✔ (`countries.cell_country` is computed once in `cli.py:153` and again inside `build._border_rules` ×2 and `ground.hex_edges` — all before the fork); `roads.cell_class` is computed four times per build (`nodes.py:119`, `cli.py:148 → cell_speed_kmh`, `cli.py:156`, `build.py:358 → hex_edges → cell_speed_kmh`) — ~20 s wasted, not a bug.

---

## Coverage

Every file below was read in full unless marked *skimmed*.

- `CLAUDE.md`, `calibration.toml`, `pyproject.toml` (scripts/python version), `README.md` (grep for format claims), `data/origins.toml` (count only), `dist/index.json`, sizes/contents of `dist/hover_cells.bin`, `dist/origins/seoul.{bin,air.bin,modes.bin,json}`, `dist/airports.json`, `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md` (bands section only).
- `src/transport_maps/__init__.py`, `config.py`, `cli.py`, `validate.py`
- `src/transport_maps/calibrate/__init__.py`, `fit.py`, `ground.py`
- `src/transport_maps/contour/__init__.py`, `bands.py`, `grid.py`
- `src/transport_maps/emit/__init__.py`, `airports_json.py`, `borders.py`, `hover.py`, `index.py`, `itinerary.py`, `modes.py`, `places.py`, `rail_detail.py`, `routes_json.py`, `tiles.py`, `water.py`
- `src/transport_maps/graph/__init__.py`, `air.py`, `build.py`, `ground.py`, `nodes.py`, `rail.py`, `refine.py`, `transfers.py`
- `src/transport_maps/solve/__init__.py`, `dijkstra.py`
- `src/transport_maps/sources/__init__.py`, `_utils.py`, `airports.py`, `countries.py`, `landmask.py`, `osm.py`, `roads.py`, `routes.py`, `urban.py`, `wikidata.py`
- `scripts/browser_verify.sh`, `deploy_verify.sh`, `build_water_tiles.py`, `check_ramps.py`, `expand_origins.py`, `ground_check.py`, `osm_rail.sh`; `scripts/calibrate_ground.py` and `scripts/adsb_extract.py` *skimmed* (docstring, constants and function list — they feed `calibration.toml` and are outside the mandated flows; `calibrate_ground.py` calls `nodes.build_index()` and is therefore also broken by TR-1).
- `web/app.js`, `web/index.html`
- Tests were consulted only to locate code and to size TR-1's blast radius (`tests/graph/test_ferry.py` header, grep over `tests/`); no test was trusted as evidence of behaviour.

Probes run (all read-only; scripts in the session scratchpad): default-constructed `NodeIndex` (NameError), `hover_cells.bin` ordering/length vs Seoul arrays, modes-vs-onward comparison over Seoul, dep-node chain truncation over Seoul, legend tick replication, forked-pool `SystemExit` hang, synthetic mixed-resolution ferry/ground duplicate with border/speed functions stubbed in-process.
