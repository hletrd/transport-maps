# Architect review — transport-maps, cycle 2

Reviewer angle: architecture and design risk — coupling and layering, the implicit
pipeline↔page contract, configuration and calibration provenance, build
identity/resumability/atomicity, the deploy layout, the scripts' environment
coupling, module boundaries, and the shape of `web/app.js`. Read-only: nothing
under `dist/`, `data/` or the repo tree was written except this file. Every claim
was checked against the code (line numbers from `cat -n` at HEAD), not against
comments or tests; where a claim rests on live state the probe is named.

Date: 2026-09-10 04:40 KST. Tree reviewed: `feat/transport-pipeline` at HEAD
`bf9e5cc` (working tree clean; `git status --short` empty). Cycle-1 fixes landed
between `ac191db` and `bf9e5cc`; the cycle-1 architect review is at
`.context/reviews/cycle-1/architect.md` (IDs ARCH-1…23 there are referred to
below as **c1-ARCH-n**; the aggregate IDs A6, A7, B2, J1… are used as the plan
does). Finding IDs in this file restart at ARCH-1.

Live state at review time (read-only `ps`, `stat`, `ls`, `curl`):

- The orchestrator's 553-origin `build-all` is running on HEAD: parent pid 94066
  started 04:23:33 (six seconds after `bf9e5cc` was committed), five forked
  workers 4143–4147 started 04:28:31 at 99 % CPU and ~2 GB RSS each.
- `dist/hover_cells.bin` was rewritten at 04:28:31 (90,740 entries) — that is the
  parent's `index.write_hover_cells` at `cli.py:196`, executed *before* the fork.
  `dist/origins/seoul.bin` (04:34) and `tokyo.bin` (04:35) have since been
  overwritten in place. `dist/index.json` is still the 157-origin, `solveRes: 5`
  file of 09 Sep 23:18 (no `modeDetail`, `fineRes` or `railDetail`), and
  `dist/origins/` holds 157 of each array, 5 `.rail.*` pairs and
  `las-vegas.pmtiles-journal`. The live site serves an `index.json` identical in
  shape to the local one (157 origins, `solveRes: 5`).
- Eight `python -u -m transport_maps.cli build-all` processes (pids 12633–12640,
  started 09 Sep 18:46:54, parent pid 1, 0 % CPU, ~10 MB RSS) are still resident:
  the pre-A3 hung pool the cycle-1 aggregate mentioned. Not mine to touch; the
  owner should reap them (they are harmless but they are the signature A3 was
  fixed for, and nothing in the build detects a stale run — see ARCH-1).

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 0 | — |
| High | 4 | ARCH-1, ARCH-2, ARCH-3, ARCH-4 |
| Medium | 6 | ARCH-5, ARCH-6, ARCH-7, ARCH-8, ARCH-9, ARCH-10 |
| Low | 5 | ARCH-11, ARCH-12, ARCH-13, ARCH-14, ARCH-15 |

The five that matter most: ARCH-1 (the build has no identity and no lock, and
`dist/` is a mixed generation *right now*), ARCH-2 (`.pmtiles` and
`water.pmtiles` are published by cross-filesystem copy, not rename — plan A6a
assumes the opposite), ARCH-4 (`app.js` is TDZ-safe only by source order, and
the scheduled D13 reorder is exactly the change that breaks it), ARCH-3 (the
contract has no version and no per-array length check on the page), ARCH-5
(the no-polars-in-workers invariant is enforced by comments only).

---

## 1. Inventory

Every file below was read in full for this review (line-numbered), unless
marked otherwise.

- `CLAUDE.md`; `.context/reviews/cycle-1/_aggregate.md` (sections A6, A7, B2,
  J1–J9 and the rest); `.context/reviews/cycle-1/architect.md`; `plan/README.md`,
  `plan/deferred.md`, `plan/2026-09-10-c1-build-robustness.md`,
  `plan/2026-09-10-c1-gates-and-tests.md`, `plan/2026-09-10-c1-web-ui-detail.md`,
  `plan/2026-09-10-c1-docs-attribution-calibration.md`,
  `plan/2026-09-10-c1-security-and-policy.md`.
- `src/transport_maps/`: `__init__.py`, `config.py`, `cli.py`, `validate.py`;
  `calibrate/fit.py`, `calibrate/ground.py`; `contour/bands.py`, `contour/grid.py`;
  `emit/airports_json.py`, `emit/borders.py`, `emit/hover.py`, `emit/index.py`,
  `emit/itinerary.py`, `emit/modes.py`, `emit/places.py`, `emit/rail_detail.py`,
  `emit/routes_json.py`, `emit/tiles.py`, `emit/water.py`; `graph/air.py`,
  `graph/build.py`, `graph/ground.py`, `graph/nodes.py`, `graph/rail.py`,
  `graph/refine.py`, `graph/transfers.py`; `solve/dijkstra.py`;
  `sources/_utils.py`, `sources/airports.py`, `sources/countries.py`,
  `sources/landmask.py`, `sources/osm.py`, `sources/roads.py`, `sources/routes.py`,
  `sources/urban.py`, `sources/wikidata.py` (the five empty `__init__.py` files
  were listed, not read).
- `calibration.toml`, `data/origins.toml` (header and count: 553 origins; there
  is no top-level `origins.toml`), `pyproject.toml`, `.gitignore`, `README.md`.
- `scripts/adsb_extract.py`, `scripts/build_water_tiles.py`,
  `scripts/calibrate_ground.py`, `scripts/check_ramps.py`,
  `scripts/expand_origins.py`, `scripts/ground_check.py`,
  `scripts/browser_verify.sh`, `scripts/deploy_verify.sh`, `scripts/osm_rail.sh`.
- `deploy/README.md`, `deploy/worldmap.atik.kr.conf`,
  `deploy/worldmap-security-headers.conf`.
- `web/app.js` (1,126 lines), `web/index.html`, `web/README.md`, `web/llms.txt`,
  `web/robots.txt`, `web/sitemap.xml`; `web/vendor/` listing only (generated).
- `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md` (all);
  `docs/superpowers/plans/2026-09-03-transport-pipeline.md` — the 15 task
  headings and every line mentioning `index.json`, `hover_cells`, `.bin`,
  `offsets`, `dist/`, `atomic`, `resum` (a targeted grep, not all 3,646 lines:
  it is the superseded pre-implementation plan, E10 is scheduled, and the
  cycle-1 architect read it whole).
- Tests read for the contract and seam questions: `tests/test_cli.py`,
  `tests/test_config.py`, `tests/test_licence_firewall.py`,
  `tests/cli/test_entrypoint.py`, `tests/web/test_ramps.py`,
  `tests/emit/test_hover.py`, `tests/emit/test_index.py`,
  `tests/emit/test_itinerary.py`, `tests/emit/test_modes.py`,
  `tests/emit/test_rail_detail.py`, `tests/emit/test_routes_json.py`,
  `tests/sources/test_cache_provenance.py`.
- Read-only probes: `git log`/`git show bf9e5cc`, `ps`, `stat dist/hover_cells.bin`,
  `ls dist/ dist/origins`, `python3 -c 'json.load(dist/index.json)'`,
  `curl https://worldmap.atik.kr/index.json`, `data/build` and `data/cache`
  listings (counts only), a sha256 of the inline gtag snippet.

## 2. Dependency graph and contract

### 2a. Module imports (`src/transport_maps`, at HEAD)

Arrows point from importer to imported. `(fn)` marks an import inside a
function body — invisible to a reader of the module header and to ruff's
import sorter. Layer order per the design spec: `sources → graph → solve →
contour → emit`, with `validate`, `config` and `cli` outside it.

```
config           <- every module (paths, resolutions, band edges, sentinel)
sources/_utils   <- sources/{airports,countries,landmask,osm,roads,routes,urban,wikidata}
                    contour/grid, emit/{airports_json,borders,places}      [cross-package use of a private helper]
sources/airports <- graph/nodes, graph/build, sources/routes, emit/airports_json
sources/landmask <- graph/nodes
sources/roads    <- graph/nodes (fn), graph/ground, emit/modes (fn, fallback)
sources/urban    <- graph/nodes (fn), graph/ground, emit/index (fn)
sources/countries<- graph/ground, graph/build (fn), validate (fn), cli
sources/osm      <- graph/build, cli
sources/routes   <- graph/build
sources/wikidata <- sources/routes
graph/nodes      <- graph/{build,ground}, solve/dijkstra, cli
graph/air        <- graph/{build,transfers}
graph/rail       <- graph/build, graph/nodes (fn), emit/rail_detail (fn)   [emit -> graph]
graph/refine     <- graph/{nodes (fn),ground,build}, emit/modes (MODULE level since b38fb8b)   [emit -> graph]
graph/ground     <- graph/build, validate (fn), emit/index (fn), cli        [emit -> graph]
graph/transfers  <- graph/{build,ground}, validate (fn), cli
contour/bands    <- cli, validate (fn)
contour/grid     <- contour/bands (fn), cli
emit/hover       <- emit/{index,itinerary (fn),modes (fn),rail_detail (fn)}
emit/*           <- cli
validate         <- cli
calibrate/*      <- scripts only
```

Reverse or cross-layer edges at HEAD (every one still present from cycle 1
except `sources/urban -> emit/places`, which A5 removed):

| Edge | Where | Kind |
|---|---|---|
| `emit/index` → `graph/ground`, `sources/urban` | `emit/index.py:104-105` (`mode_detail`) | emit reaches back for calibration figures (B2) |
| `emit/modes` → `graph/refine` | `emit/modes.py:19` (module level) | emit reaches back; acceptable direction for a shared predicate, but it lives in `graph` |
| `emit/modes` → `sources/roads` | `emit/modes.py:47-50` (fn, fallback when `cell_class is None`) | a rasterio path a forked worker must never take (ARCH-5) |
| `emit/rail_detail` → `graph/rail.station_key` | `emit/rail_detail.py:46,72` (fn) | emit reaches back |
| `emit/rail_detail` → `polars` | `emit/rail_detail.py:17` (module level) | a worker-side module importing the library workers must not call (ARCH-5) |
| `emit/{airports_json,borders,places,water}` | HTTP + `config.CACHE` writes | sources disguised as emitters (J2, deferred) |
| `contour/grid`, `emit/*` → `sources/_utils._atomic_write` | `grid.py:24`, `places.py:25`, `borders.py:17`, `airports_json.py:11` | private helper used by four packages (J2) |
| `validate` → `graph/ground`, `graph/transfers`, `sources/countries`, `contour/bands` | `validate.py:66,140-141` (fn) | the gate module depends on everything it gates; the countries fallback at `:149-153` is a GDAL/polars path (ARCH-5) |
| `cli` → `sources/countries` (for `zone`), `graph/transfers` | `cli.py:28-30,173-176` | orchestration re-derives `zone` exactly as `build._border_rules` and `ground.hex_edges` do — three copies of the same two lines |

No import cycle exists at module load; the cycles that would exist are avoided by
hiding edges in function bodies. `bf9e5cc` did not add an edge; it moved the
polars work from the worker path into the parent (`rail_detail.lookup_tables`,
called at `cli.py:185`), which is the right direction.

### 2b. Pipeline ↔ page contract as it exists at HEAD

| Artefact | Producer | Consumers | Layout / schema | Re-typed at |
|---|---|---|---|---|
| `index.json` | `emit/index.py:120-140` | `app.js:54-67,125,131,211,225,483,599,806,816`; `deploy_verify.sh:13,28,31,43`; `browser_verify.sh:11-13` | `bandEdgesMin[36]`, `unreachable`, `hoverRes`, `solveRes`, `fineRes` (unused by the page), `modeDetail{6}`, `railDetail: true` (always), `hoverCellsUrl`, `attribution[9]`, `origins[{slug,name,lat,lon}]`. No version, no build id, no hover-cell count, no channel list, no suffix table | page fallbacks `?? 65535`, `?? 4`, `?? 6`, `?? []`, `?? 10` (`app.js:55-64,125`) |
| `hover_cells.bin` | `emit/index.py:91-99` (`<u8`, sorted) | `app.js:67,541-550` (`BigUint64Array`, binary search) | LE uint64 H3 ids, sorted; platform-endian typed array on the page (LE assumed) | — |
| `origins/{slug}.pmtiles` | `emit/tiles.py` from `contour/bands.py` | `app.js:463-476,672-689` | layer `bands`; props `band` (−1 = unreachable), `max_minutes`; four LODs by `tippecanoe.minzoom/maxzoom` (`bands.py:161-166`); **rendering invariant the pipeline relies on**: faster band painted on top (`fill-sort-key`, `app.js:470`; `bands.py:5-20`) | layer name `tiles.py:20` ↔ `app.js:465`; −1 `bands.py:40` ↔ `app.js:23` |
| `origins/{slug}.bin` | `emit/hover.py:59-72` | `app.js:489-499,555-559` | LE uint16 minutes per hover cell, 65535 = no route, clamp 65534 | `hover.py:23`, `modes.py:28` (65534 twice); `config.py:31` ↔ `app.js:55` |
| `origins/{slug}.air.bin` | `emit/itinerary.py:49-71` | `app.js:508-511,564-580` | LE uint16 arrival-airport ordinal; 0xFFFF none | `itinerary.py:18` ↔ `app.js:145` |
| `origins/{slug}.modes.bin` | `emit/modes.py:82-101` | `app.js:504-507,606-616`; `deploy_verify.sh:18` (width 12) | 6 × LE uint16 per hover cell in `CHANNELS` order | `modes.py:24` ↔ `app.js:610` ↔ `deploy_verify.sh:18` ↔ `index.py:109-116` (keys) ↔ `app.js:130-137` (`MODE_FALLBACK` keys) |
| `origins/{slug}.rail.bin` + `.rail.json` | `emit/rail_detail.py:80-110` | `app.js:483-488,743-750` (only if `meta.railDetail`) | uint16 index into `stations[[station,line]]`; 0xFFFF none | `rail_detail.py:21` ↔ `app.js:742`; `deploy_verify.sh:21-23` treats the file as optional regardless of the flag |
| `origins/{slug}.json` | `emit/routes_json.py` | `app.js:512-519,564-580` | `offsets{cells,airports,stations}`, `nodes[{id,kind:dep\|arr,code,min,prev}]`; airport nodes only | node arithmetic `n_cells + 2*n_airports`: `routes_json.py:52`, `itinerary.py:32-33,61`, `modes.py:45`, `rail_detail.py:29,90`, `app.js:571-573`; `NodeIndex.n` at `nodes.py:74` is the only place that owns it |
| `places.json`, `airports.json`, `borders.json` | `emit/{places,airports_json,borders}.build` — still **no CLI stage** (E6, docs plan) | `app.js:229,399,821`; required by `deploy_verify.sh:29` | columnar JSON | — |
| `water.pmtiles` | `emit/water.py` via `scripts/build_water_tiles.py` | `app.js:371-373` | layer `water` | `water.py:32` ↔ `app.js:372` |
| file suffixes and the `origins/` directory | `cli.py:116-124` | `app.js:463,484-485,489,504,508,512`; `deploy_verify.sh:18,26,58-61` | — | three copies |
| `data/origins.toml` | hand + `scripts/expand_origins.py` (appends) | `emit/index.load_origins` | `[[origin]] slug,name,lat,lon` | slug grammar: `cli.py:34` (`--name` only) vs `expand_origins.py:51-54`; `load_origins` checks uniqueness only (A17) |
| DOM/verification contract | `web/index.html`, `app.js:350` (`window.__map`) | `browser_verify.sh:23-26,37-39,44-48,52,58-59,64-67,71,77-80` | 15 selectors + one global | shell only; no test (ARCH-7) |

The original pipeline plan (`docs/superpowers/plans/…:3645`) said the contract
would be documented by a separate frontend plan; that document was never written,
which is where J1 comes from.

---

## 3. Findings

### High

#### ARCH-1 — The build has no identity and no lock; `dist/` is a mixed generation for the whole 7–8 h run, and a second `build-all` or a `--limit` run against the same `dist/` interleaves silently

- Severity: **High** · Confidence: High · Status: **Confirmed (live)** · Effort: M (lock and staging dir: S each; sidecars: M)
- Where: `cli.py:196` (`write_hover_cells` before the loop), `cli.py:116-124`
  (per-origin files written straight into `dist/origins/`), `cli.py:228-231`
  (`--limit` overwrites the first N origins and `hover_cells.bin` but leaves the
  other ~550 origin files and `index.json` from whatever build was there);
  `scripts/deploy_verify.sh:12-25` (length equality is the only cross-file
  check; `.pmtiles` is `exists()` only at `:26-27`); no lock file anywhere.
- Why it is a problem: at this moment `dist/` holds a res-5 `index.json` (157
  origins), a res-6 `hover_cells.bin` (04:28:31, 90,740 entries) and a moving
  mixture of res-5 and res-6 per-origin arrays (`seoul.bin` 04:34, `tokyo.bin`
  04:35). The plan's own progress note records the last deploy attempt refusing
  on exactly this ("90,659 entries against a 90,740-entry hover_cells.bin"). The
  refusal was luck: whenever two builds share a cell universe — a recalibration,
  a route-network refresh, any change that moves numbers but not cells — every
  length agrees and the gate passes on a mixed set. Nothing records which build
  produced which file; nothing prevents a second `build-all` (or a
  `scripts/build_water_tiles.py`, or `deploy_verify.sh`'s `rsync web/ dist/`)
  from writing into the same directory while this one runs. The eight orphaned
  workers from 09 Sep show that a stale run can also just *sit there*
  undetected.
- Failure scenario: the owner recalibrates `[rail]` next week and re-runs
  `build-all`; the run dies at origin 300 of 553 (tippecanoe OOM, a gate);
  `dist/` now has 300 new and 253 old arrays of identical length; `deploy_verify.sh`
  passes; the site shows rail times from two models depending on the city.
- Minimal fix: (1) `dist/.build.lock` opened with `O_CREAT|O_EXCL` holding the
  pid and start time, removed in `finally`; `deploy_verify.sh` and
  `build_water_tiles.py` refuse while it exists (a stale lock whose pid is dead
  is reported, not silently reused). (2) Write everything into
  `dist/.build-{build_id}/` and publish by rename at the end (design under A6b
  below). (3) Per-origin sidecar written last as the origin's commit record
  (A6c). References: A6 (aggregate), c1-ARCH-7 — new evidence is the live mixed
  state, the `--limit` semantics and the absence of a lock.

#### ARCH-2 — `tiles.write_pmtiles` and `water.build` publish by cross-filesystem `shutil.move`, which is a copy plus unlink, not a rename; plan A6a assumes the opposite

- Severity: **High** · Confidence: High · Status: Confirmed (by reading; the
  docstring states the mechanism) · Effort: S
- Where: `emit/tiles.py:28-38` (GeoJSON and staged `.pmtiles` under the system
  temp directory, local disk), `:68-70` (`shutil.move(str(staged), str(out))`,
  with the comment "handles the cross-filesystem case (local -> NFS) that
  os.replace cannot"), `:77-78` (post-check is `exists()` and `size > 0`);
  `emit/water.py:96-100,124` (`TemporaryDirectory()` then `shutil.move` of an
  867 MB file into `dist/`).
- Why it is a problem: `shutil.move` across filesystems is `copy2` then
  `unlink`. For the whole duration of the copy `dist/origins/{slug}.pmtiles`
  exists and is truncated; a concurrent `rsync` (deploy) or a killed worker
  leaves a partial `.pmtiles` that `deploy_verify.sh:26-27` accepts (`exists()`
  only) and that the page reads as a broken archive with no console error
  (PMTiles fails on the header range). This is the largest per-origin artefact
  and the one the plan's A6a says "already moves atomically (verify it is a
  rename, not a copy, on this filesystem)" — it is a copy. `las-vegas.pmtiles-journal`
  in `dist/origins/` (I4) is a sqlite journal from an older writer that wrote
  directly into `dist/`, i.e. this class of failure has already happened once.
- Failure scenario: worker killed by `Pool.terminate()` (A3's abort path,
  `cli.py:212-218`) mid-copy → truncated `.pmtiles` of non-zero size → deploy
  gate green → blank bands for that origin, no error.
- Minimal fix: keep tippecanoe on local disk (the sqlite-over-NFS reason is
  sound), then copy to `out.parent / f".{out.name}.tmp"` (same directory, same
  filesystem) and `os.replace` it onto `out`; same in `water.build`. Reuse
  `_atomic_write` with a `write_fn` that does the copy. Test: monkeypatch
  `os.replace` to record its arguments and assert the source is in `out.parent`;
  mutation — restore `shutil.move` → the recorded source is under `$TMPDIR` →
  red. `deploy_verify.sh` (or `check-dist`, ARCH-7) should compare `.pmtiles`
  sizes against the sidecar (A6c) and refuse any `*-journal`/`.tmp` in
  `dist/origins/`.

#### ARCH-3 — The contract has no version and no per-array length check on the page; the only cross-generation defence is `deploy_verify.sh`'s length equality, and the page's `??` fallbacks accept any `index.json`

- Severity: **High** · Confidence: High · Status: Confirmed · Effort: M
- Where: `emit/index.py:120-140` (no `contractVersion`, `buildId`,
  `hoverCellCount`, `modeChannels`, `sentinels`, `files`); `web/app.js:55-64,125`
  (`?? 65535`, `?? 4`, `?? 6`, `?? []`, `?? 10` — the last is stale: 36 edges
  ship); `app.js:489-499` (`hoverTimes = new Uint16Array(b)` with no check that
  `hoverTimes.length === hoverCells.length`); `app.js:610` (channel list),
  `:145,:742` (sentinels), `:571-573` (node arithmetic) re-typed;
  `deploy_verify.sh:18` (widths), `:21-23` (`.rail.bin` optional regardless of
  `index.json.railDetail`); `deploy/worldmap.atik.kr.conf:39-56` (`no-cache`
  + ETag: a visitor who loaded `hover_cells.bin` before a deploy and switches
  origin after it fetches a new `.bin` against the old ordering).
- Why it is a problem: the served build is contract "v1" (no `modeDetail`,
  `railDetail`, `fineRes`) and the page copes only because every field has a
  silent default; when the 553-origin build ships, a client mid-session holds
  old `hover_cells.bin` and fetches new origin arrays — `cellIndex` then indexes
  the wrong row, or past the end (`undefined` → "—"), with no error. Server-side
  atomicity (A6d) cannot close that window; only a page-side check can. On the
  build side, the current `index.json` literally cannot say which of the two
  generations in `dist/` it describes (ARCH-1).
- Failure scenario: A6d lands, a visitor has the page open across the deploy,
  clicks Lagos; the readout shows Lagos numbers indexed by the old cell order —
  plausible-looking, wrong everywhere.
- Minimal fix (this is J1, with the page-side check added): ship
  `contractVersion`, `buildId`, `hoverCellCount`, `modeChannels`, `sentinels`,
  `files` in `index.json`; on the page, `fatal()` (it exists now, `app.js:37-41`)
  when `contractVersion` is unsupported, and on every origin array compare its
  length with `hoverCells.length` — on mismatch re-fetch `index.json` and
  `hover_cells.bin` (cheap: 12 KB + 726 KB) or show "the map was updated,
  reload". `deploy_verify.sh` derives widths from `modeChannels` and requires
  `.rail.*` when `railDetail` is true. Design and tests in §4 (J1).

#### ARCH-4 — `web/app.js` module state is declared mid-file, after the functions that assign to it; TDZ safety rests on `paintOrigin(FALLBACK)` being the last statement — and D13's reorder is precisely the change that moves it

- Severity: **High** (latent; becomes live with scheduled cycle-2 work) ·
  Confidence: High · Status: Confirmed (by reading) · Effort: S
- Where: `let pinB` at `app.js:739`, `let railDetail` at `:741`, `let airports`
  at `:820`, `const cities`/`bySlug` at `:816-817`, `let addressSeq` `:875`,
  `let reverseSeq` `:920` — all after `paintOrigin` (`:458-526`, which assigns
  `railDetail = null` at `:480` and calls `renderPins()` at `:525`, which reads
  `pinB` at `:756`), `renderLegs` (`:582-665`, reads `airports` at `:595`) and
  `nearest()` (`:1082-1089`, reads `cities`). Everything works because the only
  early call, `paintOrigin(FALLBACK)`, sits at `:1094`. Separately, the
  `places.json` `.then` at `:229-311` references `map` (declared `const` at
  `:332`); it is safe only because no `await` exists between `:229` and `:347`,
  so the callback cannot run before `:332` executes.
- Why it is a problem: D13 (web plan, cycle 2) is "create the map before
  `hover_cells.bin` arrives" and "fetch modes/json lazily" — the natural edit
  calls `paintOrigin` (to show tiles) before the `let` block at `:739-742`, and
  `railDetail = null` at `:480` then throws `ReferenceError: Cannot access
  'railDetail' before initialization`. The error happens after the map is
  created but before the readout is wired, so the symptom is the one
  CLAUDE.md's deploy rule records twice: a blank or half-dead page with no
  useful console error after the fact. Inserting an `await` between `:229` and
  `:332` (e.g. awaiting the cells promise "later") has the same effect via the
  `places` callback, and that one is swallowed by `.catch(() => {})` at `:311`
  — no labels, no error.
- Failure scenario: as above, on the local preview it "works" if the first
  origin's fetches happen to resolve after module evaluation; deployed on a
  fast CDN it throws.
- Minimal fix: one "module state" block at the top of the file (after the
  `meta` load) declaring every `let` the functions assign — `active`, `pinB`,
  `railDetail`, `airports`, `places`, `hoveredCell`, `raf`, `addressSeq`,
  `reverseSeq`, the origin data (C5 collapses six of them into one object).
  Ten lines moved, no behaviour change. Make it the first commit of the C5/D13
  work, and add to the plan's verification line: run `scripts/browser_verify.sh
  http://127.0.0.1:8899/` against the local preview *before* deploy, since the
  canvas/city-list checks are what catch this class. J3 (module split) stays
  deferred; this is not that.

### Medium

#### ARCH-5 — "No polars, GDAL or rasterio inside a forked worker" is an invariant enforced by comments; four code paths violate it if a caller drops a keyword, and the test stub cannot see them

- Severity: Medium · Confidence: High · Status: Confirmed · Effort: M
- Where: `cli.py:5-9,170-172,184` (the rule, as comments); `cli.py:123`
  (`shared.get("rail_tables")` — a soft key: a typo yields a build whose every
  `.rail.bin` is `NO_RAIL`, silently); `emit/modes.py:47-50` (`cell_class is
  None` → `roads.cell_class` → rasterio and the `_grid_cache` global);
  `validate.py:149-153` (`country`/`zone` None → `countries.cell_country`, i.e.
  pyogrio + polars); `emit/rail_detail.py:17` (module-level `import polars`,
  now used only in the parent-side `_line_between`/`lookup_tables`, but nothing
  stops a future `pl.` call in `write_rail_detail`); `tests/test_cli.py:29-112`
  (`_stub_pipeline` replaces all seven emitters and both gates, so renaming
  the key at `cli.py:185` leaves every test green — checked by reading: the
  stub at `:110-112` ignores its `routes` argument).
- Why it is a problem: the symptom of a violation is the A3 signature — 0 %
  CPU, no exit, no traceback, hours lost — and it took two incidents
  (`cli.py:7`, `rail_detail.py:64-68`) to find each time. `bf9e5cc` fixed the
  instance, not the class.
- Failure scenario: a contributor adds a `--no-cell-class` debugging flag or
  refactors `_solve_one` to call `modes.write_modes(...)` without `cell_class`;
  the serial path (tests, `--limit 3`) works; the 553-origin forked run hangs.
- Minimal fix: replace the `shared` dict with a frozen `BuildContext` dataclass
  (`country, zone, cell_class, grid, native, rail_tables, hover_grid, cal,
  build_id`) — required fields, no `.get`; pass it via
  `Pool(initializer=_install_ctx, initargs=(ctx,))` (under the fork start
  method the object is inherited, not pickled, so `globals()["_CTX"]` goes
  away — J8's exit criterion moves); delete the in-function fallbacks in
  `modes.py:47-50` and `validate.py:149-153` (raise `TypeError` instead). Test:
  run `_solve_one` on the small fixture inside a forked child after
  `monkeypatch`ing `polars.DataFrame.__init__`, `pyogrio.read_arrow` and
  `rasterio.open` to raise; mutation — restore either fallback and pass `None`
  → the child raises → red (and, importantly, the test proves the fixture
  actually reaches the writer, which `_stub_pipeline` does not).

#### ARCH-6 — Per-origin writers rebuild a 10 M-entry dict four times per origin and recompute origin-independent structure per origin; this is H2's cost and part of H5's memory un-sharing

- Severity: Medium · Confidence: High · Status: Confirmed · Effort: M
- Where: `emit/hover.py:40-41` (`position` and `cell_pos = {c: i for i, c in
  enumerate(idx.cells)}` — a dict over every solver cell — inside
  `_representative_children`), called once each from `hover.py:63`,
  `itinerary.py:66`, `modes.py:96`, `rail_detail.py:94` for every origin;
  `hover.py:28`, `itinerary.py:58`, `modes.py:90`, `rail_detail.py:86` each
  re-sort the parent set; `validate.py:33-37` (`reachable_in_principle`: one
  `cell_to_latlng` per solver cell, per origin); `validate.py:153` and
  `ground.py:28-34` (`_land_border_min` re-parses `calibration.toml` per
  origin, and per `hex_edges`/`_border_rules` call at build time).
- Why it is a problem: four 10 M-entry dicts per origin in each of five workers
  is CPU, allocator churn and — because building them touches every cell
  string's refcount — the copy-on-write page duplication `cli.py:63-67,78-82`
  describes. The plan's H2 names the rail tables (fixed in `bf9e5cc`) and
  "hover parents / representative children"; the dict is the expensive part
  and the reason the four emitters cannot be shown to share one ordering (F7).
- Minimal fix: a `HoverGrid` computed once in the parent (design in §4, H2);
  each writer takes it and calls `grid.pick(cell_minutes)`. Move
  `reachable_in_principle` and the border minute into the context too.

#### ARCH-7 — Verification is a shell script that (a) is a second writer of `dist/`, (b) re-types the contract as inline Python, (c) binds the page to fifteen DOM selectors, and (d) kills every `agent-browser` process on the host by name

- Severity: Medium · Confidence: High · Status: Confirmed · Effort: M
- Where: `scripts/deploy_verify.sh:54` (`rsync -a --exclude README.md web/
  dist/` mutates the build output directory before deploying it — while
  `build-all` may be writing there, ARCH-1); `:9-37` (widths, suffixes and the
  required-extras list re-typed; `.pmtiles` checked by existence); `:6,55,58-62`
  (repo path, host path, URL ×4 hard-coded; J5); `scripts/browser_verify.sh:23-26,
  37-39,44-48,52,58-59,64-67,71,77-80` (selectors `.results button`, `.tints span`,
  `.keys .sw`, `#ramps button`, `.disclaimer`, `#legs .ap`, `#legs .mode`,
  `.results .addresses button[data-geo]`, `.lbl.origin`, `#tints`, `.reading`,
  `.rail`, `.mast`, `#compass`, `#time`, plus `window.__map` from
  `app.js:350`); `:16` (`SCHEMES=12` while `RAMPS` in `app.js:74-85` is the
  source); `:18,74,86` (`cd /tmp`, screenshots in `/tmp`); `:89` (`kill -9`
  of every process matching `agent-browser` — in this session that is the
  designer reviewer's browser, and on the owner's machine any other agent's).
- Why it is a problem: a renamed CSS class silently turns a gate into a
  guaranteed failure (or, with an inverted grep, a vacuous pass); the deploy
  gate cannot be unit-tested (F9) because its logic is a heredoc; two
  processes write `dist/`; and the cleanup violates the CLAUDE.md rule's
  intent ("kill agent-browser's own Chrome tree") by scope, not by target.
- Minimal fix: (1) `transport-maps check-dist [--dist PATH] [--json]` in the
  package, importing `modes.CHANNELS`, `config.HOVER_RES`, the sidecars and the
  suffix table directly (no re-typing), tested on a temp `dist/` (F9); the
  shell script calls it. (2) Assemble the release outside `dist/`
  (`dist/.release-{buildId}/` or a temp dir) instead of copying `web/` into the
  build output. (3) The page exports `window.__diagnostics()` returning the
  facts the script asserts (`cities`, `tints`, `schemes`, `waterFeatures`,
  `bandsBelowWater`, `disclaimerVisible`, `legs`) so the contract is one
  function, not fifteen selectors; `browser_verify.sh` asserts values. (4)
  Cleanup scoped to the session the script opened (`agent-browser close` plus
  the pid it started), never a name grep; `VERIFY_TMP` under the repo's
  scratch dir.

#### ARCH-8 — Calibration is loaded by four loaders in three modules, parsed again per origin inside a gate, and the two most consequential fitted tables live in code; CLAUDE.md's provenance rule has no mechanical check

- Severity: Medium · Confidence: High · Status: Confirmed · Effort: M
- Where: loaders `graph/air.py:29-45` (called three times per graph build:
  `build.py:60,137,174`), `graph/rail.py:44-47,50-54`, `graph/ground.py:28-34`
  (`_land_border_min`, called from `ground.py:89`, `build.py:228` (twice via
  `_border_rules` at `:250,285`) and per origin from `validate.py:153`);
  fitted-but-in-code `ground.py:25` (`SPEED_BY_ROAD_CLASS_KMH`, "FITTED against
  2,998 journeys"), `urban.py:30-32` ("Fitted jointly"); model constants that
  change travel times but are neither in the file nor labelled: `air.py:63,79`
  (`MIN_FLIGHTS_PER_WEEK`, `KNEE_KM`), `build.py:29` (`IMPLAUSIBLE_LONGHAUL_KM`),
  `osm.py:101` (`MIN/MAX_FERRY_KM`); stale provenance prose
  `calibration.toml:42-48,95` ("refitted in Task 12/13"); `emit/index.py:110-116`
  hard-codes "200 km/h", "75 km/h", "35 km/h plus 30 min" that `[rail]`/`[ferry]`
  own; `tests/test_licence_firewall.py:61-68` forbids lists in the file (so a
  `[ground]` table must be six keyed scalars) and `:72` caps the JSON dump at
  4,000 bytes (headroom is fine: the file is ~30 scalars).
- Why it is a problem: B2 is scheduled, but as an editing task; the rule
  "each constant carries a fitted/default label" will drift again without a
  test, and the per-origin TOML parse inside `check_monotonic_ground` is a
  config read hidden in a gate (a broken file fails at origin 1, after the
  graph is built — 15 minutes late).
- Minimal fix: one `calibrate.load(path) -> Calibration` (frozen dataclass with
  `.air`, `.rail`, `.ferry`, `.ground`, `.urban`, `.land_border`) loaded once
  in `_build_all` and threaded through `BuildContext` (ARCH-5) and
  `build_graph(idx, cal=...)`; `mode_detail(cal)`; `[ground]`, `[urban]`,
  `[air_bounds]` tables with labels; a provenance test that parses the raw TOML
  text and asserts every table header is preceded (within its comment block)
  by "fitted" or "published-figure default" — mutation: delete one label →
  red. Where to draw the line: constants that change a *time* belong in
  `calibration.toml`; constants that change the *graph's shape* (resolutions,
  `SPLIT_MAX_CLASS`, `STATION_RES`) stay in `config.py`/modules. The move of
  the ground table must wait for the running build (the plan notes this).

#### ARCH-9 — The inline gtag bootstrap in `index.html` and its sha256 in the CSP snippet are a hand-synchronised pair with no test; an edit to either silently kills analytics

- Severity: Medium · Confidence: High · Status: Confirmed (currently in sync:
  computed `pCkIJ0WqstDvWvix9v7v2C15fx9jgy6oPf71TIqllqU=` from
  `web/index.html:6-11`; present in `deploy/worldmap-security-headers.conf:18`)
  · Effort: S
- Where: `web/index.html:6-11`; `deploy/worldmap-security-headers.conf:18`;
  `deploy/README.md:57-62` (documents the trap in prose).
- Why it is a problem: CSP-blocked inline scripts fail with a console message
  only; `browser_verify.sh:75` counts console "error" lines, so a mismatch
  *might* be caught post-deploy — but the conf is installed by the owner out of
  band (E3 server half), so the page and the header can drift in either
  direction with nothing in the repo noticing.
- Minimal fix: `tests/web/test_csp.py` — read the first inline `<script>` body
  from `index.html`, sha256 → base64, assert `sha256-<hash>` appears in the
  snippet; mutation: change one character of the snippet → red. Ten lines.

#### ARCH-10 — `solve` and `index` remain divergent entry points; `solve` writes into `dist/` root where `rsync --delete` ships it, `index` rebuilds the cell universe independently of the arrays it advertises

- Severity: Medium · Confidence: High · Status: Confirmed · Effort: S (delete) / M (align)
- Where: `cli.py:264-282` (`solve`: `dist/{name}.pmtiles`, `dist/{name}.hover.bin`,
  `dist/{name}.routes.json`; no gates; no `grid`/`native`; a layout the page
  cannot read), `cli.py:284-294` (`index`: `write_index` for every origin in
  `origins.toml` with no check of files, then `write_hover_cells` from a fresh
  `build_index()`), `deploy_verify.sh:55` (no excludes: `solve` leftovers go
  live).
- New evidence since cycle 1: `index` now writes `hover_cells.bin` *after*
  `index.json` (`:289-292`), the reverse of `_build_all`'s justified order, and
  neither subcommand has a test (F8). A7 (aggregate), c1-ARCH-6.
- Minimal fix: design under A7 in §4 — delete both; `build-all --only slug,…`
  covers the one-origin use; `check-dist` covers the "is it consistent" use.

### Low

#### ARCH-11 — `PAGE_CREDITS` in `app.js` duplicates two `ATTRIBUTION` entries with their licence strings; README is test-synced, the JS copy is not

- Severity: Low · Confidence: High · Status: Confirmed · Effort: S
- Where: `app.js:204-208` (GeoNames, HydroLAKES, Nominatim); `emit/index.py:59-70`
  (GeoNames, HydroLAKES); `tests/emit/test_index.py:83-90` syncs README only.
- Fix: keep only Nominatim (the one runtime-only source) in `PAGE_CREDITS`;
  extend the README test to grep `app.js` for any `ATTRIBUTION` name it repeats
  and fail — mutation: add GeoNames back → red.

#### ARCH-12 — `index.json` says `railDetail: true` unconditionally and nothing in the artefact says whether rail or ferries were in the graph

- Severity: Low · Confidence: High · Status: Confirmed · Effort: S
- Where: `emit/index.py:131`; `cli.py:45-59,136-149` (`EXCLUDED` goes to
  stdout only); `web/llms.txt:33-34` claims rail and ferry are in the graph.
- Why: a road-and-air build (extracts absent) is indistinguishable from a full
  one in `dist/`, and `deploy_verify.sh` cannot refuse it.
- Fix: `index.json.graph = {"rail": bool, "ferry": bool, "stations": n,
  "ferryCrossings": n}` from `idx.has_rail`/`ferry_links`; `check-dist` refuses
  `rail: false` unless `--allow-no-rail`. Belongs in J1's schema.

#### ARCH-13 — `contour/grid.MIN_CELLS_TO_CACHE` switches the cache path on input size, so fixtures never exercise it

- Severity: Low · Confidence: High · Status: Confirmed · Effort: S
- Where: `contour/grid.py:31,44,71,97,126`.
- Fix: an explicit `cache: bool | None = None` parameter (None → size rule) so a
  test can force the cached path on a 12-cell fixture with `config.BUILD`
  redirected; mutation: break the `npz` key names → red.

#### ARCH-14 — Two slug grammars and no grammar check where slugs become URL paths

- Severity: Low · Confidence: High · Status: Confirmed · Effort: S
- Where: `cli.py:34` (`_SLUG_RE`, applied to `--name` only), `scripts/expand_origins.py:51-54`
  (`slugify`, lowercase-hyphen), `emit/index.py:81-88` (`load_origins` checks
  uniqueness only), `app.js:463-512` (slug in URL path). A17 is scheduled; the
  design point is that `load_origins` should be the single validator and
  `expand_origins.py` should import `_SLUG_RE` rather than own a second rule.

#### ARCH-15 — Site URL, server path and repo path exist in five places outside any config

- Severity: Low · Confidence: High · Status: Confirmed · Effort: S
- Where: `deploy_verify.sh:6,55,59-62`; `browser_verify.sh:6`;
  `deploy/worldmap.atik.kr.conf:22`; `web/index.html:16,24,43`;
  `web/sitemap.xml:3`; `web/robots.txt:3`. J5 (docs plan, cycle 2) covers the
  scripts; the page copies are legitimately static. One `deploy/.env` with
  `SITE_URL`, `DEPLOY_HOST`, `DEPLOY_ROOT`, sourced by both scripts, with the
  current values as documented defaults.

Still open from cycle 1 with no new evidence (one line each, by aggregate ID):
J2 (emit reaches back; borders/places/water are sources — deferred, exit
criterion unmet), J3 (app.js globals — deferred; C5 below reduces six of them),
J4 (no injection seams — `BuildContext` in ARCH-5 is the seam F8/F10 need),
J6, J7, J8 (deferred; ARCH-5 removes `globals()["_CTX"]` as a side effect), J9,
E6 (`places/airports/borders` still have no producing stage: zero callers of
the three `build()` functions in `src/`, `scripts/` or `tests/`), C3/C1/C2
(contract changes waiting on a rebuild), H1/H3/H4/H5/H9 (deferred performance),
B1 (model), A15.

---

## 4. Design notes for the cycle-2 backlog

The CLAUDE.md mutation rule applies to every test named here: the guard is not
done until the named mutation has been shown red and reverted.

### A6a — atomic per-origin writes

- Shape: move `_atomic_write` (and `_params_hash`) to `transport_maps/_io.py`
  with public names; `hover.py:71-72`, `itinerary.py:70-71`, `modes.py:100-101`,
  `rail_detail.py:107-110`, `routes_json.py:56-57` write through it;
  `tiles.py` and `water.py` copy the local-disk output to a same-directory
  dot-temp and `os.replace` (ARCH-2). Do not add a per-file fsync policy; the
  rename is the guarantee that matters here.
- What it does not give: per-*origin* atomicity. Seven files renamed one after
  another still leave a window in which `.bin` is new and `.air.bin` old with
  equal lengths. A6a is the precondition for A6c's sidecar to mean anything
  (a sidecar written last is a commit record only if each sibling is either
  complete or absent), not a substitute for it.
- Blast radius: seven emitters, four import sites of `sources._utils`, the
  `tests/emit/*` files that read outputs (paths unchanged; behaviour
  unchanged), `tests/sources/test_cache_provenance.py::test_atomically_written…`
  (moves with the helper).
- Test: for each writer, monkeypatch the inner write (e.g. `np.ndarray.tobytes`)
  to raise after the temp file is created → target absent, no `.tmp` left
  behind; mutation — call `out.write_bytes` directly → a truncated target
  exists → red. For `tiles.py`: assert `os.replace`'s source is in
  `out.parent`; mutation — restore `shutil.move` → red.

### A6b — `hover_cells.bin` and `index.json` last

- Recommended shape: **staging, not reordering.** `_build_all` creates
  `dist/.build-{build_id}/` (with `origins/`), writes `hover_cells.bin` there
  first (it is graph-only and workers may as well have it), every origin's
  files there, and `index.json` there last; on success it publishes with three
  same-filesystem renames — `dist/origins` → `dist/.origins-prev-{id}`,
  `.build-{id}/origins` → `dist/origins`, then `hover_cells.bin`, then
  `index.json` (`os.replace`, last). A `--limit`/`--only` run never publishes;
  it prints the staging path. The previous `origins/` is removed only after
  the publish succeeded (and can be kept one generation for rollback).
- Why the literal plan text is not enough: writing `hover_cells.bin` last in
  place inverts the window (new origin arrays beside an old `hover_cells.bin`
  for seven hours) and leaves the same-length mixed case invisible; it would
  give the deploy gate a false sense of order. The `--limit` semantics today
  ("index.json left untouched", `cli.py:228-230`) already illustrate the
  problem: the *other* files are overwritten.
- Flag: `dist/` is not owned solely by `build-all` — `water.pmtiles`
  (`build_water_tiles.py`) and the copied `web/` assets live there too. Only
  the three build-owned entries are swapped; the lock (ARCH-1) covers the rest.
- Blast radius: `cli._build_all` (~30 lines), `tests/test_cli.py` (paths move
  under the staging dir; `written` counts unchanged), `deploy_verify.sh`
  (refuse when `.build-*`/`.build.lock` exists), `.gitignore` (already covers
  `dist/`).
- Test: seed `tmp_path` with a fake previous build (`index.json`,
  `hover_cells.bin`, `origins/first.bin` with known bytes), run `_build_all`
  with the second origin failing → the three seeded files are byte-identical
  afterwards and `.build-*` holds the partial output; mutation — write
  `hover_cells.bin` to `config.DIST` directly → seeded bytes changed → red.
  Companion: a full run publishes and the staging directory is gone.

### A6c — `build_id` and sidecars

- Shape: `inputs_hash = _params_hash(git HEAD + dirty flag, sha256 of
  calibration.toml, sha256 of data/origins.toml, the land-cells cache stamp
  name, routes.parquet (size, mtime_ns), config.{SOLVE_RES, FINE_RES,
  HOVER_RES, BAND_EDGES_MIN}, modes.CHANNELS, CONTRACT_VERSION)`;
  `build_id = f"{inputs_hash}-{start_utc:%Y%m%dT%H%M%SZ}"`. `index.json` gets
  `buildId`, `inputsHash`, `builtAt`, `contractVersion`, `hoverCellCount`.
  Each origin gets `origins/{slug}.meta.json` written **last** of its eight
  files (it is the commit point): `{"buildId", "inputsHash", "files": {".bin":
  size, ".air.bin": size, …}}`. `check-dist` requires: every origin listed in
  `index.json` has a sidecar; `sidecar.buildId == index.buildId`; every listed
  file exists with the recorded size; `hover_cells.bin` size ==
  `hoverCellCount * 8`; array sizes == `hoverCellCount * width` with widths
  from `modeChannels`. Resume (A6e, later) skips a slug whose sidecar's
  `inputsHash` matches and whose sizes verify — the identity for deploy is the
  full `buildId`, the identity for resume is `inputsHash`. A rsync exclude
  keeps sidecars off the server (or not — they are 200 bytes each; keeping
  them lets a live `check-dist --url` run).
- Flags: do not put per-origin hashes in `index.json` (page payload); do not
  make `build_id` time-only (kills resume) or inputs-only (two runs of one
  input set become indistinguishable when one was aborted — the dirty flag
  and the start stamp separate them). Sidecars must be written after the
  seven files, not before, or they certify nothing.
- Blast radius: `cli`, `emit/index`, a new `emit/meta.py` (or `_io.py`),
  `check-dist`, `deploy_verify.sh`, tests.
- Test: a temp `dist/` with one sidecar carrying a different `buildId` →
  `check-dist` exits 1; mutation — drop the `buildId` comparison → exits 0 →
  red. Second: truncate one `.air.bin` by two bytes → red (size check).

### A6d — staged deploy swap

- Shape: server layout `/var/www/worldmap/releases/{buildId}/` and a symlink
  `/var/www/worldmap/current`; nginx `root /var/www/worldmap/current;` (a
  one-line change to `deploy/worldmap.atik.kr.conf:22`, installed by the owner
  in the same step as the pending E3 snippet — production change, owner
  confirms). `deploy_verify.sh`: `check-dist` locally → assemble the release
  outside `dist/` (`web/` minus README + the build-owned entries + water) →
  `rsync -a --link-dest=../{previous}` into `releases/{buildId}/` → live
  `check-dist --url` against `https://…/releases/{buildId}/` is not possible
  without exposing it, so instead verify file sizes over the ssh session →
  `ln -sfn releases/{buildId} current.tmp && mv -T current.tmp current` (atomic
  for new requests; in-flight range requests on the previous release keep
  working because its directory still exists) → live checks → keep the
  previous release; `deploy_verify.sh --rollback` re-points the symlink.
- Flags: the plan's alternative (1) — "stage to `/var/www/worldmap.new` and
  swap with a rename" — needs two renames (`worldmap` away, `.new` in) with a
  404 window and no rollback; (2) versioned dir + symlink is strictly better
  and also satisfies H12's exit criterion cheaply (vendor assets become
  release-addressed). `rsync --delete` into `current/` must not survive.
  Residual window: a client mid-session (ARCH-3) — closed only on the page.
- Blast radius: nginx conf (`root`), `deploy/README.md`, `deploy_verify.sh`,
  `browser_verify.sh` (unchanged).
- Test: run the script with `DEPLOY_HOST=` (local mode) against a temp
  "server" dir twice → `current` points at the second release, the first still
  exists, no file in `current/` differs from the assembled release; mutation —
  rsync into `current/` with `--delete` → the first release is gone → red.

### A7 — `solve` and `index`

- Shape: remove both subcommands. `build-all --only seoul,tokyo` writes into the
  staging directory through the same `_solve_one` with every gate and never
  publishes (prints the path); `build-all` publishes; `check-dist` answers "is
  this `dist/` consistent". If `index` must survive for "refresh attribution
  without a rebuild", it must rewrite `index.json` *from the sidecars* (origins
  = those whose sidecar `buildId` matches the existing `index.json`'s; refuse
  when none) — never from `origins.toml` alone.
- Flag: the plan's "make `solve` and `index` call the same `solve_and_emit`"
  keeps two entry points for one job; aligned today, they drift tomorrow (they
  already did once). `solve` with all gates is a slower `--limit 1` (it must
  load the 10 M-cell graph anyway). Delete rather than align.
- Blast radius: `cli.main`, `README.md:36`, `tests/test_cli.py` (add
  `--only`), F8's planned test becomes a `check-dist` test.
- Test: `check-dist` on a `dist/` whose `index.json` lists an origin with no
  files → `SystemExit`; mutation — remove the existence check → exit 0 → red.
  `build-all --only x` on the stub pipeline → `index.json` untouched and no
  file under `config.DIST` outside `.build-*`; mutation — publish anyway → red.

### J1 — contract document and `contractVersion`

- Shape: `docs/contract.md` with: file set and suffix table; `index.json`
  schema (required vs optional, by version); binary layouts (LE uint16/uint64,
  stride 6 for modes, ordering = sorted res-4 parents of the solver cells,
  sentinels 65535/0xFFFF/−1, clamp 65534); PMTiles layer/props/LODs; the
  rendering invariants the pipeline relies on (faster band painted on top;
  water above bands; `band < 0` beneath everything); node-offset arithmetic
  (`cells | airports dep | airports arr | stations`); the endianness assumption
  (`Uint16Array`/`BigUint64Array` are platform-endian; little-endian is
  assumed and is universal on shipping browsers — say so). Code:
  `config.CONTRACT_VERSION = 2` (call the currently served shape v1);
  `write_index` adds `contractVersion`, `modeChannels` (from `modes.CHANNELS`),
  `sentinels {unreachable, noAirport, noRail, unreachableBand}`, `files`
  (suffix table, one place — `cli.py:116-124` reads it too), `hoverCellCount`,
  `buildId`, `graph {rail, ferry}` (ARCH-12); `NodeIndex.offsets` property
  and `kind(node)` replace the six hand-derived sites; `app.js`: `const
  SUPPORTED = [2]; if (!SUPPORTED.includes(meta.contractVersion)) fatal(…)`,
  `names = meta.modeChannels`, sentinels and suffixes from `meta`, and the
  per-array length check against `hoverCellCount` (ARCH-3); `check-dist`
  derives widths from `modeChannels`; `deploy_verify.sh` greps `SUPPORTED`
  from `app.js` and compares to `index.json.contractVersion` before rsync.
- Flags: a `contractVersion` read with `??` is not a check — it must refuse
  visibly (`fatal()` exists); widths keyed by version number (a lookup table)
  would be a third copy — derive from `modeChannels`, which is data; do not
  drop the `??` fallbacks and the version check in the same deploy as the
  553 build unless A6d has landed, because `app.js` and `index.json` must
  change together (they do: `web/` is copied into the release).
- Blast radius: `config`, `emit/index`, `graph/nodes`, five emitters, `app.js`
  (~40 lines), `deploy_verify.sh`, `docs/`, tests.
- Tests: `tests/test_contract.py` — (1) `write_index` output has every key the
  doc's schema lists with the documented types (hand-written assertions; no
  jsonschema dependency); (2) `docs/contract.md` contains the literal
  `CHANNELS` tuple, the sentinel values and `CONTRACT_VERSION` — mutation:
  reorder `CHANNELS` → red; (3) `web/app.js` contains no literal
  `["rail", "ferry"` and no `0xFFFF` — mutation: reintroduce → red; (4)
  `NodeIndex.offsets` equals the tuple each emitter used to compute — mutation:
  change `+ len(self.airports)` in `airport_arr_index` → `test_routes_json`
  red.

### C5 — origin-switch generation counter

- Shape: one `loadOrigin(o)`; `const gen = ++originGen` at entry; the tile
  source switches immediately (visual feedback); each per-origin fetch is
  wrapped by a `take(promise, key, decode)` helper whose `.then` assigns into
  one `data` object **only if `gen === originGen`** and then calls
  `renderPins(); renderLegs()`; `.bin` failure sets `data.failed` under the
  same guard. `lookup()` reads `data.times`; `railVia` reads `data.rail`;
  the readout's "unavailable" branch reads `data.failed`. Reuse the idiom the
  file already has twice (`addressSeq` `:875-894`, `reverseSeq` `:920-928`)
  through one `latest()` helper so there is one pattern, not three. This
  collapses `hoverTimes, hoverFailed, hoverAir, hoverModes, routes, railDetail`
  (`app.js:139-144,741`) into one object — a step toward J3 without a split.
- Flag: the plan's "awaits all per-origin fetches" (a `Promise.all`) would
  hold the first readout until the ~2 MB `.json` lands — a regression from
  today, where times appear as soon as the 180 KB `.bin` does. Guard each
  fetch; do not join them.
- Blast radius: `paintOrigin`, `lookup`, `renderLegs`, `railVia`, the
  `mousemove` handler's `hoverFailed === active` test (`:715`), ~60 lines;
  prerequisite ARCH-4 (state block at the top).
- Test (browser, on the local preview before deploy; F5 is cycle 3): install
  a `fetch` wrapper that delays URLs matching `/seoul\.air\.bin$/` by 3 s;
  click Seoul then Tokyo within 500 ms; after 4 s assert
  `__diagnostics().origin === "tokyo"` and that the route panel for a clicked
  Siberian point names Tokyo's airports (or `__diagnostics().airSlug ===
  "tokyo"` if the loader records the slug it decoded). Mutation: remove the
  `gen !== originGen` guard → Seoul's `.air.bin` lands last → red.

### D13 — map before `hover_cells.bin` (reorder), lazy leg data

- Shape: keep `meta` first (everything needs it); start `const cellsPromise =
  loadCells(…)` without awaiting; create the map; `await` its `load`;
  `paintOrigin(FALLBACK)` (tiles visible); `hoverCells = await cellsPromise`
  (or `.then`) — `cellIndex` returns −1 while `hoverCells` is null, so
  `lookup()` yields `undefined` and the readout already says "Loading…".
  Lazy `.modes.bin`/`.json` (and `.air.bin` if wanted): fetched on the first
  `map.click` for the current origin, through the same `take()`/`gen` path as
  C5, so C5 must land first. `borders.json` as a URL source (H8's one-liner)
  fits the same commit.
- Flags: (1) ARCH-4 — hoist the state block before touching order, or
  `paintOrigin` throws in the TDZ; (2) do not insert a top-level `await`
  between the `places.json` fetch and `const map`; simplest is to move the
  `places` block below the map creation (where `borders` already is); (3)
  `paintOrigin` calls `moveTo` → `map.flyTo`, which needs the loaded map —
  keep the `load` await before it.
- Blast radius: `app.js:54-67,229-311,332-347,1094`; `cellIndex`/`lookup`.
- Test (local preview): `fetch` wrapper delaying `hover_cells.bin` by 5 s;
  assert `#map canvas` exists and `map.getSource("bands")` is set within 2 s
  and `#where` reads "Loading…" on hover; mutation — restore the serial
  `await` at `:67` → canvas appears after 5 s → red. Lazy half: with a wrapper
  that records URLs, load the page and switch origin twice without clicking →
  no `.modes.bin`/`.json` requested; click → requested once; mutation —
  restore eager fetch → red.

### H2 — hoist origin-independent work

- Shape: `emit/hover.HoverGrid` built once in the parent: `parents`
  (sorted list), `parent_of` (int32 per solver cell → parent position),
  `centre_pos` (int64 per parent → position of the SOLVE_RES centre child,
  else the FINE_RES centre child, else −1), `n = len(parents)`;
  `pick(cell_minutes) -> int64[n]`: `centre_pos` where ≥ 0, otherwise the
  fastest child by a vectorised group-min over `parent_of` (`np.lexsort` on
  `(minutes, parent_of)` then first-per-group). `write_hover`,
  `write_itinerary`, `write_modes`, `write_rail_detail` take `grid: HoverGrid`
  and use `grid.parents`/`grid.pick`; `write_hover_cells(grid)` too, so the
  five files provably share one ordering (F7). Also into the context:
  `reachable_in_principle` for `check_coverage` and the land-border minute for
  `check_monotonic_ground` (ARCH-6). Keep `_representative_children` in the
  test file only, as the oracle.
- Blast radius: four writer signatures, `cli._solve_one`, `emit/index`,
  `tests/emit/*` (fixtures pass a grid built from the fake index).
- Test: `HoverGrid(idx).pick(minutes)` equals the old dict-based oracle on the
  res-6/7 fixture from `tests/emit/test_hover.py` (centre child, water-centre
  fallback, split centre); mutation — set `centre_pos[:] = -1` → the
  centre-child case returns the fastest child → red. Ordering test: the five
  outputs' lengths equal `grid.n` and `write_hover_cells` writes
  `grid.parents`; mutation — sort parents differently in one writer → red.

### I4 — deploy hygiene

- Shape: `deploy/rsync-excludes.txt` (`.*`, `*-journal`, `tmp*`, `*.tmp`,
  `*.part`, `.build-*`, `.release-*`, `.build.lock`) used by both the local
  assembly and the server rsync; nginx `location ~ /\. { return 404; }` in the
  conf that goes to the owner with E3; `_atomic_write` keeps its umask
  semantics (the 0600 trap is already tested); `check-dist` **refuses** (does
  not merely exclude) when `dist/origins/` contains a `*-journal`, `.tmp` or
  `.part` — those are evidence of an aborted writer, and a deploy that hides
  them ships the partial file next to them. The `las-vegas.pmtiles-journal`
  deletion stays with the owner (the `dist/` rule).
- Test: temp `dist/` with a `x.pmtiles-journal` → `check-dist` exits 1;
  mutation — drop the check → 0 → red. For the excludes: a dry-run
  `rsync -n --exclude-from` listing must not contain any excluded name;
  mutation — empty the exclude file → red.

---

## 5. Regression check — did the cycle-1 fixes introduce coupling or ordering dependencies?

| Commit | Change | Coupling / ordering introduced | Verdict |
|---|---|---|---|
| `b030d38` (A3) | `GateFailure` instead of `SystemExit` in the worker | none; `cli.py:85-95,219-222` | ✔ |
| `599dc60` (A5) | `urban.py` owns its download | removes the `sources → emit` reverse edge; `PLACES_URL` in the stamp (`urban.py:76`) | ✔ |
| `be2cc94` (A8) | empty universe → 0.0 | none | ✔ |
| `b38fb8b` (A4) | `refine.ground_adjacent` shared by `build._ferry_edges` and `emit.modes` | `emit/modes.py:19` now imports `graph.refine` at **module** level (was function-level); same direction as before (J2), now visible in the header — acceptable | ✔ (note) |
| `cea16ca`, `4d74cbe` (E1 verify half, D14) | counts from the deployed `index.json` | `browser_verify.sh` now depends on the live `index.json` being fetchable and on 15 DOM selectors + `window.__map` — an unversioned page↔script contract with no test (ARCH-7); `SCHEMES=12` is still a literal | ⚠ |
| `c70c77a` (railDetail flag) | `index.json.railDetail` | page guards on it (`app.js:483`) ✔; `deploy_verify.sh:21-23` still treats `.rail.bin` as optional regardless of the flag; `write_index` sets it `True` even for a rail-less graph (ARCH-12) | ⚠ |
| `f943964`, `662f5d3`, `7cd7d63` (web) | `fatal()`/`fetchOk` for the root loads, `hoverFailed`, gesture-gated geolocation | `fatal()` is the hook J1 needs ✔; the `??` fallbacks for fields remain (ARCH-3); `MODE_FALLBACK` (`app.js:130-137`) is a third copy of the mode prose keyed by the same six names | ⚠ |
| `03988a5` (E3 repo half) | security snippet included per location; CSP names gtag + Nominatim | a new hand-synchronised pair: inline snippet ↔ sha256 in the conf (ARCH-9) | ⚠ |
| `e11c830` (E5/E7/E9/D20) | one description of the build; `llms.txt` says `index.json` describes what is served | good direction; nothing couples | ✔ |
| `662f5d3` (E2/F1c) | README rows for GeoNames/HydroLAKES | README is test-synced (`test_index.py:83-90`); the JS `PAGE_CREDITS` copy is not (ARCH-11) | ⚠ |
| `bf9e5cc` (`shared` dict) | `rail_tables` built in the parent; airport snapping | `shared.get("rail_tables")` is the only soft key (`cli.py:123`) — a rename produces a rail-less build silently, and `tests/test_cli.py::_stub_pipeline` (`:110-112`) cannot see it; workers are polars-free ✔ but the invariant is unenforced (ARCH-5); no ordering dependency between emitters beyond `write_pmtiles` preceding the size `stat` at `:126`; `rail_detail.py:17` still imports polars at module level (annotations only) | ⚠ |
| `6cc60d4`, `ceebfc2`, `3e393b5`, `498b971` (fixtures at `SOLVE_RES`) | tests built from `config.SOLVE_RES` | none; correct direction | ✔ |

Net: no fix introduced an import cycle, a reverse layer edge, or an ordering
dependency inside `_solve_one`; four introduced unversioned duplicated facts
(selectors, the CSP hash, `PAGE_CREDITS`, `MODE_FALLBACK`), and one (`shared`)
introduced a soft key the tests cannot see.

---

## 6. Final sweep

- **Hidden global state**: `cli.py:132,211` (`globals()["_CTX"]`), `roads.py:26,63-72`
  (`_grid_cache`), `countries.py:69-80,171-175` (`A3_TO_A2` filled by a side
  effect of `_polygons()`, read by `iso2()` which can trigger GDAL on first
  miss — safe only because `cli.py:173-175` warms it before forking), `app.js`
  (19 module-level `let`s, `window.__map` at `:350`). J8/J3 deferred; new
  evidence only for `app.js` ordering (ARCH-4) and `_CTX` (removed by ARCH-5's
  shape).
- **Import-time side effects**: `cli.py:9` (`POLARS_MAX_THREADS` — J8);
  `tests/web/test_ramps.py:5` (`sys.path` mutation — J6). No network or file
  I/O at import anywhere in `src/` (every module header checked); `scripts/*.py`
  act only under `__main__`.
- **Duplicated constants across Python / JS / shell** (each row is one fact):

  | Fact | Python | JS | Shell / conf |
  |---|---|---|---|
  | unreachable sentinel 65535 | `config.py:31` | `app.js:55` (`?? 65535`) | — |
  | clamp 65534 | `hover.py:23`, `modes.py:28` | — | — |
  | 0xFFFF none | `itinerary.py:18`, `rail_detail.py:21` | `app.js:145,742` | — |
  | unreachable band −1 | `bands.py:40` | `app.js:23` | — |
  | hover/solve resolutions | `config.py:13-20` | `app.js:56,63` (`?? 4`, `?? 6`) | — |
  | band count | `config.py:28` (36 edges) | `app.js:125` (`?? 10`, stale) | `browser_verify.sh:13` (derived ✔) |
  | mode channel order | `modes.py:24`, `index.py:109-116` (keys) | `app.js:610`, `app.js:130-137` (keys) | `deploy_verify.sh:18` (width 12) |
  | GRIP class → channel | `modes.py:27` | prose in `MODE_FALLBACK` | — |
  | node offsets | `nodes.py:74` (owner), `routes_json.py:52`, `itinerary.py:32-33,61`, `modes.py:45`, `rail_detail.py:29,90` | `app.js:571-573` | — |
  | file suffixes / `origins/` | `cli.py:116-124,273-279` | `app.js:463-512` | `deploy_verify.sh:18,26,58-61` |
  | tile layer names | `tiles.py:20`, `water.py:32` | `app.js:372,465` | — |
  | colour-scheme count | — | `app.js:74-85` (owner) | `browser_verify.sh:16` (`12`) |
  | site URL | — | `index.html:16,24,43`, `sitemap.xml`, `robots.txt` | `deploy_verify.sh:59-62`, `browser_verify.sh:6` |
  | server root | — | — | `worldmap.atik.kr.conf:22`, `deploy_verify.sh:55` |
  | gtag id + inline hash | — | `index.html:5-11` | `worldmap-security-headers.conf:18` |
  | slug grammar | `cli.py:34`, `scripts/expand_origins.py:51-54` | — | — |
  | `zone` derivation (two lines) | `cli.py:174-175`, `build.py:226-227`, `ground.py:87-88` | — | — |
  | Geofabrik region list | — | — | `osm_rail.sh:24` |
  | rail/ferry calibration figures in prose | `index.py:110-112` | `MODE_FALLBACK` | — |

- **Environment-specific paths**: `deploy_verify.sh:6` (`cd /Users/hletrd/…`),
  `:55` (`atik.kr:/var/www/worldmap/`), `browser_verify.sh:18,74,86` (`/tmp`),
  `:89` (name-grep kill); `scripts/adsb_extract.py:133` (`~/adsb-cache`),
  `calibrate/ground.py:62` (`~/.config/transport-maps/env`, documented);
  `calibrate_ground.py:38,49` (`data/build/…` relative to cwd; reads
  `dist/places.json` — the shipped gazetteer is a calibration input, and
  `places.json` has no producing stage, E6). J5 is scheduled; ARCH-7/15 add
  the multi-agent kill and the five URL copies.
- **Configuration read from more than one place**: `calibration.toml` by four
  loaders (`air.py:29-45`, `rail.py:44-54`, `ground.py:28-34`) and re-parsed
  per origin (ARCH-8); `data/origins.toml` read by `index.load_origins` and
  appended by `expand_origins.py` (fine); site URL/host/root as above;
  `POLARS_MAX_THREADS` only in `cli.py`.
- **Implicit ordering between stages**: `build_water_tiles.py` before deploy
  (documented); `places/airports/borders` have no stage (E6); `deploy_verify.sh`
  copies `web/` into `dist/` before rsync (documented in `deploy/README.md:9-11`
  now, but still a second writer of `dist/`, ARCH-7); `calibrate_ground.py`
  reads `dist/places.json`; `index` after `build-all --limit` is unsafe (A7).
- **Two builds, one directory**: no lock (ARCH-1). The eight pre-A3 orphans
  are idle and cost nothing but prove that nothing detects a stale run.
- **Contract fallbacks that mask breakage**: `app.js:55-64,125` (ARCH-3);
  `deploy_verify.sh:21-23` (`.rail.bin` optional regardless of the flag).
- **Spec statement now false**: the design spec's "the frontend never learns
  how the numbers were made; the pipeline never learns how they are drawn"
  (`spec:62-63`) — `modeDetail` prose crosses one way and the overlap-by-rim
  design (`bands.py:5-20`) depends on `fill-sort-key` (`app.js:470`) the other
  way. Both are legitimate; both belong in J1's document as named invariants.
  E10 (spec "superseded in part") is scheduled.
- **Nothing skipped**: every file in the inventory was read in full except
  `web/vendor/*` (generated) and the pipeline plan (headings + targeted grep,
  as stated). `.superpowers/` ledgers, `tests/graph/*` and
  `tests/sources/test_{osm,countries,urban,routes,wikidata}.py` were not part
  of this angle and were not read.
