> Status column is a snapshot at `edf4b0d`; HEAD status is tracked in `plan/*.md` (cycle 2 moved every finished item to `plan/archive/`).

# Aggregate review — transport-maps, cycle 1

Reviewed tree: `feat/transport-pipeline` at `ac191db` (working tree clean at fan-out).
While the reviews ran another agent pushed `7b7e601` (import numpy in `graph/nodes.py`)
and `edf4b0d` (pass the station maps by keyword), which close the two Critical
build-breakers below; everything else is open at HEAD `edf4b0d`.

Twelve reviewers ran in parallel and returned: code-reviewer (CR, 32), perf-reviewer
(PR, 23), security-reviewer (SEC, 17), critic (CRIT, 26), verifier (VER, 23),
test-engineer (TE, 26), tracer (TR, 20), architect (ARCH, 23), debugger (DBG, 20),
document-specialist (DOC, 28), designer (UX, 23), feature-dev:code-reviewer (FD, 8).
**269 raw findings**, merged below into **96 distinct findings**. Per-agent files sit
beside this one for provenance; this file keeps the highest severity and confidence
any agent assigned to a merged item and lists every contributing ID so the detail
can be found.

Gate evidence gathered during the review (verifier, test-engineer, re-checked by
the aggregator at `edf4b0d`):

| Gate | Result at `ac191db` | Result at `edf4b0d` |
|---|---|---|
| `uv run ruff check .` | 46 errors (6 × F821 `np`) | **40 errors**, 18 auto-fixable |
| `uv run pytest -q -k "not real_multi_band"` | 22 failed, 199 passed, 21 errors (41 of 43 red = missing numpy import) | not yet re-run; the two non-numpy failures (`test_landmask` count bound, `test_index` README attribution) are still expected red |
| `scripts/check_ramps.py` | 12/12 anchors OK (ΔE 6.5–8.9, monotonic); interpolated bands ΔE 1.8–2.7 | unchanged |

Severity legend: C = Critical, H = High, M = Medium, L = Low. "Agents" counts the
reviewers that independently flagged the same defect — the strongest signal in
this document.

## AGENT FAILURES

None. All twelve reviewers returned on the first attempt. Note: the OMC agent
types named in the brief (code-reviewer, perf-reviewer, …) are not registered in
this environment; each role was run as a `general-purpose` agent with the role's
brief, plus the registered `feature-dev:code-reviewer` (read-only tools, so its
review was saved by the aggregator verbatim).

---

## A. Build-breaking and pipeline correctness

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| A1 | `graph/nodes.py` uses `np` without importing numpy; nothing builds, 41 tests red | C | H | 8 | CR-1 PR-2 VER-1 TE-1 TR-1 ARCH-1 DBG-1 FD-2 | `nodes.py:61-62,124` | **Fixed** by `7b7e601` (other agent) |
| A2 | `build_index` passes station maps positionally into the new `base_cells`/`base_index` slots → `TypeError` | C | H | 3 | VER-2 FD-1 TE-1 | `nodes.py:184-187` | **Fixed** by `edf4b0d` (other agent) |
| A3 | `raise SystemExit` from the coverage gate inside a forked `Pool.imap` worker is never delivered; `build-all` hangs forever instead of aborting (reproduced by 4 agents; 8 idle `transport_maps.cli` processes on this host match the signature) | C | H | 6 | CR-3 PR-1 VER-3 TE-2 TR-3 DBG-2 | `cli.py:83-88,109-112,187-191` | Open |
| A4 | Ferry between a res-7 cell and its adjacent unsplit res-6 neighbour is not recognised as ground-adjacent (`grid_disk` at one resolution), duplicates the `hex_edges` cross edge, and `build_graph` refuses the whole graph | H | H | 4 | CR-12 VER-4 TR-2 DBG-3 | `build.py:301-307` vs `ground.py:115-130`, `build.py:381-386` | Open |
| A5 | `urban._places()` calls `emit.places._download()` with no `url` (signature changed; also the wrong dataset); fresh-cache build crashes; reversed layer (`sources` → `emit`) | H | H | 4 | CR-4 VER-5 ARCH-2 DBG-5 | `urban.py:34-46`, `emit/places.py:35` | Open |
| A6 | `dist/` is a mixed build during every run and after every abort: `hover_cells.bin` written before any origin, per-origin `.bin/.json` written non-atomically, `Pool.terminate()` kills siblings mid-write, no resume, no build identity, and `rsync --delete` deploys in place | H | H | 8 | TR-4 PR-8 DBG-4 DBG-11 CR-16 CR-25 ARCH-7 SEC-7 | `cli.py:174,182-191`; `hover.py:71-72`, `itinerary.py:70-71`, `modes.py:109-110`, `rail_detail.py:90-93`, `routes_json.py:53-54`; `deploy_verify.sh:40-41` | Open |
| A7 | `solve` and `index` subcommands write a different layout, skip every gate, and `index` can publish an `index.json` for origins with no files | M | H | 6 | CR-22 ARCH-6 TR-11 TR-18 VER-16 CRIT-24 | `cli.py:233-263` | Open |
| A8 | `check_coverage` returns NaN on an all-excluded universe and NaN passes the `<` gate | L | H | 1 | DBG-12 | `validate.py:33-39`, `cli.py:84` | Open |
| A9 | South-pole cap (`_pole_cells`) dissolves into planar garbage after antimeridian unwrap; `check_bands_cover`'s fixed-seed sample can abort a build | M | M | 1 | DBG-8 | `landmask.py:135-144,217`, `bands.py:62-85` | Needs manual validation |
| A10 | `osm.rail_routes` cross-extract dedupe uses an unstable sort with no secondary key | M | M | 2 | CR-17 DBG-18 | `osm.py:202-207` | Likely |
| A11 | A wikitext batch that triggers `continue` can never be resolved → permanent `_refuse_partial` | M | M | 1 | CR-18 | `routes.py` (crawl) | Needs manual validation |
| A12 | Ferry crossings dropped silently and unbounded; ferry minutes booked as road when the two base parents are adjacent | L | H | 2 | TR-12 TR-13 | `build.py:279-334`, `modes.py` | Open |
| A13 | Times above 65,534 min display as a real duration, not "no route" (latent; Seoul max 16,676) | L | H | 1 | TR-14 | `hover.py:67-69`, `app.js` | Open |
| A14 | Monotonic-ground gate is blind to cross-resolution edges | L | H | 1 | TR-19 | `validate.py` | Open |
| A15 | Immigration-zone rules incomplete and inconsistent between air and ground; border control charged on transits | M | H | 2 | CR-20 TR-17 | `build.py:88-93`, `countries.py` | Open (model) |
| A16 | `check_bands_cover` validates the GeoJSON, not the tiles tippecanoe ships | M | M | 1 | CR-21 | `validate.py`, `tiles.py` | Needs manual validation |
| A17 | Origin slugs from `origins.toml` unvalidated on the `build-all` path; `expand_origins.py` writes third-party names into TOML unescaped | L | H | 1 | SEC-12 | `cli.py:26-34`, `index.py:81-88`, `expand_origins.py:94-99` | Open |
| A18 | `adsb_extract.py` builds a cache path from an upstream tag name and downloads without bounds | L | H | 1 | SEC-13 | `adsb_extract.py:103-115,143-147` | Open |

## B. Modelling semantics

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| B1 | The expected-wait model is bypassed: `arr → cell → dep` (disembark + processing) is cheaper than the connection edge at small/medium airports, so Dijkstra never pays headway; route frequency never affects a journey; rail and ferry carry no headway at all — contradicting the spec, the page copy and "leave now" | H | H | 4 | CR-2 CRIT-2 ARCH-17 CR-19 | `build.py:163-213,232-334`, `air.py`, `calibration.toml`, `index.html:406-407` | Open (model change; copy half is bounded) |
| B2 | Calibration provenance: six `calibration.toml` tables lack the fitted-vs-published label CLAUDE.md requires, two claim refits that never happened, fitted ground speeds/urban factor live in code (non-monotonic in road grade), and `mode_detail()`/`index.py` hard-code figures the file owns | H | H | 6 | DOC-8 ARCH-8 CRIT-12 CR-13 CR-14 DBG-14 | `calibration.toml`, `ground.py:28-34`, `emit/index.py:110-112`, `air.py:29-45`, `rail.py:44-54` | Open |
| B3 | Golden tests are too loose to notice a factor-of-two error | L | H | 1 | CRIT-25 | `tests/test_golden.py:32-44` | Open |

## C. Page data and route correctness (user-visible)

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| C1 | Route panel loses every flight before a surface transfer between airports and mislabels the remainder ("To JAV, and through the airport: 20h53m"); 33.5 % of Seoul air itineraries | H | H | 3 | CR-7 TR-6 DBG-6 | `app.js:473-489,537`, `routes_json.py:31-39` | Open |
| C2 | "Onward from X, of which:" itemises the *whole journey's* surface minutes; parts exceed the header on 84.3 % of air-reached Seoul cells | H | H | 3 | CR-8 CRIT-3 TR-5 | `modes.py:71`, `app.js` route summary | Open |
| C3 | Hover value, highlighted hexagon and painted band come from three different cells; the outline is the res-6 parent even where the surface was solved at res 7 (`fineRes` shipped, unused) | H | H | 5 | CRIT-8 CR-9 ARCH-16 DBG-16 TR-15 | `app.js:34-35,334-342,453-468,573-577` | Open |
| C4 | Legend tick labels are rounded onto the wrong edges: "72+" drawn at 67 h although an exact 72 h edge exists, "4" at 3 h 45, "48" at 50 h 20; "48"/"72+" collide into "4872+" at 1280 px — the misstatement CLAUDE.md's legend rule forbids | H | H | 5 | CRIT-4 UX-5 CR-10 TR-7 VER-19 | `app.js:129-143` | Open |
| C5 | Origin-switch race: four of five per-origin fetches never check `active === o`; a slow city overwrites the newer one's arrays | M | H | 3 | CR-11 ARCH-10 DBG-7 | `app.js:396-431` | Open |
| C6 | Unreachable / "no scheduled route" grey (`#4a4d50`, 9.8 % of Seoul hover cells) has no legend entry | M | H | 2 | CRIT-10 UX-10 | `app.js:14-21,122-127,368-372`, `index.html:340-344` | Open |
| C7 | "Open water." is shown for land whenever the time array is not yet loaded, after a fetch failure, or for a land cell absent from the mask | M | H | 1 | CRIT-11 | `app.js:464-468,618-626` | Open |
| C8 | Hover minutes are truncated (`astype u2`) while `routes.json` minutes are rounded; totals can disagree by a minute; unit presentation inconsistent | L | H | 3 | DBG-13 VER-22 CR-24 | `hover.py:67-69`, `routes_json.py:27`, `modes.py:108` | Open |
| C9 | No failure UI for the two top-level awaits: a 404 or odd-length `hover_cells.bin` is a blank globe with a `RangeError` | L | H | 2 | DBG-15 SEC-11 | `app.js:27,38-40` | Open |
| C10 | Geolocation permission prompt fires on page load with no user gesture; the deferred `flyTo` can hijack the next gesture; first visit downloads two origins | M | H | 4 | CRIT-14 SEC-14 DBG-17 PR-19 | `app.js:956-998` | Open |
| C11 | Airport search offers airports the graph dropped; the picker shows indistinguishable duplicate names | L | H | 1 | CR-31 CR-28 | `app.js` search | Open |
| C12 | Mode tooltips never render because the served `index.json` has no `modeDetail`; `.rail.bin`/`.rail.json` 404 twice per origin | M | H | 1 | UX-11 | `app.js:396-401,508-511,646-653` | Open (dist staleness; page needs a fallback) |
| C13 | On phones: a tap with the sheet folded opens the Route panel inside the hidden sheet (nothing visible happens); folding the sheet hides the legend (CLAUDE.md "always visible"); the big reading may never update on tap | M | H | 3 | UX-9 VER-11 CRIT-18 | `app.js:689-698,932-960`, `index.html:310-317` | Open |

## D. Page design, ease of use, accessibility

| # | Finding | Sev | Conf | Agents | IDs | Where | Effort |
|---|---|---|---|---|---|---|---|
| D1 | Invalid `font: 400 13px/1.4 inherit` shorthands are dropped, so the search box, city list, scheme picker, Clear button and address results render in Arial/system-ui instead of IBM Plex Sans (CLAUDE.md typeface rule) | H | H | 1 | UX-1 | `index.html:181,189,208,251` | S |
| D2 | Globe place labels inherit MapLibre's Helvetica Neue; origin-city labels have no text shadow (1.07:1–2.5:1 on bright bands); only the `latin` Plex subset is vendored | H | H | 1 | UX-2 UX-20 | `index.html:226-231`, `app.js:160-186`, `vendor/fonts.css` | S |
| D3 | Opening view has zero city names (label budget 0 below zoom 2.2, `flyTo` lands at 1.9) while the first line of copy says "Click a city name to depart from it" | H | H | 1 | UX-3 | `app.js:189,433`, `index.html:338` | S |
| D4 | Enter in the search box does nothing; the city list is 157 tab stops with no arrow-key navigation; ramp picker and results lack widget semantics; `#map` is `role="img"` with buttons inside; no live region | H | H | 2 | UX-4 UX-18 CRIT-23 | `app.js:870,728-770,893-908`, `index.html:329,336-347,365-366,396` | S |
| D5 | Route panel copy describes a click model the code does not implement ("Click the chart to drop an origin, then click again") | M | H | 3 | CRIT-9 UX-6 DOC-13 | `index.html:373-375`, `app.js:689-698` | S |
| D6 | `--text-3` (#6f757e) fails AA everywhere (3.9:1), down to 2.0:1 on the readout scrim over bright bands | M | H | 1 | UX-7 | `index.html:85,132,147-151,160,186,193,236-237,248,272` | S |
| D7 | Focus is invisible on the search box; `.ap`/`.mode`/origin labels remove the outline | M | H | 1 | UX-8 | `index.html:189,191,231,245` | S |
| D8 | Empty and failed search states are silent (no "no matches", no Nominatim error) | M | H | 1 | UX-12 | `app.js:728-770,778-842` | S |
| D9 | No `color-scheme: dark`: native controls and scrollbars render light | M | H | 1 | UX-13 | `index.html:82-87` | S |
| D10 | No `prefers-reduced-motion` handling: every origin change, address pick and geolocation is a 1–3 s `flyTo` arc | M | H | 1 | UX-14 | `app.js:433,848,858,875,994` | S |
| D11 | Two blocks headed "Route" with different content on screen at once; the time is shown three times | L | H | 1 | UX-15 | `index.html:370-379`, `app.js:556-561,655-672` | S |
| D12 | "Door to door" is asserted at the legend but explained only inside a closed panel, and not stated at the tooltip, the Route "Time" row or the meta descriptions | L | H | 2 | UX-16 DOC-23 | `index.html:331-334,343,403-414`, `app.js:556` | S |
| D13 | Start-up serialises map creation behind `index.json` → 725 KB `hover_cells.bin`; every origin switch eagerly fetches ~2 MB of leg data only needed after a click; 45 requests / 8.4 MB first load | H | H | 2 | PR-9 UX-17 | `app.js:27,38-40,252-267,396-431` | S (reorder) / M (lazy) |
| D14 | The only disclaimer is inside `<noscript>`; the visible page has none; `browser_verify.sh` certifies the noscript text and never asserts `borders`/`disclaimer` | M | H | 3 | UX-19 FD-5 CRIT (sweep) | `index.html:273-274,403-414,425-426`, `browser_verify.sh:12-19` | S |
| D15 | Airport-code and mode tooltips can be clipped by the scrolling `#legs` box (3 px margin) | L | M | 1 | UX-21 | `index.html:154-156,239-244` | S |
| D16 | Target sizes: city rows 23 px, scheme rows 23 px, sheet handle 22 px, checkboxes 15 px (WCAG 2.2 2.5.8 wants 24) | L | H | 1 | UX-22 | `index.html:182,208,311-315` | S |
| D17 | Seven unlabelled `console.error("Error")` entries on a clean load, five per origin switch | L | L | 1 | UX-23 | unknown | S |
| D18 | Headline numeral asks for IBM Plex Sans 300, which is not vendored (400/500/600 only) | L | H | 2 | CR-27 CRIT-20 | `index.html:136`, `vendor/fonts.css` | S |
| D19 | Terminology drift: passage / time / journey, departure / origin, chart / map / globe, hours vs "2 days 0h"; archaic diction ("reckoned") | L | H | 2 | CRIT-22 DOC-24 | `index.html:333-411`, `app.js:444-451,594` | S |
| D20 | Separation threshold is stated as 8 in `app.js` and 6 in CLAUDE.md/`check_ramps`; the 37 interpolated bands measure ΔE 1.8–2.7 (only the anchors are measured) | L | H | 3 | DOC-21 VER-15 TE-20 | `app.js:5-12,42-46,90-97`, `check_ramps.py` | S (docs) |

## E. Copy, docs and data drift

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| E1 | The page, README and llms.txt describe a 553-city, res-6/7, 37-band, HydroLAKES, station-naming build; the served `index.json` (local and live) has 157 origins at res 5 with no `modeDetail`; `browser_verify.sh` hard-codes 157 cities / 37 swatches / 12 schemes, so it will block the correct 553-origin deploy; `deploy_verify.sh` never checks copy against `index.json` | C | H | 11 | CRIT-1 DOC-4 DOC-5 VER-7 TR-8 ARCH-4 DBG-9 SEC-15 CRIT-15 DOC-14 TE-6 | `index.html:15,23,31,41-42,375,421`, `llms.txt:3`, `README.md:5`, `app.js:722`, `browser_verify.sh:18-19,41`, `deploy_verify.sh` | Open (553-origin rebuild in progress elsewhere) |
| E2 | GeoNames gazetteer and HydroLAKES (both CC BY 4.0) ship without attribution in README, llms.txt, noscript or JSON-LD; `test_readme_documents_the_same_sources` is red; MapLibre's attribution control is hidden so credits need a closed panel; JSON-LD licences the whole dataset ODbL alone | C | H | 8 | DOC-1 CRIT-6 VER-9 TE-8 DOC-15 CRIT-26 DOC-17 VER-23 SEC-17 | `README.md:48-56`, `emit/index.py:59-70`, `index.html:55,97`, `llms.txt` | Open |
| E3 | nginx `add_header` inheritance drops CSP/HSTS/nosniff/XFO on every response served by a `location` that sets `Cache-Control` (all of them; confirmed live); the CSP as written (`connect-src 'self'`, `script-src 'self' blob:`) would block Nominatim and the Google tag | H | H | 7 | SEC-1 CR-5 CRIT-5 DOC-2 VER-6 ARCH-12 SEC-2 | `deploy/worldmap.atik.kr.conf:26-32,42-71`, `index.html:4-11`, `app.js:773-842` | Open (infra) |
| E4 | Search-as-you-type against public Nominatim is autocomplete, which the OSMF usage policy prohibits; the code comment claims compliance; reverse-geocoded labels carry no attribution; Google Analytics and Nominatim contradict the "no runtime API calls, no third party" statements in three places with no disclosure | H | H | 4 | SEC-5 DOC-3 CRIT-13 SEC-6 | `app.js:754-783`, `index.html:4-11`, `web/README.md:6-10` | Open |
| E5 | `web/llms.txt` contradicts itself (11 bands / 548,557 res-5 cells / "rail not yet in the graph" vs res 6/7 further down) | H | H | 3 | DOC-6 VER-12 ARCH-11 | `llms.txt:13,22,31,53-59` | Open |
| E6 | README "Development" cannot produce the artifact `deploy_verify.sh` requires: `places.json`, `airports.json`, `borders.json` have no producing stage anywhere (zero callers) and the water build is a separate script | H | H | 2 | DOC-7 ARCH-5 | `README.md:28-40`, `emit/{places,airports_json,borders}.py`, `deploy_verify.sh:29-30` | Open |
| E7 | `web/README.md` stale in five statements ("both font families", "eleven steps of a single blue hue", "no third-party dependency"); `deploy/README.md` omits the web→dist copy step and the uncached asset classes; MapLibre 6 warning cites a symptom | M | H | 4 | DOC-12 CRIT-16 DOC-22 DOC-27 | `web/README.md:6-45`, `deploy/README.md:3-6` | Open |
| E8 | Cell-size figures throughout use pre-H3-v4 edge lengths and are ~15 % too small | M | H | 1 | DOC-9 | multiple docs and comments | Open |
| E9 | Stale comments and dead constants: "11th band is open-ended" (37 bands), res-5 language in `config.py`/`hover.py`/`modes.py`/`itinerary.py`/`app.js` (`solveRes ?? 5`), "takes the FASTEST child", `band-seams` layer never added, `STATION_ACCESS_MIN` defined twice and unused, `__init__.main()` stub, `routes_json.py` "Task 9" comment | L | H | 10 | DOC-10 DOC-11 DOC-20 FD-6 FD-7 FD-8 CR-26 CRIT-21 TR-20 DBG-20 VER-17 ARCH-19 ARCH-20 TE-21 | `config.py:11,19-24`, `hover.py:7`, `modes.py:95`, `itinerary.py:51`, `app.js:29-34,376,573-577,923-924`, `transfers.py:5-9,53-54`, `__init__.py` | Open |
| E10 | Spec still "Approved, pre-implementation" and promises Google Routes TRANSIT; plan has 0 of 118 checkboxes ticked while the SDD ledger says 13/15 done | M | H | 4 | DOC-18 DOC-19 CRIT-17 VER-21 | `docs/superpowers/specs/*.md:4`, `docs/superpowers/plans/*.md` | Open |
| E11 | `--detect-shared-borders` is deprecated in tippecanoe; MapLibre sky properties under globe are inert except `atmosphere-blend` | L | M | 1 | DOC-25 | `water.py:105-108`, `app.js` | Needs manual validation |
| E12 | README factual claims that no longer match the code (lakes source, coast zoom, band count) | M | H | 1 | DOC-16 | `README.md` | Open |
| E13 | `pyproject.toml` author email looks like a placeholder | L | L | 1 | DOC-26 | `pyproject.toml:7` | Needs owner decision |
| E14 | `h3shape_to_cells_experimental` carries no API stability guarantee; undocumented dependency | L | H | 1 | DOC-28 | `landmask.py:222` | Open |
| E15 | Shipped `water.pmtiles` is zoom 11 without lakes, not the zoom-12 HydroLAKES layer the code and copy describe; no gate can tell | M | H | 1 | CRIT-19 | `water.py:33,121`, `deploy_verify.sh:29-30` | Open (water rebuild in progress elsewhere) |

## F. Tests

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| F1 | Suite red since the res-6/7 migration: `test_landmask` asserts 500k–620k cells against 4,091,715; `test_index` README attribution; `test_build` hardcodes a res-5 Seoul cell (`KeyError`); other res-5 literals in `test_bands`/`test_grid` | H | H | 6 | CR-6 CRIT-7 VER-13 TE-7 FD-3 TE-8 | `tests/sources/test_landmask.py:14-16`, `tests/graph/test_build.py:61-65`, `tests/emit/test_index.py:76-83` | Open |
| F2 | `tests/emit/test_hover.py` is vacuous for the centre-child rule (res-5 fixture cells; mutation to min-over-children keeps 4/4 green) | H | H | 3 | TE-3 VER-14 CRIT-7 | `tests/emit/test_hover.py:9-27`, `hover.py:30-55` | Open |
| F3 | DMZ ground-cut test vacuous at `SOLVE_RES=6` (chain has non-adjacent pairs); Singapore/Johor fixture no longer adjacent; Schengen test guarded by an `if` that silently passes | H | H | 2 | TE-4 TE-25 | `tests/sources/test_countries.py:38-62,79` | Open |
| F4 | Most of the "unit" suite is unmarked integration: six `build_index()` fixtures at 42–47 s each, real caches, would download on a cold clone; tests leave 294 + 18 + 31 parquet files in the real `data/cache/` | H | H | 4 | TE-5 TE-12 VER-8 PR-16 | `tests/graph/test_*.py`, `tests/sources/test_osm.py`, `tests/test_golden.py` | Open |
| F5 | Web page data decoding (`cellIndex`, `legsTo` ordinal arithmetic, hard-coded `names` mirror of `modes.CHANNELS`, legend tick placement) has no automated test | H | H | 1 | TE-6 | `app.js:133-143,453-462,473-489` | Open |
| F6 | `test_base_values_carry_down_to_children` cannot tell carry-down from zero-fill (mutation proven) | M | H | 1 | TE-9 | `tests/graph/test_refine.py:30-42` | Open |
| F7 | `write_rail_detail` untested; no test that the five per-origin arrays share one ordering; each emitter recomputes `parents` | M | H | 1 | TE-10 | `emit/rail_detail.py:60-93`, `itinerary.py:57-58`, `modes.py:98-99` | Open |
| F8 | `tests/test_cli.py` reads the real OSM extracts; `solve`/`index` subcommands untested; forked build path untested (`_worker_count` returns 1 for small fixtures) | M | H | 2 | TE-13 TE-2 | `tests/test_cli.py:27-104`, `cli.py:64-65` | Open |
| F9 | Deploy consistency gate untested and misses the copy-vs-index drift | M | H | 1 | TE-14 | `deploy_verify.sh:9-37` | Open |
| F10 | Graph edge builders other than ferry untested at unit level | M | H | 1 | TE-15 | `build.py:88-213` | Open |
| F11 | `tests/emit/test_modes.py` depends on the real GRIP4 grid and never pins the road-channel mapping | M | H | 1 | TE-16 | `tests/emit/test_modes.py:34-69` | Open |
| F12 | Dead assertion `… or True` in the split-cell band test | M | H | 1 | TE-17 | `tests/contour/test_bands.py:260` | Open |
| F13 | Low-severity test hygiene: implied connectivity assertion + graph built twice per module (TE-18), golden threshold counts Antarctica (TE-19), ramps parser can skip a scheme (TE-20), missing `__init__.py` in `tests/`, `tests/cli/`, `tests/web/` (TE-22), `real_multi_band` is a name convention not a registered marker (TE-23), `test_tiles` needs tippecanoe with no skip and ignores the layer name (TE-24), 44 s tests for two-airport bounds (TE-26) | L | H | 1 | TE-18 TE-19 TE-20 TE-22 TE-23 TE-24 TE-26 | various | Open |
| F14 | Lint debt: 40 ruff errors at HEAD (F401 unused imports, F841 unused locals, I001, RUF007, RUF012, UP031); nothing gates on ruff; SDD task reports claimed clean lint | L | H | 2 | CR-23 VER-18 | repo-wide | Open |

## G. Cache provenance

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| G1 | Derived caches that break the CLAUDE.md `_params_hash` rule: `routes.parquet` and the parsed-destination cache are bare `.exists()`; `urban_mask` keys on count + first/last cell (not the list, not `PLACES_ZIP`); `ferry_links` omits `ANTIMERIDIAN_EPS_DEG`; `road_class_grid` omits `GRIP4_URL`; land-cell stamp lacks the polyfill method; three keying idioms, no GC | M | H | 8 | CR-15 PR-14 VER-10 TR-9 TR-10 DBG-10 TE-11 ARCH-15 | `routes.py:242-244`, `urban.py:51-52`, `osm.py:180-185`, `roads.py:59`, `landmask.py:176-178`, `grid.py:27,82` | Open |
| G2 | Raw downloads cached by fixed name, never refreshed, read by path in more than one place; no integrity or provenance checks | L | H | 3 | CR-32 TR-16 SEC-9 | `airports.py:23-30`, `countries.py:61`, `landmask.py:53`, `roads.py:37`, `emit/places.py:38`, `borders.py:27`, `water.py:52` | Open |

## H. Performance

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| H1 | Every origin's bands round-trip `mapping()` → `json.dump` (100+ MB/origin) → tippecanoe → `shape()`; 1–3 GB peak per worker | H | H | 1 | PR-3 | `bands.py:187`, `tiles.py:28-30` | Open |
| H2 | Origin-independent work redone per origin: hover parents and representative children ×4, rail line table (`_line_between` polars UDF over 257 k rows), `stop_names`, coverage latitudes, coarse parents; polars runs inside forked workers against the module's own rule | H | H | 4 | PR-4 PR-17 FD-4 DBG-19 | `rail_detail.py:43-75`, `hover.py`, `itinerary.py:57-58`, `modes.py:98-99`, `cli.py:102-103,149-151` | Open |
| H3 | Per-node Python loops over ~10 M nodes for modes/itinerary/rail with an h3 adjacency call per predecessor edge and a 480 MB float64 accumulator | H | H | 2 | PR-5 CR-30 | `modes.py:60-86` | Open |
| H4 | `_interior` recomputes the band-independent slowest-neighbour reduction for every band (38× per LOD); `_dissolve` runs a full overlay on already-valid geometries; `_crosses_antimeridian` evaluated twice per cell per band | H | H | 1 | PR-6 PR-21 | `bands.py:120-121,195-197` | Open |
| H5 | Forked workers un-share the 10 M-entry `cells` list and `_cell_pos` dict through refcount traffic; caps the build at 5 workers | H | M | 1 | PR-7 | `nodes.py:42-44,60,123`, `cli.py` | Likely |
| H6 | `mousemove` frame: `queryRenderedFeatures`, two gazetteer scans, three `innerHTML` writes, forced layout under `backdrop-filter` panels | M | M | 1 | PR-10 | `app.js:578-639` | Likely |
| H7 | 900 DOM markers for place labels re-projected in a JS loop on every `move` frame; 553 haversines per label at start-up | M | M | 1 | PR-11 | `app.js:166-219` | Likely |
| H8 | `borders.json` (1.28 MB) and `places.json` (1.78 MB) parsed on the main thread; borders could be a URL source parsed in MapLibre's worker | M | H | 1 | PR-12 | `app.js:151-160,319-331` | Open |
| H9 | 60 M-edge ground adjacency rebuilt in pure Python with a `frozenset` per edge in `hex_edges`, duplicating the cached `grid.native_edges` | M | H | 1 | PR-13 | `ground.py:81-130` | Open |
| H10 | tippecanoe runs multi-threaded inside each of 5 workers on a `cores-2` budget, from `$TMPDIR`, and leaks 100 MB inputs when a worker is killed (five 91–107 MB `tmp*.geojson` found) | M | M | 1 | PR-15 | `tiles.py:28-61` | Open |
| H11 | `pool.imap` (ordered) hides progress behind the slowest origin | L | H | 1 | PR-18 | `cli.py:190-191` | Open |
| H12 | Every asset including 1.05 MB `maplibre-gl.js` is `Cache-Control: no-cache`; vendored libraries could be versioned and cached | L | H | 1 | PR-20 | `deploy/worldmap.atik.kr.conf:44-63` | Open |
| H13 | `hover_cells.bin` is 725 KB of sorted uint64 for ~90 k entries | L | H | 1 | PR-22 | `emit/index.py:91-99`, `app.js:38-40` | Open |
| H14 | `renderLegs` and search use linear `find`/`filter` over 3,983 airports and 553 cities per call/keystroke | L | H | 1 | PR-23 | `app.js:504-507,728-770,855` | Open |

## I. Security

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| I1 | GeoNames place/region/country names and OurAirports airport names go into `innerHTML` unescaped (stored XSS via community-edited upstream data, with no CSP behind it) | M | H | 1 | SEC-3 | `app.js:596-601,614-624,730` | Open |
| I2 | Vendored MapLibre GL JS 5.24.0 carries CVE-2026-85061 (`removeAttributes` sanitizer bypass); unreachable today only because `attributionControl: false`; README forbids the patched 6.x line | M | H/M | 1 | SEC-4 | `web/vendor/maplibre-gl.js` | Open (needs decision) |
| I3 | Licence firewall is real but narrow: not on the deploy path, no token for the provider actually used (Google Routes), scans only `.json/.geojson/.toml` | M | H | 1 | SEC-8 | `tests/test_licence_firewall.py:11-72`, `deploy_verify.sh` | Open |
| I4 | Artifact permissions follow the umask and rsync preserves them; dotfile/temp leftovers (e.g. `las-vegas.pmtiles-journal`) would be deployed and served; no `location ~ /\.` deny | L | H | 2 | SEC-10 VER-20 | `_utils.py:76,85`, `deploy_verify.sh:41`, `worldmap.atik.kr.conf:73-75`, `dist/origins/las-vegas.pmtiles-journal` | Open |
| I5 | Supply-chain hygiene: `selectolax` declared but unused; no audit step; vendored JS without a recorded hash | L | H | 1 | SEC-16 | `pyproject.toml:20`, `web/vendor/*.js`, `web/README.md:12-13` | Open |

## J. Architecture

| # | Finding | Sev | Conf | Agents | IDs | Where | Status |
|---|---|---|---|---|---|---|---|
| J1 | Pipeline↔page contract undocumented, unversioned and re-typed in ≥ 6 places (sentinels, resolutions, band count, mode-channel order, `n_cells + 2*n_airports` node arithmetic in seven files, file suffixes, byte widths in `deploy_verify.sh`) | H | H | 2 | ARCH-3 ARCH-14 | `nodes.py:170`, `routes_json.py:42-50`, `itinerary.py:32-33`, `modes.py:52-54`, `rail_detail.py:28,69`, `validate.py:180`, `app.js:481,520`, `deploy_verify.sh` | Open |
| J2 | `emit` reaches back into `graph` and `sources`; three "emitters" (`borders`, `places`, `water`) are really sources | M | H | 1 | ARCH-9 | `emit/index.py:104-105`, `modes.py:35,57`, `rail_detail.py:45,72` | Not for this cycle |
| J3 | `web/app.js`: 999 lines, 17 module-level mutable globals, `window.__map` | M | H | 1 | ARCH-10 | `app.js` | Not for this cycle (module split); race is C5 |
| J4 | No injection seams: `build_graph` loads calibration/airports/routes internally; tests monkeypatch module attributes; `cli.py` imports `roads` only so a test can stub it | M | H | 1 | ARCH-13 | `build.py:61-184`, `cli.py:22` | Open (partial) |
| J5 | Environment-specific absolute paths and config that only exist in shell scripts (`cd /Users/hletrd/...`, `atik.kr:/var/www/worldmap/`, `cd /tmp`, `kill -9` by name grep) | M | H | 1 | ARCH-18 | `deploy_verify.sh:6,41,45-48`, `browser_verify.sh:7,59,71,74` | Open |
| J6 | `check_ramps.py --respace` rewrites `web/app.js` in place; tests import from `scripts/` via `sys.path` | L | H | 1 | ARCH-21 | `check_ramps.py:99-110`, `tests/web/test_ramps.py:5` | Not for this cycle |
| J7 | `config.ROOT` derived from `__file__`; package assumes an editable install | L | H | 1 | ARCH-22 | `config.py:5` | Not for this cycle |
| J8 | Hidden global state and import-time side effects (`POLARS_MAX_THREADS` at import, `globals()["_CTX"]`, module-level `_grid_cache`) | L | H | 1 | ARCH-23 | `cli.py:9,111,188`, `roads.py:26,65`, `countries.py:69-8x` | Not for this cycle |
| J9 | `urban_mask` distance ignores the antimeridian; `countries.iso2` re-reads the shapefile on an empty table | L | H | 1 | CR-29 | `urban.py`, `countries.py` | Open |

---

## Cross-agent agreement (highest-signal items)

| Merged | Agents | Summary |
|---|---|---|
| E1 | 11 | Page copy / verify scripts / shipped data disagree (553 vs 157, res 6/7 vs 5) |
| A1 | 8 | numpy import (fixed) |
| A6 | 8 | non-atomic, mixed `dist/`, no resume |
| E2 | 8 | GeoNames / HydroLAKES attribution missing; README test red |
| G1 | 8 | `_params_hash` rule violations |
| E3 | 7 | nginx `add_header` drops CSP/HSTS; CSP would break Nominatim/gtag |
| A3 | 6 | `SystemExit` in forked worker hangs the build |
| A7 | 6 | `solve`/`index` diverge from `build-all` |
| B2 | 6 | calibration provenance rule |
| F1 | 6 | suite red since res-6/7 |
| C3 | 5 | hover value / outline / band from three cells |
| C4 | 5 | legend tick labels on the wrong edges |
| A4, A5, B1, C10, E4, E7, E10, F4, H2 | 4 | see tables |

## What fits this cycle's brief ("more details, higher quality, ease of use, UI; do not overwork")

Bounded, S-effort, user-visible: C4, C6, C7, C13 (legend/sheet half), D1, D2, D3, D4, D5, D6, D7, D8, D9, D10, D11, D12, D14, D15, D16, D18, D19, C5 (generation counter), C9 (failure UI), C10 (gesture-gated geolocation), C12 (fallback when `modeDetail` is absent), E1 (derive copy and verify counts from `index.json`), E2 (attribution rows and credits), E5, E7, E9, E12, D13 (reorder only).

Blocking for the gates regardless of brief: F1, F14 (ruff), E2's README test, F12.

Not for this cycle (recorded, not dropped): A6 full resume, B1 model change, H1–H5, H9, J2, J3 split, J6–J8, I2 (needs an upgrade decision), E3/E4 policy decisions that need the owner (nginx conf lives on the server; Nominatim self-hosting or a search button).
