# Code review — transport-maps (code-reviewer lane)

Reviewed at commit `ac191db` (branch `feat/transport-pipeline`), working tree clean.
Angle: code quality, logic bugs, invariants, error handling, data flow, state
consistency, and the places where code quality limits user-visible detail or
accuracy. Read-only: no repo file other than this review was written. Evidence
runs: `uv run ruff check .`, `pytest tests/graph/test_nodes.py -x`, a
`pytest` pass over every test module that does not call `nodes.build_index()`,
and a handful of stdlib/parquet introspections (all cited inline).

## Summary

| Severity | Count | IDs |
| --- | --- | --- |
| Critical | 1 | CR-1 |
| High | 6 | CR-2, CR-3, CR-4, CR-5, CR-6, CR-7 |
| Medium | 15 | CR-8 … CR-22 |
| Low | 10 | CR-23 … CR-32 |

The two headline facts:

1. **The pipeline as committed cannot run.** `graph/nodes.py` uses `np` without
   importing numpy; `build_index()` and every bare `NodeIndex(...)` raise
   `NameError`. Every entry point (`build-all`, `solve`, `index`) and every
   integration test module fail at fixture setup. `ruff` has flagged it (F821)
   since commit `1a4d66b`, but nothing gates on ruff (46 outstanding errors).
2. **The expected-wait model — the thing the page describes as "onward
   connections are [waited for]" — is bypassed by the graph itself** at every
   small airport and most medium ones: `arr → cell → dep` (disembark +
   processing) is cheaper than the connection edge, so Dijkstra never pays the
   headway. The far bands are systematically optimistic exactly where waiting
   dominates, and the route panel then shows only the last flight.

---

## Findings (ordered by severity)

### CR-1 — `graph/nodes.py` uses `np` without importing numpy: nothing builds
**Severity:** Critical · **Confidence:** High · **Status:** Confirmed (test run)

`src/transport_maps/graph/nodes.py:21-27` imports `logging`, `dataclasses`,
`h3`, `config`, `airports`, `landmask` — and nothing else. Yet:

```python
# nodes.py:61-62
base_index: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
fine: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
# nodes.py:124
split_set = {base_cells[i] for i in np.flatnonzero(split)}
```

Python 3.14's deferred annotations hide the `np.ndarray` annotation, so the
module *imports* cleanly — and fails the moment `build_index()` reaches line 124
or any caller constructs `NodeIndex(...)` without passing `base_index`/`fine`
(the default factories run). Verified:

```
$ uv run pytest tests/graph/test_nodes.py -x
E   NameError: name 'np' is not defined      src/transport_maps/graph/nodes.py:124
$ uv run pytest tests/graph/test_ferry.py tests/graph/test_rail_integration.py …
E   NameError: name 'np' is not defined      src/transport_maps/graph/nodes.py:61   (12 tests)
$ uv run ruff check . --output-format concise | grep F821
src/transport_maps/graph/nodes.py:61:17: F821 Undefined name `np`   (+5 more)
```

`git log -S"import numpy" -- src/transport_maps/graph/nodes.py` is empty: the
import never existed; the `np` uses arrived in `1a4d66b` (res-6 grid). So
`transport-maps build-all`, `solve`, `index`, `scripts/ground_check.py`,
`scripts/calibrate_ground.py`, and the modules `tests/graph/test_nodes.py`,
`test_build.py`, `test_ground.py`, `test_ferry.py`, `test_rail_integration.py`,
`tests/sources/test_roads.py`, `test_countries.py`, `test_urban.py`,
`tests/test_golden.py`, `tests/contour/test_bands.py::seoul_*` all fail today.

**Failure scenario:** `uv run transport-maps build-all` → `NameError` before
any origin is solved. A fresh clone cannot reproduce the deployed site.

**Fix:** add `import numpy as np` to `nodes.py`; make `uv run ruff check .`
a pre-commit/CI gate (it is currently at 46 errors, so the one that mattered
was invisible in the noise — see CR-23).

---

### CR-2 — Expected wait is bypassed by `arr → cell → dep` at most airports
**Severity:** High · **Confidence:** High · **Status:** Confirmed (arithmetic on shipped calibration)

`graph/build.py:163-213` (`_transfer_edges`) puts the *only* charge for waiting
on the `arr(X) → dep(X)` connection edge, cost `max(MCT, median expected
wait)`. But `_access_edges` (`build.py:136-160`) also emits `arr(X) → cell(X)`
(disembark) and `cell(X) → dep(X)` (processing) for the same airport, so the
graph contains a parallel path `arr → cell → dep` costing
`disembark + processing`:

| size | bypass (disembark+processing, `calibration.toml:74-83`) | connection edge floor (MCT, `:94-98`) |
| --- | --- | --- |
| large | 30 + 70 = **100** | 75 |
| medium | 22 + 55 = **77** | 50 |
| small | 15 + 40 = **55** | 35 |

Dijkstra takes the bypass whenever `max(MCT, wait) > bypass`, i.e. whenever
`wait > 100/77/55 min`. With `air.expected_wait_min` = 5040 / flights_per_week
(`graph/air.py:55-60`) and the shipped gravity model (`calibration.toml:53-59`,
`air.py:82-96`), the wait exceeds the bypass for any median outbound route
longer than roughly:

- large–large ≈ 2,800 km, large–medium ≈ 1,600 km
- medium–medium ≈ 900 km
- small–large ≈ 450 km, small–medium ≈ 450 km, small–small: **always** (the
  400 km knee alone gives 25.7/wk → 196 min wait vs a 55 min bypass)

So at every small airport and at any medium/large airport whose routes are
mostly long, the modelled connection is disembark + check-in and **zero
waiting**. This is the opposite of the semantics the page states
(`web/index.html:406-407`: "the first service is not waited for, but onward
connections are") and of the spec's D7 rationale ("Frequency-aware waiting is
the honest number"). The effect is concentrated in the far bands — island
hops, regional fields — where headway is the dominant term, so the map is
systematically optimistic there. Corollary: `_transfer_edges`' docstring claim
that "this edge is the only place a connection is charged" is true, but it is
not the only place a connection *happens*.

**Failure scenario:** Seoul → small Pacific island via two small-airport
connections: real expected wait 3–6 h per connection; modelled 55 min each.

**Fix options (pick one, document it in `calibration.toml`):**
1. Charge the expected wait on every *flight edge* of the departing airport
   (simplest, one-layer graph, consistent with "expected" semantics; the
   first flight then also pays its wait — a documented modelling choice).
2. Keep "leave now" semantics with a two-layer graph (pre-flight / post-flight
   copies of airport nodes and cells) — expensive at 10 M cells.
3. At minimum, make the bypass at least as costly as the connection by
   moving `max(0, conn − disembark − processing)` onto the `cell → dep`
   access edge for connections… which is not expressible without knowing the
   traveller's history, which is why (1) is the honest choice.

Add a test that builds a 1-cell/1-airport graph and asserts
`dist(arr) → dist(dep)` equals the connection edge, not the bypass; it goes
red today.

---

### CR-3 — `raise SystemExit` inside a forked pool worker hangs the build forever
**Severity:** High · **Confidence:** High · **Status:** Confirmed (stdlib source)

`src/transport_maps/cli.py:83-88`:

```python
coverage = validate.check_coverage(minutes, idx)
if coverage < validate.MIN_COVERAGE:
    raise SystemExit(f"{slug}: coverage {coverage:.1%} below {validate.MIN_COVERAGE:.0%}")
```

is executed inside `_solve_one_forked` (`cli.py:109-112`) under
`ctx.Pool(workers)` / `pool.imap` (`cli.py:187-191`) whenever there are ≥ 4
origins. `multiprocessing.pool.worker` only catches `Exception`:

```
$ uv run python -c "import inspect, multiprocessing.pool as m; print([l.strip() for l in inspect.getsource(m.worker).splitlines() if 'except' in l])"
['except (EOFError, OSError):', 'except Exception as e:', …]
```

`SystemExit` is a `BaseException`, so it escapes the worker loop, the child
process exits, the pool's maintenance thread replaces it, and the task's
result is never delivered — `pool.imap` blocks indefinitely. The docstring's
promise ("Aborts on the first failing gate") holds only in the `workers <= 1`
path, which is also the only path the tests exercise
(`tests/test_cli.py` uses two origins → `_worker_count` returns 1).

**Failure scenario:** a 553-origin build where one origin lands on a cell with
< 90% coverage: seven workers idle at 0% CPU for hours, no error, no exit.

**Fix:** raise `RuntimeError` (or a project `GateError`) from gates; reserve
`SystemExit` for `main()`. Add a test that runs `_build_all` with ≥ 4 stub
origins and a failing coverage and asserts it raises within a timeout.

---

### CR-4 — Fresh-cache build crashes: `urban._places()` calls `emit.places._download()` with no arguments (and the wrong dataset)
**Severity:** High · **Confidence:** High · **Status:** Confirmed (signatures)

`src/transport_maps/sources/urban.py:34-40`:

```python
path = (config.CACHE / PLACES_ZIP).resolve()          # ne_10m_populated_places_simple.zip
if not path.exists():
    from ..emit import places as places_mod
    places_mod._download()
```

but `src/transport_maps/emit/places.py:35` is `def _download(url: str)` — no
default — and it downloads GeoNames, not Natural Earth populated places. On
any machine without `data/cache/ne_10m_populated_places_simple.zip` (a fresh
clone, a cleared cache) `build_index()` → `urban_mask()` → `TypeError:
_download() missing 1 required positional argument`. Nothing in the repo
downloads that zip any more (the emitter that once did now fetches GeoNames),
so the file only exists on machines that ran an older revision.

**Fix:** give `urban.py` its own `_download()` for the Natural Earth URL (or
switch the urban mask to the GeoNames gazetteer it already ships and drop the
NE dependency). Add a test with `config.CACHE` pointed at an empty `tmp_path`
and `httpx.get` stubbed.

---

### CR-5 — nginx `add_header` inheritance silently drops the CSP/HSTS/X-Frame headers on every response that matters; the CSP as written would break the page
**Severity:** High · **Confidence:** High · **Status:** Confirmed (nginx semantics)

`deploy/worldmap.atik.kr.conf:26-32` sets CSP, HSTS, `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` at `server` level.
nginx's `add_header` is inherited *only if the current level defines none* —
and `:42-71` define `add_header Cache-Control …` in the locations for `/`,
`\.(html|js|json)$`, `\.bin$`, `\.pmtiles$`, `\.woff2$`. Every one of those
responses — including `index.html` — therefore ships with **no** security
headers. The `# the CSP stays tight` comment is wrong for the only response
where a CSP acts.

The second half explains why nobody noticed: the CSP as written
(`connect-src 'self'`, `script-src 'self' blob:`) would block the page's own
external calls — Nominatim (`web/app.js:776-792`, `:826-841`) and Google
Analytics (`web/index.html:5-11`) — and `scripts/browser_verify.sh:43-46`
asserts that address search *works*. So the CSP has never been in effect, and
the conf header comment "no runtime API calls" and `web/README.md:8-10` ("no
third-party dependency … strict `script-src 'self'` CSP") describe a page
that no longer exists.

**Fix:** repeat the security `add_header`s inside each location (or use
`include security-headers.conf;` per location), then extend the CSP
deliberately: `connect-src 'self' https://nominatim.openstreetmap.org`, and
either add the GA origins or drop the tag. Update the README and conf
comments to match. Add a `curl -sI` check of the CSP header on `/index.html`
to `deploy_verify.sh`.

---

### CR-6 — The test suite has not been green since the res-6/7 migration; several tests are stale or vacuous
**Severity:** High · **Confidence:** High · **Status:** Confirmed (test run + code)

Beyond CR-1, once `np` is imported these fail or prove nothing:

- `tests/sources/test_landmask.py:14-16` asserts `500_000 < len(cells) <
  620_000` for `land_cells(config.SOLVE_RES)`. The res-6 cache the build
  actually uses has **4,091,715** rows (`data/build/land_cells_r6_dd95e3b5.parquet`,
  read with polars). The bound is the res-5 count.
- `tests/test_golden.py:28-29` looks up
  `h3.latlng_to_cell(*latlon, config.SOLVE_RES)` in `idx.cell_index`. Seoul,
  Tokyo and London are urban, so their res-6 cell is *split* and removed from
  `idx.cells` (`graph/refine.py:43-53`) → `KeyError`. Must use `idx.cell_at`.
- `tests/graph/test_build.py:61-65` and `tests/graph/test_ground.py:24-29`
  look up res-**5** cells in a res-6/7 index → `KeyError`. 32 res-5 literals
  remain across 10 test files.
- `tests/contour/test_bands.py:260`:
  `assert by_band[5].contains(...) and not by_band[0].contains(...) or True`
  — always true. The "parent under children" invariant is not tested.
- `tests/emit/test_hover.py:23-27` ("parent takes the minimum of its
  children") passes only because its res-5 fixture cells never match the
  res-6/7 centre child, so `_representative_children` falls through to the
  fastest-child fallback (`emit/hover.py:48-54`). The centre-child rule the
  module documents is untested; the test's name asserts the *old* rule.
- `tests/emit/test_index.py:76-83` **fails now**: `README.md:48-56` has no row
  for HydroLAKES (and no proper row for GeoNames) although `index.ATTRIBUTION`
  ships both (`emit/index.py:59-70`). That is a CC BY 4.0 attribution
  obligation, not just a test (see CR-15).
- `tests/graph/test_transfers.py:90-92` pins `STATION_ACCESS_MIN` /
  `STATION_EGRESS_MIN`, which are defined twice (`transfers.py:8-9` and
  `:53-54`) and used nowhere — a test guarding dead code.
- `tests/sources/test_countries.py:72-83` wraps its only assertion in `if
  len(set(codes)) == 2 and …:` — vacuous when the fixture cells land in one
  country.
- `tests/test_cli.py:27-104` stubs `_build_all` with two origins, so the
  `Pool` path (CR-3) is never executed.

Observed: `13 failed, 149 passed` over the non-`build_index` modules; every
`build_index` module errors at setup. CLAUDE.md's testing rule ("assume a new
test is vacuous until shown otherwise") is not being applied.

**Fix:** after CR-1, run the whole suite and fix each stale assumption
(`idx.cell_at`, `config.SOLVE_RES` fixtures, res-6 count bound); delete the
`or True`; rewrite `test_hover` with res-6 fixtures that hit the centre-child
branch and mutate the code to confirm it goes red; add the missing README rows.

---

### CR-7 — The route panel loses every flight before a surface transfer and mislabels the remainder
**Severity:** High · **Confidence:** High · **Status:** Confirmed (code); frequency depends on CR-2

`emit/routes_json.py:31-39` emits only airport nodes; `web/app.js:473-489`
(`legsTo`) walks `prev` and stops at the first id that is not in
`routes.byId` — i.e. at the first *cell*. `renderLegs` (`app.js:537`) then
labels `chain[0].min` as “To **X**, and through the airport”.

That is correct only when the cell before the first departure is the origin's
own access leg. Whenever the journey re-enters an airport from a cell after
an earlier flight — the CR-2 bypass at the same airport, or a genuine
airport-to-airport surface transfer (NRT→HND, LHR→LGW, hub → regional field
by road) — the chain is truncated to the *last* flight and its “To X, and
through the airport” row silently contains every earlier flight. Because CR-2
makes the same-airport bypass the *normal* connection at small/medium
airports, this is the common case in the far bands, not an edge case: a
Seoul → outer-island reading shows “To ⟨island hub⟩, and through the airport:
14 h · Fly hub → island: 1 h”.

**Fix:** either ship the chain’s cell/station links too (only nodes on some
airport's `prev` chain are needed — a few thousand), or emit, per arrival
node, the *previous* arrival node (`itinerary.arrival_airport_per_node`
already computes `last`; storing `last[prev]` for each `dep` node closes the
gap cheaply), and render “Surface transfer X → Y” rows. Until then, label the
first row “Journey to X” rather than asserting it was the access leg.

---

### CR-8 — “Onward from X, of which:” lists the *whole journey's* surface minutes
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

`emit/modes.py:64-86` accumulates surface minutes down the entire
shortest-path tree from the origin — the drive to the first airport included.
`web/app.js:545-553` presents that total under “Onward from **X**, of
which:” after the last flight. A 40 min drive to ICN plus a 60 min drive from
NRT shows as “Onward from NRT, of which: 1 h 40 by highway”, and the listed
parts can exceed the “Onward” duration printed beside them.

**Fix:** either emit the surface breakdown *since the last arrival airport*
(reset `acc[node]` to zero on `arr` nodes in `mode_minutes_per_node`, or ship
two channels sets), or move the parts under “Door to door, of which:” and say
so. Add a test with `cell → dep → arr → cell` where both cell hops are road
and assert the onward figure excludes the access hop.

---

### CR-9 — Hover value, highlighted hexagon and painted band come from three different cells
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

- The number comes from the res-4 parent's *centre* res-6/7 child
  (`emit/hover.py:30-55`), which can sit ~10–15 km from the pointer.
- The white outline is the res-**6** hexagon under the pointer
  (`web/app.js:334-342`, `h3.latLngToCell(lat, lon, SOLVE_RES)`), which in
  refined areas is seven times the solved cell — the exact thing the comment
  at `app.js:30-34` says the highlight must not do (that comment, and
  `app.js:573-577`, `emit/hover.py:7-11`, `emit/itinerary.py:52-55`,
  `emit/modes.py:95`, still describe the retired “min of seven children”
  rule and res 5).
- The colour is the res-6/7 polygon under the pointer; `bandRangeAt`
  (`app.js:578-595`) reads it back, so the panel can say “3 h 10 · 4–4.3 h”.

For a page whose stated goal this cycle is detail and accuracy, the readout
contradicting its own highlight is the most visible quality gap. The modes,
airport and rail arrays inherit the same representative-child choice, so the
itinerary shown belongs to the centre child too.

**Fix:** (a) highlight the *representative* cell (ship its id, or recompute
`cell_to_center_child(parent, SOLVE_RES/FINE_RES)` client-side — the split set
is derivable from `hover_cells` + a small bitmap), and (b) either ship the
hover array at res 5 (~600 k × 2 B ≈ 1.2 MB, gzips to ~400 KB) or make the
band range the primary figure with the centre-child time as “≈”. Fix the
stale comments either way.

---

### CR-10 — Legend ticks are labelled with rounded hours that are not the edge they sit on
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed (arithmetic)

`web/app.js:132-143` places a tick at the nearest edge within 8% of each round
hour. With `config.BAND_EDGES_MIN` (`config.py:24`): “4” sits at 225 min
(3 h 45), “8” at 465 min (7 h 45), “24” at 1470 min (24 h 30), “48” at
3020 min (50 h 20). CLAUDE.md: “its ticks sit at their true band boundaries …
evenly spaced labels would misstate the scale” — a tick on a true boundary
with the wrong number misstates it just the same (the “48” is 2 h 20 off).

**Fix:** label ticks with the edge's own value (“3¾”, “7¾”, “50”), or add
edges at exactly 240/480/1440/2880 to the ladder, or tighten the tolerance to
~2% and accept fewer labels. Pin it with a test that recomputes the labels
from `BAND_EDGES_MIN` and asserts `|label − edge| < 1%`.

---

### CR-11 — Origin switch race: four of five per-origin fetches never check `active === o`
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

`web/app.js:394-431`: only the rail pair guards with `active === o`. The
`.bin`, `.modes.bin`, `.air.bin` and `.json` handlers assign unconditionally,
so clicking Seoul then Tokyo while Seoul's `.bin` is still in flight leaves
`hoverTimes` from Seoul under Tokyo's tiles, with no error. On a slow
connection the four arrays can even end up from different origins.

**Fix:** capture `const mine = o` and early-return in every `.then` when
`active !== mine`; better, `AbortController` per `paintOrigin`.

---

### CR-12 — Ferry edges can duplicate fine↔base ground edges and abort `build_graph`
**Severity:** Medium · **Confidence:** Medium · **Status:** Needs manual validation

`graph/build.py:296-307` skips a crossing only when
`idx.cells[v] in h3.grid_disk(idx.cells[u], 1)` — a same-resolution test. On
the mixed grid `graph/ground.py:115-130` also joins a fine cell to the
*unsplit base cell* beyond its ring. A ferry whose terminals land in a
boundary fine cell and the adjacent base cell is not caught, is emitted, and
`build_graph:381-386` raises “duplicate (row, col) pairs”, killing the build.
`emit/modes.py:30-38` already has the correct parent-aware adjacency test;
`_ferry_edges` should use it (and the comment at `build.py:301-302` still
says “At resolution 5 … ~8 km”).

---

### CR-13 — Ground speed table is non-monotonic in road grade, lives in code, and is described misleadingly on the page
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

`graph/ground.py:25`: `[5.0, 104.0, 57.0, 50.0, 18.0, 25.0]` — tertiary (class
4, fitted) is *slower* than local (class 5, published default).
`roads.cell_class` takes the best grade present, so a cell containing a
tertiary road and local roads is charged 18 km/h while a cell with only local
roads gets 25 km/h: adding a better road slows the cell. `emit/index.py:115`
then tells the user “Tertiary and local roads (GRIP4 classes 4-5), fitted at
18-25 km/h” — the range reads as ascending with grade and calls the
un-fitted default “fitted”. Also: CLAUDE.md says calibration constants live in
`calibration.toml` with a fitted/default comment; this table and
`urban.py:27-29` (`URBAN_*`) live in code.

**Fix:** enforce `speed[c] >= speed[c+1]` for c ≥ 1 (clamp local to ≤ tertiary
or refit local with the tertiary prior), move both tables into
`calibration.toml`, and generate the tooltip text from the values.

---

### CR-14 — `mode_detail()` hard-codes figures the calibration file owns
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

`emit/index.py:110-116` writes literal “200 km/h”, “75 km/h”, “35 km/h plus
30 min” and “halved” into `index.json`. `calibration.toml:110-125` and
`urban.URBAN_CONGESTION_FACTOR` are the sources of truth; change any of them
and the shipped tooltips are wrong with no test noticing. (Only the road
figures are interpolated — inconsistently.)

**Fix:** read `rail`/`ferry` from `load_rail_calibration()` /
`load_ferry_calibration()` and format `1/URBAN_CONGESTION_FACTOR`; add a test
that mutates a calibration value and asserts the text moves.

---

### CR-15 — Derived caches that violate the `_params_hash` rule
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

CLAUDE.md: “Derived caches key on `_params_hash` of the constants **and
inputs** that govern them, never on a bare `.exists()`.”

- `sources/urban.py:51-52` keys on `len(cells)`, `cells[0]`, `cells[-1]` — the
  exact shortcut `sources/countries.py:93-98` explains is wrong (“two
  different cell universes of the same length would otherwise share a cache
  entry”). It also omits `PLACES_ZIP`/source URL.
- `sources/routes.py:242-246` (`routes.parquet`), `:169-187`
  (`airline_destinations.json`) and `sources/wikidata.py:160-161`
  (`wikidata_iata.json`) are bare `.exists()` with no stamp for the parser
  regexes, `_SKIP_PREFIXES`, `_SANITY_PAIRS`, or the airports-table stamp
  they depend on. A parser fix never takes effect on a warm cache.
- `sources/landmask.py:169-178` stamps constants but not the polyfill method;
  `_cells_touching` (`:181-207`, currently dead) is “ready to replace overlap
  containment” and would silently reuse the overlap cache.
- `sources/roads.py:52-61` omits `GRIP4_URL`.
- `contour/grid.py:27,82` use hand-bumped `GRID_VERSION`/`NATIVE_VERSION`
  strings instead of hashing the constants.

**Fix:** stamp each with the governing constants (hash the full cell list for
`urban_mask`, as `countries.py` does); extend `tests/sources/test_cache_provenance.py`
to cover them — it currently covers only roads/airports/landmask.

---

### CR-16 — Partial builds leave a mixed `dist/`; deploy verification has no build identity and a stale origin count
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

- `cli.py:169-174` writes `hover_cells.bin` *before* any origin is solved, on
  the claim that it depends only on the graph. It depends on the cell
  universe, which changed in `1a4d66b`; an aborted build after that point
  leaves a new `hover_cells.bin` beside old `origins/*.bin` — precisely the
  mismatch CLAUDE.md warns renders a blank globe.
- Per-origin files are written straight into `dist/origins/` as each origin
  finishes; there is no build id. `scripts/deploy_verify.sh:9-36` compares
  *lengths* only, so old and new files of equal length pass.
- `scripts/browser_verify.sh:19` requires `"cities":157`; `data/origins.toml`
  has 553 origins. The post-deploy check either always fails or is being
  ignored — both are bad given the deploy rules.
- `web/app.js:722` comment and `docs`/READMEs still say 157.

**Fix:** write to `dist/.staging-<build id>/` and rename at the end; put the
build id (git sha + timestamp) in `index.json` and in a `manifest.json` with
per-file sha256 that `deploy_verify.sh` checks; derive the expected city count
from `index.json` in `browser_verify.sh`.

---

### CR-17 — `osm.rail_routes` dedupes cross-extract routes with an unstable sort
**Severity:** Medium · **Confidence:** Medium · **Status:** Likely

`sources/osm.py:199-207` keeps “the longer” of two regional fragments of one
`route_id` via `.sort("_n", descending=True).unique(["route_id","seq"],
keep="first")`. Polars' `sort` is not stable unless `maintain_order=True`, so
when both fragments have the same stop count the survivor's `seq` values are
an interleaving of two regions — a hybrid stop sequence whose consecutive
pairs are hundreds of kilometres apart, turned into rail edges at 75–200 km/h
by `graph/rail.py:86-114`. Even in the non-tie case the cross-border hop is
always lost (by design, but undocumented on the page).

**Fix:** `sort(["_n", "route_id", "seq"], descending=[True, False, False],
maintain_order=True)` or pick the winning extract explicitly; better, merge
fragments by `stop_id` overlap.

---

### CR-18 — A wikitext batch that triggers `continue` can never be resolved: permanent `_refuse_partial`
**Severity:** Medium · **Confidence:** Medium · **Status:** Needs manual validation

`sources/_utils.py:52-53` raises on any `continue` key; `sources/routes.py:212-237`
batches the *uncached* titles in a fixed order, 50 at a time, and marks a
failed batch unresolved without caching any of it. The Action API paginates a
`prop=revisions&rvprop=content` request whose result exceeds the size limit,
so a batch of fifty large airport articles can `continue` every single run —
and, because the batch composition is a pure function of what is not cached,
the same fifty fail identically on every re-run. `route_network()` then
refuses forever with a message that tells the operator to “re-run”.

**Fix:** on `continue`, halve the batch and retry (or follow `rvcontinue`);
cache the titles that *did* come back before giving up on the rest.

---

### CR-19 — Rail has no headway model, and the line name shown may not be the service used
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

`graph/rail.py:86-114` prices a ride as distance × detour / speed plus a flat
15 min boarding — a once-daily regional train and a metro cost the same, and
riding through a station never waits. Air pays (nominally, see CR-2) an
expected wait; rail pays none, so the model is biased *toward* rail in exactly
the regions where rail is sparse. Separately, `emit/rail_detail.py:55-56`
names a station pair by the *first* route seen (`setdefault`), while
`rail.ride_edges` used the *fastest* — the page can say “via Lyon (TER)” on
a leg priced as TGV. And `sources/osm.py:89` falls back to the *route* name
for an unnamed stop node, so a station can be captioned “KTX 경부선”.

**Fix:** at least add a per-route frequency proxy (relation count per
segment as a headway estimate) or a documented flat wait in
`calibration.toml`; pick the line name from the fastest route on the pair.

---

### CR-20 — Immigration-zone rules are incomplete and inconsistent between air and ground
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

Air uses OurAirports `iso_country` (`build.py:92-93`); ground/rail/ferry use
Natural Earth `ADM0_A3 → ISO_A2_EH` (`countries.py:76-82`). Consequences of
`transfers.py:15-22` being Schengen + CTA only:

- Paris → Réunion/Guadeloupe/Martinique/Guyane/Mayotte (RE/GP/MQ/GF/YT in
  OurAirports) pay a 45 min “border” on a domestic flight, while the same
  cells are `FRA` on the ground.
- Åland (AX), Isle of Man/Jersey/Guernsey (IM/JE/GG), Monaco/San Marino/
  Vatican (MC/SM/VA) are their own zones: Stockholm–Mariehamn ferry, IOM–LHR
  and every FR↔MC ground edge pay 45 min for a desk that does not exist.
- Northern Cyprus: ECN is `CY` in OurAirports but its cells are `CYN`.

**Fix:** map overseas departments to `FR`, add the CTA dependencies and
microstates, and normalise both paths through one `immigration_zone` table
keyed on a single country source. Add table-driven tests.

---

### CR-21 — `check_bands_cover` validates the GeoJSON, not the tiles tippecanoe ships
**Severity:** Medium · **Confidence:** Medium · **Status:** Needs manual validation

`emit/tiles.py:58-59` passes `--coalesce-densest-as-needed` and
`--extend-zooms-if-still-dropping`, and `:62-67` *logs* when tippecanoe
coarsened or dropped. The cover gate (`validate.py:48-95`) runs on the
feature collection before tippecanoe. So a tile where tippecanoe dropped or
coalesced a rim polygon can open a gap that no gate sees — the exact class of
failure the gate exists for.

**Fix:** decode a sample of emitted tiles (pmtiles + mapbox-vector-tile) and
re-run the vertex test on them, or drop the density flags and fail loudly when
tippecanoe reports dropping.

---

### CR-22 — `solve` and `index` subcommands write a different layout and skip every gate
**Severity:** Medium · **Confidence:** High · **Status:** Confirmed

`cli.py:233-251` writes `DIST/<name>.pmtiles`, `<name>.hover.bin`,
`<name>.routes.json` — not `DIST/origins/<slug>.{pmtiles,bin,json,air.bin,
modes.bin,rail.bin}` — and runs no coverage/monotonic/cover gate and no
`grid`/`native` arguments to `band_feature_collection`. Nothing the page can
load, and nothing the gates protect. `index` (`:253-263`) rebuilds
`hover_cells.bin` from an index built *without* rail (harmless today, since
cells do not depend on rail, but unstated).

**Fix:** make `solve` a thin wrapper over `_solve_one` with the same paths and
gates, or delete it and keep `build-all --limit`/`--only <slug>`.

---

### CR-23 — Lint debt hides real defects; dead and duplicated code
**Severity:** Low · **Confidence:** High · **Status:** Confirmed

`uv run ruff check .` → 46 errors, including the F821s of CR-1, `F841`
unused `position` in `hover.py:60`, `itinerary.py:58`, `modes.py:99`,
`first_arr` in `modes.py:53`, unused imports in `cli.py:22`, `build.py:10`,
`dijkstra.py:3,7`. Dead/duplicate code: `transfers.py:8-9` and `:53-54`
(same two constants twice), `landmask._cells_touching` (`:181-207`),
`rail.stations`' unused `cell` column (`rail.py:78-82`), `rail._haversine_km`
duplicating `ground.haversine_km`, four copies of
`sorted({cell_to_parent(c, HOVER_RES) …})` (`hover.py:27`, `itinerary.py:57`,
`modes.py:98`, `rail_detail.py:65`), `MAX_MINUTES` defined in both
`hover.py:22` and `modes.py:27`. Fix: make ruff a gate, delete, and route the
hover ordering through `hover.hover_cells`.

---

### CR-24 — Rounding and unit presentation inconsistencies
**Severity:** Low · **Confidence:** High · **Status:** Confirmed

- `emit/hover.py:67-69` `.astype("<u2")` **truncates** (59.9 → 59) while
  `emit/routes_json.py:27` rounds; `web/app.js:545` compares the two.
- `web/app.js:591-594` prints sub-hour bands as “0.5–0.6 h” (35 min → 0.6):
  the boundary is misstated by a minute and reads oddly; print minutes
  below 2 h.
- `web/app.js:447` `m = Math.round(min % 60)` can yield “1h 60m” for
  non-integer input (safe today only because inputs are ints).
- `graph/modes.py:79` attributes the 45 min land-border crossing to the
  road channel, so “by highway 2 h” may contain a passport queue.

---

### CR-25 — Shipped artifacts are written non-atomically
**Severity:** Low · **Confidence:** High · **Status:** Confirmed

`emit/index.py:98-101,136-139`, `hover.py:71-72`, `itinerary.py:70-71`,
`modes.py:109-110`, `rail_detail.py:90-93`, `routes_json.py:53-54` use
`write_bytes`/`write_text` directly while `_utils._atomic_write` exists and is
used for every cache. A worker killed mid-write leaves a truncated `.bin`
whose length `deploy_verify.sh` will reject — good — but a truncated
`index.json`/`hover_cells.bin` from the parent is a blank globe. Use
`_atomic_write` everywhere under `dist/`.

---

### CR-26 — Stale comments that now mislead maintainers
**Severity:** Low · **Confidence:** High · **Status:** Confirmed

`config.py:11` (“548,557 land cells at ~253 km²” — res-5 numbers; res 6 has
4.09 M), `config.py:19-24` (“11th band”, “eleven lumps”, “corner smoothing”),
`contour/bands.py:1,12-13` (“smoothed”, “2 km at resolution 5”), `bands.py:25`
and `cli.py:147`, `app.js:722` (157 origins), `hover.py:7-11`,
`itinerary.py:52-55`, `modes.py:95`, `app.js:30-34,573-577` (“min of seven
children”, res 5), `roads.py:100-113`, `ground.py:55`, `countries.py:91`,
`build.py:301-302`, `tiles.py:11-12` (res-5 hexes), `validate.py:26`
(“~43,500 cells”), `routes_json.py:38-39` and `transfers.py:5-7` (“Task 9”
stations not wired — they are), `calibrate_ground.py:47` (7,342 places),
`web/README.md:41-47` (single blue hue), `deploy/worldmap.atik.kr.conf:2`.

---

### CR-27 — `index.html` requests a font weight that is not vendored
**Severity:** Low · **Confidence:** High · **Status:** Confirmed

`web/index.html:136` sets `font-weight:300` on the main readout;
`web/vendor/fonts.css:7,14,21` declare only 400/500/600. The browser silently
uses 400 — CLAUDE.md: “a face that silently falls back undoes the choice”.
Ship Plex Sans 300 or set 400.

---

### CR-28 — Picker shows indistinguishable duplicate names; helper scripts have rough edges
**Severity:** Low · **Confidence:** High · **Status:** Confirmed

`data/origins.toml` has four pairs with identical `name` (Hyderabad IN/PK,
Suzhou, Fuzhou, Taizhou ×2 in CN) that the list at `app.js:753-766`
distinguishes only by coordinates. `scripts/expand_origins.py:98-99` writes
`name = "{…}"` without TOML escaping and `:46` caches non-atomically.
`scripts/browser_verify.sh:74` `kill -9`s any process whose command line
matches `agent-browser`. `scripts/osm_rail.sh:43` `r/type=route,route=train`
is parsed by osmium as `type ∈ {route, "route=train"}`, so every route
relation (bus, hiking…) survives the filter — harmless, but the extracts are
larger than the comment claims.

---

### CR-29 — `urban_mask` distance ignores the antimeridian; `countries.iso2` re-reads the shapefile on an empty table
**Severity:** Low · **Confidence:** High · **Status:** Confirmed (no real city affected today)

`sources/urban.py:61-64` uses `(lon − lo) × 111 × cos(lat)` without wrapping;
`countries.py:172-176` calls `_polygons()` (a full GDAL read) on every
`iso2()` call if the A2 table came back empty.

---

### CR-30 — `modes.mode_minutes_per_node` is O(nodes) Python with an h3 call per edge and a 6×float64 accumulator per node
**Severity:** Low (performance) · **Confidence:** High · **Status:** Confirmed

`emit/modes.py:60,64-86`: at ~10 M nodes that is ~480 MB per worker plus a
Python loop calling `_ground_adjacent` (two `base_parent` + one `grid_ring`)
per cell edge, per origin. Precompute an edge-mode array once in the parent
(`shared`) and vectorise the accumulation, or store uint16 channels.

---

### CR-31 — Airport search offers airports the graph dropped or isolated
**Severity:** Low · **Confidence:** High · **Status:** Confirmed

`emit/airports_json.py:14-22` ships every `scheduled_airports()` row,
including the ~25 dropped for lacking a land cell (`nodes.py:136-142`) and
the isolated ones (`validate.py:12-18`). Picking one gives “not on land” or a
∞ reading with no explanation. Filter by `idx.airports` minus isolated, or
flag them.

---

### CR-32 — Raw-download caches never refresh and are read by path in more than one place
**Severity:** Low · **Confidence:** High · **Status:** Confirmed

`sources/routes.py:291-293` reads `config.CACHE/"ourairports.csv"` directly;
if only the stamped parquet exists (cache cleared, build dir kept) it raises
`FileNotFoundError`. `airports._download` (`:23-30`) and the other raw
downloads are cached forever with no date; `index.json` carries no data
vintage, so the page cannot say when the route network was crawled.

---

## Final sweep (commonly missed classes)

- **Off-by-one / band edges:** `bands.band_of` (`bisect_left`) and
  `band_indices` (`searchsorted side="left"`) agree that a value exactly on
  an edge belongs to the lower band; `_feature` maps `k == len+1` to −1 and
  `max_minutes` to `None` correctly; legend positions `(i+1)/N` are right —
  only the *labels* are wrong (CR-10).
- **uint16 / sentinel:** `hover.MAX_MINUTES = 65534` clamps below 65535 ✓;
  `modes` clamps to 65534 ✓; `rail_detail` clamps table indices with
  `np.minimum(chosen, 0xFFFF)` — a table > 65535 rows would alias to
  NO_RAIL silently (unrealistic today); itinerary ordinals are airport
  indices (< 4,100) ✓. Truncation vs rounding: CR-24.
- **Units:** minutes throughout the graph; km/h → min via `×60` ✓;
  `haversine_km` radius 6371.0088 in three copies (CR-23); `app.js` uses
  6371 — fine.
- **Float/int:** `air.block_time_min` and `expected_wait_min` return
  banker's-rounded ints — consistent; `hover` truncates (CR-24).
- **Mutable defaults:** none in `src/`; tests trip RUF012 (harmless).
- **Exception swallowing:** `landmask.py:204,223` are annotated and
  re-surface; `wikidata`/`routes` catch and count ✓; `emit/water.py:102-123`
  runs tippecanoe with `capture_output=True` and never prints stderr on
  failure (unlike `tiles.py:71-72`) — the `CalledProcessError` message loses
  the reason. `app.js` `.catch(() => {})` on borders/places/airports is
  intentional progressive enhancement but also hides a 403 from the
  0600-permission bug class the tests mention.
- **Resource leaks:** `tiles.py` unlinks temps in `finally` ✓; `water._download`
  streams to `.part` and replaces ✓; forked workers inherit `_grid_cache`
  copy-on-write ✓.
- **Ordering assumptions:** hover ordering = sorted 15-hex-char H3 strings,
  equal to numeric order ✓ (`test_index` pins it); `itinerary`/`modes`
  argsort by distance relies on strictly positive weights, enforced at
  `build.py:371-372` ✓; polars `sort` instability (CR-17); `pool.imap`
  preserves order ✓.
- **Encoding / paths:** JSON written with `ensure_ascii=False` + utf-8 ✓;
  `_slug` regex blocks traversal ✓; `Path.with_suffix(".part.fgb")` is valid
  on 3.14 (checked) ✓; `deploy_verify.sh` uses system `python3` for a
  stdlib-only script ✓.
- **Concurrency:** `POLARS_MAX_THREADS=1` set before imports ✓; `SystemExit`
  in workers (CR-3); `countries.A3_TO_A2` module global populated as a side
  effect — filled in the parent before fork ✓.
- **CLAUDE.md design policy in `web/`:** no `letter-spacing`, no
  `text-transform`, no `tabular-nums`, no serif, fonts vendored ✓ — except
  the missing 300 weight (CR-27). Legend always visible ✓. Ramps measured by
  `tests/web/test_ramps.py` ✓.

## Coverage

Every file below was read in full (line-numbered) and considered; cross-file
flows traced: config → sources → nodes/refine → build (air/ground/rail/ferry/
transfers) → dijkstra → validate → bands/grid → emit (tiles/hover/itinerary/
modes/rail_detail/routes_json/index) → `web/app.js`/`index.html`; CLI and
deploy/verify scripts; each test module against the code it claims to cover.

- `pyproject.toml`, `calibration.toml`, `README.md`, `web/README.md`,
  `deploy/README.md`, `deploy/worldmap.atik.kr.conf`, `CLAUDE.md`,
  `data/origins.toml` (header + programmatic checks),
  `docs/superpowers/specs/2026-09-03-global-transport-time-map-design.md`
  (grepped for the invariants cited; not reviewed as code).
- `src/transport_maps/`: `__init__.py`, `config.py`, `cli.py`, `validate.py`;
  `sources/{__init__,_utils,airports,routes,countries,wikidata,roads,landmask,osm,urban}.py`;
  `graph/{__init__,nodes,build,air,ground,rail,refine,transfers}.py`;
  `solve/{__init__,dijkstra}.py`; `contour/{__init__,bands,grid}.py`;
  `emit/{__init__,index,hover,tiles,routes_json,itinerary,modes,rail_detail,places,borders,water,airports_json}.py`;
  `calibrate/{__init__,fit,ground}.py`.
- `scripts/`: `adsb_extract.py`, `browser_verify.sh`, `build_water_tiles.py`,
  `calibrate_ground.py`, `check_ramps.py`, `deploy_verify.sh`,
  `expand_origins.py`, `ground_check.py`, `osm_rail.sh`.
- `tests/`: `test_cli.py`, `test_config.py`, `test_golden.py`,
  `test_licence_firewall.py`, `test_validate.py`, `cli/test_entrypoint.py`,
  `calibrate/{test_fit,test_ground}.py`, `contour/{test_bands,test_grid,test_native_grid}.py`,
  `emit/{test_hover,test_index,test_itinerary,test_modes,test_rail_detail,test_routes_json,test_tiles}.py`,
  `graph/{test_air,test_build,test_ferry,test_ground,test_nodes,test_rail,test_rail_integration,test_refine,test_transfers}.py`,
  `solve/test_dijkstra.py`,
  `sources/{test_airports,test_cache_provenance,test_countries,test_landmask,test_osm,test_roads,test_routes,test_urban,test_wikidata}.py`,
  `web/test_ramps.py`, plus the `__init__.py` stubs and `tests/fixtures/icn_wikitext.txt` (presence).
- `web/app.js`, `web/index.html`, `web/vendor/fonts.css` (weights only;
  other vendored libraries not reviewed).
