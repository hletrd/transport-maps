# Plan (cycle 2): build correctness, artifact integrity, deploy and verification scripts

Source findings: `.context/reviews/_aggregate.md` sections K, L, R, S2–S5, plus
every unfinished task carried from
`plan/archive/2026-09-10-c1-build-robustness.md` (A6a–e, A7, A9, A10, A11, A12,
A13, A14, A15, A16, A17, A18, G1, G2, H2, H10, I4/VER-20, E15). Per-agent detail:
`tracer.md` (T3–T8), `architect.md` (§3, §4), `code-reviewer.md`, `verifier.md`,
`debugger.md`, `perf-reviewer.md`, `security-reviewer.md`, `test-engineer.md`,
`feature-dev-code-reviewer.md`.

Orchestrator constraint (unchanged): rebuild16 (`build-all`, 553 origins) is
running and writes into `dist/origins` in place; do not start, stop or re-run it,
do not run `build-all` or `scripts/build_water_tiles.py`, do not delete or rewrite
files under `dist/` or `data/`. Source edits do not affect the running process
(it has imported its modules; forked workers inherit the parent's code), so every
task below lands in the tree now and takes effect on the *next* build. Tasks that
change a cache key make the next build recompute that cache once; each says so.

## Cycle 2 (this run)

The airport snap (bf9e5cc) and its tests
- [x] **K1** `_nearest_land` also considers the `FINE_RES` children of a ring
      cell that is absent from `cell_pos` but present in the split set, ranked
      by distance to the airport; ring 1 and ring 2 candidates are compared by
      distance, not first-found (`graph/nodes.py:114-128,154-173`). Refresh the
      docstring ("two rings ≈ 13 km"; the counts) and `nodes.py:30-36`.
      Test (**K2**): a fixture with a split ring-1 neighbour (children only) and
      an unsplit ring-2 cell → the nearest child wins; an off-centre probe with
      two ring-2 candidates → the nearer wins. Mutation: revert to the current
      lookup → the child case returns the ring-2 cell → red.
- [x] **K2 (rail half)** `test_write_rail_detail_never_touches_polars`: monkeypatch
      `rail_detail.pl` to raise and call `write_rail_detail` on the two-cell
      fixture (VER-27). Mutation: build a `pl.DataFrame` in the writer → red.

Worker failure, locks, logging
- [x] **K3** Consume the pool with `it.next(timeout=…)` in a loop; on
      `TimeoutError`, check `[p for p in pool._pool if p.exitcode not in (None, 0)]`
      (or count live workers) and abort with a message (TR-1). Test: a worker
      that `os.kill(getpid(), SIGKILL)`s under a 30 s alarm → `SystemExit`, not
      a hang. Mutation: remove the liveness check → alarm fires → red.
- [x] **K4** `dist/.build.lock` opened `O_CREAT|O_EXCL` with pid and start time,
      removed in `finally`; a stale lock whose pid is dead is reported, not
      reused; `Pool(initializer=_watch_parent)` starts a daemon thread that
      `os._exit(1)`s when `os.getppid()` changes; `_build_all` warns loudly when
      other `transport-maps build-all` processes exist (PR-6, TR-9, ARCH-1).
      `deploy_verify.sh` refuses while the lock exists or `pgrep` finds a build.
      Test: second `_build_all` against a held lock → `SystemExit`. Mutation:
      drop the `O_EXCL` → green → red.
- [x] **K5** `logging.basicConfig(level=INFO, format="%(levelname)s %(name)s:
      %(message)s")` in `cli.main` (workers inherit it); the snapped list at
      WARNING with distances; bound `len(snapped)` (5 %) beside the dropped
      bound (CR-4, TR-3). Test: the snapped bound aborts. Mutation: drop the
      bound → red.
- [x] **K8** `if m > cap: raise RuntimeError(...)` before writing past capacity
      in `hex_edges` and `native_edges` (FD-4). Test: a fixture whose cap is
      forced below its edge count raises with the message. Mutation: remove
      the check → `IndexError` (different type) → red.
- [x] **K9** `rail_detail`: raise when `len(table) >= NO_RAIL` (TR-10).
- [x] **K10** `load_origins` raises on an empty list (CR-14); page half in the
      web plan.
- [x] **K6** `check_bands_cover` pull-in in an unwrapped frame for
      antimeridian-straddling cells (or test their raw vertices) (DBG-2). Test:
      the Chukotka cell `860d9100fffffff` with a synthetic single band passes.
      Mutation: restore the planar interpolation → red.
- [x] **A13** Clamp emitted minutes to 65,534 and treat 65,534 as unreachable on
      both sides (`hover.py:23,67-69`, `modes.py:28`, `app.js:534`); a
      `routes.json` leg ≥ 65,535 is refused by the emitter (TR T7).

Atomic writes and the next build's identity
- [x] **L2 / A6a (pmtiles)** `tiles.write_pmtiles` and `water.build` copy the
      local staged file to `out.parent / f".{out.name}.tmp"` and `os.replace`
      it; `finally` removes the temp (CR-2, TR-6, ARCH-2). Test: monkeypatch
      `os.replace` to record its source → it lies in `out.parent`. Mutation:
      restore `shutil.move` → the source is under `$TMPDIR` → red.
- [x] **A6a (arrays)** `hover.py`, `itinerary.py`, `modes.py`, `rail_detail.py`,
      `routes_json.py` and `index.py` write through `_atomic_write` (moved to
      `transport_maps/_io.py` with public names; `_params_hash` too). Test: an
      inner write that raises after the temp file exists → target absent, no
      `.tmp` left. Mutation: `out.write_bytes` directly → truncated target → red.
- [x] **S1 (S parts) / A6c (identity)** `write_index` adds `buildId`
      (`inputs_hash-startUTC`), `builtAt`, `hoverCellCount`, `modeChannels`
      (from `modes.CHANNELS`), `graph: {rail, ferry}` (ARCH-12); the page
      prints `builtAt` when present (web plan O4). Sidecars and staging: cycle 3.
- [x] **H10 / R6** tippecanoe input in one named LOCAL scratch directory
      (deliberately not `data/build/tmp/`: tippecanoe's sqlite output is
      unreliable over the NFS mount, and the input is read once), named with
      the writer's pid, deleted as soon as tippecanoe has read it and in
      `finally`; the start-up sweep removes only files whose writer is gone,
      so it cannot touch another build; threads capped through
      `TIPPECANOE_MAX_THREADS` (PR-7).
- [x] **L11** tippecanoe runs with `cwd` set, relative paths and `-n <slug>`
      `-N` so no local path reaches the served metadata (CRIT-17).
- [x] **A7** Delete the `solve` and `index` subcommands; add `build-all --only
      slug,…` that runs the same `_solve_one` with every gate and leaves
      `index.json` untouched (ARCH-10; design in `architect.md` §4 A7). README
      updated. Test: `--only x` on the stub pipeline → `index.json` untouched.
      Mutation: publish anyway → red.
- [x] **A17 / Q7** `load_origins` applies `_SLUG_RE.fullmatch` (leading `-`
      excluded) to every slug; `expand_origins.py` imports the same regex,
      writes names with `json.dumps` and falls back to the GeoNames id for a
      slug that would collapse (SEC-26, ARCH-14, DBG-9).

Cache provenance (CLAUDE.md rule; each key change recomputes that cache once
on the next build)
- [x] **G1 / P7** `routes.parquet` keyed on `_params_hash(airports table stamp,
      _SANITY_PAIRS, cargo regex, _SKIP_PREFIXES, PARSER_VERSION)` with a
      documented legacy adoption: when the stamped file is absent and the bare
      `routes.parquet` exists, use it and print a WARNING naming the stale
      inputs (a re-crawl of Wikipedia is not something the build may start
      silently); `urban_mask` on the full cell-list hash + `PLACES_URL`;
      `ferry_links` includes `ANTIMERIDIAN_EPS_DEG`, `MIN/MAX_FERRY_KM`;
      `road_class_grid` includes `GRIP4_URL`; the land-cell stamp names the
      polyfill method and `_cells_touching` is deleted; the per-item parsed
      caches (`airline_destinations.json`, `wikidata_iata.json`) carry a
      `PARSER_VERSION` stamp (TR-12). Tests: one parametrised "path moves" case
      per constant per stamp; `urban_mask` same-length/same-ends/different-middle
      → two files; `routes` path carries a stamp. Mutation: revert each key.

Deploy and verification scripts (`scripts/deploy_verify.sh`,
`scripts/browser_verify.sh`, `deploy/`)
- [x] **L4 / F9** Step 1 becomes `scripts/check_dist.py` (`check_dist(dist,
      origins, n_channels) -> list[str]`) imported by the script and tested on a
      synthetic `tmp_path` dist (truncate a `.bin` by 2 bytes; `.rail.bin`
      without `.rail.json`; a listed origin with no files; a `*-journal`;
      `n_channels` from `modes.CHANNELS`). Step 1b asserts that `web/index.html`
      and `llms.txt` contain **no** hard-coded three-digit count and no
      "hundreds" (TE-4, CRIT-9). Mutation: widen a byte width → red.
- [x] **L3** `check_dist` requires `{slug}.json`, pairs `.rail.json` with
      `.rail.bin`, requires `.rail.*` when `index.json.railDetail`, checks each
      `.pmtiles` starts with the `PMTiles` magic and the header offsets lie
      within the file, refuses when a build is running (lock or `pgrep`)
      (CR-7, VER-36, TR-5, SEC-20).
- [x] **L5 / I4** `deploy/rsync-excludes.txt` (`.*`, `*-journal`, `tmp*`,
      `*.tmp`, `*.part`, `.build-*`, `.build.lock`) used by the server rsync
      with `--delete-delay --delay-updates --chmod=D755,F644`, output logged to
      a file (no `tail -c 200`); `check_dist` **refuses** a stray (they are
      evidence of an aborted writer); `location ~ /\. { return 404; }` and a
      `tmp|part|journal` deny in the conf (server install stays with the owner
      under E3); `_atomic_write` chmods `0o644`. Deleting
      `dist/origins/las-vegas.pmtiles-journal` waits for the orchestrator's
      go-ahead.
- [x] **L6** `rsync -a --delete web/vendor/ dist/vendor/` (and the enumerated
      page files) so removed vendor files do not linger (VER-33).
- [x] **L7** Add `css` and `png` to the `no-cache` location; `deploy/README.md`
      lists them; the font comment says "named by family/subset/weight, not by
      content" (VER-34, CRIT-21, DOC-8).
- [x] **L8** `deploy_verify.sh --page-only`: rsync `web/` minus README to the
      server with no `--delete` and no `dist/` gate, then `browser_verify.sh`
      (VER-28). Correct the cycle-1 web plan's completion line (docs plan O7).
- [x] **L9** `browser_verify.sh` asserts `map.getLayer("borders")` and
      `queryRenderedFeatures({layers:["borders"]}).length > 0` at zoom ≥ 3
      (CR-6, CRIT-3, VER-30); adds the folded-sheet legend check (web plan M16)
      and a `?from=` check (M12). Mutation: rename the layer id → red.
- [x] **L10 / J5 / Q8** Repo root from the script's own path; host, server root
      and URL from `deploy/.env` (documented defaults); screenshots under
      `mktemp -d`; the cleanup kills only the session the script opened plus
      agent-browser's own Chrome tree under `~/.agent-browser/browsers/`, never
      a name grep (VER-35, SEC-27, ARCH-15).
- [x] **K4 (deploy half)** covered above.

## Cycle 3

- [ ] **A6b / A6c (staging + sidecars)** `_build_all` writes into
      `dist/.build-{build_id}/`, publishes with same-filesystem renames
      (`origins`, then `hover_cells.bin`, then `index.json`), keeps one previous
      generation; per-origin `{slug}.meta.json` written last as the commit
      record; `check_dist` compares sidecar `buildId` with `index.json`'s and
      recorded sizes (design in `architect.md` §4 A6b/A6c). `--only` and
      `--limit` never publish.
- [ ] **A6d** Versioned releases on the server (`releases/{buildId}` + `current`
      symlink; `root` change in the nginx conf is the owner's install step);
      `deploy_verify.sh --rollback`.
- [ ] **A6e** `--skip-existing` trusting a sidecar with the current
      `inputsHash`; `imap_unordered` for progress (H11, PR-20).
- [ ] **S2** `BuildContext` frozen dataclass via `Pool(initializer=…)`; remove
      the rasterio/GDAL fallbacks in `modes.py:47-50` and `validate.py:149-153`;
      one poisoned-import fork test (ARCH-5).
- [ ] **R3 / H2 (hover grid)** `emit/hover.HoverGrid` built once in the parent
      (`parents`, `parent_of`, `centre_pos`, vectorised `pick`); the four
      writers and `write_hover_cells` take it so the five files provably share
      one ordering (F7); `reachable_in_principle` and the land-border minute
      into the context (PR-3, ARCH-6, PR-16). Mutation: `centre_pos[:] = -1` →
      the centre-child test goes red.
- [ ] **R2** Precompute a `wraps` mask once per build; `_dissolve` loops only
      over wrapping cells (PR-2). Mutation: `wraps` all-False → the Fiji band
      test goes red.
- [ ] **R1 / H1** Stream one feature line at a time with `shapely.to_geojson`;
      `check_bands_cover` builds its STRtree from the geometries directly
      (PR-1). **R4** Log `ru_maxrss` per origin; derive the worker cap from
      physical memory and the measured peak (PR-4). **R5** Compute `cell_class`,
      `speeds`, `country`, `zone` once in `_build_all` and pass them into
      `build_graph` (PR-5, CR-15, J4's seam).
- [ ] **K7** `native_edges` treats a missing neighbour as resolved when any of
      its `FINE_RES` children is indexed, so the cover gate samples the seam
      (TR-11). **K11** `osm_rail.sh` filters on `route=train` alone (CR-16).
  - [x] **K7** (2026-10-02) `grid.native_edges` counts a split neighbour as
        resolved (`NATIVE_VERSION` v2, so a v1 cache cannot hand back the old
        flag), and `check_bands_cover` also samples split cells a quarter of
        the way along each edge, where the slivers their children leave are
        (measured: all 36 edge points of six split cells). Deleting the
        parent-under-children painting now turns the mixed-grid gate test red;
        with the seam sample removed it stayed green. Gate only, no output
        change.
- [ ] **L12 / E15** `check_dist` reads `water.pmtiles`' header and metadata and
      checks `maxzoom` and the `water` layer against `emit/water.py`; `-D 10` /
      low-detail for the water layer's z0–2 (PR-14).
- [ ] **A10** Stable secondary key in `osm.rail_routes` dedupe. **A12** Count
      and bound dropped ferry crossings; book a ferry leg as ferry when the base
      parents are adjacent. **A14** Monotonic-ground gate over cross-resolution
      edges. **A18 / Q4** `adsb_extract.py`: sanitised tag, https + host
      allow-list, size cap.
  - [x] **A14** (2026-10-02) `validate.check_monotonic_ground` walks the
        edges `ground.hex_edges` builds: same-resolution ring neighbours, the
        fine-to-base seam pair from either side, and every `idx.spans` link,
        honouring `severed` and closed borders. Five mixed-grid tests; each of
        the four new branches removed in turn turns one red. Gate only, no
        output change.
- [ ] **A9** South-pole cap dissolve (K13's slivers as the fixture). **A11**
      Resolvable `continue` batches in the wikitext crawl. **A15** Immigration
      zones: one table for air and ground; no border charge on airside
      transits (model change — document before/after per CLAUDE.md). **A16**
      `check_bands_cover` samples the tiles tippecanoe wrote. **G2** Raw
      downloads by URL hash with ETag/size and a refresh policy.
- [ ] **O6 / E6** `transport-maps assets` (or the last step of `build-all`)
      writes `places.json`, `airports.json`, `borders.json`; README lists it.
      Not run this cycle (writes under `dist/`).

## Progress

- 2026-09-10 cycle 2: plan written from the cycle-2 aggregate; carries every
  unfinished task from the cycle-1 build plan (now archived) under its original
  ID. Live evidence recorded in the aggregate: `dist/` is a mixed generation
  (L1), `las-vegas.pmtiles-journal` is served live with 200 (L5), eight orphaned
  workers from 09 Sep are still resident (K4).
- 2026-09-10 cycle 2 done: K1/K2 a30ef1b (old lookup red on the split-neighbour and nearest tests; polars mutant red), K5 c22d630 (snapped bound red without it), K3/K4 53cd8cf (SIGKILLed worker aborts under a 15 s alarm; removing the liveness check hangs -> red; dropping O_EXCL -> red), K8/K9/K10 151b1e6, K6 100f2bb (planar pull-in red), A13 ceb2732 (clamp restored red), A6a 12fe779 (in-place write red for each of seven writers), L2/H10/L11/O12 64ab007 (shutil.move red; metadata carries no local path), S1 S-parts + A17 269e17c (slug validation removed red), A7 35320bf (--only publishing red), G1 364986b (25 stamped constants each red when dropped; urban whole-list red), L3/L4 160bb34 (twelve check_dist refusals), L5/L6/L7/L8/L9/L10/K4-deploy 0e74b2b. Every code change takes effect on the next build; the running rebuild16 is untouched.
- 2026-09-10 cycle 2 deploy: DEPLOY_CMD (`scripts/deploy_verify.sh && scripts/browser_verify.sh`) run once at the end of the cycle, at 10:32 KST with rebuild16 227 of 553 origins in and 0 errors. Step 1 refused: `a build-all is running (pids 4144 4145 4146 4147); refusing to deploy a mixed dist/`, exit 1 before any rsync, so neither dist/ nor the server was touched and the rebuild was not disturbed. rebuild16 predates 53cd8cf, so it holds no `dist/.build.lock`; the CPU-threshold fallback added in 0e74b2b is what caught it -- the refusal is the K4/L1 guard working, not a regression. Not retried and no gate weakened (a `--page-only` deploy was available and deliberately not used: the orchestrator's brief allows one attempt at DEPLOY_CMD). Recorded in the cycle report as per-cycle-failed:artifacts-mid-rebuild. Exit criterion for a green deploy is unchanged: rebuild16 finishes, then DEPLOY_CMD passes check_dist on a single-generation dist/.
- 2026-09-10 cycle 2 closed at `29c6330`: every Cycle 2 task above is ticked; the Cycle 3 section stays open, so this plan is not archived. Both gates green on the whole repo at that commit (ruff clean; pytest 356 passed, 4 deselected, 5 warnings, exit 0) -- recorded in `plan/2026-09-10-c2-gates-and-tests.md`.
