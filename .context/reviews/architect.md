# Architect review — transport-maps

Reviewer angle: architecture and design risk (layering, contracts, orchestration, calibration, extensibility, testability, documentation). Read-only; nothing under `dist/` or `data/` was written. Every claim below was checked against the code, not against comments or tests. Where a claim rests on running something, the exact probe is named.

Date: 2026-09-10. Tree reviewed: HEAD `ac191db` (`feat/transport-pipeline`), working tree clean.

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 1 | ARCH-1 |
| High | 7 | ARCH-2, ARCH-3, ARCH-4, ARCH-5, ARCH-6, ARCH-7, ARCH-8 |
| Medium | 10 | ARCH-9 … ARCH-18 |
| Low | 5 | ARCH-19 … ARCH-23 |

Bounded (fits this cycle): ARCH-1, 2, 3, 4, 5, 6 (partial), 7 (partial), 8 (partial), 10, 11, 12, 13 (partial), 14, 17 (copy only), 18, 19, 20.
Not for this cycle (recorded as risk): ARCH-6 (full split), ARCH-7 (resume), ARCH-9, ARCH-10 (module split), ARCH-15, ARCH-16 (precise fix), ARCH-17 (model), ARCH-21, ARCH-22, ARCH-23.

The single most important fact: **`nodes.build_index()` cannot run at HEAD** (ARCH-1). Every entry point that touches the graph — `build-all`, `solve`, `index`, `scripts/calibrate_ground.py`, `scripts/ground_check.py`, and roughly a dozen tests — fails with `NameError: name 'np' is not defined`. The `build-all` currently running (pid 12633, log `/private/tmp/rebuild10.log`) was started before that commit and is running older code, so it proves nothing about HEAD.

---

## Dependency and contract map

### Import graph (module level, from `grep` of every `src/` file)

```
config  <-- everything
sources/_utils  <-- sources/*, contour/grid, emit/{airports_json,borders,places}
sources/airports <-- graph/nodes, graph/build, sources/routes, emit/airports_json
sources/landmask <-- graph/nodes
sources/roads    <-- graph/nodes (fn), graph/ground, emit/modes (fn), cli (unused)
sources/urban    <-- graph/nodes (fn), graph/ground, emit/index (fn)
sources/urban    --> emit/places (fn)            <-- REVERSED LAYER (ARCH-2)
sources/countries<-- graph/ground, graph/build (fn), validate (fn), cli
sources/osm      <-- graph/build, cli
sources/routes   <-- graph/build
graph/nodes      <-- graph/{build,ground}, solve/dijkstra, cli
graph/air        <-- graph/{build,transfers}
graph/rail       <-- graph/build, graph/nodes (fn), emit/rail_detail (fn)
graph/refine     <-- graph/{nodes,ground}, emit/modes (fn)
graph/ground     <-- graph/build, validate (fn), emit/index (fn), cli
contour/bands    <-- cli, validate (fn)
contour/grid     <-- contour/bands (fn), cli
emit/hover       <-- emit/{index,itinerary,modes,rail_detail}
emit/*           <-- cli
validate         <-- cli
calibrate/*      <-- scripts only (never the package)
```

"(fn)" = function-level import. Every cross-layer dependency is hidden inside a function body, so ruff's import sorter and a reader of the header both miss them. There is no import cycle at module load, but `emit` → `graph`/`sources` (five modules) and `sources` → `emit` (one) both exist.

### Pipeline → page contract (as actually implemented)

| Artefact | Producer | Consumer | Layout / schema | Where documented |
|---|---|---|---|---|
| `index.json` | `emit/index.py:120-137` | `web/app.js:27-35,98,145,509,709` ; `scripts/deploy_verify.sh:13-31` ; `scripts/browser_verify.sh` | `bandEdgesMin[]`, `unreachable`, `hoverRes`, `solveRes`, `fineRes`, `modeDetail{}`, `hoverCellsUrl`, `attribution[]`, `origins[]{slug,name,lat,lon}` | nowhere as a schema; no version field |
| `hover_cells.bin` | `emit/index.py:91-99` | `app.js:38-40,453-462` | sorted LE uint64 H3 ids | docstring only |
| `origins/{slug}.pmtiles` | `emit/tiles.py`, geometry `contour/bands.py` | `app.js:379-392,578-595` | layer `bands`, props `band:int` (−1 unreachable), `max_minutes`; per-feature `tippecanoe.minzoom/maxzoom` | `tiles.py:20`, `bands.py:170-188` |
| `origins/{slug}.bin` | `emit/hover.py` | `app.js:402-411,464-468` | LE uint16 minutes per hover cell; 65535 sentinel; clamp 65534 | docstring |
| `origins/{slug}.air.bin` | `emit/itinerary.py` | `app.js:420-423,473-489` | LE uint16 arrival-airport ordinal; 0xFFFF none | docstring; `NO_AIRPORT` duplicated `app.js:106` |
| `origins/{slug}.modes.bin` | `emit/modes.py` | `app.js:416-419,516-526` ; `deploy_verify.sh:18` (width 12) | 6 × LE uint16 per hover cell, channel order `CHANNELS` | `modes.py:23`; order re-typed in `app.js:520` |
| `origins/{slug}.rail.bin` / `.rail.json` | `emit/rail_detail.py` | `app.js:396-401,646-653` | uint16 index into `stations[[station,line]]`; 0xFFFF none | docstring; `NO_RAIL` duplicated `app.js:645` |
| `origins/{slug}.json` | `emit/routes_json.py` | `app.js:424-431,480-489` | `offsets{cells,airports,stations}`, `nodes[]{id,kind:dep|arr,code,min,prev}` | docstring; node arithmetic re-derived `app.js:481` |
| `places.json`, `airports.json`, `borders.json` | `emit/places.py`, `emit/airports_json.py`, `emit/borders.py` | `app.js:151,724,319` ; required by `deploy_verify.sh:29` | columnar JSON | **no CLI stage calls them** (ARCH-5) |
| `water.pmtiles` | `emit/water.py` via `scripts/build_water_tiles.py` | `app.js:291-293` | layer `water` | README |
| `data/origins.toml` | hand + `scripts/expand_origins.py` | `emit/index.load_origins` | `[[origin]] slug,name,lat,lon` | plan Task 13 |

Two sides, no shared definition: the constants that make this contract (resolutions, sentinels, channel order, band count, file suffixes) live in `config.py`, `emit/*.py`, `cli.py:95-103`, `app.js`, and two shell scripts, each re-typing them (ARCH-3).

### Spec/plan → shipped drift (headline)

| Item | Spec / plan | Shipped |
|---|---|---|
| Solver grid | res 5, 548,557 cells (`spec:125`, `plan:17-18`) | res 6 base + res 7 where dense, ~10 M cells (`config.py:12-15`, `refine.py`) |
| Bands | 10 edges / 11 bands (`spec:248-253`, `plan:21`) | 36 edges / 37 bands (`config.py:24`, `dist/index.json`) |
| Frontend | Vite + React 19 + TS (`spec:257`) | one vanilla ES module, 999 lines (`web/app.js`) |
| Basemap | Protomaps `basemap.pmtiles` (`spec:243`) | `water.pmtiles` + `borders.json` + DOM labels |
| Hosting | S3 + CloudFront (`spec:47`) | nginx on `atik.kr` (`deploy/`) |
| Calibration source | FR24 / FlightAware (`spec:73,98`) | adsb.lol (D15) + Google Routes DRIVE for ground |
| Rail | 250 / 80 km/h, headway wait (`spec:164-171`) | 200 / 75 km/h, **no wait** (`calibration.toml:110-111`, `build.py:232-276`) |
| Band validation | `check_bands_disjoint` (`plan` Task 15) | bands overlap by design; `check_bands_cover` |
| Per-origin file key | `origins/{iata}` (`spec:68-70`) | `origins/{slug}` |
| `dist/index.json` (live) | — | `solveRes: 5`, 157 origins, no `modeDetail`/`fineRes` — an older build than the code |

---

## Findings

### ARCH-1 — `graph/nodes.py` uses `np` without importing numpy; `build_index()` raises `NameError` at HEAD

- Severity: **Critical** · Confidence: High · Status: **Confirmed**
- Where: `src/transport_maps/graph/nodes.py:21-27` (imports: `logging`, `dataclasses`, `h3`, `config`, `airports`, `landmask` — no `numpy`), used at `:61`, `:62`, `:124`. Introduced by `1a4d66b` (blame).
- Why it is a problem: `build_index()` is the root of every graph-touching entry point (`cli.py:139,236,255`, `scripts/calibrate_ground.py:53`, `scripts/ground_check.py:38`, tests in `tests/graph/test_{nodes,build,ground}.py`, `tests/test_golden.py`, `tests/contour/test_bands.py:119`, `tests/sources/test_roads.py:16`). Python 3.14's deferred annotations let the module *import* cleanly, which is why nothing noticed; the failure is at first call.
- Evidence: probe `scratchpad/np_probe.py` (all I/O stubbed, nothing written) →
  `build_index` → `NameError: name 'np' is not defined`; `NodeIndex([], [], {}, {}, {})` → same, from the `default_factory` lambdas. `uv run ruff check src/` reports six `F821 Undefined name np` at `nodes.py:61,62,124` — the project's own `select = ["F", …]` (`pyproject.toml:60`) would have caught it, so lint is not run before commit.
- Failure scenario: the next `transport-maps build-all` on HEAD dies after loading rail/ferry parquet, before any origin. The running build (pid 12633) predates this commit and will finish, leaving a `dist/` that matches neither HEAD nor the spec.
- Fix: add `import numpy as np` to `nodes.py`; add `uv run ruff check src tests scripts` as a pre-commit / CI gate (a one-line `.pre-commit-config.yaml` or a Makefile `check` target). Then run `tests/graph/test_nodes.py`.
- Tag: **Bounded (fits this cycle)** — prerequisite for everything else.

### ARCH-2 — `sources/urban.py` depends on `emit/places.py` (reversed layer) and the call is broken; the urban mask only builds because of a stale cache file

- Severity: High · Confidence: High · Status: Confirmed (by reading; masked in this checkout by `data/cache/ne_10m_populated_places_simple.zip`)
- Where: `src/transport_maps/sources/urban.py:36-41` — `if not path.exists(): from ..emit import places as places_mod; places_mod._download()`. `emit/places.py:35` is `def _download(url: str)` (required positional) and downloads GeoNames files, never the Natural Earth `ne_10m_populated_places_simple.zip` that `urban._places()` reads at `:41`.
- Why: a `sources` module importing an `emit` module inverts the spec's layering (`spec:79-86`); and the call would raise `TypeError` on a fresh clone. Nothing in the repo produces `PLACES_ZIP` any more (the docstring at `places.py:10-11` says Natural Earth was "used before").
- Failure scenario: new machine or cleared `data/cache/` → `urban.urban_mask()` → `TypeError: _download() missing 1 required positional argument`; `build_index()` (which now calls `urban_mask` at `nodes.py:119`) cannot run; every fitted ground speed depends on this mask (`ground.py:60-70`).
- Fix: give `urban.py` its own `_download()` for the Natural Earth URL (same pattern as `landmask._download`), delete the import of `emit.places`. Add the URL to the `_params_hash` stamp at `urban.py:51`.
- Tag: **Bounded**.

### ARCH-3 — The pipeline↔page contract is undocumented, unversioned, and re-typed in at least six places

- Severity: High · Confidence: High · Status: Confirmed
- Where (duplicates of the same facts):
  - sentinels: `config.py:27` (65535) ↔ `app.js:28` (`?? 65535`); `itinerary.py:18` and `rail_detail.py:20` (0xFFFF) ↔ `app.js:106,645`; `bands.py:40` (−1) ↔ `app.js:21`; `hover.py:22` and `modes.py:27` (65534, two copies).
  - resolutions: `config.py:12-17` ↔ `app.js:29,34` (`?? 4`, `?? 5` — the fallback is the *old* solve resolution).
  - band count: `config.py:24` ↔ `app.js:98` (`?? 10`) ↔ `browser_verify.sh:18` (`"tints":37`).
  - mode channels: `modes.py:23` (`CHANNELS`) ↔ `app.js:520` (`names = [...]`) ↔ `deploy_verify.sh:18` (width 12 = 6 × 2) ↔ `index.py:102-117` (`modeDetail` keys).
  - node-id arithmetic (stations start at `n_cells + 2*n_airports`): `nodes.py:170`, `routes_json.py:49`, `itinerary.py:32-33`, `modes.py:53-54`, `rail_detail.py:28,69`, `validate.py:180`, `app.js:481`.
  - file suffixes: `cli.py:95-103` ↔ `app.js:379,397-398,402,416,420,424` ↔ `deploy_verify.sh:18,26`.
- Why: none of these is validated on both sides. `index.json` carries no `contractVersion`; the page silently falls back to wrong defaults (`solveRes ?? 5`) when a field is missing, which is exactly the shape of the "blank globe with no console error" incident recorded in `CLAUDE.md` and `deploy/README.md:16-20`. Adding a seventh mode channel would corrupt the route panel on every origin without any gate firing (`deploy_verify.sh` would even pass if the width constant were updated by hand).
- Failure scenario: someone reorders `CHANNELS` to put ferry before rail; `.modes.bin` changes; `app.js:520` still labels column 0 "rail"; deploy verification passes (lengths agree); users read ferry minutes as rail.
- Fix (bounded): (1) in `emit/index.write_index` add `"contractVersion": 1`, `"modeChannels": list(modes.CHANNELS)`, `"sentinels": {"unreachable": …, "noAirport": …, "noRail": …, "unreachableBand": -1}`, and `"files": {"bands": "origins/{slug}.pmtiles", …}`; (2) in `app.js` replace the `??` fallbacks with a hard check (`if (meta.contractVersion !== 1) throw …` and render a visible message), read `modeChannels` instead of the literal list; (3) in `deploy_verify.sh` derive the `.modes.bin` width from `len(idx["modeChannels"]) * 2` and the band count from `bandEdgesMin`. (4) Write the table above into `docs/CONTRACT.md` (or a "Shipped artefact" section of `README.md`) and link it from `web/README.md`. This is the "single place a new contributor learns the contract" that does not exist today.
- Tag: **Bounded** — directly enables adding detail to the route panel safely.

### ARCH-4 — `scripts/browser_verify.sh` hard-codes 157 cities, 37 swatches and 12 schemes; `origins.toml` has 553

- Severity: High · Confidence: High · Status: Confirmed
- Where: `scripts/browser_verify.sh:18-19,41`; `data/origins.toml` has 553 `[[origin]]` blocks (commit `29cd959`); `dist/index.json` (live) still has 157.
- Why: the post-deploy gate that CLAUDE.md makes mandatory will fail the moment the 553-origin build is deployed, and the obvious "fix" is to edit the literal — a gate that must be edited on every content change stops being a gate. The same literals leak into copy: `web/index.html:15,23,31,41-42,375,421` say "553 cities" while the served `index.json` lists 157, so the live page currently overstates its own content by 3.5×.
- Failure scenario: next deploy → `browser_verify.sh` exits 1 on `"cities":157`; or the number is bumped and a build that accidentally shipped 156 origins passes.
- Fix: in `browser_verify.sh`, fetch `index.json` first and compare `.results button` count to `origins.length`, `.tints span` to `bandEdgesMin.length + 1`, `#ramps button` to the count parsed from `app.js` (or ≥ 6). In `index.html`, keep the static number out of the meta description or generate it; in-page copy (`:375`, `:421`) should be filled from `meta.origins.length` by `app.js`.
- Tag: **Bounded** — user-visible correctness of the page's own claims.

### ARCH-5 — Three shipped artefacts (`places.json`, `airports.json`, `borders.json`) have no producing stage; `build-all` does not produce a complete `dist/`

- Severity: High · Confidence: High · Status: Confirmed
- Where: `emit/places.build`, `emit/airports_json.build`, `emit/borders.build` have **zero callers** in `src/`, `scripts/`, `tests/`, or any README (grep over the repo). `deploy_verify.sh:29-30` refuses to deploy without them. `README.md:30-35` lists only `build-all` and `build_water_tiles.py`.
- Why: the artefacts exist in `dist/` only because someone ran `python -c` by hand. A fresh clone following the README cannot produce a deployable `dist/`; `airports.json` in particular must agree with the airport table the graph was built from (it is what the search box and the route tooltips read, `app.js:504-507,724-727`), and nothing ties the two builds together.
- Failure scenario: OurAirports refresh → `airports_{stamp}.parquet` rebuilt (ARCH-15 notwithstanding) → graph uses new codes → `airports.json` left stale → route panel shows bare codes with no tooltip for new airports; no gate notices because the file "exists".
- Fix: add a `transport-maps assets` subcommand (or fold into `build-all` before the origin loop) that calls the three builders and `write_hover_cells`; document it in README; have `deploy_verify.sh` check `airports.json` row count against `index.json` (add `"airportCount"` to `index.json`).
- Tag: **Bounded**.

### ARCH-6 — `cli.py` holds the per-origin business pipeline and file naming; `solve`, `index` and `build-all` have diverged

- Severity: High · Confidence: High · Status: Confirmed
- Where: `cli.py:77-106` (`_solve_one`: gates + 7 emitters + naming); `cli.py:233-251` (`solve`: writes `dist/{name}.pmtiles`, `dist/{name}.hover.bin`, `dist/{name}.routes.json` — a *different* layout and suffix set, skips `check_coverage`/`check_monotonic_ground`/`check_bands_cover`, omits `.air.bin`, `.modes.bin`, `.rail.*`, and passes no `grid`/`native` so `band_feature_collection` recomputes the render grid); `cli.py:253-263` (`index`: writes `index.json` from *all* origins in `origins.toml` with no check that per-origin files exist — the exact "advertise origins that were never built" failure `_build_all` guards against at `:193-200`).
- Why: the page cannot consume `solve` output; a maintainer testing one origin gets no gates; `index` is a footgun that re-creates the partial-`dist/` incident.
- Failure scenario: after a `--limit 3` smoke build, someone runs `transport-maps index` to "refresh attribution" → `index.json` lists 553 origins, 550 of which 404 → blank globe for every city but three.
- Fix (bounded): move `_solve_one` and the suffix table into `src/transport_maps/pipeline.py` (or `emit/origin.py`) exposing `ORIGIN_FILES = {"bands": "{slug}.pmtiles", …}` and `solve_and_emit(origin, ctx)`; have `solve` call it with the same gates and layout (`dist/origins/`); make `index` refuse when any origin lacks its files unless `--force`. Full split of orchestration (worker pool, shared context) into a `build.py` module: **Not for this cycle**.
- Tag: **Bounded (partial)**.

### ARCH-7 — Build orchestration: no per-origin atomicity, no build identity, no resumability, no progress until the first origin completes

- Severity: High · Confidence: High · Status: Confirmed (design) / Needs manual validation (timing)
- Where: `cli.py:95-103` writes seven files per origin sequentially with plain `write_bytes`/`write_text` (`hover.py:71-72`, `itinerary.py:70-71`, `modes.py:109-110`, `rail_detail.py:90-93`, `routes_json.py:53-54`); only `tiles.py:70` moves atomically. `cli.py:174` writes `hover_cells.bin` first and `:200` `index.json` last, but neither carries a build id; `deploy_verify.sh:12-25` checks only lengths. `cli.py:190` uses `pool.imap` (ordered) so no line prints until origin 1 finishes — the running build's log (`/private/tmp/rebuild10.log`) shows the table header and nothing else after 5 h 29 m. A crash at origin 400 of 553 leaves 400 fresh origins next to a stale `index.json` and requires a full re-run.
- Why: CLAUDE.md's "never deploy a partial dist" rule is enforced by humans and by file *lengths*, not by the artefacts themselves. A kill during `write_modes` leaves a truncated `.modes.bin` that `deploy_verify.sh` catches only if the length happens to differ; a kill between `.bin` and `.air.bin` leaves an old `.air.bin` (same length, previous build) beside a new `.bin` — passes verification, mislabels routes.
- Failure scenario: as above; also two builds started by different agents against the same `dist/` (there are two agents in this session) interleave writes.
- Fix (bounded): (1) generate `build_id = _params_hash(graph inputs, git sha, time)` once in `_build_all`; write it into `index.json` and into a sidecar `dist/origins/{slug}.meta.json` per origin; have `deploy_verify.sh` require every sidecar's id to equal `index.json`'s. (2) Emit each origin into `dist/origins/.tmp-{slug}/` and `os.rename` the directory's files into place at the end of `_solve_one`. (3) `imap_unordered` with `flush=True` and a running count. Resumability (`--resume` skipping origins whose sidecar matches the current `build_id` inputs): **Not for this cycle**, but the sidecar makes it a ten-line change later.
- Tag: **Bounded (partial)**.

### ARCH-8 — Calibration is split across three loaders, and the two most consequential fitted constants are not in `calibration.toml`

- Severity: High · Confidence: High · Status: Confirmed
- Where: loaders — `graph/air.py:29-45` (`Calibration`), `graph/rail.py:44-54` (`RailCalibration`, `FerryCalibration`), `graph/ground.py:28-34` (`_land_border_min` re-parses the TOML with its own `tomllib` call; invoked per `hex_edges`, per `_border_rules`, and per `check_monotonic_ground`). `air.load_calibration()` is called three times per graph build (`build.py:61,137,175`) and `airports.scheduled_airports()`/`routes.route_network()` re-read parquet three/two times (`build.py:62,76,138,176,184`). Fitted-but-not-in-TOML: `SPEED_BY_ROAD_CLASS_KMH` (`ground.py:25`, "FITTED against 2,998 journeys"), `URBAN_POP_MIN/RADIUS_KM/CONGESTION_FACTOR` (`urban.py:27-29`, "Fitted jointly"). Prose that hard-codes numbers: `emit/index.py:110-112` (`"200 km/h, conventional at 75 km/h"`, `"35 km/h plus 30 min"`) while the same values are read from `[rail]`/`[ferry]` elsewhere. Provenance comments that are no longer true: `calibration.toml:42-43` ("Coefficients are refitted in Task 13 against observed frequencies") and `:95` ("refitted in Task 12 from observed connections") — neither refit happened; `[meta]` describes only the airborne fit.
- Why: CLAUDE.md requires every calibration constant to live in `calibration.toml` with a fitted/default label; the ground-speed table is the single largest determinant of the surface and lives in code. `mode_detail()` is what the page shows in tooltips (`app.js:508-511`), so the moment `[rail].highspeed_kmh` changes, the UI lies.
- Failure scenario: refit rail to 230 km/h → tooltip still says 200; refit ground speeds → `calibration.toml` unchanged, `scripts/ground_check.py` and `calibrate_ground.py` keep reading `gmodel.SPEED_BY_ROAD_CLASS_KMH`, and `test_licence_firewall::test_calibration_contains_only_numbers` never sees them.
- Fix (bounded): add `[ground]` (`speed_kmh = [5,104,57,50,18,25]` — note `assert_scalar` at `tests/test_licence_firewall.py:65` forbids lists; use six keyed scalars `roadless/highway/primary/secondary/tertiary/local`) and `[urban]` to `calibration.toml` with the fitted/default comments; one `calibrate.load()` returning a single frozen object with `.air`, `.rail`, `.ferry`, `.ground`, `.urban`, `.land_border`; `mode_detail(cal)` formats from it; correct the two stale provenance comments. Consolidating the three call sites in `build.py` to one `cal` argument is part of the same change. Refitting anything: not in scope.
- Tag: **Bounded (partial)** — tooltips are user-visible.

### ARCH-9 — `emit` reaches back into `graph` and `sources`; three "emitters" are really sources

- Severity: Medium · Confidence: High · Status: Confirmed
- Where: `emit/index.py:104-105` → `graph.ground`, `sources.urban`; `emit/modes.py:35,57` → `graph.refine`, `sources.roads`; `emit/rail_detail.py:45,72` → `graph.rail.station_key`; `emit/airports_json.py:10` → `sources.airports`; `emit/{borders,places,water}.py` perform HTTP downloads and cache under `config.CACHE` (`borders.py:25-29`, `places.py:35-41`, `water.py:49-59`); `contour/grid.py:24` → `sources._utils`.
- Why: the spec's layering (`sources` fetch, `emit` write) is not held; forked workers import polars through `rail_detail` (`:17`) although `cli.py:149-151` promises no child touches polars; `_atomic_write` is a generic I/O helper filed under `sources/_utils` (private name, imported by four packages).
- Failure scenario: a future `write_rail_detail` change that calls a polars expression in the worker hits the fork/rayon deadlock documented at `cli.py:5-9`; nothing in the structure prevents it.
- Fix: move `_atomic_write`, `_params_hash` to `transport_maps/_io.py` (public names); have `mode_detail` take the calibration object (ARCH-8); pass `station_key`/`cell_class` in `shared` from the parent as `cell_class` already is. Moving `borders/places/water` to `sources/` with thin emitters: **Not for this cycle**.
- Tag: Not for this cycle (except the `_io.py` move, which is mechanical).

### ARCH-10 — `web/app.js`: 999 lines, 17 module-level mutable globals, and an origin-switch race that can mix two origins' data

- Severity: Medium (user-visible) · Confidence: High · Status: Confirmed (race by reading; reproduction needs a slow network)
- Where: globals at `app.js:61,99,101-105,118-119,150,333,609,642,644,723,777,825`; `window.__map` at `:270`; `paintOrigin` at `:374-438` issues six independent fetches (`:396-431`); only the rail pair checks `active === o` (`:400`); `.bin`, `.modes.bin`, `.air.bin`, `.json` assign unconditionally on resolve. `renderLegs` (`:491-571`) combines `hoverTimes`, `hoverAir`, `routes`, `hoverModes`, `railDetail` whichever origin each came from. Stale comments describing the old contract: `:30-34` ("res-5 … min of seven children"), `:573-577`, `:719-722` ("157 cities").
- Why: click Seoul then Tokyo quickly on a slow link → Tokyo's `.bin` arrives, Seoul's `.air.bin` arrives later and overwrites → route panel walks Seoul's airport chain against Tokyo's times. For the user's stated focus (route detail, UI polish) every new per-origin file added to the panel widens this window. Adding a feature today means adding another `let`, another fetch, another unguarded assignment.
- Fix (bounded): one `loadOrigin(o)` with a generation counter: `const gen = ++originGen; const [bin, air, modes, routes, rail] = await Promise.all(...); if (gen !== originGen) return; state.origin = {o, bin, air, ...}; render();` — replaces five globals with one object and removes the race. Also delete or correct the three stale comments. Splitting the file into `state/data/legend/route/search` modules: **Not for this cycle**.
- Tag: **Bounded (partial)**.

### ARCH-11 — Documentation architecture: five documents disagree with each other and with the code; no "as built" reference exists

- Severity: Medium · Confidence: High · Status: Confirmed
- Where: `web/README.md:39-45` ("Eleven sequential steps of a single blue hue") vs `app.js:41-59` (12 multi-hue schemes); `web/llms.txt:13,22,31` ("11 bands", "548,557 H3 resolution-5 land cells", "Rail and ferry are not yet in the graph") vs `:53-59` (res 6/7, rail legs) in the same file; `web/index.html` "553 cities" ×6 vs live `index.json` 157; `README.md:11` badge "H3 res 6/7" vs spec `:125`; spec/plan drift table above; `emit/tiles.py:9-18` and `emit/hover.py:7` still describe res-5; `deploy/README.md:6` rsyncs `dist/` but `deploy_verify.sh:40` copies `web/` into `dist/` first (the README omits that step).
- Why: a new contributor (or the next agent) has no single truthful description of what is built; the design spec is marked "Approved, pre-implementation" and was never amended, so its decision log now records decisions that were reversed (D9, D10, D13 — Antarctica is now included, `landmask.py:147-166`).
- Fix (bounded): add an "As built — 2026-09" section at the top of the spec listing the reversed decisions (D9, D10, D13, grid, bands, frontend stack, rail speeds/no-wait); rewrite `web/README.md` "Colour ramp" and `llms.txt` "What the numbers mean / How it is computed"; derive the city count on the page from `index.json` (ARCH-4). `docs/CONTRACT.md` per ARCH-3.
- Tag: **Bounded**.

### ARCH-12 — The repo's CSP forbids what the page does (Google tag, Nominatim); either production is misconfigured or the repo's conf is not what is deployed

- Severity: Medium (a user-facing feature silently fails) · Confidence: Medium · Status: **Needs manual validation** (check the live response headers)
- Where: `deploy/worldmap.atik.kr.conf:26` — `script-src 'self' blob:` and `connect-src 'self'`; `web/index.html:4-11` loads `https://www.googletagmanager.com/gtag/js`; `app.js:776-842` fetches `https://nominatim.openstreetmap.org/...`; `web/README.md:8-10` and the conf's own header comment (`:2`) still say "no runtime API calls". `browser_verify.sh:42-46` asserts address search returns ≥ 1 result on the live site.
- Why: if the conf in the repo is deployed, address search and click-to-address fail silently (blocked fetch → `catch {}` → nothing), analytics never loads, and the verification script fails. If it passes today, the deployed nginx conf differs from the committed one — configuration drift the repo cannot see.
- Fix: decide, then make the repo truthful: add `connect-src 'self' https://nominatim.openstreetmap.org` (and the gtag hosts, or drop the tag) to the conf; update `web/README.md:8-10` and the conf comment; add a `curl -sI https://worldmap.atik.kr/ | grep -i content-security-policy` line to `deploy_verify.sh` that diffs against the committed value.
- Tag: **Bounded**.

### ARCH-13 — Testability: no injection seams, a suite that builds the full 10 M-cell graph in a dozen places, and fixtures pinned to res-5 literals after the move to res 6

- Severity: Medium · Confidence: High · Status: Confirmed (literals) / Likely (which tests now fail, given ARCH-1 blocks running them)
- Where: `build.py:61-62,76,137-138,175-176,184` load calibration/airports/routes internally (tests must monkeypatch module attributes: `tests/graph/test_build.py:52-55`, `tests/test_cli.py:38-104`). `cli.py:22` imports `roads` *only* so `tests/test_cli.py:61` can monkeypatch `cli.roads.cell_class` (ruff F401). Full-graph fixtures: `tests/graph/test_{nodes,build,ground}.py`, `tests/test_golden.py`, `tests/contour/test_bands.py:117-135`, `tests/sources/test_roads.py:14-16`, `tests/sources/test_countries.py:93-95` — each `build_index()` now classifies ~2.8 M base cells and writes caches under `data/`; the only marker is `network`, so `uv run pytest` runs all of them. Res-5 literals that no longer name a solver cell: `tests/graph/test_build.py:63`, `tests/graph/test_ground.py:27-28`, `tests/test_validate.py:16,31,153,200`, `tests/emit/test_hover.py:11` (res-5 ids; `_representative_children` now falls through both `SOLVE_RES` and `FINE_RES` lookups to the "fastest child" fallback, so `test_parent_cell_takes_the_minimum_of_its_children` passes for the wrong reason — the shipped rule is "centre child"), `tests/contour/test_bands.py:33,51,65,78,144,175,213-214`, `tests/graph/test_transfers.py:90-92` (pins constants that are dead code, ARCH-19). `tests/test_config.py:21` asserts `HOVER_RES < SOLVE_RES` but nothing asserts `SOLVE_RES < FINE_RES`.
- Why: CLAUDE.md's "assume a new test is vacuous until shown otherwise" — several existing ones became vacuous or wrong at `1a4d66b` and nobody could tell because the suite could not run.
- Fix (bounded): `slow` marker on every full-graph fixture with `addopts = "-m 'not network and not slow'"`; replace literal `5` with `config.SOLVE_RES` and res-5 ids with `h3.latlng_to_cell(..., config.SOLVE_RES)`; rewrite `test_hover.py` to assert the centre-child rule with res-6 children; add `assert config.SOLVE_RES < config.FINE_RES`. Passing `cal`/`airports`/`routes` into `build_graph` as parameters (default `None` → load) is a small seam that removes most monkeypatching: bounded. Removing the `cli.roads` import requires the test to patch `roads.cell_class` at its source.
- Tag: **Bounded (partial)**.

### ARCH-14 — Extensibility: node-range arithmetic is re-derived by hand in seven places; adding a node type or a mode channel touches all of them

- Severity: Medium · Confidence: High · Status: Confirmed
- Where: `nodes.py:170`, `routes_json.py:42-50`, `itinerary.py:32-33`, `modes.py:52-54`, `rail_detail.py:28,69`, `validate.py:180`, `app.js:481` all compute `n_cells + 2*n_airports`; `modes.CHANNELS` order is mirrored in `app.js:520` and as a width in `deploy_verify.sh:18`; `index.py:102-117` keys `modeDetail` by the same names by hand.
- Why: `NodeIndex` already knows its layout but exposes only `n`, `n_cells`, `airport_index`, `airport_arr_index`, `station_index`. Adding ferry-terminal nodes (spec `:128`, plan Task 10) or a "fastest possible" second surface (spec Future 1) means editing every consumer and the page.
- Fix (bounded): `NodeIndex.offsets -> dict(cells=0, airports=n_cells, arrivals=…, stations=…)` and `NodeIndex.kind(node_id)`; emitters and `routes_json` use it; `index.json` ships `offsets` per origin already (in `.json`) — keep that, plus `modeChannels` (ARCH-3). Adding an origin already needs no code (good); adding a colour scheme needs `browser_verify.sh:41` edited (fix per ARCH-4).
- Tag: **Bounded**.

### ARCH-15 — Cache/provenance: three keying idioms, several unkeyed caches, and no garbage collection

- Severity: Medium · Confidence: High · Status: Confirmed
- Where: stamped-by-constants (`_params_hash`): `airports.py:40`, `roads.py:59`, `landmask.py:176-178`, `osm.py:151-153,180-183`, `urban.py:51-52`, `countries.py:96`; manual version strings: `grid.py:27` (`GRID_VERSION`), `grid.py:82`; bare `.exists()`: `routes.py:242-244` (`routes.parquet` — never invalidated by a new OurAirports CSV or a re-crawl), `airports.py:25-30` (`ourairports.csv`), `landmask.py:49-56`, `countries.py:58-64`, `water.py:72-74` (`.fgb`), `roads.py:31-33` (rasters), `places.py:36-41`, `borders.py:25-29`, `routes.py:170` and `wikidata.py:161` (JSON crawl caches). `airports._table_cache_path` stamps constants but not the CSV bytes, so a refreshed download reuses the old parquet. `urban.py:51-52` keys on `len(cells) + first + last` only — two universes of equal length and identical ends share an entry (test fixtures built from `grid_disk` collide easily). `data/build/` holds seven `land_cells_r5_*` variants, two road grids, two airport tables; `data/cache/` holds 30 `cell_country-*` and five `ferry_links-*` files (listing taken 2026-09-10) — nothing prunes them.
- Why: CLAUDE.md's rule ("key on the constants **and inputs**") is met by `osm.py` (size + mtime) and by nothing else; the graveyard makes it impossible to tell which artefact a build used (ties to ARCH-7).
- Fix: include source-file `(size, mtime_ns)` in every stamp the way `osm.py:151` does; key `urban_mask` on the full cell-list hash like `countries.py:96`; a `transport-maps cache-gc --keep-current` that deletes stamped files whose stamp is not the current one. Provenance sidecars per ARCH-7.
- Tag: Not for this cycle (no user-visible gain), except the `urban_mask` key which is a one-liner.

### ARCH-16 — `index.json` ships `fineRes` but the page ignores it; in refined regions the hover outline is the res-6 parent of a res-7 solved cell

- Severity: Medium (visible in every city) · Confidence: High · Status: Confirmed (code) / Needs manual validation (visual weight)
- Where: `app.js:34-35,334-342` outline `h3.latLngToCell(lat, lon, SOLVE_RES)`; `index.py:125-126` emits `solveRes: 6, fineRes: 7`; the split mask (`NodeIndex._split`, `nodes.py:63`) is not shipped. The comment at `app.js:30-33` records that exactly this class of mismatch ("outlining the readout parent drew a hexagon seven times the size") was fixed once.
- Why: in Seoul, Tokyo, London the painted bands are 2.1 km hexes and the cursor outline is a 5.6 km hex that does not coincide with any painted edge.
- Fix: precise fix needs the split set on the page (a sorted uint64 array of split base cells, or one bit per base cell) — size and design to be decided: **Not for this cycle**. Bounded mitigation: hide the outline at zoom ≥ 7 when `queryRenderedFeatures` under the cursor returns a `bands` feature (the band edge already shows the cell), or outline the res-7 cell when the hit feature's `tippecanoe.minzoom` is the native level — both are small `app.js` changes.
- Tag: Bounded mitigation / Not for this cycle (precise).

### ARCH-17 — "Leave now" expected wait applies to air only; rail and ferry carry no headway, contradicting the spec and the page's own explanation

- Severity: Medium (model semantics; page copy overclaims) · Confidence: High · Status: Confirmed
- Where: spec `:183-195` ("expected wait for any timetabled leg"), `:164-171` (rail frequency per class); `build.py:232-276` (`_rail_edges`: running time + boarding/alighting only), `:279-334` (`_ferry_edges`: sailing + terminal only); `web/index.html:406-407` ("the first service is not waited for, but onward connections are"), `web/llms.txt:14-17`.
- Why: a 3-trains-a-day branch line and a 10-minute metro-grade railway cost the same per kilometre; ferries likewise. The UI text and `llms.txt` state a semantic the model does not implement for two of four modes.
- Fix: model change (per-class rail frequency as in the spec, ferry frequency default) is a calibration decision — **Not for this cycle**. Bounded: make the copy precise ("onward *flight* connections are waited for; rail and ferry are charged running time plus boarding") in `index.html:406-411`, `llms.txt`, and the `mode_detail` strings.
- Tag: Bounded (copy) / Not for this cycle (model).

### ARCH-18 — Environment-specific absolute paths and config that exist only in shell scripts

- Severity: Medium · Confidence: High · Status: Confirmed
- Where: `scripts/deploy_verify.sh:6` (`cd /Users/hletrd/flash-shared/transport-maps`), `:41` (`atik.kr:/var/www/worldmap/`), `:45-48` (`https://worldmap.atik.kr`); `scripts/browser_verify.sh:7` (`cd /tmp`), `:74` (`kill -9` by process-name grep); `scripts/osm_rail.sh:24` (region list, duplicated from the plan); `scripts/calibrate_ground.py:38,49` (`data/build/ground_samples.json` relative to cwd, reads `dist/places.json` as its town sample — the *shipped* gazetteer is an input to calibration, so the calibration sample changes whenever the gazetteer emitter changes, and the script comment at `:47` still says 7,342 Natural Earth places while `places.py` now ships ~31,000 GeoNames rows).
- Why: the deploy path is unrunnable on any other machine or by any other user; the host, path and URL are not in any config file; the browser-verify cleanup kills by name.
- Fix (bounded): `cd "$(dirname "$0")/.."`; `DEPLOY_HOST`, `DEPLOY_PATH`, `SITE_URL` env vars with the current values as defaults, documented in `deploy/README.md`; `calibrate_ground.py` should read towns from `data/cache/cities15000.zip` (its true source) rather than `dist/`.
- Tag: **Bounded**.

### ARCH-19 — Dead and duplicated code

- Severity: Low · Confidence: High · Status: Confirmed
- Where: `graph/transfers.py:8-9` and `:53-54` define `STATION_ACCESS_MIN`/`STATION_EGRESS_MIN` twice, unused anywhere (boarding lives in `calibration.toml:117-118`), pinned by `tests/graph/test_transfers.py:90-92` (a test guarding nothing); `graph/rail.py:61-65` `_haversine_km` duplicates `ground.haversine_km` (`ground.py:144-150`, whose docstring says "Public: rail and ferry use it"); `hover.py:60`, `itinerary.py:58`, `modes.py:99` compute an unused `position` and re-derive `parents` instead of calling `hover.hover_cells(idx)`; `modes.py:27` duplicates `hover.MAX_MINUTES`; `build.py:10` and `solve/dijkstra.py:3,7` unused imports; `emit/index.ATTRIBUTION` is mirrored by hand in `README.md:48-56` (test-enforced, fine) and again in `index.html:48-54` (`isBasedOn`, not enforced, omits GeoNames/HydroLAKES/Wikipedia).
- Fix: delete/dedupe; `ruff --fix` handles the imports.
- Tag: **Bounded**.

### ARCH-20 — Stray package entry point

- Severity: Low · Confidence: High · Status: Confirmed
- Where: `src/transport_maps/__init__.py:1-2` — `def main(): print("Hello from transport-maps!")`, the `uv init` template; the real entry point is `cli:main` (`pyproject.toml:25`).
- Fix: delete.
- Tag: **Bounded**.

### ARCH-21 — A verification script mutates source, and tests import from `scripts/` via `sys.path`

- Severity: Low · Confidence: High · Status: Confirmed
- Where: `scripts/check_ramps.py:99-110` (`--respace` rewrites `web/app.js` in place, control flow by `assert m, key`); `tests/web/test_ramps.py:5` (`sys.path.insert(0, …/scripts)`).
- Why: a measurement script with a write mode is easy to run by accident; `scripts/` becomes an untyped, un-linted part of the tested surface.
- Fix: move the OKLab functions to `src/transport_maps/web_check.py` (or `tools/ramps.py` inside the package) and have both the script and the test import it; keep `--respace` but make it write to stdout unless `--write`.
- Tag: Not for this cycle.

### ARCH-22 — `config.ROOT` is derived from `__file__`; the package assumes an editable install

- Severity: Low · Confidence: High · Status: Confirmed
- Where: `config.py:5` (`Path(__file__).resolve().parents[2]`), used for `calibration.toml` (`air.py:30`, `rail.py:45,51`, `ground.py:33`), `data/`, `dist/`; `pyproject.toml:27-29` builds a wheel with `uv_build`.
- Why: installed from the wheel, `ROOT` is `site-packages/..` and none of those paths exist; `scripts/` also assume cwd = repo root.
- Fix: `TRANSPORT_MAPS_ROOT` env override with the current default; package `calibration.toml` as package data or accept a path on the CLI.
- Tag: Not for this cycle.

### ARCH-23 — Hidden global state and module-level side effects

- Severity: Low · Confidence: High · Status: Confirmed
- Where: `cli.py:9` sets `POLARS_MAX_THREADS` at import (affects any process that imports `cli`, including the test runner); `cli.py:111,188` pass the graph to workers through `globals()["_CTX"]`; `roads.py:26,65` module-level `_grid_cache`; `countries.py:69-80` `A3_TO_A2` mutable dict filled as a side effect of `_polygons()`, read by `iso2()` which triggers a GDAL read on first miss (safe today only because `cli.py:153` warms it in the parent before forking; `validate.check_monotonic_ground`'s fallback at `:130-133` would hit GDAL from a child if `country`/`zone` were ever omitted).
- Fix: keep the fork design (it is justified in the comments) but make the shared context an explicit dataclass passed via `Pool(initializer=…, initargs=…)`; give `countries` an explicit `load()`; document the POLARS env in README.
- Tag: Not for this cycle.

---

## Final sweep

- **Circular imports**: none at module load. All cross-layer edges (`emit`→`graph`/`sources`, `sources`→`emit`, `validate`→everything) are function-level imports, i.e. cycles are avoided by hiding them (ARCH-9, ARCH-2).
- **Module-level side effects**: `cli.py:9` environment mutation at import; no network or file I/O at import anywhere in `src/` (checked every module header). `scripts/*.py` do I/O only under `__main__`.
- **Hidden global state**: ARCH-23. Also `app.js` (ARCH-10) and `window.__map` (`app.js:270`), which `browser_verify.sh` depends on.
- **Implicit ordering between CLI stages**: `build_water_tiles.py` must precede deploy (documented); `places/airports/borders` emitters have no stage at all (ARCH-5); `index` after `build-all --limit` is unsafe (ARCH-6); `deploy_verify.sh:40` copies `web/` into `dist/` — an undocumented step that `deploy/README.md:6` omits; `calibrate_ground.py` reads `dist/places.json`, so calibration depends on a prior emit (ARCH-18).
- **Environment-specific absolute paths**: ARCH-18 (`/Users/hletrd/...`, `/tmp`, `atik.kr`).
- **Config that exists only in shell scripts**: deploy host/path/URL, expected counts (157/37/12), Geofabrik region list, `--limit-rate 8M` — ARCH-4, ARCH-18.
- **Contract fallbacks that mask breakage**: `app.js:28-35,98` `??` defaults (ARCH-3).
- **Unused/duplicated**: ARCH-19; `ruff check` totals: 6 F821, 10 F401, 4 F841, 8 I001, 12 RUF012, 5 RUF007, 1 UP031 across `src/ scripts/ tests/` — the configured rule set is not enforced anywhere.
- **Licence/attribution architecture**: `emit/index.ATTRIBUTION` is the single source and is test-synced with README — good; `index.html:48-54` is a third, unsynced copy (ARCH-19).
- **Live artefact vs code**: `dist/index.json` has `solveRes: 5`, 157 origins and no `modeDetail`; `dist/origins/` has 786 files (no `.rail.*`), i.e. the deployed site is two model generations behind HEAD, and HEAD cannot currently build (ARCH-1). `deploy_verify.sh:21-23` already had to special-case the missing `.rail.bin` — the first symptom of a contract without a version.

## Coverage

Every file below was read in full (line-numbered) for this review. Nothing was sampled.

Source (`src/transport_maps/`): `__init__.py`, `config.py`, `cli.py`, `validate.py`; `calibrate/__init__.py`, `calibrate/fit.py`, `calibrate/ground.py`; `contour/__init__.py`, `contour/bands.py`, `contour/grid.py`; `emit/__init__.py`, `emit/airports_json.py`, `emit/borders.py`, `emit/hover.py`, `emit/index.py`, `emit/itinerary.py`, `emit/modes.py`, `emit/places.py`, `emit/rail_detail.py`, `emit/routes_json.py`, `emit/tiles.py`, `emit/water.py`; `graph/__init__.py`, `graph/air.py`, `graph/build.py`, `graph/ground.py`, `graph/nodes.py`, `graph/rail.py`, `graph/refine.py`, `graph/transfers.py`; `solve/__init__.py`, `solve/dijkstra.py`; `sources/__init__.py`, `sources/_utils.py`, `sources/airports.py`, `sources/countries.py`, `sources/landmask.py`, `sources/osm.py`, `sources/roads.py`, `sources/routes.py`, `sources/urban.py`, `sources/wikidata.py`.

Scripts: `scripts/adsb_extract.py`, `scripts/browser_verify.sh`, `scripts/build_water_tiles.py`, `scripts/calibrate_ground.py`, `scripts/check_ramps.py`, `scripts/deploy_verify.sh`, `scripts/expand_origins.py`, `scripts/ground_check.py`, `scripts/osm_rail.sh`.

Web and deploy: `web/app.js`, `web/index.html`, `web/README.md`, `web/llms.txt`, `web/robots.txt`, `web/sitemap.xml`, `web/vendor/` (listing only — generated), `deploy/README.md`, `deploy/worldmap.atik.kr.conf`.

Config and docs: `CLAUDE.md`, `README.md`, `pyproject.toml`, `calibration.toml`, `.gitignore`, `.python-version`, `data/origins.toml` (header + count), `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md`, `docs/superpowers/plans/2026-09-03-transport-pipeline.md` (all 3,646 lines).

Tests: `tests/test_cli.py`, `tests/cli/test_entrypoint.py`, `tests/test_config.py`, `tests/test_golden.py`, `tests/test_licence_firewall.py`, `tests/test_validate.py`, `tests/web/test_ramps.py`; `tests/calibrate/test_fit.py`, `tests/calibrate/test_ground.py`; `tests/contour/test_bands.py`, `tests/contour/test_grid.py`, `tests/contour/test_native_grid.py`; `tests/emit/test_hover.py`, `tests/emit/test_index.py`, `tests/emit/test_itinerary.py`, `tests/emit/test_modes.py`, `tests/emit/test_rail_detail.py`, `tests/emit/test_routes_json.py`, `tests/emit/test_tiles.py`; `tests/graph/test_air.py`, `tests/graph/test_build.py`, `tests/graph/test_ferry.py`, `tests/graph/test_ground.py`, `tests/graph/test_nodes.py`, `tests/graph/test_rail.py`, `tests/graph/test_rail_integration.py`, `tests/graph/test_refine.py`, `tests/graph/test_transfers.py`; `tests/solve/test_dijkstra.py`; `tests/sources/test_airports.py`, `tests/sources/test_cache_provenance.py`, `tests/sources/test_countries.py`, `tests/sources/test_landmask.py`, `tests/sources/test_osm.py`, `tests/sources/test_roads.py`, `tests/sources/test_routes.py`, `tests/sources/test_urban.py`, `tests/sources/test_wikidata.py` (`tests/fixtures/icn_wikitext.txt` — data fixture, not read).

Read-only artefacts consulted: `dist/index.json` (keys and counts), `dist/` and `dist/origins/` listings, `data/build/` and `data/cache/` listings, `/private/tmp/rebuild10.log` (head/tail), `git log`/`git blame` for `graph/nodes.py`, `uv run ruff check` output, and the stubbed probe `scratchpad/np_probe.py` (no repo or data writes).
