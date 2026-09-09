# Document-specialist review — cycle 2

**HEAD reviewed:** `bf9e5cc` (2026-09-10 04:23 +0900), branch `feat/transport-pipeline`.
Working tree clean apart from another reviewer's `.context/reviews/security-reviewer.md`.
Angle: documentation ↔ code mismatches, every statement checked against the code at HEAD,
the shipped `dist/`, the live site (read-only `curl`), and the authoritative external
sources listed in §5. No repo file other than this one was written; no build command, no
pytest, no browser session was used.

Finding IDs are `DOC-n`. Severity follows the brief: a user-facing false claim about data,
licence or privacy is High; a stale internal comment is Low. "Confirmed" means I reproduced
the contradiction from the files or an authoritative source quoted below.

**Totals:** 27 findings — High 4, Medium 9, Low 14. Five most important: DOC-1, DOC-2,
DOC-3, DOC-6, DOC-7.

---

## 1. Inventory (nothing sampled; every file below was read end to end)

### Documents

| File | Lines | Read |
|---|---|---|
| `README.md` | 78 | yes |
| `web/README.md` | 64 | yes |
| `web/llms.txt` | 72 | yes |
| `web/robots.txt` | 3 | yes |
| `web/sitemap.xml` | 5 | yes |
| `deploy/README.md` | 73 | yes |
| `deploy/worldmap-security-headers.conf` | 24 | yes |
| `deploy/worldmap.atik.kr.conf` | 83 | yes |
| `CLAUDE.md` | 74 | yes (on-disk copy at `2526673`) |
| `calibration.toml` | 135 | yes, every table |
| `data/origins.toml` | 553 `[[origin]]` blocks | header, marker at :949, counts |
| `pyproject.toml` | 72 | yes |
| `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md` | 323 | yes |
| `docs/superpowers/plans/2026-09-03-transport-pipeline.md` | 3,646 | header, constants, every `## Task` heading, checkbox count (0 of 118 ticked) |
| `.superpowers/sdd/2026-09-03-transport-pipeline/progress.md` | — | task status lines, blocked section, tail |
| `plan/README.md`, `plan/deferred.md`, `plan/2026-09-10-c1-{build-robustness,docs-attribution-calibration,gates-and-tests,security-and-policy,web-ui-detail}.md` | 42 / 53 / 126 / 80 / 112 / 79 / 141 | yes; every commit SHA in every Progress section checked with `git log` |
| `.context/reviews/cycle-1/_aggregate.md` | 229 | yes, status column vs HEAD (§6) |
| `.context/reviews/cycle-1/document-specialist.md` | 922 | DOC-8/9/10/11/16/20/24/25, policy table, final sweep |
| `web/index.html` | 479 | yes: meta, OG, JSON-LD, noscript, visible copy, tooltips, CSS comments |
| `web/app.js` | 1,126 | yes: every comment, tooltip string, error message, empty state |
| `web/vendor/fonts.css` + the three `.woff2` name tables | — | yes (name tables dumped with `ttx` into the scratchpad) |
| `dist/index.json`, `dist/places.json`, `dist/airports.json`, `dist/hover_cells.bin`, `dist/origins/*` sizes | — | read only |
| `data/build/ground_samples*.json` (sample counts), `data/validation/` | — | read only |

### Code whose comments and docstrings were audited (every `.py` under `src/` and `scripts/`)

`src/transport_maps/{__init__,config,cli,validate}.py`; `graph/{air,build,ground,nodes,rail,refine,transfers}.py`;
`emit/{airports_json,borders,hover,index,itinerary,modes,places,rail_detail,routes_json,tiles,water}.py`;
`sources/{_utils,airports,countries,landmask,osm,roads,routes,urban,wikidata}.py`;
`solve/dijkstra.py`; `calibrate/{fit,ground}.py`; `contour/{bands,grid}.py`;
`scripts/{adsb_extract,build_water_tiles,calibrate_ground,check_ramps,expand_origins,ground_check}.py`,
`scripts/{browser_verify,deploy_verify,osm_rail}.sh`; plus `tests/web/test_ramps.py`,
`tests/emit/test_index.py:28-90`, `tests/test_licence_firewall.py:1-40` where a doc cites them.

---

## 2. Findings

### High

#### DOC-1 — `calibration.toml` still breaks the CLAUDE.md provenance rule: seven tables carry no fitted/published label and three comments describe refits that never happened (B2, scheduled cycle 2 — here is the exact list)

- **Severity:** High · **Confidence:** High · **Status:** Confirmed · **Effort:** S (comments) / M (table move)
- **Rule:** `CLAUDE.md:39-43` — "Calibration constants live in `calibration.toml` and each carries a comment saying whether it is **fitted** (and against what) or a **published-figure default**."
- **Tables with no fitted/published label at all** (`calibration.toml`):
  `[taxi_out_min]` :29-32 (no comment), `[taxi_in_min]` :34-37 (no comment),
  `[frequency.size_weight]` :56-59 (no comment), `[processing_min]` :74-77,
  `[disembark_min]` :80-83, `[border_min]` :89-92 (explained, never labelled),
  `[connection_min]` :94-98 (labelled falsely, below). Seven, not the six cycle 1 counted
  (`size_weight` was folded into `[frequency]`).
- **Labelled correctly:** `[airborne]` (:7-8 "FITTED, from adsb.lol"), `[rail]` (:100 "NOT
  fitted"), `[ferry]` (:120 "Published-figure defaults"), `[land_border]` (:131 "A
  published-figure default, not fitted"), `[frequency]` (:44 "Fitted to two real-world
  anchors" — true, see next point).
- **False claims:**
  - :42-43 "Coefficients are refitted in Task 13 against observed frequencies." — no
    observed-frequency input exists anywhere in the repo; `calibrate/fit.py:46-77`
    `fit_frequency` has no caller and `scripts/adsb_extract.py:188-196` writes only
    `(minutes, km)` legs. The values are the two-anchor hand fit the same comment describes.
  - :48 "Task 12 refits from data." — same; never happened.
  - :95 "Minimum connection time, refitted in Task 12 from observed connections." — nothing in
    the repo observes connections (`fit.py` has `fit_airborne`, `fit_airborne_with_holdout`,
    `fit_frequency` only). The SDD ledger records Task 12 as *blocked* (`progress.md:431`).
  - :3 "Fitted coefficients for the flight time model." — the file also holds rail, ferry and
    land-border tables, all published-figure defaults; `[meta] calibrated = true` (:11)
    describes only `[airborne]`.
- **Fitted constants that live outside the file** (the rule says they live in it):
  `graph/ground.py:25` `SPEED_BY_ROAD_CLASS_KMH` ("FITTED against 2,998 real driving
  journeys"), `sources/urban.py:30-32` `URBAN_POP_MIN/RADIUS_KM/CONGESTION_FACTOR` ("Fitted
  jointly"), `graph/air.py:63,79` `MIN_FLIGHTS_PER_WEEK`, `KNEE_KM` (chosen to preserve the
  fitted anchors), `graph/refine.py:25` `SPLIT_MAX_CLASS`. `emit/index.py:110-112` hard-codes
  "200 km/h … 75 km/h", "35 km/h plus 30 min" that `[rail]`/`[ferry]` own (equal today).
- **Corrected wording (comment-only half, safe to land while the rebuild reads the file):**
  - :3 → `# Calibration constants for the air, rail, ferry and land-border models.`
  - above :29 and :34 → `# Published-figure defaults (typical block-time components by
    airport size); not fitted.`
  - :42-43 and :48 → `# Hand-fitted to two anchors (ICN-NRT ~120/wk, ICN-LHR ~14/wk); no
    observed-frequency refit has been done (fit_frequency exists but has no data).`
  - above :56 → `# Published-figure defaults; not fitted.`
  - above :74, :80, :89 → `# Published-figure default; not fitted.`
  - :95 → `# Minimum connection time: published-figure defaults (typical MCTs by airport
    size); not fitted.`
  The table move (`[ground]`, `[urban]`) after the orchestrator's rebuild, as the plan says.

#### DOC-2 — README says "only the fitted coefficients in `calibration.toml` are kept" from Google Routes; the fitted ground constants are kept in code and the observed durations are kept on disk

- **Severity:** High (user-facing claim about what is retained from a commercial service) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `README.md:75-78`: "One commercial service is used during **calibration only**:
  `scripts/calibrate_ground.py` fits the ground-speed constants against Google Routes
  journeys, and only the fitted coefficients in `calibration.toml` are kept."
- **What the code does:** the fitted speeds are `graph/ground.py:25` and the urban factor
  `sources/urban.py:30-32` — nothing from that fit is in `calibration.toml`. The observed
  durations are retained locally: `data/build/ground_samples.json` (1,383 observations, 1,573
  requests), `ground_samples2.json` (2,998 / 3,309), `ground_pilot2.json` (63) — gitignored
  (`.gitignore:2`), not shipped, but "kept".
- **Corrected wording:** "One commercial service is used during **calibration only**:
  `scripts/calibrate_ground.py` samples driving times from Google Routes and fits the
  per-road-class speeds in `graph/ground.py` and the urban factor in `sources/urban.py`. The
  sampled durations stay in `data/build/` (gitignored) and nothing from them reaches `dist/`."
  (Or move the constants into `calibration.toml` per DOC-1 and keep the sentence.)

#### DOC-3 — Public JSON-LD still states pre-H3-v4 cell sizes; the same wrong figures remain in eight code comments (E8, scheduled cycle 2 — exact figures and every location)

- **Severity:** High (machine-readable public claim about the dataset) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Authoritative figures** (`h3` 4.5.0 in the project venv, `average_hexagon_edge_length` /
  `average_hexagon_area`; identical to https://h3geo.org/docs/core-library/restable/):

  | res | avg edge | avg area | flat-to-flat (edge·√3) | corner-to-corner (2·edge) | cells |
  |---|---|---|---|---|---|
  | 4 | 26.07 km | 1,770 km² | 45.2 km | 52.1 km | 288,122 |
  | 5 | 9.85 km | 252.9 km² | 17.1 km | 19.7 km | 2,016,842 |
  | 6 | 3.72 km | 36.1 km² | 6.45 km | 7.45 km | 14,117,882 |
  | 7 | 1.41 km | 5.16 km² | 2.44 km | 2.81 km | 98,825,162 |
  | 9 | 0.201 km | 0.105 km² | 0.348 km | 0.402 km | — |

  Already correct at HEAD: `config.py:11-16`, `web/llms.txt:26-27`, `web/app.js:57-58`
  ("~6.5 km across", "2.4 km", "~45 km"), `web/README.md`.
- **Still wrong (quoted → correct):**
  - `web/index.html:46` JSON-LD "resolution 6 (5.6 km across), refined to resolution 7
    (2.1 km)" → "resolution 6 (about 36 km², 6.5 km across), refined to resolution 7 (about
    5 km², 2.4 km across)".
  - `graph/refine.py:3` "cells about 5.6 km across", :7 "2.1 km across" → 6.5 km / 2.4 km.
  - `contour/bands.py:13` "about 2 km at resolution 5" (quarter of an edge: 2.5 km at res 5,
    0.9 km at res 6), :17 "7 km at the least" (a res-6 rim is 6.5 km flat-to-flat, 3.7 km
    edge), :148-149 "a base cell is 5.6 km across, a fine one 2.1 km", :151-157 margin
    arithmetic ("4 km at least", "5.6 km against 2.4 km at zoom 5", "17 km", "45 km") →
    recompute with 6.5 km / 2.4 km / 45 km (the margins get safer; no code change).
  - `emit/tiles.py:11` "H3 res-5 hexes (~8.5 km edge)" → the source is now res 6/7 (3.7 km /
    1.4 km edge); :17 "Fine cells are 2.1 km across" → 2.4 km.
  - `emit/hover.py:35` "the best time anywhere within ~22 km" → a res-4 cell is ~45 km across
    (26 km edge).
  - `sources/countries.py:91` "at resolution 5 is about 8 km" → "at resolution 6 is about
    6.5 km (2.4 km where refined)".
  - `contour/grid.py:3` "an 8 km hex stair-step" → "a 2–7 km hex stair-step".
  - `sources/roads.py:100-101` "An H3 res-5 cell is about 253 km2 … spans 3-6 GRIP4 cells"
    and `graph/ground.py:55-57` "an H3 res-5 cell spans 3-6 GRIP4 cells" → a res-6 cell
    (36 km²) is *smaller* than a GRIP4 5-arcmin cell (86 km² at the equator, 43 km² at 60°),
    so the footprint window spans 1–4 GRIP4 cells; the measured 51.5 % → 29.3 % figures were
    taken at res 5 and should be dated as such.
  - `graph/rail.py:24` "~174 m edge length" (res 9) → "~200 m edge (0.35 km across)".

#### DOC-4 — `web/README.md` pins MapLibre 5.24.0 without saying it carries CVE-2026-85061; no 5.x patch exists, so the "check for a 5.x patch" branch of I2 is closed

- **Severity:** High (security fact omitted from the doc that governs the pin) · **Confidence:** High · **Status:** Confirmed · **Effort:** S (doc) / M (I2)
- **Where:** `web/README.md:19-34` ("maplibre-gl **5.24.0** NOT 6.x", "MapLibre 5.24 has globe
  projection and works correctly"); `web/vendor/maplibre-gl.js` is 5.24.0 (version string
  checked).
- **Authoritative:** GitHub releases API — v5.24.0 published 2026-04-23; **no `v5.*` release
  after it**; v6.0.0 2026-07-22; v6.4.1 2026-08-18 "Fix `DOM.sanitize` leaving dangerous
  attributes behind when multiple consecutive attributes are present … (#8189)"; latest
  v6.9.0 2026-09-09. npm `time` agrees (5.24.0 is the last 5.x; `latest` = 6.9.0). CVE
  advisory: https://advisories.gitlab.com/npm/maplibre-gl/CVE-2026-85061/ (CVSS 10, affects
  ≤ 6.4.0, reachable through attribution/popup HTML).
- **Mitigation present in the page:** `web/app.js:344` `attributionControl: false`,
  `index.html:107` hides the control, no `Popup`/`setHTML` anywhere, so the sanitizer is not
  reachable with untrusted input today.
- **Corrected wording (add to the pinned-versions table note):** "5.24.0 is the last 5.x
  release and carries CVE-2026-85061 (DOM.sanitize bypass, fixed only in 6.4.1). It is
  unreachable here because the attribution control is disabled and no popup is used; do not
  enable either without upgrading or patching (security plan I2)."

### Medium

#### DOC-5 — E6 is neither scheduled nor deferred: `README.md` "Development" still cannot produce the `places.json`, `airports.json`, `borders.json` that `deploy_verify.sh` requires, and no stage calls their builders

- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed · **Effort:** S (plan) / S (wire a subcommand)
- **Where:** `README.md:33-38` lists `uv sync`, `uv run pytest`, `build-all`,
  `build_water_tiles.py`. `scripts/deploy_verify.sh:29-30` refuses without
  `places.json`, `airports.json`, `borders.json`. `git grep` finds **no caller** of
  `emit.places.build`, `emit.airports_json.build` or `emit.borders.build` (only `emit/__init__`
  siblings and a comment in `sources/urban.py:46`); `cli.py:19-27` imports neither.
- **Plan gap:** `plan/2026-09-10-c1-docs-attribution-calibration.md:3` says its sources are
  "E2, E5–E14" but has no E6 task in any cycle; `plan/deferred.md:51-53` claims every E item
  except E1-data/E13/E15 is scheduled. E6 (High/High in the aggregate) is dropped.
- **Corrected wording:** README Development gains the missing step once it exists (e.g.
  `uv run transport-maps assets  # places.json, airports.json, borders.json -> dist/`), and
  the docs plan gets an E6 task: "add an `assets` subcommand (or run the three builders at
  the end of `build-all`) and list it in README".

#### DOC-6 — The web plan says cycle-1 work was "verified … by scripts/browser_verify.sh after deploy"; the live site still serves the pre-cycle-1 page, and the server still has the old nginx conf

- **Severity:** Medium (plan accuracy; privacy consequence noted) · **Confidence:** High · **Status:** Confirmed (read-only `curl`, 2026-09-10) · **Effort:** S (wording) — deploy is the owner's
- **Claim:** `plan/2026-09-10-c1-web-ui-detail.md:141` "verified on the local preview … and by
  scripts/browser_verify.sh after deploy". `plan/2026-09-10-c1-build-robustness.md:126`
  says the opposite: "deploy attempt: the consistency gate refused mid-rebuild … No files
  were copied."
- **Live evidence:** `https://worldmap.atik.kr/` meta description "from **157 cities**" (the
  repo says "hundreds of cities"); live `app.js` contains none of `function fatal`, `const
  esc`, `MODE_FALLBACK`, `PAGE_CREDITS` and still has `solveRes ?? 5`; live `llms.txt` is the
  self-contradicting 11-band/res-5 text E5 fixed; `sitemap.xml` lastmod 2026-09-09; `/` and
  `/app.js` return **no** CSP/HSTS/X-Frame-Options (only `cache-control: no-cache`), while
  `/vendor/maplibre-gl.css` and `/preview.png` return the *old* CSP (`connect-src 'self'`,
  no Nominatim/gtag) — exactly the E3 inheritance trap, so the corrected conf is not
  installed (E3 server half: still blocked on owner, as the security plan records).
- **Consequence worth stating:** every cycle-1 user-facing fix (D1–D14, C4, C6, C7, C9, C10,
  C12, E2 credits, E4 Nominatim/GA disclosure and explicit search, I1 escaping) is not live.
  The live page therefore still searches Nominatim per keystroke and tells visitors nothing
  about Nominatim or Google Analytics.
- **Corrected wording:** web plan :141 → "verified on the local preview with agent-browser;
  **not yet deployed** (the consistency gate refused mid-rebuild, see build plan) — the
  post-deploy `browser_verify.sh` run is still owed."

#### DOC-7 — `emit/index.py` says "this pipeline never queries OSM directly"; it parses OSM PBF extracts and downloads OSM water polygons. Ferries are `route=ferry` *ways*, not relations, and the README/index attribution omit them

- **Severity:** Medium (attribution wording is user-facing) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where / contradiction:**
  - `emit/index.py:19-21` "OSM appears here even though this pipeline never queries OSM
    directly" — `sources/osm.py:47,68,116,127` stream Geofabrik PBF extracts with pyosmium;
    `emit/water.py:30,49-58` downloads `water-polygons-split-4326.zip` from
    osmdata.openstreetmap.de. The same file's own entry (:57) lists "rail route relations".
  - `README.md:58` OSM row "coastlines …; rail route relations; upstream source of the GRIP4
    road network" and `index.py:57` `usedFor` — both omit the ferry network
    (`osm.py:109-140`, `_ferries`).
  - `README.md:63` "rail and ferry route relations are parsed from Geofabrik PBF extracts"
    and `web/llms.txt:53` "rail and ferry route relations" — ferries are read from **ways**
    tagged `route=ferry` (`osm.py:117`), reduced to their endpoints.
- **Corrected wording:** index.py comment → "OSM enters three ways: rail route relations and
  ferry ways parsed from Geofabrik extracts (sources/osm.py), the coastline layer
  (emit/water.py), and GRIP4, which is compiled partly from OSM." README:58 / index.py:57
  `usedFor` → "coastlines (water polygons via osmdata.openstreetmap.de); rail route
  relations and ferry ways; upstream source of the GRIP4 road network". README:63 and
  llms.txt:53 → "rail route relations and ferry ways".

#### DOC-8 — `deploy/README.md` says every rebuilt asset is `no-cache`; `.css` and `.png` match no nginx location and are served with no `Cache-Control` at all, and the "content-addressed" fonts are not content-addressed

- **Severity:** Medium (the doc explains a blank-globe failure mode and misses one of its causes) · **Confidence:** High · **Status:** Confirmed (conf + live headers) · **Effort:** S
- **Where:** `deploy/README.md:23-33` "Every artifact except the fonts is rewritten by a
  rebuild … Hence `no-cache` on html/js/json/txt/xml/bin/pmtiles"; `deploy/worldmap.atik.kr.conf:43`
  `location ~* \.(html|js|json|txt|xml)$`, :50 `.bin`, :61 `.pmtiles`, :70 `.woff2` — nothing
  matches `vendor/maplibre-gl.css`, `vendor/fonts.css` or `preview.png`; they fall to
  `location /` (:75) with no `Cache-Control` (browser heuristic caching). Live:
  `/vendor/maplibre-gl.css` and `/preview.png` return no `cache-control`. A refreshed
  `maplibre-gl.js` (no-cache) paired with a heuristically cached old `maplibre-gl.css` is the
  mismatch the README warns about. `conf:68-69` "Fonts … content-addressed by name" — the
  names (`ibm-plex-sans-latin-400-normal.woff2`) carry no hash; a refreshed Plex under the
  same name would be served stale for a year. (Cycle-1 E7 asked for "the uncached asset
  classes" to be documented; they were not.)
- **Corrected wording / fix:** add `css` to the `no-cache` location regex (and `png`, or
  give `preview.png` its own rule) and say so in the README; change the font comment to
  "named by family/subset/weight, not by content — bump the filename when Plex is refreshed".

#### DOC-9 — Design spec is still "Approved, pre-implementation" and describes a system that was not built (E10, scheduled cycle 2 — the as-built delta list)

- **Severity:** Medium · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where (spec line → as built):** :4 status; :14 "The site makes no runtime API calls" →
  Nominatim + Google tag (`app.js:874-935`, `index.html:5-11`); :46 D9 "Google Routes API
  (TRANSIT)" → `calibrate/ground.py:74` `travelMode: DRIVE`, used only to fit ground speeds;
  :47 D10 "AWS S3 + CloudFront" → nginx on `atik.kr` (`deploy/`); :49 D12 "res-5 cell size" →
  res 6/7; :56, :213, :320 "~150 origins" → 553 in `origins.toml`; :68, :257 "Vite + React
  19 + TypeScript" → one vanilla ES-module page; :73, :98, :218 "fitted from FR24/FlightAware"
  → adsb.lol (`calibration.toml:7`); :96, :243 "Protomaps basemap … basemap.pmtiles ~100 MB"
  → `water.pmtiles` from OSM/HydroLAKES (867 MB); :125 "548,557 res-5 cells (~253 km², ~8.5 km
  edge)" → 4,091,715 res-6 cells refined to 7; :148-152 ground speeds 85/60/40/25/5 →
  `ground.py:25` 104/57/50/18/25/5 by GRIP4 class; :166-167 rail 250/80 km/h with 140/56
  per week → 200/75 km/h, no headway (`calibration.toml:109-118`); :170 sinuosity 1.15 →
  `detour_factor = 1.2`; :201-206 transfer table → `processing/disembark/border/connection`
  tables; :212-213 "600k nodes and 4M edges … minutes" → ~10 M cells, hours
  (`cli.py:81,201`); :231-232 Google TRANSIT per origin → never done; :241 ".bin 162 KB
  (82,983 cells)" → 181,480 B (90,740 cells); :250 "Eleven bands" → 37; :265 "Contour lines"
  → none; :277-278 EC2/S3/CloudFront → nginx. Also `docs/superpowers/plans/…:16-19`
  "H3 resolution 5 … 548,557 … 82,983 … 10 edges, 11 bands" and 0 of 118 boxes ticked.
- **Corrected wording:** :4 → "**Status:** Superseded in part — see 'As built' below"; add a
  short "As built (2026-09)" section with the table above; tick the plan's boxes per the SDD
  ledger and record that Tasks 9/10/12/13 were completed outside the plan
  (`progress.md:425-432` records them as *blocked*).

#### DOC-10 — `web/README.md`, `CLAUDE.md` and `app.js` say `scripts/check_ramps.py` measures the sea-vs-band and sea-vs-space constraints; the script does not, and the test that does compares against the wrong colour

- **Severity:** Medium (a CLAUDE.md rule cites a measurement that is not made) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/README.md:52-56` "`scripts/check_ramps.py` measures each scheme — adjacent
  anchors ≥ 6 …, lightness strictly monotonic, **and the scheme's own sea darker than its
  darkest band**"; `CLAUDE.md:21-27` "the scheme's sea colour between space and its darkest
  band. `scripts/check_ramps.py` measures all of it"; `web/app.js:20-22` "Space behind the
  globe: darker than every scheme's sea (measured by scripts/check_ramps.py)".
- **Code:** `scripts/check_ramps.py:54-62` `problems()` checks only monotonic lightness and
  ΔE ≥ `MIN_DELTA_E`; :116-120 merely *prints* the sea lightness and never reads `SPACE`. The
  sea checks live only in `tests/web/test_ramps.py:29-37`, and that test compares the sea
  against `"#0a0b0d"` (`BG`), not `SPACE = "#050609"` (`app.js:22`).
- **Fix:** move both checks into `check_ramps.problems()` (parse `SPACE` from `app.js`) so the
  script and the CLAUDE.md sentence are true, or reword all three statements to "measured
  by `tests/web/test_ramps.py`" and make the test read `SPACE`.

#### DOC-11 — `web/llms.txt` still claims "Coverage is about 98% of land" with no source; the build gate is 90 %

- **Severity:** Medium (public data claim) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **Where:** `web/llms.txt:43-44`. The only gate is `validate.py:7` `MIN_COVERAGE = 0.90`
  (non-Antarctic cells); the ledger's one measured value is Seoul 99.28 % at res 5
  (`progress.md:439`); nothing measures or publishes a per-origin figure, and cycle 1's E5
  (marked done) left this sentence in place (DOC-6 cycle 1 flagged it).
- **Corrected wording:** "Every departure reaches at least 90 % of non-Antarctic land (a
  build gate; `coverage` per origin is printed by `build-all`); land with no modelled route
  is drawn in a neutral grey the legend names."

#### DOC-12 — Attribution is correct in wording but lives only inside the closed "Sources and method" panel; MapLibre's attribution control is hidden

- **Severity:** Medium (licence compliance judgement) · **Confidence:** Medium · **Status:** Needs manual validation (owner) · **Effort:** S
- **Where:** `index.html:440-453` `<details id="key">` (closed by default) holds `#credits`;
  `index.html:107` hides `.maplibregl-ctrl-attrib`. Credits render as "OpenStreetMap
  (ODbL 1.0)" linked to `/copyright`, "GeoNames (CC BY 4.0)", "HydroLAKES (CC BY 4.0)",
  "Nominatim (OpenStreetMap) (ODbL 1.0)" (`app.js:204-224`); address results carry
  "Search by Nominatim © OpenStreetMap contributors" (`app.js:914`).
- **Authoritative:** OSMF Attribution Guidelines
  (https://osmfoundation.org/wiki/Licence/Attribution_Guidelines): "OpenStreetMap" linked to
  openstreetmap.org/copyright satisfies the wording; attribution may be collapsed only if
  "users must still be able to find the licence information if they look for it" through an
  info button or menu. A summary labelled "Sources and method" is arguably such a control;
  the guideline's examples use an "i" icon or "attribution" label. GeoNames
  (https://download.geonames.org/export/dump/readme.txt): "Creative Commons Attribution 4.0
  … give credit to GeoNames … with a link". HydroLAKES: CC BY 4.0 with the Messager et al.
  2016 citation (README:60 cites it; the page credits by name and link only).
- **Suggested fix:** rename the summary to "Sources, licences and method" or add a
  permanent one-line credit under the legend ("Data © OpenStreetMap contributors · GeoNames ·
  HydroLAKES · more…" linking to the panel). Cycle-1 DOC-15 was merged into E2 and marked
  done; this half was not addressed.

#### DOC-13 — Six terminology drifts and three first-visit gaps in the page copy (D19, scheduled cycle 2 — every instance with line numbers)

- **Severity:** Medium (ease of use) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- **chart / globe / map / world map:** `index.html:352` "Interactive globe", :361 "over the
  chart", :408 "anywhere on the chart", :410 "a city name on the globe", :435 "rotate the
  globe", :465 (noscript) "interactive world map", :15/:23 "isochrone world map";
  `app.js:762` "click the chart", :1078 "Tap the chart". Pick "map" for instructions ("the
  globe" only when describing rotation).
- **departure / origin / From / charted:** `index.html:390` "Departure" (panel), :370/:409
  "departure city", :411 "charted cities", :393 "the city nearest me"; `app.js:755` "From",
  :1110 "nearest charted city", :1095 "Showing Seoul."; `origin` in ids/code only. Keep
  "departure city"; drop "charted".
- **passage / reading / time / travel time / reckoning:** `index.html:14` "travel time",
  :361 "read a passage", :443 "Reckoned from a planned departure", :445 "The reckoning
  includes the passage to the airport", :448 "a passage of five", :446-447 "the arrival
  field"; `app.js:1078` "read a passage". Plain: "read a travel time", "Times assume you
  leave when you choose…", "the journey from the arrival airport into the city".
- **hours vs days vs minutes:** `app.js:532-539` `fmtTime` prints "min", "h 05m" and, above
  48 h, "N days Nh" (:538), while `bandRangeAt` (:685-688) prints the same reading's band as
  "48–72 h" / "over 72 h" and the legend ticks print hours ("48", "72+", :180,:194) under
  "Hours from the departure city" (:370); `llms.txt:14` "expected door-to-door minutes";
  masthead/meta "hours". One line can read "2 days 3h · 48–72 h". Use hours everywhere
  ("51 h" or "51h 20m").
- **no route / no scheduled route / not on land / Open water / unavailable:** `app.js:534`
  "no route" (readout unit under ∞) vs `index.html:367` and `app.js:684` "no scheduled
  route" (legend key and band label); `app.js:760` "not on land" vs :718 "Open water."
  (same state, two labels).
- **modes:** masthead `index.html:356`, meta :15, :23, :31 "by air, rail and road" omit the
  ferries the noscript (:466), README and llms.txt list; JSON-LD :42 has them.
- **Colour / Color:** `index.html:432` "Color scheme" (UI, en-US) vs "colour" in every prose
  doc (`CLAUDE.md`, `web/README.md`, code comments); pick one for visible copy.
- **What a first-time visitor is not told:** (a) *what the grey is* — the legend key says
  "no scheduled route" but nowhere says it means "no modelled route: no airport, rail, ferry
  or road link reaches it" (a one-line `title` on `#sw-uncharted` would do); (b) *what "door
  to door" includes* — stated only inside the closed panel (:445-448) and as two words at
  :370/:650/:728; the legend caption could read "Door to door: including the trip to the
  airport, check-in, border control and the trip from the arrival airport."; (c) *how to
  change the departure* — the instruction is inside the closed Route panel (:408-412); the
  always-visible line :361 says only "Click a city name to depart from it" and omits the
  list and the "Depart from" button; (d) on phones the pointer copy "Move the pointer…" is
  replaced (`app.js:1077-1078`) but "Click a city name" survives with no click target
  visible until zoomed (`app.js:269` shows 18 labels at the landing zoom, fine on desktop);
  (e) `index.html:399` "Enter departs from the first city match." — and, per `app.js:972`,
  the first *airport* match too, which drops a destination, not a departure.

### Low

#### DOC-14 — Stale numbers and dead references in comments (E9 residue; batch)

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `graph/build.py:380-381` "Task 9's future station edges are the obvious way one could sneak
  in later" — rail edges exist (`_rail_edges`, :231-275).
- `emit/modes.py:10` "Three minute-totals per cell cost 6 bytes" — `CHANNELS` (:24) has six
  → 12 bytes (`deploy_verify.sh:18` width 12; `dist/origins/seoul.modes.bin` = 90,740 × 12).
- `scripts/calibrate_ground.py:7` "the ground graph has 600k nodes" (≈10 M at res 6/7,
  `cli.py:81`); :47-48 "The shipped gazetteer is 7,342 populated places" — `dist/places.json`
  has 34,135 GeoNames rows; the sampling population changed and the comment's argument with it.
- Two sample sizes for one fit: `graph/ground.py:17` "2,998" vs `scripts/ground_check.py:5`
  "1,383" vs `sources/urban.py:4-6` "112 … 1,383". Evidence: `data/build/ground_samples.json`
  = 1,383 observations (first run, which fitted the urban factor), `ground_samples2.json` =
  2,998 (second run, which fitted the shipped speeds). Say so in each place.
- `web/app.js:233` "7,000 objects", :319 "7,000 trig calls" → 34,135; :618-622 "rail or ferry
  … are not itemised here … shipping 57,000 station nodes" — `surface()` (:606-616) itemises
  rail/ferry from `modes.bin` and `railVia` names the station; the comment now describes only
  the no-`modes.bin` fallback.
- `emit/places.py:3-4` "about 31,000 of them" — GeoNames readme says "ca 25.000"; the 2026-09
  download yields 34,135. Write "about 34,000 (2026-09)".
- `emit/airports_json.py:3` "3,983 rows" — emits 4,008 (`dist/airports.json`); 3,983 is the
  graph count after drops. `graph/nodes.py:32` "25 of 4,008 today", :162 "64 of 4,008 needed
  it", `validate.py:14` "9 of 3,983 today", `index.html:46` "3,983 airports" — `bf9e5cc` now
  snaps off-mask airports, so all four numbers change with the running rebuild; re-measure
  and date them.
- `emit/tiles.py:9-19` argues "Do not raise this without re-measuring" for `MAX_ZOOM = 6`,
  then justifies 7 and 8; `MAX_ZOOM` is 8. One paragraph with the current measurement.
- "157 origins" as the full build: `validate.py:133`, `cli.py:170`, `contour/bands.py:25`,
  `emit/tiles.py:35` — `origins.toml` has 553 (`cli.py:92` already says so).
- `scripts/osm_rail.sh:11-16` repeats the `curl -C -` explanation twice verbatim.
- `sources/landmask.py:181-207` `_cells_touching` is defined, documented as the polyfill
  method, and never called (`land_cells` :222 uses `h3shape_to_cells_experimental`); the
  cache stamp (:176-177) does not name the method (G1/E14).

#### DOC-15 — IBM Plex ships with no licence text; the fonts' own metadata carries the copyright and the OFL URL but not the licence

- **Severity:** Low · **Confidence:** High (metadata) / Medium (compliance reading) · **Status:** Likely · **Effort:** S
- **Where:** `web/vendor/` has no `OFL.txt`/`LICENSE`; `fonts.css:1-3` has no copyright line;
  `web/README.md:59-64` and `CLAUDE.md:8-10` name the face but not its licence. The `.woff2`
  name tables (dumped with `ttx`) contain nameID 0 "Copyright 2019 IBM Corp. All rights
  reserved." and nameID 14 "http://scripts.sil.org/OFL"; nameID 13 (licence text) is absent.
- **Authoritative:** SIL OFL 1.1 (https://github.com/IBM/plex/blob/master/LICENSE.txt):
  "may be bundled, redistributed … provided that each copy contains the above copyright
  notice and this license. These can be included either as stand-alone text files,
  human-readable headers or in the appropriate machine-readable metadata fields".
- **Fix:** add `web/vendor/OFL.txt` (the Plex LICENSE.txt) and one line in `web/README.md`
  Typography: "IBM Plex Sans © 2017–2019 IBM Corp., SIL Open Font License 1.1
  (`vendor/OFL.txt`)".

#### DOC-16 — `plan/README.md` status column and paths are stale; "13 of 15 tasks" does not match the ledger

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `plan/README.md:15-19` all five plans "in progress (cycle 1)" while each plan's Progress
  records cycle 1 done (`c6df446`). `plan/README.md:3` and
  `plan/2026-09-10-c1-web-ui-detail.md:3` cite `.context/reviews/_aggregate.md`; moved to
  `.context/reviews/cycle-1/` in `02d1031`. `plan/README.md:37` "its own ledger … records 13 of
  15 tasks done" — `progress.md` records **11** "complete" (Tasks 1–8, 11, 14, 15) and lists
  9, 10, 12, 13 as blocked (:425-432); those four were done outside the plan (rail/ferry via
  `osm_rail.sh`, air fit via adsb.lol) or replaced (Task 13 → DRIVE-mode ground fit).

#### DOC-17 — Docs plan Progress lists E8 as done in `e11c830`; E8 is an unticked cycle-2 task and its locations are still wrong

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `plan/2026-09-10-c1-docs-attribution-calibration.md:80` "E5/E7/E8/D20 (e11c830)". That
  commit fixed `config.py`, `llms.txt`, `app.js`, `web/README.md` only (`git show --stat`);
  DOC-3 lists what remains. Reword to "E8 (partial: config.py/llms.txt/app.js in e11c830;
  code comments and JSON-LD outstanding)".

#### DOC-18 — `_aggregate.md` status column is a snapshot at `edf4b0d` with no header saying so; many "Open" items are closed at HEAD

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- Closed at HEAD (verified in code, commit in brackets): A3 (`b030d38`, `cli.py:85-95`), A4
  (`b38fb8b`, `refine.ground_adjacent`), A5 (`599dc60`, `urban.py:43-58`), A8 (`be2cc94`,
  `validate.py:42-43`), C4 (`b7da35f`, `app.js:172-198`), C6 (`index.html:366-369`), C7
  (`app.js:552-559`), C9 (`app.js:37-52`), C10 (`app.js:1097-1126`), C12 (`app.js:128-137,
  483`), D1, D2 (latin only), D3 (`app.js:269`), D4 (Enter/arrows; semantics pending), D5
  (`index.html:408-412`), D6 (`--text-3`), D7, D9 (`color-scheme:dark`), D10 (`moveTo`),
  D12, D14 (`#disclaimer`), D18 (weight 400), E2 (rows + credits; visibility pending, DOC-12),
  E3 repo half (`03988a5`), E4 bounded (`1305ba7`), E5, E7 (partial, DOC-8), E9 (partial,
  DOC-14), E12, F1, F2, F12, F13 (TE-22/23), F14, I1 (`esc`), H2 (partial, `bf9e5cc`), E1
  page/verify halves, C2 copy half. Still open as recorded: everything else, plus E6 (DOC-5).
- **Fix:** one header line: "Status column as of `edf4b0d`; HEAD status is tracked in
  `plan/*.md` Progress sections."

#### DOC-19 — `web/llms.txt` calls the frequency model "fitted" and states the connection wait unconditionally; both need the B1 hedge

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `web/llms.txt:41` "Flight frequency is a fitted gravity model" → "a gravity model
  hand-fitted to two anchor routes" (`calibration.toml:44-45`). `llms.txt:18-20` "onward
  flight connections are charged an expected wait at the connecting airport" and
  `index.html:443-444` "onward connections are [waited for]" — true only when the
  `arr → dep` connection edge is cheaper than `arr → cell → dep` (deferred B1,
  `build.py:162-212`); add "where the model routes the connection through the airport".

#### DOC-20 — README "550+ cities" vs the 157-origin build the README's own badge links to (E1 data half, deferred)

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `README.md:5` "from 550+ cities" (`origins.toml` 553); `dist/index.json` and the live
  `index.json` have 157 at `solveRes 5`. Reference only; wording that survives the lag:
  "from the cities in `data/origins.toml` (553 today; the live build may lag)".

#### DOC-21 — tippecanoe `--detect-shared-borders` is deprecated with a named replacement; six of the seven sky keys are inert under globe (E11, scheduled cycle 2 — verified)

- **Severity:** Low · **Confidence:** High (deprecation) / Medium (sky behaviour) · **Status:** Confirmed / Likely · **Effort:** S
- `emit/water.py:105-108` `--detect-shared-borders`. felt/tippecanoe README: "-ab or
  --detect-shared-borders: DEPRECATED … Use --no-simplification-of-shared-nodes instead,
  which is faster and more correct." Latest release 2.79.0 (2025-07-24).
- `web/app.js:356-360` sets `sky-color`, `horizon-color`, `fog-color`, `fog-ground-blend`,
  `horizon-fog-blend`, `sky-horizon-blend`, `atmosphere-blend` under `setProjection({type:
  "globe"})` (:352). MapLibre CHANGELOG 5.0.0: "Disable sky when using globe and blend it in
  when changing to mercator (#4853)"; style spec: `fog-color` "Requires 3D terrain",
  `atmosphere-blend` "best to interpolate … when using globe projection". Only
  `atmosphere-blend` acts here; note it in the comment or trim the call.

#### DOC-22 — `pyproject.toml` declares `selectolax` with zero imports; author email (E13) unchanged

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `pyproject.toml:20` — `git grep selectolax` hits only pyproject (I5 scheduled). :7 email
  matches the git author, so it is the owner's choice (E13, deferred).

#### DOC-23 — `data/origins.toml` header describes the hand-picked list only

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `data/origins.toml:3-4` "Top world cities by airport passenger volume, plus coverage for
  every inhabited continent" — 396 of 553 entries follow the :949 marker "Added by
  scripts/expand_origins.py: population >= 1,000,000, or a national capital >= 250,000".
  Add one sentence to the header.

#### DOC-24 — `tests/emit/test_index.py` REQUIRED_ATTRIBUTION does not require GeoNames or HydroLAKES

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `tests/emit/test_index.py:30-40` lists six sources; `index.ATTRIBUTION` has nine. The
  README test (:87-90) compares against `ATTRIBUTION`, so README drift is caught, but
  dropping GeoNames/HydroLAKES from `ATTRIBUTION` itself would stay green. Add both rows
  with `"CC BY"`.

#### DOC-25 — `web/index.html` `<meta charset>` follows the Google tag scripts

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `index.html:4-12`: the charset declaration is the sixth element in `<head>`. It is within
  the first 1,024 bytes, so it is valid; convention and some validators want it first. Move
  :12-13 above :4.

#### DOC-26 — `emit/index.py:110-112` hard-codes the rail and ferry speeds that `calibration.toml` owns

- **Severity:** Low (equal today) · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- "high-speed lines at 200 km/h, conventional at 75 km/h", "35 km/h plus 30 min" match
  `calibration.toml:110-111,124-125` now and will silently diverge on the next edit. Part of
  B2 (read `RailCalibration`/`FerryCalibration`). `app.js:130-137` `MODE_FALLBACK` avoids
  numbers, which is right.

#### DOC-27 — `web/llms.txt` and README describe rail from "OpenStreetMap route relations" only; the readout's rail station/line names come from the same relations — fine — but `llms.txt:36-37` omits that the hover arrays are per-origin and 181 KB each

- **Severity:** Low · **Confidence:** High · **Status:** Confirmed · **Effort:** S
- `web/llms.txt:34-37` "per-origin binary arrays of time, arrival airport, surface mode and
  rail station on a resolution-4 hover grid" — accurate; add the sizes (181 KB / 181 KB /
  1.09 MB / 181 KB) and that `hover_cells.bin` (726 KB) gives their ordering, so a
  machine reader can use `index.json` without reading `app.js`. (J1's `docs/contract.md`
  is the proper home.)

---

## 3. Fact-consistency table (value found per document; ✓ = consistent with code at HEAD)

| Fact | Code / artefact at HEAD | README.md | web/README.md | web/llms.txt | web/index.html | CLAUDE.md | calibration.toml | deploy/* | plans / spec |
|---|---|---|---|---|---|---|---|---|---|
| Band count / edges | 37 / 36 (`config.py:28`; `dist` 36 edges) | — | 37 ✓ (:50) | 37 ✓ (:16) | 37 ✓ (:42); 37 slivers ✓ (:154) | 37 ✓ (:22) | — | derived ✓ (`browser_verify.sh:13`) | spec: 11 ✗ (:250); plan: 11 ✗ (:19) |
| Solver resolution | 6 refined to 7 (`config.py:13,17`) | 6/7 ✓ (:11,27) | — | 6/7 ✓ (:26-28) | 6/7 ✓ (:46) but km wrong (DOC-3) | — | — | — | spec/plan: 5 ✗ |
| Hover resolution / cells | 4; 90,740 (`config.py:18-20`, `dist/hover_cells.bin`) | — | — | res 4 ✓ (:36) | res 4 implied ✓ | — | — | derived ✓ | plan: 82,983 ✗ |
| Land cells | 4,091,715 res 6 (`config.py:11`) — served build: 548,557 res 5 | — | — | 4,091,715 ✓ + lag note (:45-46) | — | — | — | — | 548,557 ✗ |
| Cell sizes | 6.45 km / 36.1 km²; 2.44 km / 5.16 km² | — | — | ✓ (:26-27) | ✗ 5.6 / 2.1 (:46) | — | — | — | spec ✗ 8.5 km edge |
| Departure cities | 553 (`origins.toml`); served/live 157 | "550+" (:5) | — | "list is `origins`" ✓ (:4) | "hundreds" + runtime count ✓ | — | — | derived ✓ | spec ~150 ✗ |
| Airports | 4,008 in `airports.json`; 3,983 in graph (pre-`bf9e5cc`) | — | — | — | 3,983 (:46) | — | — | — | — |
| Rail stations / ferry crossings | 57,286 (`modes.py:9`); 5,672 unsourced | — | — | — | 57,286 / 5,672 (:46) | — | — | — | spec ~10,000 / ~2,000 ✗ |
| ADS-B legs / MAE | 107,366 / 9.3 min (`calibration.toml:14-15`) | — | — | 107,366 ✓ (:8) | 107,366 ✓ (:46) | — | ✓ | — | — |
| Ground-fit journeys | 2,998 (`ground.py:17`, `ground_samples2.json`) | — | — | 2,998 ✓ (:6) | 2,998 ✓ (:42,46) | — | — | — | `urban.py`/`ground_check.py` say 1,383 (DOC-14) |
| Sources (count) | 9 (`index.py:22-78`) | 9 ✓ (:53-61) | — | 9 ✓ (:50-58) | 9 ✓ (JSON-LD :48-58, noscript :468-471, credits at runtime) | — | adsb.lol ✓ | — | spec lists Protomaps/FR24 ✗ |
| Licences | CC BY-SA 4.0, CC0, PD, PD, CC0, ODbL, CC BY 4.0, CC BY 4.0, ODbL | ✓ | — | ✓ | ✓ (:59) | — | ODbL ✓ | — | — |
| OSM usedFor | rail relations + ferry ways + coast + GRIP4 | omits ferries (:58); "ferry route relations" (:63) ✗ | — | "ferry route relations" ✗ (:53) | "ferry crossings" ✓ | — | — | — | — |
| Runtime third-party calls | 2: Nominatim, Google tag (`app.js:874,924`; `index.html:5`) | — | 2 ✓ (:10-14) | 2 ✓ (:60-63) | 2 ✓ (:449-452) | — | — | 2 ✓ (conf :2-3, snippet :11-17) | spec "no runtime API calls" ✗ (:14) |
| Fonts | IBM Plex Sans 400/500/600 latin (`fonts.css`) | — | ✓ (:61) | — | ✓ preload 400/600 (:79-80) | ✓ (:8) | — | — | — |
| Colour schemes / anchors | 12 × 11 (`app.js:74-85`) | — | 12 × 11 ✓ (:49) | — | — | 11 anchors ✓ (:21) | — | 12 ✓ (`browser_verify.sh:16`) | — |
| Separation threshold | anchors ≥ 6, target 8 (`check_ramps.py:20`, `app.js:8`) | — | ≥ 6 aiming 8 ✓ (:52-53) | — | — | ≥ 6 ✓ (:22-23) | — | — | — |
| Sea/space check | test only (`test_ramps.py:29-37`, vs BG) | — | "check_ramps measures" ✗ (:52-54) | — | — | "check_ramps measures" ✗ (:25-26) | — | — | — |
| MapLibre | 5.24.0 (vendor) | 5.24 ✓ (:9) | 5.24.0 ✓; CVE absent (DOC-4) | — | — | — | — | — | spec "GL JS 5" ✓ |
| Door to door | everywhere a figure is shown (`app.js:650,728,760`; `index.html:370`) | ✓ (:5,26) | — | ✓ (:14) | ✓ | rule ✓ | — | — | — |
| Cache classes | no-cache html/js/json/txt/xml/bin/pmtiles; css/png none | — | — | — | — | — | — | README omits css/png ✗ (DOC-8) | — |
| CSP inline-script hash | `sha256-pCkIJ0…` recomputed from `index.html:6-11` | — | — | — | ✓ | — | — | ✓ equal | — |

---

## 4. External facts verified (with the URL used)

| Fact | Result | Source |
|---|---|---|
| H3 v4 average edge / area, res 4/6/7 (and 5, 9) | see DOC-3 table; page states "Version: 4.x" | https://h3geo.org/docs/core-library/restable/ ; `uv run python -c "import h3; …"` (h3 4.5.0) |
| tippecanoe `--detect-shared-borders` | "DEPRECATED … Use --no-simplification-of-shared-nodes instead, which is faster and more correct." Latest release 2.79.0 (2025-07-24) | https://raw.githubusercontent.com/felt/tippecanoe/main/README.md ; https://api.github.com/repos/felt/tippecanoe/releases/latest |
| MapLibre GL JS releases | v5.24.0 2026-04-23 is the last 5.x; v6.0.0 2026-07-22; v6.4.1 2026-08-18 fixes DOM.sanitize (#8189); latest v6.9.0 2026-09-09; npm `latest` 6.9.0, no 5.x after 5.24.0 | https://api.github.com/repos/maplibre/maplibre-gl-js/releases?per_page=100 ; https://registry.npmjs.org/maplibre-gl |
| CVE-2026-85061 | XSS sanitizer bypass in `DOM.sanitize()`, CVSS 10, affects ≤ 6.4.0, fixed 6.4.1; reachable via attribution/popup HTML | https://advisories.gitlab.com/npm/maplibre-gl/CVE-2026-85061/ |
| MapLibre sky under globe | CHANGELOG 5.0.0 "Disable sky when using globe and blend it in when changing to mercator (#4853)"; spec: `fog-color` requires 3D terrain, `atmosphere-blend` for globe | https://raw.githubusercontent.com/maplibre/maplibre-gl-js/main/CHANGELOG.md ; https://maplibre.org/maplibre-style-spec/sky/ |
| Nominatim usage policy | "Auto-complete search … you must not implement such a service on the client side using the API"; max 1 request/s; valid Referer or User-Agent; "Clearly display attribution" | https://operations.osmfoundation.org/policies/nominatim/ — the page complies at HEAD (`app.js:870-917`: explicit search, one reverse request per click, credit line; Referer sent under `strict-origin-when-cross-origin`) |
| OSM attribution wording/visibility | "OpenStreetMap" linked to /copyright suffices; collapsed attribution acceptable if the licence information can still be found | https://osmfoundation.org/wiki/Licence/Attribution_Guidelines |
| GeoNames | "Creative Commons Attribution 4.0 License"; "give credit to GeoNames … with a link"; cities15000 = "all cities with a population > 15000 or capitals (ca 25.000)" | https://download.geonames.org/export/dump/readme.txt |
| HydroLAKES | CC BY 4.0; cite Messager et al. 2016, Nat. Commun. 7:13603, doi:10.1038/ncomms13603; v1.0 | https://www.hydrosheds.org/products/hydrolakes |
| Natural Earth | public domain; "Crediting the authors is unnecessary" | https://www.naturalearthdata.com/about/terms-of-use/ |
| GRIP4 | CC-0; citation Meijer et al. 2018 ERL 13-064006 (README:69-71 ✓); 5 arc-minutes (~8×8 km) | https://www.globio.info/download-grip-dataset |
| OurAirports | "released to the Public Domain"; credit appreciated, not required | https://ourairports.com/data/ |
| OSM water polygons | "copyright OpenStreetMap contributors and available under the ODbL" | https://osmdata.openstreetmap.de/data/water-polygons.html |
| adsb.lol globe_history | "made available under the Open Database License … odbl/1.0" | https://github.com/adsblol/globe_history_2026 |
| Wikidata / Wikipedia | CC0 1.0 / CC BY-SA 4.0 (unchanged; not re-fetched this cycle) | cycle-1 policy table |
| IBM Plex licence | SIL OFL 1.1; copies must contain the copyright notice and the licence (text file, header or metadata) | https://github.com/IBM/plex/blob/master/LICENSE.txt ; woff2 name tables (nameID 0 and 14 present, 13 absent) |
| Code uses OpenFlights? | No — the route network is Wikipedia + Wikidata (`sources/routes.py`, `sources/wikidata.py`); OpenFlights appears only as a rejected alternative in the spec (:48) | repo |

---

## 5. Regression check of the cycle-1 doc items marked done

| Item | Plan claim | Verified at HEAD | Residue |
|---|---|---|---|
| E2 attribution | done (`662f5d3`, `d84217f`, `e11c830`) | README rows ✓ (:59-60); `index.ATTRIBUTION` ✓ 9 entries; llms.txt ✓; JSON-LD `conditionsOfAccess` + `isBasedOn` ✓; noscript ✓; `#credits` + `PAGE_CREDITS` ✓; Nominatim credit under results ✓ | credits only inside a closed panel (DOC-12); index test not updated (DOC-24); served/live `index.json` predates the rows (rebuild) |
| E5 llms.txt | done (`e11c830`) | one consistent res-6/7, 37-band, rail+ferry, HydroLAKES description ✓; lag note ✓ | "98 % of land" unsourced (DOC-11); "ferry route relations" (DOC-7); "fitted gravity model" (DOC-19). Live copy is still the old text (DOC-6) |
| E7 web/README + deploy/README | done (`e11c830`, `03988a5`) | one font family ✓; twelve multi-hue schemes ✓; Nominatim/gtag disclosed ✓; MapLibre note honest ("not isolated") ✓; deploy README documents `web/ → dist/` copy ✓ and the inheritance trap ✓ | uncached `.css`/`.png` classes not documented (DOC-8); CVE absent (DOC-4); "check_ramps measures the sea" (DOC-10) |
| E9 stale comments | done (`fa89fbc`, `e11c830`) | `config.py` ✓; `hover.py:7` ✓; `modes.py:86-88` ✓; `itinerary.py:52-56` ✓; `app.js` res-5/fastest-child/`band-seams` gone ✓; `solveRes ?? 6` ✓; `transfers.py` duplicates gone ✓; `__init__.py` stub gone ✓; `routes_json.py` "Task 9" gone ✓ | `build.py:380`, `modes.py:10`, `calibrate_ground.py:7,47`, `app.js:233,319,618-622`, `places.py:3`, `airports_json.py:3`, `tiles.py:9-19`, sample-size split (DOC-14); `N_BANDS … ?? 10` (`app.js:125`) still encodes the 11-band design |
| E12 README claims | done (`e1b9558`) | "any location" → fixed list ✓ (:26-27); Natural Earth row ✓ (:56); OSM row says extracts are parsed ✓ (:63-67); firewall sentence accurate ✓ (:73-75) | "only the fitted coefficients in calibration.toml are kept" (DOC-2); OSM row omits ferries (DOC-7) |
| D20 threshold | done (`e11c830`) | `app.js:7-8` "floor is 6, the target 8" ✓; `CLAUDE.md:21-23` "adjacent ANCHORS … at least 6" ✓; `web/README.md:52-53` ✓; interpolated-band measurement deferred to cycle 3 ✓ | none for the threshold; the sea/space sentence in the same CLAUDE.md bullet is wrong (DOC-10) |
| Plan SHAs | — | every SHA cited in the five Progress sections (`662f5d3 d84217f e11c830 fa89fbc e1b9558 a261141 b7da35f 1305ba7 f943964 b030d38 599dc60 be2cc94 b38fb8b 3487081 cea16ca 4d74cbe a3f918f 00f40e4 990febe 6f63764 84fb110 498b971 6cc60d4 ceebfc2 3e393b5 03988a5 7b7e601 edf4b0d`) exists and is an ancestor of HEAD ✓ | the "verified after deploy" claim (DOC-6) and "E8 (e11c830)" (DOC-17) |

Also verified correct and worth keeping: `deploy/worldmap-security-headers.conf:18` CSP hash equals the SHA-256 of the exact inline gtag script body; `Permissions-Policy geolocation=(self)` matches the on-request button; `web/preview.png` is 1200×630 as the OG tags say; `sitemap.xml` lastmod and JSON-LD `dateModified` are 2026-09-10 (HEAD date); `.python-version` 3.14 matches the badge; vendor versions 5.24.0 / pmtiles 4.5.0 / h3-js 4.2.1 / fflate 0.8.3 match `web/README.md:23-26`; `calibration.toml:44-47` anchors agree with `air.py:76`; `KNEE_KM` comment agrees with the Seoul–Jeju distance; `hover.py` docstring matches `_representative_children`.

---

## 6. `_aggregate.md` status column vs HEAD

The file is frozen at `edf4b0d` (see DOC-18 for the list of items closed since). Items whose
status is *still* accurate as "Open" and touch documentation: E6 (unscheduled — DOC-5), E8
(DOC-3), E10 (DOC-9), E11 (DOC-21), E13, E14 (DOC-14 last bullet), E15, B2 (DOC-1), J1, J5,
D19 (DOC-13), C3, C13 (legend folds on phones — CLAUDE.md "always visible" still violated
at 390 px: `index.html:339` `.rail.folded > :not(.sheet-toggle){display:none}` hides
`.reading` which holds the legend).

---

## 7. Final sweep

- **Broken links:** none found by inspection; every URL in the four user docs is the same as
  cycle 1's 200-checked set except the added GeoNames/HydroLAKES/Nominatim links, which
  resolved during the fetches above.
- **Jargon left unexplained on the page:** "H3", "resolution", "PMTiles", "Dijkstra" appear
  only in JSON-LD/llms.txt (fine); on the visible page "computed surface" (`index.html:412`),
  "scheduled route" (:367), "surface travel" (`app.js:625,642`), "expressways (GRIP4 class
  1)" (`app.js:133`, tooltip) are unexplained to a visitor — "GRIP4 class 1" should not be in
  a tooltip; say "motorways" only.
- **Missing units:** legend ticks print bare numbers (`app.js:194`: "1", "2", "4", …, "72+")
  with the unit carried only by the caption two lines below; `title` gives minutes. Put "h"
  on the last tick or in the tick itself.
- **Terminology:** enumerated in DOC-13.
- **What the first-time visitor is not told:** DOC-13 (a)–(e).
- **Documents skipped:** none. Every file in §1 was read in full; every `.py` under `src/`
  and `scripts/` (including the 0-line `__init__.py` files and `solve/dijkstra.py`) was
  opened; the pipeline plan's 3,646 lines were scanned for status lines, constants and
  checkboxes rather than read as prose (its task bodies are historical instructions, not
  claims about HEAD).
