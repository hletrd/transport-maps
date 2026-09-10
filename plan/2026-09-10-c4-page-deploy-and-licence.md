# Cycle 4 — the page a visitor reads, the deploy that is about to happen, and two licence obligations

Source: `.context/reviews/_aggregate.md` (cycle 4, clusters Y1–Y30) and the twelve
per-agent files beside it. Every task carries its cluster ID and the per-agent
finding IDs so the provenance is traceable to the review text. `.context/reviews/`
is not committed (`.gitignore:29`), so this file is the durable record.

**Scope discipline for this cycle (from the run brief).** Cycles 1–3 landed about
110 commits and paid down the structural debt. This cycle is smaller again: the
changes that most improve what a visitor sees and does, the three defects that
would otherwise break the deploy the orchestrator is about to run, and two licence
obligations that are not discretionary. No sweeping refactors. Everything not
scheduled here is in `deferred.md` with its severity, reason and exit criterion.

**What the reviewers found that shaped this plan.** Three things:

1. **The deploy sequence the cycle-3 plan wrote down cannot execute.** `reindex`
   will refuse (Y3), and if it did run it would publish an index `check_dist`
   then rejects (Y2) carrying today's constants under yesterday's hash (Y1).
   These three come first because nothing else ships until they land.
2. **Cycle 3's flagship addition prints a wrong number, in its largest type, to
   almost nobody.** The departure card's "10.2 % has no scheduled route from
   here" is a dataset constant — every city prints it — and 83.5 % of it is
   Antarctica (Y4); the card renders at one of five viewports tested (Y7).
3. **The OpenStreetMap credit cannot be seen without interacting with the page**
   (Y12), and that is not the owner judgement call `deferred.md:58` records it as.
   The OSMF guideline the deferral cites says the opposite of what the deferral
   says it says. It is reclassified here from deferred to scheduled.

**Binding rules.** `CLAUDE.md`'s design policy (IBM Plex Sans, default
letter-spacing, no uppercase transforms, no tabular figures, dark theme, measured
band separation, the legend always visible), the modelling rule (door to door
wherever a figure appears; calibration constants labelled fitted or default), the
testing rule (mutate the code and confirm the guard goes red), and the deploy rule
(no deploy is done until it has been opened in a browser).

**Orchestrator constraints.** The 553-origin rebuild writes into `dist/` in place
for most of this cycle. No task here runs `build-all` or `build_water_tiles.py`,
and none writes under `dist/` or `data/`. Two tasks (U21, U22) change emitters
whose output only changes at the next build; both say so.

---

## A. The deploy blockers

- [x] **U1 / Y3 (ARCH4-1)** `cli._other_builds()` has no CPU filter, so
      `transport-maps reindex` refuses the moment it is needed. It returned 16 pids
      at review time; eight (12633–12640) are orphans from a build killed on
      9 September — `ppid=1`, `stat=SN`, 0.0 % CPU, resident 18 hours — and
      `_reindex` (`cli.py:384-388`) refuses on any match. So when the rebuild exits
      and publishes its unstamped `index.json`, the command written in `f2abd49`
      for exactly that repair says "a build-all is running… wait for it" about
      yesterday's corpses, while `deploy_verify.sh` passes its own step 1 and
      `check_dist` refuses the deploy telling the operator to run `reindex`.
      `scripts/deploy_verify.sh:37-41,48` already carries the CPU threshold and the
      comment explaining why; the Python that duplicates it never learned it.
      Fix: apply the same threshold in `_other_builds`, and say in the refusal how
      many candidates were filtered. Mutation: drop the filter → a test with a
      synthetic 0 %-CPU process must go red.

- [x] **U2 / Y2 (CR4-2, ARCH4-2, FCR4-5)** `emit/index.py:226` hard-codes
      `"railDetail": True` with no parameter, so `reindex` prints "rail detail
      absent" and writes `true` in the same breath (`cli.py:411,426,450-452`
      computes `rail_seen` and uses it only for `graph.rail`). `check_dist.py:110,
      123-124` then reports one problem per origin and names `reindex` as the
      remedy — the command that caused it. On the page, `app.js:788` fetches
      `.rail.bin`/`.rail.json` per origin switch, two 404s each, and
      `browser_verify.sh:93` fails the deploy on any console entry matching
      `error|exception`. The test named for this asserts a different field:
      `tests/cli/test_reindex.py:85-88` is
      `test_rail_detail_is_false_when_no_origin_has_rail_files` and asserts
      `idx["graph"]["rail"] is False`; nothing checks `railDetail`.
      Fix: `rail_detail: bool` parameter on `write_index`, `rail_seen` passed
      through, `check_dist`'s per-origin length check extended to `.rail.bin` and
      `.rail.json` as its own docstring already claims, and the test corrected to
      assert what its name says. Mutation: hard-code `True` again → red.

- [x] **U3 / Y1 (CR4-1, FCR4-4)** `_reindex` carries `identity` forward
      deliberately — `cli.py:435-444`: "The identity of a build cannot be recovered
      from its artifacts, so it is carried forward, never invented" — and then
      `emit/index.py:214-233` writes `bandEdgesMin`, `solveRes`, `modeChannels` and
      `modeDetail` from the code and `calibration.toml` **as they stand at reindex
      time**. `write_index`'s own docstring forbids exactly this and
      `_build_all_locked` obeys it (that is T20); `_reindex` does not. A
      `BAND_EDGES_MIN` change therefore republishes a new legend over old pmtiles
      with the old `inputsHash` still attached, and `modeDetail` — the route
      panel's visitor-facing tooltips — describes constants the artifacts were not
      built with. Not hypothetical: the in-flight build read `calibration.toml` at
      about 04:28 and the file was rewritten at 05:34:33, which is the evidence T20
      was built on.
      Fix: `_reindex` passes `modes_detail=previous.get("modeDetail")` and warns
      when the previous index has none; and it refuses, naming the field, when the
      previous index's `bandEdgesMin`, `solveRes` or `modeChannels` disagree with
      the current code rather than silently overwriting them. Mutation: change a
      `[ground]` speed, reindex a fixture carrying `modeDetail` → the written value
      must not move.

## B. The page — the answer a visitor reads

- [x] **U4 / Y4 (CRIT4-1, CR4-6)** The departure card's headline is a dataset
      constant. `web/app.js:713-727` counts unreachable cells over *every* hover
      cell, so Seoul, Tokyo, London and Sydney all print exactly **10.23 %** "has
      no scheduled route from here", and **83.5 % of that is Antarctica**, which
      `validate.py:21-44` excludes by name for this reason. The same denominator
      dilutes all three reach figures: Seoul's "82.5 % within two days" is really
      **90.2 %**. It also contradicts `llms.txt:50` ("at least 90 % of
      non-Antarctic land") — the page says 89.8 %.
      Fix: exclude the same cells `validate.check_coverage` excludes, from a mask
      the emitter ships rather than a latitude the page re-types. Check: the four
      cities stop agreeing to three significant figures; Seoul's unreachable share
      lands near 1.85 %.

- [x] **U5 / Y5 (CRIT4-2)** On a phone, one tap scrolls the answer and the whole
      legend off screen. Reproduced at 390×844 on a clean load: `rail.scrollTop`
      297, `#time` at y=149 above the sheet top of 405, `#tints` and `#scale` gone.
      `app.js:1203` opens the Route panel and T27's `scrollIntoView`
      (`app.js:1526`) then scrolls the readout out from under the visitor.
      **CLAUDE.md: "The legend is always visible."**
      `browser_verify.sh` is structurally blind: it checks the legend on an
      unclicked page, checks a tap only when folded, and its `#time` check uses
      `offsetParent`, which stays truthy for a scrolled-out element.
      Fix: scroll only when the target is actually out of view, and never past the
      readout; make the browser check measure `#time`, `#tints` and `#scale`
      against the viewport box **after a tap** at 390×844. Mutation: restore the
      unconditional `scrollIntoView` → the new check goes red.

- [x] **U6 / Y6 (CRIT4-3, FCR4-1)** At 1280×800 an open itinerary covers the
      departure card, including the line carrying its door-to-door qualifier.
      `.depart-card` (`index.html:147`) is fixed at `top:104px` and grows down;
      `.reading` (`:166-167`) is fixed at `bottom:14px` and grows up; both are
      306 px wide in the same column at `z-index:6` and neither knows the other's
      height. Measured 43 px of overlap in a browser and 852 px of demand in an
      800 px column from the shipped CSS; the "16 h 41 min · Door to door" total
      also sits 15 px below its `max-height:34vh` box. Overlap band 701 ≤ H < 865,
      which includes the first viewport the deploy rule names.
      Fix: bound the reading so it cannot climb into the card, and let the card
      yield when a route is open. Then extend `browser_verify.sh`'s `overlap`
      predicate — it tests only mast/compass/rail, and neither element is in any
      pair — and run the viewport checks **after** the route click it already
      performs. Mutation: revert the CSS → the desktop assertion goes red.

- [x] **U7 / Y7 + Y11 (CRIT4-4, UX4-2, UX4-4, VER4-1)** The departure block renders at
      one of five viewports measured: `display:none` at 820×1180, 390×844, 844×390,
      320×800 and 1280×400, and absent in a default browser window
      (`innerHeight` 577). On a phone the departure city is then named exactly once
      outside the globe: 12.5 px, weight 400, inside a `<summary>` 218 px below the
      number. Half the cause is that **T27's tablet breakpoint was never written**:
      the task says "give 600–900 px its own breakpoint", `grep -n "@media"
      web/index.html` returns exactly three (`max-height:700px`, `max-width:860px`
      and its landscape variant), and `git show 01fd1ec -- web/index.html` adds no
      breakpoint at all. At 820×1180 the tablet gets the phone's bottom sheet
      verbatim, including `.depart-card{display:none}`.
      Fix: the 600–900 px breakpoint T27 owes, and a compact form of the reach
      figures that survives the phone. Check at all four CLAUDE.md viewports.

- [x] **U8 / Y8 (UX4-1)** A searched destination never writes the readout, so
      the page states two different answers at once and the bigger one is wrong.
      Reproduced: click Keene NH from Seoul, then type "JFK" and press Enter —
      `#time` (50 px) still reads `19 h 51 min`, `#where` still says "Keene… from
      Seoul", `#status` still says "Keene: 19 h 51 min", while `#legs` reads
      "Journey to JFK" with a door-to-door total of **17 h 17 min**. From a fresh
      load the same search leaves `#time` at `—`. Cause: `app.js:1434-1453` — the
      `data-geo` and `data-airport` branches call `renderPins(); renderLegs();` and
      never `showReading()`/`announceReading()`, unlike the map click at
      `:1193-1208`. Search is the only keyboard and screen-reader path to a
      destination, and the page advertises it. About six lines.

- [x] **U9 / Y22 (CRIT4-5) — the addition** There is no way to ask "how long to
      X". Typing "London" and pressing Enter on a Seoul page **departs from
      London**; cities are departures only. Put the door-to-door time from the
      active origin in the city list, in place of the lat/lon column nobody reads:
      all 157 origins resolve in **4.5 ms** from arrays already in memory (London
      15 h 15, Sydney 14 h 33, Buenos Aires 30 h 18). Must carry the door-to-door
      qualifier, and must use weight and colour for hierarchy — no uppercase, no
      letter-spacing, no tabular figures. Recompute the cost at 553 rows before
      shipping; if it exceeds one frame, rank lazily.

- [x] **U10 / T26 carried (UX3-9, UX3-10, UX3-12, UX3-14)** Carried from cycle 3
      for the second time, and now load-bearing: after U5 the Route panel is the
      only place a phone visitor's answer survives. The big number splits one
      quantity across two sizes and two colours; at rest the largest element on the
      page is an em dash; inside the Route panel the instructions permanently
      outrank the answer; and the page has one heading and two landmarks, so there
      is nothing to navigate it by. Fix: one type size for one quantity, a real
      empty state in place of the dash, the answer above the instructions, and
      `<main>`/`<nav>`/`<aside>` with accessible names.

- [x] **U11 / T28 carried (CRIT3-12)** The permalink carries the departure but not
      the destination, so the interesting half of a reading cannot be shared:
      `?from=seoul` reopens the city, not the journey. Carry the pinned destination
      in the URL and restore it on load, through the same validated path `?from=`
      already uses. About fifteen lines. While here, fix the designer's related
      note: an unknown `?from=` slug is silently swallowed *and* the URL rewritten.

- [x] **U12 / Y26 (FCR4-3) + Y28 (UX4-3)** Two things the visitor is looking
      directly at. (a) "Name the place under the cursor" does not govern the
      tooltip that follows the cursor: the setting is respected in `describe()` and
      `announceReading()` and ignored in `mousemove` (`app.js:1110-1116`), so
      unticking it switches the panel to `37.57°N 126.98°E` while the tip keeps
      saying "Seoul, South Korea"; and toggling it re-renders nothing, so on a
      coarse pointer it appears to do nothing at all. (b) `.legs` has computed
      `overflow-x: auto` (forced by `overflow-y:auto`), so the `::after` tooltip —
      the page's only gloss on an IATA code or a surface mode — is clipped by its
      own scroll box: 8 px of a roughly 40 px tooltip at 390×844 on Seoul→JFK, and
      cut at the panel edge on desktop.

- [x] **U13 / Y23 (TR4-3) + TR4-4** `#tip` is written only in `mousemove` and
      hidden only by `mouseout`; `paintOrigin` never touches it. Departing by
      clicking a globe label keeps the pointer on the canvas, so the previous
      city's door-to-door figure floats at the cursor beside the new city's
      readout — two numbers for one place. The other three switch paths are safe
      only by accident. One line, and T25 missed it. Same task: four of the five
      `paintOrigin` call sites guard on `slug !== active.slug` and the results-list
      handler (`app.js:1459`) does not, so re-picking the city you are already on
      refetches everything and wipes the reading.

- [x] **U14 / Y10 (FCR4-2, UX4-6)** `layoutForSize`'s large branch
      (`app.js:1619-1623`) never removes or hides `#sheet-toggle`, and
      `.sheet-toggle` has no `display` rule outside `@media (max-width:860px)`. On
      desktop the leftover renders as UA chrome (measured 264×6 px,
      `rgb(107,107,107)`, 2 px white border), takes a tab stop, announces "Collapse
      or expand the panel", and toggles a class whose every rule is inside that
      media query — so it does nothing. Reachable by rotating a tablet (two of the
      four CLAUDE.md viewports are on opposite sides of the 860 px line).
      `browser_verify.sh` never returns to a width above 860 px, so it cannot see
      it. Fix: one top-level `display:none`, and extend the browser check with a
      desktop → small → desktop sequence. Mutation: delete the declaration → red.

- [x] **U15 / Y24 (UX4-5)** T7's accessible-name fix is a no-op for every
      non-origin globe label: 29 of 29 plain labels at zoom 5.2 are still
      `role="button" aria-label="Map marker"`. Root cause in the vendored library:
      `addTo()` re-applies both attributes behind `hasAttribute` guards, and
      `nameMarker(el, null)` *removes* them at construction, before `addTo`. Origin
      labels survive only because their branch sets the attributes. WCAG 4.1.2.
      Fix: name the marker after `addTo`. Check: re-count the labels.

- [x] **U16 / Y14 (CR4-4, UX4-7, TR4-5, FCR4-6, VER4-6)** The announcement layer
      contradicts itself in five places, all from T4's incomplete landing.
      `#pins` still carries `aria-live="polite"`, so an origin switch announces the
      route block up to six times and every click announces twice. A failed origin
      is never announced — `#status` says "Loading travel times" for ever
      (`app.js:802-808` writes `#where` but not `announce()`). Airport and address
      picks never reach the live region at all — the only destination route that
      does not require pointing at the globe. While the sheet is folded `#status`
      is `display:none` (`index.html:421` matches it) and the click handler writes
      it *before* `unfoldSheet()`, so the reveal produces no mutation and nothing
      is announced. And the `role="status"` comment claims it "carries the number"
      when `announceReading` is called from exactly one site.
      Fix all five; one live region, written after the reveal, on every committed
      reading including failure. Check with a `MutationObserver` count per path.

- [x] **U17 / Y30 (CR4-5, DBG4-4)** Two unreachable-or-throwing states.
      The `{slug}.bin` failure path calls `renderPins()` but not
      `renderDeparture()`, so the departure card's "Travel times… are unavailable"
      string is unreachable and the card sits on "Reading the travel times…" for
      ever. And T13's shape guard stops one file short: `{slug}.rail.json`'s
      `stations` is dereferenced unchecked at `app.js:793`, so `railVia` throws out
      of the click handler on rail-served cells, leaving the previous destination's
      itinerary on screen. Mutation: truncate `stations` in a fixture → the readout
      must say unavailable, not throw.

## C. Two obligations that are not discretionary

- [x] **U18 / Y12 (DOC4-1) — reclassified from deferred** The OpenStreetMap credit
      cannot be seen without interacting with the page. `app.js:362` sets
      `attributionControl: false` and adds no control; the only credit line
      (`index.html:574`) is inside `<details id="key">` at `:557`, which has no
      `open` attribute, and on a phone `app.js:1592` closes even the one panel that
      does. The OSMF Attribution Guideline says verbatim: *"The attribution format
      should not require individuals to interact with the map or produced work to
      see the attribution."* Its three permitted collapse behaviours all presuppose
      the credit was shown first.
      **`deferred.md:58` (N22) defers this on the stated ground that "OSMF
      guidelines accept a collapsed credit behind a clearly labelled control".
      That premise is wrong**, so it is not an owner judgement but a mechanical
      requirement, and it is scheduled here. Fix: one permanently visible corner
      line, `Map data © OpenStreetMap contributors` linking to
      openstreetmap.org/copyright; the detail stays in the panel. Must obey the
      design policy — sentence case, default letter-spacing, dark ground, and it
      must not cover the legend at any of the four viewports.
      Source: https://osmfoundation.org/wiki/Licence/Attribution_Guidelines

- [x] **U19 / Y13 (DOC4-2)** Google Analytics ships with no privacy policy. GA
      ToS §7, verbatim: *"You must post a Privacy Policy … You must disclose the
      use of Google Analytics, and how it collects and processes data,"*
      satisfiable by a prominent link to google.com/policies/privacy/partners/.
      `grep -rni privacy web/` returns zero matches; the only disclosure is one
      clause inside the same closed panel as U18. A contract term, jurisdiction
      independent, and distinct from the blocked SEC-6 consent-banner item.
      Fix: a short privacy note in the page naming what is collected and linking
      to Google's partner-sites page, reachable without opening a panel.
      Source: https://marketingplatform.google.com/about/analytics/terms/us/

## D. The failure CLAUDE.md names as this project's recurring one

- [x] **U20 / Y9 (TR4-1, DBG4-1, ARCH4-4)** Three more routes to a blank or wrong
      globe with nothing in the console.
      (a) **No `map.on("error")` anywhere** — seven `map.on(...)` handlers, none for
      `error`. `index.json` and `hover_cells.bin` go through `fatal()`; all five
      per-origin fetches have `.catch`; `origins/{slug}.pmtiles` has nothing, and
      MapLibre's default for an unlistened `error` is `console.error` only. A
      missing archive, or a server that stops honouring byte ranges, gives a
      sea-coloured globe with a full legend, a working readout and no message.
      (b) **WebGL unavailable throws synchronously at `app.js:350`**, before the
      city list, the ramp picker, `layoutForSize()` and `paintOrigin()`, so
      `fatal()` is never reached and the shell stays up with an empty city list —
      and a `<canvas>` **has** already been created, so the deploy rule's "confirm
      the canvas exists" passes. The page owns the right sentence but it is in
      `<noscript>` (`index.html:583-596`), which cannot render when JS ran and
      WebGL did not. `await map.on("load")` (`app.js:365`) has no timeout, giving
      the same result silently.
      (c) **No `window.onerror`, no `unhandledrejection`, no watchdog.**
      Fix: an error handler on the map, a WebGL capability check that routes to
      `fatal()` with the sentence the page already owns, a load watchdog, and a
      boot guard. `script-src 'self'` means no CSP hash change is needed.
      Mutations: force `getContext("webgl2")` to return null → the page must say
      so; point an origin at a missing pmtiles → the page must say so.

## E. Gates, tests and the build

- [x] **U21 / Y17 (TE4-1…TE4-6, TE4-8, TE4-9)** Six tests that pass when the code
      is deliberately broken, demonstrated by mutation (eleven run, seven green).
      **TE4-1** `tests/web/test_ramps.py:60` cannot detect the literal it names —
      reverting `check_ramps.py:26` to `N_BANDS = 37` leaves all seven ramp tests
      green, and all three assertions are structurally blind (`37 == 37`;
      `len(expand(c))` compared with `expand`'s own default; a literal the test
      passes in). **T22's stated exit criterion is not satisfiable by this test and
      was never run.** **TE4-2** the `params_hash` seed test is a permanent green
      (deleting `_reject_unordered` leaves it passing); cycle 3's written spec was
      to compare the three cache *path names* across seeds. **TE4-4** dropping
      `"size"` from `emit/airports_json.FIELDS` keeps 93 tests green, silently
      restoring the search order T9 removed. **TE4-5** reverting the backwards
      "57-50 km/h" range keeps all 13 `test_index.py` tests green. **TE4-6** both
      cycle-3 page-load guards (T12's `Object.hasOwn`, T13's shape check) can be
      **deleted** with all 34 `tests/web/` tests green. **TE4-9** `validate.py:220`
      `weak`→`strong` keeps all 15 validate tests green because `_graph()`
      symmetrises every edge. **TE4-8** `tests/emit/test_index.py:181-189` writes
      to the tracked `calibration.toml`, so any concurrent `build_identity()`
      stamps `<head>-dirty` — the exact defect `a71954d` fixed — and a hard kill
      leaves the source modified.
      Fix each so the named mutation goes red, and record the mutation in the
      commit body. Where a test cannot be fixed in place (TE4-1's import-time
      binding), rewrite it against a parameter rather than deleting it.

- [x] **U22 / Y25 (CR4-3, TR4-2)** `check_dist` calls a `dist/` consistent in three
      states the page cannot survive: an `index.json` with no `bandEdgesMin`
      (`app.js` then `fatal()`s on load); a `{slug}.json` with empty `offsets` (the
      route panel silently disappears); and a res-5/res-6 mixture, because the
      res-4 parent count depends on the land mask rather than the solve resolution,
      so all 349 shipped arrays are 181,480 bytes and a stale array passes every
      length check. `offsets.airports` **does** move (13,751,643 at res 6 against
      about 635 k at res 5) and is the only per-origin build fingerprint, and both
      `check_dist` and the page discard it. Two free checks: cross-origin equality
      (all 349 agree today, byte-identical) and the bound `49·H ≤ n_cells ≤ 343·H`.
      Mutation: perturb one origin's `offsets.airports` in a fixture → red.
      **TE4-3** rides along, being the same file: the summary test asserted
      `bands == 1` from an expression it computed the same way the code does,
      and never called `main()`, so reverting the fix kept it green.

- [x] **U23 / Y15 (PR4-1)** `emit/borders.py:20,38-40` ships 15 significant digits
      for geometry already simplified to a kilometre. The first shipped vertex is
      `[-124.75886592699995,48.49401784300004]` — 38 characters for a point
      accurate to 1,100 m. Over the real file (515 features, 31,182 vertices):
      1,278,586 raw / **463,693 gzipped**; 5 dp gives 250,751 gz (−46 %), 4 dp
      gives 221,784 gz (−52 %). At the page's `maxZoom: 11` one pixel is 38.2 m, so
      4 dp is 0.29 px where the existing simplification is already 29 px.
      **213–242 KB off every cold load**, one line, no page change. Distinct from
      the deferred D13, which changes *when* it is fetched. **Takes effect at the
      next build**; the shipped `borders.json` is unchanged this cycle.

- [x] **U24 / Y16 (PR4-2) + Y20 (SEC4-1) + Y21 (SEC4-2)** Three things about what
      the deploy ships.
      (a) **42.7 % of `water.pmtiles` is at a zoom the page cannot request.**
      `emit/water.py:33` builds z0–12; `app.js:358` caps at `maxZoom: 11`, and
      MapLibre asks a vector source for `floor(mapZoom)`. Decoding the header, root
      and all 2,094 leaf directories: **366,690,691 bytes (42.7 % of the 858 MB
      tile section) is referenced only at z ≥ 12**. `MAX_ZOOM = 11` takes the
      archive from 867 MB to about 490 MB. Add the gate as **emitter-max ≤
      page-max**, not equality — the deferred L12's "check maxzoom against
      `emit/water.py`" would pass happily on 12 = 12. **Takes effect at the next
      water build**, which this cycle must not run.
      (b) **The build host's OS username and this repo's absolute path are on the
      live site now.** One unauthenticated `Range: 0-4095` GET of `water.pmtiles`
      returns its gzipped metadata carrying `/Users/<user>/…/data/cache/…` and the
      macOS launchd temp identifier, and `app.js:390` fetches that blob on every
      page load. `64ab007` fixed the **code**; the **artifacts** were not, and
      `water.pmtiles` is not produced by `build-all` at all. The running rebuild
      imported `emit/tiles.py` before the fix and is still writing the leak in 9 of
      9 sampled origin archives. The guard (`tests/emit/test_tiles.py:77-82`)
      builds a fresh archive with today's code, so it structurally cannot see a
      shipped file. `check_dist::_pmtiles_ok` already opens every archive and reads
      only the first 127 bytes — about nine lines from catching this.
      **Land the detector as a reported WARNING, not a failure**, because the only
      remedy is a water rebuild this cycle is forbidden to run and the leak is
      already live, so failing the gate would block a deploy on an unfixable
      artifact without reducing any exposure. Recorded in `deferred.md` with the
      exit criterion that it becomes a failure once the water tileset is rebuilt.
      (c) **`--page-only` publishes `web/` while its licence-firewall gate scans
      `dist/`.** T18 is ticked "in both modes"; only the full mode was — the vendor
      and CSP tests read `web/` directly, the firewall reads `config.DIST`. Proved
      two ways: `web/app.js` contains `countryName` three times and `dist/app.js`
      zero, so the gate scans 9-September copies; and the helper goes red when
      pointed at a `web`-shaped scratch tree. `--page-only` is *the* documented mode
      for a page fix while a rebuild owns `dist/` — today's situation.

- [x] **U25 / Y18 (DBG4-2) + Y19 (DBG4-3)** Two things the 553-origin build makes
      wrong the moment it publishes.
      (a) A ticked plan item was silently reverted. `plan/…-c2-web-ui-detail.md:123`
      ticks O4 ("more than a hundred cities" → "hundreds"). Git shows the round
      trip: `39a9b42` "553 cities" → `d84217f` "hundreds of cities" (the fix) →
      **`9d0a401` back to "more than a hundred cities"**, all five occurrences —
      the search snippet, both social cards, the JSON-LD name and the noscript
      block. `#n-cities` will render **553** directly under them. No test covers
      any of the five; add one.
      (b) Four duplicate origin *names* arrive with 553: Hyderabad, Suzhou, Fuzhou
      and Taizhou twice each (slugs disambiguated, names not); at 157 there are
      none. The list sorts by name so the pairs are adjacent rows, and
      `app.js:1149` gates the "versus" comparison — cycle 3's other addition — on
      `lastFrom.name !== active.name`, so it silently suppresses itself for exactly
      the pair a visitor is most likely to click, and would print nonsense if it
      fired. `scripts/expand_origins.py:78,96` already reads GeoNames' country code
      and the writer at `:105` throws it away. Fix both halves: disambiguate the
      displayed name, and gate the comparison on slug. The existing C11 covers only
      the picker-display half and was written when duplicates were hypothetical.

- [x] **U26 / Y27 (PR4-3) — reopens a deferral on new evidence** `deferred.md:47`
      records H14 as "2–5 ms measured", Low, "below the 50 ms trigger". The
      `.sort()` with comparator-side `rankAirport` landed **later**, in `05f88a5`,
      and the pathological query is the word *Airport*: six two-letter substrings
      each match about 99 % of the 4,008 names. Measured on one fast desktop core,
      airport stage only, no DOM: **"portland" costs 20.0 ms** across three
      keystrokes, "airport" 36.8 ms. Ranking once into a temporary before sorting
      measures 4.5× faster. With U9's and the 553-row city rebuild in the same
      synchronous `input` handler, a mid-range phone lands at 65–125 ms per
      keystroke — past the deferral's own exit criterion. Three lines.

- [x] **U27 (small, grouped)** Four one-line fixes the reviewers proved and nothing
      else covers: `check_ramps.py:169` rewrites `web/app.js` with a bare
      `write_text`, the only writer bypassing `_io.atomic_write` (SEC4-3);
      `app.js:1414` rounds the reverse-geocode cache key to 3 dp but `:1418` sends
      Nominatim the raw double (SEC4-4); `renderDeparture` uses `>= UNREACHABLE`
      where every other reader uses `>= MAX_MINUTES`, vacuous today and a trap for
      the next emitter change (DBG4-6); two assertions pinning the six surface
      mode names to `modes.CHANNELS` in the four places they live, of which only
      `MODE_NAMES` is pinned today (ARCH4-3); and the non-text contrast of T31's
      own controls, measured from shipped pixels at 1.08:1 fill and 1.40:1 border
      for zoom and compass over space, 1.08:1 and 1.30:1 for `#q` on the panel
      (UX4-10) -- WCAG 1.4.11 wants 3:1 on the boundary that identifies a control,
      and raising the border is a one-line change that cannot regress anything.

## F. The record

- [x] **U28 / Y29 + T24 carried** The documentation and record corrections, one
      commit. From the reviews: DOC4-3 (`emit/index.py:147` and `app.js:150` ship
      "Tertiary and local roads, **fitted** at 18-25 km/h" into the visitor-facing
      route tooltip, but `graph/ground.py:21-25` says the local 25 km/h is a
      **published-figure default** — CLAUDE.md's calibration rule, and
      `test_calibration_provenance.py` cannot see it because it reads only
      `calibration.toml`); DOC4-4 (`cli.py:491` still says `--only` "never
      publishes"; T23 is ticked and names `cli.py`, and `git show bfa7e10 --
      src/transport_maps/cli.py` is empty); DOC4-5 (`roads.py:116` "about 25x
      larger" is 7.5×, introduced by the commit that fixed DOC3-5); DOC4-6
      (`deploy/README.md:9-27` describes the script before T16/T17/T18 and
      prescribes the ordering bug T18 fixed — DOC3-14's exit criterion is due);
      DOC4-7 (the page claims SC 2.5.7 but **panning is still drag-only**);
      VER4-3 (`app.js:404-407`'s "17.0:1" ignores `line-opacity: 0.55`; the shipped
      composite is **4.19:1** — still clears 3:1, but the figure is 4× the
      delivered value); VER4-4 (`validate.py:150-153` carries res-5 minutes on a
      res-6 grid: 8.7 → **3.1**, 180 → **65**; T23 fixed the km/h in this very
      sentence and left the derived minutes); VER4-5 (`05f88a5`'s "measured in the
      browser" search order is wrong for `london` — LTN comes first under the
      commit's own name-length tie-break); VER4-7 (the Settings hint and `#map`'s
      aria-label still say drag/scroll only after T31); VER4-2 and VER4-8 (three
      promised regression checks do not exist: no `#scale` in
      `browser_verify.sh`, no `fmtTick` or `bandRangeOf` anywhere in `tests/` or
      `scripts/` — the code fixes are all present, the task text overstates);
      UX4-9 (six cycle-3 designer findings A3–A8 reached no `plan/` table,
      contradicting `plan/README.md:19-21`, and the designer's `A1…A8` collide with
      the build plan's `A1…A17` — rename); `deferred.md:113` (CRIT3-7 recorded as
      carried into T14, which shipped the departure card and never added the
      *Known limits* list); DOC4-8 (`schema.org/TravelApplication` 404s); DOC4-9 (the connection cap
      reads 55 min to 1 h 40, not "about an hour to an hour and a half");
      ARCH4-5 and TR4-7 (J3's exit criterion has fired — `app.js` is 1,689 lines
      against its 1,500 threshold — recorded, not acted on); ARCH4-6 (O6/E6's
      deferral reason conflates writing the `assets` subcommand with running it).
      Plus **T24 carried from cycle 3**: tick N23 (shipped in `9d0a401`) and ARCH-4
      (fixed at `app.js:152-179`, though ARCH4-5 notes its comment invariant is
      violated by seven declarations with no live TDZ), and record VER3-6 (the SDD
      ledger's headline says "13 of 15" where the docs say 11 — the docs are right).

---

## Progress

- 2026-09-10 cycle 4: plan written from `.context/reviews/_aggregate.md` (78
  findings, clusters Y1–Y30). Every cycle-4 finding is either scheduled above or
  recorded in `deferred.md` with its citation, unchanged severity and confidence,
  a concrete reason and an exit criterion.

- 2026-09-10 cycle 4 done: **all 28 tasks landed**, across 19 signed commits
  (`d291fca`…`0b9c3bc`).

  **The deploy blockers.** U1 `d291fca` — `_other_builds` had no CPU filter and
  counted eight orphans of a build killed the previous day, so `reindex` would
  have refused the moment it was needed. U2 `ee1325a` — `railDetail` was
  hard-coded `True`, so `reindex` printed "rail detail absent" and wrote `true`
  in the same breath, and `check_dist` then refused the result naming `reindex`
  as the remedy. U3 `b69d8b5` — `modeDetail` carried forward instead of
  re-derived, and a refusal when `bandEdgesMin`, `solveRes` or `modeChannels`
  have moved since the artifacts were built.

  **The page.** U4 `e833faa` (the departure card counted Antarctica, so four
  cities printed the same 10.2%; now 1.9%, and Seoul's "within two days" moves
  from 82.5% to 90.2%); U5, U6, U7, U8, U13, U14 and U15 in `9536f75`, with the
  browser gate that guards them in `cb0c97d`; U18 and U19 `099f55b`; U20
  `71aec12`; U12, U16 and U17 `87fd7e1`; U11 `f1b4a01`; U9 and U26 `4192d80`;
  U25 `1000bd3`; U27 `f8adfc7`; U10 `fe86c4a` — T26, carried twice, landed.

  **Gates, build and the record.** U21 `80947e5` (seven vacuous tests, each
  re-mutated after the fix); U22 `162aa38`; U23 `d70e194` (211 KB off every
  cold load); U24 `8f590ff`; U28 `0b9c3bc`.

  Every guard added was shown to go red under a deliberate mutation, named in
  its commit body (CLAUDE.md testing rule). Every page change was verified in a
  browser against a local range-capable preview of `dist/` with `web/` over it,
  at 1280x800, 820x1180, 390x844 and 844x390.

  **One defect introduced and caught inside the cycle.** U25's shared-name set
  was first written as an IIFE several hundred lines above the `cities`
  declaration it reads, so it threw in the temporal dead zone at module scope
  and left a blank page with an empty city list — CLAUDE.md's named recurring
  failure, reproduced inside the commit meant to guard against it, and caught
  by opening the page rather than by any test. Recorded because the lesson is
  which gate actually worked.

  **Two cycle-3 ticks the verifier found do not hold**, both scheduled and
  landed here rather than quietly corrected: T27's 600–900 px tablet breakpoint
  was never written (U7), and T3's promised `#scale` check did not exist (U5).

  **T24, carried from cycle 3 and closed here.** N23 is confirmed shipped
  (`index.html:84-85`, in `9d0a401`); ARCH-4 is fixed at HEAD
  (`app.js:152-179`), though the cycle-4 architect notes its comment invariant
  is violated by seven declarations with no live TDZ; `plan/README.md`'s review
  paths were corrected for the `cycle-3/` move; VER3-6 is recorded in
  `deferred.md` (the docs are right and the SDD ledger is a generated file).

  **Gates at `5683067`.** `uv run ruff check .` all checks passed, exit 0.
  `uv run pytest -q` **460 passed, 4 deselected, 5 warnings, exit 0**, in
  23 min 13 s under the rebuild's load. 460 against cycle 3's 390: 70 new
  tests. The five warnings are the recorded `W1` class unchanged -- the same
  two forked-pool tests in `tests/test_cli.py`, fork of a multi-threaded
  process -- still not suppressed, because the production build forks on
  purpose.

  **Deploy: refused, correctly, for the second cycle running.**
  `scripts/deploy_verify.sh` was run once and stopped at step 1: "a build-all
  is running (pids 4143 4144 4145 4146 4147); refusing to deploy a mixed
  dist/". Nothing under `dist/` was touched and `browser_verify.sh` did not
  run. The rebuild stood at 435 of 553 origins with no errors. Recorded as
  `per-cycle-failed:artifacts-mid-rebuild`; not retried, per the run brief.

  Worth noting because it is this cycle's own U1 working: the refusal names
  five pids, not the seventeen `ps` matches on this machine. Twelve are
  orphans of a build killed on 9 September, and before U1 the Python half of
  the same guard counted them -- so `reindex`, the command scheduled to run
  the moment this build exits, would have refused for them.

  The page changes were therefore verified on a local range-capable preview
  only -- `dist/` with `web/` overlaid, which is what the deploy assembles --
  at all four CLAUDE.md viewports, with `browser_verify.sh` reporting ALL
  CHECKS PASSED and zero console entries. CLAUDE.md's deploy rule still owes
  them a pass on the live site, and cycles 3 and 4 have now both ended that
  way: **the payload about to ship has never run in a browser against its own
  index.json**, which the cycle-4 critic named as the single biggest risk to
  this shipping well. Cycle 5's first task should be the reindex-then-deploy
  sequence, not new work.

  **Cycle-4 IDs carry the cycle number.** Cycle 3's designer used a bare
  `A1…A8`, colliding with the build plan's `A1…A17`, and six of those findings
  reached no table at all — the one gap in the audit `plan/README.md` records.
