# Critic review — transport-maps (revision `ac191db`, branch `feat/transport-pipeline`)

Reviewed read-only on 2026-09-10 against the working tree, the local `dist/` (157 origins,
`solveRes` 5), the local preview at `http://127.0.0.1:8899/`, and the live site
`https://worldmap.atik.kr/` (same 157-origin build). Perspectives: the visitor, a transport
geographer, a maintainer, and a journalist checking the figures. The user's brief for this
cycle — *more details, higher quality and design and ease of usage and UI; do not overwork*
— is applied as a filter: every finding says whether it fits that brief.

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 1 | CRIT-1 |
| High | 7 | CRIT-2 … CRIT-8 |
| Medium | 11 | CRIT-9 … CRIT-19 |
| Low | 7 | CRIT-20 … CRIT-26 |
| **Total** | **26** | |

Findings that fit this cycle's brief (bounded, user-visible detail/quality/UI work):
CRIT-1 (copy derived from data), CRIT-3, CRIT-4, CRIT-8, CRIT-9, CRIT-10, CRIT-11, CRIT-12,
CRIT-14, CRIT-16, CRIT-18, CRIT-20, CRIT-22, CRIT-23, and the copy half of CRIT-2.
Findings that do **not** fit it (infrastructure, modelling, test suite): CRIT-5, CRIT-6,
CRIT-7, CRIT-15, CRIT-17, CRIT-24, CRIT-25, CRIT-26, and the modelling half of CRIT-2.

Top five: CRIT-1 (the page says 553 cities and the list shows 157), CRIT-2 (waiting is not
what the page and spec say it is), CRIT-3 (the route panel's "of which" itemisation
overflows its own total on 84 % of air journeys), CRIT-4 (legend tick "72+" sits at 67 h),
CRIT-5 (the live site sends no CSP/HSTS on any page asset because of an nginx
`add_header` inheritance bug).

---

## Findings

### CRIT-1 — The page describes a dataset the artifact does not contain (553 cities, res 6/7, rail stations, HydroLAKES) while `index.json` lists 157 origins at res 5

- **Severity:** Critical  **Confidence:** High  **Status:** Confirmed
- **Where:**
  - `/Users/hletrd/flash-shared/transport-maps/web/index.html:14-15` (`<title>` / description: "from 553 cities"), `:23`, `:31`, `:41-46` (JSON-LD: "resolution 6 (5.6 km across), refined to resolution 7 … 57,286 rail stations and 5,672 ferry crossings"), `:373-375` ("only those 553 have a computed surface"), `:420-422` (noscript "553 cities") — seven hard-coded occurrences.
  - `/Users/hletrd/flash-shared/transport-maps/web/llms.txt:3-7` ("each of 553 origin cities … rail from OpenStreetMap"), `:31` ("Rail and ferry are not yet in the graph"), `:53-59` ("H3 resolution 6 … Coastlines … zoom 12 … Lakes: HydroLAKES … Rail legs name the station and line") — the same file asserts rail is absent *and* that rail legs are named.
  - `/Users/hletrd/flash-shared/transport-maps/README.md:5` ("550+ cities"), `:11` (badge "H3 res 6/7"), `:26` ("travel times from any location in the world" — origins are a fixed list).
  - `/Users/hletrd/flash-shared/transport-maps/web/app.js:722` (comment: "only the 157 cities have a computed surface"), `:29-34` (defaults and comment describe res-5 solve / res-4 readout).
  - `dist/index.json` (local and live): `origins: 157`, `solveRes: 5`, `hoverRes: 4`, 7 attribution entries (no GeoNames, no HydroLAKES). `dist/origins/` has no `.rail.bin/.rail.json`. `dist/water.pmtiles` (local **and** live, identical size) has `maxzoom 11` and no `Lake_area` field — it is the pre-HydroLAKES coast build, not the zoom-12 build described by `emit/water.py` and `llms.txt`.
  - Live `llms.txt` still says 157 *and* "Rail and ferry are not yet in the graph" — yet `dist/origins/seoul.modes.bin` (the file the live route panel reads) has non-zero rail minutes on 70,395 of 90,659 cells (78 %) and ferry minutes on 1,647.
- **Why it matters:** Journalist: the numbers a reader is most likely to quote (how many cities, how fine the grid, whether rail is modelled) are wrong in one direction on the live site and the other direction in the working tree. Visitor: the working-tree page would show "553 cities" in its title and a 157-entry list. Maintainer: none of the gates catch it — `scripts/deploy_verify.sh` never compares copy to `index.json`, and `scripts/browser_verify.sh:19` hard-codes `"cities":157`, so the two verification scripts and the HTML disagree with each other about which build is expected.
- **Failure scenario:** The next `scripts/deploy_verify.sh` run copies `web/` over the current `dist/` (step 2 does exactly that) and passes; the live title says 553, the Departure list shows 157, Google indexes "553 cities" and "57,286 rail stations", and the machine-readable `llms.txt` tells every LLM that rail is not modelled while the Route panel says "by rail via …".
- **Fix:** (a) Stop hard-coding counts in the page: render "N cities" from `meta.origins.length` in `app.js` and keep only build-independent wording in static tags (or have the build emit `index.html`'s meta block from `index.json`). (b) Add to `deploy_verify.sh` step 1 a check that every number in `index.html`/`llms.txt` that names an origin count or resolution equals what `index.json` says, and that `water.pmtiles` metadata carries `Lake_area`/`maxzoom 12` when the copy claims HydroLAKES/zoom 12. (c) Rewrite `llms.txt` "Known limits" to match the artifact (rail and ferry are in; no waiting on them — see CRIT-2). (d) Fix the `app.js:722` comment and the README "any location" sentence.
- **Fits this cycle's brief:** yes (copy and one verification check); the build itself is out of scope.

### CRIT-2 — The published waiting semantics are not what the graph computes: route frequency never affects a journey, rail/ferry connections wait zero minutes, and remote islands are painted hours away

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where:**
  - `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/build.py:94-101` — flight edges carry block time only ("Waiting is charged on the connection edge instead").
  - `build.py:163-213` `_transfer_edges` — the only wait in the air graph is `max(MCT, median(expected wait of ALL routes departing this airport))`, charged on the `arr → dep` edge of the *connecting* airport. The frequency of the route actually flown next is never consulted; `air.frequency_model` (`graph/air.py:82-96`) reaches the graph only through that per-airport median.
  - `build.py:232-276` `_rail_edges` — boarding 15 min + running time + alighting 5 min; no headway, no wait, and a change of train at a merged station (`graph/rail.py:26`, res-9 merge) costs 0 min.
  - `build.py:279-334` `_ferry_edges` — sailing time + `terminal_min` 30; no headway.
  - Copy: `web/index.html:406-407` "Reckoned from a planned departure: the first service is not waited for, but onward connections are."; `web/llms.txt:14-17` "Waiting is derived from route frequency, which is why remote islands correctly resolve to days rather than hours."; spec `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md:183-207` (D7 "leave now", `E[wait] = headway/2` on every timetabled leg, rail `max(10 min, headway/2)`, ferries waited) and plan `docs/superpowers/plans/2026-09-03-transport-pipeline.md:20` ("expected wait for any timetabled leg is headway / 2").
  - Shipped numbers (Seoul, `dist/origins/seoul.bin`): St Helena **28.8 h** (one scheduled flight a week), Tristan da Cunha **105.8 h** (a ship roughly nine times a year), Easter Island 27.5 h. Half of all land is under 23.4 h from Seoul (p50).
- **Why it matters:** Transport geographer: the model is now "fastest-possible on rail and ferry, planned departure by air, hub-median connection wait". That is a coherent semantic, but it is not the one the page, `llms.txt`, spec and `calibration.toml:40-52` describe, and it makes the elaborate frequency model (and its "the whole map was nonsense" cautionary comment) nearly decorative: a weekly onward flight from a hub costs the hub's median wait (tens of minutes), and a weekly ferry costs 30 minutes. Journalist: "remote islands correctly resolve to days" is a claim the data contradicts.
- **Failure scenario:** A reader hovers St Helena, sees "28 h", checks the airline and finds one Saturday flight, and concludes the map is a best-case fantasy — the exact thing the spec's Goals (`spec:21`) promised not to publish.
- **Fix (modelling, not this cycle):** charge `headway/2` of the *onward route* on the connection (needs per-route wait on the flight edge for non-first legs — a two-node-per-airport graph can do this by charging the wait on `dep → arr` edges and giving the origin a wait-free "first departure" copy, or by keeping the current structure and charging `max(MCT, headway/2 of the destination route)` via per-route transfer nodes); give rail and ferry a documented per-class headway (the spec's 140/56 per week is a published-figure default). **Fix (copy, this cycle):** say what is true — "the first service is not waited for; a connecting flight waits the typical interval at that airport; rail and ferry connections are not waited for" — and remove the "remote islands resolve to days" sentence from `llms.txt` until it is. Put a one-line version of this under the legend, since the spec (`:269`) wants the semantic "stated plainly in the UI" and today it lives only inside the collapsed "Sources and method" panel.
- **Fits this cycle's brief:** copy yes; modelling no.

### CRIT-3 — The route panel's "Onward from X, of which:" lists surface minutes for the *whole* journey, so the parts exceed the figure they claim to break down on 84 % of air journeys

- **Severity:** High  **Confidence:** High  **Status:** Confirmed (measured on shipped Seoul data)
- **Where:**
  - `/Users/hletrd/flash-shared/transport-maps/web/app.js:516-526` `surface()` reads `hoverModes[i*6+k]`, and `:544-553` prints `Onward from <X>, of which:` followed by those parts.
  - `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/modes.py:64-88` — `acc[node] = acc[prev]` accumulates from the **origin**, so the array includes the drive/train to the departure airport (Seoul → ICN is 127 min at the `ICN dep` node, 70 of it processing).
  - Measured: of 81,626 Seoul hover cells reached by air, **68,794 (84.3 %)** have itemised surface minutes greater than `total − landed.min`. Worst case: onward from AJL = 60 min, "of which" 56 by rail + 73 by highway + 120 by major road = 249 min.
- **Why it matters:** Visitor: the panel visibly contradicts itself ("Onward 1 h, of which 4 h"). This is the one place the page shows its working, and the working does not add up.
- **Failure scenario:** Seoul → Paris: "To ICN, and through the airport 2 h 07" / "Fly ICN → CDG 12 h 10" / "Onward from CDG 1 h 05, of which: 1 h 30 by highway" — the highway minutes include the Incheon expressway.
- **Fix (bounded):** in `modes.py` start a fresh accumulator whenever `node` is an arrival-airport node (`first_arr <= node < first_stn`), so `.modes.bin` describes surface travel *after the last flight* — exactly what the panel labels it; for no-flight journeys nothing changes. Alternatively keep the array and relabel the rows "Surface travel on this journey, of which:" (weaker, but honest). Add a test that mutates the reset and goes red.
- **Fits this cycle's brief:** yes.

### CRIT-4 — Legend tick labels sit at true band boundaries but carry rounded values: "72+" is drawn at 67 h, "4" at 3 h 45, "48" at 50 h 20

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:132-143` — `SHOWN_HOURS = [1,2,4,8,16,24,48,72]`, a tick is placed on the *first* edge within 8 % of each round hour and labelled with the round hour. With `bandEdgesMin` from `index.json`: "2" at 125 min (+4.2 %), "4" at 225 min (−6.2 %), "8" at 465 (−3.1 %), "24" at 1470 (+2.1 %), "48" at 3020 (+4.9 %), and **"72+" at 4025 min = 67.1 h (−6.8 %)** because 4025 precedes the true 4320 edge and is inside the 8 % window, so the real 72 h boundary gets no tick.
- **Why it matters:** `CLAUDE.md:31-33` is explicit: ticks must sit at their true band boundaries because "evenly spaced labels would misstate the scale". These labels do the mirror image — true positions, false values — and the open-ended band is mislabelled by one whole band. A reader hovering the band under the "72+" tick is told "over 67 h" by the readout's band text (`app.js:591-594`) and "72+" by the legend.
- **Fix (bounded):** label the edge's real value (`f(mins/60)` as `bandRangeAt` already does), choose `SHOWN` edges by index rather than by nearest hour, and make the last label the true last edge (`EDGES.at(-1)`); or move the ladder so that 240, 480, 2880 are actual edges. Add a test in `tests/web/` that parses `SHOWN_HOURS`/edges and asserts each label equals its edge within 1 %.
- **Fits this cycle's brief:** yes.

### CRIT-5 — The live site sends no Content-Security-Policy, HSTS or X-Frame-Options on any HTML, JS, JSON, `.bin`, `.pmtiles` or `.woff2` response (nginx `add_header` inheritance), so the "strict CSP" the docs describe does not exist

- **Severity:** High  **Confidence:** High  **Status:** Confirmed (live headers)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/deploy/worldmap.atik.kr.conf:26-32` set the security headers at `server` level; `:42-71` then declare `add_header Cache-Control …` inside every `location` that serves a page asset. nginx replaces, not merges, inherited `add_header` directives when a block defines its own. Verified: `curl -sI https://worldmap.atik.kr/` returns `cache-control: no-cache` and nothing else; `/robots.txt` and a 404 (served by the bare `location /`) return the full CSP/HSTS/XFO set.
- **Why it matters:** Maintainer/security: `deploy/README.md:32-33` says "HSTS is set"; `web/README.md:8-10` and the conf's own comments describe a `script-src 'self'` CSP as the reason nothing external is loaded — none of it is in force. Ironically this is the *only* reason the Google tag (`index.html:5`) and the Nominatim calls (`app.js:776-842`) work at all: the documented CSP (`script-src 'self' blob:`, `connect-src 'self'`) would block both silently. Fixing the header bug without widening the CSP breaks address search and analytics with no console-visible error in production (`browser_verify.sh` would catch the address search).
- **Fix:** move the security headers into an `include security-headers.conf;` snippet and include it in every `location` that has its own `add_header`, or set `Cache-Control` via a `map $uri $cache` variable and a single server-level `add_header`. Decide deliberately whether GA and Nominatim stay (CRIT-13) and add `https://www.googletagmanager.com` / `https://nominatim.openstreetmap.org` to `script-src` / `connect-src` if so. Add `curl -sI …/index.html | grep -i content-security-policy` to `deploy_verify.sh` step 3.
- **Fits this cycle's brief:** no (bounded, but infrastructure).

### CRIT-6 — CC BY 4.0 data (GeoNames gazetteer, HydroLAKES) will ship without the attribution the licence requires, and the README already fails its own attribution test

- **Severity:** High  **Confidence:** High  **Status:** Likely (the local `dist/` is one deploy away; the live site still serves the older Natural Earth gazetteer)
- **Where:**
  - `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/index.py:59-70` adds GeoNames and HydroLAKES to `ATTRIBUTION`, but `dist/index.json` (local and live) was written by the previous `build-all` and carries only 7 entries. `web/app.js:145-147` renders credits **only** from `index.json`.
  - `dist/places.json` locally is the GeoNames `cities15000` build (34,135 rows; `emit/places.py:27`), i.e. CC BY 4.0 data already staged next to an `index.json` that does not credit it. `scripts/deploy_verify.sh:29-31` checks that `places.json` exists and prints the attribution names but does not require GeoNames when the gazetteer is GeoNames-shaped.
  - `tests/emit/test_index.py:76-83` `test_readme_documents_the_same_sources` **fails today**: `README.md` (`:48-56`) has no GeoNames or HydroLAKES row (run: `uv run pytest tests/emit/test_index.py` → "README.md omits GeoNames's licence").
  - `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:253-263` — the only way to regenerate `index.json` without a full build is the `index` subcommand, which also rewrites `hover_cells.bin` from a fresh `build_index()` at the *current* `SOLVE_RES` (6) — against the deployed res-5 origin arrays that is precisely the partial-dist mismatch `CLAUDE.md:68-69` forbids.
- **Why it matters:** Journalist/legal: a public site redistributing CC BY data without the credit is the kind of thing that gets a polite email and then a takedown. Maintainer: the attribution-refresh path is coupled to a file that must not change.
- **Fix:** add GeoNames and HydroLAKES rows to `README.md` (makes the suite green); split `cli.py index` into `index --json-only` (or have `write_index` runnable alone); make `deploy_verify.sh` fail when `places.json` has more than ~8,000 rows and `index.json` lacks a GeoNames entry, and when `water.pmtiles` carries `Lake_area` without a HydroLAKES entry. Once the page can, list credits with links (the `url` field is already shipped and unused by `app.js:145`).
- **Fits this cycle's brief:** partly (README row and credit links yes; CLI split no).

### CRIT-7 — The test suite is red and partly vacuous after the resolution-6/7 migration

- **Severity:** High  **Confidence:** High  **Status:** Confirmed (two failures reproduced; the rest by code reading)
- **Where:**
  - `tests/sources/test_landmask.py:14-16` asserts 500,000–620,000 cells; `config.SOLVE_RES = 6` yields **4,091,715** (reproduced: `uv run pytest tests/sources/test_landmask.py` → 1 failed).
  - `tests/emit/test_index.py:76-83` fails (CRIT-6).
  - `tests/graph/test_build.py:61-65` and `tests/graph/test_ground.py:24-29` call `h3.latlng_to_cell(…, 5)` then `idx.cell_index(...)` on a res-6/7 index → `KeyError`.
  - `tests/test_golden.py:28-29` `_minutes_at` uses `h3.latlng_to_cell(*latlon, config.SOLVE_RES)`; Seoul, Tokyo and London are urban cells that `graph/refine.py:28-31` splits into res-7 children, so the res-6 id is not in `_cell_pos` → `KeyError` in all four golden tests. `solve/dijkstra.py:23-29` already has the right helper (`idx.cell_at`).
  - `tests/emit/test_hover.py:23-27` `test_parent_cell_takes_the_minimum_of_its_children` asserts the semantic that `emit/hover.py:30-55` **replaced** (centre child, not minimum). It still passes only because its res-5 fixture cells never match `cell_to_center_child(parent, 6)` or `(…, 7)`, so `_representative_children` falls through to the fastest-child fallback. That is the vacuous-test pattern `CLAUDE.md:48-51` names.
  - `tests/graph/test_transfers.py:90-92` pins `STATION_ACCESS_MIN`/`STATION_EGRESS_MIN`, constants nothing uses (rail reads `calibration.toml [rail]`); `graph/transfers.py:5-9` and `:53-54` define them twice with a "Task 9 is blocked" comment.
- **Why it matters:** Maintainer: `README.md:32` says `uv run pytest`; it is not green, so a contributor cannot tell a regression from the baseline, and the one test that names the hover semantic asserts the wrong one.
- **Fix:** update the landmask bound (or make it resolution-aware), use `idx.cell_at`/`try_cell_index` in the res-hard-coded tests, rewrite `test_hover.py` with a res-6 fixture where centre and fastest children differ and assert the centre wins (then mutate `hover.py` to the min and confirm red), delete the duplicate `STATION_*` constants and their test, add the README rows. Run the whole suite and record the result in the PR.
- **Fits this cycle's brief:** no.

### CRIT-8 — The headline reading is for a different cell than the one highlighted: a res-4 parent's centre child (up to ~15 km away) versus the res-6/7 hexagon under the cursor

- **Severity:** High  **Confidence:** High  **Status:** Confirmed (by design; the code says so)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:334-342` outlines `h3.latLngToCell(lat, lon, SOLVE_RES)`; `:453-468` looks the time up by `HOVER_RES` (4, ~1,770 km² per cell); `:573-577` comments "the number can be optimistic against the colour it sits on … lets the readout say which band you are in rather than quietly contradicting it"; `src/transport_maps/emit/hover.py:30-55` reports the *centre* solve cell of each res-4 parent. With `SOLVE_RES` 6 the painted cells are 5.6 km (2.1 km where refined) and the readout stays one number across a 22 km hexagon.
- **Why it matters:** Visitor: the page draws a 5 km highlight, prints a 50 px number for a cell that may be three bands away, and appends a smaller "3.8–4.3 h" band note that disagrees with the big figure. The `app.js:30-33` comment says the highlight was made small so it would not "draw a hexagon seven times the size of anything the map was actually computed from" — but the number *is* computed from that larger footprint. With the finer grid the mismatch got worse, not better.
- **Failure scenario:** Hover Gimpo-side Seoul: colour band "1.0–1.2 h", big number "2 h 45" (the parent's centre child sits in the hills), highlight a single suburb hex. A reviewer screenshots it.
- **Fix (bounded, choose one):** (a) raise `HOVER_RES` to 5 — seven times finer, `.bin` ≈ 1.1 MB per origin before gzip (the nginx conf already gzips `.bin` at ~30 %), and the highlight can then honestly outline the res-5 cell; (b) keep res 4 but make the *band range* the primary figure when `bandRangeAt` disagrees with the array's band, showing the array value as "≈"; (c) at minimum outline the res-4 hexagon the number belongs to, with a caption "reading for this ~20 km cell". Whichever is chosen, say the cell size in the reading (`.at` line) so the precision claim is explicit.
- **Fits this cycle's brief:** yes (b and c are small; a is a config change plus a rebuild).

### CRIT-9 — The Route panel's instructions describe an interaction the page does not have ("Click the chart to drop an origin, then click again for a destination")

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/index.html:373-375`; `/Users/hletrd/flash-shared/transport-maps/web/app.js:689-698` — every map click sets `pinB` (the destination). An origin can only be changed via the list, an origin *label* (`:170-181`), or the "Depart from X" button that appears when the clicked point is within 80 km of a charted city (`:673-686`).
- **Why it matters:** Visitor: follow the text, click twice, and the first click is silently overwritten; the "snaps to the nearest charted city" sentence describes the optional button, not the click.
- **Fix:** "Click anywhere on the chart to set a destination. To depart from a different city, pick it from the list, click its name on the chart, or use *Depart from …* when your click lands near one." Also rename the panel's "From/To" rows consistently with "Departure" (CRIT-22).
- **Fits this cycle's brief:** yes.

### CRIT-10 — The legend has no key for the "no scheduled route" tone, which covers Antarctica, Arctic Canada and Siberia (9.8 % of Seoul's hover cells)

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:14-21` `UNCHARTED = "#4a4d50"`, painted by `bandColorExpression()` (`:368-372`); `paintLegend()` (`:122-127`) renders only the 37 band tints; `index.html:340-344`. Measured on `dist/origins/seoul.bin`: 8,916 of 90,659 hover cells are `65535` (7,745 in Antarctica, 1,171 elsewhere — clusters at 70°N/−120°E, 70°N/40°E, Papua).
- **Why it matters:** Visitor: a large grey continent and grey patches across the Arctic are the only colour on the globe the legend does not explain; the readout's "∞ no route" appears only on hover. Geographer: "no scheduled service" is a meaningful class and deserves a label.
- **Fix:** a small grey swatch after the ramp: "no scheduled route". Consider making `UNCHARTED` scheme-aware like `sea` (`:294-301`) so it reads as land, not water, under every scheme.
- **Fits this cycle's brief:** yes.

### CRIT-11 — "Open water." is shown for land whenever the time array is not (yet) available, and for any land cell absent from the mask

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:464-468` `lookup()` returns `null` both when `hoverTimes` is null (before the origin's `.bin` arrives, or after a fetch failure) and when `cellIndex < 0`; `:618-626` prints "Open water." for either. Islands finer than the 10 m coastline (25 airports' worth, `graph/nodes.py:29-35`) and every point during the first second after switching origin therefore read as sea.
- **Fix:** distinguish the two: "Loading …" while `hoverTimes === null`, "Not charted" for `cellIndex < 0` on land (e.g. when `queryRenderedFeatures` hits a band polygon or `water` returns nothing), "Open water." only when the water layer is under the cursor.
- **Fits this cycle's brief:** yes.

### CRIT-12 — `calibration.toml` does not label every constant as fitted or published-default, carries stale "refitted in Task 12/13" promises, and fitted ground constants live in code

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:**
  - `/Users/hletrd/flash-shared/transport-maps/calibration.toml:29-37` `[taxi_out_min]`/`[taxi_in_min]` — no comment at all; the header (`:7-8`) says only the *airborne* coefficients are fitted.
  - `:74-98` `[processing_min]`, `[disembark_min]`, `[border_min]`, `[connection_min]` — descriptive comments but no fitted/default label; `:95` "refitted in Task 12 from observed connections" never happened.
  - `:39-59` `[frequency]` — "Coefficients are refitted in Task 13 against observed frequencies" (never happened; `calibrate/fit.py:46-68` exists but no frequency data source does) and "Fitted to two real-world anchors: ICN-NRT … ICN-LHR" — which is the "handful of hand-picked routes" tuning `CLAUDE.md:42-44` warns against, documented rather than silent, so acceptable only if labelled as such.
  - `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/ground.py:25` `SPEED_BY_ROAD_CLASS_KMH` and `sources/urban.py:27-29` `URBAN_*` — fitted against 2,998 Google Routes journeys, well commented, but not in `calibration.toml` as `CLAUDE.md:40-41` requires ("Calibration constants live in calibration.toml").
- **Why it matters:** Journalist: the file is the auditable statement of what was measured and what was assumed; today a reader cannot tell taxi times (published figures) from cruise speed (fitted) without reading the plan document.
- **Fix:** one comment line per block: "PUBLISHED-FIGURE DEFAULT" or "FITTED against …"; delete the Task 12/13 promises or turn them into a "not yet fitted" note; move (or mirror) the ground speeds and urban factor into `calibration.toml` with their fit provenance; surface the label in `index.json`'s `modeDetail` (`emit/index.py:102-117` already says "fitted at 104 km/h").
- **Fits this cycle's brief:** yes (documentation).

### CRIT-13 — Google Analytics and Nominatim contradict the "self-contained, no runtime API calls, no third party" story told in three places, and nothing on the page discloses them

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/index.html:4-11` (gtag from `googletagmanager.com`; not on the live build yet); `web/app.js:776-842` (Nominatim search on every pause in typing ≥ 4 chars and reverse geocode on every map click — the clicked coordinates leave the site); vs `web/README.md:8-10` ("Nothing is fetched from a CDN at runtime … no third-party dependency"), `deploy/worldmap.atik.kr.conf:2` ("no runtime API calls"), spec `:14-15` ("The site makes no runtime API calls"). The only disclosure is the "Search by Nominatim" credit under results (`app.js:817-820`) and `llms.txt:58`; the Sources panel says nothing about analytics or geolocation.
- **Why it matters:** Journalist/visitor in the EU: analytics without notice, plus geolocation on load (CRIT-14), plus coordinates sent to a third party on click. Maintainer: three documents say the opposite of the code.
- **Fix:** decide, then make the docs and the CSP agree with the decision; add one sentence to the Sources panel ("Address search and click-to-address use OpenStreetMap Nominatim; your location, if you allow it, stays in the browser; the page uses Google Analytics."). If analytics stays, consider a cookieless setting or a self-hosted counter.
- **Fits this cycle's brief:** partly (the disclosure sentence).

### CRIT-14 — The geolocation permission prompt fires on page load with no user gesture

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:984-998`.
- **Why it matters:** Ease of use: a permission dialog before the globe has finished its first frame is the classic first-visit annoyance; Safari and Chrome increasingly suppress or auto-deny ungestured prompts, in which case the "Allow location to start from the city nearest you" line (`:982`) promises something that will not happen.
- **Fix:** replace with a "Use my location" button in the Departure panel (the `#here` line already exists to hold the result); keep the Seoul fallback.
- **Fits this cycle's brief:** yes.

### CRIT-15 — Verification scripts hard-code build facts, so the gates will either block the next build or be edited to pass

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/scripts/browser_verify.sh:18-19,41` (`"tints":37`, `"cities":157`, `"schemes":12`); `scripts/deploy_verify.sh` (no copy-vs-index check; step 2 `rsync web/ dist/` is undocumented in `deploy/README.md:6`, which shows only `rsync dist/`); `scripts/browser_verify.sh:15` checks the disclaimer text but not that the legend labels match `bandEdgesMin`.
- **Fix:** read `index.json` in the script and compare (`cities == origins.length`, `tints == bandEdgesMin.length + 1`); add the CRIT-1 copy check; document the two-step rsync in `deploy/README.md`.
- **Fits this cycle's brief:** partly.

### CRIT-16 — `web/README.md` and `deploy/README.md` describe a page that no longer exists

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/README.md:8-9` ("both font families" — only IBM Plex Sans is vendored, `web/vendor/fonts.css`), `:39-45` ("Eleven sequential steps of a single blue hue … 0.905 → 0.433 … deliberately one hue" — the page ships twelve multi-hue schemes, `app.js:41-59`, and `CLAUDE.md:21-27` forbids a single hue), `:32-33` (deploy list omits `llms.txt`, `robots.txt`, `sitemap.xml`, `preview.png`, `places.json`, `airports.json`, `borders.json`, `water.pmtiles`), `:8-10` (see CRIT-13). `deploy/README.md:6` (see CRIT-15), `:32` ("HSTS is set" — see CRIT-5).
- **Fix:** rewrite the Colour ramp section to point at `scripts/check_ramps.py` and the twelve schemes; list the real deploy set (or point at `deploy_verify.sh`); drop "both font families".
- **Fits this cycle's brief:** yes (docs).

### CRIT-17 — The design spec is still marked "Approved, pre-implementation" and promises things the code never did, while the code does things the spec does not mention

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md` — `:5` status; `:46,231-233` Google Routes TRANSIT for city↔airport legs (shipped: GRIP4 speed field + urban factor fitted on *driving* samples, `calibrate/ground.py`); `:47,275-278` S3/CloudFront (shipped: nginx); `:68,257` Vite + React 19 (shipped: one vanilla ES module — better, but undocumented); `:96,243` Protomaps basemap (none; there is no basemap at all, only DOM labels); `:141-152` speed table 85/60/40/25/5 (code: 104/57/50/18/25/5); `:164-171` rail 250/80 km/h, 140/56 per week, sinuosity 1.15 (code: 200/75, no frequency, 1.2); `:199-207` transfer table (none of those numbers survive); `:248-253` eleven bands (37); `:265` contour lines (a `band-seams` layer is referenced in `app.js:376,923-924` but never created); `:125` 548,557 res-5 cells (4.09 M res-6 plus refinement); `:203` air→air `max(MCT, headway/2)` (CRIT-2). Not in the spec: ferries as cell edges, closed borders and land-border charges (`sources/countries.py:35-53`), immigration zones, urban congestion factor, the mixed-resolution grid, the four-LOD band emission, the static water layer, GeoNames labels, Nominatim, the colour-scheme picker, the click-to-depart labels.
- **Why it matters:** Maintainer: the spec is the document a newcomer reads first; the plan (`docs/superpowers/plans/…`) has the same drift (res 5, 10 edges, `graph/ferry.py`, `emit/geojson.py`, `calibrate/fr24.py`, `transit.py`, none of which exist). `README.md:26` still says "travel times from any location".
- **Fix:** a short "As built (2026-09-10)" section at the top of the spec listing the deltas, and a status line; or move the decision log into `CLAUDE.md`-style standing policy and archive the rest.
- **Fits this cycle's brief:** no (docs, but not user-visible).

### CRIT-18 — On a phone the big reading may never update: "Tap the chart to read a passage" but `#time`/`#where` are only written in the `mousemove` handler

- **Severity:** Medium  **Confidence:** Medium  **Status:** Needs manual validation (designer agent: tap a land cell at 390×844 and check whether `#time` changes)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:959-960` sets the coarse-pointer hint; `:611-639` is the only writer of `#time`/`#where`; the `click` handler (`:689-698`) updates the Route panel's "Time" row but not the reading. Whether a tap produces a synthetic `mousemove` through MapLibre's touch handlers is browser-dependent; `scripts/browser_verify.sh:62-71` checks only that `#time` is *visible* at mobile sizes, not that a tap updates it.
- **Fix:** in the click handler call the same readout update (`lookup`, `fmtTime`, `bandRangeAt`, `describe`) and highlight the cell; then the hint is true on every device.
- **Fits this cycle's brief:** yes.

### CRIT-19 — The shipped coast layer is not the one the code and copy describe (zoom 11, no lakes), and no gate can tell

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (PMTiles metadata of local and live `water.pmtiles`: `maxzoom 11`, `fields {}`)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/water.py:33,121` (`MAX_ZOOM 12`, `--include=Lake_area`); `web/llms.txt:57` and `index.html:42` claim zoom 12 and HydroLAKES; `scripts/deploy_verify.sh:29-30` only checks the file exists; `CLAUDE.md:70-74` says the layer "is static and not produced by build-all", which is exactly why it silently lags the code.
- **Fix:** have `deploy_verify.sh` read the PMTiles header (`maxzoom`, `vector_layers[0].fields`) and compare with `emit/water.py`'s constants; stamp `GRID_VERSION`-style provenance into the tile metadata (`tippecanoe -A`/`--name`) so the page or the verifier can print which build it is.
- **Fits this cycle's brief:** partly (verification; the rebuild is a long job).

### CRIT-20 — The headline numeral asks for IBM Plex Sans 300, which is not vendored

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/index.html:136` `font-weight:300`; `web/vendor/fonts.css` declares 400, 500, 600 only.
- **Why it matters:** The 50 px light figure the design intends renders at 400; `CLAUDE.md:8-10` warns specifically about faces that silently fall back.
- **Fix:** vendor `ibm-plex-sans-latin-300-normal.woff2` and preload it, or set the weight to 400 on purpose.
- **Fits this cycle's brief:** yes.

### CRIT-21 — Stale comments and dead code that will mislead the next reader

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/app.js:376,923-924` (a `band-seams` layer that is removed and restyled but never added); `:29-34,573-577` (res-5/res-4, "takes the FASTEST of each cell's children" — `emit/hover.py` now takes the centre child); `:722` (157); `src/transport_maps/config.py:11,16` (548,557 res-5 cells; 82,983 res-4 cells — `hover_cells.bin` has 90,659 entries); `src/transport_maps/emit/itinerary.py:52-55` ("the hover value is a minimum over children"); `emit/routes_json.py:38-39` ("Rail nodes are added in Task 9 … nothing to emit"); `graph/transfers.py:5-9,53-54` (duplicate unused constants, "Task 9 is blocked"); `contour/bands.py:25` ("157 origins"); `validate.py:113` ("157 times in a full build"); `emit/tiles.py:9-13` (res-5 hexes); `cli.py:233-251` `solve` writes `dist/{name}.pmtiles|.hover.bin|.routes.json` in the dist *root* with names the page never reads and without `.air.bin`/`.modes.bin` — `rsync --delete dist/` would ship them.
- **Fix:** a comment sweep after the resolution change; delete the `band-seams` references or add the layer (the spec's contour lines); make `solve` write into `dist/origins/` with the same file set as `build-all`, or into a scratch directory.
- **Fits this cycle's brief:** partly.

### CRIT-22 — Terminology drifts across the page: passage / time / journey, departure / origin, chart / map / globe, hours / days

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/index.html:333,338,343,362,373,404-411` ("passage", "departure city", "chart", "origin", "reckoning"); `web/app.js:444-451` (`fmtTime` switches to "2 days 0h" above 48 h while the legend and the band note (`:594`) stay in hours — "over 67 h" next to "3 days 5h"); `app.js:663` "Time" row; `:658` "From/To"; `index.html:329` aria-label "map"; `noscript` "map"; README "chart"/"map". "Charted city", "departure city", "origin", "the city nearest you" all name the same thing.
- **Fix:** pick one register — the Galton "chart/passage/departure" voice is distinctive; use it everywhere including `aria-label`s and the Route panel — and keep a single unit rule (hours to 72 h, then "3 d 5 h" *and* keep the legend's "72+" consistent with it). Drop "0h" when the remainder is zero.
- **Fits this cycle's brief:** yes.

### CRIT-23 — The legend, tooltips and map are not exposed to assistive technology

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/index.html:329` (`<div id="map" role="img">` for an interactive control that also receives keyboard input via MapLibre); `:340-344` + `app.js:122-143` (37 empty `span`s and eight absolutely positioned labels with no accessible name — a screen reader hears "1 2 4 8 16 24 48 72"); `index.html:239-245` + `app.js:504-511` (airport/mode explanations are `::after` pseudo-elements on `tabindex="0"` spans — focusable, but the text is not in the accessibility tree); `:351` compass is fine; `#time` updates are not announced.
- **Fix:** `role="application"` + label on the map; `aria-label="Travel time in hours from the departure city, door to door: 0–30 min … over 72 h"` on `.legend` and `aria-hidden` on the tints; use `title` or `aria-describedby` + a visually hidden element for the airport/mode explanations; `aria-live="polite"` on `.reading` (throttled — the value already updates once per animation frame).
- **Fits this cycle's brief:** yes.

### CRIT-24 — `cli.py solve` and `index` are inconsistent with `build-all` and can corrupt a deployable `dist/`

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:233-263` (see CRIT-6 and CRIT-21).
- **Fix:** see CRIT-6 (split `index`) and CRIT-21 (`solve` output set and location).
- **Fits this cycle's brief:** no.

### CRIT-25 — The golden tests are too loose to notice a factor-of-two error

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/tests/test_golden.py:32-44` — Seoul→Tokyo anywhere in 2–12 h (shipped: 5.3 h), Seoul→London < 48 h (shipped: 15.2 h); the docstring says "tighten as real modes land" and they never were. Spec `:299-301` also names a remote Pacific island pair that was never written.
- **Fix:** ±35 % around the shipped values, plus one island case (e.g. Seoul→Majuro) so CRIT-2-style wait regressions are visible.
- **Fits this cycle's brief:** no.

### CRIT-26 — The JSON-LD declares the whole dataset ODbL while its inputs include CC BY-SA (Wikipedia) and CC BY (GeoNames, HydroLAKES) material

- **Severity:** Low  **Confidence:** Low  **Status:** Needs manual validation
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/index.html:55` `"license": "https://opendatacommons.org/licenses/odbl/1-0/"`; `README.md:42-46`; `emit/index.py:13-21`.
- **Why it matters:** The route *facts* extracted from Wikipedia are probably not protected expression, and the derivative-database question for ODbL inputs is settled by attribution + share-alike, but the page is making a single-licence claim about a compilation with four licence families. Worth a deliberate decision and a sentence saying which parts are under what.
- **Fix:** state the licence per component (or "see attribution") rather than one URL; if the author wants a single licence, check CC BY-SA 4.0 compatibility.
- **Fits this cycle's brief:** no.

---

## Final sweep

- **Terminology drift:** see CRIT-22. Additional: "cell" (code, `bandRangeAt`) vs "hexagon"/"hex" (`CLAUDE.md`, comments) vs nothing in the UI — the reading never tells the visitor what area the number covers (CRIT-8). "Departure" (panel) / "origin" (Route hint, code, `index.json`) / "charted city" (Route hint, geolocation line). "Minutes" appear only below 1 h; "h 05m" style otherwise; days above 48 h — while the legend and band note stay in hours.
- **Stale numbers in docs:** 553 vs 157 (CRIT-1); 548,557 / 82,983 / res 5 (`config.py`, plan, spec, `llms.txt:22`, `validate.py:194-200`); "Coverage is about 98 % of land" (`llms.txt:33`) — measured non-Antarctic unreachable is 1.4 % of *hover* cells for Seoul, so ~98.6 %, fine, but it is stated for every origin; "2,998 real driving journeys" (JSON-LD, `llms.txt`) vs "1,495" (commit `61af840`) vs "1,383"/"112" (`ground.py:17-25`, `urban.py:4-7`, `ground_check.py:5`) — three different sample sizes for the same fit; MapLibre "5.24" badge in README vs `web/README.md` table (consistent); `sitemap.xml`/JSON-LD `dateModified` 2026-09-10 for a live build from 2026-09-09.
- **Copy that contradicts behaviour:** CRIT-2 ("onward connections are [waited for]"), CRIT-9 (click to drop an origin), CRIT-11 ("Open water." on land), CRIT-13 ("no runtime API calls"), CRIT-18 ("Tap the chart"), `app.js:982` "Allow location to start from the city nearest you" (CRIT-14), `README.md:26` "from any location".
- **Features referenced in one place and absent in another:** contour lines / `band-seams` (spec, `app.js`) — absent; rail detail files (`llms.txt:59`, `cli.py:102`) — absent from `dist/`; `modeDetail` / `fineRes` (`emit/index.py:124-128`) — absent from the shipped `index.json` (the page degrades gracefully); HydroLAKES lakes (copy, attribution) — absent from `water.pmtiles` (CRIT-19); Google Routes TRANSIT access table (spec Task 13) — never built; `graph/ferry.py`, `emit/geojson.py`, `calibrate/fr24.py|transit.py` (plan) — never existed; STATION_ACCESS constants (`transfers.py`) — defined, tested, unused.
- **Legend accessibility:** CRIT-23; also no "0" label at the left end and nothing under 1 h although the first five bands (0–60 min) are the ones a city-dweller reads most.
- **Disclaimer wording:** present in `noscript` (`index.html:425-426`) and `llms.txt:51` and checked by `browser_verify.sh:15` ("For reference only") — but the rendered page's Sources panel (`index.html:403-414`) contains **no** disclaimer at all; the `#key .disclaimer` CSS rule (`:273-274`) styles an element that does not exist. The verification passes only because `noscript` text is in `document.body.textContent`. So the disclaimer the script certifies is one no JavaScript-enabled visitor can see. Fits the brief: add the two sentences to the Sources panel.
- **Design policy check (`CLAUDE.md`):** IBM Plex Sans only ✓ (`fonts.css`); no `letter-spacing`, `text-transform: uppercase`, or `tabular-nums` anywhere in `index.html`/`app.js` ✓; dark ground ✓; ramps measured by `scripts/check_ramps.py` and enforced by `tests/web/test_ramps.py` ✓ (all 12 pass); hexagons unrounded ✓ (`contour/bands.py`); legend always visible ✓ but ticks mislabelled (CRIT-4); weight 300 not vendored (CRIT-20).
- **Modelling rules check:** door-to-door stated on the legend ✓ and in the Sources panel ✓, but not on the cursor tooltip (`app.js:631`) or the Route panel's "Time" row; calibration labelling incomplete (CRIT-12).
- **Deploy rules check:** `deploy_verify.sh` + `browser_verify.sh` exist and open the page ✓; partial-dist protection exists for arrays but not for copy, coast layer, or attribution (CRIT-1, CRIT-6, CRIT-15, CRIT-19); nginx header inheritance bug (CRIT-5).
- **Things that are good and should not be touched:** the split departure/arrival airport nodes; the closed-border and immigration-zone handling; `_refuse_partial` and the cache stamping; the four-LOD band emission with whole-cell rims; `check_bands_cover`; the OKLab-interpolated, measured colour schemes; the gazetteer-as-DOM-labels approach; the forked build with COW graph.

---

## Coverage

Every tracked file outside `web/vendor/` was opened and read in full unless noted.

- Policy/docs: `CLAUDE.md`, `README.md`, `web/README.md`, `deploy/README.md`, `deploy/worldmap.atik.kr.conf`, `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md`, `docs/superpowers/plans/2026-09-03-transport-pipeline.md` (all 15 tasks; Task 12's code blocks skimmed).
- Config/data: `pyproject.toml`, `.python-version`, `.gitignore`, `calibration.toml`, `data/origins.toml` (first 316 lines read; 553 entries counted, 0 duplicate slugs), `uv.lock` (not read — lockfile).
- Web: `web/index.html`, `web/app.js` (all 999 lines), `web/llms.txt`, `web/robots.txt`, `web/sitemap.xml`, `web/vendor/fonts.css`, `web/vendor/` listing, `web/preview.png` (dimensions only: 1200×630 as declared). Vendored libraries (`maplibre-gl.js`, `pmtiles.js`, `h3.js`, `fflate.js`, `maplibre-gl.css`) not reviewed — third-party.
- Pipeline (`src/transport_maps/`): `__init__.py`, `cli.py`, `config.py`, `validate.py`; `calibrate/{__init__,fit,ground}.py`; `contour/{__init__,bands,grid}.py`; `emit/{__init__,airports_json,borders,hover,index,itinerary,modes,places,rail_detail,routes_json,tiles,water}.py`; `graph/{__init__,air,build,ground,nodes,rail,refine,transfers}.py`; `solve/{__init__,dijkstra}.py`; `sources/{__init__,_utils,airports,countries,landmask,osm,roads,routes,urban,wikidata}.py`.
- Scripts: `adsb_extract.py`, `browser_verify.sh`, `build_water_tiles.py`, `calibrate_ground.py`, `check_ramps.py`, `deploy_verify.sh`, `expand_origins.py`, `ground_check.py`, `osm_rail.sh`.
- Tests: `test_cli.py`, `test_config.py`, `test_golden.py`, `test_licence_firewall.py`, `test_validate.py`; `calibrate/{__init__,test_fit,test_ground}.py`; `cli/test_entrypoint.py`; `contour/{__init__,test_bands,test_grid,test_native_grid}.py`; `emit/{__init__,test_hover,test_index,test_itinerary,test_modes,test_rail_detail,test_routes_json,test_tiles}.py`; `graph/{__init__,test_air,test_build,test_ferry,test_ground,test_nodes,test_rail,test_rail_integration,test_refine,test_transfers}.py`; `solve/{__init__,test_dijkstra}.py`; `sources/{__init__,test_airports,test_cache_provenance,test_countries,test_landmask,test_osm,test_roads,test_routes,test_urban,test_wikidata}.py`; `web/test_ramps.py`; `fixtures/icn_wikitext.txt` (head only).
- Artifacts inspected read-only: `dist/index.json`, `dist/places.json`, `dist/airports.json`, `dist/hover_cells.bin`, `dist/origins/seoul.{bin,air.bin,modes.bin,json}`, `dist/water.pmtiles` header/metadata, `data/build/land_cells_r6_dd95e3b5.parquet` (row count), the live `index.json`, `index.html`, `llms.txt`, `places.json`, `water.pmtiles` metadata and response headers, and the local preview's `index.json`/`index.html`.
- Tests executed (data-free or cache-hit only; nothing written under `dist/` or `data/`): `tests/emit/test_index.py` (1 failure), `tests/emit/test_hover.py`, `tests/test_config.py`, `tests/web/test_ramps.py`, `tests/emit/test_modes.py`, `tests/emit/test_itinerary.py`, `tests/graph/test_air.py`, `tests/graph/test_transfers.py`, `tests/calibrate/`, `tests/emit/test_routes_json.py`, `tests/emit/test_rail_detail.py`, `tests/sources/test_landmask.py` (1 failure). No build, deploy or browser automation was run.
