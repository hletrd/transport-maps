# Cycle 10 — four live defects, and the gates that could not see two of them

Reviews: `.context/reviews/` (uncommitted, see `plan/README.md`). This cycle's
reviewers were code-reviewer, security-reviewer, perf-reviewer, test-engineer,
designer, architect, document-specialist and critic/verifier. Their IDs here are
`CR10-n`, `SEC10-n`, `PR10-n`, `TE10-n`, `UX10-n`, `ARCH10-n`, `DOC10-n`,
`CRIT10-n`.

The cycle's brief was four defects the owner and the deploy's own verification
reported, plus any genuine HIGH-severity correctness or security finding. Every
other review finding is scheduled below or recorded in `deferred.md`.

Build constraint honoured: no `build-all`, no `reindex`, no
`scripts/build_water_tiles.py`, nothing written under `dist/` or `data/`. Deploy
was `scripts/deploy_verify.sh --page-only`, four times.

---

## C10-1 — the itinerary claimed an overland journey to Mauritius — **DONE**

Reported by the owner: "ᆫsongres, mauritius 를 어케 육로로 가니?"

`?from=seoul&to=-20.162,57.499` printed

```
Journey to Port Louis
10 h 48 min  To KUL, and through the airport
 7 h 53 min  Fly KUL → MRU
 1 h 16 min  Onward from MRU
```

and the globe drew a ground line from Seoul to Kuala Lumpur. Seoul's only land
border is sealed.

**Mechanism.** A `dep` node's predecessor is a solver CELL, and
`emit/routes_json.py` writes airport nodes only, so `legsTo`'s walk stopped
there and the truncated head was priced as a ground leg. For the departure
city's own airport that is correct — there is nothing before it to show. For an
airport the journey FLEW to, the whole prefix was missing.

**Measured** over seven origins and 32,354 flown journeys: 34.5% had a prefix
lost this way, so it was never specific to Mauritius.

**Fix, page-side, no rebuild.** `origin.air` already records, for every hover
cell, the arrival airport the journey reached that cell through, so asking it
about the departure airport's OWN cell continues the walk one hop back. The
splice is refused unless the recovered chain lands at the airport being boarded,
and no later than it is boarded. Where it is refused the chain is returned
`partial`, the first row says the legs before it are not recorded, and
`renderRoute` draws no leading leg — a line on a globe is an assertion.

| outcome | share of flown journeys |
|---|---|
| already complete (the departure city's own airport, reached overland) | 65.5% |
| prefix recovered by the continuation | 30.7% |
| stays partial, rendered honestly | 3.8% |

Of the 3.8%, 1,210 of 1,223 land at a DIFFERENT airport from the one boarded —
an airport-to-airport surface transfer the res-4 array cannot confirm — and 13
loop. Closing them needs the pipeline to emit cell predecessors: see C10-P1.

Live after deploy: `2 h 14 min To ICN` / `Fly ICN → KUL` / `Connect at KUL` /
`Fly KUL → MRU` / `Onward from MRU`.

Commit `9567931`. Tests `tests/web/test_itinerary_grid.py` (rewritten) and
`tests/web/test_route_geometry.py` (new case). Six mutations red; one of them,
dropping the "lands at the same airport" guard, stayed GREEN on all eleven tests
until a fixture was added that reaches it.

## C10-2 — the headline and the itinerary total disagreed — **DONE**

`scripts/browser_verify.sh` failed with head `16h 23 min` against total
`16 h 20 min`. Two separate causes; both fixed.

**(a) The panel took its two numbers from different grids.** Cycle 9 made the
total res-4 so the rows would sum, which fixed the arithmetic and left the page
printing two door-to-door figures side by side. The total is the reading now,
and the ONWARD leg carries the difference — which is where it belongs. Every
other row is a node time out of the solver and does not depend on the grid; only
the leg from the arrival airport to the pin does, and that is exactly the part
the finer grid measures better.

Measured over five origins and 11,741 flown journeys, the onward leg's
distribution is unchanged by the switch:

| | median | p99 |
|---|---|---|
| onward leg, fine total | 302 min | 5,214 min |
| onward leg, coarse total | 301 min | 5,225 min |

Where the reading is at or below the minute the journey landed the rows would
exceed the total. That is 1 journey in 11,741 (0.009%); there the panel falls
back to res-4 and states the disagreement. The overland branch itemises off the
res-4 mode array, so it now checks its own arithmetic and says when the rows do
not sum.

**(b) The finer tier landed after the itinerary had rendered.** Found by
verifying (a) live: `?from=seoul&to=-20.162,57.499` then printed `19 h 48 min`
over a total of `19 h 57 min`, which are exactly the res-6 and res-4 values for
that cell. The 10 MB `.r6.bin` arrives hundreds of milliseconds after the rest,
and its success branch redid the headline, the city list, the departure card and
the legend's zoom detail — everything read through `lookup()` except the one
panel where the disagreement is visible side by side. It redoes `renderLegs()`
now, and its guard is widened to `pinB || lastPointer`, which is what
`rereadPointer` itself prefers.

Live after deploy: head `19 h 48 min`, total `19 h 48 min`; the gate reports
`{"head":"16h 23 min","total":"16 h 23 min","agree":true}`.

Commits `9567931`, `547815e`. Tests: `test_itinerary_grid.py`,
`test_reading_tier_fallback.py` (two new cases pinning the two re-read paths as
a SET, so a render added to `settle()` cannot be skipped in the other).

## C10-3 — the phone tap: the GATE was wrong, taps are not broken — **DONE**

The question the brief asked was which of the two it is. **The gate.**

Both phone checks tapped a hardcoded `[120, 40]`, which is in the Bohai Sea.
Measured against the shipped `dist/`: that point's res-4 cell IS in the land
list and reads 580 min from Tokyo, but its res-6 cell is not land, so the
reading tier holds the padding sentinel for it (`emit/hover.py` writes
`config.UNREACHABLE` into every res-6 slot inside a land-touching res-3 parent
that is not itself land — 18.3% of the array). The page printed "no scheduled
route", and `setDestination` returned before `unfoldSheet()` — correctly: an
unreachable point is not a destination. Reproduced live from a clean load,
exactly as reported.

With a point that is actually land, at the same viewport: `28 min`, the sheet
unfolds, and the live region says "Kunitachi: 28 min from Tokyo, door to door."

Four changes, all in `scripts/browser_verify.sh`:

1. The point is chosen, not assumed: near the departure city (from
   `index.json`, not a literal), the canvas must be topmost under it, and the
   page's own hover reading there must already be a number.
2. Hit testing is no longer skipped. Both checks dispatched straight at the
   canvas element. Measured with real CDP input, the topmost element at the
   departure city's own coordinate is `SPAN.dot` — its label's dot, which calls
   `stopPropagation` because a label is not a destination — so the old shape
   could have passed where no finger could reproduce it.
3. The sheet is asserted to unfold. The comment above that block has said it
   must since it was written, and nothing checked it.
4. The live region is asserted, because a HOVER already writes `#time`.
   Matched on "door to door", not "from": the idle status is "Travel times
   **from** Tokyo are ready…", so the first regex reported a committed reading
   on a page that had committed nothing. Caught by rehearsing the check against
   the sea point it used to tap.

The second phone check — "a tap must not scroll the answer out of the sheet" —
was **vacuous** for the same reason: the tap set no destination, so the panel
never opened and the scroll it exists to detect could not happen. Both now share
one `tap_js` helper.

Live: `tap on a phone: {"picked":true,"at":[80,-80],"scrollTop":28,"time":true,
"tints":true,"scale":true,"reading":"1h 5 min"}` and
`tap from folded: {"picked":true,"at":[-40,0],"folded":false,"time":"28min",
"announced":true,"timeOnScreen":true,"legendOnScreen":true}`.

Commits `4a87cce`, `03e81f0`.

## C10-4 — the white dot was not on the city it departs from — **DONE**

Reported by the owner: "흰색 점 좌표가 여전히 어긋나있어."

Cycle 4 fixed the *anchoring* and measured 1.35 px. The remaining error was not
anchoring. Measured live at zoom 8 over Tokyo: **two labels for one city.** One
read "Tokyo", carried the accent dot and sat 0.3 px from the charted
coordinate. The other read **"Ōta"**, carried a WHITE dot, sat **56.6 px** away,
and its title said "Depart from Tokyo".

Two causes.

**Every gazetteer row within 15 km of a charted city became a button for it.**
Over the shipped `places.json` and `index.json`, 595 rows claimed 511 cities.
"Ōta" departed from Tokyo, "Queens" from New York, "Johor Bahru" from Singapore
— a different country. The radius was narrowed to 15 km in an earlier cycle to
stop exactly this (its comment names "Incheon" departing from Seoul), and
narrowing was not enough, because the rule was never "one per city".

**And the button was drawn at the ROW's coordinate under the ROW's name**, so
its dot missed the city it departs from by up to 14.72 km, and its visible text
named a different place from its accessible name (WCAG 2.5.3, Label in Name).

Fixed: only the nearest row to a city carries its button, and a dotted label
carries the city's name at the city's coordinate. The other 84 rows go back to
being place names, which is what they are.

Measured live after deploy, every dotted label against its charted coordinate:

| zoom | dotted labels | worst offset |
|---|---|---|
| 2.5 | 15 | 0.61 px |
| 4 | 38 | 0.65 px |
| 6 | 5 | 0.54 px |
| 8 | 1 | 0.31 px |
| 10 | 1 | 0.47 px |

Commit `e388a93`. Test `tests/web/test_city_label_dots.py` (new). Seven
mutations red — two of them, "keep the first match" and "keep the last match",
were both GREEN against a single row order and neither is "keep the nearest", so
the fixture now presents the two Tokyo rows each way round.

## C10-5 — a click with no journey left the last destination on screen — **DONE**

Not on the brief. Found by C10-3's gate, which after the previous check could
not find a single point on the globe that would read a time.

`setDestination` shows the reading and then returns for a point with no journey.
It did not take the PREVIOUS destination with it, so the page read "no scheduled
route" in 50 px above a full itinerary to JFK, with the flight arc still drawn
across the globe. And because the hover branch takes `lookup()` instead of
`showReading` while `pinB` is set, the headline then never changed again for the
rest of the session. `commitDestination`, the search path, has always cleared it.

The three teardowns are one function now, `dropDestination()`. `lastPointer`
normally goes with the pin; the new caller is the exception, because it has just
called `showReading` itself, and nulling a live pointer would strand "Reading
the travel times from X…" in the headline after the next origin switch
(`rereadPointer` returns early on a null pointer with no pin).

Two existing tests broke and **both were strengthened, not relaxed**:

- `test_readout_state.py` scanned a two-line window around every `pinB = null`.
  It now requires exactly one clearing site, inside `dropDestination`, and that
  the `keepPointer` opt-out has exactly one caller, which must be the function
  that refreshed the pointer.
- `test_attribution_and_privacy.py` sliced `setDestination`'s body to the first
  `renderLegs()` to check it reveals before it announces. The new early-return
  branch calls `renderLegs()` before `unfoldSheet()`, so the window ended too
  early and the search raised `ValueError` on correct code. Both files bound a
  function by brace matching now.

Commit `03e81f0`. Nine mutations red.

---

## C10-15 — the dashed ground legs flow toward the destination — **DONE**

A fifth item from the owner, after the four defects: "transport 나타내는 점선이
흐르는 애니메이션으로 나타나게 해줘". The dashed legs are the journeys to and
from the airports; the solid arcs are the flights and stay solid, because a
solid line has no dashes to move.

**How.** MapLibre has no dash offset and `line-dasharray` is not data-driven, so
the pattern itself is stepped. Two facts were read out of the vendored bundle
rather than assumed:

- `LineAtlas.getDash` keys its cache on `dasharray.join(",")`. A continuously
  varying array would rebuild and re-upload a dash texture every frame and grow
  that cache without bound, so the cycle is a FIXED set of twelve.
- `getDashRanges` starts an odd-length array at `-last`, wrapping the final
  element around to before the line's start. That is what makes the
  three-element phase shift `[D-s, G, s]` exact.

Every frame's array totals exactly one period, so the spacing does not breathe
as the pattern moves, and `renderRoute` adds every leg departure-first, so a
decreasing phase moves the dashes toward the destination.

**Guards, all measured on the live page, not reasoned about.** The loop runs
only while a drawn route actually contains a ground leg; it stops on a hidden
tab; and under `prefers-reduced-motion` the dashes are static, not slower,
resting on the layer's own `[2, 2.5]`.

**Cost at 390x844, measured on the deployed build.**

| state | map repaints/sec | dash writes/sec | frame p50 | frame p95 |
|---|---|---|---|---|
| no destination (loop off) | 0 | 0 | 16.7 ms | 16.7 ms |
| journey drawn (loop on) | 60 | 16.6 | 16.7 ms | 16.8 ms |

Isolated on one page with the route left drawn: stopping the loop through its
own hidden-tab guard took the map from 60 repaints/sec to **0**, so the whole
cost is the animation and none of it is the line.

**The cost is 60 fps, not the 17/sec the design aimed at, and slowing it down
does not help.** Measured at four cadences with the route drawn:

| dash write every | writes/sec | repaints/sec |
|---|---|---|
| 60 ms | 16.5 | 59.0 |
| 120 ms | 8.3 | 58.3 |
| 200 ms | 5.0 | 57.3 |
| 360 ms | 2.8 | 54.0 |

One `line-dasharray` change puts MapLibre into a sustained repaint that outlasts
the gap to the next one, so the map never settles between steps. It is not the
fade duration: forcing `fadeDuration` to 0 left it at 59.3. No frames are
dropped either way (p95 16.8 ms), so this is battery, not smoothness. Recorded
in `deferred.md` as C10-16 with the one mitigation that would work.

**Verified live after deploy:** 49 forward steps and 0 backward, 12 distinct
patterns, 2 ground legs animated beside 3 solid air legs, and on clear the map
returns to 0 repaints/sec with the dasharray back at `[2, 2.5]`.

Commits `d46ab4b`, `c0e9876`. Test `tests/web/test_route_flow.py` (new, 14
tests). Ten mutations red.

## C10-15a — two animations shipped at once, and one ran backwards

Not a defect this cycle introduced by design, but one it had to clean up. A
concurrent agent committed `397ded7` while this work was in the tree, and BOTH
implementations went live. Measured on the deployed page: 26.6 dasharray writes
a second and **20** distinct patterns against the twelve one cycle defines.

The duplicate was removed on its own merits, computed from its own `DASH_CYCLE`:
its frames totalled 4.8126 to 7.0001 line widths, so the period swung 45% and
the dashes stretched and compressed rather than flowed; and its leading gap
decreased every step, so the flow ran toward the DEPARTURE, the opposite of what
its own comment and commit message claimed.

`397ded7` also deployed over a **red gate**: it added a `setRouteFlow()` call
inside `renderRoute`, which `tests/web/test_route_geometry.py` extracts and runs
standalone, and that file is part of `page_gate`. Checked out against its own
app.js: 1 failed, 5 passed. Repaired in `d46ab4b`.

A guard now asserts exactly one writer of `route-ground`'s dasharray and exactly
one frame loop driving it.

## C10-17 — the origin-label check blamed the page for a late gazetteer — **DONE**

Reported as "clicking an origin label did not change the departure". The page
was fine. Measured live: labels are ready 202 ms after load, and the bands
source changes 114 ms after the click, because `paintOrigin` calls
`map.addSource("bands", …)` synchronously — no fetch stands between the click
and the url.

What the check could not tell apart was "the click did nothing" from "there was
nothing to click". It slept a fixed 6 s for labels that come from
`places.json`, 1.8 MB, now sharing the connection with the 10 MB reading tier.
With the gazetteer not yet landed there was no `.lbl.origin`, and BOTH failures
fired — including one naming a defect the page did not have.

Fixed by polling for the label (25 s), then polling for the source to change,
and reporting which of the two happened. Two further corrections: the assertion
is now "the url CHANGED from what it was", read before the click, rather than
"it stopped saying seoul" — the same hardcoded-geography mistake the phone taps
made with `[120, 40]`; and the "not an origin archive" failure is matched
against the real url shape.

Both failure paths were exercised on the live page, not reasoned about.
Replacing every label with a clone to strip its handlers reported
`unchanged:true`; making `querySelectorAll(".lbl.origin")` return nothing
reported `noLabel:true, labels:0`.

Explicitly NOT this cycle's regression: the guard that makes `paintOrigin`
ignore a click on the current departure predates it (`bfa7e10`), and Seoul has
exactly one gazetteer row within 15 km, 0.06 km away, so it never had the
duplicate label that would have made the gate click its own departure.

Commit `5cf7ad2`.

---

## Gates

`uv run ruff check .` — **All checks passed.**

`uv run pytest` over the whole repository — **747 passed, 4 deselected, 0
failed**, exit 0, 17 min 14 s. The 4 deselected are the `real_multi_band` tests,
deselected by default.

Page-asset gate on the deploy path — 251 passed.

`scripts/deploy_verify.sh --page-only` — **ALL CHECKS PASSED**, run four times
(three iterations plus the final wording change). Console errors 0; all four
viewports clean at 1280×800, 820×1180, 390×844 and 844×390.

The two checks that failed before this cycle now report:

| check | before | after |
|---|---|---|
| a searched destination, headline vs total | `head 16h 23 min`, `total 16 h 20 min`, `agree:false` | `head 16h 23 min`, `total 16 h 23 min`, **`agree:true`** |
| tap from folded at 390×844 | `reading "∞no scheduled route"`, `folded:true` | `picked:true`, `time "28min"`, **`folded:false`**, `announced:true`, `timeOnScreen:true`, `legendOnScreen:true` |

GATE_FIXES this cycle: 1 (`tests/web/test_city_label_dots.py` tripped UP031;
rewritten as an f-string, not suppressed).

## Scheduled, not done this cycle

| ID | Finding | Where | Cycle |
|---|---|---|---|
| C10-P1 | Emit cell predecessors (or a res-6 arrival-airport array) so the remaining 3.8% of chains can be completed instead of shown as partial. Needs a rebuild. | `emit/routes_json.py`, `emit/itinerary.py` | next build |
| C10-6 | A sea point inside a land res-4 parent reads "∞ no scheduled route" rather than "Open water." The page has no res-6 land set, so it cannot tell padding from genuine unreachability. See `deferred.md`. | `web/app.js` `lookup()` | needs C10-P1's build |
| C10-7 | `ARCH10-2` (HIGH): the res-4 cell ordering is re-derived verbatim in four emitters. A change preserving the count but moving the order silently misaligns `.air.bin`, `.modes.bin` and `.rail.bin` against `.bin`; every gate compares byte length only. | `emit/hover.py:98`, `modes.py:91`, `itinerary.py:58`, `rail_detail.py:86` | next build cycle |
| C10-8 | `TE10-1` (HIGH): `page_gate` loses 31% of `tests/web` when `node` is not on PATH, and exits 0. `test_parses.py` — the only thing that syntax-checks `app.js` — is among them. | `scripts/deploy_verify.sh` `page_gate()` | next gate cycle |
| C10-9 | `DOC10-1` (HIGH): `modeDetail.rail` says rail costs "plus 15 min to board"; `graph/build.py:270-274` also charges `alighting_min = 5.0`. Every rail leg pays 20 minutes. User-facing. | `emit/index.py:166`, `web/llms.txt:30` | next docs cycle |
| C10-10 | `CR10-1` (MEDIUM): restoring a shared link sets `geocoded` backwards, producing a false Nominatim credit and dropping the label on the next re-share. | `web/app.js:3445-3447` | next page cycle |
| C10-11 | `ARCH10-4` / `UX10-*`: the departure marker's `addTo`/`remove` live inside the `places.json` fetch closure, so a failed 1.8 MB gazetteer leaves the departure city with no marker while the opening copy says to tap one. | `web/app.js:1048,1063-1067` | next page cycle |
| C10-12 | `UX10-1..4` (HIGH, designer): the globe has no visible focus ring (its UA outline paints outside the viewport); the "Privacy" link focuses a heading 1,334 px below the fold and never scrolls; on phones 267 px of controls sit below the fold with no cue; map city buttons are 23 px tall (SC 2.5.8 needs 24). | `web/index.html` | next page cycle |
| C10-13 | `PR10-2` (HIGH): `.r6.bin` is 10,014,228 B, re-fetched on every visit (measured: three requests for one origin in an A→B→A→C→A walk), served with `Cache-Control: no-cache` and no `gzip_static`. Delta-encoding each 343-slot block is losslessly 25.5% smaller. | nginx, `emit/hover.py` | next perf cycle |
| C10-14 | `PR10-3` (HIGH): four emitters each rebuild the same origin-invariant res-4 parent mapping twice — about 81.6 M `h3.cell_to_parent` calls per origin. The tier-B layout beside it is already hoisted. | `emit/*.py` | next build cycle |
