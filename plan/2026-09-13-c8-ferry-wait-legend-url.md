# Cycle 8 — ferry wait model, zoom-aware legend, full URL state

Status: **in progress**
Source reviews: `.context/reviews/_aggregate.md` (11 reviewers, cycle 8)
Deploy constraint this cycle: `scripts/deploy_verify.sh --page-only` ONLY. No `build-all`,
no `scripts/build_water_tiles.py`, no writes under `dist/` or `data/`. The ferry model
therefore changes no live number this cycle — it changes what the orchestrator's pending
553-origin rebuild produces. TODO 2 and TODO 3 are page work and DO go live.

The three owner-injected TODOs are USER-1, USER-2 and USER-3. USER-4 and USER-5 are the
HIGH-severity defect and the cheap doc/provenance corrections the review turned up that are
safe to land under a page-only deploy. Everything else the review found is in the deferred
list at the bottom, with citation, unchanged severity and confidence, a reason, and an exit
criterion.

---

## USER-1 — Ferries get a frequency and expected-wait model

**Finding:** H8-1 (HIGH, 6 reviewers), M8-1, M8-2, M8-3, M8-5, L8-16, L8-18, plus verifier
vacuous mutation 6 and test-engineer's "deleting the ferry wiring leaves 12 tests green".

**Why it matters, measured.** `calibration.toml:145-150` is `speed_kmh = 35.0` /
`terminal_min = 30.0`. `graph/build.py:317` charges `60*km/speed + terminal_min + extra` and
nothing else, so the modelled *wait* is zero everywhere — the 30 min is terminal processing,
as the TOML comment itself says. Against the owner's eight published anchors the error runs
from +7 min to −689 h, median ≈ −47 h, i.e. 6 to 15 bands of the 1.1526 ladder.

### Design

Ferries keep no node of their own (`build.py:281-283` — correct, and it stays), so sailing
time, terminal time and expected wait all collapse onto the single per-crossing weight. That
is the right mirror of air's three-edge split given the different node topology.

**Sailing time, in priority order.**
1. The OSM `duration` tag where it parses. Coverage rises monotonically with distance —
   7.4% under 1 km to **66.7% at 1,000–4,000 km** — so it is densest exactly where the
   straight-line chord is worst, and it is measurement rather than inference. OSM gives the
   Tristan sailing as `duration=144:00` = 8,640 min against the model's 4,818.
2. Otherwise `60 * km * detour_factor / speed_kmh`. `detour_factor` is **FITTED against the
   observed `duration` tags** (a sailing rounds headlands and threads islands; the tracer
   measured the chord model at 0.71× of observed duration in the 150–400 km bucket, i.e. 29%
   fast). Fit it, record N, and report the residual by distance bucket.

**Frequency, in priority order.**
1. The OSM `interval` tag where it parses.
2. Otherwise a **distance-based prior FITTED to the eight published anchors**, since crossing
   length predicts headway across four orders of magnitude. Fitted here:

   `interval_h = 0.008915 * km ** 1.5137`   R²(log) 0.942, log-residual sd 0.679 (×1.97 at 1σ)

   | route | km | published h | prior h | ratio |
   |---|---:|---:|---:|---:|
   | Staten Island | 8 | 0.4 | 0.2 | 0.52 |
   | Dover–Calais | 42 | 1.5 | 2.6 | 1.70 |
   | Helsinki–Tallinn | 82 | 3.0 | 7.0 | 2.34 |
   | Naples–Palermo | 315 | 24.0 | 53.9 | 2.25 |
   | Arctic Umiaq Line | 372 | 168.0 | 69.4 | 0.41 |
   | Tórshavn–Seyðisfjörður | 508 | 168.0 | 111.1 | 0.66 |
   | AMHS Whittier–Yakutat | 513 | 168.0 | 112.8 | 0.67 |
   | Cape Town–Tristan da Cunha | 2793 | 1251.0 | 1466.7 | 1.17 |

**A random arrival waits half the headway.** Say so in the code rather than leaving the 0.5
unexplained; reuse the existing `expected_wait_min` arithmetic rather than writing a second copy.

**Bounds, both derived rather than tuned.**
- `KNEE_KM = 8.0` — the shortest published anchor. Below it the prior is extrapolation, so it
  is held flat at the anchor's value, exactly mirroring air's `KNEE_KM`. Without it a 1 km
  river crossing gets a 32-second headway.
- `MIN_SAILINGS_PER_WEEK = 0.1` — chosen so the whole crossing cost cannot reach
  `hover.MAX_MINUTES` (65,534): 50,400 min of wait plus the largest accepted sailing (8,640)
  plus terminal (30) plus a border crossing (45) is 59,115. This is the answer to the owner's
  "slow rather than infinite, and inside the band ladder": without it a correct Pitcairn wait
  (≈65,700 min, critic C12) overflows the sentinel and ships as "no scheduled route" while
  `check_coverage` still counts the cell covered. 0.1/week is one sailing every ten weeks,
  which sits BELOW Tristan's real ≈0.173/week, so no anchor is clamped by the floor.

**Seasonality.** `seasonal` and month-restricted `opening_hours` multiply the weekly frequency
by an in-service fraction, which is what a year-averaged expected wait means on a page that
carries no date. Published-figure defaults, not fitted. Time-of-day restriction is **not**
modelled and the plan says so: 879 of the 1,325 ways carrying `opening_hours` are
day-conditional and a real opening-hours evaluator is out of scope; `24/7` (131 ways) is
honoured as the positive signal that service is continuous. `seasonal`/`opening_hours` coverage
is **zero above 400 km**, so this affects short crossings only.

**Parser strictness.** Accept `HH:MM`, `H:MM`, `H:MM:SS`, bare minutes and ISO-8601 `PT…`
(99.7% of the 4,598 observed `duration` strings) and **reject** everything else rather than
guessing. `120:00` and `144:00` appear in the `duration` field but are weekly *intervals*
mis-tagged; accepting an `HHH:MM` duration books a five-day sail. Reject, count, and report.

### Tasks

- [ ] **T1.1** Create `src/transport_maps/graph/ferry.py` (ARCH8-1): move `FerryCalibration`
      and `load_ferry_calibration` out of `graph/rail.py:38-47`, move `MIN_FERRY_KM`/
      `MAX_FERRY_KM` out of `sources/osm.py:103`, and add `plausible_crossing`,
      `sailing_min`, `sailings_per_week`, `crossing_min`. Re-export from `rail.py` only if
      something outside the repo depends on the old path — nothing does, so do not.
- [ ] **T1.2** Hoist `MINUTES_PER_WEEK`, `NO_SERVICE` and `expected_wait_min` from
      `graph/air.py:8-11,55-60` into `graph/transfers.py` (the mode-agnostic home) and import
      them in both `air.py` and `ferry.py`. Do NOT duplicate the formula, and do NOT make
      `ferry.py` import `air.py` — air and rail import nothing from each other and that is
      worth keeping.
- [ ] **T1.3** Parse the tags in `sources/osm.py`: add `duration_min`, `interval_min`,
      `service_fraction` to `FERRY_SCHEMA`, with strict format acceptance and a rejection
      count printed by the loader.
- [ ] **T1.4** Add `FERRY_PARSER_VERSION` and thread it into `_ferry_cache_path` (M8-2). This
      is a **blocker**: without it the 30,629-row parquet is a cache HIT and the whole feature
      silently does nothing while every test stays green. Correct the cache-path docstring,
      which claims `MIN_FERRY_KM`/`MAX_FERRY_KM` govern the parquet's content (they do not;
      the length filter is in `build.py`).
- [ ] **T1.5** Fit `detour_factor` against the observed `duration` tags; record N and the
      per-bucket residual in `calibration.toml`.
- [ ] **T1.6** Write the `[ferry]` table with the provenance CLAUDE.md demands: which figures
      are FITTED and against what, which are published-figure defaults, where the two bounds
      live (naming the file, so this table does not repeat the `[frequency]` mistake of
      documenting an equation the model does not apply), and the residual spread.
- [ ] **T1.7** Charge the wait in `graph/build.py::_ferry_edges` via `ferry.crossing_min`, and
      stop inlining the formula there.
- [ ] **T1.8** Count and bound the silent drops (M8-3): 1,872 in-window links (12.4%) are lost
      today because an endpoint's cell is off the land mask, unlogged. Follow `_air_edges`'
      out-parameter pattern that commit `fcb4d2a` established, log a count per reason, and
      bound the dropped fraction.
- [ ] **T1.9** Record the critic's objections in the calibration comment rather than
      overruling them silently: the prior's ±1.97× spread, that it fixes only 41% of the
      Greenland error, that it invents ~10.6 h on Dalian–Yantai, that three of eight anchors
      share the same 168 h value inside a 140 km span and so carry the exponent, and that
      over-charging is silent while under-charging is loud.
- [ ] **T1.10** Emit `ferry` in `index.json`'s `graph` block (L8-18) and regenerate the ferry
      sentence in `emit/index.py::mode_detail` from the new calibration so the page cannot
      drift from the model.
- [ ] **T1.11** Tests, each proven by mutation: the terminal term (verifier mutation 6 —
      deleting `cal.terminal_min` left 132 tests green), that `build_graph` actually emits
      ferry edges (test-engineer: deleting the wiring left 12 tests green), every accepted and
      every rejected duration/interval format, the knee, the floor, the floor's
      `MAX_MINUTES` headroom, the seasonal derate, and the anchor residuals.
- [ ] **T1.12** Report the before/after modelled cost for all eight anchors and the
      door-to-door effect on at least one remote destination. Read the Greenland figure with
      critic C4 in mind: `airports.SIZE_BY_TYPE` excludes heliports and seaplane bases, which
      is 46 of Greenland's 60 scheduled-service airports (77%), so the ferry wait is not the
      only thing wrong there (DEF8-16).

---

## USER-2 — A more detailed legend as the map zooms in

**Finding:** H8-3 (HIGH, 3 reviewers), M8-13, M8-14, L8-17, L8-20, plus verifier vacuous
mutations 1 and 2.

**Why it matters, measured.** `TICK_TARGETS_MIN = [60, 300, 1440, 4320]` (`app.js:378`) is a
fixed constant, and `paintScale()` runs only on `resize` and `fonts.ready`. At 1280×800 on a
274 px strip the ticks are `1 h`@16.2%, `5 h`@45.9%, `24 h 30`@75.7%, `72 h+`@97.3%, and they
are byte-identical after zooming 1.9→11 while the readings actually on screen were
"0 min – 30 min" everywhere. About 98.6% of the strip described times absent from the view.

**Binding constraints (CLAUDE.md).** Ticks sit at their TRUE band boundaries — the bands are
equal width but the time scale is not, so evenly spaced labels would misstate it. The legend
stays visible and never folds into a panel. The "72 h+" ceiling stays. The folded phone sheet
keeps its keys and caption.

### Design

Sample the viewport for the range of readings actually on screen, then choose tick targets
from inside that range instead of the four world constants. Sampling reuses `lookup()`, the
same function that prints the number, over a small grid of viewport points — tens of lookups,
not 90,740 — debounced on `moveend`/`zoomend`.

Because the strip always spans all 37 bands at equal width, a three-band on-screen range
occupies ~8% of the strip and cannot hold five labels. So the zoomed legend does two things:
it moves the ticks to the true boundaries bracketing the on-screen range, and it marks that
range on the strip so the reader can see which part of the scale the map is using. The
existing `prune()` overlap pass stays, including its rule that the ceiling is never the label
dropped. At world zoom, where the on-screen range covers most of the ladder, the current four
targets are kept unchanged.

### Tasks

- [ ] **T2.1** Make `paintScale()` zoom-aware, with the on-screen band range derived from
      sampled readings and ticks snapped to true band edges.
- [ ] **T2.2** Mark the on-screen span on the strip, and name its two true boundaries.
- [ ] **T2.3** Re-run `paintScale()` on `moveend`/`zoomend`, debounced. No history entry, no
      per-pointer-move work.
- [ ] **T2.4** Keep the ceiling, the always-visible rule, and the folded sheet's keys and
      caption. Verify the folded sheet at 390×844 and 844×390.
- [ ] **T2.5** Close verifier mutations 1 and 2: the existing
      `test_the_legend_tick_rule_lands_on_true_band_edges` is a Python PORT of `paintScale`,
      so it pins tick selection and nothing `paintScale` does afterwards. Test the real
      function by executing it, the way `test_boot_behaviour.py` already executes `boot.js`
      under a Node DOM shim. Prove both mutations go red.
- [ ] **T2.6** Fix the address-search overflow (M8-13): `.results .coord{flex:none}` clips
      secondary address text with no ellipsis. This is the concrete form the Korean-name
      truncation concern takes; the Hangul fallback itself renders correctly.
- [ ] **T2.7** Fix the 1.8 px clip of the legend's trailing build-date line at 844×390 (M8-14).
- [ ] **T2.8** Correct two stale comments: `app.js:1757` says "eleven bands" where the artefact
      has 37 (the eleven are the scheme's anchors), and the `render()` benchmark comment was
      measured against 157 origins when there are now 553.
- [ ] **T2.9** Verify at 1280×800, 820×1180, 390×844, 844×390.

---

## USER-3 — The URL carries the whole current state

**Finding:** H8-4 (HIGH, 3 reviewers), plus verifier vacuous mutations 3, 4 and 5.

**Why it matters, measured.** `syncPermalink()` (`app.js:1064-1072`) is the only
`replaceState` in the file and carries `from` and `to` only. Verified live: changing the colour
scheme, the ocean colour, or the camera leaves the URL byte-identical. A fresh context opening
a copied link restores origin and destination but reverts scheme and ocean to their defaults
and replaces the camera with an auto-fit — `?to=` restore hard-codes `zoom: 4.2`
(`app.js:2898`). `$("copy-link")` copies `location.href`, so it copies none of it.

**Not persisted today:** the camera (centre, zoom, bearing, pitch), `rampName`, `oceanName`,
`lockNorth`, `namePlaces`, `pinB.label`/`pinB.geocoded` (so an address-searched destination is
renamed on restore), `lastFrom`, the search query, `<details>` open state, sheet folded state.

### Design

Extend `syncPermalink` in place. The architect's ARCH8-8 is explicit that extracting a URL
module first would mean exporting the mutable `active`/`pinB` bindings across a module
boundary or threading them through every call site — neither shrinks `app.js`, and a state
module is a separate, riskier refactor. In place is the minimal-risk seam.

Rules: readable parameters, not an opaque blob. `replaceState` on committed changes only, and
the camera debounced on `moveend` so a pointer drag writes once. Every new parameter is
validated the way `?from=` and `?to=` already are, and an unusable value is dropped with a
message rather than swallowed — the existing "No departure city called …" behaviour is the
standard to match for all of them. Scheme and ocean stay in `localStorage` as the per-viewer
default; the URL wins when present, because a shared link must look like what the sharer saw.

Camera precision is bounded deliberately: the URL is meant to be read, and five decimals of
latitude is already far finer than the 5.4 km cell the answer is drawn from. Bearing and pitch
are written only when they are not zero, so an unrotated globe keeps a short URL.

### Tasks

- [ ] **T3.1** Extend `syncPermalink` to carry scheme, ocean, the camera, and the settings that
      change what is shown. Omit anything at its default so the common URL stays short.
- [ ] **T3.2** Restore all of it on load, tolerating missing and malformed values without
      breaking the page, and saying so for a value that names nothing.
- [ ] **T3.3** Preserve the destination's label so an address-searched pin is not renamed on
      restore (tracer F13).
- [ ] **T3.4** Honour a URL camera instead of the hard-coded `zoom: 4.2` (tracer F12).
- [ ] **T3.5** Debounce the camera write on `moveend`; never one entry per pointer move.
- [ ] **T3.6** Make "Copy link to this journey" copy the full state.
- [ ] **T3.7** Close verifier mutations 3, 4 and 5 with a real round-trip test in both
      directions — writer and reader agree today only by coincidence of two string literals
      1,800 lines apart. Prove all three go red.
- [ ] **T3.8** Verify at all four viewports, and verify a copied link in a fresh browser
      context reproduces scheme, ocean, camera and destination.

---

## USER-4 — A missing reading-tier file must not blank the page

**Finding:** H8-2 (HIGH, reproduced live in a browser), M8-10.

`loadReadingParents()` (`app.js:1410-1425`) is documented "Not fatal", but it reaches its own
catch through `loadCells` → `fetchOk` (`app.js:41-45`), and `fetchOk` calls the global
`fatal()` on any non-2xx — which adds `body.fatal` (hiding `.rail` via CSS) and overwrites the
readout with "HTTP 404" *before* the exception unwinds into the "not fatal" handler. The DOM
damage is never undone.

This is dormant only because the shipped `index.json` carries no `readingRes`, so
`READING_RES` is null and `loadReading` returns at `app.js:1233`. **The orchestrator's pending
rebuild will advertise `readingRes` and arm it.** It is exactly the "blank globe, nothing in
the console" failure CLAUDE.md records as having shipped twice.

- [ ] **T4.1** Give the reading-tier parent fetch its own `fetch`/`r.ok` check, matching the
      correctly-written per-origin `.r6.bin` fetch beside it, so a 404 degrades to the res-4
      reading as documented.
- [ ] **T4.2** A test that fails if the parent fetch ever reaches `fatal()` again.
- [ ] **T4.3** Document the resolution-6 reading tier in `web/llms.txt` (M8-10), which itemises
      every other per-origin array by byte size and omits this one.

---

## USER-5 — Provenance and documentation corrections safe under a page-only deploy

- [ ] **T5.1** M8-11: `validate.py:14` cites an isolated-airport measurement taken at res 5
      while `config.SOLVE_RES = 6`. The same stale-measurement defect was already fixed in
      `sources/countries.py`, `sources/roads.py` and `emit/tiles.py` (DOC3-4/5/10) and missed
      here.
- [ ] **T5.2** M8-12: extend `scripts/check_dist.py::_pmtiles_metadata_leak` to check its
      already-decoded metadata text against the `FORBIDDEN` provider-token list, and add the
      binary suffixes to the licence firewall's scan. No forbidden token reaches a `.pmtiles`
      today — this closes a coverage gap, not a live leak.
- [ ] **T5.3** L8-1: correct `ground.haversine_km`'s docstring, which claims "rail and ferry
      use it" when `rail.py` has no `ground` import at all, and align `web/app.js`'s radius
      literal `6371` with Python's `6371.0088`. Deleting `rail._haversine_km` touches the rail
      build path and is deferred (DEF8-10).
- [ ] **T5.4** L8-5: guard `scripts/ground_check.py:51-54` against an infinite Dijkstra
      distance and against `np.median([])`.
- [ ] **T5.5** L8-8: restore "(cities15000)" to the GeoNames attribution in `emit/index.py`,
      which README.md calls canonical.
- [ ] **T5.6** L8-16: the historical pipeline plan names `graph/ferry.py`; USER-1 creates it,
      so note that the path is now real.

---

## Deferred findings

Every deferred item carries its citation, unchanged severity and confidence, a concrete reason,
and the exit criterion that re-opens it. No finding from this cycle's reviews was dropped.

The dominant reason is a repo rule plus a run constraint, quoted: CLAUDE.md's
**"Never deploy a partial `dist/`. The per-origin arrays and `hover_cells.bin` must come from
the same build"**, and this cycle's instruction to run `--page-only` and not to rewrite
`dist/` or `data/`. Anything that changes a *number the build produces* cannot be verified this
cycle, and landing it unverified alongside a 553-origin rebuild that is already queued is how
this project has previously shipped a blank map. Note that USER-1 is itself build-path work: it
is scheduled anyway because it is the owner's explicit request and the orchestrator has
arranged the rebuild to pick it up.

| ID | Finding | File:line | Sev | Conf | Reason | Exit criterion |
|---|---|---|---|---|---|---|
| DEF8-1 | H8-5 Four of five derived caches key on the source URL, not the bytes; each raw download is a bare `.exists()` | `sources/airports.py:23-41`, `landmask.py:51-58,171-180`, `roads.py:29-62`, `routes.py:257-264` | HIGH | High | Changing a cache key invalidates every derived parquet and forces a full re-download and re-crawl mid-rebuild | The pending 553-origin rebuild has completed and been browser-verified; then land it as the first change of the next cycle |
| DEF8-2 | H8-6 The per-route air frequency model never prices the route it describes; the wait is medianed per airport and capped at [75,100] min | `graph/build.py:162-212`, `graph/air.py:55-96`, `calibration.toml:49-81` | HIGH | High | Pre-existing and already tracked as B1; restructuring the air edges changes every published number and cannot be verified under a page-only deploy | A cycle whose deploy mode permits a full rebuild; fix `calibration.toml`'s claim in the same change |
| DEF8-3 | M8-4 4,819 `route=ferry` relations sit unread, with 37.6% `duration` coverage, 85.4% named, and an ordered terminal sequence | `sources/osm.py:111-142`, `scripts/osm_rail.sh:35` | MEDIUM | High | A strictly better source, but it needs a new parser AND a new node topology (a multi-stop service must stop paying N separate terminal charges). Too large to land safely beside USER-1, and USER-1 must not be delayed | USER-1 landed and verified in a rebuild; then relations supersede ways as the primary ferry source |
| DEF8-4 | M8-6 `check_bands_cover` uses a fixed `seed=0`, so all 553 origins sample the identical ~20,000 cells | `src/transport_maps/validate.py` | MEDIUM | High | Strengthening a gate changes build outcomes; a gate that newly fails mid-rebuild aborts the queued build | The rebuild has completed; land with DEF8-5 as a gates-only cycle |
| DEF8-5 | M8-7 `check_monotonic_ground` and `check_bands_cover` raise `ValueError`, not `GateFailure`, bypassing the clean worker exit; L8-6 `check_airport_connectivity` passes vacuously on empty `idx.airports` | `src/transport_maps/validate.py`, `cli.py:404-407` | MEDIUM | High | Same rebuild-safety reason as DEF8-4; both are always monkeypatched to no-ops in `tests/test_cli.py`, so the path is untested and a change is unverifiable without a real failing build | With DEF8-4, as a gates-only cycle after the rebuild |
| DEF8-6 | M8-8 Ground edges cross straits at up to 104 km/h while `_ferry_edges` deletes the ferry for the same pair; those crossings are attributed to a road channel | `graph/build.py:300-308`, `sources/landmask.py:183-213`, `graph/refine.py:35-54` | MEDIUM | Medium | Severity reduced by measurement: the 4,333 `ground_adjacent` drops are median 3.9 km and max 12.7 km, so the "drive around it" premise holds on length. The residual is attribution, and fixing it needs a land-mask change (centroid-on-land solving), not a ferry change | A cycle that revisits the land mask; the Messina-class counterexample is the test case |
| DEF8-7 | M8-9 `_crosses_antimeridian` misclassifies pole-containing cells, which `landmask` always seeds | `contour/bands.py:62-88`, `sources/landmask.py:137-146` | MEDIUM | Medium | Cosmetic today (those cells land in the unreachable band). Becomes a gate failure on correct data only if the `check_bands_cover` sample changes — which is DEF8-4 | Land with DEF8-4, since that change is what arms this one |
| DEF8-8 | M8-15 emit modules rebuild an origin-invariant 13.75 M-entry `cell_pos` dict 3–4× per origin (~6–7 CPU-hours/build); M8-16 `check_coverage` recomputes an Antarctica mask per origin (~33 min/build); L8-3 `_land_border_min()` re-parses the TOML per call; L8-19 `json.dump` for ~650 MB/origin and a doubled `_crosses_antimeridian` | `emit/hover.py`, `emit/modes.py`, `emit/itinerary.py`, `emit/rail_detail.py`, `validate.py`, `graph/ground.py:34-40`, `emit/tiles.py`, `contour/bands.py` | MEDIUM | High | Pure build-path optimisation with no user-visible change. A rebuild is imminent and touching the emit path now risks it for no benefit this cycle | The rebuild has completed; then a performance-only cycle, measured before and after |
| DEF8-9 | M8-17 `dist/` is a mixed build: 503 `origins/*.pmtiles` from 09-10, 45 from 09-12, 5 from 09-13, against a `hover_cells.bin` written 09-12 22:47; 50 orphan `*.r6.bin` deployed and dormant | `dist/` | MEDIUM | High | CLAUDE.md forbids me from touching `dist/` and this cycle's deploy is `--page-only`. Measured as length-consistent (725,920 B = 90,740 cells, matching `index.json`, and every per-origin array 181,480 B = 90,740 × 2), so the page is not blank — but equal counts do not prove equal ordering | The orchestrator's pending 553-origin rebuild republishes `dist/` from one build; the orphan `.r6.bin` files go with it |
| DEF8-10 | L8-1 `rail.py:61-65` duplicates `ground.haversine_km` | `graph/rail.py:61-65` | LOW | High | Deleting it changes the rail build path's numerics (identical formula, so the change should be a no-op — but "should be" is not verification under a page-only deploy). The false docstring and the JS radius drift ARE fixed this cycle as T5.3 | A cycle with a rebuild; assert the rail edge weights are unchanged to the bit |
| DEF8-11 | L8-2 Planar longitude difference cannot see across the antimeridian | `sources/urban.py:91-94`, `scripts/calibrate_ground.py:102-105` | LOW | High | The urban mask halves every ground speed inside it, so a change moves every ground number on the map | A cycle with a rebuild; report how many cells change urban status |
| DEF8-12 | L8-4 no sentinel-collision guard in `itinerary.py`; L8-9 `modes.py`'s `cell_class=None` fallback disagrees with how the graph was weighted; L8-10 `countries.iso2` falls through to ADM0_A3 against an ISO-2-keyed table; L8-11 the two reading tiers would disagree if `refine` became land-selective; L8-12 `EDGE_SLOTS_PER_CELL = 8` has no headroom by its own measurement and its message misdescribes an aggregate budget | `emit/itinerary.py:65-70`, `emit/modes.py:48-51`, `sources/countries.py:173-177`, `emit/hover.py:226-233,243-251`, `graph/ground.py:26-31` | LOW | High/Medium | All five are latent: each needs a precondition that does not hold today (65,535 airports, a direct `modes` caller, a `-99` Schengen member, a land-selective `refine`, a higher split fraction). None is reachable by a visitor | Whichever precondition first becomes reachable, or a hardening cycle after the rebuild |
| DEF8-13 | L8-7 `adsb_extract.py` joins a GitHub release `tag_name` into a cache path with no traversal sanitisation | `scripts/adsb_extract.py:107-110` | LOW | High | Single trusted hard-coded upstream repo; offline maintainer-only tool never run by the build or the site. Carried from cycle 3 | The script gains a configurable repo, or is ever invoked from CI |
| DEF8-14 | L8-13 `origins.toml` and `--only` validated only after the whole graph is built, and `load_origins` never checks `name`/`lat`/`lon`; L8-14 `osm_rail.sh` lacks `-e` so six of seven extracts still prints `[ALL DONE]`, and both readers raise only on an EMPTY directory | `cli.py:316-369`, `emit/index.py:92-120`, `scripts/osm_rail.sh:20-47` | LOW | High | Both are build-invocation ergonomics. The `-e` change in particular alters what a rebuild does on a partial download, and a rebuild is queued | After the rebuild; land together as a build-robustness cycle |
| DEF8-15 | L8-21 Cycle-7 security items not re-verified this pass: analytics endpoints versus the CSP's `connect-src`, security headers still not installed on the live host, stale build-host paths already baked into deployed PMTiles | `deploy/worldmap-security-headers.conf`, deployed `dist/origins/*.pmtiles` | MEDIUM | Low (unverified) | Quoted run constraint: "the nginx security-header snippet under `deploy/` is unapproved: change nothing on the server, install no packages there." The baked-in paths need a rebuild to clear | Owner approves the nginx snippet, and the rebuild republishes the archives |
| DEF8-16 | Critic C4: `airports.SIZE_BY_TYPE` excludes heliports and seaplane bases — 192 of 4,334 scheduled-service rows, including 46 of Greenland's 60 (77%) — with no comment, no label and no bound | `sources/airports.py` | HIGH | High | An airport-set change is a rebuild change and interacts with USER-1: fixing the ferry wait alone leaves Greenland walking across the ice cap, and fixing both at once makes neither effect attributable | The next cycle whose deploy permits a rebuild; land it AFTER USER-1 has been verified so the two effects can be read apart. USER-1's task T1.12 records the Greenland figure with this caveat attached |
| DEF8-17 | Critic C5: `MIN_FLIGHTS_PER_WEEK` is dead — it first binds at 14,395 km for a small–small pair, which `is_geographically_plausible` already rejects at 8,000 km — yet two files document it as live and a test exercises it at 19,000 km | `graph/air.py:63`, `calibration.toml:57-61`, `graph/build.py:29` | LOW | High | Documentation-versus-reality, not a wrong number: a bound that never binds changes no output. Correcting it belongs with B2, which moves both air bounds into `calibration.toml` | B2 (already open in `plan/2026-09-10-c2-docs-attribution-calibration.md`) |
| AA13 | L8-15 `emit/{borders,places,airports_json}.py` have no production caller while `check_dist.REQUIRED_EXTRAS` demands their output | `cli.py:26-34`, `scripts/check_dist.py` | MEDIUM | High | Already tracked in `plan/deferred.md`; re-confirmed at this HEAD rather than re-opened | Unchanged from AA13 |

### Not deferrable, and not deferred

The review produced no security, data-loss or correctness finding that is being deferred
without a repo rule permitting it. The two HIGH correctness findings that are deferred (DEF8-1,
DEF8-2) are both build-path changes whose verification requires a full rebuild, which this
cycle's deploy mode forbids; both name the rebuild as their exit criterion, and neither is a
regression introduced this cycle. The one HIGH finding that a visitor can actually hit —
H8-2, the blanked page rail — is scheduled as USER-4 and fixed this cycle.

---

## Progress

(updated as the work lands)
