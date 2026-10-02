# Four features the owner asked for

**Status at 2026-10-02** (C13-11 / V13-16; the title used to read "PLANNED, NOT
BUILT", which described cycle 10 and went stale): F1 draggable markers shipped
in `6214283`. F2, the on-demand solver, is superseded by
`2026-09-14-c13-solver-service.md` and runs on the web host. F3, many more
departure cities, shipped in `b21e808`. F4, ETOPS, was answered as a
documented decision not to build it, in `12e68ac`. The analysis below is
cycle 10's and is kept as written.

None of these was implemented in cycle 10. The orchestrator's instruction was
explicit: write them up with enough analysis that a later cycle can pick one up.
Facts below are read from the code and the shipped artefacts, not estimated,
except where a figure is flagged as unmeasured.

Library fact used throughout: `web/vendor/maplibre-gl.js` is MapLibre GL JS
**5.24.0**, pinned per `web/README.md:23`, carrying a one-token local security
patch. **Do not silently re-vendor it without re-applying that patch.**

---

## F1 — Draggable start and end markers, start snapping to the nearest city

### What the library already does

`Marker` in this exact build supports `draggable` as a constructor option,
`setDraggable(bool)`, and fires `dragstart` / `drag` / `dragend`. Its drag
handler is wired through `this._map.on("mousedown"/"touchstart", …)` and scoped
to `this._element.contains(e.originalEvent.target)`, and the library calls
`preventDefault()` itself, so a drag does not also pan the map. **There is no
library gap to work around.**

### The two markers are not symmetric, and that is the design decision

- The **departure** marker is already a `maplibregl.Marker` (`web/app.js:969`,
  `anchor: "left"`). It is the natural target for `draggable: true`.
- The **destination** marker is **not a Marker at all**. `drawPin()`
  (`web/app.js:2359-2365`) pushes `pinB`'s coordinate into a GeoJSON
  `map.getSource("pin")` styled by a paint layer, and MapLibre layers cannot be
  made draggable — only DOM Marker elements can.

**So the concrete decision this feature forces:** replace the destination's
layer-rendered dot with a second `maplibregl.Marker`, mirroring the departure
marker, rather than hand-rolling `mousedown`/`mousemove` hit testing against a
rendered layer feature. One drag implementation in the file, not two.

**Fix C10-11 first or together.** The departure marker's `addTo`/`remove` live
inside the `places.json` fetch closure, so a failed gazetteer leaves the visitor
with no departure marker at all. A draggable control the visitor sometimes does
not have is worse than a static one.
CORRECTION (C13-11 / V13-15, 2026-10-02): F1 shipped (`6214283`) WITHOUT this
precondition. The departure marker is still added only inside `showLabels`,
which is assigned in the `places.json` `.then`. The `.catch` leaves it a
no-op, so a failed gazetteer still means no draggable departure marker. C10-11
remains open in `2026-09-13-c10-four-live-defects.md` ("next page cycle").

### It needs no new state machine

`paintOrigin(o, {keepZoom})` (`web/app.js:1332`) is already the single
epoch-guarded entry point every "become the departure" affordance calls — the
label click at `:1030`, the "Depart from X" button at `:2409-2417`. A `dragend`
handler that resolves the drop point and calls `paintOrigin(nearest,
{keepZoom: true})` is the **fifth** caller of a battle-tested function.

Commit on `dragend`, never per `drag` tick: reuse the existing precedent that
debounces camera writes to `moveend`/`rotateend`/`pitchend` (`:1286-1288`). A
live "Snap to Seoul" preview during the drag touches nothing epoch-guarded.

### Nearest-city cost: no spatial index

`originNear(lat, lon, maxKm)` (`web/app.js` — now beside `dottedCityRows`) is a
plain O(553) haversine scan with no index, already called on every render of the
"Depart from X" affordance. At 553 candidates a full scan is sub-millisecond.
**Building an index would be premature.** The file already treats a per-frame
O(553) cost as acceptable elsewhere.

The real choice is the **snap radius**. The existing 15 km default answers "does
this label sit on a charted city" and is far too tight for a deliberate drag.
Recommend 300–500 km with an explicit disclosure ("no charted city near here —
showing the nearest, Reykjavík") rather than a silent snap, and
revert-to-previous if the drop is absurdly far from every origin.

Cycle 10 note: `dottedCityRows` now proves the 15 km radius alone does not make
a match trustworthy — "Johor Bahru" was inside it for Singapore. Whatever radius
F1 picks, the label must name the city it will actually depart from.

### Touch, and hit-target size

Panning is handled by the library **provided the marker's DOM element is the
actual pointer-down target**. What is not handled is size: the label elements
are sized to their text and dot, not to a 44×44 CSS px target (WCAG 2.5.5). Add
a transparent padded hit area around the visible dot, following the "the dot is
placed by CSS, not by a pixel offset" discipline documented at `:960-968` — and
now enforced by `tests/web/test_city_label_dots.py`.

Measured in cycle 10 and directly relevant: at the departure city's own
coordinate, `document.elementFromPoint` returns `SPAN.dot`. The dot is already
the hit target there, so enlarging it changes what a click at that point does.

### Accessibility is mandatory, and the precedent is in the file

MapLibre's Marker drag is pointer-only. `web/app.js:2529-2534` already records
the rule to follow: "Arrows turned it and +/- zoomed it, and then the page's
whole point was unreachable without a pointer. Enter now does at the centre of
the view what a click does under the cursor."

Extend that: a focusable (`tabindex="0"`) marker whose Enter/Space moves the
departure to the map's current centre, snapped to the nearest charted city, with
an accessible name saying what will happen. One handler reusing `originNear` and
`paintOrigin`. No arrow-key nudging to invent.

### Permalink

**No format change for this scope.** `?from=<slug>` (`:1224`) already names a
charted city, and a drag ending in `paintOrigin(nearestCity)` is
indistinguishable to the permalink writer from a label click. Arbitrary-point
departures (F2) WOULD need `?from=lat,lon`, analogous to `?to=lat,lon` at
`:1225` — design the URL shape for both at once so `?from=` gains the same two
forms `?to=` already has, rather than twice.

---

## F2 — An on-demand solver service, so any point can be a departure

The owner has **approved this direction**. It ends the site being purely static
and needs its own design.

### The first task is to measure, because nothing here is measured

`solve/dijkstra.py` is a 28-line wrapper over `scipy.sparse.csgraph.dijkstra`,
single-source, over the whole assembled multi-modal graph. **There is no
instrumented per-origin wall-clock figure anywhere in the repository** —
`cli.py` has no `perf_counter` around `solve_from` or the per-origin loop.

The only numbers on record are both unusable as current fact:

- a stale ~16–17 h projection for the full 553-origin build across several
  workers, which predates the res-6 solve grid and the res-6/7 reading tier and
  so probably **understates** today's cost;
- `deferred.md` DEF8-8: a ~13.75 M-entry structure rebuilt 3–4× per origin,
  ~6–7 CPU-hours across the whole current build, plus a ~30–40 s/origin
  pure-Python predecessor walk (H3).

**Task 1 of building this service is one timing line around the existing
solve/emit loop.** Every sizing decision below depends on that number.

### What must be resident

The full `NodeIndex` (`graph/nodes.py`) and its weighted CSR adjacency, built by
`graph/build.py`. The batch build already keeps this per worker and already does
the build-once-share trick: `cli.py:395` uses `get_context("fork")` so children
inherit the warmed `roads._grid_cache` (`cli.py:344`) copy-on-write. A resident
solver builds NodeIndex + CSR **once at process start** and holds it for the
process lifetime. That is a persistence change, not a rewrite of graph assembly.

Scale: `deferred.md` PR-1 measured five concurrent batch workers at 11–12 GB RSS
each with the host swapping. One resident copy is plausibly in the same
multi-GB range — so **one service instance is cheaper than the batch build
already is at its default concurrency**, provided it holds one copy and never
forks per request.

### What one Dijkstra answers, and why that bounds the response

`solve_from(csr, source, with_predecessors=…)` has **no target parameter**. It
always solves to every node regardless of how many destinations the caller
wants, and there is no cheaper single-pair primitive today — no A*, no
bidirectional search, no early termination. The COST is fixed once the source
is fixed; the RESPONSE can be cheap.

A full isochrone map (band polygons as `.pmtiles`) is a fundamentally heavier
ask: it additionally needs `contour/{bands,grid}.py` and `emit/tiles.py`'s
external `tippecanoe` subprocess, today an offline, disk-bound, minutes-long
step.

**Recommendation, to be stated to the owner as a scoping decision and not an
accidental limitation:** the first iteration answers *"how long from here to the
point I click"*, not *"draw me the whole isochrone map from here."* The leg
breakdown can reuse `emit/modes.py`'s decomposition, so the answer can be a
full itinerary, not just a number.

### Reusable as a library, largely unmodified

`graph/nodes.py`, `graph/build.py`, `solve/dijkstra.py`,
`graph/{air,rail,ferry,ground,headway}.py`, `emit/modes.py`'s leg
decomposition, `_io`, `config`.

`solve/dijkstra.py:21-27`'s `origin_node()` already does exactly the validation
a service needs — snap an arbitrary (lat, lon) to its graph node, raising on
open water — but it raises a bare `ValueError`, the same taxonomy gap as
`validate.py`'s gates. **The service boundary must translate that into a clean
4xx, not let it surface as an unhandled 500.**

Explicitly out of the request path: `sources/*` (offline crawl + cache, httpx,
multi-hour) build the graph and are never called per request; `contour/*` and
`emit/tiles.py` for the reason above.

### Degradation, caching, abuse

- **Strictly additive.** The 553-city static experience must keep working with
  zero dependency on the service. Gate the affordance behind an explicit action
  plus a health check, and on failure degrade the way the tier-B reading
  fallback already does: never call `fatal()`, say "on-demand solving isn't
  available right now — pick a charted city", let the next click retry.
- **Cache on the resolved H3 cell id, not raw floats.** Cost depends only on the
  source cell, so this dedupes near-identical clicks for free and makes a
  popular uncharted point a one-time cost.
- Worker pool sized to the host's cores (mirroring `cli.py`'s
  `BUSY_CPU_PERCENT` idea), a per-session/IP rate limit, and a request timeout
  with a graceful failure. Per-request cost is plausibly seconds, not
  milliseconds, until measured.
- **Design in the loop to F3 now:** log which uncharted cells get requested and
  periodically promote the popular ones into `origins.toml` via the existing
  `scripts/expand_origins.py`.

### CSP — the owner's call, stated plainly

The deployed page runs behind a strict CSP whose `connect-src` names exactly two
third-party destinations (Nominatim, the analytics tag). **A new solver API,
even on a subdomain of the same site, is a distinct origin and WILL BE BLOCKED**
unless the owner edits `deploy/worldmap-security-headers.conf`. Changing the
server is the owner's decision, not ours.

The design that avoids forcing that conversation is to serve the API from the
**same origin under a path prefix** (`/api/solve`), which stays inside
`connect-src 'self'` with no CSP change, at the cost of coupling API deployment
to the static web server. A separate subdomain is a legitimate alternative with
cleaner isolation of a CPU-bound service from a file server, but it is the one
needing sign-off. **Recommend leading with same-origin.**

---

## F3 — Many more departure cities

### Per-origin bytes, from the real `index.json`

`hoverCellCount = 90,740`; `readingParentCount = 14,598`; `readingSlots = 343`;
6 mode channels.

| artefact | bytes raw |
|---|---|
| `.bin` (times, res 4) | 181,480 |
| `.air.bin` | 181,480 |
| `.modes.bin` (6 channels) | 1,088,880 |
| `.rail.bin` | 181,480 |
| `.r6.bin` (reading tier) | **10,014,228** |
| `.pmtiles` | ~250–290 KB, order of magnitude only (PR3-6 predates the current resolution) |

**~12 MB raw per origin, over 80% of it the reading tier.** At 553 origins,
~6.6 GB. The cycle-7 archive's "49.8 GB over 553" figure is from an earlier
padding design and is superseded.

### Scaling

The reading tier's per-origin cost is **flat in origin count** — it depends on
global land-cell counts — so storage is linear at ~12 MB/origin: 2,000 origins
≈ 24 GB, 5,000 ≈ 60 GB. A cheap-disk problem.

**Do not conflate this with the per-visitor-switch bandwidth cost** already
flagged as DEF9-5 (~5.2 MB gzipped refetched on every city change). That does
not grow with origin count; a visitor loads one origin at a time.

### The roster is close to solved

`scripts/expand_origins.py` already pulls GeoNames `cities15000` (~25,000+
candidates), adds every city above a population threshold or every national
capital above a lower one, skips anything within 40 km of an existing entry, and
only appends. **2,000–5,000 origins is largely a lower `--min-pop`, not a
curation project.** Past ~5,000 needs `cities5000` / `cities1000`.

### The real ceiling is build time, and it is unmeasured

Two recorded scaling blockers are unfixed: DEF8-8 (~6–7 CPU-hours across the
current build) and H3 (~30–40 s/origin pure-Python predecessor walk in
`emit/modes.py`). A 4–9× origin increase on top of an already multi-hour build,
without fixing either, plausibly makes it a multi-day job.

Memory is **not** the same constraint: each worker processes one origin's graph
at a time regardless of total origin count, so PR-1's 11–12 GB/worker is a
concurrency question.

### Order of work

1. Instrument real per-origin wall-clock time — a prerequisite for every other
   estimate here, and shared with F2's task 1.
2. Land DEF8-8 and H3/H5 **before** multiplying origin count.
3. Storage: no architecture change, just disk (~24–60 GB).
4. Re-run `expand_origins.py` at a lower population threshold. No code change.

---

## F4 — An ETOPS option in settings

**Recommendation: do not build it.**

The owner flagged the caveat themselves — scheduled routes already comply with
ETOPS — and asked for its effect on modelled travel time to be justified before
it is built. Read `graph/air.py` in full (92 lines) and the flight-edge assembly
in `graph/build.py`. The model is:

```
block_time_min = taxi_out_min[dep_size] + climb_descent_penalty_min
               + 60 * distance_km / cruise_kmh + taxi_in_min[arr_size]
```

`distance_km` comes from `h3.great_circle_distance(...)` (`build.py:82,189`) — a
straight-line great-circle distance between the two airports, **always**. There
is no routing graph for flights, no per-aircraft-type distinction, and no
alternative "direct vs ETOPS-compliant" distance anywhere in the file or its
callers. `frequency_model` is a pure gravity function of distance and airport
size, with no ETOPS-adjacent term.

**An ETOPS toggle would change nothing the page shows, and there is no honest
mechanism by which it could.**

1. Flight time comes from great-circle distance only. There is no representation
   of a flown track that could differ between compliant and non-compliant
   routings, so there is no lever to move.
2. Every flight the model prices comes from a real scheduled route (Wikipedia
   "Airlines and destinations" resolved via Wikidata, per `sources/routes.py`
   and `wikidata.py`) — already flown under whatever certification its operator
   holds. There is no non-ETOPS alternative in the data to switch away from.
3. The only way it could mean anything is a different feature entirely:
   modelling *hypothetical* unserved direct routes and inflating their distance
   by an assumed diversion detour factor. That is not a toggle on the existing
   model; it is a new speculative modelling mode that contradicts the project's
   premise of measuring real scheduled transport, and under CLAUDE.md's
   modelling rule it would need its own calibration and disclosure.

If the owner wants a settings-panel item here, the honest content is a short
static disclosure — "scheduled flights are already ETOPS-compliant; this map
does not model diversion routing" — not a toggle that visibly does nothing.
