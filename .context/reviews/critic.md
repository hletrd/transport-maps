# Critic review — cycle 2 (`feat/transport-pipeline` at `bf9e5cc`)

Reviewed HEAD `bf9e5cc80f06d29b6609d974bef98ac38d8d11f9` (working tree clean at
the time of review). Cycle-1 fixes are the range `ac191db..bf9e5cc` (35 commits).
A 553-origin `build-all` was running in this checkout throughout; nothing under
`dist/` or `data/` was written, no `uv run transport-maps` subcommand was run,
no browser was used. The local preview at `http://127.0.0.1:8899/` (web/ overlaid
on dist/) was read with `curl` only.

Note on the binding rules: the copy of `CLAUDE.md` handed to reviewers at fan-out
says "adjacent bands need OKLab ΔE of roughly 8"; the file on disk (last changed
in `2526673`, 2026-09-09, before `ac191db`) already says "adjacent ANCHORS need
OKLab ΔE of at least 6". The on-disk wording is what I held the code to.

## Inventory

Read in full: `CLAUDE.md`, `.context/reviews/cycle-1/_aggregate.md`, every file
under `plan/` (README, deferred, the five c1 plans), `git log ac191db..HEAD`
with bodies, the full diffs of `web/index.html` and `web/app.js` over that range,
`web/index.html` (479 lines), `web/app.js` (1,127 lines), `web/llms.txt`,
`web/README.md`, `README.md`, `deploy/README.md`, `calibration.toml`,
`src/transport_maps/emit/index.py`, `src/transport_maps/cli.py`,
`scripts/deploy_verify.sh`, `scripts/browser_verify.sh`,
`deploy/worldmap.atik.kr.conf`, `deploy/worldmap-security-headers.conf`,
`web/vendor/fonts.css`, `src/transport_maps/config.py`.

Read in part: `src/transport_maps/graph/build.py` (1–260: air, access and
transfer edges), `src/transport_maps/validate.py` (1–60), `graph/air.py`
(wait model), `sources/urban.py`, `graph/refine.py`, `emit/water.py`,
`emit/tiles.py`, `emit/hover.py`, `emit/airports_json.py`,
`emit/rail_detail.py` (ruff output), `pyproject.toml` (markers/addopts),
`tests/test_cli.py`, `tests/sources/test_landmask.py`,
`tests/contour/test_bands.py`, `.context/reviews/cycle-1/critic.md`,
`designer.md`, `document-specialist.md` (DOC-9).

Artifacts (read-only): `dist/index.json` (157 origins, `solveRes` 5, no
`modeDetail`/`railDetail` — the known E1 state), `dist/places.json` (34,135
rows), `dist/airports.json` (4,008 rows), PMTiles headers and metadata of
`dist/water.pmtiles` and `dist/origins/{seoul,guangzhou}.pmtiles`, file sizes
and mtimes under `dist/origins/`, `/tmp/verify_*.png` timestamps, the preview's
served `index.html`/`app.js`/`index.json`/`llms.txt`.

Commands: `uv run ruff check .` (2 s), sha256 of the inline gtag script against
the CSP hash, WCAG contrast recomputation for `--text-3`, one web search for the
MapLibre CVE patch status. No pytest was run.

---

## Findings

Severity: High / Medium / Low. Status: Confirmed (from code or artifact),
Likely (from code, not exercised), Needs manual validation. Effort S/M/L.

### High

#### CRIT-1 — The ruff gate is red again at HEAD; `bf9e5cc` reintroduced two findings after the plan ticked F14 "clean"
- Severity High (a declared gate) · Confidence High · Confirmed · Effort S
- Where: `src/transport_maps/emit/rail_detail.py:12` (F401 `itertools.pairwise`
  imported but unused), `:55` (RUF007 `zip()` over successive pairs). `git log -1
  -- rail_detail.py` → `bf9e5cc`. `uv run ruff check .` exits 1 with "Found 2
  errors".
- Why (maintainer / certifier): `plan/2026-09-10-c1-gates-and-tests.md` records
  "ruff clean" as the cycle-1 gate outcome and F14 as done. The last commit of the
  cycle undid it, and nothing runs ruff on commit, so the gate's green is a
  statement about `a3f918f`, not about HEAD. The same commit changed
  `rail_detail.py`/`nodes.py` after the "251 passed" run was recorded; no re-run
  is recorded.
- Failure scenario: cycle 2 starts from a plan that says the gates are green;
  the first agent to run ruff spends its budget on a false regression hunt, or
  nobody runs it and the debt compounds.
- Fix: remove the import or use `pairwise` at line 55 (ruff `--fix` covers the
  F401); re-run the full suite once at HEAD and record it; add `ruff check` to
  the same place the deploy gate lives so a red gate cannot be ticked green.

#### CRIT-2 — The page still says connections are waited for; the graph caps a connection at the cost of walking out of the terminal and back in
- Severity High (data honesty; the brief asked for "more details" and the
  detail given is wrong) · Confidence High that the copy overclaims, Likely on
  the share of journeys affected · Effort S (copy)
- Where: `web/index.html:443-444` ("the first service is not waited for, but
  onward connections are"); `web/llms.txt:18-20` ("onward flight connections are
  charged an expected wait at the connecting airport"). Code:
  `graph/build.py:150-154` (arrival → cell = disembark, cell → departure =
  processing; 30 + 70 = 100 min at a large airport, 22 + 55 = 77 medium,
  15 + 40 = 55 small), `build.py:199-207` (the connection edge is
  `max(connection_min, median half-headway)`), `graph/air.py:55-60` (half the
  headway). Dijkstra takes the cheaper of the two, so any connection whose
  expected wait exceeds the re-entry cost is charged the re-entry cost instead,
  and route frequency stops mattering exactly where the copy says it matters
  (long, thin routes). Cycle 1 deferred the model (B1) and ticked the "copy
  half" under D12/C2, but neither touched these two sentences.
- Failure scenario (data journalist): quotes the page — "the map charges an
  expected wait at the connecting airport" — and checks a remote destination
  whose only onward service is twice a week; the figure carries at most ~100
  minutes of waiting. The claim does not survive one spot check.
- Fix: say what is charged — "connections are charged the minimum connection
  time or the expected wait, whichever is longer, capped at the time it takes to
  leave and re-enter the terminal (roughly an hour to an hour and a half); rail
  and ferry legs carry no wait" — in the Sources panel and llms.txt. Keep B1 as
  the model item.

#### CRIT-3 — `browser_verify.sh`'s new "borders" assertion cannot fail; the plan records it as done
- Severity High (CLAUDE.md testing rule: a check that passes when the thing is
  broken is worse than none) · Confidence High · Confirmed · Effort S
- Where: `scripts/browser_verify.sh:25` builds `borders:!!q(".maplibregl-canvas")`
  and `:31` fails with "no map canvas for the borders layer". That selector is
  the map canvas — the same object `canvas:` on line 24 already asserts. It says
  nothing about `borders.json` having loaded or the `borders` layer existing.
  `plan/2026-09-10-c1-build-robustness.md` ticks "D14/FD-5 `browser_verify.sh`
  asserts on `borders`".
- Failure scenario: `borders.json` 404s (it has no producing stage — see
  CRIT-13) or the `addLayer` at `app.js:406` throws; the page shows a globe with
  no boundaries; the post-deploy script prints "ALL CHECKS PASSED".
- Fix: `window.__map.getLayer("borders")` and
  `queryRenderedFeatures({layers:["borders"]}).length > 0` at zoom ≥ 3, the way
  the water check on lines 37–42 already does it. Mutate: rename the layer id →
  the check must go red.

### Medium

#### CRIT-4 — Cycle-1 "done" bookkeeping overclaims verification and contradicts itself
- Severity Medium · Confidence High · Confirmed · Effort S
- Evidence:
  - `plan/2026-09-10-c1-web-ui-detail.md` progress: "verified … by
    scripts/browser_verify.sh after deploy". No deploy happened — the build plan's
    own note (`593c231`) says the gate refused and "No files were copied". The
    only artifacts `browser_verify.sh` leaves, `/tmp/verify_{desktop,tablet,
    mobile,landscape,zoom3}.png`, are dated 2026-09-09 23:20, before every web
    commit of the cycle (`a261141` onwards, 2026-09-10 01:xx–02:25). The
    verification that did happen was a manual agent-browser pass on the preview
    (`7cd7d63` body), which is a different and weaker claim.
  - `plan/2026-09-10-c1-docs-attribution-calibration.md` lists **E8** unticked
    under "Cycle 2" and, in Progress, as done in `e11c830`. The code says partly:
    `web/index.html:46` (JSON-LD) still says "5.6 km across … 2.1 km";
    `graph/refine.py:3,7`, `contour/bands.py:148-153`, `emit/tiles.py:11,17`
    ("res-5 hexes (~8.5 km edge)"), `graph/rail.py:24` still carry the pre-v4
    figures DOC-9 listed by line.
  - `plan/2026-09-10-c1-build-robustness.md:79` lists **H2** unticked, but
    `bf9e5cc` did its rail half ("lookup tables are now built once in the parent
    and workers receive plain dicts", `cli.py:184-185`). The hover-parents half
    remains.
  - `7cd7d63` records "clean console" on the preview while **D17** ("seven
    `console.error("Error")` entries on load") stays scheduled as an
    investigation. One of the two is wrong; the plan should say which.
- Why (certifier): the plans are the input to cycle 2. A tick that cites a run
  which did not occur, or an item that is simultaneously open and closed, costs
  the next agent the time to rediscover the state.
- Fix: reword the web-plan progress line to what was done (preview pass, no
  deploy); tick H2's rail half with the commit; make E8 one entry with the
  remaining sites listed; resolve D17 one way or the other.

#### CRIT-5 — Legend ticks are now honest but read as noise: "1 · 2.1 · 3.8 · 7.8 · 15.9 · 24.5 · 50.3 · 72+", and "3.8" is itself a rounding of 3.75
- Severity Medium (design quality — the brief) · Confidence High · Confirmed ·
  Effort S
- Where: `web/app.js:178-199`. `TICK_TARGETS_MIN` aims at a doubling ladder and
  snaps to the nearest edge; `fmtH` prints `h.toFixed(1)`. With the served
  edges that yields 60→"1", 125→"2.1", 225→"3.8", 465→"7.8", 955→"15.9",
  1470→"24.5", 3020→"50.3", 4320→"72+". The plan's C4 asked for the true edge
  value ("3¾ h" or "225 min"); "3.8 h" is 228 min, a three-minute misstatement
  in the opposite direction from the one C4 fixed. Meanwhile the readout formats
  the same quantity as "3h 45m" (`fmtTime`, `app.js:532-539`) and above 48 h as
  "2 days 2h", so the legend, the big number and the route rows use three
  notations for one scale (D19, still open).
- Failure scenario (first-time visitor): a legend labelled 2.1, 3.8, 7.8, 15.9
  looks like a bug, not a scale; the round-hour edges that do exist (60, 300,
  4320 min) are not all used (5 h is skipped because 480 snaps to 465).
- Fix: one formatter for the whole page (hours everywhere, minutes only under an
  hour — this is D19), used by the legend too: "1 h · 2 h 05 · 3 h 45 · 7 h 45 ·
  16 h · 24 h 30 · 50 h · 72 h+"; prefer an exact-hour edge when one lies within
  the same log distance as the nearest edge (that puts 5 h on 300). Keep
  `data-min` and `title` as they are.

#### CRIT-6 — Three of the eighteen opening-view labels are not departure cities; clicking them silently drops a destination pin
- Severity Medium · Confidence High · Confirmed (code + `places.json` +
  `index.json`) · Effort S
- Where: `web/app.js:244-260` renders a `<button class="lbl origin">` only when
  `originNear()` finds a charted city within 80 km, otherwise a `<div class="lbl">`
  with `pointer-events:none` (`index.html:245`). The click then reaches the map
  and `map.on("click")` (`app.js:786-795`) sets a destination and opens the
  Route panel. On the served build, of the 18 largest gazetteer rows shown at
  the opening zoom (`app.js:269`), Kinshasa, Tianjin and Wuhan are not origins.
  The only visual difference is weight 500 vs 400 and `--text` vs `--text-2`
  (`index.html:245-249`). The first line of copy says "Click a city name to
  depart from it" (`index.html:361`).
- Failure scenario: the visitor clicks "Wuhan", the Route panel pops open with
  "To Wuhan", the departure stays Seoul; they conclude clicking names does not
  work. D3 fixed the symptom (no names) and exposed this one.
- Fix: give origin labels an affordance a non-origin cannot have (a 4 px dot
  before the name, or an underline at rest), and make a non-origin label a
  no-op target (`pointer-events:auto` + `stopPropagation`) or exclude non-origin
  rows from the opening budget. Say in the copy which names are clickable.

#### CRIT-7 — Switching departure blanks the land with no cue until the new tiles arrive
- Severity Medium · Confidence Medium · Likely (timing is network-dependent) ·
  Effort S
- Where: `web/app.js:458-476`: `removeLayer("bands")`, `removeSource("bands")`,
  then `addSource` of a new `pmtiles://` URL. The old surface vanishes
  synchronously; the new one needs the archive header, a directory and the
  visible tiles (three sequential range requests over HTTPS) before any land is
  painted. The only "Loading the times from X…" text is written inside the
  `mousemove` handler (`app.js:714-717`), so a visitor who clicks and does not
  move the pointer — every touch user — sees an ocean planet with borders and no
  message. `#origin-name` updates at once (`:524`), which makes the blank look
  like the answer.
- Fix: keep the old layer until the new source reports `isSourceLoaded`
  (add the new source under a temporary id, swap on `sourcedata`), or at least
  write "Loading Tokyo…" into `#where` from `paintOrigin` itself and clear it on
  the first `sourcedata` for `bands`.

#### CRIT-8 — In the "Departure" panel, address and airport results set the *destination*, and the hint about Enter is wrong for those rows
- Severity Medium · Confidence High · Confirmed · Effort S
- Where: `web/index.html:389-403` (panel titled "Departure", input labelled
  "Search departure cities, airports or addresses", button "Search address",
  hint "Enter departs from the first city match"). `web/app.js:938-957`: a
  `data-geo` (address) or `data-airport` row sets `pinB` and flies to it — a
  destination. Airport rows say "· destination" in their `.coord` span
  (`:845`); address rows do not (`:905-909`, the span shows the tail of the
  display name or `h.type`). `app.js:972-973`: Enter clicks the first
  `button[data-slug], button[data-airport]` — for a three-letter code the
  airport row is first (`:849`), so Enter sets a destination; with no local
  match Enter runs the address search, which also yields destinations.
- Failure scenario: a visitor types their street, presses Enter, picks the
  result, and the panel headed "Departure" has just changed where they are
  going *to*. The C10 button "Start from the city nearest me" above it is the
  only control in the panel that actually changes the departure by location.
- Fix (bounded): tag address rows "· destination" like airports; hint →
  "Enter: depart from the first matching city; airports and addresses become
  the destination"; consider retitling the panel "Search" and keeping
  "Departure: Seoul" as the summary's second span (it already is).

#### CRIT-9 — "Hundreds of cities" is a count claim, and it is false on the served 157-origin build; the new copy gate cannot see it
- Severity Medium · Confidence High · Confirmed · Effort S
- Where: `web/index.html:15,23,31,41,466` ("hundreds of cities"); `README.md:5`
  ("from 550+ cities"). Served `index.json` has 157 origins (E1, known). The E1
  "page half" was ticked as "count-free"; "hundreds" is not count-free. The gate
  added for it, `scripts/deploy_verify.sh:44`, greps `[0-9]{3} (cities|departure)`
  in `web/index.html` only: it does not match "hundreds", "553 origin cities"
  (the JSON-LD phrasing the gate was written against), `llms.txt`, `README.md`
  or `sitemap.xml`.
- Failure scenario: the 553 rebuild fails or is rolled back; the site keeps
  saying "hundreds" over 157; the gate passes.
- Fix: "from more than a hundred cities" (true at 157 and at 553) or, better,
  inject the count at deploy time (the deploy script already parses
  `index.json`); widen the gate to a small list of forbidden literals across
  `web/*.html|txt|md`.

#### CRIT-10 — JSON-LD publishes hard numbers no artifact carries and the rebuild will change; nothing on the page says when the data was built
- Severity Medium · Confidence High · Confirmed · Effort S (page) / S (emitter)
- Where: `web/index.html:46` `measurementTechnique`: "resolution 6 (5.6 km
  across) … 7 (2.1 km) … 3,983 airports, 57,286 rail stations and 5,672 ferry
  crossings". The cell sizes contradict `web/llms.txt:26-27` (6.5 km / 2.4 km,
  fixed in the same commit `e11c830`). 3,983 is 4,008 scheduled airports minus
  the 25 dropped at res 5 (`validate.py:14`, `dist/airports.json` has 4,008
  rows); `bf9e5cc` now snaps the 64 off-mask airports to land at res 6, so the
  count the running build will ship is different. `dateModified`
  (`index.html:61`) and `sitemap.xml` `lastmod` are hand-typed; `index.json`
  (`emit/index.py:120-138`) carries no build date, no counts, no `build_id`
  (A6c).
- Failure scenario (data journalist / site owner): the JSON-LD is what search
  engines and citation tools read; it will state a station count that the
  visible page cannot corroborate and that the next build makes wrong, with a
  hand-typed date that nobody updates.
- Fix: drop the specific counts from the static JSON-LD or leave placeholders
  the deploy script fills from `index.json`; add `builtAt` and `counts`
  (`origins`, `airports`, `stations`, `ferries`) to `write_index` and print
  "Data built on 10 September 2026" in the Sources panel. The emitter change is
  a few lines and lands with the next full build; the page half can ship now
  (print only when present).

#### CRIT-11 — "Coverage is about 98% of land" has no source and a different denominator from the grey the legend names
- Severity Medium · Confidence Medium · Likely · Effort S
- Where: `web/llms.txt:43-44`. The only coverage figure in the code is a gate,
  `validate.MIN_COVERAGE = 0.90` (`validate.py:7`), measured over cells north of
  60°S (`validate.py:21-41`); Antarctica (~43,500 res-6 cells) is excluded by
  design. Cycle 1's C6 measured 9.8 % of Seoul's *hover* cells as "no scheduled
  route" — a tenth of what the visitor sees painted grey. No document, log or
  artifact in the repo states 98 %.
- Failure scenario: a reader compares "98 % of land" with a globe on which
  Antarctica, Arctic Canada and Siberia are grey and stops trusting the rest
  of the file.
- Fix: either ship the per-origin coverage in `index.json` (the build already
  prints it per origin, `cli.py:127`) and print the active origin's figure, or
  reword: "The gate requires at least 90 % of land outside Antarctica to be
  reached from every departure; unreached land is drawn in the grey the legend
  names."

#### CRIT-12 — Aggregate finding E6 (High/High) is in no plan and not in `deferred.md`; the three page-data files still have no producing stage
- Severity Medium (planning integrity; the consequence is High for a fresh
  clone) · Confidence High · Confirmed · Effort S (plan) / M (code)
- Where: `plan/README.md` promises "Nothing is dropped"; `grep -n "E6" plan/*.md`
  → no match. `grep -rn "airports_json|emit.places|emit.borders" src scripts`
  outside `emit/` → only a comment in `urban.py:46`. `deploy_verify.sh:29-30`
  still requires `places.json`, `airports.json`, `borders.json` to exist;
  `README.md:33-38` still says `build-all` + the water script is the whole
  build. The running rebuild will therefore not refresh `airports.json`
  (4,008 rows, including airports the graph drops — C11).
- Fix: schedule E6 (a `build-all` step or a documented `transport-maps
  page-data` command that writes the three files) or record it in
  `deferred.md` with an exit criterion; until then the README must say the
  three files are built by hand.

#### CRIT-13 — No permalink: every shared link and the OG preview open on Seoul
- Severity Medium (ease of use — the brief) · Confidence High · Confirmed
  (`app.js` contains no `location.hash`/`URLSearchParams`/`history.*`) ·
  Effort S
- Where: `web/app.js:1094` always paints `FALLBACK`; `index.html:25-28` OG image
  is a fixed Seoul render. A visitor who finds "Nairobi" cannot send the view to
  anyone; the owner cannot link to a city from a post.
- Fix: read `?from=<slug>` (and optionally `&to=lat,lon`) before
  `paintOrigin(FALLBACK)`, `history.replaceState` on every `paintOrigin`, and
  reject unknown slugs. ~20 lines. Missing from every plan.

### Low

#### CRIT-14 — While an origin's times load, the ocean reads "Loading the times from Seoul…"
- Low · High · Confirmed · S. `web/app.js:555-559`: `lookup` returns `undefined`
  before testing land, so the C7 fix moved the wrong message from land to sea.
  Test land first (`cellIndex` needs only `hoverCells`), return `null` for sea
  regardless of load state.

#### CRIT-15 — On phones, the `fatal()` message is painted behind the bottom sheet
- Low · Medium · Likely (from the cascade; not rendered) · S. `fatal()`
  (`app.js:37-41`) writes into `.reading`, which sits `position:fixed;
  bottom:14px; z-index:6` (`index.html:139-144`); at ≤ 860 px `.rail` is
  `position:fixed; bottom:0; z-index:6; max-height:52vh` with a solid background
  (`index.html:312-317`) and comes later in the DOM, so it covers the readout.
  `layoutForSize()` (which would move the readout into the sheet) never runs
  because the module threw first. Fix: `fatal()` should also raise the readout's
  z-index or hide `.rail`.

#### CRIT-16 — The new visible disclaimer, the legend keys and the tick labels are the smallest text on the page
- Low · High · Confirmed · S. `index.html:162` (10 px, `--text-3`), `:165`
  (10.5 px), `:158` (10 px), `#key .src` (10 px). AA contrast now passes
  (I recomputed 6.13:1 on `--surface`, 4.76:1 on the 86 % scrim), but 10 px in
  the tertiary colour is where the page puts the sentence the owner most needs
  read. Raise to 11–11.5 px; there is room in a 306 px card.

#### CRIT-17 — PMTiles metadata served to every visitor contains local filesystem paths
- Low (hygiene / minor information disclosure) · High · Confirmed · S.
  `dist/water.pmtiles` metadata `generator_options` records
  `/Users/hletrd/flash-shared/transport-maps/data/cache/…fgb` and a
  `/var/folders/…/T/tmp…` output; every origin archive's `name` and
  `description` are `/var/folders/…/tmp….pmtiles` (`emit/tiles.py:42-45` passes
  no `-n`/`-N`; `emit/water.py` likewise). The pmtiles protocol fetches this
  JSON on every source load. Fix: run tippecanoe with `cwd` set and relative
  paths, and pass `-n <slug>`/`-N`.

#### CRIT-18 — E15's exit criterion is met; `deferred.md` and the plans have not noticed
- Low · High · Confirmed · S. `dist/water.pmtiles` (2026-09-10 00:24) is
  zoom 0–12, layer `water`, built from the OSM water polygons *and*
  `HydroLAKES_polys_v10_shp.fgb` with the area-by-zoom filter from
  `emit/water.py:38-45`. `plan/deferred.md` E15 still says "the water rebuild is
  running"; the metadata gate is parked in build-plan cycle 3. The recorded
  options also show `--detect-shared-borders`, confirming E11. Close E15's
  deferral and pull the `maxzoom`/layer gate into cycle 2 (it is ten lines in
  `deploy_verify.sh`, and the archive is 867 MB — worth a gate).

#### CRIT-19 — "Every scheme rotates hue as well as lightness" is false for Mono, and Mono shows the CLAUDE.md premise is not what the gate measures
- Low · High · Confirmed · S. `web/README.md:50-51`; `app.js:79` Mono is
  achromatic (#f4f4f4 → #262626). It passes `check_ramps.py` on lightness
  alone (≈7 ΔL per anchor step ≥ 6). Either drop Mono or fix the sentence; if
  the owner wants "a single hue cannot separate the bands" to remain the
  stated rule, the gate must also require a hue delta.

#### CRIT-20 — MapLibre CVE-2026-85061: no 5.x patch exists (fixed only in 6.4.1) — evidence for the I2 decision
- Low (mitigated: `attributionControl:false`, `app.js:344`; the page never
  hands MapLibre untrusted HTML) · High · Confirmed by search · Effort M.
  The security plan's I2 asks to "check for a 5.x patch". Sources:
  [GitLab advisory](https://advisories.gitlab.com/npm/maplibre-gl/CVE-2026-85061/),
  [FORSMILE write-up](https://forsmile.jp/en/articles/maplibre-gl-js-cve-2026-85061-xss-20260904),
  [strix.ai](https://www.strix.ai/cve/CVE-2026-85061). Decision needed: local
  one-line patch of the vendored `DOM.sanitize` loop (snapshot the
  `NamedNodeMap`) with its hash recorded, or the 6.x upgrade with the tile
  retest `web/README.md:28-34` demands.

#### CRIT-21 — `.css` and `.png` fall outside every cache location, contrary to `deploy/README.md`
- Low · High · Confirmed · S. `deploy/worldmap.atik.kr.conf:43-73` covers
  html/js/json/txt/xml, bin, pmtiles, woff2; `vendor/maplibre-gl.css`,
  `vendor/fonts.css` and `preview.png` get no `Cache-Control` (browser
  heuristics). `maplibre-gl.css` is version-coupled to the `no-cache`
  `maplibre-gl.js`; a vendor refresh can pair a cached old CSS with the new JS
  (marker/control classes). Add `css|png` to the no-cache location, or
  content-address the vendor files (H12).

#### CRIT-22 — D12 is partial: the meta/OG/Twitter descriptions still describe "hours to reach" without "door to door"
- Low · High · Confirmed · S. `index.html:15,23,31` (0 of 3 say door to door;
  the JSON-LD at `:42` does). The plan text for D12 named the meta descriptions.

### Still-open cycle-1 items with one line of new evidence (no new ID)

- **C5** (race): the new `hoverFailed` path (`app.js:495-499`) writes "Times
  unavailable for A" into `#where` without checking `active === o`, and the
  `.bin` success path (`:494`) still assigns `hoverTimes` unconditionally; the
  generation counter is the fix for both.
- **C13** (phone legend): still live — `index.html:339` hides everything but
  the handle when folded and `app.js:1067` has moved `.reading` (with the
  legend) into the sheet. This is a standing CLAUDE.md rule, not a nicety; it
  should head cycle 2.
- **D4 (semantics)**: `#map` is `role="img"` (`index.html:352`) and now
  contains `<button class="lbl origin">` children — the click-to-depart
  buttons D3 made visible are invisible to assistive technology.
- **A7**: `write_index` (`emit/index.py:131`) writes `railDetail: true`
  unconditionally, so the `index` subcommand advertises rail files it never
  writes; the page will then request two 404s per origin — the exact symptom
  C12 fixed for the other direction.
- **A6c**: `dist/origins/` is at this moment a mix of two builds — 62 files
  (beijing, fukuoka, guangzhou, nagoya, osaka, sapporo, seoul, shanghai,
  shenzhen, tokyo) rewritten at 04:34–04:44 by the hung 553 run, the other 147
  origins from the res-5 build; every array has 90,740 entries, so
  `deploy_verify.sh` gate 1 would pass it and CLAUDE.md's "never deploy a
  partial `dist/`" has no mechanical guard. The preview the cycle-1 web fixes
  were checked on is this mix.
- **B2**: `calibration.toml` is unchanged in the range; the two "refitted in
  Task 12/13" claims (`:42-43,48,95`) and the six unlabelled tables remain.
  The comment-only half is S and safe to land while the build runs.
- **E1 (data half)**, **E15 (gate)**, **B1 (model)**, **H1–H5**, **J1–J3**:
  as deferred/scheduled; no new evidence beyond the above.

---

## Regression check — every plan item marked [x]

Done = the code proves it; Partly = part of the stated task is missing;
Regressed = was done, no longer holds at HEAD.

| Item | Plan | Verdict | Evidence |
|---|---|---|---|
| D1 | web | Done | `index.html:197,205,227,272` write out `font-family:inherit; font-weight; font-size; line-height` |
| D2 | web | Done (subset half deferred by the plan) | `index.html:245-249` `.lbl{font-family:var(--font)…text-shadow}`, origin 500; `vendor/fonts.css` has 400/500/600 latin |
| D3 | web | Done (see CRIT-6) | `app.js:269` budget 18 for 1.2 ≤ z < 2.2; 15 of the top 18 gazetteer rows are origins |
| D4 + E4 (bounded) | web | Done (see CRIT-8) | `app.js:968-990` Enter/arrows/Escape; `:876-917` explicit search; `index.html:398` button |
| C4 | web | Done with caveat (CRIT-5) | `app.js:178-199` `data-min` is an edge; label is the edge rounded to 0.1 h |
| C6 | web | Done | `app.js:165-168`; `index.html:366-369` |
| D5 | web | Done | `index.html:408-412` matches `app.js:786-795` and `:772-783` |
| D6 | web | Done | `index.html:91-93`; recomputed 6.13:1 / 4.76:1 |
| D7 | web | Done | `index.html:208,251,265-266,283-284` |
| D9 | web | Done | `index.html:96` |
| D10 | web | Done | `app.js:414-415` `moveTo`; used at `:521,943,953,1120-1121`; `:995` easeTo duration 0 |
| D18 | web | Done | `index.html:146` weight 400 |
| C7 | web | Done with caveat (CRIT-14) | `app.js:552-559,714-718` |
| C10 | web | Done | `app.js:1100-1126`; `index.html:393`; `Permissions-Policy geolocation=(self)` |
| C12 | web | Done | `app.js:130-137,483-488,599`; `emit/index.py:129-131` |
| D14 | web | Done | `index.html:371`; `browser_verify.sh:26,33` checks `offsetParent` |
| D12 | web | Partly (CRIT-22) | legend cap `index.html:370`, rows `app.js:650,760`, tip `:728`; meta/OG/Twitter `index.html:15,23,31` not |
| E1 (page half) | web | Partly (CRIT-9) | runtime counts `app.js:225`, `index.html:411`; "hundreds" is still a count |
| C2 (copy half) | web | Done | `app.js:638-643` |
| C9 | web | Done | `app.js:37-52,54,67` |
| A3 | build | Done | `cli.py:85-95,104-108,205-222`; `tests/test_cli.py:196` |
| A5 | build | Done | `sources/urban.py:40-57,76` own URL, `_atomic_write`, URL in key |
| A8 | build | Done | `validate.py:37-41` |
| A4 | build | Done | `graph/refine.py:66`; `build.py:308`; `emit/modes.py:69`; `tests/graph/test_ferry.py` |
| E1 (verify half) | build | Done, narrow (CRIT-9) | `browser_verify.sh:11-17`; `deploy_verify.sh:39-51` |
| D14/FD-5 | build | Partly (CRIT-3) | disclaimer check real; `borders` check is the canvas again (`browser_verify.sh:25`) |
| E2 | docs | Done | `README.md:59-60`; `emit/index.py:59-70`; `index.html:56-59,468-471`; `llms.txt:56-58`; `app.js:204-208` |
| E5 | docs | Done | `llms.txt` is internally consistent (37 bands, res 6→7, rail and ferry in the graph) |
| E7 | docs | Done | `web/README.md:8-14,47-64`; `deploy/README.md:9-11,21-35` (the MapLibre 6 note honestly says the cause is not isolated) |
| E9 | docs | Done for the listed sites; residual `emit/tiles.py:11` "res-5 hexes" | `config.py:11-28`; `app.js:57-63,460`; `transfers.py` constants removed |
| E12 | docs | Done | `README.md:24-29,40-43,58-61` |
| D20 | docs | Done | `app.js:5-14`; `check_ramps.py:20` `MIN_DELTA_E = 6.0`; `CLAUDE.md:21-26` on disk (already so since `2526673`) |
| F14 | gates | **Regressed** (CRIT-1) | `rail_detail.py:12,55`, introduced by `bf9e5cc` |
| F1a | gates | Done | `tests/sources/test_landmask.py:11-25` |
| F1b | gates | Done | `tests/graph/test_build.py` via `idx.cell_at` (`6f63764`) |
| F1c / E2 | gates | Done | README rows present; `test_readme_documents_the_same_sources` target |
| F12 | gates | Done | no `or True` in `tests/contour/test_bands.py` |
| F2 | gates | Done | `tests/emit/test_hover.py` fixtures at `SOLVE_RES` (`498b971`, mutation evidence in body) |
| F13 / TE-23 | gates | Done | `pyproject.toml:38-44` marker + addopts |
| F13 / TE-22 | gates | Done | `tests/cli/__init__.py`, `tests/web/__init__.py` in the range's diff stat |
| Full suite run | gates | Recorded, stale | 251 passed at `3e393b5`; `bf9e5cc` changed `rail_detail.py`/`nodes.py` afterwards with no recorded re-run |
| I1 | security | Done | `app.js:31-32` and every dataset string at `:596,600,615,700,716-720,728`; `textContent` elsewhere |
| E3 (repo half) | security | Done | conf `:29,41,45,52,64,72` include the snippet; CSP hash equals sha256 of the inline gtag text (verified) |
| E4 (bounded) | security | Done | `app.js:869-917,990`; credit `:912-915`; `index.html:449-452` |
| E4 (docs) | security | Done | `web/README.md:10-14`; `llms.txt:60-63`; JSON-LD carries no "no third party" claim |

---

## The cycle-2 backlog, judged against the brief

The brief: "more details, higher quality and design and ease of usage and UI.
Do not overwork."

**Most valuable for the brief (do first):** C13 (legend never folds — a
standing rule, currently violated on every phone); CRIT-2 (honest connection
copy); D19 + CRIT-5 (one time notation, legend included); CRIT-13 (permalink);
CRIT-7 (loading cue on switch); CRIT-6 and CRIT-8 (what is clickable, what a
result does); D11 (one Route heading); C5 (generation counter — cheap
correctness on slow links); D13 reorder (map before `hover_cells.bin`);
CRIT-9/10/11 (counts, cell sizes, coverage and a build date the page can show).

**Right scope, wrong size:** D2 subset — the gazetteer's names are romanised
(0 of 34,135 rows use a non-Latin script); 77 of the 900 label-pool names carry
Latin-1 diacritics the vendored subset already covers, and about 20 need
`latin-ext` (İzmir, Al Mawşil, Cần Thơ, Huế). Vendor `latin-ext` only; cyrillic
and greek are busywork.

**Busywork relative to the brief (defer or fold into other work):** A10 (dedupe
sort key), A14 (cross-resolution monotonic gate), A17, A18 (script hygiene),
E10 (archive a plan), J5 (script paths — fold into A6d when the deploy script
is rewritten), D17 as a standalone "investigation" (run it inside the next
`browser_verify.sh` pass instead).

**Not user-visible but must not slip:** A6b/A6c/A6d (the mixed `dist/` on disk
right now is the proof), B2 comment-only half (CLAUDE.md modelling rule; safe
during the build), G1 (CLAUDE.md cache rule; in progress by another agent),
I2 with CRIT-20's evidence, F4b (tests writing into the real `data/cache/`).

**Missing from every plan (user-visible):** a permalink (CRIT-13); a loading
state on origin switch (CRIT-7); a build date and per-build counts the page can
show (CRIT-10); E6 (CRIT-12); the label-affordance problem D3 exposed
(CRIT-6); the destination-in-Departure confusion (CRIT-8); legibility of the
new 10 px copy (CRIT-16); closing E15 now that the water archive exists
(CRIT-18).

---

## Ten bounded, user-visible improvements, in priority order

1. Say what a connection really costs, on the page and in llms.txt — CRIT-2 (S).
2. One time notation everywhere, legend included; hours above 48 h — CRIT-5 + D19 (S).
3. Legend stays visible when the phone sheet folds — C13 (M; CLAUDE.md rule).
4. `?from=<slug>` permalink with `replaceState` — CRIT-13 (S).
5. Keep the old surface (or show "Loading Tokyo…") until the new tiles paint — CRIT-7 (S).
6. Mark clickable city names; a non-origin label is not a destination click — CRIT-6 (S).
7. Tag address rows "· destination"; correct the Enter hint — CRIT-8 (S).
8. Honest numbers: replace "hundreds", make the JSON-LD count-free or deploy-filled, source or reword "98 %", add `builtAt` and print it — CRIT-9, CRIT-10, CRIT-11 (S each).
9. Make the borders check real and get ruff green at HEAD — CRIT-3, CRIT-1 (S).
10. Raise the disclaimer, keys and tick labels to ≥ 11 px — CRIT-16 (S).

## Final sweep

Every file the brief listed was read in full: `web/index.html`, `web/app.js`,
`web/llms.txt`, `web/README.md`, `README.md`, `deploy/README.md`,
`calibration.toml`, `src/transport_maps/emit/index.py`,
`src/transport_maps/cli.py`, `scripts/deploy_verify.sh`,
`scripts/browser_verify.sh`, `dist/index.json` (read-only). `CLAUDE.md`, the
cycle-1 aggregate, all seven `plan/*.md`, the git log with bodies and the two
full web diffs were read before the code. No file under `dist/`, `data/` or
`src/` was written; the only write is this review. No build, test or browser
was started; one `ruff check` and one web search were run.

Counts: 22 findings — High 3 (CRIT-1, CRIT-2, CRIT-3), Medium 10 (CRIT-4 …
CRIT-13), Low 9 (CRIT-14 … CRIT-22); plus 7 still-open cycle-1 items with new
evidence. Regression table: 45 ticked items — 36 Done, 3 Done with a caveat
(D3, C4, C7), 1 Done with a residual (E9), 3 Partly (D12, E1 page half,
D14/FD-5), 1 Regressed (F14), 1 recorded but stale at HEAD (the full-suite run).
