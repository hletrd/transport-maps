# Verifier review, cycle 2 — evidence-based correctness against stated behaviour

Repository: `/Users/hletrd/flash-shared/transport-maps` @ **`bf9e5cc`** (branch `feat/transport-pipeline`).
Working tree at review time: **clean** (`git status --short` empty; the session's opening git-status snapshot listing `M sources/_utils.py … ?? tests/sources/test_cache_provenance.py` was stale — `git ls-files` shows that test tracked since `fd5da85`). Every gate and every number below was therefore measured on exactly `bf9e5cc`.

Read-only review: no file under the repo, `dist/` or `data/` was written by me except this file. Scratch copies and logs live under `/private/tmp/claude-501/-Users-hletrd-flash-shared-transport-maps/aacce825-73ee-496f-a42e-4a7a5c8148d1/scratchpad/` (`ruff_cycle2.log`, `pytest_cycle2.log`, `pytest_cycle2.time`, `check_ramps.log`, `mutver/`, `snap_check.py`). A 553-origin `build-all` (pids 4143–4147, started 04:28:31) was running in this checkout throughout; nothing I ran started, stopped or touched it.

Finding IDs continue the cycle-1 sequence (**VER-24 …**) so that the `VER-6`, `VER-20` etc. already cited in `plan/*.md` stay unambiguous; cycle-1 findings are written `c1-VER-n`.

## Gate results

| Gate | Result |
| --- | --- |
| `uv run ruff check .` (ruff 0.16.5) | **FAIL — 2 errors**: `F401 itertools.pairwise imported but unused` at `src/transport_maps/emit/rail_detail.py:12`; `RUF007 Prefer itertools.pairwise() over zip()` at `rail_detail.py:55`. Both introduced by `bf9e5cc` (it rewrote `pairwise(st)` as `zip(st, st[1:])` and kept the import). Plan task F14 ("`uv run ruff check .` exits 0", ticked at `a3f918f` 00:56) regressed at 04:23 the same night. → VER-24 |
| `uv run pytest -q -W default --durations=15` (pytest under uv's CPython 3.14.2) | **254 passed, 4 deselected, 1 warning, 0 failed, 0 skipped** in 1590.42 s — **26 min 30 s** wall (`time -p`: real 1591.18, user 1334.93, sys 61.65), with the five-worker rebuild running beside it (load average 10–27). Cycle 1 recorded 251 passed in 16 min 42 s; the three new tests are `bf9e5cc`'s two and `test_index_json_advertises_rail_detail` (`662f7d5`). Deselected by the default `addopts`: 3 × `network`, 1 × `real_multi_band`. Side effect to know about: the run wrote **nine files into the real `data/cache/`** at 04:57:38 (`ferry_links-d7484730.parquet`, `rail_routes-{04057732,4f5acac9,7a2e3903,60cfb642,74c1ed75,47844fc6,ca8d1b69,ce316507}.parquet`, 2.1–2.8 KB each) — `tests/sources/test_osm.py` builds its PBF fixtures in `tmp_path` but `osm.rail_routes()`/`ferry_links()` cache into `config.CACHE` (`osm.py:153,183`); that is plan item **F4b**, still open, now with the file list. |
| Warnings emitted by the run | Exactly one: `tests/test_cli.py::test_a_gate_failure_in_a_forked_worker_aborts_the_run` → `…/python3.14/multiprocessing/popen_fork.py:70: DeprecationWarning: This process (pid=15059) is multi-threaded, use of fork() may lead to deadlocks in the child.` — the **W1** entry already in `plan/2026-09-10-c1-gates-and-tests.md:51-61` (the production build forks on purpose; the test exercises that path). No `PytestWarning`, `ResourceWarning` or other category. |
| Slowest tests (`--durations=15`) | 373.71 s call `tests/graph/test_ground.py::test_hex_edge_cost_uses_destination_speed_not_source`; 271.41 s setup `tests/graph/test_build.py::test_route_pairs_naming_an_unknown_airport_are_counted` (second `build_graph`, `test_build.py:104-108`); 261.46 s setup `tests/graph/test_build.py::test_matrix_is_square_and_matches_node_count` (module `idx`/`csr`); 248.74 s setup `tests/test_golden.py::test_seoul_to_tokyo_is_a_half_day_or_less`; 91.89 s / 87.99 s / 56.53 s calls in `test_ground.py`; 44.43 s `test_nodes.py::test_the_dropped_airport_bound_actually_aborts`; 43.61 s setup `test_roads.py::test_cell_class_is_never_worse_than_centroid_sampling`; 43.31 s setup `test_nodes.py::test_cells_occupy_the_low_indices`; everything else ≤ 2.5 s. Roughly 1,480 s of the 1,590 s is six `build_index()`/`build_graph()` constructions across module fixtures — plan item **F4a** (mark them `integration`) and TE-18 (double graph build). |
| `uv run python scripts/check_ramps.py` | **12/12 OK.** Anchor ΔE min per scheme: muted 6.9, vivid 8.9, warm 6.5, ice 6.8, forest 7.0, mono 6.8, ember 8.0, rose 7.3, sand 6.5, twilight 7.3, copper 6.8, lavender 6.8; lightness strictly decreasing in all; sea L 0.20–0.22. See VER-32 for the interpolated bands. |
| `tests/emit/test_rail_detail.py` and `tests/graph/test_refine.py` run individually (bf9e5cc's two new tests) | `uv run pytest -q -W default tests/emit/test_rail_detail.py` → **3 passed in 0.65 s**; `… tests/graph/test_refine.py` → **5 passed in 0.50 s**. |
| Mutations of `bf9e5cc` on scratch copies (`PYTHONPATH=…/mutver/mN`, `-p no:cacheprovider`, repo untouched; `transport_maps.__file__` confirmed to resolve into the scratch copy) | m0 (unmutated copy): 8 passed. **m1** `_nearest_land` searches ring 1 only → `test_an_airport_off_the_mask…` **red** (`assert (None is not None)`, `test_refine.py:76`). **m2** `_nearest_land` returns the first hit and ignores distance → **green** (the "nearest" claim is untested). **m3** `lookup_tables` leaks a DataFrame into `stop_names` → `test_lookup_tables…` **red** (`isinstance(…, dict)`). **m4** `write_rail_detail` builds and sorts a polars frame again after unpacking `tables` → **green** (the "no polars in the worker" claim is untested). → VER-27 |

Findings by severity: **High 1 · Medium 5 · Low 9** (15 new), plus cycle-1 items re-confirmed with new evidence (W1, F4b, I4, E1, E3).

## Findings

### High

#### VER-25 — `dist/` is a mixture of two builds right now, and the 8899 preview serves it
- Severity **High** · Confidence High · Status **Confirmed** · Effort M (the real fix is A6b/A6c; a preview guard is S)
- `dist/hover_cells.bin`, `dist/origins/*.bin|.air.bin|.modes.bin`, `dist/index.json`; `web/app.js:541-559`
- Evidence (all read-only stat/size; `python3 - <<PY … PY` in the log):
  - `dist/hover_cells.bin`: 725,920 B = **90,740** entries, mtime **04:28:31** — written by the running build (`cli.py:196` writes it eagerly; the build's pids started 04:28:31).
  - **152** origins have `.bin`/`.air.bin`/`.modes.bin` of **90,659** entries, mtime Sep 9 **22:45** (e.g. `abu-dhabi.bin`) — the res-5 build that `index.json` (23:18, `solveRes: 5`, 157 origins, 7 attribution entries) describes.
  - **5** origins (`fukuoka nagoya osaka seoul tokyo`) have 90,740-entry arrays plus `.rail.bin/.rail.json`, mtime 04:34–04:36 — the first outputs of the running build.
  - The preview (`Server: SimpleHTTP/0.6 Python/3.14.3`, port 8899) serves `web/index.html` (24,316 B, 4 cycle-1 markers) and `web/app.js` (50,447 B) over this `dist/`: `/hover_cells.bin` 725,920 B, `/origins/seoul.bin` 181,480 B (90,740), `/index.json` 11,754 B (157 origins, `solveRes` 5, `attribution` 7).
- Failure scenario: choose any origin other than the five rebuilt ones on the preview. `cellIndex()` (`app.js:541-550`) binary-searches the 90,740-entry res-6 parent list and indexes a 90,659-entry array: from the first differing parent onwards every reading is a neighbouring cell's time, and for indexes ≥ 90,659 `hoverTimes[i]` is `undefined`, which `lookup()` (`:555-559`) cannot distinguish from "not loaded", so the readout says "Loading the times from Abu Dhabi…" for ever (`:714-717`). Before 04:34 this applied to Seoul as well. Any browser verification done on the preview since the first res-6 build overwrote `hover_cells.bin` was against misaligned data for the origins it happened to touch; `scripts/deploy_verify.sh:9-36` would (correctly) refuse to ship it — the refusal recorded in `593c231` — but the preview has no such gate. This is the CLAUDE.md deploy rule's "never mix per-origin arrays and `hover_cells.bin` from different builds" happening inside the working tree.
- Note on `593c231`'s wording: it calls the 90,659-entry arrays "new origin arrays" against a 90,740-entry `hover_cells.bin`. The mtimes show the reverse: the 90,659 arrays are the Sep 9 res-5 build; the 90,740 `hover_cells.bin` is the new (res-6) one.
- Fix: A6b/A6c as planned (write `hover_cells.bin` and `index.json` last, into a staging directory, with a build id per origin sidecar). Until then: have the build write to `dist.new/` and let the preview serve a snapshot whose `hover_cells.bin` length equals every origin array's, or make the preview server refuse `/hover_cells.bin` when the lengths disagree. Correct the `593c231` progress line.

### Medium

#### VER-24 — The ruff gate is red at HEAD; `bf9e5cc` reintroduced two of the findings F14 cleared
- Severity **Medium** (no runtime effect, but a shipped gate is red and the plan's definition of done for F14 is "`uv run ruff check .` exits 0") · Confidence High · Status **Confirmed** · Effort S
- `src/transport_maps/emit/rail_detail.py:12` and `:55`
- Evidence: `uv run ruff check .` → `F401 [*] itertools.pairwise imported but unused --> rail_detail.py:12:23`, `RUF007 Prefer itertools.pairwise() over zip() --> rail_detail.py:55:21`, `Found 2 errors.` `git show bf9e5cc` shows `-        for a, b in pairwise(st):` / `+        for a, b in zip(st, st[1:]):` with the import left in place. `a3f918f` (00:56) had made the same file lint-clean; `plan/2026-09-10-c1-gates-and-tests.md:17-20` ticks F14 on that basis.
- Failure scenario: any CI or pre-commit gate on ruff is red; the next `ruff --fix` will delete the import, and the "gate: ruff clean" line in the plan is false at HEAD.
- Fix: restore `for a, b in pairwise(st):` (the `zip` rewrite changed nothing semantically). Run `uv run ruff check .` before committing.

#### VER-26 — `_nearest_land` (bf9e5cc) cannot see land that was refined: split neighbours are invisible to the snap
- Severity **Medium** (6 of the 46 snappable airports stay dropped, among them Kitakyushu — a reclaimed-island airport beside a city, the case the commit was written for) · Confidence High · Status **Confirmed** (code, and measured from the caches) · Effort S
- `src/transport_maps/graph/nodes.py:114-128,142-147,155-165`; `src/transport_maps/graph/refine.py:43-49`
- Evidence: `build_index` builds `cell_pos = {c: i for i, c in enumerate(cells)}` (`nodes.py:142`) over the *mixed* list `refine.refine()` returns: unsplit base cells plus the seven res-7 children of every split base cell (`refine.py:43-49`); a split base cell's own id is not in `cells`. `_nearest_land(cell, cell_pos, …)` is only reached when `cell_at()` returned a res-6 id that is not in the mask (a base cell that is in the mask and split always yields a res-7 child, which is always present), and it then does `cell_pos.get(n)` for `n in h3.grid_ring(cell, ring)` — res-6 ids (`nodes.py:119-120`). Every neighbour that is land *and* dense (urban mask or GRIP4 class 1–3, `refine.py:28-31`) is therefore reported as "not indexed", and the airport is dropped as before. The new test (`tests/graph/test_refine.py:69-78`) builds its `land` dict from unsplit ring-2 ids and cannot observe this.
- Impact measurement (`scratchpad/snap_check.py`, 4 s; reads `land_cells_r6_dd95e3b5.parquet`, `airports_c35abade.parquet`, `road_class_grid_495d9dd1.npy` and the populated-places zip; recomputes the split decision as `refine.dense_mask(roads.cell_class(cells), urban)`; wrote nothing under `data/`): 4,091,715 land cells, 4,008 airports; **58** airports whose res-6 cell is not in the mask (the cycle-1 log said 64 against an earlier stamp/table; the difference does not affect the point). Of the 58: **12** have no land within two rings (dropped either way: APK CNC FTA KKR MNF OKR PKP RGI RMT SYU TGJ TIH); **40** have at least one unsplit land cell within two rings (the snap works); **6** have land within two rings but every such cell is split, so `_nearest_land` returns `None` and they are still dropped: **DPL, HLE, KKJ, PTF, WLS, WSZ**.
- Failure scenario: an airport on reclaimed land (its res-6 cell outside the 1:10m mask) next to a city: ring-1/ring-2 land cells are all urban → all split → `_nearest_land` returns `None` → airport dropped, the log says "snapped" for the rural cases only, and the count in the commit message ("64 needed it") overstates what the snap achieves.
- Fix: give `_nearest_land` the split set (or `idx.base_cells`/`_split`) and, for a ring cell `n` that is split, consider `h3.cell_to_children(n, config.FINE_RES)` that are in `cell_pos`, picking the nearest child; or look the ring cell up through `cell_at(lat, lon)`-style resolution. Add a test built like `tests/graph/test_ferry.py::_mixed_index` (one split neighbour) that must snap into a child; KKJ (33.846, 131.035) is a real fixture. Also update `nodes.py:32` ("25 of 4,008 today").

#### VER-27 — bf9e5cc's two tests do not test the two claims the commit makes
- Severity Medium (CLAUDE.md testing rule: "assume a new test is vacuous until shown otherwise") · Confidence High · Status **Confirmed** (mutants run on scratch copies) · Effort S
- `tests/graph/test_refine.py:69-78`; `tests/emit/test_rail_detail.py:40-51`
- Evidence:
  - `test_an_airport_off_the_mask_snaps_to_the_nearest_land_cell_within_two_rings`: `assert pos is not None and ring2[pos] in ring2` — the second clause is a tautology (`ring2[pos]` is by construction an element of `ring2`). "Nearest" is never asserted: mutant **m2** (return the first indexed ring cell, ignore distance) stays **green**. Mutant **m1** (search ring 1 only) goes **red**, so the ring-2 search is tested.
  - `test_lookup_tables_are_plain_dicts_a_fork_can_use`: asserts the *types* returned by `lookup_tables`; it does not assert that `write_rail_detail` no longer touches polars, which is the property the commit message and `cli.py:184` claim ("a forked worker must never touch a polars frame"). Mutant **m4** (`write_rail_detail` builds and sorts a `pl.DataFrame` after unpacking `tables`) stays **green**. Mutant **m3** (a DataFrame leaks into `tables["stop_names"]`) goes **red**, so the types are tested.
- Fix: in the refine test, place the probe point off-centre so one ring-2 cell is measurably nearer, and assert that exact cell; for the fork claim, monkeypatch `rail_detail.pl` (or `_line_between`) to raise and call `write_rail_detail(idx, minutes, pred, tables, …)` on the two-cell fixture — it must not raise.

#### VER-28 — The live site still runs the pre-cycle-1 page; the plan says it was verified "after deploy"
- Severity Medium (an escaping fix — I1, XSS class — and two CC BY credits are repo-only; the plan's completion line is inaccurate) · Confidence High · Status **Confirmed** · Effort S (a page-only deploy mode) / bookkeeping
- `plan/2026-09-10-c1-web-ui-detail.md:141`; `plan/2026-09-10-c1-build-robustness.md:126`; `scripts/deploy_verify.sh:53-55`
- Evidence: `curl https://worldmap.atik.kr/index.html` → 200, 19,223 B, **0** occurrences of `id="disclaimer"`, `sw-uncharted`, `find-address` (all present in `web/index.html`); `curl -sI …/app.js` → `server: nginx`, `cache-control: no-cache`, **no** `content-security-policy`/`strict-transport-security`/`x-frame-options` (E3 server half, recorded as blocked on owner — consistent); live `index.json` → 157 origins, `solveRes` 5, 7 attribution entries, no `railDetail`. `plan/…web-ui-detail.md:141` says "verified … by scripts/browser_verify.sh after deploy", while `plan/…build-robustness.md:126` (593c231) says the deploy was refused and "No files were copied"; `dist/index.html` (Sep 9 23:50, 20,381 B) predates every cycle-1 web commit (01:55–02:25), so `deploy_verify.sh:54`'s `rsync web/ dist/` never ran either.
- Failure scenario: production keeps rendering GeoNames/OurAirports/Nominatim strings through `innerHTML` unescaped (fixed at `web/app.js:31-32,596,600,615,700,716-728`), shows no visible disclaimer, credits neither GeoNames nor HydroLAKES (CC BY 4.0), and says "553 cities" against 157. A page-only deploy is safe by design — the new page reads `solveRes` (`app.js:63`), `railDetail` (`:483`), `modeDetail` (`:599`) and `attribution` (`:204-224`) defensively — but `deploy_verify.sh` has no way to ship `web/` without re-checking a `dist/` that VER-25 makes unshippable.
- Fix: a `--page-only` mode in `deploy_verify.sh` (rsync `web/` minus `README.md` to the server, no `--delete`, no `dist/` gate, then `browser_verify.sh`); reword the web plan's completion line to "verified on the local preview; not deployed".

#### VER-29 — CLAUDE.md's band-separation rule is not what the shipped ramps satisfy, and CLAUDE.md was not reworded as D20 says
- Severity Medium (a standing policy line contradicts the measured artefact) · Confidence High · Status **Confirmed** · Effort S
- `CLAUDE.md` ("Adjacent bands need OKLab ΔE of roughly 8; below that they read as one mass"), `scripts/check_ramps.py:16-20`, `web/app.js:5-14,117-126`, `plan/2026-09-10-c1-docs-attribution-calibration.md:31-35`
- Evidence: `check_ramps.py` measures the eleven **anchors** (floor 6, OK for all 12 schemes: 6.5–8.9). A Python port of `expandRamp` (`app.js:117-124`) over 37 bands gives adjacent-band ΔE **min 1.80 / median 1.83–2.58 / max 2.68** across the twelve schemes (lightness still strictly monotonic in every one). `git log ac191db..HEAD -- CLAUDE.md` is empty, while the docs plan ticks D20 with "the comment in `app.js` and CLAUDE.md wording say 'anchors ≥ 6, target 8'". The web plan lists D20 again (cycle 3) for measuring the interpolated bands.
- Failure scenario: a future reviewer applies the rule as written to the 37 bands and either fails the page or, worse, "fixes" it by cutting the band count; meanwhile the rule that is actually enforced (anchors) lives only in a script comment.
- Fix: reword the CLAUDE.md line to the enforced rule (anchors ≥ 6 aiming at 8; the 37 interpolated bands are a gradient whose steps the legend ticks carry), or decide the 37-band ladder violates the policy and change it. One of the two, by the owner (CLAUDE.md is a standing policy).

### Low

#### VER-30 — `browser_verify.sh`'s `borders` check asserts the map canvas, not the borders layer
- Severity Low · Confidence High · Status **Confirmed** · Effort S
- `scripts/browser_verify.sh:26,31`; `web/app.js:399-411`
- Evidence: `borders:!!q(".maplibregl-canvas")` — the canvas MapLibre always creates; `canvas:!!q("#map canvas")` on the same line already asserts it. The layer is `map.addLayer({ id: "borders", … })` after an async `fetch("./borders.json")`. `plan/…build-robustness.md:47-48` ticks D14/FD-5 as "asserts on `borders`".
- Failure scenario: `borders.json` 404s or the layer insertion throws; the check still prints `"borders":true`.
- Fix: `borders: !!m.getLayer("borders") && m.queryRenderedFeatures({layers:["borders"]}).length > 0` inside the `window.__map` block (the same pattern the water check uses at `:37-42`).

#### VER-31 — E8 (cell-size figures) is recorded as done but three places still quote the h3 v3 sizes, and the JSON-LD hard-codes res-5 build counts
- Severity Low · Confidence High · Status **Confirmed** · Effort S
- `web/index.html:46`; `src/transport_maps/graph/refine.py:3,7`; `src/transport_maps/contour/bands.py:148-153`; `src/transport_maps/emit/tiles.py:17`; `plan/2026-09-10-c1-docs-attribution-calibration.md:49-51,80`
- Evidence: `config.py:11-16`, `web/llms.txt:26-27`, `web/app.js:57-58` say 6.5 km / 36 km² and 2.4 km / 5.2 km² (h3 v4 averages, `e11c830`); `index.html:46` (JSON-LD `measurementTechnique`) says "resolution 6 (5.6 km across), refined to resolution 7 (2.1 km)", `refine.py:3,7` "5.6 km … 2.1 km", `bands.py:148-149` "5.6 km … 2.1 km", `tiles.py:17` "2.1 km". The docs plan lists E8 unticked under Cycle 2 (`:49-51`) and "E8 … (e11c830)" as done under Progress (`:80`). The same JSON-LD line hard-codes "3,983 airports, 57,286 rail stations and 5,672 ferry crossings" — res-5 build facts (the airport count changes with `bf9e5cc`'s snap) — although the city count was made count-free for exactly this reason (E1 page half, `index.html:15,23,31,41`).
- Fix: update the four comment/JSON-LD sites; make the JSON-LD counts count-free or generate them from `index.json`; tick or un-tick E8 consistently.

#### VER-32 — `index.json`'s `attribution` under-states what Natural Earth is used for
- Severity Low (attribution completeness) · Confidence High · Status **Confirmed** · Effort S
- `src/transport_maps/emit/index.py:41-46`; `README.md:56`; `src/transport_maps/emit/borders.py:19-20`; `src/transport_maps/sources/countries.py:25`; `src/transport_maps/sources/urban.py:38-39`
- Evidence: `borders.json` is built from `ne_10m_admin_0_boundary_lines_land.zip`, country codes from `ne_10m_admin_0_countries.zip`, the urban mask from `ne_10m_populated_places_simple.zip` — all Natural Earth. `README.md:56` (662f5d3, "correct the Natural Earth row") says "1:10m land polygons defining the H3 cell universe; country borders; populated places behind the urban mask"; `ATTRIBUTION[3]["usedFor"]` still says only "1:10m land polygons defining the H3 cell universe", and that is what `dist/index.json` will ship. `test_readme_documents_the_same_sources` compares names and licences only, so it cannot see this.
- Fix: bring `index.py:45` in line with the README row (and GeoNames `:63` with "cities15000" if that is wanted in the artifact).

#### VER-33 — The deploy copies dead vendor files to the server and caches them for a year
- Severity Low · Confidence High · Status **Confirmed** · Effort S
- `scripts/deploy_verify.sh:54-55`; `dist/vendor/g00.woff2 … g13.woff2`
- Evidence: `dist/vendor/` holds `g00.woff2`–`g13.woff2` (Sep 8 15:15, ~397 KB) that `web/vendor/` does not; `grep -rn "g0[0-9].woff2\|g1[0-9].woff2" web dist/*.html dist/*.js dist/vendor/*.css` finds no reference. `rsync -a --exclude 'README.md' web/ dist/` has no `--delete`, so anything ever removed from `web/` stays in `dist/`; the next line ships `dist/` with `--delete`, and `deploy/worldmap.atik.kr.conf:70-73` serves `.woff2` as `immutable, max-age=31536000`.
- Fix: rsync the page-owned subtrees with `--delete` (`web/vendor/ → dist/vendor/`) or enumerate the page files; the same lack of `--delete` is why a renamed `app.js` would leave its predecessor behind.

#### VER-34 — nginx's no-cache list omits `.css`
- Severity Low · Confidence High · Status **Confirmed** · Effort S
- `deploy/worldmap.atik.kr.conf:43-46`; `deploy/README.md:23-33`
- Evidence: the regex is `\.(html|js|json|txt|xml)$`; `vendor/maplibre-gl.css` and `vendor/fonts.css` fall through to `location /` with no `Cache-Control`, so browsers apply heuristic caching. `deploy/README.md:23` says every artifact except the fonts changes together and lists "html/js/json/txt/xml/bin/pmtiles".
- Failure scenario: the planned MapLibre patch (I2, security plan cycle 2) ships a new `maplibre-gl.js` while a visitor's cached `maplibre-gl.css` is the old one.
- Fix: add `css` to the regex and to the README's list.

#### VER-35 — `browser_verify.sh` kills every `agent-browser` process on the machine, not the one it opened
- Severity Low (operational; a concurrent reviewer's session dies) · Confidence High · Status **Confirmed** · Effort S
- `scripts/browser_verify.sh:88-92` (and `:18` `cd /tmp`, `:74,86` screenshots under `/tmp` — J5, docs plan cycle 2)
- Evidence: `/bin/ps -ax -o pid=,command= | grep -E "\.agent-browser/|agent-browser" | grep -vE "grep|Google Chrome\.app" | awk '{print $1}' | while read p; do kill -9 $p; done`.
- Failure scenario: the orchestrator runs the post-deploy check while the designer reviewer holds the single allowed browser session; the designer's daemon and Chrome tree are killed mid-check.
- Fix: record the daemon PID the script started (or use the CLI's own session/close-all for its session only) and kill that tree.

#### VER-36 — The deploy consistency gate does not require `{slug}.json` nor pair `.rail.json` with `.rail.bin`
- Severity Low · Confidence High · Status **Confirmed** · Effort S
- `scripts/deploy_verify.sh:16-27,36`; `web/app.js:483-488,512-519`
- Evidence: the loop checks `.bin .air.bin .modes.bin .rail.bin` and `.pmtiles`; the summary line then prints "every origin has pmtiles + bin + air.bin + modes.bin". `app.js:512` fetches `./origins/{slug}.json` (routes, node offsets that must come from the same index as `.air.bin`) and `:483-488` needs both `.rail.bin` and `.rail.json` or silently shows no station.
- Fix: add `.json` as required; when `.rail.bin` exists require `.rail.json`.

#### VER-37 — Comments still quote res-5 "today" figures after the res-6 move
- Severity Low · Confidence High · Status **Confirmed** · Effort S
- `src/transport_maps/graph/nodes.py:32` ("25 of 4,008 today"), `src/transport_maps/validate.py:14` ("9 of 3,983 today"), `tests/graph/test_build.py:117,132` ("124 today, all downstream of the 25 dropped airports"; "9 of 3,983"), `src/transport_maps/emit/airports_json.py:3` ("3,983 rows"), `src/transport_maps/emit/modes.py:9` ("57,286 stations"), `src/transport_maps/sources/roads.py:100,111` (res-5 cell size, "548,557 cells")
- Evidence: the captured log of a cycle-1 full run at res 6 (`scratchpad/full_suite.log:132-134`) shows `64 of 4008 scheduled-service airport(s) dropped` and `dropped 528 of 68152 route pair(s)` (both still under their 2 % bounds: 80 and 1,363), the figures `bf9e5cc` quotes. `nodes.py:32` was not updated by `bf9e5cc` although `:162` in the same function now says 64.
- Fix: re-measure after the rebuild and update, or phrase them as "at res 5, Sep 2026".

#### VER-38 — H2 is half-done by `bf9e5cc` without the plan saying so
- Severity Low (bookkeeping; the other half is a real per-origin cost) · Confidence High · Status **Confirmed** · Effort S
- `plan/2026-09-10-c1-build-robustness.md:79-83`; `src/transport_maps/emit/hover.py:28,31-56`, `itinerary.py:58,66`, `modes.py:90,96`, `rail_detail.py:86,94`
- Evidence: H2 asks to hoist `stop_names`/`_line_between` (done: `rail_detail.lookup_tables`, `cli.py:184-185`) **and** the hover parents / representative children. Each of the four emitters still recomputes `sorted({h3.cell_to_parent(c, HOVER_RES) for c in idx.cells})` and `_representative_children(...)` per origin — four Python passes over ~10 M cells per origin, each building its own `cell_pos` dict (`hover.py:41`).
- Fix: compute `parents` and `_representative_children` once per origin (they depend on `minutes` only through the water-centre fallback) or at least share `parents`; tick the rail half of H2 with the commit.

### Recorded, not new (cycle-1 aggregate IDs, one line each)
- **W1** — the fork `DeprecationWarning` from `tests/test_cli.py::test_a_gate_failure_in_a_forked_worker_aborts_the_run` (see the warnings row above); already in the gates plan with its exit criterion.
- **I4 / c1-VER-20** — `dist/origins/las-vegas.pmtiles-journal` (Sep 9 07:03) is still there and still not excluded from the deploy rsync.
- **E1 (data half)** — the served build is 157 origins at res 5 (known; VER-25 is the *additional* mixing).
- **E3 (server half)** — live headers still carry no CSP/HSTS/XFO (confirmed by `curl -sI`; blocked on owner).
- **F4b** — confirmed again with the file list: this gate run wrote nine `rail_routes-*/ferry_links-*` parquet files into the real `data/cache/` at 04:57:38 (`osm.py:153,183` cache into `config.CACHE`; the extracts fixture in `tests/sources/test_osm.py:22-34` uses `tmp_path` only for the PBFs). Until F4b lands, every `uv run pytest` is a write under `data/`.
- **A6a–d, A7, G1, C5, D17, J5** — unchanged; no new evidence.

## Plan-claim audit

Verdicts: **Verified** (commit + code + test read; mutation plausible from the test body), **Partial**, **Not found**. "Mutation" says whether the named mutation would plausibly make the test red, from reading the test (mutants I actually ran are in the gate table).

### `plan/2026-09-10-c1-build-robustness.md` (cycle 1)
| Task | Commit | Code / test | Verdict |
| --- | --- | --- | --- |
| A3 forked gate failure aborts | `b030d38` | `cli.py:85-95` (`GateFailure(RuntimeError)`), `:104-108`, `:205-222`; `tests/test_cli.py:196-225` forks 2 workers under a 30 s alarm and expects `SystemExit("second")` | **Verified**. Mutation (restore `raise SystemExit` in the worker) → `imap` blocks → alarm → `TimeoutError` → red. |
| A5 urban downloads its own archive | `599dc60` | `sources/urban.py:38-58` (`PLACES_URL`, `_download` via `_atomic_write`), key at `:76-77`; `tests/sources/test_urban.py:96-138` | **Verified**. Mutations named in the plan are both observable by the two tests (TypeError; glob count 2 → 1). |
| A8 empty universe → 0.0 | `be2cc94` | `validate.py:42-43`; `tests/test_validate.py:251-265` | **Verified**. Dropping the guard → `NaN` → `== 0.0` fails. |
| A4 mixed-grid ferry adjacency | `b38fb8b` | `graph/refine.py:66-83`, `build.py:308`, `emit/modes.py:69`; `tests/graph/test_ferry.py:134-194`, `test_refine.py:45-66` | **Verified**. Same-resolution-only → fine/base pair not adjacent → duplicate pair → `build_graph` raises in `:176`. |
| E1 verify half | `cea16ca`, `4d74cbe` | `browser_verify.sh:7-17` reads `origins`/`bandEdgesMin` from the deployed `index.json`; `SCHEMES=12` one variable; `deploy_verify.sh:39-51` greps `[0-9]{3} (cities|departure)` | **Verified** (the grep would not catch "553 origin cities"; the page currently states no number). |
| D14/FD-5 visible disclaimer + borders | `cea16ca` | `browser_verify.sh:26,33` (`.disclaimer` + `offsetParent`), `:26,31` (`borders`) | **Partial** — disclaimer yes; `borders` is the canvas (VER-30). |

### `plan/2026-09-10-c1-docs-attribution-calibration.md` (cycle 1)
| Task | Commit | Code | Verdict |
| --- | --- | --- | --- |
| E2 attribution | `662f5d3`, `d84217f`, `e11c830` | `README.md:59-60`; `llms.txt:56-57`; `index.html:59` (`conditionsOfAccess`), `:468-471`; `app.js:204-224` (`PAGE_CREDITS`), `:912-915` Nominatim credit | **Verified** in the repo; not live (VER-28); `index.json` row wording VER-32. |
| E5 llms.txt consistent | `e11c830` | `llms.txt:16-17,26-37,53-58` | **Verified**. |
| E7 web/README + deploy/README | `e11c830`, `03988a5` | `web/README.md:8-14,47-57,61`; `deploy/README.md:9-11,23-35` | **Verified**. |
| E9 stale comments/constants | `fa89fbc`, `e11c830` | `config.py:11-20`; `hover.py:7-9`; `modes.py:84-88`; `itinerary.py:50-56`; `app.js:57-63`; no `band-seams`; `transfers.py`/`test_transfers.py`; `__init__.py`; `routes_json.py` | **Verified** (one "Task 9" survives outside the listed sites: `build.py:380`). |
| E12 README claims | `e1b9558` | `README.md:24-29,63-78` | **Verified**. |
| D20 one threshold | `e11c830` | `app.js:5-14,69-73`; `check_ramps.py:16-20` | **Partial** — CLAUDE.md untouched (VER-29). |
| E8 (claimed in Progress `:80`, unticked at `:49`) | `e11c830` | `config.py`, `llms.txt`, `app.js` yes; `index.html:46`, `refine.py`, `bands.py`, `tiles.py` no | **Partial** (VER-31). |

### `plan/2026-09-10-c1-gates-and-tests.md` (cycle 1)
| Task | Commit | Code / test | Verdict |
| --- | --- | --- | --- |
| F14 ruff clean | `a3f918f` | — | **Verified at a3f918f, regressed at bf9e5cc** (VER-24). |
| F1a landmask bound by resolution | `990febe` | `tests/sources/test_landmask.py:14-28` | **Verified**. Mutation: a `SOLVE_RES` patch changes both the fixture and the bound; the res-6 fixture against the res-5 bound fails on 4,091,715. |
| F1b `idx.cell_at` in test_build | `6f63764` | `tests/graph/test_build.py:61-67` | **Verified**. |
| F1c/E2 README rows | `662f5d3` | `tests/emit/test_index.py:83-90` checks every `ATTRIBUTION` name **and** licence string in README | **Verified**, non-vacuous (drop "HydroLAKES" from README → red). |
| F12 no `or True` | `84fb110` | `tests/contour/test_bands.py:231-283` asserts each uncovered parent sliver is in band 5 **and not** in band 0 | **Verified**. Mutation `np.maximum.at → np.minimum.at` flips the second assertion. |
| F2 centre-child fixtures at SOLVE_RES | `498b971` | `tests/emit/test_hover.py:16-24,35-40,51-81` | **Verified**. Min-over-children → `values[PARENT] == 20` fails (10) and `== 40` fails (10). |
| F13/TE-23 marker + addopts | `00f40e4` | `pyproject.toml:38-44`; `tests/contour/test_bands.py:127` | **Verified**. |
| F13/TE-22 `__init__.py` | `00f40e4` | `tests/cli/__init__.py`, `tests/web/__init__.py` present | **Verified**. |
| Full suite recorded | `3e393b5` | plan `:111` (251 passed, 4 deselected, 16 min 42 s) | **Verified** as recorded; this cycle's run in the gate table. |

### `plan/2026-09-10-c1-security-and-policy.md` (cycle 1)
| Task | Commit | Code | Verdict |
| --- | --- | --- | --- |
| I1 escape before innerHTML | `f943964` | `app.js:31-32` (`esc`), used at `:596,600,615,700,716-720,728`; Nominatim results via `textContent` `:906-909`; labels via `textContent` `:251` | **Verified** (repo; not live, VER-28). |
| E3 repo half | `03988a5` | `deploy/worldmap-security-headers.conf`, included at `worldmap.atik.kr.conf:29,41,45,52,64,72`; CSP hosts match `app.js:874` and `index.html:5`; inline-script hash **recomputed = `pCkIJ0WqstDvWvix9v7v2C15fx9jgy6oPf71TIqllqU=`, matches** | **Verified**. Server half: live headers absent (blocked on owner, as recorded). |
| E4 bounded (explicit search) | `1305ba7` | `app.js:869-917,968-973,990`; `index.html:398` | **Verified**. |
| E4 docs | `e11c830`, `d84217f` | `web/README.md:10-14`; `llms.txt:60-63`; `index.html:59` no single-licence claim | **Verified**. |

### `plan/2026-09-10-c1-web-ui-detail.md` (cycle 1, twenty tasks)
| Task | Commit | Code (web/) | Verdict |
| --- | --- | --- | --- |
| D1 font shorthands | `a261141` | `index.html:197,205,227,272` (`font-family:inherit;font-weight;font-size;line-height`) | **Verified** (computed-style check is the designer's lane). |
| D2 label typeface + shadow | `a261141` | `index.html:245-249` | **Verified**. |
| D3 names on opening view | `f943964` | `app.js:269` (18 labels from zoom 1.2), `:521` lands at zoom 1.9 | **Verified** (DOM count not checked here). |
| D4+E4 Enter/arrows/explicit search | `1305ba7` | `app.js:965-990` | **Verified**. |
| C4 legend ticks on true edges | `b7da35f` | `app.js:172-199` (`data-min = EDGES[i]`, label = that edge's hours, ≥ 3 bands apart) | **Verified**. |
| C6 keys for grey and sea | `b7da35f` | `index.html:366-369`; `app.js:165-168` | **Verified**. |
| D5 route copy | `d84217f` | `index.html:408-412` | **Verified**. |
| D6 `--text-3` contrast | `a261141` | `index.html:91-93`; **measured 6.13:1** on `--surface`, **4.75:1** on the 86 % scrim over the brightest muted band (4.69 over mono's) | **Verified**. |
| D7 focus-visible | `a261141` | `index.html:208,251,265-266,283-284` | **Verified**. |
| D9 color-scheme | `a261141` | `index.html:96` | **Verified**. |
| D10 reduced motion | `f943964`, `662f7d5` | `app.js:414-415` (`moveTo`), `:995`, `:1117-1121`; no bare `flyTo` remains | **Verified**. |
| D18 no weight 300 | `a261141` | no `300` in `index.html`; `fonts.css` 400/500/600 | **Verified**. |
| C7 loading vs water | `d84217f`, `662f7d5` | `app.js:552-559,714-718` | **Verified**. |
| C10 location on request | `f943964` | `app.js:1097-1126`; `index.html:393` | **Verified**. |
| C12 modeDetail/railDetail fallbacks | `f943964`, `c70c77a` | `app.js:130-137,483,599`; `emit/index.py:129-131`; `tests/emit/test_index.py:76-80` | **Verified**. |
| D14 visible disclaimer | `d84217f` | `index.html:371` | **Verified**. |
| D12 door to door everywhere | `d84217f` | `index.html:370`; `app.js:650,728,760` | **Verified**. |
| E1 page half | `d84217f` | `app.js:225`; `index.html:15,23,31,41-42,411,466` | **Verified** (JSON-LD still hard-codes airport/station/ferry counts, VER-31). |
| C2 copy half | `d84217f` | `app.js:639-643` | **Verified**. |
| C9 loud load failures | `f943964`, `7cd7d63` | `app.js:37-52,54,67` | **Verified**. |
| Progress line "verified … by scripts/browser_verify.sh after deploy" | — | — | **Not found**: no deploy happened (VER-28). |

## Docs vs code vs artefacts

| Claim | Where | Verdict | Evidence |
| --- | --- | --- | --- |
| "from 550+ cities" | `README.md:5` | Holds for the repo (553 `[[origin]]` in `data/origins.toml`); E1 for the served build | `grep -c '^\[\[origin\]\]' data/origins.toml` → 553 |
| "H3 resolution 6, refined to 7 in dense regions" | `README.md:27-28`, badge `:11` | Holds | `config.py:13,17`; `refine.py:28-31` |
| Attribution table vs `emit/index.py:ATTRIBUTION` | `README.md:51-61` | Names and licences identical (9 rows); `usedFor` differs for Natural Earth and GeoNames | VER-32 |
| `dist/index.json.attribution` vs `ATTRIBUTION` | `dist/index.json` | 7 vs 9 entries (no GeoNames, no HydroLAKES) — the served build predates `662f5d3` (E1); the page adds them itself (`app.js:204-224`) once deployed | read of `dist/index.json`; live `index.json` also 7 |
| "`build-all` does not produce `water.pmtiles`" | `README.md:40-43` | Holds | `cli.py` never writes it; `scripts/build_water_tiles.py` exists |
| "no provider fingerprint reaches `dist/`" | `README.md:73-75` | Holds (test exists; ran in the suite) | `tests/test_licence_firewall.py` |
| Twelve schemes × eleven anchors, interpolated to 37, anchors ≥ 6 aiming at 8, `test_ramps.py` runs it | `web/README.md:47-57` | Holds | `app.js:74-85` (12 × 11), `N_BANDS` from `bandEdgesMin` (36+1); `check_ramps.py:20`; `tests/web/test_ramps.py:9-14` |
| Pinned versions 5.24.0 / 4.5.0 / 4.2.1 / 0.8.3 | `web/README.md:21-26` | Holds | version strings in the four vendored files |
| Fonts latin 400/500/600, no CDN | `web/README.md:61`, `index.html:79-84` | Holds | `vendor/fonts.css`; three `.woff2` present and served (`font/woff2`) |
| "Two runtime calls … Nominatim and the Google tag" | `web/README.md:10-14`, `llms.txt:60-63`, `index.html:449-452` | Holds | `app.js:874,890,924`; `index.html:5-11`; nothing else leaves the origin |
| 4,091,715 res-6 cells, 36 km² / 6.5 km; res 7 5.2 km² / 2.4 km; 37 bands 30 min → 72 h | `llms.txt:16-17,26-27` | Holds | `config.py:11-28` (edges 30 … 4320) |
| "37 continuous bands at four levels of detail" | `index.html:42` | Holds | `contour/bands.py:161-166` (4 `LODS`) |
| "resolution 6 (5.6 km across) … resolution 7 (2.1 km)" | `index.html:46` | **Fails** (h3 v3 figures) | VER-31 |
| "3,983 airports, 57,286 rail stations, 5,672 ferry crossings" | `index.html:46` | Res-5 build facts; will be wrong after the rebuild | VER-31 |
| "calibrated against 2,998 real driving journeys", "107,366 ADS-B legs" | `index.html:42,46`, `llms.txt:6-8` | Holds | `graph/ground.py:17` ("FITTED against 2,998 real driving journeys"); `calibration.toml:14` `sample_size = 107366` |
| "Coverage is about 98% of land" | `llms.txt:43` | **Unverifiable** here (no build output states it; the gate is 90 %, `validate.py:7`) | — |
| `conditionsOfAccess` mixed-licence text; `isBasedOn` nine sources | `index.html:48-59` | Holds | matches `ATTRIBUTION` |
| `deploy_verify.sh` steps as described | `deploy/README.md:3-13` | Holds | `deploy_verify.sh:8-62` |
| `browser_verify.sh` checks as described | `deploy/README.md:15-19` | Holds, except "the coast layer … borders" — borders is vacuous | VER-30 |
| Security headers included in every location; CSP matches the page; hash recompute instructions | `deploy/README.md:37-62` | Holds; hash verified | `worldmap.atik.kr.conf:29,41,45,52,64,72`; sha256 recomputed = conf |
| "no-cache on html/js/json/txt/xml/bin/pmtiles" | `deploy/README.md:32` | Holds as listed; `.css` is not in the list | VER-34 |
| `web/` vs `dist/` copies | — | `app.js`, `index.html`, `llms.txt`, `sitemap.xml` differ **only** by the cycle-1 commits (`a261141 … 7cd7d63`, plus `sitemap` lastmod 09→10); `preview.png`, `robots.txt` identical; `README.md` absent from `dist/` by design; `dist/vendor/` has 14 extra `g*.woff2` | `diff web/… dist/…`; VER-33 |

## Served preview (curl only, `http://127.0.0.1:8899/`)

`Server: SimpleHTTP/0.6 Python/3.14.3` with `Accept-Ranges: bytes`, `Cache-Control: no-cache`, `Access-Control-Allow-Origin: *`. Page files come from `web/` (sizes match `web/`, cycle-1 markers present); data from `dist/`.

| Path | Status | Content-Type | Bytes |
| --- | --- | --- | --- |
| `/`, `/index.html` | 200 | text/html | 24,316 (= `web/index.html`) |
| `/app.js` | 200 | text/javascript | 50,447 (= `web/app.js`) |
| `/index.json` | 200 | application/json | 11,754 (157 origins, res 5, 7 attribution) |
| `/hover_cells.bin` | 200 | application/octet-stream | 725,920 (90,740 × 8) |
| `/origins/seoul.pmtiles` with `-r 0-99` | **206** `Content-Range: bytes 0-99/27846999` | application/vnd.pmtiles | 100 |
| `/water.pmtiles` with `-r 0-99` | **206** | application/vnd.pmtiles | 100 (867,184,193 total) |
| `/origins/seoul.bin`, `.air.bin`, `.rail.bin` | 200 | octet-stream | 181,480 each (90,740 × 2) |
| `/origins/seoul.modes.bin` | 200 | octet-stream | 1,088,880 (90,740 × 12) |
| `/origins/seoul.json`, `.rail.json` | 200 | application/json | 527,470 / 182,987 |
| `/places.json`, `/airports.json`, `/borders.json` | 200 | application/json | 1,778,047 / 258,922 / 1,278,586 |
| `/vendor/maplibre-gl.js`, `pmtiles.js`, `h3.js`, `fflate.js` | 200 | text/javascript | 1,053,810 / 15,088 / 192,440 / 32,472 |
| `/vendor/maplibre-gl.css`, `fonts.css` | 200 | text/css | 70,024 / 727 |
| `/vendor/ibm-plex-sans-latin-{400,500,600}-normal.woff2` | 200 | font/woff2 | 22,588 / 24,184 / 24,252 |
| `/llms.txt`, `/robots.txt`, `/sitemap.xml`, `/preview.png` | 200 | text/plain, text/plain, application/xml, image/png | 3,920 / 69 / 250 / 175,451 |
| `/favicon.ico` | 404 | — | (browser auto-request only; nothing in the page asks for it) |

Everything the page requests (`app.js:1-3,229,371,399,463,484-485,489,504,508,512,821,890,924`; `index.html:5,77-85,477`) is served, except the two external hosts (Nominatim, Google tag). `.rail.bin/.rail.json` are only requested when `index.json` has `railDetail` (`app.js:483`), which the served one does not. The 206 responses mean PMTiles range reads work on this preview (the `http.server` caveat in `web/README.md:43-45` does not apply to this custom handler). The data it serves is the mixed build described in VER-25.

## Scripts

`scripts/deploy_verify.sh` (read line by line): step 1's widths — `.bin` 2 B (`hover.py:67-69` `<u2`), `.air.bin` 2 B (`itinerary.py:71` `<u2`), `.modes.bin` 12 B (`modes.py:24,99`: 6 channels × `<u2`), `.rail.bin` 2 B (`rail_detail.py:108` `<u2`) — all correct; `hover_cells.bin` 8 B (`index.py:40` `<u8`) correct. Required extras `places.json airports.json borders.json water.pmtiles` exist. Missing from the gate: `{slug}.json`, `.rail.json` pairing (VER-36). Step 1b's grep is `[0-9]{3} (cities|departure)` on `web/index.html` (VER-comment in the audit). Step 2 copies without `--delete` (VER-33). Step 3 curls eight files and two range requests on the live host.

`scripts/browser_verify.sh`: every selector exists in `web/index.html`/`web/app.js` — `#map canvas` (`index.html:352`), `.results button` (`app.js:838,852`), `.tints span` (`app.js:162`), `.keys .sw` (`index.html:367-368`), `#ramps button` (`app.js:1015`), `.disclaimer` (`index.html:371`), `window.__map` (`app.js:350`), layers `water`/`bands` (`app.js:372,465`), `#legs .ap`/`.mode` with `data-tip` (`app.js:596,600`), `.results .addresses button[data-geo]` (`app.js:882,903`), `#q` Enter → `searchAddress` when no local match (`app.js:968-973`; "Gangnam-daero, Seoul" matches no city or airport), `.lbl.origin` click → `paintOrigin` (`app.js:249-259`), `.reading .rail .mast #compass #tints #time`. Counts: `TINTS = bands + 2` = 37 spans + 2 keys — matches. Vacuous: `borders` (VER-30). Fragile: `:65` clicks the first `.lbl.origin` in DOM order at zoom 4.6 over Japan and then asserts the source is no longer Seoul — fails if that label is Seoul's. Process cleanup kills all `agent-browser` processes (VER-35). `cd /tmp` and `/tmp` screenshots: J5.

`scripts/check_ramps.py`: run output in the gate table; `MIN_DELTA_E = 6.0` on anchors; `--respace` rewrites `web/app.js` in place (J6, deferred). Interpolated-band figures: VER-29.

## Regression sweep on `bf9e5cc`

Claims in the message, each checked:

| Claim | Verdict | Evidence |
| --- | --- | --- |
| "The rail-detail writer sorted and grouped a polars frame inside each forked worker" | Holds | the removed lines in the diff: `lines = _line_between(routes)` and the `zip(routes["lat"], …)` loop inside `write_rail_detail`, which `_solve_one` calls in the worker (`cli.py:123`) |
| "polars' thread pool does not survive fork() … sat for three hours with eight idle processes" | Likely, unverifiable | no log of that run exists in any scratchpad; `cli.py:5-9` already sets `POLARS_MAX_THREADS=1` for the same reason and `validate.py:147-148` documents the same deadlock |
| "The lookup tables are now built once in the parent and workers receive plain dicts" | Holds | `cli.py:184-185` (`shared["rail_tables"] = rail_detail.lookup_tables(rail_routes)` before the pool); `rail_detail.py:61-77,89-92`; `polars` no longer imported on the worker path except `countries.py` (parent-only via `cell_country`) — `grep` over contour/emit/validate/solve |
| "64 of 4,008 airports had no land cell at resolution 6 (25 at resolution 5)" | Holds | `scratchpad/full_suite.log:132`: `64 of 4008 scheduled-service airport(s) dropped`; `nodes.py:32` still says 25 (res 5) |
| "it now snaps to the nearest indexed cell within two rings" | **Partial** | works only where the nearby land is unsplit (VER-26); "nearest" untested (VER-27) |
| Test `test_lookup_tables_are_plain_dicts_a_fork_can_use` | Passes (3 passed in 0.65 s with its module); **does not test the fork claim** (m4 green, m3 red) | VER-27 |
| Test `test_an_airport_off_the_mask_snaps_to_the_nearest_land_cell_within_two_rings` | Passes (5 passed in 0.50 s with its module); tests the ring-2 search (m1 red), **not "nearest"** (m2 green), and cannot see split neighbours | VER-26, VER-27 |
| Lint | **Fails** | VER-24 |

Other observations on the diff: `tables and tables.get("lines") is not None and len(idx.stations)` (`rail_detail.py:89`) — `lookup_tables(None)` returns `{"lines": {}, …}`, so a rail-less build with stations would enter the branch and emit an all-`NO_RAIL` array, which is harmless (`build_index(rail_routes=None)` has no stations). `_nearest_land` returns as soon as ring 1 has any hit, so a ring-2 cell that is nearer than every ring-1 cell cannot win — acceptable for the stated "a few kilometres" purpose but not "nearest" in the strict sense.

## Final sweep — what I could not verify, and why

- The three-hour hang of the first 553-origin build (`bf9e5cc`'s motivation): no log survives; taken as the author's observation.
- Browser-level checks in the web plan (computed font family, label count after load, tick `data-min` in the DOM, tooltips, console): I hold no browser session by the run's rules; all are verified at the code level only.
- "Coverage is about 98% of land" (`llms.txt:43`): no artefact states the measured coverage; the build log of the running rebuild will.
- The airport-snap impact numbers (VER-26) come from a script that reproduces `build_index`'s decisions from the caches (`land_cells_r6_dd95e3b5.parquet`, `airports_c35abade.parquet`, `road_class_grid_495d9dd1.npy`, the populated-places zip) rather than from running `build_index`, to avoid the memory of a full index beside the running build; the split decision it recomputes is `refine.dense_mask(roads.cell_class(cells), urban)` exactly as `nodes.py:138`. It counts 58 off-mask airports where the cycle-1 log (a run against an earlier stamp) counted 64; I did not chase the six, since the finding is about the ring lookup, not the count.
- The gate run itself wrote nine small parquet files under `data/cache/` (listed in the gate table) — a property of the suite (F4b), not an action of this review; nothing under `dist/` or `data/build/` was written.
- Everything under `real_multi_band` and `network` stayed deselected (default `addopts`); the deselected count is in the gate table.
- I did not open, stop or inspect the running build beyond `ps` and file mtimes under `dist/`.
