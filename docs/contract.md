# Pipeline and page contract

What the pipeline writes, what the page and the solver service read, and
which side owns each part. Written for task J1 of
`plan/2026-09-10-c2-docs-attribution-calibration.md` (2026-10-02). The two
rules task S6 asked for are the last section.

The code is the authority. Where this file and a module disagree, the module
wins and this file is wrong. Each entry names the module, so a reader can
check. `tests/test_contract_doc.py` keeps the two in step: it fails when an
`index.json` key or a per-origin suffix exists on one side only.

## Owners

Three parties touch the contract.

- **Pipeline**: `src/transport_maps/`, run on the owner's Mac by
  `transport-maps build-all` (and `reindex`, `assets`). It writes every file
  below except `water.pmtiles`, which `scripts/build_water_tiles.py` writes
  once.
- **Page**: `web/app.js`. It reads `dist/` over HTTP and never writes it.
- **Service**: `src/transport_maps/service/`, the resident solver on the web
  host. It reads only the solver bundle and answers `GET /api/solve` and,
  since 2026-10-04, `GET /api/map` (`deploy/README.md`, "The on-demand
  solver"; "The map from a point" below).

The **writer** owns a format. If a layout changes, the writer changes first,
the reader follows in the same commit, and `contractVersion` goes up (see
"Versioning").

## Versioning

`index.json` carries `contractVersion`, an integer
(`emit/index.py:CONTRACT_VERSION`, now **2**). An `index.json` without the
field was written before it existed. Read that as version 1: the layout this
file describes, minus the fields each entry below marks as optional.

Raise the number when an existing field or file changes meaning, width or
order. Adding an optional field that an older page can ignore does not need a
new version.

`reindex` treats the number as *frozen*: it refuses to stamp today's version
over a dist/ whose `index.json` names another one, because that would tell the
page that old arrays have the new layout. An `index.json` without the field
still reindexes, as for every other frozen field.

The page knows the version it was written for (`web/app.js`,
`PAGE_CONTRACT_VERSION`). When `index.json` carries a greater one, or one that
is not an integer, it writes a console warning and carries on; it never calls
`fatal()`. The page reads every field with a fallback, and the deploy gates
(`scripts/check_dist.py`, `scripts/browser_verify.sh`) are what refuse a
dist/ that is actually inconsistent. A version check that blanks the page
would turn a harmless bump into an outage. `tests/web/test_contract_version.py`
runs the guard and fails when the page's number trails `CONTRACT_VERSION`.

## The deployed file set

Everything under `dist/` except dotfiles is published by
`scripts/deploy_verify.sh` (`deploy/rsync-excludes.txt`).
`scripts/check_dist.py` is the gate that holds the set together.

### Shared, once per site

| File | Writer | Reader | Layout |
|---|---|---|---|
| `index.json` | `emit/index.py:write_index` (`build-all`, `reindex`) | page, `check_dist`, `deploy_verify.sh` | JSON object; fields below |
| `hover_cells.bin` | `emit/index.py:write_hover_cells` | page (`loadCells`, `cellIndex`) | little-endian uint64 H3 ids at `hoverRes` (4), **sorted ascending**. The page binary-searches it. Entry *i* is the cell behind entry *i* of every per-origin tier-A array. Length must equal `hoverCellCount`, or the page calls `fatal()`. |
| `reading_parents.bin` | `emit/index.py:write_reading_parents` → `emit/hover.py` | page (`checkedParents`) | little-endian uint64 H3 ids at `readingParentRes` (3), sorted ascending. Entry *b* is block *b* of every `.r6.bin`. Length must equal `readingParentCount`, or the page drops the reading tier and reads res 4. Optional: absent in a build from before the tier, and the page then reads res 4. |
| `water.pmtiles` | `scripts/build_water_tiles.py` → `emit/water.py` (**not** `build-all`) | page (`water` source) | PMTiles v3, MVT, one layer `water`, z0-11. Static between builds. `check_dist` refuses it if missing, if it has the wrong layer, or if its zoom range is stale. |
| `places.json` | `transport-maps assets` → `emit/places.py` | page (place names under the cursor) | `{"fields": ["name","region","country","lat","lon"], "places": [[...], ...]}`. Rows are positional and **sorted by population, largest first**. The page treats row index as rank for label eligibility, priority and collisions, so the order is part of the format (`plan/deferred.md` ARCH3-4). |
| `airports.json` | `transport-maps assets` → `emit/airports_json.py` | page (search) | `{"fields": ["iata","name","country","lat","lon","size"], "airports": [[...], ...]}`. Rows are positional, and `size` is `large`, `medium` or `small`. |
| `borders.pmtiles` | `transport-maps assets` → `emit/borders.py` (**not** `build-all`) | page (`borders` source: layers `borders`, `borders-other`) | PMTiles v3, MVT, one layer `borders`, z0-11. Each line carries `kind`: `international` (LSIB rank 1, drawn solid), `other` (rank 2 and the Natural Earth de facto lines, dashed) or `special` (rank 3, dashed and fainter); no other property. Static between builds. `check_dist` refuses it if missing, if it has the wrong layer, or if its zoom range is stale. Replaced `borders.json` (Natural Earth GeoJSON) on 2026-10-04. |
| `index.html`, `app.js`, `boot.js`, `llms.txt`, `vendor/`, ... | `web/`, merged in by `deploy_verify.sh` | browser | not part of this contract |

### Per origin: `dist/origins/{slug}.*`

`cli._solve_one` writes nine files per origin, in the order listed in
`progress.SUFFIXES`. They are one unit: a completion record (below) says
whether all nine come from one build. "Tier A" means one entry per
`hover_cells.bin` cell, in that file's order: *N* = `hoverCellCount`, 90,740
in the shipped build.

| Suffix | Writer | Layout |
|---|---|---|
| `.pmtiles` | `emit/tiles.py:write_pmtiles` | PMTiles v3, MVT, one layer `bands`, z0-8 (z0-6 in a variant). Feature properties are `band` (int: 0 is the fastest band, 36 is the open band past the last edge, -1 is unreachable land) and `max_minutes` (the band's upper edge from `bandEdgesMin`, or null for the open band and for -1). Each band's polygon overlaps the next by a rim; see rule 2 below. Levels of detail come from `contour/bands.py:LODS`: z7+ native, z5-6 and z3-4 base cells with one and three rim cells, z0-2 coarse res-4. |
| `.bin` | `emit/hover.py:write_hover` | Tier A: *N* × uint16 LE minutes. Each entry is the centre child at the solve resolution (the fastest child where the centre is water). Values ≥ 65,534 are written as the sentinel 65,535. |
| `.r6.bin` | `emit/hover.py:write_reading` | Tier B: `readingParentCount` × `readingSlots` (343) × uint16 LE minutes. Block *b* belongs to entry *b* of `reading_parents.bin`. The slot inside a block is the cell's H3 digits below `readingParentRes`, read as a base-7 number, so no per-cell list ships. Pentagon holes and non-land slots (18.3 %) hold 65,535. The fixed 343 stride is deliberate (`config.READING_SLOTS`). |
| `.over.bin` | `emit/override.py:write_override` | Three arrays back to back, little-endian, sorted by slot: *n* × uint32 global reading slots (`block × 343 + slot`), *n* × uint16 airport ordinals, then *n* × 6 uint16 mode minutes (cell-major). *n* = byteLength / 18 (`ENTRY_BYTES` = 4 + 2 + 2 × channels). These are the res-6 cells whose arrival airport differs from their tier-A representative's. Optional: offered only when `overrideUrlSuffix` is in `index.json`. |
| `.json` | `emit/routes_json.py:write_routes` | `{"offsets": {"cells": 0, "airports": A, "stations": S}, "nodes": [{"id", "kind": "dep"\|"arr", "code": IATA, "min", "prev": id\|null}, ...]}`. Only airport nodes are listed, both the departure side and the arrival side, and only those reachable under 65,534 min. |
| `.air.bin` | `emit/itinerary.py:write_itinerary` | Tier A: *N* × uint16 LE airport ordinal, the arrival airport the cell was last reached through. `0xFFFF` (`NO_AIRPORT`) means the journey was overland. |
| `.modes.bin` | `emit/modes.py:write_modes` | Tier A: *N* × `len(modeChannels)` (6) × uint16 LE, cell-major, minutes per surface mode in `modeChannels` order. Clipped to 0 … 65,534. An unreachable cell is all zeros. Air and airport time are not counted here, because `.json` itemises them. |
| `.rail.bin` | `emit/rail_detail.py:write_rail_detail` | Tier A: *N* × uint16 LE row index into `.rail.json` `stations`. `0xFFFF` (`NO_RAIL`) means no rail leg. A table of 65,535 rows or more is a build error, not a wrap. |
| `.rail.json` | same | `{"fields": ["station","line","operator","ref"], "operators": [...], "stations": [[name, line, operatorOrdinal, ref], ...]}`. `operatorOrdinal` is -1 when OSM gave no `operator`. Always written alongside `.rail.bin`. The page fetches both only when `railDetail` is true. |

**Node-offset arithmetic.** The solver's node ids are laid out as cells
`[0, A)`, departure airports `[A, A + n_air)`, arrival airports
`[A + n_air, S)` and stations `[S, ...)`, where `A = offsets.airports` (the
refined cell count) and `S = offsets.stations = A + 2 × n_air`. The page
derives `n_air = (S - A) / 2`. A `.air.bin` ordinal *k* names the arrival node
`A + n_air + k` in `.json`, and the page walks `prev` back from there. The
pipeline hand-derives these offsets at seven sites today: two in
`emit/itinerary.py`, two in `emit/rail_detail.py`, and one each in
`emit/modes.py`, `emit/override.py` and `emit/routes_json.py`. `check_dist` uses the
`(A, S)` pair of every origin as the build's fingerprint: two pairs mean two
builds are mixed. It also requires `H ≤ A ≤ 7^(fineRes − hoverRes) · H`,
where *H* is `hoverCellCount`. Every hover cell is the `hoverRes` parent of
at least one solver cell and of at most 343 `fineRes` ones.

### Per exclusion variant: `dist/v/no-<mode>/`

`build-all --exclude <mode>` (`variants.py`, mode is `air`, `ferry` or `rail`)
writes the same nine per-origin files under `dist/v/no-<mode>/origins/`. They
use the same widths and orderings and are read against the same shared
`hover_cells.bin` and `reading_parents.bin`. The band tiles stop at z6
(`VARIANT_MAX_ZOOM`). The build writes `variant.json` last, which lists the
excluded mode, the origins, `maxZoom` and the build identity. `index.json`'s
`variants` offers a mode only if its marker covers every listed origin and
each origin has `pmtiles`, `bin`, `json`, `air.bin`, `modes.bin`, `r6.bin` and
`over.bin` (`variants.REQUIRED`). The page reads a variant from
`./v/no-<mode>/origins/` (`originBase()`). A variant never writes
`index.json`. `variant.json` is published, but the page does not read it.

### Never deployed

- **`.progress/<slug>.json`**, under `dist/` and under each variant root
  (`progress.py`). A completion record says `writing` before the origin's
  first file is replaced. It says `complete`, with every file's size, after
  the last one. Records are keyed on the run's `inputsHash`, the graph digest,
  the excluded mode and the origin row. `check_dist` refuses an origin still
  marked `writing`, and `build-all --skip-existing` trusts only a complete
  record under the current key. The rsync filter excludes it twice: once as
  `.*` and once by name.
- **The solver bundle, `data/build/solver/`** (`service/bundle.py`, `FORMAT`
  1). Every full `build-all` writes it. It holds `cells.npy`,
  `sorted_ids.npy`, `sorted_pos.npy`, `split.npy` and the CSR graph in
  `indptr.npy` (int32), `indices.npy` (int32) and `data.npy` (float64,
  minutes), plus `meta.json` with the counts, resolutions and the build's
  `identity`. The counts include `nAirports` and `nStations`, the node
  layout above (`nNodes = nCells + 2 × nAirports + nStations`, checked at
  load). Bundles written before 2026-10-02 lack those two: they still load
  and answer a number with no legs, and `python -m
  transport_maps.service.bundle add-counts BUNDLE DIST` adds them from the
  same build's `dist/` (`counts_from_dist`). It is never under `dist/`.
  `scripts/deploy_solver.sh` ships it straight to the web host's
  `/home/ubuntu/worldmap-solver/current/`. The service maps it and answers
  wire version `WIRE_VERSION` (`service/wire.py`). With the counts, a
  response carries `legs`: surface (with its rail minutes), fly and connect,
  airport ordinals as in `.air.bin`, summing to `minutes`
  (`service/bundle.py:journey_legs`, `wire.LEG_FIELDS`). A `hover_cells.bin`
  beside the bundle is optional; when it is there, or named with
  `--hover-cells`, the service refuses to start unless it lists the bundle's
  own hover parents in the same order (below).
- `.build.lock`, and every stray an aborted writer leaves (`*-journal`,
  `*.tmp`, `*.part`, `tmp*`). `check_dist` refuses a dist/ that contains them.

## `index.json`

Writer: `emit/index.py:write_index`. "Optional" means the page has a fallback
for an `index.json` that predates the field. `reindex` refuses to rewrite the
file when a field marked *frozen* no longer matches today's code
(`cli._CURRENT_INDEX_CONSTANTS`). Rebuild instead.

| Field | Type | Meaning | Page if absent |
|---|---|---|---|
| `contractVersion` | int | this contract's version (above); *frozen* | read as 1 |
| `bandEdgesMin` | int[] | upper edge of each band in minutes, strictly ascending, 36 edges and 37 bands; *frozen* | `fatal()` |
| `unreachable` | int | the uint16 sentinel, 65,535; *frozen* | 65,535 |
| `hoverRes`, `solveRes`, `fineRes` | int | 4, 6 and 7; *frozen* | 4 and 6; `fineRes` is not read by the page (`plan/deferred.md` AB26) |
| `modeChannels` | string[] | `.modes.bin` channel order, `emit/modes.py:CHANNELS`; *frozen* | the six names |
| `modeDetail` | {channel: string} | one sentence per mode, quoting the calibrated speeds (rule 1 below). `reindex` carries it forward. | `MODE_FALLBACK` |
| `railDetail` | bool | whether `.rail.bin`/`.rail.json` exist | no rail detail |
| `carryOn` | {`departureMin`, `arrivalMin`} | `calibration.toml [carry_on]` | no carry-on option |
| `hoverCellsUrl` | string | `hover_cells.bin` | same |
| `hoverCellCount` | int | length of `hover_cells.bin` | no cross-check |
| `readingRes`, `readingParentRes`, `readingSlots` | int | 6, 3 and 343; *frozen* | no reading tier, 3, 343 |
| `readingParentsUrl`, `readingUrlSuffix` | string | `reading_parents.bin`, `.r6.bin` | no reading tier |
| `readingParentCount` | int | length of `reading_parents.bin`; a mismatch makes the page drop the reading tier and read res 4 | no cross-check |
| `overrideUrlSuffix` | string | `.over.bin`, present only when every origin has one | no override |
| `variants` | [{`exclude`, `path`, `maxZoom`}] | complete exclusion variants | none offered |
| `attribution` | [{`name`, `licence`, `url`, `usedFor`}] | `emit/index.py:ATTRIBUTION`. `check_dist` refuses a missing credit. | built-in credits |
| `origins` | [{`slug`, `name`, `lat`, `lon`, `country`?}] | departure cities from `data/origins.toml`. Slugs match `^[A-Za-z0-9][A-Za-z0-9_-]*$`. | `fatal()` |
| `graph` | {`rail`, `ferry`} | whether rail and ferries were in the graph | not read by the page; `reindex` carries it |
| `inputsHash`, `buildId`, `builtAt`, `gitHead` | string | `build_identity()`, sampled when the build starts. The page prints `builtAt`; `buildId` ties the solver bundle to the build | no build date |
| `solver` | {`wire`} | present only when `data/build/solver` is from this same build (`_solver_matches`); arms both `/api/solve` and `/api/map` | exact departure and the map from a point off |

`deploy_verify.sh`'s `solver_gate` refuses a deploy whose `index.json` offers
`solver` while the web host's bundle has a different `buildId`.

## The map from a point: `/api/map`

Added 2026-10-04 (`plan/2026-09-14-c13-solver-service.md`, "The map from any
point"). Writer: `service/bundle.py:GraphSolver.map` through
`service/hovermap.py` and `service/wire.py:map_body`. Reader: `web/app.js`,
`solveMap` and `pointFeatures`.

`GET /api/map?from=<lat>,<lon>` answers the whole map from one point as one
JSON body:

```json
{"v": 1, "status": "ok", "mapVersion": 1, "hoverRes": 4, "count": 90740,
 "buildId": "52660de5-20261002T081551Z", "snappedKm": 0.0,
 "snappedLat": 37.80123, "snappedLon": 127.24567, "times": "<base64>"}
```

- **`times` is a tier-A array.** Base64 of `count` little-endian uint16
  minutes, one per `hover_cells.bin` cell in that file's order: exactly the
  layout of `{slug}.bin`, sentinel included (values at or past 65,534 are
  65,535), and valued by the same child -- the res-4 parent's centre at
  `solveRes`, or at `fineRes` where that base cell was split, and its fastest
  child (ties to the lowest node position) only where neither centre is
  land. The rule is `emit/hover.py`'s; the service restates it with numpy
  over `cells.npy` because the package may not import `emit`, and
  `tests/service/test_hovermap.py` holds the two byte for byte. Measured on
  the shipped bundle on 2026-10-04: Seoul's and Suva's maps equal their
  `.bin` at all 90,740 cells.
- **The order is checked at both ends.** The service derives the hover
  parents from `cells.npy` (the sorted unique res-4 parents, as
  `emit/hover.hover_cells` makes them) and, given a `hover_cells.bin`,
  refuses to start on any difference. The page refuses a body whose `count`
  is not its `hover_cells.bin` length, whose `hoverRes` is not its own, or
  whose `buildId` is not `index.json`'s.
- **`mapVersion`** (`wire.MAP_VERSION`, the page's `SOLVER_MAP_VERSION`, now
  1) versions `times`' layout. The map is additive to wire 1, so `v` is
  unchanged; a change to the array's order or width moves `mapVersion`, and
  `tests/service/test_wire.py` keeps the two ends equal.
- **Errors** are `/api/solve`'s: the same six codes and bodies, the same
  validation of the one point, the same nginx limit zone and the same
  wire-format `busy` and `unavailable` from nginx itself.
- **Base64 in JSON, not a binary body**, so the page has one parse path for a
  map, a journey and every failure, and a captive portal's HTML 200 fails
  `JSON.parse` as `unavailable`. About 242 KB, ~149 KB gzipped by nginx,
  against ~130 KB for the raw array gzipped.

The page draws `times` as res-4 hexagons in a GeoJSON layer (`pointbands`)
with the bands layer's paint and sort key, inserted beneath `water` like the
tiles, and hides the tile layer while it is shown. Rule 2 below does not need
the one-cell overlap there: the hexagons tile exactly and share every vertex,
and the source is not simplified (`tolerance: 0`). A cell across the
antimeridian is split into two polygons as `contour/bands.py
_split_at_antimeridian` splits it.

## Sentinels, widths and byte order

- **65,535 (`config.UNREACHABLE`)** means "no route" in `.bin` and `.r6.bin`,
  and is the padding in `.r6.bin`. The writers fold anything at or above
  65,534 minutes (45 days) into it (`MAX_MINUTES`), and the page reads
  `>= MAX_MINUTES` the same way.
- **`0xFFFF`** means "none" in `.air.bin` and `.over.bin` (`NO_AIRPORT`) and in
  `.rail.bin` (`NO_RAIL`). It is the same bit pattern as `UNREACHABLE` but
  typed separately in three places (`plan/deferred.md` AB25).
- **-1** is `band` for unreachable land in the tiles and `operatorOrdinal` for
  "no operator" in `.rail.json`. **-9999** is scipy's "no predecessor", which
  `.json` writes as `null`.
- **Widths.** Tier-A arrays are 2 bytes per entry, `.modes.bin` is 12 bytes
  (2 × channels), `.r6.bin` is 686 bytes per block (2 × 343) and `.over.bin`
  is 18 bytes per entry. `check_dist` checks each against `hover_cells.bin`,
  `reading_parents.bin` and `modeChannels`.
- **Byte order.** Every binary file is little-endian (`<u2`, `<u4`, `<u8`).
  The page reads them through `Uint16Array`, `Uint32Array` and
  `BigUint64Array`, which use the platform's byte order. That is safe only
  because every browser the page targets runs on little-endian hardware. No
  `DataView` is used, and nothing checks the assumption.

## What checks this contract

- `scripts/check_dist.py`: lengths, widths, the node universe, completion
  records, variants, PMTiles headers, the `water` layer, `index.json`
  required fields and attribution.
- `tests/test_contract_doc.py`: this file against `write_index`'s keys and
  `progress.SUFFIXES`.
- `tests/cli/test_reindex.py`: the *frozen* fields, including
  `contractVersion`. `tests/test_contract_doc.py` keeps the *frozen* marks in
  this file equal to `cli._CURRENT_INDEX_CONSTANTS`.
- `tests/emit/test_index.py`: `contractVersion` and the other fields.
- The page itself: `hoverCellCount` and per-origin length checks, and a
  console warning for a newer `contractVersion`.
- `tests/service/test_hovermap.py`: `/api/map`'s array against
  `emit/hover.write_hover` byte for byte, its representatives against
  `representative_array`, and the hover order against `hover_cells.bin`.
- `tests/web/test_point_map.py`: what the page accepts from `/api/map` and
  how it draws, reads and abandons it.
- `tests/web/test_contract_version.py`: that warning, and the page's version
  against `emit/index.py`'s.

`check_dist` measures `.modes.bin` and `.over.bin` against the channel count
in `index.json`'s `modeChannels`, the list the page reads them by. It falls
back to `emit/modes.py:CHANNELS` only when the field is absent, and reports
the absence (J1b(d), 2026-10-02).

Not done yet (J1's code half, recorded in the plan): one `NodeIndex.offsets`
in place of the seven hand-derived sites.

## Rules that cross the layer boundary

The design spec says "the frontend never learns how the numbers were made; the
pipeline never learns how they are drawn". Both halves of that sentence are
false, and on purpose. Each rule below couples the two layers. Changing one
side alone breaks the page without an error anywhere.

### 1. The page prints the pipeline's account of how a time was made

- `emit/index.py:mode_detail()` writes `modeDetail` into `index.json`: one
  sentence per surface mode, with the speeds read from the same calibration
  objects the graph uses (`graph/ground.py`, `graph/rail.py`,
  `graph/ferry.py`, `sources/urban.py`).
- The page shows that sentence verbatim as the tooltip on each mode name in
  the itinerary (`web/app.js`, `mode()` inside `renderLegsInto()`). It uses
  its own `MODE_FALLBACK` only for an `index.json` older than the field.
- The keys are the mode names themselves: `emit/modes.py:CHANNELS` (`rail`,
  `ferry`, `highway`, `major road`, `minor road`, `track`), which the page
  reads as `modeChannels` (`MODE_NAMES` in `web/app.js`). If a channel is
  renamed on one side only, the tooltip disappears and the mode name is
  printed bare.
- So a calibration constant is visitor-facing text. Each sentence must say
  whether its speed is fitted or a published-figure default, which is
  CLAUDE.md's calibration rule applied to the page.
  `tests/test_calibration_provenance.py::test_every_speed_in_the_mode_tooltips_says_which_it_is`
  enforces it.
- The prose describes the build the arrays came from, not today's
  `calibration.toml`. `reindex` therefore carries the previous `modeDetail`
  forward instead of re-deriving it
  (`tests/cli/test_reindex.py::test_mode_prose_is_carried_forward_not_resampled`).

### 2. The band geometry is gap-free only under the page's draw order

- `contour/bands.py` emits band *k* as the cumulative region reached within
  its upper edge, minus the cells that sit safely inside band *k-1*. Each band
  polygon therefore covers its own cells plus a one-cell rim of every faster
  band, and neighbouring bands overlap by that rim. That overlap is what makes
  a gap between bands geometrically impossible (see the module docstring and
  the hexagon rules in CLAUDE.md).
- The overlap is correct only if the faster band is painted on top. The page
  does this with the bands layer's `fill-sort-key`, which is `-band`, so a
  faster band has a higher key and draws later. Unreachable land gets -1000
  and goes underneath everything. If that order is reversed or dropped, each
  slower band's rim covers the outer ring of the band inside it, and every
  boundary on the map moves one cell outward. Nothing reports an error.
- The same layer must stay opaque (`fill-opacity: 1`) and not antialiased
  (`fill-antialias: false`). Otherwise the hidden rim shows through, or a
  hairline is drawn along every boundary.
- The bands also run out to sea: `contour/grid.py` adds rings of sea cells,
  more of them for the low-zoom levels (`contour/bands.py` LODS). The page
  inserts the bands layer beneath `water`, so the static `water.pmtiles`
  coastline cuts them back to the shore. Without that layer,
  or with the bands drawn above it, the shore is hex-shaped out at sea
  (CLAUDE.md, deploy rules).
- Guards: `validate.check_bands_cover` checks the pipeline half on the
  emitted geometry. `tests/web/test_app_constants.py` checks that the page's
  bands layer has `fill-sort-key`, `fill-opacity: 1` and
  `fill-antialias: false` and is added before `water`. It checks that the
  sort key is present, but not its sign.
