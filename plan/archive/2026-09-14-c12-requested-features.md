# Cycle 12 — the three tasks the owner named

Derived from the eleven-lane review in `.context/reviews/` (cycle 12; per-agent
IDs `CR12-n`, `SEC12-n`, `PR12-n`, `TE12-n`, `CRIT12-n`, `ARCH12-n`, `UX12-n`,
`VER12-n`, `TR12-n`, `DBG12-n`, `DOC12-n`, aggregate `_aggregate.md`).

Scope discipline: this cycle implements these three plus HIGH-severity
correctness and security only. Everything else the review found is scheduled in
`2026-09-14-c12-review-findings.md` or recorded in `deferred.md`.

---

## F1 — `esc()` has no test

**Named by cycle 11.** The security lane traced every HTML sink and found the
surface closed; the helper that closes it is itself unguarded.

`esc()` at `web/app.js:28-29` neutralises exactly four characters — `&`, `<`,
`>`, `"` — `&` first. Six sinks write HTML: `:350`, `:2144`, `:2148`, `:2228`,
`:2540`, `:2546`/`:2627`. Two of them (`ap()` at `:2144`, `mode()` at `:2148`)
interpolate into **double-quoted attributes**, which is the one place the `"`
replacement is load-bearing — it is what stops an OurAirports or OSM name from
closing `data-tip="` and adding an event handler.

Zero of 772 tests assert anything about it. Worse, `tests/web/test_itinerary_grid.py:128`
**stubs `esc` to the identity function**, so the one harness that runs its call
sites has the escape disabled: deleting the `"` replacement opens live XSS and
leaves the suite green (TE12-1, SEC12-1).

### What the test must do

| requirement | why | the mutation it must catch |
|---|---|---|
| all four characters, exact equality | `assert "&lt;" in esc("<")` still passes when `&` is replaced last and the output is `&amp;lt;` | reorder the replacements |
| each character **twice** in one input | a single occurrence cannot see a missing `/g` | drop `/g` from any replace |
| `&`-first ordering | `esc("&amp;") == "&amp;amp;"` | move the `&` replace to last |
| `String()` coercion | sinks pass `undefined`, numbers | drop `String(...)` |
| a text-context payload | `:350`, `:2540`, `:2546` | drop `<` or `>` |
| an **attribute**-context payload | `:2144`, `:2148` — `" onmouseover="alert(1)` | drop `"` — the mutation a text-only test misses |

Structural traps, from TE12-8: every existing `_function()` extractor matches
`function NAME(`, and `esc` is a two-line `const` arrow, so a `_const()` slicer
is needed **and must self-check** that all four `.replace(` calls are inside the
slice — a missed slice is a green test of nothing.

- [x] **F1.1** Add `tests/web/test_esc.py` following the `test_route_geometry.py`
      idiom: slice the source out of `app.js`, run it under Node over
      `process.argv`, module-scoped `run` fixture.
- [x] **F1.2** Cover all six requirements above.
- [x] **F1.3** Assert the sink inventory, so a seventh sink that forgets `esc`
      fails here rather than on the live site.
      CORRECTION (C13-11 / V13-8, 2026-10-02): as shipped, the inventory saw three of
      the six live sinks. It was rewritten as C13-5 in `268e98d`. Removing
      `esc()` from `active.name` or from `where` now turns
      `test_every_html_sink_routes_through_esc` red. The tick holds since
      `268e98d`, not since cycle 12.
- [x] **F1.4** Pin that `'` is deliberately **not** escaped and is safe only
      because no sink uses a single-quoted attribute — verified true today,
      unguarded until now.
- [x] **F1.5** Mutate and confirm red. Seven mutants, each reverted.

---

## F2 — draggable start and end markers

> "starting point 도 임의의 지점으로 잡을수 있게 해줘. start, end 드래그도 되게."

### The honesty constraint

Only the charted cities have precomputed data. The destination may go anywhere;
the **start may not**. A dragged start must snap to the nearest charted city and
say so, and — this is the part that is easy to get wrong — **the marker itself
must return to that city**. A marker left sitting where it was dropped is the
lie, whatever the text alongside it says.

The rule is an **unconditional** snap to the nearest origin, with the distance
always stated. No threshold: a radius-limited snap leaves drags that silently do
nothing, and `web/index.html:917` already promises "a departure snaps to the
nearest of them" — which an unconditional snap finally makes true (CRIT12-5
measured it false today for 58.7% of populated places).

Copy, one template so it cannot drift (UX12-6):

> Moved to Osaka — the nearest departure city, 34 km from where you dropped the
> marker. Times are measured from Osaka, not from that point.

During the drag, in the same slot: **"Will depart from Osaka, 34 km from here."**
Off the globe: **"Off the globe."** Dropped where the nearest city is the one you
already departed from: **"Kept Seoul — still the nearest departure city, 41 km
from where you dropped the marker."**

### Integration points (ARCH12-7, verified against the file)

- Start marker element `app.js:1060-1074`, `Marker` at `:1075`, positioned at
  `:1737`, added/removed inside the `places.json` closure `:1136-1215`.
- Commit through `paintOrigin(o, { keepZoom: true })` at `:1459` — already the
  single epoch-guarded entry, four existing callers. It calls `setLngLat` at
  `:1737`, which is what returns the marker to the real city.
- Nearest origin: `haversineKm` `:2878`. **Not** `originNear` `:2924`, which
  returns null past 80 km — wrong for a drag, and the trap an implementer
  falls into.
- The destination is **not** a marker: `map.addSource("pin")` `:806` plus circle
  layers `:807-811`, drawn by `drawPin()` `:2640`. Converting it to a `Marker`
  would break `tests/web/test_app_constants.py:365-377`, which asserts the route
  layers are lifted before `pin-halo`. So the circle layers **stay** and a
  transparent draggable handle rides on top: no layer-order change, no test
  change, and a 32 px touch target on a phone where a 9 px circle has none.
- Commit the destination through `commitDestination()` `:2715`.

- [x] **F2.1** Make the start marker draggable; live feedback in `#where`.
      CORRECTION (C13-11 / V13-13, 2026-10-02): the live feedback goes to `#snapped`
      (`snapNotice()`, called from `originDragMove()`), not to `#where`, which
      a drag never writes. The behaviour is right; the element name in the
      task text was wrong.
- [x] **F2.2** Snap unconditionally to the nearest origin on dragend; return the
      marker to that city's real coordinates.
- [x] **F2.3** Say plainly that it moved, with the distance, in a dedicated slot
      that survives the origin switch.
- [x] **F2.4** Add a transparent draggable handle over the destination pin; live
      reading during the drag; commit on dragend.
- [x] **F2.5** Keyboard and screen-reader equivalence: dragging is
      pointer-only, so both already-existing keyboard paths keep working.
      CORRECTION (C13-11 / V13-14, 2026-10-02): overstated. Both existing keyboard paths
      do still work: Enter or Space on `#map`, and the city list. But the
      destination handle is announced as a button reading "Drag to move it"
      and cannot be focused. MapLibre adds a tabindex only to default and
      popup markers, so `.pinhandle:focus-visible` never applies, and no key
      handler moves it. There is no keyboard equivalent of dragging the
      destination, and none was built. Recorded as D13-2 in the cycle-13
      findings.
- [x] **F2.6** Tests, mutated and confirmed red.

---

## F3 — an ETOPS option in Settings

> "etops 적용도 설정에서 되게 해줘."

### The finding: there is no lever

Three lanes searched independently (CRIT12-6, ARCH12-8, UX12-2) and found the
same thing. **No aircraft type, engine count, operator or equipment field exists
anywhere in this repository's data, code or sources.**

| where you would look | what is actually there |
|---|---|
| `dist/airports.json` | exactly `iata, name, country, lat, lon, size` |
| `sources/routes.py:267-322` | a parquet of `["src","dst"]` IATA pairs; the airline column is discarded |
| `scripts/adsb_extract.py` | keeps `(t, lat, lon, alt)`; discards the type code the traces carry |
| `graph/air.py:52-59` | `taxi + climb/descent + 60·d/cruise_kmh + taxi`, affine in great-circle distance, unbounded |
| `grep -rE 'etops\|overwater\|diversion\|range_km\|twin\|oceanic' src/` | zero hits |

The three credible options, each assessed against that:

1. **Draw the diversion-airport constraint on the arc.** Rejected on
   measurement. "Adequate alternate" would have to be inferred from `size`, and
   CRIT12-6 checked that against the shipped file: Lajes, Cold Bay, Goose Bay,
   Iqaluit, Kangerlussuaq, Kodiak, Wake and Ascension are all `medium`, and
   Midway and Shemya are **absent entirely** — structurally so, because
   `sources/airports.py` keeps only `scheduled_service == "yes"`. A
   "large = alternate" rule would exclude every canonical alternate and include
   1,148 city airports that are not one. It would also need a single-engine
   drift-down speed the repo does not have, and a flown track — while the page
   draws great circles, which is precisely what an ETOPS-limited flight does not
   fly.
2. **Mark twin-engine arcs.** Rejected on data. Needs per-route equipment. The
   only sources are commercial schedules, which shipped prose already rules out
   ("no commercial flight data is used anywhere", `index.html:1019`), or a new
   ADS-B type-code crawl, which is a different project.
3. **Report that the time effect is nil, and explain why.** Accepted, prose
   only. The visual half of this option needs the same flown track that does not
   exist.

### Decision

**No control ships. A statement ships, in Settings, where the owner looked for
it.**

A toggle here is a placebo by construction, and a placebo is worse than nothing:
a switch that visibly does nothing claims more modelling sophistication than
saying nothing at all, and the brief is explicit that "the page must not claim
the number changed when it did not". Cycle 10 had already established that
scheduled routes comply with ETOPS; what cycle 10 left out is the more useful
half, and it is what gets written down — **not merely that it makes no
difference, but why the model could not represent one if there were.**

The Settings entry uses the existing `.rampwrap` + `.rowlabel` + `.hint` group
idiom **with no control inside it**, so its shape reads as a statement rather
than a switch. The same explanation, at length, goes in "Sources and method →
What this does not know", which already holds three paragraphs of exactly that
shape.

- [x] **F3.1** Settings entry, no control, in the existing group idiom.
- [x] **F3.2** The full paragraph in "What this does not know".
- [x] **F3.3** A test that fails if a control is ever added under that label
      without the model gaining a lever.

---

## Status

All three tasks landed in cycle 12. See the commit trail for the mutation
evidence on each test.
