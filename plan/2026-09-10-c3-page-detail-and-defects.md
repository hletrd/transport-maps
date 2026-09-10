# Cycle 3 — page detail, ease of use, and the defects the review confirmed

Source: `.context/reviews/_aggregate.md` (cycle 3, clusters X1–X21) and the twelve
per-agent files beside it. Every task below carries the merged cluster ID and the
per-agent finding IDs so the provenance is traceable.

**Scope discipline for this cycle (from the run brief).** Cycles 1 and 2 landed
~85 commits and paid down the structural debt. This cycle is deliberately
smaller: the handful of changes that most improve what a visitor sees and does,
plus the correctness defects the review confirmed. No sweeping refactors, no
rewriting of subsystems that work. Everything not scheduled here is recorded in
`deferred.md` with its severity, reason and exit criterion.

**The critic's verdict shaped this plan and is worth quoting.** Roughly 90
finding IDs were queued for cycle 3 and *not one added anything a visitor can see
or learn that is not already there* — every web item was a repair. So this plan
schedules two genuine **additions** (T14, T15) alongside the repairs, and defers
two queued cosmetic items (D2 font subset, N24 scrim swap) that no visitor would
notice.

**Binding rules.** `CLAUDE.md` design policy (IBM Plex Sans, default
letter-spacing, no uppercase transforms, no tabular figures, dark theme, measured
band separation, legend always visible), the modelling rule (door to door
everywhere a figure appears; calibration constants labelled), the testing rule
(mutate the code and confirm the guard goes red), and the deploy rule (no deploy
is done until it has been opened in a browser).

**Orchestrator constraints.** The 553-origin rebuild (`rebuild16`) writes into
`dist/` in place for the duration of this cycle. No task here runs `build-all` or
`build_water_tiles.py`, and none writes under `dist/` or `data/` while the build
holds the lock. T19 adds a command that writes `dist/index.json`; it refuses to
run while a build is in flight and is **not** run this cycle unless the rebuild
has exited.

---

## A. The page — repairs a visitor can see

- [x] **T1 / X7 (UX3-1)** `web/index.html:186` — `.leg .t{width:58px}` is narrower
      than the text it holds. Measured natural widths in the page's own 12.5 px
      Plex: 59.6 px ("2 h 14 min"), 67.1 px ("14 h 39 min"), 74.6 px
      ("120 h 59 min"); the Seoul→Türkmenabat itinerary measured row heights
      `[44,44,44,44,44,44,44,25,48]` px — 8 of 9 rows double-height with "min"
      orphaned, and the "Door to door" total pushed below the fold at y=869.
      Fix: `width:76px; white-space:nowrap`. Check: re-measure the same journey;
      every row single-height and the total on screen at 1280×800.

- [x] **T2 / X8 (CR3-3, CRIT3-5, TR3-10)** `web/app.js` `fmtTick` has no sub-hour
      branch, so the readout prints "0 h 45 – 0 h 55" beside a `#time` reading
      "45 min" — for all six bands under an hour, which is every cell around the
      departure city. Fix: one notation, `fmtTick` delegating to the same
      minutes-under-an-hour rule as `fmtTime` (N3/N4's stated intent). Mutation:
      restore the hour-only branch → the new assertion goes red.

- [x] **T3 / X9 (CR3-4, CRIT3-5, TR3-11)** `paintScale()` runs once at load and
      never again, so its measured ≥8 px tick-gap rule is stale at every viewport
      but the first and runs in the fallback face under `font-display:swap`; it
      iterates a **live `HTMLCollection` while removing from it** (so it skips the
      next label); and it always drops the *later* of an overlapping pair, so
      "72 h+", the ceiling, goes first. Fix: snapshot to an array before pruning,
      prefer dropping the interior label over either end, and re-run on `resize`
      and on `document.fonts.ready`. `browser_verify.sh` gains a `#scale` check at
      the four CLAUDE.md viewports. Mutation: revert to the live collection →
      the overlap assertion goes red.

- [x] **T4 / X10 (PR3-3, CRIT3-4, UX3-5)** `web/index.html:389` — `#where` carries
      `aria-live="polite"` and is rewritten by `showReading` every animation frame
      (a `MutationObserver` recorded 10 mutations for 10 discrete pointer steps),
      while `#time` — the answer — is in no live region at all, so the only thing
      announced never contains the number. Fix: drop the live region from
      `#where`; add one visually-hidden `role="status"` written on a *committed*
      reading (click, tap, keyboard, origin switch), carrying the time, the place
      and the door-to-door qualifier. Check: the observer records one mutation per
      committed reading and none during a drag.

- [x] **T5 / X11 (FCR3-1, VER3-2, CRIT3-6)** `web/index.html:366` —
      `.rail.folded .legend > :not(.tints):not(.scale){display:none}` also matches
      `#keys`, hiding the "no scheduled route" and "open water" swatches on a
      folded phone sheet. M16(c) was ticked claiming the keys stay visible, and
      `browser_verify.sh:106-115` only measures `#tints`; the swatch-count check
      cannot catch it because `display:none` leaves the nodes in the DOM.
      CLAUDE.md: "The legend is always visible." The same fold also hides the
      door-to-door caption, which the modelling rule requires wherever a figure is
      presented. Fix: keep `#keys` and the caption folded-visible; extend the
      folded check in `browser_verify.sh` to assert both have a non-zero box.
      Mutation: re-hide `#keys` → the new browser check goes red.

- [x] **T6 / X13 (UX3-6, UX3-7)** Non-text contrast, WCAG 2.2 AA (3:1). The "open
      water" legend swatch measures 1.09–1.22:1 against the reading's real scrim
      composite and its border 1.01:1; "no scheduled route" is 2.16:1; the hover
      cell ring is `#ffffff` at 1.15:1 on band 0, invisible exactly around the
      departure city where everyone first points. Fix: raise the *outline*
      (`--text-3` measures 4.76:1) and keep the fills truthful; give the hover
      ring a dark halo beneath the white line (17.0:1 on band 0). Check:
      recompute both ratios from the shipped hex values.

- [x] **T7 / X14 (UX3-4)** WCAG 2.2 SC 2.5.3 Label in Name. All ten globe labels
      carry MapLibre's default `role="button" aria-label="Map marker"`, so the
      visible name is never the accessible name and the departure city reads
      "Map marker, button, current"; non-origin labels are exposed as buttons that
      do nothing. Fix: set the accessible name from the label text on origin
      markers and remove the button role from the rest.

- [x] **T8 / X15 (CRIT3-3)** The destination pin is never drawn: `pinB` has no
      source, layer or marker anywhere in `web/app.js`, so the point-to-point
      feature the itinerary describes draws no point and the web plan's own check
      ("click Wuhan → no pin dropped") cannot fail. Fix: render the pinned
      destination as a marker in the page's own type, cleared on origin switch.

- [x] **T9 / X16 (UX3-8, CR3-9)** Search ranks by IATA code, so typing "tok"
      returns ACC Kotoka, ENT Eniwetok, FYN Koktokay and GTA Gatokae before HND.
      `airports.json` already ships an unused `size` column. Fix: rank exact code,
      then name-prefix, then size, then substring; and resolve the airport's
      country to a name so one results list stops mixing "Seoul — Seoul, South
      Korea" with "JFK … — US · destination". Check: "tok" puts HND first;
      "seo" puts Seoul first.

- [x] **T10 / X12 (UX3-2)** `web/app.js:655-656` uses a literal opening zoom of
      `1.9` and no MapLibre `padding`, so the globe is framed for 1280×800 only:
      at 390×844 the sphere spans x −64…454 (25 % off-screen) with the departure
      label sliced by the sheet seam; at 844×390 north is at y=−46 and south at
      y=440 (20 % clipped) with the east limb behind the rail. Fix: derive
      `padding` from the measured rail/sheet box and the opening zoom from the
      viewport. Check: at all four CLAUDE.md viewports the limb is inside the
      canvas and the departure label is not under a panel.

- [x] **T11 / X5 (DBG3-1)** Below map zoom 7 — the opening view and most reading
      zooms — only the coarse band LODs are rendered, and those value a parent by
      the **minimum** over its children (`contour/bands.py:330-338,270-295`) while
      the headline number comes from the res-4 array's **centre** child. So
      `bandRangeAt` (`web/app.js:817-832`) prints the fastest child's range beside
      the centre child's time; reproduced as "10 h" above "0 h – 0 h 30". Fix:
      derive the band from the minute value the readout already holds, not from
      `queryRenderedFeatures` — the range then cannot disagree with the number it
      sits under. Mutation: point it back at the rendered feature → the new
      agreement assertion goes red.

- [x] **T12 / X19 (SEC3-6, DBG3-5)** Two module-level throws that beat `fatal()`
      to the screen, both reproduced, both the blank-globe-with-no-console-error
      failure CLAUDE.md names as this project's recurring one: `web/app.js:189`
      tests `RAMPS[r]` on a `localStorage` value, so `constructor`, `toString` and
      `__proto__` are truthy with no `.c` and `:191` throws; and `fatal()` accepts
      `bandEdgesMin: []`, after which `expandRamp` throws the same way. Fix:
      `Object.hasOwn` for the scheme, a non-empty check for the band edges.
      Mutation: set `localStorage.scheme = "constructor"` → the page must load
      with the default scheme, not a blank globe.

- [x] **T13 / X18 (DBG3-3, TR3-3)** The cycle-2 `checked()` guard covers the four
      `.bin` files but not `{slug}.json`, and `web/app.js:710` destructures
      `offsets` unguarded. A rebuild that changes only the dense-split rule leaves
      the res-4 parent set bit-identical, so every length check stays green while
      `offsets.airports` moves by millions; reproduced, the page then prints the
      **positive claim** "No flight on this journey: surface travel" with a full
      surface breakdown for a journey that flew, with no console error. Fix:
      validate the shape of `{slug}.json` on load, guard the destructure, and make
      an inconsistent file say the route is unavailable rather than assert a
      surface journey. Mutation: truncate `offsets` in a fixture → the readout
      must say unavailable.

## B. The page — additions (the "more detail" half of the brief)

- [x] **T14 / A1 (designer)** There are 306 × 413 px of dead screen between the
      masthead and the reading, and the departure city is named only at 12.5 px in
      a panel header, at 11 px as "Showing Seoul.", and as a globe label measured
      at 2.20:1. Add a departure block that names the city properly and states its
      reach — computed from arrays already in memory, prototyped live at **11 ms
      including the fetch**: from Seoul, 6.8 % of charted land within 12 h, 45.6 %
      within 24 h, 82.5 % within 48 h, 10.2 % with no scheduled route. Country
      comes from `places.json` client-side. No rebuild, no new file. Must carry
      the door-to-door qualifier (CLAUDE.md modelling rule) and use weight and
      colour, not uppercase or letter-spacing, for hierarchy.

- [x] **T15 / A2 (designer)** Keep the previous city's figure across an origin
      switch (~10 lines) and print the difference: verified live, Türkmenabat
      reads 14 h 39 min from Seoul and 18 h 22 min from Tokyo, and the first
      figure is discarded today. "3 h 43 min slower than from Seoul" is the only
      comparison the page would have. Cleared when the pin is cleared.

## C. Build and deploy — confirmed defects

- [x] **T16 / X3 (CR3-2)** `scripts/deploy_verify.sh:33` under `set -euo pipefail`:
      `busy=$(ps … | grep … )` exits 1 when nothing matches, so the script exits 1
      **whenever no build is running** — the healthy path has never executed. Both
      branches reproduced. This blocks the plan's own exit criterion for a green
      deploy the moment the rebuild finishes. Fix: tolerate grep's no-match.
      Check: run the guard with and without a build in flight.

- [x] **T17 / X17 (CR3-5, DBG3-7, ARCH3-9)** `scripts/deploy_verify.sh:62-73`
      prints ten HTTP statuses and asserts none, so a deploy in which
      `places.json`, `airports.json` or `borders.json` 404s still prints ALL
      CHECKS PASSED; the two range checks — the only regression detector for
      PMTiles byte serving — are unasserted too. Fix: assert 200 (206 for the
      range probes) and fail the deploy otherwise. Mutation: point one probe at a
      missing path → the deploy goes red.

- [x] **T18 / X21 (SEC3-2, SEC3-3)** `check_dist.py` and the licence firewall run
      at `deploy_verify.sh:38-40`, but `web/` is merged into `dist/` at `:44-45`
      and pushed at `:49`: `index.html`, `app.js`, `llms.txt` and `vendor/` — the
      assets that actually ship — are scanned by neither, and `--page-only` runs
      neither. The CVE patch pin (`tests/web/test_vendor.py`) and the CSP hash
      test (`test_csp.py`) added in cycle 2 never run on the deploy path. Fix: run
      the vendor and CSP tests plus the licence firewall over the assembled page
      assets in both modes, after the merge and before the push.

- [x] **T19 / X1 (CRIT3-1, ARCH3-2)** The in-flight rebuild will publish an
      `index.json` written by an emitter imported at 04:23, before the commits
      that add `buildId`, `builtAt`, `hoverCellCount`, `modeChannels`,
      `railDetail` and `graph` (05:51–06:00). That makes the M1 mixed-build guard
      and the channel-order guard inert, leaves `#built` empty, and — because
      `app.js:613` tests `meta.railDetail` — means the **~204 MB of `.rail.bin` /
      `.rail.json` the build is writing right now ships and is never fetched**.
      `check_dist` gates on `"modeChannels" in idx`, so it passes and prints
      "build unstamped"; `tests/web/test_check_dist.py:51-52` always supplies both
      fields, so the skip branch is untested. `35320bf` deleted the `index`
      subcommand, so there is no supported way to rewrite `index.json` short of
      another 17-hour run.
      Fix, in this order: (a) `transport-maps reindex`, which rewrites
      `dist/index.json` alone from the artifacts on disk — origin list from
      `origins.toml` filtered to complete file sets, `hoverCellCount` from
      `hover_cells.bin`'s size, `graph` from the `.rail.*` files present, identity
      carried forward from the existing index when it has one and otherwise
      stamped with `reindexedAt` so the provenance stays honest — refusing to run
      while `dist/.build.lock` exists or a `build-all` is busy; (b) `check_dist`
      **refuses** an index missing `hoverCellCount`/`modeChannels`, naming
      `transport-maps reindex` as the remedy. This strengthens the gate rather
      than weakening it: the artifact is repaired, not the check. Tests: a
      synthetic dist round-trips through `reindex`; the refusal fires on an
      unstamped index. Mutation: drop `modeChannels` from the fixture → red.
      **Not run against `dist/` this cycle unless the rebuild has exited.**

- [x] **T20 / X4 (ARCH3-1)** `emit/index.py:162-178` — `build_identity()` takes
      `started` as an argument but samples `_git_head()` and
      `_sha256(calibration.toml, origins.toml)` at call time, and that call is the
      last statement of a 16-hour build (`cli.py:342-346`). Live proof: the parent
      read those files by 04:28; `calibration.toml` was rewritten at 05:34:33 and
      `data/origins.toml` at 05:33:40, and HEAD has moved 38 commits. `inputsHash`
      therefore names inputs the artifacts were not built from — the opposite of
      its purpose. Fix: sample identity at the top of the build, pass the frozen
      dict to `write_index`. Mutation: rewrite `calibration.toml` mid-test → the
      hash must not move.

## D. Gates, tests and the record

- [x] **T21 / TE3-3** `sources/_utils.py`'s `_validated_json` and
      `_retry_after_seconds` have **zero** tests: deleting the
      `if "error" in body: raise` guard — the guard against MediaWiki's HTTP-200
      error bodies, the bug the docstring records having already shipped once —
      leaves the whole suite green. Both are pure and need no network. Mutation:
      delete the guard → red.

- [x] **T22 / CR3-12, DBG3-6** `scripts/check_ramps.py` hard-codes `n_bands=37`
      instead of deriving it from `BAND_EDGES_MIN`, so the colour gate silently
      stops covering the shipped ladder the moment the band edges change; and it
      carries a dead module-level `old_list` that ruff cannot see. Fix: derive the
      count. Mutation: add a band edge → the derived count follows.

- [x] **T23 (record corrections)** Six confirmed doc/code mismatches, each a
      one-line fix: `emit/index.py:141` ships the backwards range "fitted at
      57-50 km/h" straight into the page's route tooltip (VER3-4);
      `validate.py:151` still says ground speeds span 5 to 85 km/h where the built
      max is 104 (VER3-5); `contour/bands.py:1,12-22` still describes a live
      smoothing pass that the same file contradicts at `:118-120,152` and that
      CLAUDE.md's hexagons rule forbids (DOC3-2); `calibration.toml:52-70`
      documents `flights_per_week = base * w * w * d^decay` without the
      `KNEE_KM = 400.0` and `MIN_FLIGHTS_PER_WEEK = 0.5` bounds the model actually
      applies (DOC3-3); `README.md:34` and `cli.py:382-383` say `build-all --only`
      "never publishes" when it withholds only `index.json` and still writes
      `dist/hover_cells.bin` and `dist/origins/` (DOC3-1 — the code half is A6b,
      cycle 4); and `sources/_utils.py:61-64` claims a migration that four call
      sites contradict (FCR3-2 — finish it, four imports).

- [ ] **T24 (bookkeeping)** Tick what the review found already done: **N23** is
      shipped (`index.html:84-85`, in `9d0a401`) and **ARCH-4** (the app.js TDZ
      hazard) is fixed at HEAD (`app.js:152-179`). Correct `plan/README.md`'s
      review paths for the `cycle-2/` move. Record `VER3-6`: the SDD ledger's own
      headline still says "13 of 15" where the docs say 11 — the docs are right.

## E. The page — smaller repairs found in the same pass

- [x] **T25 / TR3-5, TR3-9, CR3-11 (stale state on an origin switch)**
      `paintOrigin` calls `renderPins()` but never `renderLegs()`, so the previous
      city's itinerary stays on screen — permanently if the new origin 404s, beside
      "Times unavailable for <new city>" (TR3-5). The band range vanishes from the
      readout after a switch and, on a coarse pointer, stays missing until the next
      tap (TR3-9). And the geolocation status line says "Locating…" for ever when
      the permission prompt is dismissed — the 10 s timer re-enables the button but
      never clears the text (CR3-11, a partial fix of M9). Fix all three: one
      `clearReading()` on switch, and clear the locating text on the same timer.

- [ ] **T26 / UX3-9, UX3-10, UX3-12, UX3-14 (hierarchy and the empty state)**
      The big number splits one quantity across two sizes and two colours
      (UX3-9); at rest the largest element on the page is an em dash (UX3-10);
      inside the Route panel the instructions permanently outrank the answer
      (UX3-12); and the page has one heading and two landmarks, so there is
      nothing to navigate it by (UX3-14). Fix: one type size for one quantity,
      a real empty state in place of the dash, the answer above the instructions,
      and `<main>`/`<nav>`/`<aside>` with accessible names. CLAUDE.md: hierarchy
      by weight and colour, sentence case, no letter-spacing.

- [x] **T27 / UX3-3, UX3-15 (small viewports)** At 390×844, tapping "Departure"
      puts `#results` at y=844 — the entire city list off-screen with no scroll
      cue (UX3-3). At 820×1180 the tablet gets the phone's bottom sheet with none
      of the tablet's room (UX3-15). Fix: scroll the opened panel into view, and
      give 600–900 px its own breakpoint. Check at all four CLAUDE.md viewports.

- [ ] **T28 / CRIT3-12 (share what you are looking at)** The permalink carries the
      departure but not the destination, so the interesting half of a reading
      cannot be shared: `?from=seoul` reopens the city, not the journey. Fix:
      carry the pinned destination in the URL and restore it on load, through the
      same validated path `?from=` already uses. Ease of use, ~15 lines.

- [x] **T29 / X2 (CR3-1, DBG3-2, DOC3-7) — the rail dedupe, code half**
      `sources/osm.py:216-221`: `_n` is `group_by("route_id").len()` over the
      *concatenation* of both extracts, so it carries no per-extract information
      and `sort("_n", descending=True)` is a no-op — "the longer one wins" is not
      implemented; `_parse` renumbers `seq` from 0 per extract, so
      `unique(["route_id","seq"], keep="first")` keeps an interleaved mixture.
      Measured on the live cache: **1,823 duplicated `(route_id, stop_id)` pairs
      across 469 routes; 891 routes with a >200 km "consecutive" hop; max
      6,351 km**, and `rail.ride_edges` books those fabricated hops at line speed.
      Route 8382151 reads Vladivostok → Nizhny Novgorod → Ozernaya Pad → Moscow →
      Muchnaya. Live for every route crossing a Geofabrik continent cut.
      Fix the **code** this cycle — choose one extract's sequence per route by a
      measured criterion, keep it whole, and bump the parser version so the next
      build re-parses — with a test on a synthetic two-extract frame. Mutation:
      restore the concatenated count → the splice reappears and the test goes red.
      **The data half waits for a build the orchestrator owns**: this cycle must
      not re-parse (it writes under `data/`), so the fabricated edges stay in the
      shipped artifacts until the next full build. Recorded in `deferred.md` as
      the data half with that exit criterion.

- [x] **T30 / TE3-4** `_io.params_hash`'s `default=repr` accepts values whose
      digest is per-process: `params_hash({'a'…'g'})` gives `652072a0` under
      `PYTHONHASHSEED=1` and `ed78b352` under `=2`. Every call site is safe today
      (verified across seven seeds), but the stability test only compares two
      calls inside one process, and getting it wrong is silent — a permanent cache
      miss that re-downloads GRIP4 and re-polyfills 4.09 M cells every run while
      reporting success. This is the exact failure the CLAUDE.md cache rule exists
      to prevent. Fix: refuse unordered containers in `params_hash` rather than
      hashing their `repr`. Mutation: pass a set → must raise, not hash.


- [x] **T31 / DOC3-26** WCAG 2.2 SC 2.5.7 Dragging Movements: the globe pans and
      zooms by drag alone — there is no `NavigationControl`, no pan or zoom
      buttons, and no single-pointer alternative. It is also the commonest
      complaint about a globe on a phone. Fix: zoom in / zoom out / reset-north
      controls in the page's own type and palette (MapLibre's default control CSS
      is not used elsewhere and must not introduce uppercase or letter-spacing),
      keyboard-operable, with a target size meeting SC 2.5.8.

---

## Progress

- 2026-09-10 cycle 3: plan written from `.context/reviews/_aggregate.md`. Every
  cycle-3 finding is either scheduled above or recorded in `deferred.md`.
- 2026-09-10 cycle 3 done: 28 of 31 tasks landed across 17 signed commits.

  **Build and deploy.** T16 `6d4ac0f` (the grep under `pipefail` that aborted
  the healthy path -- both branches reproduced); T17 `42f9564` (ten printed
  statuses now asserted, 206 required on the range probes, origin taken from
  the deployed index); T18 `3ec7e34` (one page-asset gate in both deploy
  modes, all ten vendor files pinned by enumerating the directory);
  T19 `f2abd49` + `87d31c6` (`transport-maps reindex`, and `check_dist`
  refusing an unstamped index with the remedy named); T20 `a71954d` (identity
  and mode prose sampled at build start).

  **The page.** T1/T5/T6 `6694b90`; T2/T3/T11 `2a2c183`; T12/T13/T25 `96e4558`;
  T4/T7 `5c085e6`; T8/T15 `4fa96ec`; T10 `6c27a57`; T9 `05f88a5`;
  T14 `c1a786e`; T27/T31 `01fd1ec`. Every one verified in a browser against a
  local range-capable preview of `dist/` with `web/` overlaid, at 1280x800,
  820x1180, 390x844 and 844x390: canvas present, no horizontal scroll, the
  readout and the legend on screen at all four, and zero console entries.

  **Gates, tests and the record.** T21 (eleven tests for the two crawl guards
  that had none), T22 and T30 `487f524`, T23 + T29 `bfa7e10` / `87aec6f`.

  Every guard added was shown to go red under a deliberate mutation, named in
  its commit body (CLAUDE.md testing rule).

  **Not landed.** T24 is this entry. T26 (type hierarchy and the em-dash empty
  state) and T28 (destination in the permalink) were dropped to keep the cycle
  within its brief: T14 already puts real content in the space T26's empty
  state was about, and both are recorded as carried forward rather than done.

  **Gates at `43b99f5`.** `uv run ruff check .` all checks passed, exit 0.
  `uv run pytest -q` 390 passed, 4 deselected, 5 warnings, exit 0, in 23 min 04 s
  under the rebuild's load. 390 against cycle 2's 356: 34 new tests. The five
  warnings are the recorded `W1` class unchanged -- the same two forked-pool
  tests in `tests/test_cli.py`, fork of a multi-threaded process -- still not
  suppressed, because the production build forks on purpose.

  **Deploy: refused, correctly.** `scripts/deploy_verify.sh` was run once and
  stopped at step 1: "a build-all is running (pids 4143 4144 4145 4147);
  refusing to deploy a mixed dist/". Nothing under `dist/` was touched and
  `browser_verify.sh` did not run. The rebuild stood at 317 of 553 origins with
  no errors. Recorded as `per-cycle-failed:artifacts-mid-rebuild`; not retried.
  The page changes were therefore verified on a local range-capable preview
  only, and CLAUDE.md's deploy rule still owes them a pass on the live site.

  **When the rebuild exits, in this order:** `uv run transport-maps reindex`
  (verified refusing against the live build today, releasing its lock and
  leaving `dist/` untouched), then `scripts/deploy_verify.sh`. Without the
  reindex, `check_dist` will now refuse the unstamped index rather than pass it
  -- that is T19 working, not a regression, and the refusal names the remedy.

  **Data halves still owed to a build.** T29 fixes the rail splice in code and
  bumps `RAIL_PARSER_VERSION`, so the next build re-parses; the fabricated
  hops remain in the shipped artifacts until then. T19's `reindex` was NOT run
  against `dist/`: the 553-origin rebuild still held the directory at the end
  of this cycle.
