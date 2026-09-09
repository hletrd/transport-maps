# Code Review: transport-maps (feature-dev:code-reviewer)

Reviewing the full repository at `/Users/hletrd/flash-shared/transport-maps` — everything under `src/`, `scripts/`, `tests/`, `web/app.js`, `web/index.html`, `calibration.toml` and `pyproject.toml` — against the binding rules in `CLAUDE.md`, with particular attention to the H3 resolution/cell-ordering contracts, the `UNREACHABLE` sentinel, the `.modes.bin`/`.rail.bin` layouts, `_params_hash` cache keys, the `cli.py` worker orchestration, and the deploy gate.

Reviewed at HEAD `ac191db`. (Aggregator note: FD-1 and FD-2 were fixed by another agent during the review in `7b7e601` and `edf4b0d`.)

## Critical

### FD-1: `NodeIndex(...)` constructor call in `build_index()` is malformed — every call crashes
**Severity:** Critical **Confidence:** High
**File:** `src/transport_maps/graph/nodes.py:184-187`

```python
return NodeIndex(cells, codes, cell_pos, airport_pos, airport_cell, tuple(dropped),
                 tuple(station_keys), station_pos, station_cell,
                 base_cells=base_cells, base_index=base_index, fine=fine,
                 _split=frozenset(split_set))
```

The dataclass field order (lines 42-65) is: `cells, airports, _cell_pos, _airport_pos, _airport_cell, dropped_airports, stations, base_cells, base_index, fine, _split, _station_pos, _station_cell`. The 9 positional arguments above bind `station_pos` to the **`base_cells`** field (position 8) and `station_cell` to the **`base_index`** field (position 9) — then the call *also* passes `base_cells=base_cells` and `base_index=base_index` as keywords for the same two parameters. Python raises `TypeError: NodeIndex.__init__() got multiple values for argument 'base_cells'` on every single invocation, unconditionally (this triggers even when `rail_routes` is `None`, since `station_pos`/`station_cell` are always initialized to `{}` and always passed positionally).

**Failure scenario:** `nodes.build_index()` is the entry point every pipeline command uses (`cli.py`'s `solve`, `index`, and `build-all`, plus `graph/build.py`, `tests/graph/test_nodes.py`, `tests/graph/test_build.py`, etc.). None of them can currently run past this call — the whole pipeline is non-functional. Separately, note that even after fixing the arg alignment, `station_pos`/`station_cell` (the real dicts the rail-station indices were built from) are never actually threaded into `_station_pos`/`_station_cell` — the constructor call needs those two dicts passed to the correct keyword-named fields, not positionally into `base_cells`/`base_index`.

**Fix:** Pass every field by keyword (safest, given how easy this is to get wrong positionally):
```python
return NodeIndex(
    cells=cells, airports=codes, _cell_pos=cell_pos, _airport_pos=airport_pos,
    _airport_cell=airport_cell, dropped_airports=tuple(dropped),
    stations=tuple(station_keys), base_cells=base_cells, base_index=base_index,
    fine=fine, _split=frozenset(split_set),
    _station_pos=station_pos, _station_cell=station_cell,
)
```

---

### FD-2: `NodeIndex.base_index`/`fine` default factories reference `np`, but `numpy` is never imported in `graph/nodes.py`
**Severity:** Critical **Confidence:** High
**File:** `src/transport_maps/graph/nodes.py:61-62`

```python
base_index: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
fine: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=bool))
```

The module's imports are only `logging`, `dataclasses.{dataclass, field}`, `h3`, `transport_maps.config`, `transport_maps.sources.{airports, landmask}` — there is no `import numpy as np` anywhere in the file. These `default_factory` lambdas close over the free variable `np`, resolved against the module's global namespace at call time, independent of any annotation-evaluation semantics. Whenever a `NodeIndex` is constructed without explicitly supplying `base_index`/`fine`, the generated `__init__` invokes the lambda and raises `NameError: name 'np' is not defined`.

**Failure scenario:** Numerous test fixtures build a bare `NodeIndex` this way and rely on the defaults, e.g.:
- `tests/sources/test_urban.py:15`
- `tests/sources/test_countries.py:41,63,75,104`
- `tests/graph/test_ferry.py:32`
- `tests/graph/test_rail_integration.py:35`

Every one of these raises `NameError` at fixture-construction time (independently of FD-1, since these call sites don't go through `build_index()` at all).

**Fix:** `import numpy as np` at the top of `graph/nodes.py`.

---

## Important

### FD-3: `test_neighbouring_land_cells_are_connected` hardcodes resolution 5, but the solver grid only ever contains resolution 6/7 cells
**Severity:** High **Confidence:** High
**File:** `tests/graph/test_build.py:61-65`

```python
def test_neighbouring_land_cells_are_connected(csr, idx):
    import h3
    seoul = h3.latlng_to_cell(37.5665, 126.9780, 5)
    u = idx.cell_index(seoul)
```

`config.SOLVE_RES = 6` and `graph/refine.refine()` guarantees every entry of `idx.cells` is either that base resolution-6 cell or one of its resolution-7 children (`config.FINE_RES`) — never resolution 5. An H3 cell id encodes its resolution, so a resolution-5 id can never equal a resolution-6/7 id for the same point. `idx.cell_index(seoul)` (`self._cell_pos[cell]`, `nodes.py:79-80`) is therefore guaranteed to raise `KeyError`, not exercise the assertion the test is written for.

**Failure scenario:** Once FD-1/FD-2 are fixed and `build_index()` can actually run, this test fails immediately with `KeyError`, not with the intended assertion about edge connectivity.

**Fix:** Use `idx.cell_at(37.5665, 126.9780)` (which already resolves base-vs-fine correctly) instead of a hardcoded `h3.latlng_to_cell(..., 5)`.

---

### FD-4: `emit/rail_detail.write_rail_detail()` recomputes origin-independent work on every origin
**Severity:** Medium **Confidence:** High
**File:** `src/transport_maps/emit/rail_detail.py:68-89`

`stop_names` (a dict built by looping `routes["lat"], routes["lon"], routes["name"]`) and `lines = _line_between(routes)` (a Polars `.sort()` + `.with_columns(map_elements(...))` + `.group_by("route_id")` over the *entire* rail network, up to 257,000 rows per the module's own docstring) depend only on the fixed `routes` DataFrame — not on `idx`, `minutes` or `predecessors`. Yet `write_rail_detail` is called once per origin from `cli.py:_solve_one` (line 102-103), so this Python-UDF sort/group-by is redone up to 157 times in a full build.

This is exactly the anti-pattern the project already fixed for `ground.cell_speed_kmh` and `countries.cell_country` — `cli.py:_build_all` explicitly hoists those into `shared` with the comment "the ground speed grid does not change between origins, and re-deriving it per origin cost ~4.8s x 157 origins for the same value." The same reasoning applies here.

**Fix:** Compute `stop_names` and `lines` once in `_build_all` (or lazily-memoize inside `rail_detail`), and pass them through `shared` instead of recomputing per origin.

---

### FD-5: `browser_verify.sh` computes `disclaimer` and `borders` checks but never asserts on them
**Severity:** Medium **Confidence:** High
**File:** `scripts/browser_verify.sh:12-19`

```bash
R=$(agent-browser eval '(()=>{...return JSON.stringify({
  canvas:!!q("#map canvas"), cities:..., tints:..., ramps:...,
  borders:!!q(".maplibregl-canvas"), disclaimer:document.body.textContent.includes("For reference only")})})()' ...)
echo "  $R"
echo "$R" | grep -q '"canvas":true' || fail=1
echo "$R" | grep -q '"tints":37' || { ...; fail=1; }
echo "$R" | grep -q '"cities":157' || fail=1
```

`borders` and `disclaimer` are computed and echoed but no subsequent `grep -q ... || fail=1` ever checks either value, so the deploy gate cannot detect a missing MapLibre canvas class or missing disclaimer copy. This is exactly the class of problem CLAUDE.md's testing rule warns about ("A test that passes when the code is deliberately broken is worse than none"). Worth noting separately: even if asserted, the `disclaimer` check as written can never fail meaningfully — `<noscript>` content is present in the DOM as an inert text node whenever scripting is enabled (it's merely hidden via the UA's default `noscript{display:none}`), so `document.body.textContent` includes "For reference only…" from `web/index.html`'s `<noscript>` block (`index.html:425`) regardless of whether `app.js` ran or the map rendered at all.

**Fix:** Either assert on `borders`/`disclaimer` (`echo "$R" | grep -q '"borders":true' || fail=1`, etc.) or remove them if they're not meant to gate anything; and replace the `disclaimer` check with something that actually distinguishes a working render (e.g. a visible `.mast`/`#key` element's text) rather than `<noscript>` content.

---

## Minor

### FD-6: Stale "the 11th band is open-ended" comment in `config.py` contradicts the actual 37-band scheme
**Severity:** Low **Confidence:** High
**File:** `src/transport_maps/config.py:19-24`

```python
# Upper edge of each isochrone band, in minutes. The 11th band is open-ended.
# Thirty-six bands on a geometric ladder from 30 minutes to 72 hours, ...
BAND_EDGES_MIN: tuple[int, ...] = (30, 35, 40, ..., 4025, 4320)  # 36 entries
```

`contour/bands.py:171` computes `open_band = len(config.BAND_EDGES_MIN)` (36) and treats band index 36 (the 37th band) as open-ended; `CLAUDE.md`'s design policy and `scripts/browser_verify.sh:18` (`"tints":37`) both confirm the scheme has 37 total bands. "The 11th band is open-ended" is a leftover from an earlier 11-band design and is simply wrong for the current 36-edge/37-band scheme.

**Fix:** Update the comment to describe the last (37th) band as open-ended.

---

### FD-7: Stale "res-5" language across the H3-resolution contract
**Severity:** Low **Confidence:** High
**Files:** `src/transport_maps/config.py:11`, `src/transport_maps/emit/hover.py:7`, `src/transport_maps/emit/modes.py:95`, `src/transport_maps/emit/itinerary.py:51`, `web/app.js:30-34`

`config.SOLVE_RES = 6` (confirmed consistent with `FINE_RES = 7`'s "1.2 km cells instead of 3.2 km" comment, which matches H3 resolution 6→7 edge lengths). But:
- `config.py:11` describes the solver grid as "548,557 land cells at ~253 km^2 each" — that area matches resolution **5** (~253 km²), not resolution 6 (~36 km²).
- `emit/hover.py:7` says "the value of its CENTRE res-5 child"; `emit/modes.py:95` and `emit/itinerary.py:51` both say "the same res-5 child" — the code actually uses `config.SOLVE_RES` (6).
- `web/app.js:30-34` comments the surface as "solved per res-5 cell (~8 km)" and falls back `const SOLVE_RES = meta.solveRes ?? 5;` — the real value shipped in `index.json` is 6.

None of this is presently a functional bug (the JS reads `meta.solveRes` dynamically, and the Python computations use `config.SOLVE_RES` correctly), but it's exactly the cross-file H3-resolution contract the project cares most about getting right, and the stale "5" is likely to mislead the next person who touches `SOLVE_RES`, `FINE_RES`, or the `web/app.js` fallback.

**Fix:** Update the comments (and the `?? 5` fallback default) to reflect resolution 6.

---

### FD-8: Duplicate, dead `STATION_ACCESS_MIN`/`STATION_EGRESS_MIN` constants with a stale "rail isn't wired" comment
**Severity:** Low **Confidence:** High
**File:** `src/transport_maps/graph/transfers.py:5-9` and `:53-54`

```python
# Defined here for Task 9 (rail) to consume once station nodes exist in the
# graph. Not wired into build_graph yet -- there is no station_index to wire
# them to (Task 9 is blocked on the OSM extract). Intentionally unused for now.
STATION_ACCESS_MIN = 15.0
STATION_EGRESS_MIN = 10.0
...
STATION_ACCESS_MIN = 15.0
STATION_EGRESS_MIN = 10.0
```

Rail is fully wired today (`graph/rail.py`, `graph/build.py::_rail_edges`, `NodeIndex.station_index`/`station_cell_index`), and the actual boarding/alighting costs come from `calibration.toml`'s `[rail]` section (`cal.boarding_min`, `cal.alighting_min` in `build.py:274-275`) — these two constants are unused dead code, defined twice in the same file. `tests/graph/test_transfers.py:90-92` (`test_station_constants_exist_for_task_9`, "Defined but deliberately unwired until rail lands") only checks they exist and compare correctly; it doesn't exercise anything real.

**Fix:** Remove the duplicate definitions and the stale comment, or wire the constants in if they were meant to replace the calibration-driven boarding/alighting cost.

---

## Coverage

Files read and reviewed in full: `CLAUDE.md`; `src/transport_maps/config.py`, `cli.py`, `validate.py`; `src/transport_maps/contour/bands.py`, `grid.py`; `src/transport_maps/graph/nodes.py`, `build.py`, `ground.py`, `refine.py`, `air.py`, `transfers.py`, `rail.py`; `src/transport_maps/solve/dijkstra.py`; `src/transport_maps/emit/hover.py`, `index.py`, `modes.py`, `rail_detail.py`, `itinerary.py`, `routes_json.py`, `tiles.py`, `water.py`, `borders.py`, `places.py`, `airports_json.py`; `src/transport_maps/sources/_utils.py`, `airports.py`, `landmask.py`, `roads.py`, `routes.py`, `urban.py`, `countries.py`, `wikidata.py`, `osm.py`; `scripts/deploy_verify.sh`, `browser_verify.sh`; `pyproject.toml`; `calibration.toml`; `web/app.js`, `web/index.html`; `tests/sources/test_cache_provenance.py`, `test_urban.py`, `test_countries.py`; `tests/graph/test_ferry.py`, `test_rail_integration.py`, `test_nodes.py`, `test_build.py`, `test_transfers.py` (partial).

Examined but not called out (read as part of the modules above; no additional findings): `src/transport_maps/__init__.py` and package `__init__.py` files.

Not opened this pass (repo is large; prioritized the modules the task named plus everything they import): `src/transport_maps/calibrate/fit.py`, `calibrate/ground.py`; `scripts/adsb_extract.py`, `osm_rail.sh`, `build_water_tiles.py`, `expand_origins.py`, `check_ramps.py`, `ground_check.py`, `calibrate_ground.py`; the remaining test files not listed above. No findings are claimed for these; a follow-up pass would be worth doing given the severity of FD-1/FD-2, since they likely mask further test breakage once fixed.
