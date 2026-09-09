# Document-specialist review — transport-maps

Date: 2026-09-10. Branch `feat/transport-pipeline` at `ac191db` (working tree has
uncommitted changes to `sources/_utils.py`, `sources/airports.py`,
`sources/landmask.py`, `sources/roads.py` and an untracked
`tests/sources/test_cache_provenance.py`). Read-only review: no repo file other
than this one was modified; no build, deploy or process was started or stopped.

Angle: documentation-versus-code and documentation-versus-authoritative-source
mismatches, including the page copy as documentation. Authoritative sources
were fetched today (URLs inline). Live-site facts come from `curl` against
`https://worldmap.atik.kr/` at review time.

## Summary

| Severity | Count |
|---|---|
| Critical | 1 |
| High | 7 |
| Medium | 12 |
| Low | 8 |
| **Total** | **28** |

Top themes:

1. **The served artifact and the page metadata describe two different
   datasets.** `dist/index.json` and the live site are a 157-origin,
   resolution-5 build from before commit `1a4d66b`; `web/index.html`,
   `web/llms.txt` and `README.md` describe a 553-origin, resolution-6/7 build
   that does not exist yet. `dist/index.html` and `dist/llms.txt` were
   hand-patched to say 157, which the next `deploy_verify.sh` run overwrites.
2. **Licence and policy claims are not met on the live site**: GeoNames and
   HydroLAKES (both CC BY 4.0) are served without attribution; the Nominatim
   integration implements client-side search-as-you-type, which the OSMF
   policy forbids; OSM attribution is hidden inside a closed panel.
3. **Security-header documentation describes headers the server does not
   send** on any page-bearing response (nginx `add_header` inheritance), which
   is also the only reason the Google tag and Nominatim work despite the
   `connect-src 'self'` CSP in the conf.
4. **Calibration provenance rule** (`CLAUDE.md` "fitted (and against what) or a
   published-figure default") is unmet for six tables in `calibration.toml`,
   and two comments describe refits that never happened.
5. **Cell-size figures throughout use pre-H3-v4 edge lengths** (~15% too
   small) and a dozen comments still describe the resolution-5, min-of-children
   design.

Cross-references: `.context/reviews/architect.md` ARCH-5 (no CLI stage builds
`places.json`/`airports.json`/`borders.json`) is the code side of DOC-7 below.

---

## Findings

### DOC-1 — Live site ships GeoNames and HydroLAKES data (CC BY 4.0) with no attribution anywhere a visitor can see

- **Severity:** Critical  **Confidence:** High  **Status:** Confirmed
- **Where:**
  - Live `https://worldmap.atik.kr/index.json` `attribution` has 7 entries:
    Wikipedia, Wikidata, OurAirports, Natural Earth, GRIP4, OpenStreetMap,
    adsb.lol. `dist/index.json` is identical. Neither names GeoNames or
    HydroLAKES.
  - `dist/places.json` (34,135 rows, served live) is built by
    `src/transport_maps/emit/places.py:3-4` from "GeoNames cities15000"; the
    page reads it at `web/app.js:151` and shows a GeoNames name on every
    pointer move (`web/app.js:597-607`).
  - `dist/water.pmtiles` (134 MB, served live) is built by
    `src/transport_maps/emit/water.py:12,31,94` from "HydroLAKES (Messager et
    al. 2016, CC BY 4.0)".
  - `README.md:48-56` attribution table: no GeoNames row, no HydroLAKES row,
    although the badge at `README.md:12` advertises "OpenStreetMap · Natural
    Earth · GeoNames".
  - `web/llms.txt:35-42` "Data sources" list: neither source (they appear only
    in the appended `## Grid and geometry (2026-09-10)` section, lines 57-58).
  - `web/index.html:423-424` noscript: "Built from open data: OurAirports,
    Wikipedia, OpenStreetMap, GRIP4 road density and Natural Earth."
  - `web/index.html:48-54` JSON-LD `isBasedOn`: no GeoNames, HydroLAKES,
    Wikipedia or Wikidata URL.
  - `tests/emit/test_index.py:30-39` `REQUIRED_ATTRIBUTION` lists six names;
    GeoNames and HydroLAKES are absent, so the attribution gate cannot catch
    their loss.
- **Authoritative source:** GeoNames dump readme: "This work is licensed under
  a Creative Commons Attribution 4.0 License"
  (https://download.geonames.org/export/dump/readme.txt); export page: "You
  should give credit to GeoNames when using data or web services with a link or
  another reference to GeoNames" (https://www.geonames.org/export/). HydroLAKES:
  "licensed under a Creative Commons Attribution (CC-BY) 4.0 International
  License", citation Messager et al. 2016, Nature Communications 7:13603
  (https://www.hydrosheds.org/products/hydrolakes).
- **Why it matters:** CC BY 4.0 §3(a) makes attribution a condition of the
  licence. The code already carries both entries
  (`src/transport_maps/emit/index.py:59-70`), but the artifact on the server
  predates that commit and nothing in the deploy path checks that the served
  `index.json` credits every source the served files came from.
- **Fix:**
  1. Until the 553 build lands, regenerate `dist/index.json` from the current
     `emit/index.py` (`uv run transport-maps index` writes it) and redeploy —
     or hand-add the two entries; the page renders whatever the block holds.
  2. `README.md` table: add
     `| [GeoNames](https://www.geonames.org/) | CC BY 4.0 | departure cities (via scripts/expand_origins.py) and the place names under the cursor (cities15000) |`
     and
     `| [HydroLAKES](https://www.hydrosheds.org/products/hydrolakes) | CC BY 4.0 | lake outlines drawn on the map (Messager et al. 2016, doi:10.1038/ncomms13603) |`.
  3. `web/index.html` noscript and JSON-LD `isBasedOn`: add
     `https://www.geonames.org/`, `https://www.hydrosheds.org/products/hydrolakes`,
     `https://en.wikipedia.org/`, `https://www.wikidata.org/`.
  4. `tests/emit/test_index.py:30-39`: add `"GeoNames": "CC BY"` and
     `"HydroLAKES": "CC BY"`; then remove one entry from `ATTRIBUTION` and
     confirm the test goes red (CLAUDE.md testing rule).
  5. `scripts/deploy_verify.sh` step 1: assert the served `index.json`
     attribution names ⊇ `emit.index.ATTRIBUTION` names, so a stale artifact
     cannot be deployed with missing credits.

### DOC-2 — deploy docs claim a strict CSP and HSTS; the server sends neither on any page, script, data or tile response

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where (claims):**
  - `deploy/README.md:32-33`: "HSTS is set without `preload`".
  - `deploy/worldmap.atik.kr.conf:1-2`: "Self-contained: no CDN, no external
    fonts, no runtime API calls."; `:24-32` the CSP/HSTS/`X-Frame-Options`/
    `Referrer-Policy`/`Permissions-Policy` `add_header` lines at `server` level.
  - `web/README.md:8-10`: "the deployed site works behind a strict
    `script-src 'self'` CSP and has no third-party dependency."
- **Where (reality):** `curl -sI` today:
  - `/`, `/index.html`, `/app.js`, `/index.json`, `/origins/seoul.bin`,
    `/water.pmtiles`: only `cache-control: no-cache` (plus `etag`,
    `accept-ranges`). No CSP, no HSTS, no X-Frame-Options, no nosniff.
  - `/vendor/ibm-plex-sans-latin-400-normal.woff2`: only `cache-control:
    public, max-age=31536000, immutable`.
  - `/vendor/fonts.css` (matches no `add_header`-bearing location): all six
    security headers present.
- **Cause (verified from the conf):** nginx `add_header` directives "are
  inherited from the previous configuration level if and only if there are no
  `add_header` directives defined on the current level"
  (https://nginx.org/en/docs/http/ngx_http_headers_module.html#add_header).
  Every `location` block at `deploy/worldmap.atik.kr.conf:42-71` defines its
  own `add_header Cache-Control`, which discards the server-level set for
  exactly the responses that matter (the document, the module scripts, the
  data).
- **Why it matters (two ways):**
  1. The documented security posture is not the deployed one; a reader of
     `deploy/README.md` believes clickjacking, MIME sniffing and downgrade
     are covered.
  2. If the headers *were* inherited, the CSP as written would break the site:
     `script-src 'self' blob:` blocks `https://www.googletagmanager.com/gtag/js`
     (`web/index.html:5`) and the inline `gtag` snippet (`:6-11`, no nonce);
     `connect-src 'self'` blocks `https://nominatim.openstreetmap.org`
     (`web/app.js:776,789,829`) and the GA beacons. Google's CSP guide requires
     `script-src-elem https://www.googletagmanager.com`, `img-src
     https://*.google-analytics.com https://www.googletagmanager.com`,
     `connect-src https://*.google-analytics.com https://*.analytics.google.com
     https://www.googletagmanager.com`
     (https://developers.google.com/tag-platform/security/guides/csp). The conf
     comment "no runtime API calls" is false since `a709be5` and `b14148c`.
- **Fix:**
  1. Move the five security headers into `deploy/security-headers.conf` and
     `include` it inside every `location` that sets `Cache-Control` (or set
     `Cache-Control` via a `map $uri $cache_ctl` at `server` level so there is
     a single `add_header` scope). Verify with `curl -sI https://worldmap.atik.kr/
     | grep -i content-security` in `scripts/deploy_verify.sh` step 3.
  2. Decide the policy first: either drop the Google tag and Nominatim (then
     the strict CSP is honest), or extend the CSP with the hosts above plus
     `connect-src https://nominatim.openstreetmap.org` and a nonce/hash for the
     inline gtag snippet.
  3. Rewrite `deploy/worldmap.atik.kr.conf:1-2`, `deploy/README.md` and
     `web/README.md:6-10` to say which third-party endpoints the page contacts
     (googletagmanager.com, google-analytics.com, nominatim.openstreetmap.org)
     and why, and keep the "self-contained" wording only for the *assets*.

### DOC-3 — Address search implements client-side autocomplete against Nominatim, which its usage policy prohibits; the docs describe it as compliant

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/app.js:773-783`:
  > "One request per pause in typing, never more than one a second, which is
  > what its usage policy asks."
  `scheduleAddressSearch` is called from `render()` on every `input` event
  (`web/app.js:769-770,870`) and fires `/search` after a 900 ms pause for any
  query of four characters or more. `web/llms.txt:58`: "queries are sent to
  nominatim.openstreetmap.org only when typed or clicked."
- **Authoritative source:** OSMF Nominatim Usage Policy, "Unacceptable Use":
  > "Auto-complete search — This is not yet supported by Nominatim and you
  > must not implement such a service on the client side using the API."
  Requirements: "Provide a valid HTTP Referer or User-Agent identifying the
  application", "Clearly display attribution as suitable for your medium",
  "No heavy uses (an absolute maximum of 1 request per second)", and the new
  clause "Code generated by LLMs must adhere to all terms laid out in this
  policy." (https://operations.osmfoundation.org/policies/nominatim/)
- **Why it matters:** A debounce does not make search-as-you-type something
  other than autocomplete; the policy is about the pattern, not the rate. The
  OSMF blocks offending referrers, at which point the feature (and the
  `browser_verify.sh:42-46` gate that requires it) fails silently for every
  visitor. The browser sends `Referer` automatically (Referrer-Policy
  `strict-origin-when-cross-origin` yields the origin), so identification is
  fine; the reverse-geocode label (`web/app.js:838`) carries no attribution at
  all, unlike the search list (`:819`).
- **Fix:**
  1. Search only on an explicit action: Enter key or a "Search addresses"
     button; remove the timer in `scheduleAddressSearch`. Keep the local
     city/airport filtering live — that is not Nominatim.
  2. Show "Address © OpenStreetMap contributors (Nominatim)" next to a
     reverse-geocoded pin label, or fold it into the credits line that is
     always visible (see DOC-15).
  3. Update `web/app.js:773-775`, `web/llms.txt:58` and `web/README.md` to say
     "one request per explicit search or click".
  4. Consider a self-hosted Nominatim or Photon instance if autocomplete is a
     product requirement; the policy explicitly points there.

### DOC-4 — Page metadata, README and llms.txt say 553 origin cities; the served index.json has 157, and the hand-patched dist copies will be overwritten by the next deploy

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where (553):** `web/index.html:15` meta description, `:23` og:description,
  `:31` twitter:description, `:41,42` JSON-LD name/description, `:373-375`
  Route hint ("only those 553 have a computed surface"), `:421` noscript;
  `web/llms.txt:3`; `README.md:5` "550+ cities". `data/origins.toml` has 553
  `[[origin]]` blocks (157 hand-picked plus 396 appended at `:949` by
  `scripts/expand_origins.py`).
- **Where (157):** live and local `index.json` `origins` length 157;
  `dist/origins/` holds 157 × 5 files; `dist/index.html` and `dist/llms.txt`
  differ from `web/` only in "553" → "157" (diffed); `web/app.js:722` comment
  "only the 157 cities"; `scripts/browser_verify.sh:19` asserts `"cities":157`.
- **Why it matters:** `scripts/deploy_verify.sh:40` runs
  `rsync -a --exclude 'README.md' web/ dist/` before deploying, so the very
  next deploy ships "553 cities" copy on top of a 157-origin `index.json`, and
  step 1 has no check for it. Visitors, search engines (JSON-LD `Dataset`) and
  LLM readers (`llms.txt`) are then told a number the site cannot back.
- **Fix:**
  1. Make the on-page numbers data-driven: in `web/app.js` after `meta` loads,
     set the Route hint from `meta.origins.length` (`<span
     id="origin-count">`), and stop hard-coding it in `index.html:373-375`.
  2. For the static head (meta/OG/JSON-LD/noscript), either template
     `index.html` at deploy time from `dist/index.json`, or word them without
     a count ("from hundreds of cities") until the count is stable.
  3. `scripts/deploy_verify.sh` step 1: fail if `dist/index.html` or
     `dist/llms.txt` contains a city count different from
     `len(idx["origins"])`.
  4. `README.md:5`: keep "550+" only once the 553 build is live; today it
     should read "157 cities (553 in the next build)".

### DOC-5 — web/index.html JSON-LD and llms.txt describe the resolution-6/7, 37-band, four-LOD, HydroLAKES, station-naming build; the served dataset is the resolution-5 build from before that code existed

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/index.html:42` "37 continuous bands at four levels of
  detail ... coastlines from OpenStreetMap and lakes from HydroLAKES"; `:46`
  "resolution 6 (5.6 km across), refined to resolution 7 (2.1 km)";
  `web/llms.txt:53-59` "Grid and geometry (2026-09-10)"; commit `39a9b42`
  body: "Meta and JSON-LD say 553 cities, the resolution-6/7 grid, four levels
  of detail". Against: `dist/index.json` `solveRes: 5`, no `fineRes`, no
  `modeDetail` (both are written by the current
  `src/transport_maps/emit/index.py:125-128`); `dist/index.json` mtime
  2026-09-09 23:18, `SOLVE_RES = 6` committed 2026-09-09 23:44 (`1a4d66b`);
  `dist/origins/*.rail.bin` count is 0 (station naming, `2526673`, is not in
  the artifact). On the live page `meta.modeDetail` is `undefined`, so the
  mode tooltips that `browser_verify.sh:38-40` requires cannot appear.
- **Why it matters:** The page's machine-readable description (`Dataset`
  JSON-LD, `dateModified: 2026-09-10`, `sitemap.xml` lastmod 2026-09-10) is a
  statement about the served data; today it is a statement about a build that
  is still running. `web/README.md`/`CLAUDE.md` deploy rules exist precisely
  because mismatched artifacts have shipped before.
- **Fix:** Keep `web/` metadata describing the *served* build. Practical
  guard: `scripts/deploy_verify.sh` step 1 already prints `solveRes`; extend
  it to assert `idx["solveRes"] == config.SOLVE_RES`, `"fineRes" in idx`,
  `"modeDetail" in idx`, and that `dist/index.html` mentions the same
  resolution as `config.SOLVE_RES`. Add a `dataVersion`/`builtAt` field to
  `index.json` and print it in the credits so the page can never quietly
  describe a different dataset.

### DOC-6 — web/llms.txt contradicts itself and the code in four places

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where:**
  - `web/llms.txt:13-14`: "rendered in 11 bands from under 2 hours to over 72
    hours" — `src/transport_maps/config.py:24` has 36 edges from 30 min
    (37 bands); `dist/index.json` `bandEdgesMin` has 36 entries; the page
    paints 37 swatches (`web/index.html:144`).
  - `:22`: "548,557 H3 resolution-5 land cells (about 253 km2 each)" —
    contradicted by `:55` of the same file ("H3 resolution 6 ... refined to
    resolution 7") and by `config.py:12,15`.
  - `:31`: "Rail and ferry are not yet in the graph." — contradicted by `:5`
    ("rail from OpenStreetMap route relations, ferry crossings"), `:59`, and
    `src/transport_maps/graph/build.py:362-366`.
  - `:33`: "Coverage is about 98% of land" — no source; the only gate is
    `validate.MIN_COVERAGE = 0.90` (`src/transport_maps/validate.py:7`) and
    the build prints per-origin coverage that is not recorded anywhere shipped.
  - `:37-42` "Data sources" omits adsb.lol (fitted air model), GeoNames,
    HydroLAKES and Nominatim, all of which the file itself mentions elsewhere.
- **Why it matters:** `llms.txt` exists to be quoted by machines; a
  self-contradicting file gets quoted both ways.
- **Fix:** Rewrite as one coherent document: bands "37 bands from 30 minutes
  to 72 hours on a geometric ladder (ratio ≈1.155)"; grid paragraph from
  `config.py`/`refine.py` with the corrected sizes (DOC-9); delete the "not
  yet in the graph" line and replace with real limits (OSM rail coverage is
  uneven; ferries carry published-figure speeds; frequency is a gravity
  model); either emit measured coverage into `index.json` and cite it, or
  drop the 98% claim; merge the appended section into the main body and list
  every source once with its licence.

### DOC-7 — README "Development" does not produce the artifact the deploy script requires, and omits every other script the build depends on

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where:** `README.md:28-40` lists three commands. Against:
  - `scripts/deploy_verify.sh:29-30` refuses to deploy without
    `places.json`, `airports.json`, `borders.json`, `water.pmtiles`. The first
    three are written by `src/transport_maps/emit/places.py`,
    `emit/airports_json.py`, `emit/borders.py`, whose `build()` functions have
    **no caller** in `src/`, `scripts/`, `tests/` or any README (repo-wide
    grep; see also `.context/reviews/architect.md` ARCH-5). `cli.py:207-232`
    defines only `solve`, `index`, `build-all`.
  - Rail and ferries require `scripts/osm_rail.sh` first
    (`src/transport_maps/sources/osm.py:148-150,171-173`); without it
    `build-all` prints `rail: EXCLUDED` and continues
    (`src/transport_maps/cli.py:44-51`). Not mentioned.
  - `tippecanoe` must be on PATH (`src/transport_maps/emit/tiles.py:24-25`).
    Not mentioned.
  - `scripts/calibrate_ground.py` (needs `GOOGLE_ROUTES_API_KEY`),
    `scripts/adsb_extract.py`, `scripts/expand_origins.py`,
    `scripts/check_ramps.py`, `scripts/deploy_verify.sh`,
    `scripts/browser_verify.sh`, `scripts/ground_check.py` — none documented.
  - `README.md:17` "How it is built" links to `#development`, which is the
    four-line block above.
- **Why it matters:** The spec's stated goal is "Keep the pipeline
  reproducible: re-runnable from open inputs plus a small config"
  (`docs/superpowers/specs/...:23`). A reader following the README cannot
  reproduce `dist/`, and cannot tell that the rail network was silently left
  out of a build.
- **Fix:** Add a `transport-maps emit-static` subcommand (or fold into
  `build-all`) that calls the three builders, then document the full order:
  `brew install tippecanoe osmium-tool` → `uv sync` →
  `OSM_DIR=... scripts/osm_rail.sh` (copy extracts to `data/cache/osm/`) →
  `uv run transport-maps build-all` → `uv run python
  scripts/build_water_tiles.py` → `scripts/deploy_verify.sh` →
  `scripts/browser_verify.sh`. Add a "Calibration" subsection pointing at
  `calibrate_ground.py`/`adsb_extract.py` and the env file, and an
  "Adding origins" subsection for `expand_origins.py`.

### DOC-8 — calibration.toml breaks the CLAUDE.md provenance rule in six tables and claims two refits that never happened; fitted ground constants live outside the file

- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Rule:** `CLAUDE.md:40-44`: "Calibration constants live in
  `calibration.toml` and each carries a comment saying whether it is
  **fitted** (and against what) or a **published-figure default**."
- **Where:**
  - `calibration.toml:29-37` `[taxi_out_min]`, `[taxi_in_min]`: no comment of
    any kind. The plan (`docs/superpowers/plans/...:536-547`) says these were
    "pre-calibration defaults derived from published block times", which is
    the sentence that belongs here.
  - `:74-92` `[processing_min]`, `[disembark_min]`, `[border_min]`: explained
    but never labelled fitted or default.
  - `:94-95` `[connection_min]`: "Minimum connection time, refitted in Task 12
    from observed connections." False — `src/transport_maps/calibrate/fit.py`
    contains only `fit_airborne`, `fit_airborne_with_holdout` and
    `fit_frequency`; `scripts/adsb_extract.py` emits (minutes, km) legs only.
    Nothing observes connections.
  - `:42-48` `[frequency]`: "Coefficients are refitted in Task 13 against
    observed frequencies" and "Task 12 refits from data" (two different task
    numbers) — never done; `fit_frequency` exists but no observed-frequency
    input exists in the repo. The values are the two-anchor hand fit.
  - `:3` header: "Fitted coefficients for the flight time model" — the file
    also holds rail, ferry and land-border tables.
  - Fitted constants **not** in the file: `SPEED_BY_ROAD_CLASS_KMH`
    (`src/transport_maps/graph/ground.py:25`, "FITTED against 2,998 real
    driving journeys"), `URBAN_POP_MIN`/`URBAN_RADIUS_KM`/
    `URBAN_CONGESTION_FACTOR` (`src/transport_maps/sources/urban.py:24-29`,
    "Fitted jointly"), `KNEE_KM` and `MIN_FLIGHTS_PER_WEEK`
    (`graph/air.py:63-81`), `SPLIT_MAX_CLASS` (`graph/refine.py:25`).
- **Why it matters:** The rule exists so a reader can tell a fitted number
  from a guess without reading the git log; the file currently says the
  opposite of the truth for `connection_min`.
- **Fix:** Add a one-line provenance to every table, e.g.
  `# Published-figure default (typical airline block-time components); not fitted.`
  for taxi/processing/disembark/border/connection, and change the frequency
  comment to `# Hand-fitted to two anchors (ICN-NRT 120/wk, ICN-LHR 14/wk); no
  observed-frequency refit exists.` Move the ground-speed table and the urban
  factor into `[ground]`/`[urban]` sections read by `ground.py`/`urban.py`
  (with their fitted-against text), or amend `CLAUDE.md` to say where each
  fitted constant may live. Retitle the header "Calibration constants for the
  air, rail, ferry and border models".

### DOC-9 — Cell-size figures throughout use the pre-H3-v4 edge lengths and are ~15% too small

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where (quoted figure → file:line):**
  - "5.6 km across" res 6 / "2.1 km" res 7: `src/transport_maps/graph/refine.py:3,7`,
    `src/transport_maps/contour/bands.py:142-153`, `emit/tiles.py:17`,
    `web/llms.txt:55`, `web/index.html:46` (JSON-LD).
  - "1.2 km cells instead of 3.2 km": `src/transport_maps/config.py:13-14`.
  - "~8.5 km edge" res 5: `emit/tiles.py:11`, spec `:125,154`.
  - "~8 km" res 5: `web/app.js:30`, `sources/countries.py:91`,
    `graph/build.py:301-302`, `contour/grid.py:3`.
  - "~22 km" res 4: `web/app.js:31`.
  - "~174 m edge length" res 9: `graph/rail.py:24`.
- **Authoritative source:** h3geo.org resolution table and `h3 4.5.0`
  (`average_hexagon_edge_length`, run in the project venv): res 4 = 26.07 km
  edge / 1,770 km²; res 5 = 9.85 km / 252.9 km²; res 6 = 3.72 km / 36.1 km²;
  res 7 = 1.41 km / 5.16 km²; res 9 = 0.20 km
  (https://h3geo.org/docs/core-library/restable/). The 3.229/1.221/8.54/22.6 km
  figures are the H3 v3 table values, which were corrected in v4.
- **Why it matters:** Several of these numbers are load-bearing arguments
  ("5.6 km against 2.4 km at zoom 5", `bands.py:147-148`) and one is a
  published claim (`index.html:46`, `llms.txt:55`).
- **Fix:** Use area-based, resolution-honest wording: "resolution 6 (about
  36 km², 6.5 km flat-to-flat) refined to resolution 7 (about 5 km², 2.4 km)".
  Update `config.py:13-14` to "3.7 km edge → 1.4 km edge". Recheck the LOD
  margin arithmetic in `bands.py:145-153` with 6.5 km/2.4 km — the margins
  get *safer*, so no code change, but the comment should not understate them.

### DOC-10 — config.py comments describe the previous grid, the previous hover array and a rendering the page no longer does

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `src/transport_maps/config.py`
  - `:11` "548,557 land cells at ~253 km^2 each (measured)" sits above
    `SOLVE_RES = 6`; those are resolution-5 numbers.
  - `:16` "82,983 cells -> 165,966 bytes as uint16": `dist/hover_cells.bin`
    holds 90,659 entries (725,272 bytes ÷ 8; each `origins/*.bin` is 181,318
    bytes) because Antarctica is now charted (`sources/landmask.py:147-153`).
  - `:19` "The 11th band is open-ended" and `:20` "Thirty-six bands": 36 edges
    make 37 bands, the last open-ended (`contour/bands.py:171-172`,
    `web/app.js:98`).
  - `:22-23` "with corner smoothing and the seam stroke the steps vanish":
    corners are not smoothed (`CLAUDE.md:28-30`, `contour/bands.py:116-119`)
    and there is no seam layer — `band-seams` appears in `web/app.js` only as
    a defensive `getLayer` guard (`:376,923-924`).
- **Fix:** Replace with measured facts: "SOLVE_RES = 6: ~36 km² cells, N base
  cells (measured YYYY-MM-DD)"; "HOVER_RES = 4: 90,659 cells → 181,318 bytes";
  "36 edges → 37 bands, ratio ≈1.155; hexagons are drawn unrounded and
  neighbouring bands overlap by a rim (contour/bands.py)". Delete the dead
  `band-seams` guards in `app.js` or add the layer.

### DOC-11 — Hover/itinerary/modes docstrings and app.js comments disagree with each other about which child the readout reports and at which resolution

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:**
  - `src/transport_maps/emit/hover.py:7-11,31-37`: "value of its CENTRE res-5
    child" — code uses `config.SOLVE_RES` (6) then `config.FINE_RES` (7)
    (`:49-53`).
  - `emit/itinerary.py:52-55`: "the hover value is a minimum over children" —
    it is the centre child (hover.py docstring, same file's own code path via
    `_representative_children`).
  - `emit/modes.py:95`: "same res-5 child".
  - `web/app.js:30-34`: "solved per res-5 cell (~8 km); the readout array is
    res 4 (~22 km, the min of seven children)"; `:573-577`: "takes the FASTEST
    of each cell's children. So the number can be optimistic against the
    colour" — the optimism argument is stale now that the centre child is used;
    and the highlight polygon (`:335`) is drawn at `SOLVE_RES` even inside
    refined cells, where the solved cell is res 7.
  - `web/app.js:34,98` fallbacks `?? 5` and `?? 10` encode the old design;
    harmless but misleading.
- **Fix:** One sentence, repeated verbatim in the four places: "Each res-4
  hover entry is the value of the solved cell at the parent's centre (base
  cell, or its fine centre child where the base cell was split); the fastest
  child only where the centre is water." In `app.js:335`, choose
  `meta.fineRes` when the base cell is split (needs the split set, or use
  `queryRenderedFeatures` on the native LOD) and rewrite `:573-577`.

### DOC-12 — web/README.md is stale in five statements

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where / contradiction:**
  - `web/README.md:8-9` "both font families are vendored" — `web/vendor/`
    holds one family (IBM Plex Sans 400/500/600, `vendor/fonts.css`).
  - `:39-45` "Eleven sequential steps of a single blue hue ... 0.905 -> 0.433
    ... 2.41:1 against the `#0a0c10` surface ... deliberately one hue" — the
    page ships twelve multi-hue schemes of eleven anchors interpolated to 37
    bands (`web/app.js:41-59,90-99`), `--bg` is `#0a0b0d`
    (`web/index.html:83`), and `CLAUDE.md:21-27` says a single hue cannot
    separate the bands; measured minima today (`scripts/check_ramps.py`) are
    ΔE 6.5-8.9 and L 0.95→0.26-0.33.
  - `:8-10` "Nothing is fetched from a CDN at runtime ... no third-party
    dependency" — Google tag (`web/index.html:5`) and Nominatim
    (`web/app.js:776`).
  - `:32-33` "Copy `index.html`, `app.js` and `vendor/`" — omits `llms.txt`,
    `robots.txt`, `sitemap.xml`, `preview.png`; `scripts/deploy_verify.sh:40`
    copies all of `web/`.
  - `:21` h3-js **4.2.1** while 4.5.0 is current (npm `latest`, verified);
    the user's global rule is "always use the latest stable version".
- **Fix:** Rewrite the Colour section to point at `CLAUDE.md` design policy
  and `scripts/check_ramps.py` ("twelve schemes, each eleven OKLab anchors
  interpolated to 37 bands; adjacent anchors ≥ ΔE 6, lightness strictly
  monotonic; sea between space and darkest band"); fix "one font family";
  list the third-party endpoints; say "copy `web/` except README.md"; bump
  h3-js to 4.5.0 (the two names used, `latLngToCell`/`cellToBoundary`, are
  unchanged).

### DOC-13 — The Route panel hint describes an interaction the page does not have

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/index.html:373-375`:
  > "Click the chart to drop an origin, then click again for a destination.
  > The origin snaps to the nearest charted city, because only those 553 have
  > a computed surface."
  Code: the first click sets the **destination** pin (`web/app.js:689-698`);
  the departure changes only through the "Depart from X" button that appears
  when a listed city is within 80 km of the pin (`:673-686,705-714`), a
  city-label button (`:170-181`) or the Departure list (`:863-868`). Nothing
  "snaps" a click to an origin.
- **Why it matters:** This is the one paragraph that teaches point-to-point
  use, and it sends the reader down a two-click sequence that produces a
  destination pin on the first click and replaces it on the second.
- **Fix:** "Click anywhere on the chart to set a destination; the route from
  the current departure city appears below the legend. To depart from a
  different city, click its name on the map, pick it from the list above, or
  use the *Depart from …* button that appears when your click lands near a
  listed city." Drop "computed surface" and "charted"; make the count
  data-driven (DOC-4).

### DOC-14 — browser_verify.sh hard-codes 157 cities, 37 swatches and 12 schemes; deploy_verify.sh checks none of the page copy

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `scripts/browser_verify.sh:18-19,41`; `scripts/deploy_verify.sh`
  step 1 (`:9-37`) validates only file presence/lengths.
- **Why it matters:** The 553 build will fail `"cities":157` (a false red),
  while a 157 build with 553 copy passes (a false green). A verification
  script that encodes yesterday's numbers is the vacuous-test pattern
  `CLAUDE.md:48-51` warns about.
- **Fix:** In `browser_verify.sh`, fetch `index.json` once (`curl -s
  "$URL/index.json"`), compute expected cities = `len(origins)` and tints =
  `len(bandEdgesMin)+1`; count schemes from `Object.keys(RAMPS).length` via
  `agent-browser eval` instead of a literal. In `deploy_verify.sh`, assert
  the count in `dist/index.html` equals `len(idx["origins"])` (DOC-4) and the
  `solveRes` equals `config.SOLVE_RES` (DOC-5).

### DOC-15 — Data attribution is never visible without opening a closed panel; MapLibre's attribution control is hidden

- **Severity:** Medium  **Confidence:** Medium  **Status:** Needs manual validation (legal)
- **Where:** `web/index.html:97` hides `.maplibregl-ctrl-attrib`; credits are
  rendered only into `#credits` inside `<details id="key">` (`:403-414`),
  closed by default on desktop and, with every other panel, on phones
  (`web/app.js:950`). `web/app.js:145-147` renders "Name (licence)" pairs
  with no link to `openstreetmap.org/copyright`.
- **Authoritative source:** OSMF Licence/Attribution Guidelines — collapsing is
  allowed only "immediately with a dismiss interaction ... automatically on
  map interaction ... automatically after five seconds", and "If the
  attribution has been collapsed, the user must still be able to find the
  licence information ... from an '(i)' button in the corner of the map or an
  'About' option"; "Attribution must be to 'OpenStreetMap' ... make the text
  'OpenStreetMap' a link to openstreetmap.org/copyright"
  (https://osmfoundation.org/wiki/Licence/Attribution_Guidelines). Nominatim
  policy: "Clearly display attribution as suitable for your medium."
- **Why it matters:** The coastline and lakes on every frame are OSM/HydroLAKES
  data; the guideline's model is "shown, then collapsible", not "hidden until
  found". The "Sources and method" label does not signal that licences live
  there.
- **Fix:** Add a one-line credit strip in the bottom-right corner ("©
  OpenStreetMap contributors · GeoNames · HydroLAKES · GRIP4 · Wikipedia ·
  more") with `OpenStreetMap` linked to the copyright page, always visible on
  desktop and collapsible to an (i) after first interaction on phones; keep
  the full table in the panel. Rename the panel "Sources, licences and
  method".

### DOC-16 — README factual claims that no longer match the code

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where / contradiction:**
  - `README.md:26` "travel times from any location in the world" — origins
    are a fixed list (`data/origins.toml`); destinations are any land cell.
  - `:53` Natural Earth "lakes; borders; place names" — place names come from
    GeoNames (`emit/places.py`), drawn lakes from HydroLAKES
    (`emit/water.py:31`); Natural Earth lakes are used only to cut the land
    mask (`sources/landmask.py:24`).
  - `:55` OpenStreetMap "coastlines drawn on the map ...; rail route relations;
    upstream source of the GRIP4 road network" and `:58-61` "this pipeline
    never queries OSM directly" — it parses OSM PBF extracts with pyosmium
    (`sources/osm.py:47,68,116`) and downloads OSM water polygons
    (`emit/water.py:30,50-58`). The sentence was true before `59c3234`.
  - `:67-68` "No commercial flight data ... is used anywhere in this
    pipeline; `tests/test_licence_firewall.py` enforces that" — the test scans
    only `.json/.geojson/.toml` under `dist/` for five tokens
    (`tests/test_licence_firewall.py:11-14,30-38`) and skips when `dist/` is
    empty; it enforces "no provider fingerprint in shipped text", not "not
    used anywhere". `scripts/calibrate_ground.py` uses the commercial Google
    Routes API (for ground, not flights) — say so.
  - `:12` badge names GeoNames; the table does not (DOC-1).
- **Fix:** Reword each line to the current mechanism; add a "Commercial
  services used during calibration only" note (Google Routes, `GOOGLE_ROUTES_API_KEY`).

### DOC-17 — JSON-LD licence and provenance are incomplete for a mixed-licence derivative

- **Severity:** Medium  **Confidence:** Medium  **Status:** Needs manual validation (legal)
- **Where:** `web/index.html:55` `"license": "https://opendatacommons.org/licenses/odbl/1-0/"`
  for a `Dataset` that `emit/index.py:22-78` says derives from CC BY-SA 4.0
  (Wikipedia), CC BY 4.0 (GeoNames, HydroLAKES), ODbL (OSM, adsb.lol), CC0
  and public-domain sources. `:48-54` `isBasedOn` lists five of nine sources.
  `:46` "5,672 ferry crossings" has no source in the repo (the rail figure
  57,286 matches `emit/modes.py:9`).
- **Why it matters:** Declaring a single ODbL licence on a share-alike
  derivative of CC BY-SA text data is at minimum an unexamined choice; search
  engines surface the `license` field.
- **Fix:** Either declare the licence of *your* output explicitly (e.g. "ODbL
  1.0 for the isochrone data; see index.json attribution for upstream terms")
  and confirm compatibility, or drop `license` until decided. Complete
  `isBasedOn`. Emit the station/ferry counts into `index.json` at build time
  and have the page fill JSON-LD from it, or remove the numbers.

### DOC-18 — Spec status and decisions are stale with no "superseded" marker

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md`
  - `:4` "Status: Approved, pre-implementation".
  - `:14-15` "The site makes no runtime API calls" — Nominatim, Google tag.
  - `:46` D9 "Google Routes API (TRANSIT) for city↔airport legs" — used for
    DRIVE-mode ground-speed calibration instead (`calibrate/ground.py:74`).
  - `:47` D10 "AWS S3 + CloudFront" — nginx on a VPS (`deploy/`).
  - `:68-70,257` "Vite + React 19 + TypeScript" — vanilla ES modules
    (`web/app.js`).
  - `:73,98` "calibration.toml (fitted from FR24/FlightAware)" — adsb.lol
    (`calibration.toml:12`); D15 notes this but the diagram and table do not.
  - `:96,243` "Protomaps basemap ... `basemap.pmtiles` ~100 MB" — none; a
    static `water.pmtiles` (134 MB) instead.
  - `:125` "548,557 ... H3 resolution 5"; `:250-253` eleven bands; `:240-241`
    "0.5–1.5 MB" per origin (actual `dist/origins/abu-dhabi.pmtiles` 12 MB).
  - `:146-152` ground speed table (85/60/40/25/5) vs `graph/ground.py:25`
    (104/57/50/18/25/5, fitted); `:166-171` rail 250/80 km/h, 1.15 sinuosity vs
    `calibration.toml:110-114` (200/75, 1.2).
- **Fix:** Add at the top: "Status: implemented; superseded in part — see
  Decision Log addenda D16-D2x" and append the addenda (grid 6/7, 37 bands,
  adsb.lol, nginx, vanilla JS, water layer, Nominatim/GA, fitted ground
  speeds). Do not rewrite history in the body.

### DOC-19 — Implementation plan: 0 of 119 checkboxes ticked; the ledger says 11 of 15 tasks are complete and four were done outside the plan

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where:** `docs/superpowers/plans/2026-09-03-transport-pipeline.md` (3,646
  lines, `- [ ]` ×119, `- [x]` ×0). `.superpowers/sdd/2026-09-03-transport-pipeline/progress.md`
  marks Tasks 1-8, 11, 14, 15 "complete"; Tasks 9 (rail), 10 (ferry), 12, 13
  (calibration) have no completion line — rail/ferry/calibration landed via
  later commits (`9fc4dd1`, `2526673`, `calibration.toml:10-15`). The plan
  still specifies res 5 (`:16`), "10 edges, 11 bands" (`:19`), an FR24 sampler
  (`:2822-2848`), `emit/geojson.py` and `graph/ferry.py` (`:46,41`; neither
  exists — ferries live in `graph/build.py:279`), and
  `transfers.access_min(size, international, cal)` (`:2582`; the real API is
  `processing_min`/`disembark_min`/`border_min`). The ledger's last entry says
  "COMPLETE BUT UNCOMMITTED: I1 cache provenance" — still true: `git status`
  shows the four `sources/*.py` modified and
  `tests/sources/test_cache_provenance.py` untracked.
- **Fix:** Either mark the plan "Historical — executed 2026-09-03..09,
  superseded by the code" in its header, or tick the executed steps and strike
  the abandoned ones (FR24, Google TRANSIT). Close the ledger with the commit
  that lands I1.

### DOC-20 — Comments that describe behaviour the code no longer has (batch)

- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed
- **Where / what is wrong:**
  - `src/transport_maps/graph/transfers.py:5-9` and `:53-54`:
    `STATION_ACCESS_MIN`/`STATION_EGRESS_MIN` defined twice with "Not wired
    into build_graph yet ... Task 9 is blocked" — rail is wired
    (`graph/build.py:232-276`) and uses `calibration.toml` `[rail]`
    `boarding_min`/`alighting_min`; the constants are dead.
  - `emit/routes_json.py:38-39` "Rail nodes are added in Task 9, once
    NodeIndex grows a station_index and a .stations list. Until then" — both
    exist (`graph/nodes.py:54,105`); stations are deliberately not emitted
    (`emit/modes.py:8-10` explains why) — say that instead.
  - `graph/build.py:377-379` "Task 9's future station edges".
  - `scripts/calibrate_ground.py:47-48` "The shipped gazetteer is 7,342
    populated places, which is exactly the population of journeys the ground
    model is meant to predict" — `dist/places.json` is now 34,135 GeoNames
    rows (`emit/places.py:3-11` says "about 31,000"); the script samples from
    a different population than the comment argues for, which is a
    calibration-design change nobody wrote down.
  - `web/app.js:155,239` "7,000 objects / 7,000 trig calls" (34,135);
    `:531-532` "listing them would mean shipping 57,000 station nodes"
    (`emit/rail_detail.py` now ships the station and line per hover cell);
    `:722` "only the 157 cities".
  - `emit/airports_json.py:3` "3,983 rows" — `dist/airports.json` has 4,008
    (3,983 is the count *after* `nodes.py` drops 25 without a land cell).
  - `scripts/ground_check.py:5` "1,383 real journeys" and
    `sources/urban.py:6` "1,383 journeys" + "112 city-to-airport" vs
    `graph/ground.py:17` "2,998 real driving journeys" and `web/llms.txt:6`,
    `web/index.html:42,46` "2,998" — two sample sizes for the same fit; state
    which run produced the shipped table.
  - `emit/index.py:94-95` "The frontend fetches that ordering once from
    index.json" — from `hover_cells.bin` (URL given by `index.json`).
  - `sources/landmask.py:181-207` `_cells_touching` is unused
    (`land_cells()` still calls `h3shape_to_cells_experimental`); commit
    `ac191db` says "ready to replace" — either wire it or mark it so.
  - `src/transport_maps/__init__.py:1-2` scaffold `main()` printing "Hello
    from transport-maps!" (the console script is `cli:main`).
  - `emit/tiles.py:9-19`: the block argues for `MAX_ZOOM = 6` ("Do not raise
    this without re-measuring"), then two later paragraphs justify 7 and 8;
    `MAX_ZOOM` is 8. Rewrite as one paragraph with the current measurement.
- **Fix:** Correct each in place; delete the duplicate constants in
  `transfers.py`.

### DOC-21 — Separation threshold is stated as 8 in app.js and 6 in CLAUDE.md/check_ramps; by app.js's own criterion ten of twelve schemes fail

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `web/app.js:7-8` "below about 8 two bands are hard to tell apart
  at all", `:42-43` same; `CLAUDE.md:21-27` "adjacent ANCHORS need OKLab ΔE of
  at least 6"; `scripts/check_ramps.py:15-19` `MIN_DELTA_E = 6.0`. Measured
  today: muted 6.9, vivid 8.9, warm 6.5, ice 6.8, forest 7.0, mono 6.8, ember
  8.0, rose 7.3, sand 6.5, twilight 7.3, copper 6.8, lavender 6.8.
- **Fix:** Make `app.js` quote the rule that is enforced ("adjacent anchors
  ≥ ΔE 6 in OKLab ×100; ~7 is the ceiling for eleven anchors from near-white
  to near-black; `scripts/check_ramps.py`"), and note that the 37 *bands* are
  interpolated and therefore closer than the anchors.

### DOC-22 — deploy/README.md omits the web→dist copy step and the uncached asset classes

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `deploy/README.md:3-6` says `dist/` plus `web/` are rsynced but
  shows only `rsync -a --delete dist/ ...`; the actual sequence is
  `scripts/deploy_verify.sh:40-41` (`rsync web/ dist/` first). `:19` lists
  "html/js/json/bin/pmtiles"; `.css`, `.png`, `.txt`, `.xml` match no
  `Cache-Control` location in `deploy/worldmap.atik.kr.conf:42-71` and are
  heuristically cached — `vendor/maplibre-gl.css` is linked without a version
  (`web/index.html:80`) and changes with every vendor bump, which is the same
  mismatched-asset class the README warns about.
- **Fix:** Document `scripts/deploy_verify.sh` as *the* deploy command; add
  `css|png|txt|xml` to the `no-cache` location or version the CSS link.

### DOC-23 — User-facing copy: door-to-door is stated at the legend but not at the tooltip, the Route "Time" row, or the social/meta descriptions

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Rule:** `CLAUDE.md:37-39` "Say so wherever a figure is presented."
- **Where:** Stated: `web/index.html:343` legend caption, `web/app.js:556`
  route total, `:408-411` panel text. Not stated: pointer tooltip
  (`web/app.js:631`, "<b>5 h 20m</b> Tokyo, Japan"), Route panel "Time" row
  (`:663`), masthead (`web/index.html:333` "Hours to reach any point on
  Earth" — hidden on phones by `:285`), `<title>`/`og:description`/
  `twitter:description` (`:14,23,31` "Hours required to reach any point on
  Earth from 553 cities").
- **Fix:** Tooltip: `<b>5 h 20m</b> door to door · Tokyo, Japan`; pins row
  label "Door to door" instead of "Time"; meta/OG: "Door-to-door hours to
  reach any point on Earth ...".

### DOC-24 — Archaic diction works against ease of use

- **Severity:** Low  **Confidence:** Medium  **Status:** Confirmed
- **Where:** `web/index.html:338` "read a passage", `:406` "Reckoned from a
  planned departure", `:408-411` "The reckoning ... the arrival field ... a
  passage of five", `:374` "charted city", "computed surface";
  `web/app.js:960` "Tap the chart to read a passage." The Galton homage is the
  title; the instructions should be plain.
- **Fix:** "Move the pointer over the map to read a travel time. Click a city
  name to depart from it." / "Times assume you leave when you choose, so the
  first service is not waited for; onward connections are." / "the journey
  from the arrival airport into the city". Keep "Isochronic Passage Chart" as
  the name.

### DOC-25 — `--detect-shared-borders` is deprecated in tippecanoe; the MapLibre sky properties set under globe are inert except `atmosphere-blend`

- **Severity:** Low  **Confidence:** Medium  **Status:** Needs manual validation
- **Where:** `src/transport_maps/emit/water.py:105-108` `--detect-shared-borders`
  with a comment explaining it prevents hairlines — the felt/tippecanoe README
  marks `-ab/--detect-shared-borders` "DEPRECATED"
  (https://github.com/felt/tippecanoe/blob/main/README.md); re-measure whether
  the hairlines return without it before the flag disappears.
  `web/app.js:276-280` sets `sky-color`, `horizon-color`, `fog-color`,
  `fog-ground-blend`, `horizon-fog-blend`, `sky-horizon-blend` — MapLibre 5.0
  "Disable sky when using globe and blend it in when changing to mercator
  (#4853)" (CHANGELOG); under `setProjection({type:"globe"})` only
  `atmosphere-blend` has an effect. The comment "A faint atmosphere at the
  limb" is right; the other six keys are decoration.
- **Fix:** Note the deprecation next to the flag; trim `setSky` to
  `atmosphere-blend` (or comment that the rest applies only if the projection
  is ever switched to Mercator).

### DOC-26 — pyproject author email looks like a placeholder

- **Severity:** Low  **Confidence:** Low  **Status:** Needs manual validation
- **Where:** `pyproject.toml:7` `email = "01@0101010101.com"`; the JSON-LD
  creator (`web/index.html:47`) is "Jiyong Youn" with no contact.
- **Fix:** Confirm or replace; PyPI/`uv build` metadata will carry it.

### DOC-27 — web/README.md's MapLibre 6 warning cites a symptom, not the cause

- **Severity:** Low  **Confidence:** Medium  **Status:** Needs manual validation
- **Where:** `web/README.md:24-28` "pmtiles 4.x's `addProtocol` handler is
  called once for the source metadata and then never for tiles". The
  maplibre-gl 6.0.0 changelog documents the breaking changes that *are*
  verifiable: ESM-only distribution (`maplibre-gl.mjs`; UMD bundles no longer
  published; `import maplibregl from` must become `import * as`), WebGL2
  required, `Map` no longer extends `Camera`
  (https://github.com/maplibre/maplibre-gl-js/blob/main/CHANGELOG.md). Latest
  npm: maplibre-gl 6.9.0 (2026-09-09), 5.24.0 is the last 5.x; pmtiles 4.5.0
  is current and depends on `fflate ^0.8.2` (both verified against the npm
  registry).
- **Fix:** Cite the changelog items; keep the empirical note but label it
  "observed with 6.0.x on 2026-09-04, root cause not identified".

### DOC-28 — h3-py's `h3shape_to_cells_experimental` carries no API stability guarantee; the docs do not say the land mask depends on it

- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `src/transport_maps/sources/landmask.py:222` and the plan
  (`docs/superpowers/plans/...:235-236,305`). h3-py API reference: "this
  function is experimental and has no API stability gaurantees across
  versions"; `contain` accepts `center|full|overlap|bbox_overlap`
  (https://uber.github.io/h3-py/api_verbose.html). All other h3-py/h3-js
  names used in the repo are current v4 names (verified list: `latlng_to_cell`,
  `cell_to_latlng`, `grid_disk`, `grid_ring`, `cell_to_parent`,
  `cell_to_boundary`, `cell_to_children`, `cell_to_center_child`,
  `great_circle_distance`, `get_resolution`, `str_to_int`, `int_to_str`,
  `grid_path_cells`, `grid_distance`, `are_neighbor_cells`, `geo_to_h3shape`,
  `h3shape_to_cells`, `cells_to_h3shape`, `h3shape_to_geo`; JS `latLngToCell`,
  `cellToBoundary` returning `[lat, lng]` — matched by the swap at
  `web/app.js:338`).
- **Fix:** Pin `h3==4.5.*` in `pyproject.toml` (currently `>=4.5.0`) or
  finish the `_cells_touching` replacement (`landmask.py:181-207`) and note in
  the README that the cell universe is cached on `_params_hash` so a library
  change forces a rebuild only when the constants change (it does not today —
  add `h3.__version__` to the stamp at `landmask.py:176-177`).

---

## Library and policy verification (part 2 of the brief)

| Usage | Verdict | Source |
|---|---|---|
| `map.setProjection({type:"globe"})` (`web/app.js:272`) | Valid in 5.24.0 | maplibre-gl-js `v5.24.0/src/ui/map.ts`, globe example |
| `map.setSky({...})` keys (`:276-280`) | All seven keys valid; only `atmosphere-blend` acts under globe (DOC-25) | https://maplibre.org/maplibre-style-spec/sky/ ; CHANGELOG 5.0.0 |
| `map.getSky()` (`scripts/browser_verify.sh:38`) | Exists | Map API docs |
| Constructor `maxPitch`, `renderWorldCopies`, `attributionControl:false`, `dragRotate` (`:260-264`) | Valid | MapOptions docs |
| `fill-sort-key` layout (`:385-387`) | Valid | style spec layers |
| `pmtiles.Protocol()` + `addProtocol("pmtiles", proto.tile)` (`:24-25`) | Documented usage | protomaps/PMTiles js README |
| `scipy.sparse.csgraph.dijkstra(csgraph=, directed=, indices=int, return_predecessors=True)` (`solve/dijkstra.py:17-20`) | Valid; scalar `indices` → 1-D arrays, list → 2-D (matches `calibrate_ground.py:79-81`, `ground_check.py:50`); `limit`/`min_only` exist and are unused | docs.scipy.org 1.18 |
| `connected_components(csr, directed=True, connection="weak")` (`validate.py:176`) | Valid | docs.scipy.org |
| tippecanoe flags in `emit/tiles.py`, `emit/water.py` | All documented; `--detect-shared-borders` deprecated (DOC-25) | felt/tippecanoe README; latest release 2.79.0 |
| Nominatim usage (`web/app.js:773-842`) | Violates "Auto-complete search" clause; reverse-geocode label lacks attribution (DOC-3) | operations.osmfoundation.org/policies/nominatim |
| Google tag under the repo CSP | Would be blocked if the CSP were served (DOC-2) | developers.google.com/tag-platform/security/guides/csp |
| Licences in `README.md` table | GRIP4 CC-0 ✓, OurAirports public domain ✓, Natural Earth public domain ✓, osmdata water polygons ODbL ✓, adsb.lol ODbL ✓ (globe_history README), Wikipedia CC BY-SA ✓, Wikidata CC0 ✓; GeoNames and HydroLAKES CC BY 4.0 missing (DOC-1) | see DOC-1 |
| Pinned versions | `uv.lock`: h3 4.5.0, scipy 1.18.1, shapely 2.1.2, polars 1.44.1 (1.44.2 out), numpy 2.5.2 (2.5.3 out), ruff 0.16.5 (0.16.6 out) — lower bounds only, fine. `web/vendor`: maplibre-gl 5.24.0 (latest 5.x; 6.9.0 exists), pmtiles 4.5.0 ✓, fflate 0.8.3 ✓, h3-js 4.2.1 (4.5.0 current, DOC-12) | pypi.org / registry.npmjs.org |

---

## Final sweep

- **Broken links:** none. Every `http(s)` URL in `README.md`, `web/README.md`,
  `deploy/README.md`, `web/llms.txt` returns 200 (301 for
  `en.wikipedia.org/` and `www.wikidata.org/`, which redirect to their
  language/main pages). `README.md:19` `web/preview.png` exists (1200×630,
  matching `og:image:width/height`).
- **Badges:** `H3 res 6/7` matches `config.py`; `MapLibre 5.24` matches
  `web/vendor/maplibre-gl.js`; `Python 3.14` matches `.python-version`;
  `data-OpenStreetMap · Natural Earth · GeoNames` names a source the table
  omits (DOC-1). No version badge for pmtiles/h3 to go stale.
- **Licence/attribution completeness:** see DOC-1, DOC-3, DOC-15, DOC-17.
  `tests/emit/test_index.py` cannot catch the two missing CC BY sources.
- **Spelling and terminology:**
  - "colour" (CLAUDE.md, web/README.md, comments) vs "Color scheme" in the UI
    (`web/index.html:395`); pick one for prose (the CSS keyword is
    unavoidable).
  - "Departure" (panel title), "origin" (hint, code), "charted city",
    "departure city" (aria label, legend), "From" (pins) all name the same
    thing; recommend "departure city" in copy, `origin` in code only.
  - "passage" / "reading" / "travel time" (DOC-24); "chart" vs "map".
  - "hex" vs "cell": `llms.txt:56` "Hexagons", `:22-24` "cells";
    `README.md:37` "one cell past the shore" — fine, but define "cell" once.
  - "minutes" vs "hours": the readout shows min / h m / days h
    (`web/app.js:444-451`); masthead and meta say "hours"; `llms.txt:13`
    "expected door-to-door minutes". Say "times" in prose.
  - `<meta charset>` sits after the Google tag (`web/index.html:4-12`); still
    within the first 1,024 bytes, but convention (and some validators) want it
    first.
- **Process docs:** `docs/superpowers/plans` 0/119 boxes ticked (DOC-19);
  `.superpowers/sdd/.../progress.md` ends mid-fix-wave and is accurate about
  the uncommitted I1 work.
- **Numbers that are right and should stay:** 107,366 legs and MAE 9.3 min
  (`calibration.toml:14-15` ↔ `llms.txt:7`); 3,983 graph airports
  (`validate.py:14` ↔ `llms.txt:23`); 57,286 stations (`modes.py:9` ↔
  `index.html:46`); 37 bands (`index.html:42,144`, `browser_verify.sh:18`);
  12 schemes (`app.js:47-58`, `browser_verify.sh:41`); 4 LODs
  (`bands.py:155-160`, `index.html:42`); `og:image` 1200×630.

---

## Coverage

Every file below was opened and read in full unless marked otherwise.

**Rules and top-level docs:** `CLAUDE.md`; `README.md`; `web/README.md`;
`deploy/README.md`; `deploy/worldmap.atik.kr.conf`;
`docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md`;
`docs/superpowers/plans/2026-09-03-transport-pipeline.md` (lines 1-1400 in
full; Tasks 8-15 by heading, grep for calibration/firewall/emit claims, and
the Task 14/15 openings); `.superpowers/sdd/2026-09-03-transport-pipeline/progress.md`
(head, tail and every task-status line; the 43 per-task briefs/reports and
review diffs were listed, not read).

**Page and site files:** `web/index.html`; `web/app.js` (999 lines);
`web/llms.txt`; `web/robots.txt`; `web/sitemap.xml`; `web/preview.png`
(dimensions); `web/vendor/fonts.css`; headers of `web/vendor/maplibre-gl.js`,
`pmtiles.js`, `h3.js`, `fflate.js`, `maplibre-gl.css`; the three `.woff2`
(listed). Live: `https://worldmap.atik.kr/` headers for eight paths,
`/index.json`, `/llms.txt`, `/app.js` (diffed against `web/app.js`: identical),
`/` HTML city count.

**Config and data:** `calibration.toml`; `pyproject.toml`; `.python-version`;
`uv.lock` (locked versions); `data/origins.toml` (head, count, expand marker);
`dist/index.json`, `dist/places.json`, `dist/airports.json` (structure and
counts), `dist/hover_cells.bin` and `dist/origins/*` (sizes/counts),
`dist/index.html`, `dist/llms.txt` (diffed against `web/`).

**Source (all files under `src/transport_maps/`):** `__init__.py`, `cli.py`,
`config.py`, `validate.py`; `calibrate/__init__.py`, `calibrate/fit.py`,
`calibrate/ground.py`; `contour/__init__.py`, `contour/bands.py`,
`contour/grid.py`; `emit/__init__.py`, `emit/airports_json.py`,
`emit/borders.py`, `emit/hover.py`, `emit/index.py`, `emit/itinerary.py`,
`emit/modes.py`, `emit/places.py`, `emit/rail_detail.py`,
`emit/routes_json.py`, `emit/tiles.py`, `emit/water.py`; `graph/__init__.py`,
`graph/air.py`, `graph/build.py`, `graph/ground.py`, `graph/nodes.py`,
`graph/rail.py`, `graph/refine.py`, `graph/transfers.py`;
`solve/__init__.py`, `solve/dijkstra.py`; `sources/__init__.py`,
`sources/_utils.py`, `sources/airports.py`, `sources/countries.py`,
`sources/landmask.py`, `sources/osm.py`, `sources/roads.py`,
`sources/routes.py`, `sources/urban.py`, `sources/wikidata.py`.

**Scripts (all):** `scripts/adsb_extract.py`, `scripts/browser_verify.sh`,
`scripts/build_water_tiles.py`, `scripts/calibrate_ground.py`,
`scripts/check_ramps.py` (also executed read-only), `scripts/deploy_verify.sh`,
`scripts/expand_origins.py`, `scripts/ground_check.py`, `scripts/osm_rail.sh`.

**Tests consulted for doc claims:** `tests/test_config.py`,
`tests/test_golden.py`, `tests/test_licence_firewall.py` (first 60 lines),
`tests/emit/test_index.py:25-65`, `tests/web/test_ramps.py` (test names).
Other test files were not examined; they are not documentation.

**External sources fetched:** h3geo.org resolution table; uber.github.io/h3-py
API reference; pypi.org JSON for h3/scipy/numpy/polars/etc.; npm registry for
maplibre-gl/pmtiles/h3-js; maplibre-gl-js v5.24.0 `map.ts`, style-spec `sky`
and layers pages, CHANGELOG; protomaps/PMTiles js README; docs.scipy.org
`dijkstra`; felt/tippecanoe README and releases; OSMF Nominatim usage policy;
OSMF Attribution Guidelines; Google tag CSP guide; GeoNames readme/export;
HydroSHEDS HydroLAKES page; osmdata.openstreetmap.de water polygons; globio
GRIP4; ourairports.com/data; adsblol globe_history README; Natural Earth terms;
nginx `add_header` documentation.
