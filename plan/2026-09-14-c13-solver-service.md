# F2 — the on-demand solver service: the design, and what it really costs

Supersedes `2026-09-13-c10-requested-features.md:110-217`, which is the cycle-10
analysis this replaces. Three of that section's load-bearing claims are false,
measured this cycle by four independent review lanes; they are corrected below
with the measurement and the lane that made it.

The owner asked for an arbitrary departure point — "starting point 도 임의의
지점으로 잡을수 있게 해줘" — and, told it needs a server that solves on demand,
chose exactly that over the static alternatives. **This document designs it and
does not build the resident half.** A solver holding 13.8 million nodes and
82 million edges would contend for RAM with the 39-hour `rebuild20` that owns
the machine, on a box already 10.9 GB into a 12 GB swap file.

Every figure here is measured unless it says otherwise. Where a quantity is not
measured it says so in those words.

---

## The verdict, in five lines

1. **It is buildable, and it costs 3.40 GiB resident and 207 s to start.** Both
   are far below cycle 10's guesses. It can share the owner's host with nginx
   **after** the current build finishes, and not during it.
2. **A solve is 10–11 s, not 3 s.** The 3 s figure has no measurement behind it.
3. **`scipy.sparse.csgraph.dijkstra` takes `limit=`.** Cycle 10's "no early
   termination" is wrong, and it is the claim that made 10 s look unavoidable.
   A bounded solve is 21× faster on the case measured.
4. **The static site must not gain a dependency, and now cannot.** The page's
   solver client is behind a flag that is off by default and that the address
   cannot arm; it never reaches `fatal()`; every failure ends in a sentence.
   Built and tested this cycle.
5. **A cheaper answer exists and the owner should see it before the service is
   built.** See "The alternative this cycle is obliged to put in front of the
   owner" below. It is not this document's job to overrule a decision the owner
   has already made, but it is its job to report a measurement that changes the
   question.

---

## What cycle 10 assumed, and what is true

| quantity | `c10-requested-features.md` | measured, 2026-09-14 | lane |
|---|---|---|---|
| one full-graph solve | ~3 s ("plausibly seconds") | **10–11 s** | perf |
| early termination | ":153-154 no target parameter … no early termination" | **`limit=` exists and works**: 2.1 % of nodes reached in 0.01 s against 0.21 s for the full solve, 21× | architect, critic |
| resident memory | ":168-172 plausibly in the same multi-GB range" as 11–12 GB/worker | **3.40 GiB idle, 3.97 GiB with one solve in flight** | perf |
| cold start | not stated | **207 s** | perf, architect |
| reuse `emit/modes.py` per request | ":226-228 the leg breakdown can reuse it" | **refuted**: each call `argsort`s 13.8 M nodes and allocates 663 MB, about 18 s | architect |

The solve timing is extrapolated from three measured points — 0.51 s at 6 M
edges, 2.27 s at 24 M, 5.48 s at 48 M — to the graph's real 82.5 M. It is
measured scaling, not a measured 82.5 M solve, and it is labelled as such.

---

## The resident set, itemised

The dominant term is not the graph. It is Python.

| component | bytes | how derived |
|---|---:|---|
| H3 cell **strings** | 1,033.8 MB | 15,361,631 distinct `str`, measured 67.3 B each |
| `_cell_pos` dict table | 492.1 MB | 2^25 slots × 16 B, formula validated at 1e6 |
| `_cell_pos` int values | 467.6 MB | 13,751,643 `PyLong` × 34.0 B measured |
| `NodeIndex.cells` pointers | 116.2 MB | 13,751,643 × 8.45 B |
| `base_index` int64 | 110.0 MB | 13,751,643 × 8 |
| `_split` frozenset | 67.1 MB | 1,609,988 entries → 2^22 × 16 B |
| `base_cells`, `fine`, stations, airports | 59.4 MB | |
| **NodeIndex subtotal** | **2,346.2 MB** | **67 % of the service** |
| CSR `data` float64 | 659.6 MB | 8 × 82,456,172 |
| CSR `indices` int32 | 329.8 MB | 4 × nnz |
| CSR `indptr` int32 | 55.3 MB | 4 × 13,816,885 |
| **CSR subtotal** | **1,044.7 MB** | |
| interpreter and libraries | ~95 MB | measured |
| **idle resident** | **3,486 MB = 3.40 GiB** | |
| one solve in flight | +580.3 MB | 8 B dist + 4 B pred + ~30 B scipy heap per node, measured flat at N = 1 M / 4 M / 8 M |
| **one request in flight** | **4,066 MB = 3.97 GiB** | +0.57 GiB per additional concurrent solve |

int32 indices are safe with 26× headroom: the limit is `nnz`, not node count.

**The per-object model was cross-checked independently**, because 2.3 GB of
Python objects is the number the whole design rests on and it is derived, not
observed. Building 251,595 real res-6 cells as a list of strings plus a
`str -> int` dict, under `tracemalloc`, gives **126.5 bytes per cell** against
the model's **125.8** for the same two structures — 0.6 % apart. That is a
cheap measurement (35 MB) that can be repeated on a loaded box; the full-scale
figure stays an extrapolation until a solver is actually started, and it is
labelled as one. It extrapolates higher than a naive count because
`graph/refine.py` keeps 15,361,631 distinct cell strings against 13,751,643
list slots: a split base cell's string outlives the slot it came from.

Two consequences that shape the design:

- **Two thirds of the footprint is a Python data structure the solver does not
  need.** `_cell_pos` exists to answer "which node is this cell?", which a
  service needs exactly twice per request. An int64 `numpy` array of h3 cells
  with `searchsorted` answers the same question and saves an estimated 795 MB;
  dropping the string list saves about 1,040 MB. Neither is done here — they
  change `graph/nodes.py`, which the running build is using — but they are the
  first optimisation and they are recorded as PR13-2.
- **The CSR arrays are memory-mappable and it was verified** (`np.shares_memory`
  returns True on a round trip). A service that mmaps them from a `.npz`
  written once by the build pays no Python cost for 1.04 GB of the footprint
  and starts in seconds rather than minutes. That depends on the build
  persisting the graph, which it does not: `grep save_npz` hits only the render
  grid. This is C13-18 / PR13-3 and it is the single highest-value piece of
  work behind the service.

---

## Cold start: 207 s, and what it is spent on

The running build's parent phase is **310 s** measured wall clock, from lock
acquisition at 17:11:28 to the pool fork at 17:16:36, with every source cache
warm. A minutes-and-legs solver does not need all of it:

| skipped | cost | why a solver does not need it |
|---|---:|---|
| `roads.cell_class` (called twice) | 69.8 s | render classification and a gate input |
| `countries.cell_country` + zone | 13.4 s | `check_monotonic_ground`'s inputs |
| `write_hover_cells` | 11.7 s | an emit artefact |
| `grid.universe` + `grid.native_edges` | 5.0 s | the render grid, for band polygons |
| `hover.reading_layout` | 3.0 s | the reading tier's block ordering |
| **total skippable** | **~103 s** | |

Leaving **~207 s**, essentially all of it `nodes.build_index` and
`build.build_graph`. Peak RSS during that start is about **11 GB**, three times
the steady state — which matches `deferred.md` PR-1's observed 11–12 GB per
build worker and is the number that decides whether a restart can happen while
anything else is running. It cannot, today.

**Keeping it warm is therefore not an optimisation, it is the design.** A
cold-start-per-request model is 207 s of CPU and 11 GB of peak RSS to answer a
10 s question: 20× the cost of the answer, and it cannot be made concurrent on
a 32 GB box. Cold start is ruled out.

---

## Process model: one resident process, one solve at a time

**Recommended: a single resident process with a bounded FIFO queue and exactly
one in-flight solve.**

The reason is not simplicity, it is the GIL. Measured: a spin thread runs at
68.7 M ticks/s while the process is idle and **3.15 M ticks/s during a scipy
dijkstra call — 4.6 %**. The GIL is held for the whole call. Therefore:

- **Threads buy nothing.** A thread pool of four would serialise anyway, and
  would hold four × 580 MB of transient arrays while doing it.
- **asyncio buys nothing.** An `async` handler cannot yield during the call.
- **The health check cannot be served by the solving process.** A liveness
  probe during a 10 s solve times out, and a supervisor would restart a healthy
  service mid-answer. The health endpoint must be served by a separate
  lightweight process in front, or the probe's timeout must exceed the solve
  deadline. This is the detail most likely to be got wrong.
- **There is no in-process cancellation.** scipy offers no callback and no
  checkpoint. A deadline is enforceable only by `limit=` (which bounds the
  search space, not the wall clock) or by running the solve in a **separate
  killable process** and sending it SIGKILL. Those are the only two options and
  the design must pick one deliberately.

A prefork pool — the shape `cli.py:405-411` already uses, with `_watch_parent`
as the orphan reaper — is the v2 answer, once the graph is memory-mapped and a
worker costs 1 GB of private pages rather than 3.4 GB. It is not v1.

**A second request arriving during a solve waits.** The queue is bounded at a
small depth and returns `busy` with `Retry-After: 15` when full, rather than
accepting work it cannot start for a minute. The wire format carries that code
and the page has a sentence for it.

---

## What may be imported in a request path, and what may not

| module | in the request path? | why |
|---|---|---|
| `graph/nodes.py`, `graph/build.py` | **at startup only** | build the resident graph; never re-entered |
| `solve/dijkstra.py` | yes | `snap_origin` and `solve_from` are the whole request |
| `graph/{air,rail,ferry,ground,headway}.py` | at startup only | edge assembly |
| `emit/modes.py`, `emit/itinerary.py` | **NO** | each `argsort`s 13.8 M nodes and allocates 663 MB; ~18 s added to a 10 s solve |
| `contour/*`, `emit/tiles.py` | **NO** | band polygons and an external `tippecanoe` subprocess; the completed `rebuild18` log puts a full origin emit at **466 s** |
| `sources/*` | **NO** | multi-hour network crawls |
| `validate.py` | no | publication gates, not request-time checks |

The leg breakdown is therefore **not** a reuse of `emit/modes.py`. The primitive
a request needs is a single backward walk of the `predecessors` array from the
destination node, classifying each edge as it goes. The classification rules
exist today only inside those two modules' loop bodies and must be extracted
before a leg breakdown can be served. That extraction is scheduled, not done,
and until it lands the service answers **a number, not an itinerary** — which
is the honest v1 scope and is stated as a scoping decision, not discovered as a
limitation.

---

## The request and the response — built this cycle

`src/transport_maps/service/wire.py`. Pure, no graph, 39 tests.

```
GET /api/solve?from=<lat>,<lon>&to=<lat>,<lon>
```

`GET`, deliberately. There is no body, so "reject an oversized payload before
parsing" has no surface to defend; `json.loads` never sees attacker bytes,
which matters because Python's parser accepts the literals `NaN`, `Infinity`
and `-Infinity` by default; and a same-origin `GET` is cacheable on the URL by
both nginx and the browser, which makes an identical click free. A solve costs
seconds of a core, so that is worth more than REST tidiness.

Success:

```json
{"v": 1, "status": "ok", "reachable": true, "minutes": 618,
 "snappedKm": 4.2, "snappedLat": 5.98014, "snappedLon": 116.11302}
```

Failure:

```json
{"v": 1, "status": "error", "code": "not_on_land", "message": "..."}
```

Six decisions in that shape, each with a test that goes red without it:

- **`minutes`, integer, named so.** The binary arrays are minutes and the page
  says "door to door" beside every figure. A `seconds` field here would be a
  60× error nobody notices until a number is absurd.
- **Unreachable is `minutes: null`, not 65535.** That sentinel is a uint16
  artefact of the shipped arrays. In JSON it reads as 45 days of travel, which
  the page would format rather than refuse.
- **`snappedKm` is always present, including at 0.0.** A field that appears
  only when it is interesting makes the page's "did it move?" test a presence
  test — and a presence test reads a renamed field as "it did not move",
  printing a time measured 13 km away with no disclosure at all.
- **`v` is checked by the page**, which refuses a version it does not know
  rather than parsing a shape it was not written for.
- **Six enumerated codes**, and `tests/service/test_wire.py` asserts the
  service's table and the page's `SOLVER_CODES` are **equal**. A code only the
  service knows is a silent failure; a code only the page knows is dead code
  that reads as a handled case.
- **A response carries no exception text, no echo of the input and nothing
  about the queue.** The first leaks build-host paths, the second is an echo
  primitive, the third is a timing oracle for the rate limiter. `handle()`
  never raises and defaults to deny.

| code | HTTP | means |
|---|---:|---|
| `bad_request` | 400 | missing or malformed parameter |
| `out_of_range` | 400 | non-finite, or off the Earth |
| `not_on_land` | 422 | `snap_origin`'s `ValueError`, translated |
| `busy` | 503 | queue full; `Retry-After: 15` |
| `timeout` | 504 | the deadline passed |
| `unavailable` | 503 | not ready, or an internal failure |

Validation refuses, before anything expensive: NaN, ±Infinity and the three
strings `float()` accepts; latitude outside ±90 and longitude outside ±180; a
query string over 256 characters, checked before parsing; and a repeated
parameter, which takes the first value and never a list, so `?from=a&from=b`
cannot become a batch. The range check is a denial-of-service control and not
merely correctness: **h3 4.5.0 does not refuse a latitude of 91** — it
normalises it into a real cell somewhere else on Earth and would spend a full
solve there.

---

## How the page degrades — built this cycle, and non-negotiable

`web/app.js`, `solvePoint()`, 20 tests run under node against a stubbed
network. The requirement is CLAUDE.md's deploy rule, not a nicety: this page
has shipped a blank live site twice.

- **The flag is off by default and the address cannot arm it.** A third URL
  parameter would let a pasted link turn on an experimental network dependency
  in someone else's browser, and spend their share of a rate limit doing it. It
  is a stored preference, like the two Settings switches.
  **2026-10-02, superseded by the owner's call to build it:** the stored
  preference is gone. The page arms itself only when `index.json` carries
  `"solver": {"wire": 1}` matching `SOLVER_WIRE_VERSION`, which `write_index`
  writes only beside a solver bundle from the same build. The address still
  cannot arm it, and neither can localStorage.
- **`solvePoint()` cannot reach `fatal()`, and a test reads the source to prove
  it.** `fatal()` sets `body.fatal`, which hides the rail — so a solver outage
  reaching it would delete the city list, the legend and a static map that is
  still entirely correct.
- **It never throws.** An unhandled rejection reaches `boot.js`'s capturing
  listener, which paints "The page could not start" over a globe that is
  drawing perfectly. `boot.js`'s own header records that as shipped and seen
  live.
- **Every failure names the city the times are still measured from.** That
  sentence is the difference between a failure and a dead end.
- Covered paths: the flag off (no request at all), a good answer, no scheduled
  route, all six codes, a code the page does not know, a wire-version
  mismatch, a reachable answer with a non-numeric figure, a captive portal
  answering HTML with HTTP 200, a refused connection, a request that never
  answers, and a caller cancelling.

**The decision the page still has to make, and has not.** Six or seven
consumers of `origin.times` assume a full 90,740-cell array; `paintOrigin`
unconditionally adds a per-slug pmtiles source; `?from=` is slug-only; every
`lookup` caller is synchronous. **The page has no representation for a
departure with no precomputed surface.** The interaction that avoids inventing
one — recommended by the designer lane and adopted here — is that the drag
still snaps instantly to the nearest charted city and says so, and the exact
point is *offered* in that notice as an extra reading. The map keeps belonging
to a charted city; the service adds one number. Flag off, nothing changes;
service down, a correct answer is already on screen.

**Made, 2026-10-02 — built as adopted.** A drop more than 1 km from the city
it snaps to keeps the point as `exactFrom`; the notice says the map is the
city's and that the point's own time is computed on demand. With a destination
pinned, `refreshExact()` asks `/api/solve` once per from/to pair (abandoning
the request for the previous pair) and prints a separate line under the notice
— "From the exact point you chose: 7 h 12 min door to door, computed on
demand", plus "The point was moved N km to the nearest land" past 0.5 km — or
the wire code's sentence and "The times on the map are still measured from
<City>". The headline stays the city's. No request while the map avoids a
mode (the service solves the full network). The list, a permalink, "Depart
from" and a city label all drop the point, in `paintOrigin` before its
same-city guard. `?dep=lat,lon` carries the point, only beside a `from=` that
names the city nearest to it, and never arms anything. The client timeout is
45 s, not 30: `service/server.py` solves one at a time with a listen backlog of
four, so an accepted request can wait behind six 6-7 s solves, and nginx's own
`proxy_read_timeout` is 60 s. `tests/web/test_exact_departure.py`, every guard
mutated red.

---

## What it costs on the owner's host, stated plainly

The host is the same box that serves the site. Right now:

| | |
|---|---:|
| physical memory | 32 GB |
| held by the five build workers | 13.08 GB |
| free | 331 MB |
| swap used | 10.9 GB of a 12 GB file |

**A resident solver cannot start today.** Starting one would peak at ~11 GB
during graph assembly, and an OOM kill of a build worker is turned by
`_consume`'s dead-worker detection into a build abort — 39 hours lost to a
service nobody is using yet.

**After the build, 3.4 GiB alongside nginx is comfortable** on 32 GB. What is
not comfortable is the next build: nothing stops `build-all` starting beside a
resident solver, and `cli.py:175` and `deploy_verify.sh:74` both detect
concurrency by matching the literal string `build-all`, so neither can see a
solver and the solver cannot see them. That is ARCH13-2 and it must be fixed
**before** anything resident is started, not after.

CPU: one core, fully, for 10–11 s per request, with the GIL held. Sizing at one
in-flight solve, the ceiling is about **5 requests per minute** sustained.
That is a personal-project endpoint, and the rate limit should say so rather
than pretending otherwise.

Keep-warm cost: 3.4 GiB of RSS and near-zero CPU between requests. Cold start:
207 s and ~11 GB peak. There is no middle option until the graph is persisted
and memory-mapped.

---

## nginx and the CSP — the owner's call, stated rather than assumed

The deployed CSP's `connect-src` is `'self'` plus Nominatim and the analytics
hosts (`deploy/worldmap-security-headers.conf:23`).

- **Same-origin `/api/solve` needs no CSP change at all.** `connect-src 'self'`
  already covers it. This is the recommendation.
- It does need a `location ^~ /api/` block in `worldmap.atik.kr.conf`, and
  three things right: `^~` so it wins over the regex locations; **no file
  extension in the path**, or the `\.(html|js|css|json|txt|xml|png)$` regex at
  `:58` takes it first; and `include snippets/worldmap-security-headers.conf;`
  inside the block, because nginx's `add_header` does not inherit into a
  location — the file's own comment at `:25-28` says exactly this.
- **A separate subdomain needs a CSP edit, CORS and a certificate.** Recommend
  against. And `Access-Control-Allow-Origin: *` would turn a per-IP rate limit
  into a distributed one, so if a subdomain is ever chosen, CORS stays absent.
- Rate limiting belongs in nginx (`limit_req`, `limit_conn`), in front, not in
  the application: a request rejected by the application has already cost a
  process wake-up, and the application is single-threaded and busy.

**Editing the server is the owner's decision.** Nothing in this repository
changes it, and no work here assumes it has been done.

---

## The alternative this cycle is obliged to put in front of the owner

The critic lane measured two things cycle 10 did not, and both are cheaper than
a service. This is not a recommendation to overrule a decision already made; it
is a measurement that changes what the decision is between.

1. **The model is 98 % reciprocal.** Built from the shipped binaries across all
   553 origins: median |t(A→B) − t(B→A)| is **19 minutes on a 998-minute median
   journey, 2.0 %**, and flat across every trip-length bucket — a correctable
   constant offset, not noise. So the time from an arbitrary point P to a
   charted city X is already on disk, in X's own array, at P's cell. A
   leave-one-out two-hop estimate over 305,256 pairs gives a **p50 over-estimate
   of 4.8 %, with 78.8 % within 10 %**, from 8 arrays totalling 1.45 MB — 28 %
   of one city switch the page already performs.
2. **Every named place on Earth fits in 14,159 res-4 cells.** All 34,135
   gazetteer places land in that many distinct cells. Precomputing them is
   ~43 CPU-hours, about 9 hours at the build's five workers — **less than the
   39-hour build already running** — and 2.57 GB on disk. That makes every named
   place a departure to within 26 km, against today's 49 km median snap.

And a scoping point that stands regardless: the page reads its answers off a
res-4 hover grid (~45 km cells) and a res-6 reading tier (~6.5 km). **An exact
arbitrary departure is finer than anything the page can display.**

The service remains the right answer if the requirement is genuinely "any point,
exactly, including mid-ocean islands and places with no gazetteer entry". If the
requirement is "I want to depart from somewhere that is not one of the 1,464",
option 2 delivers it for a third of the build time already committed, with no
new runtime dependency, no rate limit, no cold start and no outage mode.

---

## Tasks

Built this cycle:

- [x] **C13-F2.1** The wire format, validation and error taxonomy, with no
  graph — `src/transport_maps/service/wire.py`, 39 tests, every branch mutated.
- [x] **C13-F2.2** The page's solver client behind a flag that is off by default
  and that the address cannot arm — `web/app.js`, 20 node-run tests.
  (2026-10-02: the flag is now `index.json`'s `solver.wire`, not a stored
  preference; see "How the page degrades".)
- [x] **C13-F2.3** The fallback contract: never `fatal()`, never throw, always
  name the city the times are still measured from.
- [x] **C13-F2.4** This document, superseding the cycle-10 analysis.

Not built, in the order they must happen:

- [x] **C13-F2.5** Put the two measurements above in front of the owner before
  any resident process is written. Blocked on the owner.
  (2026-10-02: **decided, build it.** The owner chose to run the solver on
  the web host. The rest of this list follows from that choice.)
- [~] **C13-F2.6** Fix ARCH13-2 — the build's concurrency guard and the deploy
  script's both match the literal `build-all` and cannot see a solver. This is
  a prerequisite for anything resident, not a follow-up.
  (2026-10-02: **OBSOLETE.** The premise was a resident solver on the build
  machine, competing with a build for its memory. As built, the solver runs
  on the web host (atik.kr, 5 GB, 3 cores) and the build runs on the owner's
  Mac, so the two never share a machine, and a guard on either one could not
  see the other anyway. The resource limits that matter on the web host are
  the unit's own (`CPUQuota=150%`, `MemoryMax=2500M`). The same disposition
  applies to C13-8 in the findings file.)
- [x] **C13-F2.7** Persist the graph (`save_npz` + an int64 cell array) so a
  start is seconds and 1.04 GB is memory-mapped rather than rebuilt. C13-18,
  PR13-2, PR13-3. The single highest-value piece behind the service.
  (2026-10-02: done as plain `.npy` arrays rather than `save_npz`, because
  `np.load(mmap_mode="r")` maps those and an npz has to be decompressed.
  `service/bundle.py` writes `cells`, `sorted_ids`, `sorted_pos`, `split` and
  the CSR triple, plus `meta.json` with the build identity, under `FORMAT`
  1 (`f6aa6ed`). Every full `build-all` writes it to `data/build/solver/`
  (`74ce63c`). Measured on the web host: 1.1 s to map, 1.2 GB peak.)
- [x] **C13-F2.8** Extract the edge-classification rules from `emit/modes.py`
  and `emit/itinerary.py` into a per-destination backward walk, so a response
  can be an itinerary rather than a number.
  (2026-10-02: **still open.** The service answers a number only, `minutes`
  plus the snapped departure (`GraphSolver.solve`). The page's on-demand
  line says so. With carry-on on, it says the figure assumes a checked bag,
  because there are no legs to apply the saving to.)
  (2026-10-02, later: **DONE.** `GraphSolver.solve` asks dijkstra for
  predecessors, `walk_back` reads the path from the destination, and
  `journey_legs` classifies each edge by node range: dep -> arr is
  `{"kind":"fly","from","to","min"}`, arr -> dep is
  `{"kind":"connect","at","min"}`, everything else is surface,
  `{"kind":"surface","min","railMin"}`, with rail the time on edges touching
  a station. Ordinals are `.air.bin`'s. Minutes are rounded per node, so the
  legs sum to `minutes` exactly. Road and ferry are NOT told apart: that
  needs the landmass data (`severed`, `spans`) the bundle does not carry.
  `meta.json` gains `nAirports` and `nStations`; a FORMAT-1 bundle without
  them still loads and answers the number alone, and `add_counts` (CLI
  `python -m transport_maps.service.bundle add-counts BUNDLE DIST`, which
  checks `buildId` and the offsets) gives it the counts. `legs` is optional
  and additive, so `WIRE_VERSION` stays 1; `wire.ok_body` refuses legs that
  do not sum, do not end on the surface, or carry unknown fields. The page
  checks them the same way (`solverLegs`), drops a bad breakdown without
  losing the figure, and prints them under the on-demand line in the
  itinerary's own words and glosses ("To ICN, and through the airport",
  "Fly ICN → EWR", "Connect at EWR", "Onward from EWR", the rail share on
  a line beneath). Measured: walk + legs 0.04-0.05 ms on the real bundle;
  predecessors cost within the noise of a 4-6 s solve on a loaded machine
  (+2 % on the warm pair). The carry-on saving is still not applied to the
  on-demand figure, and the line still says it assumes a checked bag.
  Mutation-checked: 22 service and 20 page mutations, each RED.)
- [x] **C13-F2.9** The resident process itself: FIFO depth 1, a separate
  killable solve process for the deadline, a health endpoint NOT served by the
  solving process, and `limit=` as the first-line bound.
  (2026-10-02: built as `service/server.py` (`f6aa6ed`), simpler than
  specified, and the differences are deliberate and recorded here. It is one
  single-threaded process that answers one solve at a time, with a listen
  backlog of 4 (`_Server.request_queue_size`); scipy holds the GIL for the
  whole solve, so threads would only queue. nginx rate-limits each address
  to 6 a minute with a burst of 3 and answers `busy` itself, so the depth
  bound sits in front of the process rather than inside it. It has **no
  killable solve subprocess and no in-process deadline.** nginx's
  `proxy_read_timeout 60s` is the only one, and a solve that overruns
  finishes unseen; at a measured 6-7 s that is a margin of about nine. It has
  **no separate health endpoint**: `scripts/deploy_solver.sh` probes a real
  Seoul -> Gumi solve through nginx, and the runbook does the same. It passes
  **no `limit=`** to dijkstra; the destination is not known to scipy as a
  bound. Each of these is the next thing to add if a solve is ever measured
  near 60 s. The wire version, the error taxonomy and the never-throw handler
  are F2.1's, unchanged.)
- [x] **C13-F2.10** The nginx `location ^~ /api/` block, with the header
  include and no file extension in the path. **Owner's call.**
  (2026-10-02: done as the narrower exact match `location = /api/solve` in
  `deploy/worldmap.atik.kr.conf` (`dfd1ef7`). It includes the header snippet,
  has `access_log off` because the query is the visitor's two points,
  rate-limits through `limit_req zone=worldmap_solver` (6 a minute, burst 3),
  and maps 429 and 502/503/504 to `busy` and `unavailable` bodies in the wire
  format. Installed by `scripts/deploy_solver.sh` only after `nginx -t`.)
- [x] **C13-F2.11** The operator runbook, to `deploy/README.md`'s shape: start
  and stop, working directory, ordering against `dist/.build.lock`, measured
  RSS and cores, the down-contract, the log path and level — logging only
  service-produced values (cell id, outcome class, duration), never a raw body,
  header or `str(exc)`, and never a coordinate finer than the ~110 m the page's
  Privacy section promises.
  (2026-10-02: `deploy/README.md`, "The on-demand solver". It covers the
  host, the unit and its limits, the directory layout with only `current/`
  kept, the measured 1.1 s map, 6-7 s solve and 1.2 GB peak, the nginx block,
  the ship order (`deploy_solver.sh` before `deploy_verify.sh`, enforced by
  `solver_gate`), restart, stop, status, logs and rollback, including why a
  bundle rollback alone breaks the same-build rule. The "ordering against
  `dist/.build.lock`" part does not apply, because the build and the solver
  are on different machines (F2.6). The logging is stricter than asked: the
  unit logs the HTTP status and the duration, no cell id and no coordinate
  at any precision, and nginx keeps no access log for the path.)
- [x] **C13-F2.12** The page becomes a **third** runtime service. `index.html:1036`
  and `llms.txt:113` say "two external services" and
  `tests/web/test_attribution_and_privacy.py` pins it. They change in the same
  commit that ships the fetch, not later.
  **Done 2026-10-02**, in the commit that wires the fetch into the page. The
  solver is this site's own server, so "two external services" stays true;
  what changed is "everything else is computed in the browser". The Privacy
  section now says the exact point and the destination are sent to this
  site's own server, to about a metre, once a destination is chosen, and that
  the address bar carries the point as `dep=`; `llms.txt` and the "How it is
  computed" paragraph say the same.
- [x] **C13-F2.13** The page wiring (2026-10-02): arming from `index.json`,
  `exactFrom` kept from a drag, the on-demand line, `?dep=` in the address.
  See "How the page degrades".
- [x] **C13-F2.14** The map from any point (2026-10-04, owner-approved):
  `/api/map`, the kept trees, the nginx route, and the page's loading,
  drawing, reading and fallback. See "The map from any point". Mutation-
  checked: 30 service and 35 page mutations, each RED. Open: ship
  `hover_cells.bin` beside the bundle in `scripts/deploy_solver.sh`, and the
  `deploy/README.md` runbook's mention of the new route.

## The map from any point (2026-10-04)

The owner approved it on 2026-10-04 and asked only that the loading UI be
clear. Until now a dragged departure snapped to the nearest of 1,464 charted
cities, whose map is precomputed tiles, and the exact point got one number, to
a chosen destination. Now the point gets the MAP. Nothing in the model, the
graph or the build changes, so the freeze on model and input changes until
rebuild 27 lands is not touched: this is the service and the page only.

**The service.** `GET /api/map?from=lat,lon` snaps the point, solves once,
and answers the minutes per `hover_cells.bin` cell in that file's order --
`{slug}.bin`'s layout exactly -- as base64 inside the usual JSON envelope
(`docs/contract.md`, "The map from a point"). Decisions:

- **JSON plus base64, not a binary body.** One parse path for a map, a
  journey and every failure; a captive portal's HTML 200 fails `JSON.parse`
  as `unavailable`. Measured: 242,149 bytes, 148,706 gzipped (gzip -6),
  against 130,277 for the raw uint16 array gzipped -- 14 % more on the wire
  for a page that cannot misread a body.
- **`WIRE_VERSION` stays 1; `mapVersion` 1 versions the array.** The map is
  additive and `index.json`'s `solver.wire` (written by the build, frozen)
  arms both endpoints; bumping the wire would disarm every page against the
  shipped `index.json`. `count`, `hoverRes` and `buildId` ride along to be
  checked, and the page refuses any that are not its own.
- **The representative rule is `emit/hover.py`'s, restated** in
  `service/hovermap.py` because the seam test bans `emit` from the package:
  the parents come from `cells.npy` by h3 bit arithmetic (no per-cell Python),
  the centres by the same arithmetic and a `searchsorted` on the bundle's
  sorted ids, and the fallback groups are built once, at start. Held to
  `emit.hover.write_hover` byte for byte, and to `representative_array`
  child for child (the tie rule is invisible in the minutes), on a fixture
  with every branch. Measured on the shipped `52660de5` bundle: the index
  builds in 1.7 s and 2.7 MB (7,238 parents with no land centre, 277,420
  fallback cells), reproduces `dist/hover_cells.bin` exactly, and the maps
  from Seoul and from Suva equal `seoul.bin` and `suva.bin` at 0 differing
  cells of 90,740.
- **The order is checked at start.** `--hover-cells PATH`, or a
  `hover_cells.bin` beside the bundle, makes the service refuse to start on
  any difference. `scripts/deploy_solver.sh` does not ship that file yet
  (out of this change's scope); until it does, the `buildId` the page checks
  and `solver_gate`'s same-build rule are what tie the two.
- **The last two shortest-path trees are kept**, keyed by snapped node, with
  their predecessors, so the journey the page asks for next from the same
  point is a lookup and a walk back. 12 bytes a node, 166 MB a tree on the
  shipped graph; two beside the measured 1.2 GB peak stay inside 80 % of the
  unit's 2,500 MB `MemoryMax`, and a test holds `TREES` to that. Room is
  made before a solve, never after, so the peak is the kept trees plus one
  solve in flight. Measured locally (a loaded Mac, five build workers
  running): solve + map 9.3-9.4 s, map from a kept tree 4-5 ms (encode and
  JSON 3.1 ms), `/api/solve` from a kept tree 0.0 s in the server log.
- nginx: `location = /api/map`, the same `worldmap_solver` zone, the same
  wire-format `busy` and `unavailable`, `access_log off`.

**The page.** Armed by `meta.solver` only. A drop more than 1 km from the
city it snaps to (or a `dep=` link) asks for the point's map at once:

- *While it is computed* the reading panel (`#pointmap`) and a notice over
  the globe (`#pointbusy`, the only place it shows when the phone sheet is
  folded) both say "Computing travel times from the point you chose…" and
  "This takes a few seconds. Seoul's map stays on screen until it is ready.",
  the overlay counts the seconds over an indeterminate bar (none under
  reduced motion), and both carry Cancel, which goes back to the city. The
  city's tiles stay on screen. The dropped point is drawn as an accent ring.
- *When it lands* it is drawn client-side: one outline per hover cell from
  h3 (`cellToBoundary`, built in idle slices while the request is out, kept
  flat in a Float64Array), one MultiPolygon per band with the tiles' `band`
  values, `bandColorExpression()` and sort key, `fill-antialias: false`, in a
  GeoJSON source with `tolerance: 0`, beneath `water`. A cell across the
  antimeridian is split in two as `contour/bands.py` splits it. The tile
  layer is hidden, not removed. Every reading, the departure card, the city
  list and the legend's zoom detail then read the point's array; the
  city's itinerary is withdrawn (its arrays are the city's), and the journey
  from the point is the on-demand line with its legs, answered from the
  kept tree. The panel says "This map is measured from the point you chose,
  door to door, computed on demand on a grid of cells about 45 km across
  (22 km a side), coarser than a charted city's map." with "Back to Seoul's
  map".
- *On any failure* -- each wire code, a captive portal, another build's
  array -- the city's map stays, with "The map from the point you chose could
  not be computed. <the code's sentence> The times on the map are still
  measured from Seoul, the nearest charted departure city." and Try again.
  Never `fatal()`. With a mode avoided nothing is asked for: "No map is
  computed from the point you chose while the map avoids flights: the
  service that computes it uses every mode. The map is Seoul's, the nearest
  charted departure city."
- Carry-on is not applied to the point's map readings (the array does not
  say which cells flew) and the panel says its times assume a checked bag.

**Measured in a real browser** (headless Chromium, 1280x800, against the real
bundle served read-only through a local stand-in for nginx): building the
GeoJSON 12-130 ms (the high end when the answer beat the idle-slice outline
build), source loaded and shown 1.2-2.9 s after the answer on the loaded
Mac. Main-thread heap after a forced GC: about 80 MB with the city's map,
134 MB with the point's map shown (MapLibre keeps the GeoJSON it was given),
91 MB after going back (the 15 MB outline cache is kept for the next map).
The worker's tiling memory cannot be read from the page and is not
measured. Dissolving each band with `h3.cellsToMultiPolygon` was tried to
cut the vertex count and did not finish in 120 s in node, so the cells are
drawn whole.

**Browser evidence.** Loading, drawn, failure (busy and a captive portal),
Cancel during the wait (the late answer changes nothing and `dep=` leaves the
address), "Back to Seoul's map", a real drag of the marker, a pinned
destination (journey answered from the kept tree) and the avoid path, at
1280x800; loading and drawn at 820x1180, 390x844 and 844x390. No page
errors, no console errors. At 1280x800 the three notices together grew the
reading into the departure card; `fitReading` now stands the card down there
as it does for a long itinerary.

**Deploy, in order:** first make sure the bundle that will be shipped names
its node layout -- `data/build/solver/meta.json` on the owner's Mac still
lacked `nAirports` and `nStations` on 2026-10-04, and `deploy_solver.sh`
rsyncs it over the host's copy with `--delete`, so run `python -m
transport_maps.service.bundle add-counts data/build/solver dist` first or the
legs go. Then `scripts/deploy_solver.sh` (ships `service/` and the nginx
site, `nginx -t` first, restarts the unit; the probe is the same Seoul ->
Gumi solve; start-up is ~1.7 s longer for the hover index), then check `/api/map` through
nginx (`curl -s 'https://worldmap.atik.kr/api/map?from=37.8,127.25' | head
-c 200` answers `"status":"ok"` with `"mapVersion":1`), then
`scripts/deploy_verify.sh` for the page, then open it: drop the marker away
from a city at the four viewports and watch the loading state, the drawn
map and the console. Optionally copy `dist/hover_cells.bin` into the
bundle directory on the host so the service checks the order at start.

## The owner's decisions, 2026-09-15 — recorded in full elsewhere

Two owner requests landed mid-cycle and both are solver features. **The record
is `2026-09-15-c14-owner-requests.md`** (R1 carry-on-only, R2 preferred and
excluded modes), including the four costed options the owner chose between and
the traps each request carries. It is not repeated here; only what it changes
about the design ABOVE is.

**Preferred-mode weighting cannot be precomputed, and that is the point.**
Excluding a mode is one more static build — `build_graph` already accepts
`rail_routes=None` and `ferry_links=None`. A weighting is a continuum and every
point on it is a different solve, which makes it this service's strongest
justification rather than an argument against it.

Two consequences for the sections above:

- **`## The request and the response` needs per-mode weights.** It was designed
  around an origin. It now needs a bounded map of mode → multiplier, and
  `service/wire.py` needs matching validation: a fixed key set (the six
  `MODE_NAMES` the page ships, never caller-supplied), a closed finite bound on
  each multiplier, rejection rather than clamping outside it, and a canonical
  form so two requests meaning the same weighting do not solve twice. **Cycle 14
  deliberately did not touch `wire.py`**: it is the one module in the tree with
  zero package imports, and that property is worth changing on purpose.

- **Everything derived from the path must come from the WEIGHTED solve** — the
  itinerary chain, the mode breakdown, and the rail line naming. The default
  answer will still be in memory and will be the easy thing to reach for. AA17,
  closed in cycle 14, was exactly this shape: a figure and a caption produced by
  different journeys, shipped for months because nothing checked they agreed.

## Status

Cycle 13: the design is complete and the graph-free half is built and tested.
Nothing resident was started, no graph was loaded, and the static build is
unchanged. C13-F2.5 is blocked on the owner; C13-F2.6 blocks everything after
it.

Cycle 14: no code. Two owner decisions recorded above — preferred-mode
weighting (which makes filtering a solver feature rather than a static one) and
a carry-on-only option. Neither was implemented and `service/wire.py` was not
touched, as instructed.

2026-10-02: the owner decided to build the on-demand solver. The page half is
wired (C13-F2.12, C13-F2.13): armed only by `index.json`, one extra line, the
map unchanged. With carry-on on, the line says the figure assumes a checked
bag, since the service returns no legs to apply it to.

2026-10-02, later: the service half is built and running on the web host.
That covers F2.5 (decided), F2.7 (the bundle), F2.9 (the process), F2.10
(nginx) and F2.11 (the runbook, `deploy/README.md`). F2.6 is obsolete,
because the build and the solver never share a machine. **F2.8 is the one
open task**: a response is a number, not an itinerary.

2026-10-02, later still: F2.8 is done. A response carries its legs when the
bundle's `meta.json` names its node layout, and the page prints them under
the on-demand line. The bundle the `52660de5` rebuild wrote predates the
counts, so the deploy must run `add-counts` on it first
(`deploy/README.md`, "Legs need the node counts").

2026-10-04: F2.14, the map from any point, is built in the service and the
page, and verified in a browser against the real bundle; not deployed.
Nothing in the model or the build changed.
