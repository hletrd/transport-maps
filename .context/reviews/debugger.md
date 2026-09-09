# Debugger review — cycle 2 (latent bug surface, failure modes, regressions)

**HEAD reviewed:** `bf9e5cc` on `feat/transport-pipeline` (working tree clean at review time;
`git status --short` empty). Cycle-1 range examined: `ac191db..bf9e5cc`, 46 commits, full diff read
(saved and read hunk by hunk: `src/`, `web/`, `scripts/`, `deploy/`, `tests/`, docs).

**Environment at review time (read-only observation, nothing touched):** the 553-origin
`build-all` is running (parent pid 94066, five forked workers 4143–4147 at 60–70 % CPU,
2.7–3.7 GB RSS each; `dist/origins/*` being rewritten in place: seoul/tokyo/osaka/nagoya/fukuoka
at 04:36, guangzhou/shenzhen at 04:46, sapporo by 04:50). Five additional `.venv/bin/python`
processes (pids 12633–12637, PPID 1, 10 h old, 0 % CPU, ~10 MB RSS) are orphaned idle workers of
the earlier hang (A3); left alone per the constraints — see DBG-14.

Probes run (all read-only, `.venv/bin/python` with `httpx.get` stubbed to refuse the network,
`nice 15`, no writes under `data/`/`dist/`; scripts in the session scratchpad):
`probe_airports.py` (replays `nodes.build_index`'s airport placement from the stamped caches —
reproduces the build's "18 of 4,008 dropped" exactly), `probe_snap_country.py`,
`probe_origins.py`, `probe_routes.py`, plus small h3 probes for the antimeridian/pole cases.

## Inventory (every file below was read in full unless marked)

| Area | Files |
|---|---|
| Pipeline entry / gates | `src/transport_maps/cli.py`, `validate.py`, `config.py`, `__init__.py` |
| Graph | `graph/build.py`, `graph/nodes.py`, `graph/ground.py`, `graph/refine.py`, `graph/air.py`, `graph/rail.py`, `graph/transfers.py`, `solve/dijkstra.py` |
| Sources | `sources/_utils.py`, `airports.py`, `landmask.py`, `urban.py`, `roads.py`, `countries.py`, `osm.py`, `routes.py`, `wikidata.py` |
| Contour | `contour/bands.py`, `contour/grid.py` |
| Emit | `emit/hover.py`, `index.py`, `itinerary.py`, `modes.py`, `rail_detail.py`, `routes_json.py`, `tiles.py`, `water.py`, `places.py`, `borders.py`, `airports_json.py` |
| Calibration | `calibrate/fit.py`, `calibrate/ground.py`, `calibration.toml` |
| Scripts | `scripts/deploy_verify.sh`, `browser_verify.sh`, `osm_rail.sh`, `build_water_tiles.py`, `expand_origins.py`, `adsb_extract.py`, `calibrate_ground.py`, `ground_check.py`, `check_ramps.py` |
| Page | `web/app.js` (1,126 lines), `web/index.html` (479 lines), `web/README.md` |
| Deploy | `deploy/worldmap.atik.kr.conf`, `deploy/worldmap-security-headers.conf`, `deploy/README.md` (diff) |
| Data | `data/origins.toml` (553 origins, probed), `dist/index.json` header, `dist/hover_cells.bin`/`origins/*` sizes |
| Tests touched by cycle 1 | `tests/test_cli.py`, `tests/test_validate.py`, `tests/graph/test_refine.py`, `test_ferry.py`, `test_build.py`, `test_ground.py`, `test_rail_integration.py`, `tests/emit/test_hover.py`, `test_index.py`, `test_itinerary.py`, `test_modes.py`, `test_rail_detail.py`, `tests/sources/test_urban.py`, `test_landmask.py`, `test_countries.py`, `test_osm.py`, `test_cache_provenance.py`, `tests/contour/test_bands.py` (diff hunks + surrounding context) |
| Context | `CLAUDE.md`, `.context/reviews/cycle-1/_aggregate.md`, all five `plan/2026-09-10-c1-*.md`, `plan/deferred.md`, `plan/README.md`, `.omc/progress.txt` |

Not in scope / not read: `web/vendor/*` (third-party), `docs/superpowers/*` (design docs),
`tests/fixtures/*`.

---

## PASS A — regression hunt on `ac191db..bf9e5cc`

### High

#### DBG-1 — `_nearest_land` cannot see a split neighbour: six airports dropped and nine snapped 2–4× too far (bf9e5cc)

- **Severity** High · **Confidence** High · **Status** Confirmed (probe reproduces the build's
  numbers) · **Effort** S (code) — the data fix needs a rebuild
- **Where** `src/transport_maps/graph/nodes.py:114-128` (`_nearest_land`), `:145-173`
  (the airport loop); fixture `tests/graph/test_refine.py:466-475`
- **Why.** `_nearest_land` walks `h3.grid_ring(cell, 1|2)` at the airport cell's own
  resolution (res 6, since an off-mask base cell is never in `split_set`) and asks
  `cell_pos.get(n)`. `cell_pos` holds an *unsplit* base cell under its res-6 id but a *split*
  one only under its seven res-7 children (`refine.refine`, `:43-53`), so every split neighbour
  answers `None`. The split cells are precisely the built-up coastal cells that surround
  reclaimed-land airports. The snap therefore (a) skips the nearest land and takes a farther
  unsplit cell, or (b) finds nothing and drops the airport.
- **Reproduction** (`probe_airports.py`, from the stamped `land_cells_r6_dd95e3b5.parquet`,
  `urban_mask-bd1ee498.parquet`, `road_class_grid_495d9dd1.npy`, `airports_c35abade.parquet`):
  58 airports off the mask → 40 snapped, **18 dropped** (matches the build).
  - Dropped although a split land cell lies within two rings: **KKJ Kitakyushu (JP, land 5.4 km
    away, 5 outbound routes incl. Tokyo)**, DPL Dipolog (PH, 4.2 km, 3 routes), HLE St Helena
    (3.7 km, 3), PTF Pacific Harbour (FJ, 9.8 km), WLS Wallis (3.7 km, 2), WSZ Westport (NZ,
    4.0 km). The other 12 dropped are atolls with no land cell within 14 km (APK, CNC, FTA,
    KKR, MNF, OKR, PKP, RGI, RMT, SYU, TGJ, TIH). 94 of 68,152 directed route pairs name a
    dropped airport and are deleted from the graph (`build._air_edges` "unknown" skip).
  - Snapped to a farther unsplit cell although a nearer split one exists: **BOO Bodø 11.2 km
    vs 2.9 km (26 outbound routes)**, USH Ushuaia 13.4 vs 4.6, SIT Sitka 9.5 vs 3.4, NRL 10.2
    vs 4.2, DUT 6.9 vs 3.5, BYW 6.4 vs 3.4, FRO 6.0 vs 4.2, INQ 9.5 vs 8.2, PPW 4.6 vs 4.1.
    All same-country (checked against Natural Earth admin-0 by cell intersection), so no
    border side effect today, but a 10–13 km error in the access cell is 10–13 km of
    ground travel at whatever speed that cell has, charged on every journey through the airport.
  - The docstring's "a few kilometres" and "64 of 4,008 needed it" do not match: reach is two
    res-6 rings ≈ 14 km (XMY 14.0, USH 13.4, JSU 13.0, BOO 11.2) and the count is 40.
- **Fix.** In `_nearest_land`, when `cell_pos.get(n)` is `None`, also try
  `h3.cell_to_children(n, config.FINE_RES)` (the children present are the split cell's nodes)
  and rank by distance to the airport; or search at `FINE_RES` directly via
  `cell_at` on each candidate. Then the test: extend
  `test_an_airport_off_the_mask_snaps_to_the_nearest_land_cell_within_two_rings` with a
  fixture whose nearest land is present only as res-7 children and assert the snap lands on
  one of them — today's fixture holds res-6 ids only, so the blind spot is invisible to it
  (mutation: the current code fails the new assertion; the fixed code passes).
  Correct the docstring numbers. Note the running build already carries this defect.

### Medium

#### DBG-2 — `check_bands_cover`'s 3 % pull-in ignores the antimeridian: phantom sample points 11° away (47f0baf)

- **Severity** Medium · **Confidence** High · **Status** Confirmed (arithmetic + h3 probe);
  latent in the current build · **Effort** S
- **Where** `src/transport_maps/validate.py:94-98`
- **Why.** `pts.append((clon + 0.97 * (lon - clon), clat + 0.97 * (lat - clat)))` treats
  longitude as planar. For a cell straddling ±180 the centre is at, say, −179.95 and a vertex
  at +179.96, so the pulled-in point is `−179.95 + 0.97·359.9 ≈ +169.2`: eleven degrees away,
  in another band or in the open sea. Probe: Chukotka cell `860d9100fffffff` → one vertex
  pulled to (169.17 E, 66.01 N); Taveuni cell `869b436f7ffffff` → three vertices pulled to
  169.2 E. Before 47f0baf the raw vertex was tested and the antimeridian-split polygon parts
  covered it.
- **Failure scenario.** `rng = default_rng(seed=0)` and `interior` are origin-independent, so the
  20,000-cell sample is the same for every origin; seven origins have passed the gate in the
  running build, so this run will not trip on it. Any change to `COVER_SAMPLE_CELLS`, the seed,
  the land mask or the refine rule can put one of the ~230 antimeridian-straddling interior
  cells (Chukotka, Wrangel, Antarctica wedge) into the sample and abort a multi-hour build with
  `level i: n of N interior hex vertices fall between bands` for geometry that is correct.
- **Fix.** Pull in within an unwrapped frame: if `max(lons) − min(lons) > 180`, add 360 to
  negative longitudes (and to `clon` if negative) before interpolating, then wrap the result
  back into [−180, 180]; or exclude cells for which `bands._crosses_antimeridian` is true
  from the pull-in and test their raw vertices. Test: a Chukotka cell with a synthetic single
  band feature must pass the gate.

#### DBG-3 — The page never checks a per-origin array against `hoverCells.length`: a mixed build renders shifted, wrong readings with no error

- **Severity** Medium · **Confidence** High · **Status** Confirmed (code) — and `dist/` is in
  exactly this state during the running rebuild · **Effort** S
- **Where** `web/app.js:489-499` (`.bin`), `:504-511` (`.modes.bin`, `.air.bin`), `:541-559`
  (`cellIndex`/`lookup`), `:564-580` (`legsTo`), `:606-616` (`surface()`)
- **Why.** C9 (cycle 1) validates `hover_cells.bin` (whole 8-byte cells) and the page now
  says "unavailable" on a failed fetch, but a `.bin` of the *wrong length* is accepted:
  `hoverTimes[cellIndex(...)]` indexes by position in `hoverCells`, so with 90,659 entries
  against 90,740 cells every reading after the first inserted cell is a neighbouring cell's
  time, and readings past the end are `undefined` → the copy says "Loading the times from …"
  for ever. `.air.bin` mismatched → `hoverAir[i]` is another cell's ordinal or `undefined`
  (`routes.byId.get(NaN)` → empty chain) → the Route panel asserts "No flight on this
  route — surface travel". `.modes.bin` mismatched → `hoverModes[i*6+k]` reads the wrong
  cell's channels.
- **Evidence.** Before the rebuild overwrote them, `dist/origins/abu-dhabi.bin` (and 150
  others) were 181,318 bytes = 90,659 entries while `dist/hover_cells.bin` is 725,920 bytes =
  90,740 (the new build's ordering); `.omc/progress.txt` records the deploy gate refusing
  exactly this pair. Anyone opening `dist/` locally during a rebuild (the preview server the
  web work used) sees plausible, silently wrong numbers for every old origin.
- **Fix.** After each fetch: `if (arr.length !== hoverCells.length) throw new Error(...)` for
  `.bin`/`.air.bin`/`.rail.bin` and `arr.length !== 6 * hoverCells.length` for `.modes.bin`;
  route the `.bin` case through the existing `hoverFailed` path ("Times unavailable") and drop
  the optional arrays silently. The array-length checks suffice; `routes.json` needs no
  extra check because a mismatched `.air.bin` is rejected first. (A6b/A6c stay the
  build-side fix; this is the page-side belt.)

### Low

#### DBG-4 — Stale address results reappear after the query changed (1305ba7)

- **Severity** Low · **Confidence** High · **Status** Confirmed (code) · **Effort** S
- **Where** `web/app.js:876-917`, esp. `:894` and `:916`; `render()` at `:866`
- **Why.** `searchAddress` appends `ul.addresses` before the `await` (`:887`) and appends it
  *again* afterwards (`:916`). Every keystroke calls `render()`, whose `replaceChildren`
  removes the list; when the earlier fetch resolves, `seq === addressSeq` still holds (the
  counter only moves on another *address* search) and `box.append(ul)` re-inserts the old
  query's addresses under the new filter's city rows. The `$("q").value.trim() !== q` guard
  that prevented this before 1305ba7 was removed.
- **Fix.** Restore the guard (`if (seq !== addressSeq || $("q").value.trim() !== q) return;`)
  and delete the second `box.append(ul)`.

#### DBG-5 — Legend tick labels round the edge value they are placed on (b7da35f)

- **Severity** Low · **Confidence** High · **Status** Confirmed (arithmetic) · **Effort** S
- **Where** `web/app.js:178-198`, `fmtH` at `:180`
- **Why.** The ticks now sit on true edges (C4 done), but `h.toFixed(1)` prints 225 min as
  "3.8" (3 h 45), 465 as "7.8" (7 h 45), 125 as "2.1" (2 h 05), 955 as "15.9", 1470 as
  "24.5", 3020 as "50.3". The visible label misstates the edge by up to 3 min while the
  `title` carries the exact minutes; C4 asked for the true value ("3¾ h" or "225 min").
- **Fix.** Print hours with quarter fractions where exact ("3¾", "7¾") and `h m` otherwise
  ("2 h 05"), or the minute value below 10 h.

#### DBG-6 — `fatal()` does not cover a valid `index.json` that lacks `origins`/`bandEdgesMin` (f943964)

- **Severity** Low · **Confidence** High · **Status** Confirmed (code) · **Effort** S
- **Where** `web/app.js:54-67, 125, 225, 816`
- **Why.** `loadJSON` only proves the body parses. `meta.origins.length` (`:225`) then throws
  `TypeError` before the map exists; the readout keeps its static prompt copy, the city list is
  empty and the globe is absent — the "blank page, no message" C9 set out to remove, for a
  differently-shaped failure (an `index.json` written by another tool, or truncated to `{}`).
  `bandEdgesMin` missing degrades quietly to 11 bands and `NaN–NaN h` band ranges.
- **Fix.** Validate the contract fields (`Array.isArray(meta.origins) && meta.origins.length`,
  `Array.isArray(meta.bandEdgesMin)`) through `fatal()` right after `loadJSON`. J1
  (`contractVersion`) is the durable version of this.

#### DBG-7 — "Start from the city nearest me" stays disabled when the permission prompt is dismissed (f943964)

- **Severity** Low · **Confidence** Medium · **Status** Likely (spec behaviour; not run) · **Effort** S
- **Where** `web/app.js:1100-1126`
- **Why.** `locate.disabled = true` is undone only inside the success/error callbacks. If the
  visitor closes the permission prompt without answering, Chrome/Firefox fire neither callback
  and the `timeout` option does not start until permission is granted, so the button stays
  disabled with "Locating…" until reload.
- **Fix.** Re-enable on a `setTimeout` (say 10 s) as well, or do not disable — just ignore a
  second click while one request is pending.

#### DBG-8 — Antimeridian on the page: the hover outline wraps the globe and `nearestPlace` names a far place

- **Severity** Low · **Confidence** High · **Status** Confirmed (code; J9 is the pipeline twin) · **Effort** S
- **Where** `web/app.js:418-426` (`highlight`), `:313-329` (`nearestPlace`)
- **Why.** `highlight` feeds `h3.cellToBoundary` straight into a GeoJSON polygon; for a cell
  straddling ±180 the ring's longitudes jump from +179.9 to −179.9 and MapLibre draws the
  359.8°-wide ring the long way round. `nearestPlace` uses `dx = (lon_i − lon)·cos(lat)` with
  no wrap, so from a Fiji/Chukotka cell every place across the line is 359° away and the
  readout says "near <somewhere in Vanuatu>".
- **Fix.** Unwrap the ring when `max−min > 180` (add 360 to negative longitudes; MapLibre
  accepts longitudes beyond 180 in globe and mercator), and take `dx = ((dlon + 540) % 360 −
  180)·cos(lat)` in `nearestPlace`.

#### DBG-9 — `scripts/expand_origins.py` slug fallback collapses to the country code

- **Severity** Low · **Confidence** High · **Status** Confirmed (code) · **Effort** S
- **Where** `scripts/expand_origins.py:51-54, 84-89`
- **Why.** `slugify` strips everything non-ASCII, so a name with no ASCII form (an empty
  GeoNames `asciiname` alongside a CJK `name`) yields `""`, and the fallback
  `slugify(f"{name}-{country}")` yields just `"cn"`; the second such city is then skipped
  silently by `if slug in slugs: continue`. A17 (TOML escaping of `"`/`\` in names) is the
  other half; `data/origins.toml` today has no such name (probed: 30 non-ASCII names, all
  with ASCII slugs, no quotes/backslashes, no duplicate slugs).
- **Fix.** Fall back to the GeoNames id (`f"{slug or 'city'}-{country}-{r['id']}"`) and
  write names with `json.dumps` (TOML basic strings share JSON escaping).

### Informational (PASS A checks that came back clean)

- `cli.py` forked path (b030d38): `GateFailure` is a `RuntimeError` and pickles back through
  `imap`; `Pool.__exit__` is `terminate()`; both paths share the same `shared` dict and
  `_solve_one` reads only keys both paths set (`country`, `zone`, `grid`, `native`,
  `cell_class`, `.get("rail_tables")`). A `ValueError` from `check_monotonic_ground`/
  `check_bands_cover` or the tippecanoe `RuntimeError` still aborts (with a traceback, not the
  clean exit) — acceptable. `solve`/`index` remain divergent (A7, cycle 2).
- `refine.ground_adjacent` (b38fb8b): pairs passed to it are always index nodes, so the purely
  geometric test equals `hex_edges`' join rule; `are_neighbor_cells` on identical cells returns
  `False` (probed), pentagons fine.
- `_slowest_within` (47f0baf) is algebraically the old `_interior` (max over the r-ring
  neighbourhood ≤ k−1), including isolated cells (`−1`).
- `_dissolve` no longer unions overlapping parts (47f0baf): `fill-opacity` is 1 on the
  `bands` layer, tippecanoe unions rings of one feature with the positive fill rule, and
  `check_bands_cover` was adapted to test parts individually. `_polygonal` is now dead code.
- `rail_detail.lookup_tables` (bf9e5cc): plain dicts; `write_rail_detail` handles `None`,
  `{}` and the no-station index. `index.json` advertises `railDetail: true` even for a build
  without OSM extracts, but the files are still written, so no 404.
- `tests/test_cli.py::test_a_gate_failure_in_a_forked_worker_aborts_the_run` is not vacuous:
  coverage is keyed by origin through the stubbed solve, the failure is in the second task,
  the alarm bounds a hang, and `index_calls == []` is asserted.
- `tests/test_validate.py::test_a_hole_between_bands_is_rejected` widened the punched hole
  from ~55 m to ~440 m to survive the pull-in: the gate's demonstrated sensitivity dropped 8×,
  by design ("holes this gate exists for are cells wide"). Recorded, not a finding.
- CSP hash in `deploy/worldmap-security-headers.conf` matches the inline gtag bootstrap in
  `web/index.html` (`sha256-pCkIJ0…`, recomputed); the JSON-LD block is not executed and
  needs no hash.
- `esc()` is applied only to strings that go into `innerHTML`; slugs used in URLs are not
  escaped and are also not validated on the `build-all` path (A17).
- No stale "553"/"157"/res-5 count remains in `README.md`, `web/llms.txt` or `web/index.html`
  (grep).

---

## PASS B — edge-case sweep

### Medium

#### DBG-10 — `_pole_cells` still dissolve into planar slivers (fresh evidence for A9)

- **Severity** Medium · **Confidence** High · **Status** Confirmed (probe) · A9, build plan cycle 3+
- `bands._split_at_antimeridian("86f29380fffffff")` (the res-6 cell over the South Pole) returns
  two polygons of 0.47 and 3.49 deg² lying between −89.94 and −89.99 latitude, i.e. a thin strip,
  not the cap. The pole cell and its ring are `complete`, so they are eligible for the
  coverage sample; their pulled-in vertices (DBG-2) are garbage as well. One line here because the
  plan already schedules the investigation; new evidence only.

### Low

#### DBG-11 — Two origins share one hover cell (Shenzhen and Hong Kong, `84411cbffffffff`)

- **Severity** Low · **Confidence** High · **Status** Confirmed (probe) · Effort S (copy)
- No build-side effect (each origin is its own solve), but on the page the res-4 readout for
  that cell is the centre child's value for both, and `originNear` (80 km) can offer "Depart
  from Shenzhen" while hovering Hong Kong's own cell. C3's finer hover cell removes the first
  half; the second is a wording choice. No two origins share a res-6 cell; no origin lies within
  0.5° of ±180; every origin's res-6 cell is on the mask (so `origin_node` cannot raise mid-build).

#### DBG-12 — Hidden `<details>` reset and legend loss on orientation change (phone)

- **Severity** Low · **Confidence** High · **Status** Confirmed (code) · C13 covers the legend half
- `layoutForSize()` runs on every `(max-width: 860px)` change and closes every panel
  (`web/app.js:1068`), so rotating a phone while reading a route folds the Route panel; with
  the sheet folded, `.rail.folded > :not(.sheet-toggle){display:none}` (`index.html:339`) hides
  the legend (CLAUDE.md "always visible"). Fix the first half by closing panels only on the
  first entry into the small layout.

#### DBG-13 — Nominatim non-array 200 body is not handled

- **Severity** Low · **Confidence** Medium · **Status** Likely · Effort S
- `web/app.js:892, 899`: a 200 response whose body is an object (`{"error": …}`) makes
  `hits.length` undefined ("No address found") and then `for (const h of hits)` throws
  `TypeError: hits is not iterable` after the head text was set, so the credit line is never
  appended and the console carries an unhandled rejection. Guard with `Array.isArray(hits)`.

#### DBG-14 — Five orphaned idle build workers from the pre-A3 hang

- **Severity** Low · **Confidence** High · **Status** Confirmed (ps) · Effort S (owner action)
- pids 12633–12637, `.venv/bin/python`, PPID 1, elapsed 10:01 h, state S, ~10 MB each: the
  respawned pool workers of the build that hung before b030d38. Harmless, but they are the
  "8 idle transport_maps.cli processes" signature the aggregate mentions and will confuse the
  next diagnosis. Not killed (constraint); reap them after the current build finishes.

### Edge cases checked and found handled (no finding)

- **65535 sentinel / ≥ 65535 minutes:** `hover.MAX_MINUTES = 65534` clamps, `modes` clamps to
  65534, `NO_AIRPORT`/`NO_RAIL = 0xFFFF` with 4,008 airports and a few-thousand-row rail table;
  page `fmtTime` treats only `>= 65535` as "no route" (A13 remains open for the ≥ 45-day case).
  Band edges: `band_indices([30, 30.0001, 4320, 4320.5, inf]) → [0, 1, 35, 36, 37]`, page
  `bandRangeAt` uses the same half-open convention.
- **Empty tables:** no rail → `lookup_tables(None)` → `{}` dicts, `write_rail_detail` writes
  all-`NO_RAIL`; zero ferry links → `build_graph` skips the part; an airport with no outbound
  routes gets no transfer edge (documented); `check_coverage` on an all-Antarctic universe → 0.0
  (A8 done); empty `origins` (`--limit 0`) → serial no-op, `index.json` untouched.
- **Missing/short files:** `hover_cells.bin` odd length or 0 → `fatal`; `.bin` odd length →
  `RangeError` inside the promise → "Times unavailable" (handled); `.modes/.air/.rail` odd
  length → swallowed by `.catch(() => {})` (silent but non-fatal); absent `.rail.json` →
  `r.ok` false → skipped. Length *mismatch* is DBG-3.
- **Duplicate slugs/names:** `load_origins` refuses duplicate slugs; four duplicate display
  names (Hyderabad, Suzhou, Fuzhou, Taizhou) remain — C11 (cycle 3+).
- **Unicode:** 30 non-ASCII origin names; `write_index` uses `ensure_ascii=True`,
  `rail_detail` writes UTF-8 with `ensure_ascii=False`; page uses `textContent`/`esc()`;
  `expand_origins.py` quoting is A17 + DBG-9.
- **Airports sharing a cell:** INQ and IIA both snap to `8618058f7ffffff`; distinct airport
  nodes, so no duplicate `(row, col)`.
- **Timezone/locale:** no date arithmetic in the scripts; `index.html` JSON-LD `dateModified`
  is a hard-coded string (docs item).
- **rsync partial transfer / nginx ranges:** `deploy_verify.sh` still deploys in place with
  `--delete` and no `--delay-updates`; the page now survives a 404 `.bin` but not a mixed set
  (DBG-3); `.pmtiles` location has `gzip off` and `Accept-Ranges`, `.bin` is gzipped and
  fetched whole — correct. A6d/I4 scheduled.
- **MapLibre globe at the poles:** `screenPointToLocation` returns a horizon point off the
  sphere, so `e.lngLat` is always defined; `latLngToCell` at ±90 is fine. Only the outline
  wrap (DBG-8) is off.
- **Results list empty / focus:** `ArrowDown` uses `?.focus()`; `render()` never runs while a
  results button has focus (typing focuses `#q`); D8 (local "no matches") is scheduled.

---

## Exception handlers

Every `except` in `src/` and `scripts/`, every `catch` in `web/app.js`.

| Location | Catches | Then | Verdict |
|---|---|---|---|
| `cli.py:54` `_load_rail` | `FileNotFoundError` | prints EXCLUDED, returns None | correct (announced) |
| `cli.py:145` `_load_ferries` | `FileNotFoundError` | prints EXCLUDED, returns None | correct |
| `cli.py:219` `_build_all` | `GateFailure` | `raise SystemExit(msg)` | correct |
| `emit/places.py:61` | `ValueError` (lat/lon parse) | `continue` | correct (row skipped; count not reported — minor) |
| `emit/tiles.py:71` | `CalledProcessError` | re-raise as `RuntimeError` with stderr | correct; `finally` unlinks temp files |
| `sources/_utils.py:25,32` `_retry_after_seconds` | `ValueError`, `(TypeError, ValueError)` | fall through to backoff | correct |
| `sources/_utils.py:87` `_atomic_write` | `BaseException` | unlink temp, re-raise | correct |
| `sources/landmask.py:107` | `StopIteration` | `RuntimeError` | correct |
| `sources/landmask.py:204` `_cells_touching` | `Exception` (BLE001) | add endpoint cell only | **too broad**: any error in `grid_path_cells` (not only the pentagon case) silently thins the boundary cells; unused by `land_cells` today (it uses `h3shape_to_cells_experimental`) |
| `sources/landmask.py:223` `land_cells` | `Exception` (BLE001) | collect, raise after loop | correct (surfaced) |
| `sources/routes.py:161` | `HTTPStatusError` 429 | backoff or re-raise | correct |
| `sources/routes.py:220` | `HTTPStatusError, TransportError, RuntimeError` | mark batch unresolved, later `_refuse_partial` | correct |
| `sources/wikidata.py:49` | `TransportError` | retry / re-raise | correct |
| `sources/wikidata.py:196` | `HTTPStatusError, TransportError, RuntimeError` | mark failed, later `_refuse_partial` | correct |
| `solve/dijkstra.py:26` | `KeyError` | `ValueError` "not on a land cell" | correct (aborts build with traceback; every current origin is on the mask — probed) |
| `scripts/adsb_extract.py:66` | `IndexError, TypeError` (trace row shape) | `continue` | correct |
| `scripts/adsb_extract.py:165,172` | `OSError` / `JSONDecodeError, UnicodeDecodeError` | count unreadable, bounded at 50 % | correct |
| `scripts/calibrate_ground.py:129,131` | `RuntimeError` (budget) / `httpx.HTTPError` | break / continue | correct |
| `app.js:43` `fetchOk` | network error | `fatal()` | correct |
| `app.js:47` `loadJSON` | JSON parse | `fatal()` | correct (shape not validated — DBG-6) |
| `app.js:151,153,156,1036` | `localStorage` | default / ignore | correct |
| `app.js:311` places.json | any | ignore | acceptable (labels are optional; a parse error is also silent) |
| `app.js:411` borders.json | any | ignore | acceptable |
| `app.js:488` rail detail | any | ignore | acceptable (optional) |
| `app.js:495` `.bin` | any | `hoverFailed`, message | correct |
| `app.js:507,511,519` modes/air/routes | any | ignore | **swallows a real error**: a `RangeError` from an odd byte length or a malformed `routes.json` leaves the Route panel silently incomplete; at least `console.warn` |
| `app.js:824` airports.json | any | ignore | acceptable |
| `app.js:893` Nominatim search | any | `failed = true` → message | correct (non-array body: DBG-13) |
| `app.js:936` reverse geocode | any | keep gazetteer label | correct |

---

## Final sweep

- Inventory coverage: every file in the table above was opened and read; nothing under
  `src/transport_maps/**`, `scripts/*.py`, `scripts/*.sh`, `web/app.js`, `web/index.html`,
  `deploy/**`, `calibration.toml` or `data/origins.toml` was skipped.
- Still-open cycle-1 items touched by this pass and left to their plans (no new evidence beyond
  what is stated inline): A6a–A6d (non-atomic/in-place `dist/`), A7 (`solve`/`index`
  divergence), A13 (≥ 65,535 min), A17 (slug validation / TOML escaping), C3 (hover cell),
  C5 (origin-switch generation counter), C11 (dropped airports still searchable, duplicate
  names), C13 (folded sheet hides the legend), D8, D15, I4, J1, J9.
- Counts: High 1 (DBG-1), Medium 3 (DBG-2, DBG-3, DBG-10), Low 10 (DBG-4…9, 11…14).
- Constraints honoured: no build commands, no process signalled, no writes under `dist/` or
  `data/`, no git operations, no browser; probes ran niced and read caches only.
