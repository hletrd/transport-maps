# Debugger review — latent bug surface

Scope: `/Users/hletrd/flash-shared/transport-maps` at HEAD `ac191db` (2026-09-10 00:04 KST), read-only.
Angle: failure modes that have not fired yet — escaped/swallowed exceptions, partial writes, numeric and H3/shapely edge cases, stale caches, CLI and page regressions. Every high-value suspicion below was reproduced with a scratchpad experiment (scripts under `/private/tmp/claude-501/-Users-hletrd-flash-shared-transport-maps/aacce825-73ee-496f-a42e-4a7a5c8148d1/scratchpad/dbg/`); nothing in the repo was modified and no build/deploy was run.

## Summary

| Severity | Count | IDs |
|---|---|---|
| Critical | 1 | DBG-1 |
| High | 4 | DBG-2, DBG-3, DBG-4, DBG-5 |
| Medium | 6 | DBG-6, DBG-7, DBG-8, DBG-9, DBG-10, DBG-11 |
| Low | 9 | DBG-12 … DBG-20 |

Status legend: **Confirmed** = reproduced by experiment or by running the code; **Likely** = code path certain, trigger depends on data/timing; **Needs manual validation** = mechanism shown, full-scale trigger not measured.

---

## Findings

### DBG-1 — `graph/nodes.py` never imports numpy: `build_index()` and every default-constructed `NodeIndex` raise `NameError` at HEAD
- **Severity:** Critical  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/nodes.py:21-27` (imports: `logging`, `dataclasses`, `h3`, `config`, `airports, landmask` — no `numpy`), `:61-62` (`field(default_factory=lambda: np.zeros(...))`), `:124` (`split_set = {base_cells[i] for i in np.flatnonzero(split)}`).
- **Trigger:** any call to `nodes.build_index()` (so `transport-maps build-all`, `solve`, `index`, every `scripts/*.py` that builds an index) and any `NodeIndex(...)` constructed without explicit `base_index`/`fine` (every test fixture in `tests/graph/test_ferry.py`, `test_rail_integration.py`, `tests/sources/test_countries.py`, `test_urban.py`, …). Python 3.14's deferred annotations hide the missing name at class-definition time, so the module imports cleanly and the failure only surfaces at call time.
- **Failure scenario:** the operator starts the new res-6/7 build and it dies after the ~40 s land-cell/road/urban preamble with `NameError: name 'np' is not defined`; the test suite is red across five modules. The `build-all` currently running (pid 12633) was started before this commit and is executing the old module, so nothing has flagged it.
- **Evidence:** `uv run pytest tests/graph/test_nodes.py -x` → `src/transport_maps/graph/nodes.py:124: NameError: name 'np' is not defined`; `uv run pytest tests/graph/test_ferry.py -x` → `nodes.py:61: NameError`. `git show HEAD:src/transport_maps/graph/nodes.py | grep numpy` is empty.
- **Fix:** add `import numpy as np` to `nodes.py`. Then, per CLAUDE.md's testing rule, keep a cheap smoke test that instantiates `NodeIndex([...], [], {...}, {}, {}, ())` with the defaults (that test would have gone red here in 0.5 s instead of after a 40 s fixture).

### DBG-2 — A coverage failure inside a forked worker hangs `build-all` forever instead of aborting
- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:84-87` (`raise SystemExit(f"{slug}: coverage … below …")` inside `_solve_one`), `:187-191` (`ctx.Pool(workers)` + `pool.imap(_solve_one_forked, origins)`).
- **Trigger:** ≥ 4 origins (so `_worker_count` > 1) and any origin whose coverage is below `MIN_COVERAGE`. `multiprocessing.pool.worker` only catches `Exception`; `SystemExit` escapes, the worker process exits, the pool's maintenance thread quietly respawns a replacement, and the in-flight task never produces a result, so `imap.__next__` blocks forever. The same hang occurs for a worker killed by the macOS OOM killer / SIGKILL — the exact risk `_worker_cap` (`cli.py:70-74`, "at ten million cells eight workers exceed 32 GB") is trying to dodge.
- **Failure scenario:** a multi-hour 553-origin build prints the coverage message from the child to stderr, then sits at 0 % CPU indefinitely with `n-1` idle workers; the operator sees neither an exit code nor a traceback. The serial path (`cli.py:183-185`) exits 1 correctly, so the two code paths disagree.
- **Evidence:** `scratchpad/dbg/pool_systemexit.py` (fork context, 2 workers, task 1 raises `SystemExit`): child prints `origin-1: coverage 0.0% below 90%`, parent prints `origin-0 ok`, then `RESULT: parent HUNG for 20 s after the worker's SystemExit (imap never returned)` (alarm fired). `tests/test_cli.py:107-125` cannot see this because `_worker_count(2) == 1` forces the serial path.
- **Fix:** raise a regular exception (e.g. `RuntimeError`) from `_solve_one` and convert to `SystemExit` in `main()`; or move to `concurrent.futures.ProcessPoolExecutor(mp_context=fork)` which raises `BrokenProcessPool` when a worker dies; and add a per-task timeout on `imap` (`pool.imap(...)` → iterate `next(it, timeout=…)` via `imap_unordered`/`apply_async().get(timeout)`) so a dead worker can never stall the build.

### DBG-3 — Mixed-resolution ferry edges duplicate a ground edge, so the first refined build with ferries aborts in `build_graph`
- **Severity:** High  **Confidence:** High  **Status:** Confirmed (synthetic) / Likely (real extracts)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/graph/build.py:306` (`if idx.cells[v] in h3.grid_disk(idx.cells[u], 1): continue` — same-resolution adjacency only), vs `graph/ground.py:115-130` (a fine cell is joined to the unsplit base cell beyond its ring, both directions) and `build.py:381-386` (duplicate `(row, col)` → `RuntimeError`).
- **Trigger:** any OSM ferry way ≥ `MIN_FERRY_KM` (1 km) whose two terminals land in a res-7 cell and a neighbouring unsplit res-6 cell (or vice versa) — i.e. a harbour ferry at the edge of any urban/secondary-road area: Norwegian fjords, Greek islands, Hong Kong outlying islands, Puget Sound, the Bosphorus edges. `grid_disk` of a res-7 cell can never contain a res-6 id, so the "already joined by road" skip is bypassed while `hex_edges` has already emitted `(u, v)` and `(v, u)`.
- **Failure scenario:** `build-all` builds the ~10 M-cell index (minutes), assembles edges, then dies with `graph edge list contains duplicate (row, col) pairs; coo_matrix would silently sum their weights` before solving a single origin. With 5,672 crossings in the extracts the chance that none straddles a split boundary is negligible. `tests/graph/test_ferry.py` only exercises uniform-resolution indices.
- **Evidence:** `scratchpad/dbg/ferry_mixed.py`: a Helsinki res-6 disk with the centre split; fine cell `871126d31ffffff` → base cell `861126d07ffffff`, 3.70 km apart; `idx.cells[v] in h3.grid_disk(idx.cells[u], 1)` = **False**; `ground.hex_edges` joins `(u,v)` and `(v,u)`; `_ferry_edges` emits `{(19,10),(10,19)}`; intersection non-empty; `build_graph`'s key check would raise = **True**.
- **Fix:** test adjacency the way `emit/modes._ground_adjacent` already does (`graph/refine.base_parent` on both ends; skip when parents are equal or ring-1 neighbours), or make `build_graph` reduce duplicates by `min` instead of refusing. Add a mixed-resolution case to `tests/graph/test_ferry.py` and confirm it goes red on the current code.

### DBG-4 — Per-origin artifacts are written non-atomically; a sibling failure `terminate()`s workers mid-write and the deploy gate cannot see the truncation
- **Severity:** High  **Confidence:** High  **Status:** Confirmed (mechanism) / Likely (occurrence)
- **Where:**
  - `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/tiles.py:70` (`shutil.move(str(staged), str(out))`): the staged file is in the local temp dir and `out` is on `dist/`, which lives on NFS (`mount` → `172.30.60.100:/mnt/mnt/flash/flash-shared … (nfs)`), so `move` degrades to `copy2` + unlink: `out` is truncated to zero and refilled over seconds.
  - `emit/hover.py:72`, `emit/index.py:99,137`, `emit/itinerary.py:71`, `emit/modes.py:110`, `emit/rail_detail.py:91-93`, `emit/routes_json.py:54`: plain `write_bytes`/`write_text` straight into `dist/`. `sources/_utils._atomic_write` (`_utils.py:68-89`) exists and its docstring — and `tests/sources/test_cache_provenance.py:133-138` ("Every artifact in dist/ goes out through this helper") — claim it is used for dist, but no emitter uses it.
  - `cli.py:189` `with ctx.Pool(...)`: any worker exception propagates through `imap` and `__exit__` calls `terminate()` → SIGTERM to the other 4–7 workers, which are by construction mid-write; Python's default SIGTERM disposition skips the `finally` at `tiles.py:73-75`, so the staged `.pmtiles` and the multi-hundred-MB GeoJSON leak in `/var/folders/...`, and the `tippecanoe` child (`tiles.py:41`) is orphaned and keeps running.
  - `scripts/deploy_verify.sh:26-27` checks only `.pmtiles` existence; `.json`/`.rail.json` are never checked; the page swallows a JSON parse failure (`web/app.js:424-431` `.catch(() => {})`).
- **Trigger:** any gate failure or crash in one origin while others are being emitted (DBG-3-style aborts, `check_bands_cover`, OOM), or an operator Ctrl-C, or an NFS hiccup during the copy.
- **Failure scenario:** `dist/origins/<slug>.pmtiles` is a 0–N byte prefix of a PMTiles archive with a plausible mtime. The gate says "every origin has pmtiles + bin …" because the file exists; the page loads the header, tile range requests fail or return garbage → blank/holed globe for that origin with only a MapLibre console warning. A truncated `<slug>.json` yields no itinerary for that city, silently. This is precisely the "never deploy a partial dist/" class CLAUDE.md warns about, but from inside a single build rather than from mixing builds.
- **Evidence:** environment confirmed NFS; `shutil.move` cross-filesystem semantics are documented (`copy2` then remove); write calls cited above; `Pool.__exit__ → terminate()` semantics; `tests/emit/*` all write to `tmp_path` and never exercise dist.
- **Fix:** route every dist write through `_atomic_write` (temp file in `out.parent`, `os.replace`); for pmtiles, `shutil.copy2` to `out.with_suffix(".pmtiles.tmp")` then `os.replace`; make the deploy gate validate the PMTiles header/length (`b"PMTiles"` magic, root directory offset within file size) and parse every `.json`; on abort, catch `BaseException` in the parent and remove the in-flight origin's files. Consider `signal.signal(SIGTERM, …)` in workers so `finally` runs and the tippecanoe child is killed.

### DBG-5 — `urban._places()` cannot download its source: `places_mod._download()` is called without its required `url` argument (and would fetch the wrong dataset)
- **Severity:** High  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/sources/urban.py:36-40` (`if not path.exists(): from ..emit import places as places_mod; places_mod._download()`), vs `emit/places.py:35` (`def _download(url: str) -> pathlib.Path`, which downloads GeoNames files, never `ne_10m_populated_places_simple.zip`; nothing else in the repo downloads that archive — `grep populated_places` finds only `urban.py:31`).
- **Trigger:** `data/cache/ne_10m_populated_places_simple.zip` absent — every fresh clone, a build host (mac0/mac1/mac3), CI, or a cache clean. Locally the file exists (dated 8 Sep, mode 0600, from a pre-chmod `_atomic_write`), which is the only reason `build_index()` ever gets past `urban_mask`.
- **Failure scenario:** `build-all` on a new machine dies in the index preamble with `TypeError: _download() missing 1 required positional argument: 'url'`; if someone "fixes" it by passing a URL, `_download(CITIES_URL)` would write `cities15000.zip` and `_places()` would still fail on the missing NE zip. Stale-cache regression in the strict sense: the code only works because of an artifact nothing can regenerate.
- **Evidence:** `scratchpad/dbg/urban_fresh.py` (empty `config.CACHE`): `RESULT: _places() on an empty cache raises TypeError: _download() missing 1 required positional argument: 'url'`.
- **Fix:** give `urban.py` its own `_download()` with the Natural Earth URL (`https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_populated_places_simple.zip`) via `_atomic_write`, and stamp the URL into the `urban_mask` cache key (see DBG-10). Add a test that redirects `config.CACHE` to an empty `tmp_path` and monkeypatches `httpx.get`.

### DBG-6 — The page's itinerary hides every flight before a surface leg between two airports ("To JAV, and through the airport: 20h53m")
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (real data)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:473-489` (`legsTo` walks `prev` through `routes.byId`, which holds airport nodes only — `emit/routes_json.py:31-39`, whose comment still says rail nodes "are added in Task 9"), `:537` (`To ${ap(chain[0].code)}, and through the airport` with `chain[0].min`).
- **Trigger:** any shortest path of the form `… → B_arr → cell → (road/rail/ferry) → C_dep → D_arr`: multi-airport cities (GMP/ICN, HND/NRT, LHR/LGW/STN, JFK/EWR, CDG/ORY), and islands/regions where a flight lands at one field and the onward flight leaves from another. `C_dep.prev` is a cell id, `byId.get` returns `undefined`, and the walk stops; flights A→B vanish and their time is attributed to reaching C.
- **Failure scenario:** with Seoul active, click Ilulissat: the Route panel shows "20 h 53 m — To JAV, and through the airport", then "Fly JAV → NAQ". The reader is told it takes 21 hours to reach a Greenland airport by surface transport from Seoul.
- **Evidence:** `scratchpad/dbg/chain_break.py` over `dist/origins/seoul.{json,air.bin,bin}`: of 81,626 hover cells with an air itinerary, **27,313 (33.5 %)** have a visible chain head that is a departure node reached more than 6 h after leaving Seoul; example `To JAV … 20h53m → JAV:dep → NAQ:arr`.
- **Fix:** emit, per departure node, the arrival node it was reached from through the surface leg (or emit the surface-hop cells' `prev` for the few cells that sit between two airport nodes) so the page can bridge the gap; or emit `last_arrival_before` in `routes_json` computed from `itinerary.arrival_airport_per_node`. At minimum, when `chain[0].kind === "dep"` and `chain[0].min` exceeds any plausible access time, label the row "… by earlier flights and surface transport".

### DBG-7 — Rapid origin switches race: the slower city's `.bin/.air.bin/.modes.bin/.json` overwrite the newer one's
- **Severity:** Medium  **Confidence:** High  **Status:** Likely
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:402-411` (`hoverTimes = new Uint16Array(b)` with no `active === o` check), `:415-431` (`hoverModes`, `hoverAir`, `routes` likewise). Only the rail pair at `:396-401` guards with `active === o`. No `AbortController` anywhere.
- **Trigger:** click city A then city B within one round trip (the list is one click per row; keyboard users tab through fast). With `.bin` served gzipped and sizes/latencies differing per origin, A's 181 KB array can land after B's.
- **Failure scenario:** the bands painted are B's (the PMTiles source is replaced synchronously), but hover readouts, the Route panel and "Door to door" come from A; `hoverAir` from A and `routes` from B produce a chain of the wrong airports. Nothing in the console. The bug is invisible to `browser_verify.sh`, which clicks once and waits 5 s.
- **Evidence:** by inspection; the asymmetric guard at `:400` shows the authors hit exactly this on the rail files.
- **Fix:** hold an `AbortController` per `paintOrigin` call, abort the previous one, and check `active === o` (or `signal.aborted`) before assigning any array; clear `pinB`-dependent panels until the new arrays arrive.

### DBG-8 — The south-pole cap dissolves into planar garbage; `check_bands_cover`'s fixed-seed sample can then abort every build for a given cell universe
- **Severity:** Medium  **Confidence:** Medium  **Status:** Confirmed (geometry) / Needs manual validation (abort)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/sources/landmask.py:135-144, 217` (`_pole_cells`: 19 cells around 90°S are always in `idx.cells`), `contour/bands.py:62-85` (`_crosses_antimeridian` → `_split_at_antimeridian` unwraps longitudes and clips; correct for a cell that straddles ±180°, meaningless for a cell that contains or nearly contains the pole), `:120-132` (`_dissolve`), `validate.py:82-84` (`np.random.default_rng(seed=0)` picks the same 20,000 interior cells for every origin).
- **Trigger:** always for the geometry; the abort fires iff any pole-disk cell is in the sampled set for some LOD — which is deterministic per universe (same seed, same `interior`), so it is either never or on every origin of a given build.
- **Failure scenario:** geometry: the pole cell (`86f29380fffffff`, lon span 255°) becomes two slivers along lat −89.97/−89.98; the 19-cell disk dissolves to a "valid" 41.96 deg² polygon whose bounds are `[-180, -89.99, 180, -89.82]` and which fails to contain **51 of its own 114 hex vertices**. Gate: if sampled, `check_bands_cover` raises "n of 20,000 interior hex vertices fall between bands" on the first origin and the build never emits anything, with an error that points at bands rather than at the pole.
- **Evidence:** `scratchpad/dbg/h3_edges.py` output: `dissolve(pole disk) … valid: True area: 41.955 bounds: [-180.0, -89.99, 180.0, -89.82]`, `pole-disk vertices NOT covered by their own dissolved band: 51/114` (true spherical area 745.8 km²). Whether the res-6 universe's seed-0 sample includes one of the 19 cells was not computed (needs the full `native_edges`).
- **Fix:** treat pole-containing cells specially — emit the cap as a `[-180,-90]…[180,-89.9x]` rectangle in lat/lon (which MapLibre's globe renders as a disc) or drop pole cells from `interior` in `check_bands_cover` and from `_dissolve`; and make the gate's error name the cells that failed so a pole/antimeridian cause is recognisable.

### DBG-9 — `browser_verify.sh` hard-codes 157 departure cities; the 553-origin build cannot pass post-deploy verification
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (by code)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/scripts/browser_verify.sh:19` (`echo "$R" | grep -q '"cities":157' || fail=1`), vs `data/origins.toml` (553 `[[origin]]` entries; `web/index.html:15,23,41,375,421` already say 553) and `web/app.js:722` comment ("only the 157 cities").
- **Trigger:** the next full build + deploy.
- **Failure scenario:** the one script that CLAUDE.md makes mandatory before a deploy is declared done fails on a correct site (`SOME CHECKS FAILED`), and the natural reaction — skipping or loosening it — removes the guard that caught the blank-globe deploys.
- **Fix:** read the expected count from `dist/index.json` (`origins.length`) inside the script, and assert equality with the rendered list.

### DBG-10 — Cache keys omit inputs: `urban_mask` keys on count + first/last cell, `ferry_links` omits `ANTIMERIDIAN_EPS_DEG`, `road_class_grid` omits `GRIP4_URL`
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (by code)
- **Where:**
  - `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/sources/urban.py:51-53`: `_params_hash(URBAN_POP_MIN, URBAN_RADIUS_KM, len(cells), cells[0], cells[-1])` — not the cell list, not `PLACES_ZIP`/its URL. `countries.py:93-96` explicitly calls this pattern "the exact failure this helper exists to prevent" and hashes every cell.
  - `sources/osm.py:151-153`: `ferry_links` key = file fingerprint only; `_ferries` applies `ANTIMERIDIAN_EPS_DEG` (`:106,:134`) and `FERRY_SCHEMA` at parse time, so changing either reads the stale parquet.
  - `sources/roads.py:59`: `_params_hash(DENSITY_THRESHOLD, GRID_ROWS, GRID_COLS, N_TYPES)` omits `GRIP4_URL`.
- **Trigger:** a land-mask change that keeps the count and the two end cells (e.g. lake handling or ice-shelf edits in the middle of the sorted list) → misaligned urban mask → wrong cells halved, silently; or `scripts/calibrate_ground.py:61` calling `urban.urban_mask(idx.cells)` on the *mixed* list, whose count/ends can coincide across split-mask changes.
- **Failure scenario:** ground speeds silently computed against a mask from a different universe; every test still green (they read the same cache).
- **Fix:** hash the cell list (`hashlib.sha256("".join(cells))` as `countries.py:96` does) plus the source URL/filename; add `ANTIMERIDIAN_EPS_DEG`, `MIN/MAX_FERRY_KM`-independent parse constants and `sorted(FERRY_SCHEMA)` to the ferry key; add `GRIP4_URL` to the road-grid key. Extend `tests/sources/test_cache_provenance.py` with "path moves when X moves" cases for each.

### DBG-11 — `build-all` has no resumption, so DBG-2/3/4-class failures cost the whole multi-hour run
- **Severity:** Medium  **Confidence:** High  **Status:** Confirmed (by code)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:131-200` (`_build_all`: `--limit` only, no `--only`/`--skip-existing`/`--from`), `:174` (`hover_cells.bin` rewritten first, so a partially rebuilt `dist/` immediately disagrees with untouched old origins on the local preview even though the deploy gate will catch it by count).
- **Trigger:** any abort after origin k of 553 (the 157-origin res-5 build already took ~8 h serially; the res-6/7 build is an order of magnitude larger).
- **Failure scenario:** the operator must rerun all 553 origins to recover the last few; meanwhile `dist/` holds a new `hover_cells.bin` next to old per-origin arrays, which the local preview at :8899 renders as a blank globe.
- **Fix:** accept `--only slug,…` and `--skip-existing` (skip an origin whose seven files exist, are non-empty and — after DBG-4 — atomically written, and whose `hover_cells.bin` count matches), write `hover_cells.bin` to a staging name and swap it with `index.json` at the end.

### DBG-12 — `check_coverage` returns NaN on an all-excluded universe, and NaN passes the gate
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/validate.py:33-39` (`np.isfinite(considered).mean()` on an empty array → `nan`), `cli.py:84` (`coverage < MIN_COVERAGE` is `False` for NaN).
- **Trigger:** every cell south of −60° (a test fixture, a mis-set `KNOWN_UNREACHABLE_MAX_LAT`, a broken land mask that only kept Antarctica).
- **Evidence:** `scratchpad/dbg/misc.py`: `coverage on all-Antarctic index: nan | gate cov < MIN_COVERAGE = False`.
- **Fix:** `if considered.size == 0: raise ValueError(...)`; assert `np.isfinite(coverage)` in the caller.

### DBG-13 — Hover minutes are truncated while `routes.json` minutes are rounded
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/hover.py:67-69` (`.astype("<u2")` truncates: 59.9 → 59), `emit/routes_json.py:27` (`round(...)`: 59.9 → 60); consumed together in `web/app.js:544-556` (`total > landed.min`, `dur(total - landed.min)`).
- **Failure scenario:** "Door to door" can read one minute less than the sum of the legs, and a genuine sub-minute onward leg is dropped or a legitimate "Onward" row disappears. Cosmetic, but it is the first place a reader will spot an inconsistency.
- **Evidence:** `misc.py`: `hover encodes [59.9, 65534.7, 70000] as [59, 65534, 65534] (routes.json rounds: 60)`.
- **Fix:** `np.rint` before the cast in `hover.py` (and `modes.py:108`).

### DBG-14 — `index.json` `modeDetail` hard-codes rail/ferry figures instead of reading `calibration.toml`
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (by code)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/emit/index.py:110-112` ("high-speed lines at 200 km/h, conventional at 75 km/h … 35 km/h plus 30 min") vs `calibration.toml:109-125`.
- **Failure scenario:** the next recalibration changes the numbers the model uses while the page keeps explaining the old ones; nothing tests the prose.
- **Fix:** format from `rail.load_rail_calibration()` / `load_ferry_calibration()` like the road sentence already does with `SPEED_BY_ROAD_CLASS_KMH`.

### DBG-15 — The page has no failure UI for its two top-level awaits; an odd-length `hover_cells.bin` or a 404 is a blank globe
- **Severity:** Low  **Confidence:** High  **Status:** Likely
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:27` (`await fetch("./index.json")` → `.json()`), `:38-40` (`new BigUint64Array(await …arrayBuffer())` throws `RangeError` unless `byteLength % 8 == 0`; a 404 HTML body is almost never a multiple of 8); `web/index.html:72-73` preloads both with `crossorigin` while the fetches run in default credentials mode, so Chrome discards the preload and warns.
- **Failure scenario:** exactly the "blank site with a console error nobody looked at" class from CLAUDE.md's deploy rules, e.g. after an `rsync --delete` that raced a build, or a truncated `hover_cells.bin` (`emit/index.py:99` is a plain `write_bytes`).
- **Fix:** wrap the bootstrap in `try/catch` that writes a visible message into `#where`; assert `byteLength % 8 === 0` and `hoverTimes.length === hoverCells.length` before use; drop `crossorigin` from the preload links (same-origin fetch) or add `{credentials:"omit"}`... whichever matches.

### DBG-16 — Hover highlight and `SOLVE_RES` ignore refinement
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (by code)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:34-35, 335` (`h3.latLngToCell(lat, lon, SOLVE_RES)` outlines the res-6 parent even where the surface was solved at res 7; `meta.fineRes` is shipped by `emit/index.py:125` but unused).
- **Failure scenario:** in every city the outlined "solved cell" is seven times the area of the cell the number came from — the exact mismatch the comment at `:30-33` says was fixed once already.
- **Fix:** ship the split-base-cell set (or a res-6 bitmap) and outline the res-7 cell when the base cell is split.

### DBG-17 — Geolocation's deferred `flyTo` hijacks the next user gesture when the nearest city is already active
- **Severity:** Low  **Confidence:** Medium  **Status:** Likely
- **Where:** `/Users/hletrd/flash-shared/transport-maps/web/app.js:992-994` (`if (c.slug !== active?.slug) paintOrigin(c); map.once("moveend", () => map.flyTo(...))`).
- **Trigger:** a viewer near Seoul (the fallback) whose position arrives after the initial `flyTo` has finished: no new movement starts, so `moveend` fires at the end of the viewer's *own* first drag or zoom and the globe lurches to their position.
- **Fix:** only register the `moveend` hook when `paintOrigin` was called; otherwise `flyTo` immediately (or skip when the view is already near).

### DBG-18 — `rail_routes` cross-extract de-duplication is non-deterministic on ties
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (by code)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/sources/osm.py:202-207` (`sort("_n", descending=True).unique(subset=["route_id","seq"], keep="first")` — no secondary key, no `maintain_order`).
- **Failure scenario:** a cross-border relation present in two extracts with the same number of resolved stops keeps whichever half the sort happens to place first; results differ between machines even with identical inputs, defeating the content-keyed cache's promise of reproducibility.
- **Fix:** add a deterministic tie-break (extract name) to the sort and `maintain_order=True`.

### DBG-19 — `_solve_one` runs polars inside forked workers despite the module's own rule
- **Severity:** Low  **Confidence:** Medium  **Status:** Needs manual validation
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/cli.py:102-103, 149-151` ("no forked child ever calls into polars") vs `emit/rail_detail.py:47-49, 73-75` (`routes.sort(...).with_columns(map_elements(...))`, `zip(routes["lat"], …)` on the inherited 257k-row frame, per origin, per worker).
- **Trigger:** rail present (`data/cache/osm/*-rail.osm.pbf` exists now — the current `dist/` has no `.rail.bin`, so this path has never run under the pool). `POLARS_MAX_THREADS=1` (`cli.py:9`) is what makes it survive today; any future polars build that spawns its pool eagerly, or an env override, brings back the "eight workers at 0 % CPU for 37 minutes" deadlock, and DBG-2 makes it a permanent hang rather than a crash.
- **Fix:** precompute `_line_between(routes)` and `stop_names` once in the parent (they are origin-independent) and pass plain dicts through `shared`; keep the child polars-free.

### DBG-20 — Dead/stale code that will mislead the next fix
- **Severity:** Low  **Confidence:** High  **Status:** Confirmed (by code)
- **Where:** `/Users/hletrd/flash-shared/transport-maps/src/transport_maps/config.py:19-24` (comment: "The 11th band is open-ended. Thirty-six bands …" — there are 36 edges, 37 bands, band 36 open); `graph/transfers.py:8-9` and `:53-54` (`STATION_ACCESS_MIN`/`STATION_EGRESS_MIN` defined twice, "not wired yet", while `calibration.toml:117-118` `boarding_min/alighting_min` are what the graph uses; `tests/graph/test_transfers.py:90-92` pins the dead constants); `sources/landmask.py:181-207` (`_cells_touching`, unused, carries the only `BLE001` noqa the ruff config cites as its justification); `emit/routes_json.py:38-39` ("Rail nodes are added in Task 9") — never done, and the omission is the root of DBG-6; `web/app.js:722` ("157 cities"), `web/README.md:39-45` (describes an eleven-step single-hue ramp that no longer exists).
- **Fix:** delete the dead code and constants, correct the comments, and pin the count contract in `tests/test_config.py` (`len(BAND_EDGES_MIN) + 1 == 37` is what `browser_verify.sh:18` and the legend assume).

---

## Final sweep (commonly missed items)

- **Band index vs edge index, `<` vs `<=`:** consistent. `bands.band_indices` uses `searchsorted(side="left")` so a value exactly on an edge belongs to the lower band (`band_of(30.0) == 0`, `band_of(30.0000001) == 1`, measured); `_feature.max_minutes = BAND_EDGES_MIN[k]` is the inclusive upper edge; the page's `bandRangeAt` prints `(EDGES[b-1], EDGES[b]]` and the legend puts edge *i* at `(i+1)/N_BANDS` — all agree. Unreachable is `len(edges)+1 → -1` and the page maps `-1 → UNCHARTED` and sorts it to the bottom. 37 bands = 36 edges + open band, matched by `N_BANDS` in `app.js:98`.
- **Endianness:** every array is written `<u2`/`<u8` and read with `Uint16Array`/`BigUint64Array` (host order, little-endian on every supported browser platform); no `DataView` defaults involved. OK.
- **`Math.round` vs floor:** see DBG-13 (Python side); on the page `fmtTime` only sees integers so `min % 60` is exact.
- **Timezone/locale:** no dates are formatted; `navigator.language` is only forwarded to Nominatim; `toFixed` is locale-independent. OK.
- **`Number` parsing of `index.json`:** `unreachable/hoverRes/solveRes` fall back with `??`; `origins[].lat/lon` are used arithmetically and via `.toFixed` — a string value would throw, but `emit/index.write_index` serialises TOML floats, so only a hand-edited `index.json` could hit it.
- **Silent `catch {}`:** `app.js:231, 331, 401, 419, 423, 431, 727, 792, 841` swallow fetch/parse failures for places, borders, rail, modes, air, routes, airports, Nominatim. Intentional for progressive extras, but combined with DBG-4 a truncated `<slug>.json` produces "no itinerary" with zero signal; at least log at `console.warn`.
- **`.rail.bin` 404:** handled (`r.ok ? … : null`); no crash. Note the current deployed build has no `.rail.*` files, so every origin switch logs two 404s in the console — `browser_verify.sh:60` greps the console for `error`, which may or may not include resource-load failures depending on `agent-browser`'s console capture.
- **`hover_cells.bin` odd length:** see DBG-15 (`RangeError`, blank page).
- **Nominatim debounce/order:** 900 ms debounce plus `addressSeq` and `value.trim() !== q` staleness checks are correct; `reverseGeocode` guards with `pinB.lat !== lat`. OK.
- **`localStorage`:** all reads/writes wrapped in `try/catch`. OK.
- **Keyboard handlers inside the search box:** MapLibre's keyboard handler is bound to the map canvas container, so typing in `#q` cannot pan/zoom; `applyLockNorth` only toggles it. OK.
- **Scheme switching:** repaints `bands`, `sphere`, `water`, legend and picker; `band-seams` no longer exists (`:376, :923` are dead branches). OK.
- **Resize / mobile:** `layoutForSize` re-parents `.reading` on the media-query change; touch devices never get `mousemove`, so the readout only updates on tap (by design; the `.tip` is hidden by CSS). OK.
- **History/URL state:** the page has none (no `pushState`, no query parsing), so there is nothing to parse malformed params from; a deep link to a city/destination is a missing feature rather than a bug.
- **Division by zero / NaN / negative times:** `build_graph` rejects non-positive and non-finite weights (`build.py:371-372`); `frequency_model` floors distance at `KNEE_KM` and frequency at 0.5/week; `expected_wait_min` guards ≤ 0; `rail.ride_edges` drops same-station hops so `km == 0` cannot reach the graph; `haversine_km` on identical points returns 0 only for a self-loop, which `_ferry_edges` skips. `uint16` overflow is clamped to 65534 (`hover.py:22, 68`, `modes.py:27, 108`, `rail_detail.py:91`). OK.
- **H3 pentagons:** `grid_ring` on a res-6 pentagon returns 5 neighbours and `cell_to_children` 6 (measured), so the `-1` slot in `grid.universe`'s `nb` table doubles as "pentagon gap"; every consumer masks `nb >= 0` first. OK. Pole cells: DBG-8. Antimeridian: handled for straddling cells; `roads.cell_class` falls back to the centroid for lon spans > 180° (pole cell span 255°, measured).
- **Shapely:** `_polygonal` strips `make_valid`'s LineString debris; `_dissolve` returns `None` for an empty group and callers check `is_empty`. `_without_lakes` handles `GeometryCollection` results. OK.
- **h3-py `cells_to_h3shape(tight=True)`:** requires a single resolution; `_dissolve` groups by resolution first. OK.
- **Fork safety:** `POLARS_MAX_THREADS=1` is set before any import (`cli.py:9`); see DBG-19 for the one child-side polars use.

## Coverage

Every file below was read in full unless marked otherwise.

**Pipeline (`src/transport_maps/`)** — `__init__.py`, `cli.py`, `config.py`, `validate.py`; `calibrate/fit.py`, `calibrate/ground.py`; `contour/bands.py`, `contour/grid.py`; `emit/airports_json.py`, `emit/borders.py`, `emit/hover.py`, `emit/index.py`, `emit/itinerary.py`, `emit/modes.py`, `emit/places.py`, `emit/rail_detail.py`, `emit/routes_json.py`, `emit/tiles.py`, `emit/water.py`; `graph/air.py`, `graph/build.py`, `graph/ground.py`, `graph/nodes.py`, `graph/rail.py`, `graph/refine.py`, `graph/transfers.py`; `solve/dijkstra.py`; `sources/_utils.py`, `sources/airports.py`, `sources/countries.py`, `sources/landmask.py`, `sources/osm.py`, `sources/roads.py`, `sources/routes.py`, `sources/urban.py`, `sources/wikidata.py`. The six sub-package `__init__.py` files are empty (0 bytes, verified).

**Scripts** — `scripts/adsb_extract.py`, `scripts/browser_verify.sh`, `scripts/build_water_tiles.py`, `scripts/calibrate_ground.py`, `scripts/check_ramps.py`, `scripts/deploy_verify.sh`, `scripts/expand_origins.py`, `scripts/ground_check.py`, `scripts/osm_rail.sh`.

**Page** — `web/app.js` (all 999 lines), `web/index.html` (all 432 lines), `web/README.md`. `web/vendor/*` (third-party, pinned), `web/llms.txt`, `web/robots.txt`, `web/sitemap.xml`, `web/preview.png`: not code, not reviewed.

**Configuration / deploy / data** — `calibration.toml`, `pyproject.toml`, `deploy/worldmap.atik.kr.conf`, `deploy/README.md`, `CLAUDE.md`; `data/origins.toml` (header read, entry count verified = 553); `dist/index.json`, `dist/hover_cells.bin`, `dist/origins/*`, `data/cache/*`, `data/build/*` inspected for state (timestamps, counts, cache-key stamps) but not modified. `.gitignore`, `.python-version`, `uv.lock`: not reviewed.

**Tests (all read)** — `tests/test_cli.py`, `tests/test_config.py`, `tests/test_golden.py`, `tests/test_licence_firewall.py`, `tests/test_validate.py`, `tests/cli/test_entrypoint.py`, `tests/calibrate/test_fit.py`, `tests/calibrate/test_ground.py`, `tests/contour/test_bands.py`, `tests/contour/test_grid.py`, `tests/contour/test_native_grid.py`, `tests/emit/test_hover.py`, `tests/emit/test_index.py`, `tests/emit/test_itinerary.py`, `tests/emit/test_modes.py`, `tests/emit/test_rail_detail.py`, `tests/emit/test_routes_json.py`, `tests/emit/test_tiles.py`, `tests/graph/test_air.py`, `tests/graph/test_build.py`, `tests/graph/test_ferry.py`, `tests/graph/test_ground.py`, `tests/graph/test_nodes.py`, `tests/graph/test_rail.py`, `tests/graph/test_rail_integration.py`, `tests/graph/test_refine.py`, `tests/graph/test_transfers.py`, `tests/solve/test_dijkstra.py`, `tests/sources/test_airports.py`, `tests/sources/test_cache_provenance.py`, `tests/sources/test_countries.py`, `tests/sources/test_landmask.py`, `tests/sources/test_osm.py`, `tests/sources/test_roads.py`, `tests/sources/test_routes.py`, `tests/sources/test_urban.py`, `tests/sources/test_wikidata.py`, `tests/web/test_ramps.py`. `tests/fixtures/icn_wikitext.txt` (data fixture) not reviewed; the six `tests/*/__init__.py` are empty.

**Docs** — `README.md` and `docs/superpowers/{plans,specs}/*.md` were grepped for stated build contracts (atomicity, resumption, worker failure) only; none are stated there.

**Executed (read-only, scratchpad):** `uv run pytest tests/graph/test_nodes.py tests/graph/test_refine.py -x`, `uv run pytest tests/graph/test_ferry.py tests/graph/test_rail_integration.py -x` (both red with DBG-1), and the scratchpad scripts `pool_systemexit.py`, `h3_edges.py`, `ferry_mixed.py`, `misc.py`, `urban_fresh.py`, `chain_break.py` under `scratchpad/dbg/`. No process was started or stopped other than these; no file under `dist/`, `data/` or the repo was written except this review.
