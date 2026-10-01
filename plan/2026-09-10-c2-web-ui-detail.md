# Plan (cycle 2): page detail, ease of use, UI and accessibility

Source findings: `.context/reviews/_aggregate.md` sections M and N, O1/O4/O13
(page copy), Q1 (page half), plus every unfinished task carried from
`plan/archive/2026-09-10-c1-web-ui-detail.md` (C5, D8, D11, D13, C13, D2 subset,
D15, D16, D19, D4 semantics, D17; cycle 3: C1, C2, C3, C8, C11, D20, D13 lazy).
Per-agent detail: `designer.md` (UX-24…42), `critic.md`, `tracer.md` (T1, T2, T7),
`debugger.md`, `architect.md` (§4 C5, D13), `code-reviewer.md`,
`feature-dev-code-reviewer.md`, `perf-reviewer.md`.

Files: `web/index.html`, `web/app.js`, `web/llms.txt`, `scripts/check_ramps.py`,
`src/transport_maps/emit/index.py` (page-facing fields only).
Design policy in `CLAUDE.md` is binding for every change here. The live deploy
is gated on the orchestrator's rebuild (E1 data half); every task is verified on
the local preview (`http://127.0.0.1:8899/`, web/ overlaid on dist/) with
agent-browser at 1280×800, 820×1180, 390×844 and 844×390, then by
`scripts/browser_verify.sh` after the deploy when it is possible. The preview's
`dist/` is a mixed build (L1); readings on it are only trusted for the origins
the rebuild has finished (M1's guard makes the rest say "unavailable").

## Cycle 2 (this run) — bounded, S-effort, user-visible

Origin switch, races and failure states (one theme, ordered commits)
- [x] **M3** Hoist every module-level `let` the functions assign (`active`,
      `pinB`, `railDetail`, `airports`, `places`, `hoveredCell`, `addressSeq`,
      `reverseSeq`, the origin data) into one state block right after `meta`
      loads, before any function that assigns them (`app.js:739-742,816-820`).
      No behaviour change. Check: page loads; `browser_verify.sh` on the preview.
- [x] **M2 / C5** One `loadOrigin(o)` with `const gen = ++originGen`; every
      per-origin fetch (`.bin`, `.air.bin`, `.modes.bin`, `.json`, `.rail.*`) and
      the `.bin` `.catch` assign only when `gen === originGen`; one
      `AbortController` per switch, aborted at the top of the next (PR-8). The
      six origin globals collapse into one `origin` object. Check: delay
      `seoul.air.bin` by 3 s with a `fetch` wrapper, click Seoul then Tokyo;
      after 4 s the route for a Siberian click names Tokyo's airports.
      Mutation: drop the `gen` guard → Seoul's array lands last → wrong airports.
- [x] **M1** After each `arrayBuffer()`, refuse an array whose length is not
      `hoverCells.length` (× 6 for `.modes.bin`) and route `.bin` through the
      existing "Times unavailable" branch (`app.js:489-511`). Check: serve a
      `.bin` 20 bytes short → readout says unavailable, not a number.
- [x] **M4** At the top of the switch: `#time` "—", `#where` "Loading the times
      from X…"; restore the idle prompt when `.bin` lands with no pointer on the
      chart; re-run the readout for the last pointer position otherwise
      (UX-28, CRIT-7). Check: click London; `#where` names London within one frame.
- [x] **M5** `lookup()` tests land before load state (ocean never says
      "Loading…"); `renderPins` says "unavailable" when `hoverFailed === active`
      (TR-8, CRIT-14).
- [x] **M8** `fatal()` when `index.json` lacks `origins`/`bandEdgesMin`
      (DBG-6); **K10** page half: `fatal("index.json lists no departure cities")`.
- [x] **M9** Re-enable "Start from the city nearest me" on a 10 s timer as well
      (DBG-7). **M13** Close panels only on the first entry into the small
      layout, not on every orientation change (DBG-12).

Touch and the legend (a standing CLAUDE.md rule)
- [x] **M16 / C13** (a) `map.on("click")` writes `#time`/`#where` through the same
      `showReading(lat, lng)` the pointer uses; (b) a click unfolds the sheet
      (`rail.classList.remove("folded")`, `aria-expanded`); (c) the `#tints`
      strip (and the two keys) stays visible while the sheet is folded — keep
      `.legend` as a sibling of the fold or render it inside `.sheet-toggle`;
      (d) `fatal()` raises the readout above the sheet (CRIT-15, M14).
      Check at 390×844 and 844×390: fold, tap land → `#legs` visible, `#time`
      shows the tapped cell's value, `#tints` bounding box on screen in both
      states. `browser_verify.sh` gains the folded-sheet check.

Labels and affordance
- [x] **N1** Place the active origin's label first regardless of gazetteer rank
      (Seoul is rank 22, budget 18) and mark it `aria-current`; keep the
      collision filter (UX-24). Check at 1280×800 after load: a `.lbl.origin`
      whose text is the active origin exists.
- [x] **N2** Non-origin labels are not click-through targets (`pointer-events:
      auto` + `stopPropagation`, or excluded from the opening budget); origin
      labels carry a visible affordance (a 4 px dot); the "Depart from" button
      for a gazetteer label within 80 km says the *origin's* name (CRIT-6,
      CR-11). Check: click "Wuhan" at the opening view → no pin dropped.
- [x] **N13** Keep the current zoom when switching origin from a label or the
      "Depart from" button if the new origin is on the near side; only recentre
      (CR-10).

One time notation (D19) and the legend
- [x] **N3 + N4** One `fmtTime` for the readout, tooltip, pins, legs *and the
      legend ticks*: minutes under an hour ("45 min"), "5 h 11 min" to 48 h,
      hours beyond ("51 h", days in `title`); the legend prints the true edge
      ("3 h 45", "7 h 45", "16 h", "24 h 30", "50 h", "72 h+"), puts the unit
      on the first tick, enforces a measured ≥ 8 px gap and right-anchors the
      last label; prefer an exact-hour edge (5 h = 300) when it is within the
      same log distance as the nearest edge (CRIT-5, DBG-5, UX-35, UX-33,
      DOC-13). One noun each: "map" for the surface in instructions, "travel
      time" for the quantity, "journey" for a route; "no scheduled route"
      everywhere the grey is named; "Open water" everywhere the sea is named;
      "by air, rail, road and ferry". Raise the disclaimer, keys and ticks to
      11 px (CRIT-16). Check: every `.tick` label equals `fmtTime(data-min)`;
      `#time` and `.pins .val` use the same string for the same value.
- [x] **N5** Per-scheme `uncharted` grey chosen so ΔE ≥ 8 from every one of the
      37 bands (Mono gets a cool low-chroma tone); `scripts/check_ramps.py`
      measures `min ΔE(uncharted, bands)` per scheme and the sea-vs-space /
      sea-vs-darkest-band constraints the README and CLAUDE.md say it measures
      (UX-26, DOC-10, CRIT-19); `tests/web/test_ramps.py` compares the sea
      against `SPACE`, not `BG`; `web/README.md` drops "every scheme rotates
      hue" or Mono is dropped. Mutation: set Mono's grey back to `#4a4d50` →
      `check_ramps.py` exits 1.

Search, results and copy
- [x] **N12** Diacritic folding on both sides of the city and airport match
      (`normalize("NFD")` + strip marks, fold `ı/İ`) (CR-5). Check: "Sao
      Paulo" and "Zurich" match.
- [x] **N8 / D8** "No charted city or airport matches "…". Press Enter or
      Search address to look it up." when the local list is empty; "Type at
      least three characters." for a short address query (UX-30).
- [x] **M6** Restore the `$("q").value.trim() !== q` guard in `searchAddress`
      and drop the second `box.append(ul)` (DBG-4). **M7** `Array.isArray(hits)`
      before iterating (CR-13, DBG-13).
- [x] **N11** Address and airport rows are tagged "· destination"; the hint reads
      "Enter picks the first match: a city to depart from, an airport or
      address as destination" (CRIT-8, UX-41).
- [x] **D11** One "Route" heading; the time shown once in the panel (the pins
      row carries it; the legs total does not repeat it) (UX regression note).
- [x] **O1** Sources panel and `llms.txt`: "connections are charged the minimum
      connection time or the expected wait, whichever is longer, capped at the
      cost of leaving and re-entering the terminal (about an hour to an hour and
      a half); rail and ferry legs carry no wait"; "a gravity model hand-fitted
      to two anchor routes" (CRIT-2, DOC-19). **O13** "door to door" in the
      meta/OG/Twitter descriptions (CRIT-22).
- [x] **O4 (page half)** "from more than a hundred cities" instead of "hundreds"
      (true at 157 and 553); JSON-LD `measurementTechnique` loses the airport /
      station / ferry counts and states the h3 v4 sizes (O3); the Sources panel
      prints "Data built on <date>" when `index.json` carries `builtAt` (the
      emitter half is in the build plan); `llms.txt` "about 98 %" → the 90 %
      gate wording (CRIT-9, CRIT-10, CRIT-11, DOC-11).
- [x] **N21** `mode_detail()` prints "200,000" not "200,000.0" and the road
      tooltip says "motorways and expressways" without "GRIP4 class 1"
      (CR-8; the rail/ferry figures read from the calibration object — B2 in
      the docs plan).

Controls, focus, tooltips, semantics
- [x] **N6** Focus ring inside the row (`outline-offset:-2px`) or padding on
      `.results` so the ring is not clipped (UX-27).
- [x] **N7** `.qrow .btn{flex:none;white-space:nowrap}`; the hint yields
      (UX-29).
- [x] **N9 / D15** Tooltip flips above the pointer when it would overflow the
      bottom edge (UX-31).
- [x] **N18 / D16** Origin-label buttons get a 24 px hit area via padding and
      negative margin; scheme rows 24 px; sheet handle 28 px (UX-39).
- [x] **N20** One radius token; `.pins .depart` styled as `.btn` and in the
      focus-visible list; compass needle grey → `var(--text-3)`;
      `type="button"` on generated buttons (UX-42).
- [x] **N10 / D4 (semantics)** `tabindex="-1"` on `.lbl.origin`; roving tabindex
      with `role="listbox"`/`"option"` on the results and `aria-activedescendant`
      on `#q`; `#ramps role="radiogroup"` with `role="radio" aria-checked`;
      `aria-live="polite"` on `#where` and `#pins`; `#map` → `role="application"
      aria-roledescription="globe"`; Escape with a route open clears it (UX-32).
      Check: `document.querySelectorAll("[tabindex='0'],button,input,summary,a")`
      from `#q` to the Route summary is under 10 stops.
- [x] **N14** Above ~250 km show coordinates only; when unreachable print "No
      scheduled route · <place>" without "door to door" (UX-34).
- [x] **N17** `<link rel="icon">` with an inline SVG (UX-38).
- [x] **M12** `?from=<slug>` read before the first paint (unknown slugs
      ignored); `history.replaceState` on every origin switch (CRIT-13).
      Check: open `/?from=tokyo` → `#origin-name` Tokyo.
- [x] **M11 + Q1 (page half)** Return early on a water/unreachable click (no
      Route panel, no Nominatim); reverse-geocode at most one request per
      1,100 ms across search and reverse with the latest click winning; cache by
      rounded coordinate; print "address by Nominatim © OpenStreetMap
      contributors" beside the reverse-geocoded label (SEC-18, CR-12).
- [x] **D17** Closed: 0 console entries across load, hover, click, three
      switches and a scheme change (designer, cycle 2); the seven entries were
      the `.rail.*` 404s C12 removed.

## Cycle 3

- [ ] **D13 (reorder)** Create the map before `hover_cells.bin` arrives
      (`cellsPromise` not awaited until after `map.load`); fetch `.modes.bin`
      and `.json` lazily on the first click through the C5 path; `borders.json`
      as a URL source (H8). Design and flags in `architect.md` §4 D13 — M3 is
      the prerequisite and must stay first.
- [ ] **D2 (subset)** Vendor `latin-ext` only (26 of the 900 label-pool names
      need it; cyrillic/greek are not needed — gazetteer names are romanised).
- [ ] **N15** Bottom-sheet layout below 480 px regardless of orientation; rows
      wrap (UX-36). **N16** Show the one-line description from 600 px (UX-37).
      **N19** `.results{max-height:min(40vh,280px)}` and 22vh with a route open
      (UX-40).
- [x] **N23** (confirmed shipped, cycle 4: `index.html:84-85`, in `9d0a401`)
      `modulepreload` for `fflate.js`; preload the 500 face (PR-10,
      PR-11) -- already shipped in `9d0a401` (`index.html:84-85`); the cycle-3
      perf review found it done and the box unticked. **N24** Solid scrim on `.tip` instead of `backdrop-filter`; trace
      before/after (PR-13).
- [x] **M10** (2026-10-02: `nearestPlace` wraps its longitude difference,
      run in node by `tests/web/test_nearest_place.py`; the hover ring was
      already unwrapped at `app.js` `unwrap(h3.cellToBoundary(...))`.)
      Unwrap the hover ring across ±180 and wrap `dx` in `nearestPlace`
      (DBG-8). **M15** Hover-cell copy for Shenzhen/Hong Kong (DBG-11) — C3
      removes the value half.
- [ ] **N22** Owner judgement: a permanent one-line credit under the legend or
      the panel renamed "Sources, licences and method" (DOC-12).
- [ ] **R8 (page)** `nearestPlace` once per frame; grid-bucketed label
      collision; pre-lower-cased search lists (PR-12, PR-17, PR-18).
- [ ] **C3** Hover outline and reading from the same cell (needs the split-cell
      set from the emitter and a rebuild). **C1** Route chain through surface
      transfers (rebuild). **C2 (accounting)** Per-leg surface minutes
      (rebuild). **C8** One rounding rule (rebuild). **C11** Filter dropped
      airports from search; disambiguate duplicate names with region.
- [ ] **D20 (measure)** Measure the 37 interpolated bands, not only the anchors;
      decide with the owner whether 1.8–2.7 between adjacent interpolated
      bands is the intended gradient (VER-29 refuted the wording half: CLAUDE.md
      already says anchors ≥ 6).
- [x] **P4 (node harness)** (2026-10-02: see the gates plan; the formatters
      run in node from `tests/web/test_time_format.py`.)
      `web/tests/app_pure.test.mjs` run from pytest when
      `node` is present (gates plan).

## Progress

- 2026-09-10 cycle 2: plan written from the cycle-2 aggregate; carries every
  unfinished web task from the cycle-1 plan (now archived) under its original ID.
- 2026-09-10 cycle 2 done: every cycle-2 task shipped in 9d0a401 (page) with N21 in 269e17c and the parity test in 1d382c8; verified on the local preview with agent-browser at 1280x800, 820x1180, 390x844 and 844x390 (0 console errors) and by scripts/browser_verify.sh against the preview (all checks passed, including the folded-sheet legend, the tap reading, the departure label, borders and ?from=tokyo). Checks recorded in the commit body. Not deployed: the rebuild owns dist/ (see the build plan's deploy note).
- 2026-09-10 cycle 2 closed at `29c6330`: every Cycle 2 task above is ticked; the Cycle 3 section stays open, so this plan is not archived. Both gates green on the whole repo at that commit (ruff clean; pytest 356 passed, 4 deselected, 5 warnings, exit 0) -- recorded in `plan/2026-09-10-c2-gates-and-tests.md`.
