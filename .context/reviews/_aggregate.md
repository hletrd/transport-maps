# Aggregate review — transport-maps, cycle 2

Reviewed tree: `feat/transport-pipeline` at `bf9e5cc` (working tree clean at fan-out;
the 553-origin `build-all` — rebuild16 — was running throughout and had written
20 of 553 origins at 05:10 KST, roughly nine minutes per round of five workers).

Twelve reviewers ran in parallel and returned on the first attempt: code-reviewer
(CR, 18), perf-reviewer (PR, 20), security-reviewer (SEC-18…27, 9), critic (CRIT, 22),
verifier (VER-24…38, 15), test-engineer (TE, 18), tracer (TR, 12), architect
(ARCH, 15), debugger (DBG, 14), document-specialist (DOC, 27), designer (UX-24…42, 19),
feature-dev:code-reviewer (FD, 5). **194 raw findings**, merged below into **112
distinct findings** (sections K–S) plus a table of cycle-1 items re-confirmed with
new evidence. Per-agent files sit beside this one for provenance; this file keeps the
highest severity and confidence any agent assigned to a merged item and lists every
contributing ID. Cycle-1 IDs (A1…J9) are referenced, not re-numbered; the cycle-1
aggregate is at `cycle-1/_aggregate.md`.

Where a reviewer's ID sequence continues cycle 1's (SEC, VER, UX), the cycle-1 IDs
are written `c1-SEC-n` etc. when they need distinguishing.

## AGENT FAILURES

None. All twelve returned. As in cycle 1, the OMC agent types named in the brief
are not registered in this environment; each role ran as a `general-purpose`
agent with the role's brief, plus the registered `feature-dev:code-reviewer`
(read-only tools; its review was saved verbatim by the aggregator).

## Gate evidence at `bf9e5cc` (verifier, re-run by the aggregator)

| Gate | Result |
|---|---|
| `uv run ruff check .` | **FAIL — 2 errors** (`F401` unused `pairwise`, `RUF007`) in `src/transport_maps/emit/rail_detail.py:12,55`, both introduced by `bf9e5cc` |
| `uv run pytest -q -W default --durations=15` | **254 passed, 4 deselected, 1 warning, 0 failed** in 26 min 30 s (machine loaded by the rebuild). The warning is the known fork `DeprecationWarning` (W1). The run wrote nine parquet files into the real `data/cache/` (F4b). ~1,480 s of 1,590 s is six `build_index()`/`build_graph()` fixture constructions (F4a). |
| `scripts/check_ramps.py` | 12/12 OK, anchor ΔE 6.5–8.9, lightness monotonic; the 37 interpolated bands measure 1.8–2.7 (D20 cycle 3); the uncharted grey is not measured (N5) |
| bf9e5cc's two new tests | pass individually; mutants show the "nearest" and "no polars in the worker" claims are untested (K2) |
| Designer, local preview | all twenty cycle-1 web items hold under measurement; 0 console entries (D17 not reproducible — closed) |

Refuted this cycle: **VER-29** (CLAUDE.md band rule "roughly 8") — the on-disk
`CLAUDE.md:21-26` already reads "adjacent ANCHORS need OKLab ΔE of at least 6"
(changed in `2526673`, before `ac191db`); the reviewers were handed a stale copy.
D20's wording half is done; only the interpolated-band measurement (cycle 3) remains.

Severity legend: C = Critical, H = High, M = Medium, L = Low. "Agents" counts the
reviewers that independently flagged the same defect.

---

## K. Build correctness (pipeline)

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| K1 | **bf9e5cc's airport snap cannot see split (dense) neighbours**: `_nearest_land` looks ring cells up in `cell_pos`, which never holds a split base cell's id, so the built-up coast around reclaimed-land airports is invisible. Measured from the caches (three independent probes reproduce the build's "18 of 4,008 dropped"): 6 airports still dropped with land 1–8 km away (KKJ Kitakyushu, DPL, HLE, PTF, WLS, WSZ; 94 route pairs deleted) and 9 snapped 2–4× too far (BOO Bodø 11.2 km vs 2.9, USH 13.4 vs 4.6, SIT 9.5 vs 3.4, NRL, DUT, BYW, FRO, INQ, PPW). No snap crosses a country (0 of 40). The running rebuild bakes this in. | H | H | 5 | CR-1 VER-26 TR-2 DBG-1 FD-5 | `graph/nodes.py:114-128,154-173` | S (code) — data needs a rebuild | Confirmed |
| K2 | bf9e5cc's two tests are tautological for the claims in its message: `ring2[pos] in ring2`; "nearest" untested (first-found mutant green); `test_lookup_tables_are_plain_dicts` asserts types, not that `write_rail_detail` avoids polars (mutant green); the fixture holds res-6 ids only so K1 is invisible to it | M | H | 3 | VER-27 TE-10 CR-1 | `tests/graph/test_refine.py:69-78`, `tests/emit/test_rail_detail.py:40-51` | S | Confirmed (mutants run) |
| K3 | **A worker killed by a signal still hangs `build-all` for ever**: A3 covers Python exceptions only; `multiprocessing.Pool` respawns the worker and `imap` never returns (reproduced on 3.14.2; CPython PR #16103 closed unmerged 2026-06). OOM kills, native segfaults and `kill -9` all hit this. | H | H | 1 (+PR-6) | TR-1 | `cli.py:205-222` | S | Confirmed |
| K4 | No build lock, no parent-death watchdog, no stale-run detection: eight orphaned `build-all` workers from the polars-deadlocked run (09 Sep 18:46, PPID 1) are still resident; a second `build-all`, `build_water_tiles.py` or `deploy_verify.sh`'s `rsync web/ dist/` can write into `dist/` alongside a running build | M | H | 5 | PR-6 TR-9 ARCH-1 CR-18 DBG-14 | `cli.py:204-218` | S | Confirmed (`ps`) |
| K5 | **Logging is never configured**, so every `logger.info` the pipeline relies on for "reported, not assumed" (split count, dropped stations, snapped airports, border cuts) is discarded; only two WARNINGs ever print. The snap also weakens `MAX_DROPPED_AIRPORT_FRACTION` (it now bounds only airports with no unsplit land within two rings) and `nodes.py:30-36` still says "25 of 4,008" | M | H | 2 | CR-4 TR-3 | `cli.py` (no `basicConfig`), `nodes.py:30-36,175-192`, `ground.py:132-136`, `build.py:261-262,319-320` | S | Confirmed |
| K6 | `check_bands_cover`'s 3 % pull-in (47f0baf) is planar: for an antimeridian-straddling cell the sample point lands ~11° away (probed: Chukotka vertex → 169.17 E). Latent only because the seed-0 sample is identical for every origin; any change to sample/seed/mask can abort a multi-hour build on correct geometry | M | H | 1 | DBG-2 | `validate.py:94-98` | S | Confirmed |
| K7 | `native_edges` marks the unsplit side of every split/unsplit seam `complete = False`, so `check_bands_cover` never samples exactly where `_native_features` closes slivers with the parent hexagon | L | H | 1 | TR-11 | `contour/grid.py:110-124`, `validate.py:70-73` | S | Confirmed |
| K8 | `hex_edges`/`native_edges` preallocate `8 * n` edge slots with no bounds check; the code's own comments quote 82 M edges over ~10 M cells (8.2/cell); an overflow is a bare `IndexError` hours into a build | H | M | 1 | FD-4 | `graph/ground.py:91-131`, `contour/grid.py:104-124` | S | Needs manual validation (true edge count) |
| K9 | `rail_detail` folds any table index ≥ 65,535 into `NO_RAIL` silently (latent: 2,018 rows today) | L | H | 1 | TR-10 | `emit/rail_detail.py:108` | S | Confirmed |
| K10 | `load_origins`/`write_index` accept zero origins and the page then throws on `cities[0]` — the blank-globe class | L | H | 1 | CR-14 | `emit/index.py:81-88`, `app.js:1080,1094` | S | Confirmed |
| K11 | `osm_rail.sh` `r/type=route,route=train` is an OR: every route relation survives the filter (correctness holds; extracts oversized) | L | M | 1 | CR-16 | `scripts/osm_rail.sh:42-44` | S | Likely |
| K12 | `expand_origins.py` slug fallback collapses a non-ASCII name to the country code and silently skips the next such city | L | H | 1 | DBG-9 | `scripts/expand_origins.py:51-54,84-89` | S | Confirmed |
| K13 | Fresh evidence for A9: the south-pole res-6 cell dissolves into two slivers (0.47/3.49 deg²) between −89.94° and −89.99°; the pole ring is `complete` and eligible for the cover sample | M | H | 1 | DBG-10 | `bands._split_at_antimeridian`, `landmask._pole_cells` | — | A9 (build plan cycle 3) |
| K14 | `countries.cell_country` + the `zone` comprehension are derived four times per build in the parent (~1 GB transient each) | L | H | 2 | CR-15 PR-5 | `ground.py:86-88`, `build.py:215-228`, `cli.py:173-175` | S | Confirmed (see R5) |

## L. Deploy, artifact integrity and verification scripts

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| L1 | **`dist/` is a mixture of two builds right now and the 8899 preview serves it**: `hover_cells.bin` (04:28, 90,740 entries, res 6) was written before the fork; 152 origins' arrays are the Sep-9 res-5 build (90,659); `index.json` is the res-5 one. No build identity, no lock, no staging; length equality is the only cross-file check, so two builds sharing a cell universe (a recalibration) mix invisibly. `593c231`'s progress note has the old/new direction backwards. | H | H | 5 | VER-25 ARCH-1 TR-5 CRIT(A6c) PR(note) | `cli.py:196,116-124,228-231`, `deploy_verify.sh:12-27` | M (A6b/A6c) | Confirmed (live) |
| L2 | **`tiles.write_pmtiles` and `water.build` publish by cross-filesystem `shutil.move` (copy + unlink), not a rename**: the destination is truncated for the seconds a 27 MB copy takes, and a worker killed by `Pool.terminate()` leaves a partial `.pmtiles` that the gate (`exists()` only) ships. Corrects plan A6a's premise. | H | H | 3 | CR-2 TR-6 ARCH-2 | `emit/tiles.py:28-38,68-75`, `emit/water.py:96-124` | S | Confirmed |
| L3 | Deploy consistency gate gaps: never checks `{slug}.json` (the only thing `legsTo` walks) nor pairs `.rail.json` with `.rail.bin`; `.pmtiles` by existence only (no magic/size); reads `index.json` which the build rewrites *last*, so a deploy in a build's final minutes passes and ships the old `index.json` with new arrays; no "build running" refusal | M | H | 5 | CR-7 VER-36 TR-5 SEC-20 ARCH-7 | `scripts/deploy_verify.sh:9-37,55` | S | Confirmed |
| L4 | **`deploy_verify.sh` step 1b is inert**: it greps `web/index.html` for a three-digit "N cities" literal that `d84217f` removed, so the copy gate passes on every build; "hundreds of cities" (false at 157) is invisible to it; step 1's inline Python has never had a unit test (F9) | H | H | 2 | TE-4 CRIT-9 | `scripts/deploy_verify.sh:39-51` | S | Confirmed |
| L5 | `rsync -a --delete` has no excludes and `tail -c 200` hides a failed sync: `https://worldmap.atik.kr/origins/las-vegas.pmtiles-journal` returns **200 today**; any `.tmp`/`.part`/`.DS_Store` a crashed build leaves is published; no `location ~ /\.` deny | M | H | 3 (+I4) | SEC-20 VER(I4) ARCH(I4) | `deploy_verify.sh:54-55`, `worldmap.atik.kr.conf:75-77` | S | Confirmed (live) |
| L6 | `dist/vendor/` holds 14 dead `g*.woff2` (~397 KB) that `web/vendor/` does not; `rsync web/ dist/` has no `--delete` so they deploy and cache for a year | L | H | 1 | VER-33 | `deploy_verify.sh:54` | S | Confirmed |
| L7 | nginx cache classes omit `.css` and `.png` (no `Cache-Control` at all; a refreshed `maplibre-gl.js` can pair with a heuristically cached old `.css`); `deploy/README.md` says every artifact is `no-cache`; the "content-addressed" fonts carry no hash in their names | M | H | 3 | VER-34 CRIT-21 DOC-8 | `worldmap.atik.kr.conf:43-46,68-69`, `deploy/README.md:23-33` | S | Confirmed |
| L8 | **The live site still runs the pre-cycle-1 page** (unescaped `innerHTML`, no disclaimer, no GeoNames/HydroLAKES credit, per-keystroke Nominatim, no CSP on any page asset), while the web plan says "verified … by browser_verify.sh after deploy". A page-only deploy is safe by design (every new `index.json` field has a fallback) but `deploy_verify.sh` has no such mode | M | H | 4 | VER-28 DOC-6 CRIT-4 SEC(E3) | `deploy_verify.sh:53-55`, `plan/…web-ui-detail.md:141` | S | Confirmed (live) |
| L9 | **`browser_verify.sh`'s "borders" assertion is vacuous**: `!!q(".maplibregl-canvas")` is the map canvas; a 404 on `borders.json` or a failed `addLayer` still prints `"borders":true`. FD-5 was ticked on this line. | H | H | 3 | CR-6 CRIT-3 VER-30 | `scripts/browser_verify.sh:25-26,31` | S | Confirmed |
| L10 | `browser_verify.sh` kills every `agent-browser` process on the host by name (a concurrent reviewer's session dies), `cd /tmp`, screenshots under `/tmp`; `deploy_verify.sh` hard-codes the repo path and host (J5) | L | H | 3 | VER-35 SEC-27 ARCH-7 | `browser_verify.sh:18,74,86,89`, `deploy_verify.sh:6,55` | S | Confirmed |
| L11 | PMTiles metadata served to every visitor contains local filesystem paths (`/Users/hletrd/…`, `/var/folders/…`); tippecanoe is run without `-n`/`-N` and with absolute paths | L | H | 1 | CRIT-17 | `emit/tiles.py:42-45`, `emit/water.py` | S (needs the next build to take effect) | Confirmed |
| L12 | E15's exit criterion is met: `dist/water.pmtiles` (867 MB, z0–12, HydroLAKES) landed 00:24; `deferred.md` still says the rebuild is running; the metadata gate is parked in cycle 3. Its z0/z1 tiles are 355/453 KB — 4× the bands' cost at the opening view (`-D 10` / low-detail for the water layer's lowest zooms) | L | H | 2 | CRIT-18 PR-14 | `emit/water.py:33,37,102-123`, `deploy_verify.sh:29-30` | S | Confirmed |
| L13 | The gtag inline snippet and its sha256 in the CSP conf are a hand-synchronised pair with no test (in sync today: `pCkIJ0…`, recomputed by three reviewers) | M | H | 1 | ARCH-9 | `web/index.html:6-11`, `deploy/worldmap-security-headers.conf:18` | S | Confirmed |

## M. Page correctness (data, races, failure states)

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| M1 | **The page never checks a per-origin array's length against `hover_cells.bin`**: a mixed deploy (T6: rsync ships `index.json`/`hover_cells.bin` in the first seconds, origins over minutes) or the current `dist/` renders shifted, silently wrong times for every cell; past the old array's end `undefined` reads "Loading…" for ever; `.air.bin` mismatch asserts "No flight on this route". Server-side atomicity cannot close the mid-session window; only the page can. | H | H | 4 | TR-4 DBG-3 ARCH-3 c1-SEC-11 | `web/app.js:489-499,504-511,541-559` | S | Confirmed |
| M2 | **Origin-switch race — the exact unguarded set** (new evidence for C5): only the rail fetch checks `active === o`; `.bin` (494), `.modes.bin` (506), `.air.bin` (510), `.json` (516) and the `.bin` `.catch` (495-499, which writes "Times unavailable for <old>" into `#where`) assign unconditionally. A late Seoul `.bin` re-renders the pins as "From Paris … 2 h 10" with Seoul's number; airport ordinals are shared so `legsTo` renders a plausible wrong itinerary. No `AbortController`: superseded fetches (~0.5 MB gz each) still compete for the connection. | M | H | 5 | TR-7 FD-2 CRIT(C5) CR(C5) PR-8 | `web/app.js:458-526` | S | Confirmed |
| M3 | **`app.js` module state is declared mid-file after the functions that assign it** (`pinB` :739, `railDetail` :741, `airports` :820, `cities` :816); TDZ safety rests on `paintOrigin(FALLBACK)` being the last statement (:1094). D13's reorder (map before `hover_cells.bin`) is exactly the edit that throws `ReferenceError` after the map exists — the blank-page class CLAUDE.md records twice. | H | H | 1 | ARCH-4 | `web/app.js:229-347,458-526,739-742,816-820,1094` | S | Confirmed (by reading) |
| M4 | After an origin switch the readout keeps the previous origin's figure and "· from Seoul" for ~2 s beside a header naming the new city; the land blanks synchronously with no cue until the new tiles arrive (the only "Loading…" text is written inside `mousemove`, so touch users see an ocean planet) | M | H | 2 | UX-28 CRIT-7 | `web/app.js:458-476,524,714-717` | S | Confirmed |
| M5 | C7 gaps: `renderPins` says "loading…" for ever after a failed `.bin` fetch (it ignores `hoverFailed`); while loading, the ocean reads "Loading the times from Seoul…" because `lookup` tests load state before land | L | H | 2 | TR-8 CRIT-14 | `web/app.js:555-559,760` | S | Confirmed |
| M6 | Regression from 1305ba7: `searchAddress` appends its list before *and* after the `await`, and the `$("q").value !== q` guard was removed, so stale Nominatim results for a previous query reappear under a new filter | L | H | 1 | DBG-4 | `web/app.js:876-917` | S | Confirmed |
| M7 | A non-array Nominatim 200 body (`{"error": …}`) throws `hits is not iterable` after the head text is set (unhandled rejection); a 1–2 character query plus "Search address" does nothing at all | L | H | 3 | CR-13 DBG-13 UX-30 | `web/app.js:879,892-899` | S | Confirmed |
| M8 | `fatal()` misses a valid `index.json` that lacks `origins`/`bandEdgesMin`: `meta.origins.length` throws before the map exists — blank page, no message (J1's `contractVersion` is the durable form) | L | H | 1 | DBG-6 | `web/app.js:54-67,125,225` | S | Confirmed |
| M9 | "Start from the city nearest me" stays disabled with "Locating…" when the permission prompt is dismissed (neither callback fires; the timeout does not start) | L | M | 1 | DBG-7 | `web/app.js:1100-1126` | S | Likely |
| M10 | Antimeridian on the page: the hover outline for a ±180 cell wraps the globe the long way; `nearestPlace` has no wrap so a Fiji/Chukotka cell reads "near <Vanuatu>" (J9's twin) | L | H | 1 | DBG-8 | `web/app.js:313-329,418-426` | S | Confirmed |
| M11 | Clicking open water or an unreachable cell still opens the Route panel and fires a Nominatim reverse request before `lookup()` is known to be `null` | L | H | 2 | CR-12 SEC-18 | `web/app.js:786-795,921-937` | S | Confirmed |
| M12 | **No permalink**: every shared link and the OG preview open on Seoul; `app.js` has no `location.hash`/`URLSearchParams`/`history.*` | M | H | 1 | CRIT-13 | `web/app.js:1094`, `index.html:25-28` | S | Confirmed |
| M13 | `layoutForSize()` closes every panel on each `(max-width: 860px)` change, so rotating a phone while reading a route folds the Route panel | L | H | 1 | DBG-12 | `web/app.js:1068` | S | Confirmed |
| M14 | On phones `fatal()`'s message is painted behind the bottom sheet (`.rail` fixed, z-index 6, later in the DOM; `layoutForSize` never ran) | L | M | 1 | CRIT-15 | `web/app.js:37-41`, `index.html:139-144,312-317` | S | Likely |
| M15 | Shenzhen and Hong Kong share one res-4 hover cell (`84411cbffffffff`); `originNear` can offer "Depart from Shenzhen" over Hong Kong. C3's finer hover cell removes the first half | L | H | 1 | DBG-11 | `web/app.js:244-260` | S (copy) | Confirmed |
| M16 | **On touch a tap writes pins/legs but never `#time`/`#where`** (readout showed "38h 56m · near Port-Vila, Vanuatu" above pins saying "To Beijing · 5 h 11m"); **with the sheet folded a tap does nothing visible and the legend is hidden** — the CLAUDE.md "always visible" rule, still violated at 390×844, 820×1180 and 844×390 (C13 with measured evidence) | H | H | 5 | UX-25 FD-1 CRIT(C13) DOC(C13) DBG-12 | `web/app.js:705-736,786-795,1061-1067`, `index.html:339-340` | S/M | Confirmed |

## N. Page design, ease of use, accessibility

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| N1 | **The departure city is never guaranteed a label**: Seoul is gazetteer rank 22, Tokyo 24, Paris 201; the opening budget is 18, so the bright band-0 patch at the exact centre of the screen is unnamed while the copy says "Click a city name to depart from it" | H | H | 1 | UX-24 | `web/app.js:244,269,287-298` | S | Confirmed (measured) |
| N2 | Three of the 18 opening-view labels (Kinshasa, Tianjin, Wuhan) are not origins; the only difference is weight/colour; clicking one falls through to the map and silently drops a destination pin. Gazetteer labels within 80 km of an origin become "Depart from <origin>" buttons under the *gazetteer's* name (Incheon → Seoul) | M | H | 2 | CRIT-6 CR-11 | `web/app.js:244-260,269`, `index.html:245-249,361` | S | Confirmed |
| N3 | **Legend tick labels are honest but illegible**: "1 · 2.1 · 3.8 · 7.8 · 15.9 · 24.5 · 50.3 · 72+" at 10 px with 2–3 px gaps, no unit on the strip, "72+" overhanging; "3.8" is itself a 3-minute rounding of 3 h 45 (C4 asked for the true value); the disclaimer, keys and ticks are the smallest text on the page | M | H | 4 | CRIT-5 DBG-5 UX-35 CRIT-16 | `web/app.js:178-199`, `index.html:156-165` | S | Confirmed |
| N4 | Terminology and units drift (D19, every instance enumerated by two reviewers): "5h 11m" vs "5 h 11m" vs "59 min" vs "5days 8h" vs "48–72 h" vs "72+"; chart/globe/map; passage/time/journey/reckoning; "no route" vs "no scheduled route" vs "not on land" vs "Open water"; Color/colour; "by air, rail and road" omits ferries | M | H | 3 | UX-33 DOC-13 CRIT-5 | `web/app.js:532-539,684-688,760`, `index.html:14-31,352-467` | S | Confirmed |
| N5 | In the Mono scheme "no scheduled route" is ΔE 0.9 from band 28 (muted/sand/warm 6.1–6.5); `check_ramps.py` measures neither the grey nor the sea/space constraints that `web/README.md`, `CLAUDE.md` and `app.js:20-22` say it measures (the test that does compares against `BG`, not `SPACE`); "every scheme rotates hue" is false for Mono | M | H | 3 | UX-26 DOC-10 CRIT-19 | `web/app.js:19,74-86`, `scripts/check_ramps.py:54-62,116-120`, `tests/web/test_ramps.py:29-37` | S | Confirmed (measured) |
| N6 | The focus ring on city/airport/address rows is clipped to a 1 px underline by `.results{overflow:auto}` (button edges equal container edges) — D7 defeated where keyboard users spend the most time | M | H | 1 | UX-27 | `index.html:193-199,283-284` | S | Confirmed |
| N7 | "Search address" wraps onto two lines (87×40 vs 186×28 above it) on the opening view; the `.qhint` takes the flex space first | M | H | 1 | UX-29 | `index.html:211-212,397-400` | S | Confirmed |
| N8 | Empty local search is silent (D8): "zzzzq" → 0 rows, nothing under the input; only Enter then says "No address found" | M | H | 1 | UX-30 | `web/app.js:825-867` | S | Confirmed |
| N9 | The pointer tooltip is clipped at the bottom edge (no vertical flip) (D15) | M | H | 1 | UX-31 | `web/app.js:730-734` | S | Confirmed |
| N10 | Keyboard reach and semantics (D4 semantics, measured): 9 label buttons precede the whole UI in tab order, 157 rows are tab stops (Route's summary is 159 Tabs from `#q`), no live region, `#map role="img"` with focusable children, `#results`/`#ramps` have no widget roles, Escape with a route open does nothing | M | H | 1 | UX-32 | `web/app.js:249-259,851-864`, `index.html:352,396,401,433` | S | Confirmed |
| N11 | In the panel titled "Departure", address and airport results set the **destination**; the hint "Enter departs from the first city match" is wrong for airport codes (`jfk` + Enter sets a destination) and for addresses | M | H | 2 | CRIT-8 UX-41 | `index.html:389-403`, `web/app.js:938-957,972-973` | S | Confirmed |
| N12 | City search does no diacritic folding and origins carry no ASCII alias: "Sao Paulo", "Bogota", "Zurich", "Mosul" match nothing (30 of 553 names are non-ASCII); Enter then runs an *address* search and sets a destination | M | H | 1 | CR-5 | `web/app.js:825-829,968-980`, `scripts/expand_origins.py:84-91` | S | Confirmed |
| N13 | Every origin switch flies back to zoom 1.9, even from a label clicked at zoom 6 | L | H | 1 | CR-10 | `web/app.js:521` | S | Confirmed |
| N14 | "near X" has no distance cap: Antarctica reads "near Port-aux-Français" (≈3,060 km); the tip prints "∞ no route door to door" | L | H | 1 | UX-34 | `web/app.js:534,691-700,725-728` | S | Confirmed |
| N15 | At 320 px (400 % zoom) the mast overlaps the compass, tick labels collide and city rows clip (WCAG 1.4.10); 640 px is clean | L | H | 1 | UX-36 | `index.html:306-309,343-348` | S | Confirmed |
| N16 | The one-line description is hidden below 860 px, including the 820 px tablet where the mast has 476 px of room | L | H | 1 | UX-37 | `index.html:306-308` | S | Confirmed |
| N17 | No favicon: `/favicon.ico` 404 on every load | L | H | 1 | UX-38 | `index.html` | S | Confirmed |
| N18 | Target sizes (D16): origin-label buttons 42×13–14, scheme rows 22 px, sheet handle 22 px (city rows are now 26) | L | H | 1 | UX-39 | `index.html:182,208,245,311-315` | S | Confirmed |
| N19 | With Departure open and a destination set, Settings and Sources fall below the rail's fold; the scheme picker is off-screen even when opened (`.results{max-height:40vh}`) | L | H | 1 | UX-40 | `index.html` `.results`, `.rail` | S | Confirmed |
| N20 | Control-style drift: radii 2/3/4/6 px, `.pins .depart` has a different background and the UA focus ring, the compass south needle is the pre-D6 grey, unset `type` on generated buttons | L | H | 1 | UX-42 | `index.html:253,263,383` | S | Confirmed |
| N21 | Road tooltips read "a city over 200,000.0" (`f"{200_000.0:,}"`); "GRIP4 class 1" is jargon in a tooltip | L | H | 2 | CR-8 DOC(sweep) | `emit/index.py:108`, `web/app.js:133` | S | Confirmed |
| N22 | Attribution lives only inside the closed "Sources and method" panel and MapLibre's control is hidden; OSMF guidelines accept a collapsed credit only behind a clearly labelled control | M | M | 1 | DOC-12 | `index.html:107,440-453` | S | Needs owner judgement |
| N23 | `fflate.js` (a static import of `pmtiles.js`) is missing from the `modulepreload` list; the weight-500 face is used on first paint but not preloaded (fallback swap on the panel headings) | L | H | 1 | PR-10 PR-11 | `index.html:79-83` | S | Confirmed |
| N24 | Three `backdrop-filter` surfaces over a canvas that repaints every frame, one of them (`.tip`) repositioned every pointer frame | L | M | 1 | PR-13 | `index.html:133,143,239` | S | Needs a trace |

## O. Copy, docs and plan bookkeeping

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| O1 | **The page and llms.txt say onward connections are waited for**; the graph takes the cheaper of the connection edge and `arr → cell → dep` (disembark + processing = 55/77/100 min), so frequency stops mattering exactly where the copy says it matters. B1 deferred the model; the copy half was never done. llms.txt also calls the frequency model "fitted" (it is a two-anchor hand fit) | H | H | 2 | CRIT-2 DOC-19 | `index.html:443-444`, `llms.txt:18-20,41`, `build.py:150-154,199-207`, `air.py:55-60` | S | Confirmed |
| O2 | **`calibration.toml` provenance (B2, precise list)**: seven tables carry no fitted/published label (`taxi_out_min`, `taxi_in_min`, `frequency.size_weight`, `processing_min`, `disembark_min`, `border_min`, `connection_min`); three "refitted in Task 12/13" claims are false (:42-43, :48, :95); the header :3 misdescribes the file; fitted constants live in `ground.py:25`, `urban.py:30-32`, `air.py:63,79`, `refine.py:25`; **README :75-78 "only the fitted coefficients in calibration.toml are kept" from Google Routes is false** (the fit is in code; samples sit in `data/build/`); `mode_detail()` hard-codes the rail/ferry figures the file owns; four loaders parse the file, one per origin inside a gate; no mechanical provenance check | H | H | 5 | DOC-1 DOC-2 DOC-26 CR-8 ARCH-8 | `calibration.toml`, `README.md:75-78`, `emit/index.py:104-116`, `graph/ground.py:28-34` | S (comments, README) / M (table move, loader) | Confirmed |
| O3 | **E8 half-done and recorded both ways**: JSON-LD `index.html:46` still says "5.6 km / 2.1 km" (h3 v3) and hard-codes "3,983 airports, 57,286 stations, 5,672 ferry crossings" (res-5 facts the running build changes); the same v3 sizes remain in `refine.py:3,7`, `bands.py:13,17,148-157`, `tiles.py:11,17`, `hover.py:35`, `countries.py:91`, `grid.py:3`, `roads.py:100-101`, `ground.py:55-57`, `rail.py:24`. Authoritative h3 4.5.0 figures: res 4 26.07 km edge / 1,770 km² / 45.2 km across; res 6 3.72 / 36.1 / 6.45; res 7 1.41 / 5.16 / 2.44 | H | H | 5 | DOC-3 VER-31 CR-9 CRIT-10 CRIT-4 | as listed | S | Confirmed |
| O4 | Honest numbers: "hundreds of cities" is a count claim, false at 157 (E1 page half ticked as count-free); llms.txt "Coverage is about 98% of land" has no source (the gate is 90 % non-Antarctic); README "550+"; no `builtAt`/counts in `index.json` and no build date on the page; `dateModified`/`lastmod` hand-typed | M | H | 5 | CRIT-9 CRIT-11 DOC-11 DOC-20 CRIT-10 | `index.html:15,23,31,41,61,466`, `llms.txt:43-44`, `README.md:5`, `emit/index.py:120-138` | S (page/emitter) | Confirmed |
| O5 | `web/README.md` pins MapLibre 5.24.0 without saying it is the last 5.x and carries CVE-2026-85061 (fixed only in 6.4.1); the pin note must state the mitigation | H | H | 1 | DOC-4 | `web/README.md:19-34` | S | Confirmed |
| O6 | **E6 (High/High in cycle 1) is in no plan and not in `deferred.md`**: `places.json`, `airports.json`, `borders.json` still have no producing stage (zero callers), `deploy_verify.sh` requires them, README "Development" cannot produce them, and the running rebuild will not refresh `airports.json` | M | H | 3 | CRIT-12 DOC-5 ARCH(E6) | `plan/*.md`, `README.md:33-38`, `emit/{places,airports_json,borders}.py` | S (plan) / M (stage) | Confirmed |
| O7 | Plan bookkeeping overclaims: web plan "verified … by browser_verify.sh after deploy" (no deploy happened; `/tmp/verify_*.png` predate every web commit); E8 listed both done and open; H2's rail half landed in bf9e5cc unticked; D17 scheduled while `7cd7d63` records a clean console; `593c231` has old/new reversed; `plan/README.md` status column stale, cites the pre-archive reviews path, and says "13 of 15" where the SDD ledger says 11; `_aggregate.md` status column is a snapshot at `edf4b0d` with no header | M | H | 8 | CRIT-4 VER-28 VER-38 DOC-6 DOC-16 DOC-17 DOC-18 VER-25 | `plan/*.md`, `cycle-1/_aggregate.md` | S | Confirmed |
| O8 | `emit/index.py:19-21` "this pipeline never queries OSM directly" is false (PBF extracts + water polygons); ferries are `route=ferry` *ways*, not relations (README :63, llms.txt :53); the OSM row omits ferries; `ATTRIBUTION[3]["usedFor"]` understates Natural Earth (borders, country codes, populated places) against the README row | M | H | 2 | DOC-7 VER-32 | `emit/index.py:19-21,45,57`, `README.md:58,63`, `llms.txt:53` | S | Confirmed |
| O9 | Design spec still "Approved, pre-implementation" and describes a system that was not built (Vite/React, S3/CloudFront, res 5, 11 bands, Google TRANSIT, ~150 origins); pipeline plan 0 of 118 boxes ticked (E10, with the as-built delta list) | M | H | 1 | DOC-9 | `docs/superpowers/specs/*.md:4,14,46-278`, `docs/superpowers/plans/*.md` | S | Confirmed |
| O10 | Stale numbers batch (E9 residue): `build.py:380` "Task 9's future station edges"; `modes.py:10` "6 bytes" (12); `calibrate_ground.py:7,47` "600k nodes", "7,342 places"; two sample sizes for one fit (2,998 vs 1,383) unexplained; `app.js:233,319` "7,000" (34,135); `app.js:618-622` describes only the no-`modes.bin` fallback; `places.py:3` "31,000"; `airports_json.py:3` "3,983"; `nodes.py:32`, `validate.py:14,133`, `cli.py:170`, `bands.py:25`, `tiles.py:9-19,35` "157 origins" / "today" figures; `osm_rail.sh:11-16` duplicated paragraph; `landmask._cells_touching` dead | L | H | 3 | DOC-14 VER-37 CR-9 | as listed | S | Confirmed |
| O11 | IBM Plex ships with no licence text (OFL requires the copyright notice and licence with every copy; the woff2 name tables carry nameID 0 and 14 but not 13) | L | H | 1 | DOC-15 | `web/vendor/` | S | Likely |
| O12 | tippecanoe `--detect-shared-borders` is deprecated with a named replacement (`--no-simplification-of-shared-nodes`); six of seven sky keys are inert under globe (E11 verified) | L | H | 1 | DOC-21 | `emit/water.py:105-108`, `web/app.js:356-360` | S | Confirmed |
| O13 | D12 partial: the meta/OG/Twitter descriptions still say "hours to reach" without "door to door" | L | H | 1 | CRIT-22 | `index.html:15,23,31` | S | Confirmed |
| O14 | `data/origins.toml` header describes the hand-picked list only (396 of 553 came from `expand_origins.py`) | L | H | 1 | DOC-23 | `data/origins.toml:3-4` | S | Confirmed |
| O15 | `<meta charset>` is the sixth element in `<head>` (valid, unconventional) | L | H | 1 | DOC-25 | `index.html:4-12` | S | Confirmed |
| O16 | llms.txt could state the per-origin array sizes and that `hover_cells.bin` gives their ordering (J1's home) | L | H | 1 | DOC-27 | `web/llms.txt:34-37` | S | Confirmed |

## P. Tests and gates

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| P1 | **The ruff gate is red at HEAD**: bf9e5cc reverted `pairwise(st)` to `zip(st, st[1:])` and kept the import; F14 was ticked "clean" 3.5 h earlier; nothing gates on ruff | H | H | 3 | CR-3 VER-24 CRIT-1 | `emit/rail_detail.py:12,55` | S | Confirmed |
| P2 | **F3 not landed**: the eastern DMZ chain has four non-adjacent pairs at res 6, so deleting the border cut leaves that test green (only the western test guards it); the Schengen `if` guard is still a silent pass | H | H | 1 | TE-1 | `tests/sources/test_countries.py:31-51,77-88` | S | Confirmed (mutant) |
| P3 | Nothing pins that `.air.bin`, `.modes.bin`, `.rail.bin` describe the same solver cell as `.bin` (mutating `_representative_children` to fastest-child reds `test_hover` only); `write_rail_detail` has no test at all (F7) | H | H | 1 | TE-2 | `emit/itinerary.py:49-71`, `modes.py:82-101`, `rail_detail.py:80-110` | M | Confirmed (mutant) |
| P4 | The page's pure decoding has no test though `node` v24 is on the host and a 40-line `node --test` harness runs `esc`/`fmtTime`/`cellIndex` in 66 ms; `fmtTime(119.6)` → "1 h 60m" is a latent seam; no constants-parity test for `names`/`NO_AIRPORT`/`NO_RAIL`/layer name/`airports.json` column order/`meta.*` keys (F5, pull forward) | H | H | 2 | TE-3 TE-15 | `web/app.js:31-32,145,532-580,610,742` | M (S for parity) | Confirmed (harness run) |
| P5 | F6 still vacuous: split cell 0 carries value 0 so zero-fill and carry-down are indistinguishable (mutant green) | M | H | 1 | TE-5 | `tests/graph/test_refine.py:30-42` | S | Confirmed (mutant) |
| P6 | F11: `test_modes.py` sums channels 2–5 so a swapped `ROAD_CHANNEL` stays green; every test loads the real 9 MB GRIP4 grid | M | H | 1 | TE-6 | `tests/emit/test_modes.py:30-73` | S | Confirmed (mutant) |
| P7 | Cache provenance (G1): the tests prove five of fourteen stamped constants; `test_every_stamped_path_carries_a_hash` is green under a constant `"deadbeef"` stamp; no provenance test for `cell_country`, `ferry_links` (omits `ANTIMERIDIAN_EPS_DEG`), `routes.parquet` (bare `.exists()`; on disk it is *older* than the airport table it depends on), `urban_mask` (len/first/last), `native_edges`; `road_class_grid` still omits `GRIP4_URL`; per-item parsed caches carry no parser version; `_cells_touching` is dead | M | H | 3 | TE-7 TR-12 FD-3 | `tests/sources/test_cache_provenance.py`, `roads.py:59`, `routes.py:242-244`, `osm.py:151-153`, `urban.py:76-77` | S | Confirmed |
| P8 | Tests write into the real `data/cache/` (F4b): 358 `rail_routes-*` (+64 since cycle 1), 45 `cell_country-*`, 26 `ferry_links-*`, 26 `urban_mask-*`; a `config.CACHE` redirect makes the fast subset hermetic in 18 s (demonstrated) | M | H | 3 | TE-8 VER(F4b) CR-17 | `tests/sources/test_osm.py`, `test_countries.py`, `graph/test_ferry.py`, `test_urban.py`, `test_validate.py` | S | Confirmed |
| P9 | `tests/test_cli.py` reads the real OSM cache and runs a 2.75 s polars UDF per `_build_all`; `solve`/`index` untested; `_worker_cap` untested (F8) | M | H | 1 | TE-9 | `tests/test_cli.py:29-112`, `cli.py:264-294` | S | Confirmed |
| P10 | Hygiene: no `tests/__init__.py` (subpackages import as `cli`, `web`, …); `test_ramps.py` mutates `sys.path`; `integration` marker absent (F4a); no `--strict-markers`; umask-dependent `_atomic_write` test; mtime-only fingerprint test; the forked test's 30 s alarm; `test_tiles` needs tippecanoe with no skip; `REQUIRED_ATTRIBUTION` lacks GeoNames/HydroLAKES; `PAGE_CREDITS` duplicates two `ATTRIBUTION` rows untested | L | H | 5 | TE-11…TE-18 DOC-24 ARCH-11 ARCH-13 | various | S | Confirmed |
| P11 | No test guards `attributionControl: false` / no `AttributionControl` (the only reason CVE-2026-85061 is unreachable) | M | H | 1 | SEC-22 | `tests/` | S | Confirmed |

## Q. Security and third-party policy

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| Q1 | **Reverse geocoding fires on every map click** with no throttle; the OSMF Nominatim policy (fetched today) is 1 req/s *per application*; "click anywhere to set a destination" is the primary interaction; the reverse label carries no attribution beside it. E4 covered search only. | M | H | 2 | SEC-18 CR-12 | `web/app.js:786-795,921-937` | S | Confirmed |
| Q2 | **The corrected CSP has never been exercised against the page**: live HEAD requests show no CSP on any page asset and a live build that predates gtag and Nominatim; the new policy adds a hash, `blob:` workers and five hosts at once, and the failure mode is the blank globe. Hash and hosts verified statically. | M | H (untested) / M (will break) | 1 | SEC-19 | `deploy/worldmap-security-headers.conf:18`, `deploy/README.md:53-55` | S | Needs manual validation |
| Q3 | MapLibre CVE-2026-85061: **no 5.x fix exists or will** (5.24.0 is the last 5.x; fixed only in 6.4.1; npm latest 6.9.0). The vulnerable `removeAttributes` loop is present verbatim; unreachable only because `attributionControl: false`. Patch the vendored bundle (one token: `Array.from(t.attributes)`), record the hashes, pin the mitigation with a test (P11) | M | H | 3 | SEC-22 CRIT-20 DOC-4 | `web/vendor/maplibre-gl.js` | S (patch) / M (6.x) | Confirmed |
| Q4 | `adsb_extract.py` downloads whatever URL the GitHub API returns, with any scheme, to a path built from the tag name, unbounded (A18 detail) | L | H | 1 | SEC-23 | `scripts/adsb_extract.py:96-121` | S | Confirmed |
| Q5 | CSP hardening: `script-src blob:` wider than needed, `object-src` unspecified, no `report-to`; the GA host list silently drops optional Google beacons | L | H | 1 | SEC-24 | `deploy/worldmap-security-headers.conf:18` | S | Confirmed |
| Q6 | Supply chain (I5): `selectolax` declared and unused; no vendor hashes recorded (sha256s captured in the review); no audit step (`pip_audit` absent); the locked Python set is clean against this year's advisories (urllib3 2.7.0, requests 2.34.2) | L | H | 2 | SEC-25 DOC-22 | `pyproject.toml:20`, `web/README.md:16-26` | S | Confirmed |
| Q7 | Slugs validated only on `solve --name`; `load_origins` checks uniqueness only; `expand_origins.py` writes names unescaped and owns a second slug grammar (A17 detail; all 553 slugs are clean today) | L | H | 3 | SEC-26 ARCH-14 DBG-9 | `cli.py:32-42`, `emit/index.py:81-88`, `scripts/expand_origins.py:51-54,97-98` | S | Confirmed |
| Q8 | Verification scripts: fixed `/tmp` paths, a name-grep `kill -9`, an absolute home path; site URL/host/root in five places (J5 detail) | L | H | 3 | SEC-27 VER-35 ARCH-15 | `browser_verify.sh:18,74,86,89`, `deploy_verify.sh:6,55` | S | Confirmed |

## R. Performance

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| R1 | **H1 reopened — exit criterion met**: five workers at 11–12 GB footprint each (8–10 GB compressed) plus a 5.7 GB parent on a 32 GB M4; swap 10.7 of 12.3 GB, 60 MB free, 9.6 GB paged out per 16 min; each origin writes a 629–669 MB GeoJSON for tippecanoe (6.3× res 5) held as a ~3 GB Python object tree and re-parsed by `check_bands_cover`; rounds of five take ~9 min, projecting **16–17 h** rather than 7–8 | H | H | 1 | PR-1 | `contour/bands.py:176-194,302-345`, `emit/tiles.py:28-30`, `validate.py:104-105` | M | Confirmed (measured) |
| R2 | `_dissolve` evaluates `_crosses_antimeridian` twice per cell over ~29 M cell-band memberships per origin: ~115 s of ~480 s per origin (~3.5 h of the build); only a few thousand cells on Earth wrap (H4 residual; contour code has settled) | H | H | 1 | PR-2 | `contour/bands.py:62-64,120-125,255-259` | S | Confirmed |
| R3 | **The hover family recomputes `parents`/`_representative_children` four times per origin and rebuilds a 10 M-entry dict that `idx._cell_pos` already is**: ~80 s and 4 × ~0.8 GB transient per origin; the same loops un-share the copy-on-write graph (H2's other half, H5 mechanism, F7's cause) | H | H | 4 | PR-3 ARCH-6 VER-38 CR(F7) | `emit/hover.py:26-56`, `itinerary.py:58,66`, `modes.py:90,96`, `rail_detail.py:86,94`, `cli.py:118-124` | S | Confirmed |
| R4 | `_worker_cap`'s constant is contradicted 3× by the measured footprint; nothing logs `ru_maxrss` per origin so the next build starts from the same guess (H5 evidence) | H | H/M | 1 | PR-4 | `cli.py:62-82,204-218` | S | Confirmed |
| R5 | Origin-independent inputs recomputed in the serial phase before the fork: `roads.cell_class` 4× (36–92 s each), `cell_speed_kmh` 2×, `cell_country` + `zone` 4× — 2–3 min of the ~5 min serial phase and ~2.4 GB transient in the parent (also J4's injection seam) | M | H | 2 | PR-5 CR-15 | `graph/nodes.py:138`, `ground.py:37-59,80-88`, `build.py:215-228`, `cli.py:169-176` | S | Confirmed |
| R6 | tippecanoe input is 650 MB per origin in `$TMPDIR` (~360 GB of temp writes over the build, 3.3 GB present at once), four to five run concurrently and multi-threaded (~40 threads), and a killed worker leaks them (470 MB from 9 Sep still there) (H10 quantified) | M | H | 1 | PR-7 | `emit/tiles.py:28-61` | S | Confirmed |
| R7 | `check_coverage` (10 M `cell_to_latlng` per origin ≈ 17 min over the build) and `_coarse_features` (5 M `cell_to_parent` + `np.unique` on a string array ≈ 30–45 min) redo origin-independent work | L | H | 1 | PR-16 | `validate.py:33-37`, `contour/bands.py:270-274,335` | S | Confirmed |
| R8 | Page polish: `nearestPlace` scans 34,135 rows twice per pointer frame (comment says 7,000); `showLabels` collision test is O(labels × placed); `render()` rebuilds 553 rows per keystroke; `pool.imap` ordered hides progress behind the slowest origin (H11); nginx `gzip_comp_level 1` per request where `gzip_static` would cut ~13 % at zero CPU (H12 detail); first-load inventory measured (2.5 MB gz, gtag 191 KB third-largest, ~390 KB leg data needed only after a click) | L | H | 1 | PR-9 PR-12 PR-15 PR-17 PR-18 PR-19 PR-20 | `web/app.js:229-329,265-309,825-867`, `cli.py:217`, `worldmap.atik.kr.conf:79-81` | S | Confirmed |

## S. Architecture and contract

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort | Status |
|---|---|---|---|---|---|---|---|---|
| S1 | **The pipeline↔page contract has no version, no build id, no hover-cell count, no channel list**; the page's `??` fallbacks accept any `index.json` (`?? 10` bands is stale); widths, suffixes, sentinels and node arithmetic are re-typed in ≥ 6 places; `index.json.railDetail` is `True` unconditionally and nothing says whether rail/ferry were in the graph (J1 with the page-side check M1 added; design in `architect.md` §4) | H | H | 2 | ARCH-3 ARCH-12 | `emit/index.py:120-140`, `app.js:55-64,125,145,571-573,610,742`, `deploy_verify.sh:18,21-23` | M | Confirmed |
| S2 | "No polars/GDAL/rasterio inside a forked worker" is enforced by comments only: `shared.get("rail_tables")` is a soft key (a rename yields an all-`NO_RAIL` build silently), `modes.py:47-50` and `validate.py:149-153` have rasterio/GDAL fallbacks a dropped keyword triggers, `rail_detail.py:17` imports polars at module level, and `_stub_pipeline` replaces every emitter so tests cannot see any of it | M | H | 1 | ARCH-5 | `cli.py:5-9,123,170-185`, `emit/modes.py:47-50`, `validate.py:149-153`, `tests/test_cli.py:29-112` | M | Confirmed |
| S3 | Verification is a shell script that is a second writer of `dist/`, re-types the contract as inline Python, binds the page to fifteen DOM selectors + `window.__map` with no test, and kills processes by name (`SCHEMES=12` a literal) | M | H | 1 | ARCH-7 | `deploy_verify.sh`, `browser_verify.sh` | M | Confirmed |
| S4 | `solve`/`index` remain divergent: `solve` writes a layout the page cannot read into `dist/` root where `rsync --delete` ships it; `index` now writes `hover_cells.bin` *after* `index.json` (the reverse of `_build_all`'s order) and can advertise origins with no files (A7; delete rather than align) | M | H | 1 | ARCH-10 | `cli.py:264-294` | S | Confirmed |
| S5 | `MIN_CELLS_TO_CACHE` switches the `native_edges` cache path on input size so fixtures never exercise it | L | H | 1 | ARCH-13 | `contour/grid.py:31,44,71,97,126` | S | Confirmed |
| S6 | The design spec's "the frontend never learns how the numbers were made; the pipeline never learns how they are drawn" is false both ways (`modeDetail` prose; overlap-by-rim depends on `fill-sort-key`) — legitimate invariants that belong in J1's document | L | H | 1 | ARCH(sweep) | `spec:62-63`, `bands.py:5-20`, `app.js:470` | S | Confirmed |

---

## Cycle-1 items re-confirmed with new evidence (no new ID; still scheduled or deferred)

| Cycle-1 ID | New evidence this cycle | Agents |
|---|---|---|
| A6a–d | L1 (live mixed `dist/`), L2 (pmtiles copy), TR-5 (gate reads the last-written `index.json`), rsync order (root files first, origins for minutes) | VER TR ARCH CR CRIT PR |
| A7 | `index` writes `hover_cells.bin` after `index.json`; `railDetail: true` for files it never writes | ARCH CRIT DBG |
| A9 | K13 pole slivers | DBG |
| A13 | 65,534 displays as "45 days 12h"; a `routes.json` leg ≥ 65,535 would print "∞ no route" as a leg | TR |
| A17/A18 | Q7, Q4 | SEC ARCH DBG |
| B1 | O1 is the copy half; model unchanged | CRIT DOC |
| B2 | O2 precise list | DOC ARCH CR |
| C3 | outline is the res-5 hexagon on the served dist; three-cell disagreement confirmed | TR UX |
| C5 | M2 exact unguarded set incl. the `.catch` | TR FD CRIT CR PR |
| C13 | M16 measured on three viewports | UX FD CRIT DOC DBG |
| D4 (semantics) | N10 measured tab order | UX CRIT |
| D8 | N8 | UX |
| D11 | two "Route" headings and the time three times, confirmed | UX |
| D13 | ARCH-4 (M3) is a prerequisite; design note in `architect.md` §4 | ARCH PR |
| D15 | N9 measured (3 px, and clipped at the bottom) | UX |
| D16 | N18 | UX |
| D17 | **closed**: 0 console entries; the seven entries were the `.rail.*` 404s C12 removed | UX |
| D19 | N4 enumerated | UX DOC CRIT |
| D20 | wording done on disk (VER-29 refuted); interpolated bands 1.8–2.7 (cycle 3) | VER UX DOC |
| E1 (data) | still 157/res 5 served and live; the rebuild is at 20 of 553 | all |
| E3 (server) | live headers absent on every page asset; old CSP only on unmatched files | SEC DOC VER |
| E6 | O6 — unscheduled | CRIT DOC ARCH |
| E10 | O9 as-built delta list | DOC |
| E11 | O12 verified | DOC |
| E15 | L12 exit criterion met | CRIT PR |
| F3, F4a, F4b, F5, F6, F7, F8, F9, F11 | P2, P10, P8, P4, P5, P3, P9, L4, P6 | TE VER |
| G1 | P7 extended | TE TR FD |
| H1–H5, H10, H11, H12, H14 | R1–R6, R8 with measurements; H1 and H4 exit criteria met | PR |
| I2 | Q3 decision evidence | SEC CRIT DOC |
| I3 | unchanged (no new evidence) | SEC |
| I4 | L5 live 200 | SEC VER |
| I5 | Q6 | SEC DOC |
| J1 | S1 | ARCH TE |
| J4 | R5 is the seam | PR ARCH |
| J5 | Q8 | SEC VER ARCH |
| J9 | M10 page twin | DBG |
| W1 | one warning per gate run, unchanged | VER TE |

---

## Cross-agent agreement (highest-signal items)

| Merged | Agents | Summary |
|---|---|---|
| K1 | 5 | bf9e5cc's snap blind to split cells: 6 airports dropped, 9 mis-placed (measured) |
| L1 | 5 | `dist/` is a mixed generation now; no identity, no lock |
| L3 | 5 | deploy gate: no `{slug}.json`, no pmtiles content, reads the old `index.json` |
| M2 | 5 | C5 race: exact unguarded set incl. the `.catch`; no abort |
| M16 | 5 | phone tap never writes the reading; folded sheet hides the legend (CLAUDE.md rule) |
| O2 | 5 | calibration provenance: seven unlabelled tables, three false refit claims, README false |
| O3 | 5 | JSON-LD v3 cell sizes and res-5 counts; ten comment sites |
| O4 | 5 | "hundreds", "98 %", no build date |
| O7 | 8 | plan bookkeeping overclaims |
| K4 | 5 | orphaned workers; no lock / watchdog |
| M1 | 4 | page never checks array length vs `hover_cells.bin` |
| L8 | 4 | live site still pre-cycle-1; page-only deploy mode |
| N3 | 4 | legend tick labels illegible / rounded |
| R3 | 4 | hover family recomputed 4× per origin |
| L2, L9, N4, N5, P1, P7, P8, Q3, K2, L7, M7, O6, Q7, Q8 | 3 | see tables |

## What fits this cycle's brief ("more details, higher quality, ease of use, UI; do not overwork")

Bounded, S-effort, user-visible, in priority order: M16 (C13 — the standing legend rule
and the touch readout), N1 (label the departure city), M4 (loading cue + readout reset on
switch), M2 + M1 + M3 (C5 generation counter with the array-length guard and the
state-block hoist; one commit), O1 (honest connection copy), N3 + N4 (one time formatter
for legend, readout and legs; D19), N2 + N11 (which names are clickable; what a result
does), N12 (diacritic folding), N6/N7/N8/N9 (focus clip, wrapped button, empty search,
tooltip flip), M12 (permalink), N5 (Mono grey, measured), O4 (honest counts and a build
date), O3 (cell sizes in JSON-LD and comments), M5/M6/M7 (three small failure-state
fixes), N10 (semantics), N13, N14, N17.

Blocking for the gates regardless of brief: P1 (ruff red), L4 (inert copy gate), L9
(vacuous borders check), P2 (F3), P5 (F6), P6 (F11), P8 (F4b).

Build/deploy integrity that must not slip (not user-visible until it fails): K1 + K2
(the snap, so the *next* build is right), K5 (logging), K3 + K4 (signal death; lock),
L2 (atomic pmtiles), L3 + L5 (gate and rsync hygiene), Q1 (Nominatim rate), Q3 (patch
the vendored MapLibre), O2 comment-only half, O6 (schedule E6).

Not for this cycle (recorded, not dropped; scheduled cycle 3 or deferred with exit
criteria): R1–R7 (performance; H1/H4 exit criteria met — reopen in the deferred ledger),
S1 full J1, S2 `BuildContext`, S3 `check-dist` as a package command, A6b staging design,
A6d versioned releases (owner's nginx change), N22 (owner judgement), Q2 rehearsal (needs
a scratch nginx or a meta-CSP pass), K8 validation, O9, O11.
