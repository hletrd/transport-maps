# Cycle 9 — the page's failure paths, its accessibility, and the gates that cannot see either

Status: **planned** (see Progress)
Source reviews: `.context/reviews/` — twelve lanes, `_aggregate.md` clusters `AC1`…`AC71`
(109 raw findings, 71 after dedupe).
Deploy constraint this cycle: `scripts/deploy_verify.sh --page-only` ONLY. A 553-origin
rebuild (`rebuild18`) holds `dist/.build.lock` and writes `dist/origins` in place. No
`build-all`, no `reindex`, no `build_water_tiles.py`, no writes under `dist/` or `data/`.

Task IDs are `C9-1`…`C9-31`. Everything else the review found is in the deferred table at
the bottom, with citation, unchanged severity and confidence, a concrete reason and the exit
criterion that reopens it.

---

## Why this shape

Cycle 8 landed 38 tasks. Cycle 9's reviewers found that the code cycle 8 shipped had not yet
been read by anyone, and three lanes ran measurements earlier cycles had only reasoned about.
The result is not a longer list of the same kind of thing: it is **one reproducible crash on
the live page**, **three accessibility defects a phone visitor hits today**, and **a set of
gates that pass on empty input** — the exact class CLAUDE.md's deploy rule exists to catch.

The single most valuable result is a negative one and it is recorded rather than acted on:
**the tier-B reading fallback holds.** Seven lanes checked it independently, one of them by
driving the real fetch through a node harness across seven failure modes (404, 500, an HTML
error body, an empty body, a network abort, a synchronous throw, a wrong element count). In
every case `fatal()` is not called, the function returns null, nothing propagates uncaught,
and the next origin switch retries. The one thing that could have broken the live site today
does not.

Everything scheduled below is shippable under a page-only deploy. Every build-path finding
is deferred, because a number this cycle cannot verify is a number this cycle must not ship.

---

## A — The live page's failure paths (HIGH)

### C9-1 — A resize during the map-load await deletes the side rail

**Finding:** `AC1` (ARCH9-3 flagged it; DBG9-1 **reproduced it in node**), `AC32`.

`web/app.js:499-500` registers `resize` and `fonts.ready` handlers that call
`refreshScale()`. `refreshScale` (`:2095`) always reaches `markSpan`, because its only early
exit is `hideDetail()` (`:2046`) which itself calls `markSpan(null)`. `markSpan` reads
`bandSpan` at `:2038`, and `let bandSpan` is at `:2034` — 1,535 lines below the listener.
Between the registration and that declaration the module suspends at the top-level
`await Promise.race` (`:643-647`) waiting for the globe to load. A `resize` in that window
reads a `let` in its temporal dead zone:

```
ReferenceError: Cannot access 'bandSpan' before initialization
```

The `fonts.ready` door swallows it in its own `.catch` — which is why this has shipped
unnoticed — but the `resize` door is an uncaught listener, so it reaches `boot.js`'s global
`error` handler, `say()`, and `body.fatal`, **deleting the entire side rail of a page that
was about to work**. An Android URL bar collapsing during load is enough. `bandMark`
(`:1927`) is in the same position and its own comment already narrates this exact bug having
shipped once before.

- [ ] **C9-1** Move `let bandMark = null` and `let bandSpan = null`, with their comments,
      into the state block at `app.js:255-283`, beside the `SMALL` declaration whose comment
      already records the same failure ("U25 shipped a blank page from a const read before
      its declaration"). Add a regex guard that every module-level binding a
      module-scope listener can reach is declared above the first `addEventListener`.
      **Mutation:** move `let bandSpan` back below `refreshScale` → the guard goes red.

### C9-2 — The itinerary reads its total from one grid and its legs from another

**Finding:** `AC2` (ARCH9-4).

`renderLegsInto` takes `total` from `lookup()` (`:1811`), which returns the **res-6** reading
when the tier is present, and every leg row from `cellIndex()` (`:1772`, `:1832`), which is
**res-4**. Today the tier is dormant, so the two agree. The running rebuild publishes
`readingRes`, and then they are two different cells up to 17 km apart. Two consequences, both
silent: `if (total > landed.min)` (`:1858`) can be false, so the **onward leg from the
arrival airport vanishes** from the itinerary; and the rows stop summing to the
"Door to door" line (`:1869`) they are presented as decomposing.

- [ ] **C9-2** Decompose the itinerary on the grid the chain comes from: take the panel's
      total from `origin.times[i]` at the same res-4 index the legs use, so the rows sum. Keep
      the headline reading on the finer grid, and when the two differ say so in one line in
      the panel rather than letting them disagree in silence.
      **Mutation:** feed a fixture whose res-6 reading is lower than the res-4 chain's landed
      minute → the onward row must still appear and the rows must still sum.

### C9-3 — The gate that exists to stop a mixed `dist/` cannot see the mixed `dist/` that exists now

**Finding:** `AC3` (TR9-1 measured it, ARCH9-8, CR9-7).

`scripts/check_dist.py`'s only cross-origin fingerprint is `offsets.airports`, which equals
`idx.n_cells` and therefore moves only when the solve resolution changes. `offsets.stations`
is parsed two lines above and discarded. Those two offsets differ by the airport count, and
in today's `dist/` they prove **two builds are mixed: 3,990 airports in some origins, 3,996
in others**. The gate calls this consistent. CLAUDE.md: "Never deploy a partial `dist/`. The
per-origin arrays and `hover_cells.bin` must come from the same build; mixing them renders a
blank globe with no error."

- [ ] **C9-3** Make the mixed-build check use the pair, not the single offset: every origin
      must agree on `(offsets.airports, offsets.stations)`. Report the disagreeing slugs and
      both values. This is a gate change only — it does not touch `dist/`.
      **Mutation:** a fixture with two origins differing only in `offsets.stations` → red.

---

## B — What a visitor with a phone or a keyboard hits today (HIGH)

### C9-4 — The focus ring on the map controls is invisible

**Finding:** `AC4` (UX9-1, measured).

`outline-offset: 1px` lifts the `#e48f35` focus ring off the button and onto the band colour
behind it. Measured against real pixels on the default Muted scheme: **1.00–1.08:1**, where
WCAG 2.2 SC 1.4.11 and 2.4.11 need 3:1. A keyboard visitor cannot see where focus is.

- [ ] **C9-4** Use `outline-offset: -2px` on the three map controls — the pattern
      `.results button` already uses, which measured 7.11:1. No new colour, no policy change.
      **Mutation:** restore `1px` → the contrast guard goes red.

### C9-5 — On a portrait phone the loading message is hidden for the whole load

**Finding:** `AC5` (UX9-2, `elementFromPoint` sustained t=372→4031 ms).

"Loading the map…" is occluded by the bottom sheet for the entire load, because
`layoutForSize()` only runs after `await map.on("load")` — the very await the message exists
to cover. The visitor sees a blank globe and no explanation.

- [ ] **C9-5** Run the layout decision before the map-load await, so the sheet is positioned
      correctly while the message is on screen.
      **Mutation:** move the call back below the await → the guard goes red.

### C9-6 — At 844×390 no travel time is visible anywhere, but a screen reader still gets one

**Finding:** `AC6` (UX9-3).

Folding the rail at 844×390 hides `#time`, `#where` and the legs while keeping the legend,
and `.tip` is `display: none` at ≤860 px. The number the whole site exists to show is on
screen nowhere — while the live region is deliberately kept alive, so a screen-reader user is
told the time and a sighted user is not. That inversion is the finding.

- [ ] **C9-6** Keep the reading visible when the rail is folded at short-landscape sizes.
      **Mutation:** re-hide it → the guard goes red.

---

## C — Visible defects (MEDIUM)

- [ ] **C9-7** (`AC14`, CR9-1 + ARCH9-2) `markBand` divides by `strip.children.length` minus
      the mark, while `markSpan` divides by `N_BANDS` on the same 37-swatch strip. When the
      zoom detail row is showing, the span is also a child, so the denominator is 38 and the
      pointer mark is about one band off — **on the live site today**. Use `N_BANDS`, the one
      owner of the band count. **Mutation:** restore the child count → red.
- [ ] **C9-8** (`AC20`, CR9-2) `paintDetail` calls `prune(scale)` while `#detail` is still
      `hidden`, so every tick measures a zero-width rect and all but one label is deleted.
      Unhide before pruning. **Mutation:** prune first → red.
- [ ] **C9-9** (`AC22`, CR9-4) `highlight()` never `unwrap()`s the H3 ring, so hovering a cell
      on the antimeridian paints a 360°-wide band across the globe. The file already has
      `unwrap`. **Mutation:** drop the unwrap → red.
- [ ] **C9-10** (`AC21`, CR9-3) `render()`'s `replaceChildren` wipes the on-screen address
      results whenever a per-origin array lands; the re-attach guard covers only the in-flight
      case. **Mutation:** remove the guard → red.
- [ ] **C9-11** (`AC40`, ARCH9-6) The permalink-restore `setInterval` (`:3302`) guards only on
      `origin.times`, so for the first 10 s, and across an origin switch, it overwrites a
      destination the visitor chose by hand. **Mutation:** drop the guard → red.
- [ ] **C9-12** (`AC44`, UX9-5) Escape deletes the pinned route from anywhere on the page
      (verified: focus on a city button, press Escape, the route is gone and focus is dumped
      to `<body>`). Scope it. **Mutation:** unscope → red.
- [ ] **C9-13** (`AC23`, VER9-1) Cycle-8 task T5.3 is ticked but was never done: `app.js:2481`
      still has a bare `6371` against Python's `6371.0088`, and `git log -S'6371.0088' --
      web/app.js` shows no commit ever touched it. Fix the number and correct the tick.

## D — What the page says about itself (MEDIUM; CLAUDE.md modelling and door-to-door rules)

- [ ] **C9-14** (`AC16`, CRIT9-1) Three places say the reading "averages over" the seven res-7
      sub-cells; `emit/hover.py:221-232` takes the **centre child only**. Correct
      `web/index.html:950-953`, `web/llms.txt:62-63` and `config.py:31-34` to what the code does.
- [ ] **C9-15** (`AC17`, CRIT9-2) `web/index.html:933-934` says the ferry prior over-states the
      wait on busy short-sea routes. `calibration.toml:221-234` measures the **opposite**:
      median predicted/observed 0.383 over 298 of 326 holdout observations, i.e. it
      under-states. `llms.txt` already states it correctly; the page does not.
- [ ] **C9-16** (`AC18`, CRIT9-5) The departure card prints three travel-time figures with no
      door-to-door statement, against CLAUDE.md's standing rule that the composition is said
      wherever a figure is presented. `app.js:2390-2393` already asserts the note carries one.
- [ ] **C9-17** (`AC55`, DOC9-7) Google Routes (`calibrate/ground.py:29`) sets every ground
      speed and the urban factor, and appears in no page-visible credit and nowhere in
      `web/llms.txt`, which cites the 2,998 journeys without naming their source. `README.md`
      discloses it fully; the page does not. Close the asymmetry.
- [ ] **C9-18** (`AC56`, DOC9-5 + CRIT9-9) `emit/index.py:174-176` calls the ferry sailing
      speed "a published figure" and credits a "tortuosity" term. `calibration.toml:276-280`
      says FITTED, and no tortuosity term exists — a detour factor was tried and rejected.
- [ ] **C9-19** (`AC29`, SEC9-1) Cycle-8's `?label=` puts a **reverse-geocoded street address**
      into the URL, and GA4 sends the URL as `page_location`. The privacy text discloses only
      the coordinate. Either keep the address out of what analytics receives, or disclose it.
      Prefer keeping it out: the page does not need to send it.

## E — Gates that pass on empty input (MEDIUM)

- [ ] **C9-20** (`AC15`, FCR9-1 + ARCH9-7) `browser_verify.sh:256` is the only check in the
      file using `2>/dev/null`; a failed `agent-browser console` call yields empty stdout,
      `grep -ci` prints `0`, and the gate reports "errors: 0" without having read the console.
      `:161` fails only on a positive grep, so an empty probe also reads as a pass. Both are
      the gate CLAUDE.md's deploy rule rests on. **Mutation:** point the probe at a
      nonexistent selector → red.
- [ ] **C9-21** (`AC30`, SEC9-6) Unquoted `$DEPLOY_ROOT` in the remote `df` makes the
      free-space gate read the wrong filesystem — the guard that exists to stop a mixed
      `dist/` reaching the server.

## F — Tests that pass with the bug in (HIGH and MEDIUM)

The test-engineer lane ran **18 mutations against scratchpad copies** and nine stayed green.
A fourth shape of vacuity was named: *the assertion's scope is derived from the subject*, so
breaking the code removes the assertion rather than failing it.

- [ ] **C9-22** (`AC7`, TE9-1, **HIGH**) `tests/web/test_app_constants.py:66`: the airports
      column-order guard is satisfied by `greatCircle`'s coordinate pair (`app.js:1713`) and by
      the **places** table (`:937`). Transposing airports lat/lon (TE-M14) or deleting the
      reads outright (TE-M15) both leave it **green**. Anchor the assertion to the airports
      table specifically. **Mutation:** TE-M14 must go red.
- [ ] **C9-23** (`AC60`, TE9-2) `tests/test_calibration_provenance.py:133`: the only assertion
      sits behind `if "2,998" not in text: continue`, so reprinting the sample count disarms
      the guard (TE-M3 green). `README.md` is already silently exempt.
- [ ] **C9-24** (`AC62`, TE9-4) `tests/test_cli.py:219`: `"EXCLUDED"` is satisfied by the rail
      line, so the ferry report — the suite's only assertion about it — is unguarded (TE-M9).
- [ ] **C9-25** (`AC63`, TE9-5) `tests/sources/test_cache_provenance.py:141,325`: `"airports"`
      is itself 8 alphanumerics and `land_cells_r6` has a digit and more than 12 characters.
      Each predicate is vacuous for a different path and they cover for each other by luck
      (TE-M1, TE-M2b green).
- [ ] **C9-26** (`AC64`, TE9-6) `test_reindex`: `assert current() is not None` cannot show the
      lambdas read today's config; freezing `hoverRes` leaves both guards green (TE-M8 ×2).
- [ ] **C9-27** (`AC26`, VER9-4) Only 2 of the 5 tier-B failure modes are pinned by a test
      that executes anything; deleting `current()` at `app.js:1394` leaves the suite green.
      Pin the HTML-body, abort and stale-in-flight modes. The behaviour is correct — what is
      missing is the guard that keeps it correct.

## G — The ledger (MEDIUM, docs)

- [ ] **C9-28** (`AC57`, DOC9-1/DOC9-2) Six deferred rows have exit criteria that have already
      fired: **TE3-15** (the defect is *fixed* — `tests/web/test_ramps.py:13` now pins `== 12`),
      DOC3-28, DOC5-8, AA37, CR5-7, AB41. Close TE3-15; reopen or restate the other five.
- [ ] **C9-29** (`AC58`, DOC9-3) `plan/README.md` does not describe HEAD: cycle 8 is absent
      entirely, cycle 4 is marked "open" though 28/28 and archived, two archived files are
      given `plan/` paths, "V1…V28" should be 29, and the test-count headline is three
      revisions stale (**700 passed, 4 deselected** at HEAD).
- [ ] **C9-30** (`AC59`/`AC24`/`AC25`, DOC9-4 + VER9-2 + VER9-3) Ledger integrity: `USER-n`
      names two incompatible things across cycles 4 and 8; `M8-14` is ticked while the same
      file says it was not fixed and the measurement worsened 1.8 px → 19 px; `ARCH5-6` is
      referenced and undefined; `J3`/`DOC3-21` are duplicated; one row is malformed. Plus two
      corrections to cycle 8's own progress table: the "6.5 → 1.75 bands" headline is carried
      by four ceiling-saturated anchors (on the four the ladder can resolve it is 3.5 → 2.5,
      and Helsinki–Tallinn gets **worse**, 2 → 4), and the Kerguelen/South Georgia "old model"
      column is transposed.
- [ ] **C9-31** (`AC19` doc half, CR9-6 + DOC9-6) `graph/ferry.py:62-75` derives
      `MIN_SAILINGS_PER_WEEK` from a headroom sum that substitutes 8,640 minutes for the
      48,000 its own stated bound (`MAX_FERRY_KM` at `MIN_SAILING_KMH`) gives. With the real
      figure the sum is 98,475 against `MAX_MINUTES` 65,534, so **the guarantee fails at the
      bound it invokes**. The constant itself is not changed this cycle (that is a build-path
      number); the derivation is corrected to say what it actually guarantees, and the gap is
      recorded as a deferred finding with the clamp as its fix.

---

## Deferred findings

Every row carries citation, unchanged severity and confidence, a concrete reason and the exit
criterion. No finding from this cycle's reviews was dropped.

The dominant reason is one quoted repo rule plus one quoted run constraint: CLAUDE.md's
**"Never deploy a partial `dist/`. The per-origin arrays and `hover_cells.bin` must come from
the same build"**, and this cycle's instruction to run `--page-only` and not to write under
`dist/` or `data/`. A change to a number the build produces cannot be verified this cycle, and
landing it unverified beside a running 553-origin rebuild is how this project has previously
shipped a blank map.

| ID | Finding | File:line | Sev | Conf | Reason | Exit criterion |
|---|---|---|---|---|---|---|
| DEF9-1 | `AC8` `SPEED_BY_ROAD_CLASS_KMH` is non-monotonic (tertiary 18 < local 25) while `roads.cell_class` reduces on class number, so adding a better road makes a cell 28% slower | `sources/roads.py` | HIGH | High | Changes every ground number on the map. The rebuild is mid-flight and this would make its output unattributable | A cycle whose deploy permits a rebuild; report how many cells change speed |
| DEF9-2 | `AC9` `highspeed` is read off the route **relation**, so only 537 of 16,781 are flagged (Shinkansen 0/2, Frecciarossa 0/10); Tokyo→Shin-Aomori costs 10.39 h against a real ~3 h 20, eight bands | `sources/osm.py:42-44` | HIGH | High | An extract-parsing change invalidates the rail cache and re-derives mid-rebuild | The rebuild has completed; land it first in the next build-path cycle, with the Tōhoku figure as the test case |
| DEF9-3 | `AC10` `route_network()` returns the unstamped legacy `data/build/routes.parquet` **before** cycle-8's `_refuse_partial`, the 20,000-pair floor and `_SANITY_PAIRS`; `/tmp/rebuild18.log:12,15` shows the running rebuild took that path twice | `sources/routes.py:278` | HIGH | High | Removing the legacy path forces a full re-crawl of the route network, which the running rebuild is currently reading | The rebuild has completed; then delete the legacy path and re-crawl once |
| DEF9-4 | `AC11` 428 of 3,985 airports (10.7%) are cached as "no service" by a silent `_SECTION_RE` miss — Anchorage 0, Fairbanks 42 — uncounted and unbounded; `_SECTION_RE` opens at any heading level but `_NEXT_TOP_HEADING_RE` closes only at level 2 | `sources/routes.py` | HIGH | High | Same cache as DEF9-3 and the same re-crawl cost; the two must land together or the effects are unattributable | With DEF9-3, after the rebuild |
| DEF9-5 | `AC12` `.r6.bin` is 5,216,066 B gzipped per origin, refetched on every city switch, gated only on `saveData` (absent on iOS) | `web/app.js` reading tier | HIGH | High | Page-only and shippable in principle, but the tier is **dormant until the rebuild lands**, so any change is unverifiable against real bytes and the fix (a budget, or a coarser tier on a metered link) needs the real file sizes to size | The rebuild publishes `.r6.bin` for all 553 origins; then measure on a throttled connection and land the budget. **This is the first task of the next cycle.** |
| DEF9-6 | `AC13` `water.pmtiles` low-zoom tiles sized by tippecanoe's default budget, not the screen: z1 = 443 KB on the opening view, z3 = 817 KB, z0 holds 47,559 features on a grid quantizing to 9.8 km | `scripts/build_water_tiles.py` | HIGH | High | Requires re-running the water build, explicitly forbidden this cycle | A cycle that may rebuild water tiles; re-tile z0–z3 against a screen budget |
| DEF9-7 | `AC27` Tier B's padding sentinel is indistinguishable from "unreachable"; **7.0% of reachable land area** flips from a real door-to-door time to "no scheduled route" and becomes unpinnable once the rebuild arms tier B | `emit/hover.py`, `web/app.js` `lookup()` | MEDIUM | High | The honest fix is a distinct padding sentinel in the emitted file, which is a build-path format change. The page-side half alone cannot distinguish the two values | The rebuild completes; then emit a distinct padding value and teach `lookup()` to fall through to res-4 on it. Until then `lookup()`'s res-4 fallback covers the case for any cell the reading tier does not resolve |
| DEF9-8 | `AC19` code half: nothing clamps `crossing_min`, so a long crossing with a large tagged `duration` can overflow uint16 and ship as "no scheduled route" while `check_coverage` counts the cell covered | `graph/ferry.py` | MEDIUM | High | A clamp changes emitted numbers; the derivation text is corrected this cycle (C9-31) so the gap is at least documented where it lives | A cycle with a rebuild; add the clamp and assert the sum against `MAX_MINUTES` |
| DEF9-9 | `AC31` No remote download verifies its bytes; a swapped GRIP4 raster makes every published travel time attacker-chosen behind a clean `inputsHash`, and feeds GDAL unauthenticated input | `sources/*` | MEDIUM | High | Adding digest verification invalidates every raw cache and forces a full re-download during the rebuild. Distinct from DEF8-1 (key hygiene) — this is trust on the miss path | The rebuild has completed; land with DEF8-1 as one cache-integrity change |
| DEF9-10 | `AC34` `ferry_links` accepts a zero-crossing extract that `rail_routes` explicitly refuses, and `osm_rail.sh` (`set -uo pipefail`, no `-e`) exits 0 after a failed region → a continent's ferries vanish with every gate green | `sources/osm.py`, `scripts/osm_rail.sh` | MEDIUM | High | Carried from DEF8-14: the `-e` change alters what a rebuild does on a partial download and a rebuild is running now | After the rebuild, with DEF8-14, as one build-robustness change |
| DEF9-11 | `AC35` Raw download caches key on a fixed filename while the derived cache stamps the URL, so changing a source URL re-derives from **stale bytes and stamps the result fresh** — the converse of DEF8-1 | `sources/_utils.py` | MEDIUM | High | Same cache-invalidation cost and the same running rebuild | With DEF8-1 and DEF9-9 |
| DEF9-12 | `AC36` `PARSER_VERSION`/`RESOLVER_VERSION` compare nothing against the legacy flat format, which is what both live caches are, so a parser fix reaches zero airports | `sources/` | MEDIUM | High | Same cache change; also the direct cause of why DEF9-4's fix would silently not apply, so the two must land together | With DEF9-4 |
| DEF9-13 | `AC37` `build-all --only/--limit` rewrites `hover_cells.bin` and `reading_parents.bin` but is forbidden from rewriting `index.json`; after a grid change that combination makes the whole site `fatal()` | `cli.py` | MEDIUM | High | A change to build-invocation semantics while a build is running | After the rebuild, with DEF8-14 |
| DEF9-14 | `AC38` `reindex` sets `railDetail` from *any* origin's `.rail.bin` and never checks `.rail.json`, against `write_index`'s own contract: two 404s per origin switch on a partially-railed `dist/`. `railDetail` has three disagreeing definitions across `cli.py`, `emit/index.py` and `check_dist.py` | `cli.py`, `emit/index.py`, `scripts/check_dist.py` | MEDIUM | High | `reindex` is forbidden this cycle and the fix is only testable by running it | A cycle that may run `reindex`; make `check_dist` the single owner of the definition |
| DEF9-15 | `AC42` Cell index ordering is owned by `emit/hover.py:98-100` but re-derived verbatim in `modes.py:91`, `itinerary.py:58`, `rail_detail.py:86`; an order-preserving-count change misaligns `.modes/.air/.rail` against `.bin` and both length checks pass | `emit/` | MEDIUM | High | Build-path; the defect is latent (no ordering change is pending) and the fix touches four emitters mid-rebuild | The rebuild has completed; then give the ordering one owner and have the three import it |
| DEF9-16 | `AC39` `routes._SECTION_RE` opens the destinations section at any heading level but `_NEXT_TOP_HEADING_RE` closes only at level 2, swallowing sibling subsections into fabricated flight edges | `sources/routes.py` | MEDIUM | High | Same cache and same re-crawl as DEF9-4; it is the same regex pair | With DEF9-4 |
| DEF9-17 | `AC33` No `webglcontextlost` handler: a lost context after load (a backgrounded iOS tab) gives a black globe, working numbers, no message, and `boot.js`'s watchdog already disarmed by `appReady` | `web/app.js`, `web/boot.js` | MEDIUM | Medium | Page-only and worth doing, but it needs a real context-loss rehearsal to verify and the browser budget this cycle went to the three HIGH accessibility defects. Not a regression | Next page cycle; verify by forcing `WEBGL_lose_context` |
| DEF9-18 | `AC43` `fatal()` and `noteTileTrouble()` write to non-live elements while the still-connected `role="status"` region sits empty; the fatal state says "reload" but offers no control | `web/app.js`, `web/index.html` | MEDIUM | High | Page-only; deferred on bounded scope only, behind the three HIGH accessibility defects (C9-4…C9-6) which a visitor hits on every load rather than only on an error | Next page cycle; land with DEF9-17, which shares the error-surface code |
| DEF9-19 | `AC45` `.ap`/`.mode` glosses are `tabindex="0"` spans with no role, label or `aria-describedby`; a screen reader hears "ICN" and nothing more | `web/app.js`, `web/index.html` | MEDIUM | High | Page-only; the tooltip's dismissibility (WCAG 1.4.13) is the same code and the same fix, and doing half of it would leave the pattern inconsistent | Next page cycle; land the gloss role, label and dismissal together |
| DEF9-20 | `AC46` At 844×390 all four panel summaries sit below the fold (y=482–608) with every `<details>` closed and no scroll cue | `web/index.html` | MEDIUM | Medium | Page-only; C9-6 changes the same short-landscape layout and this must be measured **after** that change, not beside it | After C9-6 ships and is browser-verified at 844×390 |
| DEF9-21 | `AC47` Boot queues 1,153 KB gz of JSON (places 658, borders 404, airports 91) ahead of the 131 KB `.bin` and the band tiles, delaying the first reading ~9× under fair sharing; `AC48` 474 KB of the 605 KB per origin switch feeds only the itinerary panel, which stays hidden until a destination is pinned | `web/app.js`, `web/index.html` | MEDIUM | High | Re-ordering the critical path is a real improvement and page-only, but it must be sized against the rebuild's file sizes and landed with DEF9-5's budget, not twice | With DEF9-5, the first task of the next cycle |
| DEF9-22 | `AC49` `showLabels()` re-decides all 900 labels every animation frame (~5,400 trig + ~450 globe `project` calls); `AC51` `render()` rebuilds all 553 rows twice per city tap; `AC50` three unthrottled `resize` listeners run the 81-sample resample while the map path debounces the same work at 160 ms | `web/app.js` | MEDIUM | Medium | Carried from H7/H14: not confirmed as user-visible jank, and the designer measured no dropped frames this cycle. `AC50`'s throttle is cheap but touches the same listeners C9-1 moves, and doing both in one cycle would confound the TDZ fix | A trace shows >16 ms frames on a non-Apple GPU, or C9-1 has shipped and been verified |
| DEF9-23 | `AC52` The analytics tag costs a measured 191,470 B on the wire and 581,628 B of main-thread parse inside the load window, plus two third-party connections; nothing on the page depends on it | `web/index.html` | MEDIUM | High | Removing a site's analytics is the owner's decision, not an agent's. C9-19 fixes the privacy defect within it | Owner decides whether to keep, defer or drop the tag |
| DEF9-24 | `AC54` The design spec's preamble guarantees "the rest reads as written"; ten body claims do not hold, including the ferry-terminal nodes, the flight edge's expected wait, the per-band airborne fit, "bands nest without overlap", and a licence table missing Natural Earth, Wikidata and GeoNames | `docs/…design.md` | MEDIUM | High | The spec describes a design; several of the ten are claims the code *should* meet and does not, so correcting the prose alone would paper over build-path findings already deferred above | The build-path cycle that lands DEF9-1…DEF9-4; revise the spec against what shipped, in one pass |
| DEF9-25 | `AC53` `[rail]`'s Seoul–Busan provenance check uses an endpoint great circle, not the sum of consecutive-stop chords the code applies; its 117 min is a strict lower bound and the documented error does not reproduce | `calibration.toml` | MEDIUM | High | The comment is wrong about a **fitted** figure, so correcting it properly means re-deriving the anchor, which needs the rail cache the rebuild is reading | With DEF9-2, which is the same rail extract |
| DEF9-26 | `AC61` `test_build_identity.py:74`: `called` is built by filtering `STAMPED`, so the direction its own failure message names is unreachable and a new stamped constant goes untested (TE-M4 green) | `tests/emit/test_build_identity.py:74` | MEDIUM | High | Test-only and shippable, but the fix needs a second source of truth for the stamped set, and the natural one is `emit/index.py`'s own `params_hash` inputs, which C9-3's gate work touches | Next cycle, immediately after C9-3's contract change settles |
| DEF9-27 | `AC65` `test_golden.py:36` tolerances admit deleting border control from every international flight; no test ties `border_min` to the air edge | `tests/test_golden.py:36` | MEDIUM | High | Tightening a golden tolerance changes what a **build** must reproduce, and the running rebuild's output has not been compared to the goldens yet | The rebuild has completed and its goldens are re-measured; then tighten, and add the `border_min` guard |
| DEF9-28 | `AC66` `24/7` early return pre-empts the seasonal derate, so a summer-only ferry is priced year-round; `AC67` the reading tier checks `reading_parents.bin` length but never its ordering, which the binary search requires; `AC68` `nearestPlace()` compares longitudes on a plane; `AC69` `tickEl` keys `.last` on the world strip's final edge, which an interior detail tick can match; `AC70` `_log_reading_cost` catches only `OSError` and divides outside the `try`; `AC71` `?to=`/`?at=` treat an empty numeric field as `0` | `graph/ferry.py`, `web/app.js`, `emit/hover.py` | LOW | High | Six small defects. Two are build-path (`AC66`, `AC70`); `AC67` cannot be exercised until the rebuild publishes a real parents file; `AC68` is the page twin of a deferral already carried as J9; `AC69` and `AC71` are cosmetic and reachable only from a hand-edited URL or a one-band detail row | `AC66`/`AC70` with the next build cycle; `AC67` with DEF9-5; the rest in a hardening cycle |
| DEF9-29 | `AC72`-range LOW security: SEC9-2 unbounded `?from=` into the ARIA live region (not XSS — the sinks are `textContent`), SEC9-3 `a.href = s.url` from `index.json` with no scheme allowlist, SEC9-5 `extractall` with no size bound, SEC9-7 the probe slug not run through `_SLUG_RE`, SEC9-8 `adsb_extract` `urlopen` with no scheme allowlist | `web/app.js`, `sources/water.py`, `scripts/deploy_verify.sh`, `scripts/adsb_extract.py` | LOW | High | All five are defence-in-depth against a precondition that does not hold: `index.json` and the deployed slug list are same-origin content this project writes, and `adsb_extract.py` is an offline maintainer-only tool (carried as DEF8-13). None is visitor-reachable | Whichever precondition first becomes reachable: a third-party writes `index.json`, or `adsb_extract.py` gains a configurable repo |
| DEF9-30 | LOW documentation drift: DOC9-8 `cli.py:589-590` says "the four fields" where `_CURRENT_INDEX_CONSTANTS` holds nine; DOC9-9 `emit/tiles.py:16-23`'s own two figures give 61%, not the ~38% it states, and its crispness rationale argues z6→z7 under `MAX_ZOOM = 8`; DOC9-10 `contour/grid.py:3-4` still quotes the res-5 "8 km hex stair-step" against the shipped 6.5 km; DOC9-11 three files name pre-stamp cache filenames; DOC9-12 `graph/build.py:330-331`'s comment sits above the wrong branch; VER9-6 two ticked cycle-8 rows prescribe designs that were rejected in favour of better ones; VER9-7 "33 mutations" undercounts its own list of 37; TR9-6 `index.json.fineRes` is declared and documented as read by the page and never read; ARCH9-9 `UNREACHABLE` comes from `index.json` but `NO_AIRPORT`/`NO_RAIL` are literal 180 lines later; ARCH9-10 `reverseSeq` is never bumped by `commitDestination`; DBG9-7 a deterministic length mismatch clears `readingParentsWanted` on the same path a network blip does; CRIT9-6 "the first service is not waited for" is false for a ferry first leg; CRIT9-7 the res-4 fallback is framed as temporary and `dateModified` contradicts the served `builtAt`; UX9-8…UX9-11 four measured but minor UI nits; TE9-7…TE9-10 four weak assertions; PR9-9/PR9-10 two load-path micro-costs | various | LOW | High/Medium | Twenty-three items, each true and each small. Bundling them into this cycle would triple its commit count for no change a visitor can perceive, against the owner's standing "do not overwork". None is a correctness, security or data-loss finding | A documentation-and-hygiene cycle, or opportunistically whenever the surrounding code is edited for a real reason. CRIT9-6 and CRIT9-7 go with the next page-copy pass |

### Not deferrable, and not deferred

No security, data-loss or correctness finding is deferred without a repo rule or run
constraint permitting it, quoted above. The six HIGH findings that are deferred (DEF9-1…DEF9-6)
are every one of them build-path or build-artifact work whose verification requires a rebuild
this cycle is forbidden to run; each names the rebuild as its exit criterion and none is a
regression introduced this cycle. The HIGH findings a visitor can actually hit today —
the TDZ crash (AC1), the invisible focus ring (AC4), the occluded loading message (AC5), the
missing travel time at 844×390 (AC6), the blind mixed-build gate (AC3) and the vacuous
column-order guard (AC7) — are all scheduled above and fixed this cycle.

---

## Progress

(filled in as tasks land)
