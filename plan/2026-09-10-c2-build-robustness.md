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

- [x] **A6b / A6c (staging + sidecars)** ~~`_build_all` writes into
      `dist/.build-{build_id}/`, publishes with same-filesystem renames
      (`origins`, then `hover_cells.bin`, then `index.json`), keeps one previous
      generation~~; per-origin `{slug}.meta.json` written last as the commit
      record; `check_dist` compares sidecar `buildId` with `index.json`'s and
      recorded sizes (design in `architect.md` §4 A6b/A6c). `--only` and
      `--limit` never publish.
      *(2026-10-02: the sidecars landed, 4924efb; the staging is won't-do.)*
      **Sidecars**, as `<root>/.progress/<slug>.json` (`transport_maps/progress.py`;
      `<root>` is `dist/` or `dist/v/no-<mode>/`). Written as "writing" BEFORE
      an origin's first file is replaced -- after its gates, so a refused origin
      keeps its last build's record -- and as "complete", with every file's
      size, after its last. Keyed on the run's `inputsHash`, a digest of the
      graph (edge arrays, hover ordering, cell classes, rail tables: the data
      inputs `inputsHash` is sampled too early to see), the excluded mode and
      the origin's own row. `index.json` and `variant.json` are published only
      when every origin is complete under the run's key, whichever run wrote
      it. `check_dist` refuses a "writing" record and a complete one whose files
      changed size since; it REPORTS, without refusing, a root with no records
      (every dist/ built before today), an origin with none, and a record from
      other inputs than `index.json` (or, for a variant, its marker) names --
      compared on `inputsHash`, not `buildId`, because a resumed build spans
      runs. Kept out of the served tree: a dot-directory the rsync filter
      already drops (named in `deploy/rsync-excludes.txt` as well), which the
      batch lists never name either; the test runs both. Mutation-checked, each
      red: `begin` removed, moved below the first write, moved above the gates;
      `finish` removed; a suffix dropped from `SUFFIXES`; the publish gate
      removed; each `check_dist` branch; the variant held against `index.json`'s
      hash; both exclude lines removed.
      **Staging** (`dist/.build-{id}/`, rename-publish, one previous
      generation): **won't do**, superseded. (1) One live copy (A6d, owner,
      2026-10-02): staging's payoff was a deployable previous generation while
      a build runs, but the local `dist/` is not deployable during a build
      anyway (`check_dist` refuses the lock) and the server swaps in seconds
      under `--delay-updates`. (2) Space: a full set is ~38.6 MB x 1,464
      origins, about 56 GB before variants; staging doubles the peak on the
      build host. (3) The defect it was for -- one origin half one build and
      half another, passing every length check -- is closed by the "writing"
      record, which `check_dist` refuses and `--skip-existing` rebuilds.
      Two builds side by side, each origin whole, are reported rather than
      refused: the batched deploy (6b739fa) already ships exactly that while
      the cell layouts agree, which the length and node-universe checks
      enforce. Deferred rows whose exit pointed at the staging directory --
      S3 (shape), SEC3-5, ARCH3-10, ARCH3-11 -- are marked for a new exit in
      `plan/deferred.md`; ARCH3-11 can now be checked against the records'
      file lists.
- [x] **A6d** ~~Versioned releases on the server (`releases/{buildId}` + `current`
      symlink; `root` change in the nginx conf is the owner's install step);
      `deploy_verify.sh --rollback`.~~ **Won't do** -- owner, 2026-10-02:
      "release -> just keep one". One live copy; `--delay-updates` keeps the
      swap to seconds, and the site has few users.
- [x] **A6e** `--skip-existing` trusting a sidecar with the current
      `inputsHash`; `imap_unordered` for progress (H11, PR-20).
      *(2026-10-02: fa12fdd, 4d49eb8.)* An origin is skipped only when its
      record is "complete" under the current key (above) and every listed file
      is there at the recorded size; anything else is built. `inputsHash` first
      had to stop naming the commit: it hashed the git head and a dirty flag,
      so a plan tick between the crash and the resume invalidated every
      record. It now hashes the package, `pyproject.toml` and `uv.lock` by
      content (`index._code_hash`), with `gitHead` recorded beside it (and
      carried forward by `reindex`). A full variant run still withdraws its
      marker at the start, resumed or not, and the marker comes back only
      through the publish gate. Forked workers report through
      `imap_unordered`; nothing published depends on the order. To resume:
      the same command plus `--skip-existing` (`uv run transport-maps
      build-all --skip-existing`, or `... --exclude <mode> --skip-existing`),
      after removing a stale `dist/.build.lock` once the dead run is confirmed
      gone. The graph is rebuilt either way; what is saved is the per-origin
      solves. A `dist/` written before records existed has none, so its first
      resume rebuilds every origin. Tests: `tests/test_progress.py`,
      `tests/emit/test_build_identity.py`; each mutation in their docstrings
      red.
- [x] **S2** `BuildContext` frozen dataclass via `Pool(initializer=…)`; remove
      the rasterio/GDAL fallbacks in `modes.py:47-50` and `validate.py:149-153`;
      one poisoned-import fork test (ARCH-5).
  - [x] **S2 (fallbacks half)** (2026-10-02) `modes.mode_minutes_per_node`
        requires `cell_class` and `validate.check_monotonic_ground` requires
        `country` and `zone` (keyword-only); `None` raises `TypeError` instead
        of reloading through rasterio or pyogrio/polars. Every build caller
        already passed them, so only three gate tests that leaned on the
        fallback changed (they now pass KOR, as the build would). The test
        (`tests/cli/test_worker_imports.py`) runs the real `_solve_one` --
        every writer, the coverage and monotonic gates -- in a fork pool
        worker whose polars, pyogrio and rasterio entry points and the two
        in-repo loaders raise, on the layout-contract fixture. Each fallback
        restored with `_solve_one` passing `None` turns it red. No output
        change: same arrays, same calls.
  - [x] **S2 (context half)** (2026-10-02) `cli.BuildContext` (frozen,
        `shared` a `MappingProxyType`) is the pool initializer's argument;
        `_init_worker` watches the parent and keeps it, and the parent's
        `globals()["_CTX"]` is gone. Measured first: a fork pool hands
        `initargs` over by fork, not pickle, at the parent's array addresses,
        so copy-on-write is unchanged. The test makes pickling the context
        raise and checks the parent holds none; three mutations each red.
        Still open: the two fallbacks and the poisoned-import test -- removing
        the fallbacks changes the signatures several tests and callers rely
        on, which is beyond a contained refactor. With S2's context half in,
        CR3-10 and TE3-10's "S2 lands" exits are met for the worker shape.
- [x] **R3 / H2 (hover grid)** `emit/hover.HoverGrid` built once in the parent
      (`parents`, `parent_of`, `centre_pos`, vectorised `pick`); the four
      writers and `write_hover_cells` take it so the five files provably share
      one ordering (F7); `reachable_in_principle` and the land-border minute
      into the context (PR-3, ARCH-6, PR-16). Mutation: `centre_pos[:] = -1` →
      the centre-child test goes red.
      *(2026-10-02: the grid itself landed in 59a3597 under another name --
      `hover.HoverGroups` (`parent_of_cell`, `centre`) built once in
      `_build_all` beside `hover_parents`, and `representative_array` the
      vectorised pick, held against the old loop in
      `tests/emit/test_hover_groups.py`; `centre[:] = -1` turns it red,
      re-checked today. The F7 ordering test is 6e97391. What was left lands
      now: `write_hover_cells(parents=)` and `index.json`'s `hoverCellCount`
      take the same `hover_parents` list every writer gets (two more
      recomputations gone, ~7 s each); `validate.reachable_in_principle` is
      computed once into `shared["reachable"]` for `check_coverage` (~9 s of
      h3 per origin); the land-border minute once into `shared["border_min"]`
      for `check_monotonic_ground(crossing_min=)`. Each keeps its old
      default, so standalone callers are unchanged. Outputs identical on
      fixtures: `hover_cells.bin` bytes with and without the list, coverage
      with and without the mask (hand-written mask, Antarctic cells in), the
      gate's verdict with and without the minute. A wiring test checks the
      parent computes each once and every origin gets the same object; four
      wiring mutations and the mask's `>` -> `<` and an ignored
      `crossing_min` each turn one red. A single `HoverGrid` object in place
      of the three `shared` entries was not done: it would rename what the
      tests build by hand and change no file.)*
- [x] **R2** Precompute a `wraps` mask once per build; `_dissolve` loops only
      over wrapping cells (PR-2). Mutation: `wraps` all-False → the Fiji band
      test goes red. *(2026-10-02: `bands.precompute_flags` -- wraps and
      resolution per native and render-grid cell -- built once in
      `_build_all_locked` (~1 µs a cell, ~14 s per build against ~115 s per
      origin) and passed as `flags=`; coarse parents are flagged once per
      origin, not per band. A Taveuni fixture with wrapping fine, unsplit,
      sea-ring and coarse cells compares the whole feature collection against
      the per-cell `_dissolve`: identical. Wraps all-False, the parents' flags
      dropped, or the base level unflagged each turn it red. No output
      change.)*
- [ ] **R1 / H1** Stream one feature line at a time with `shapely.to_geojson`;
      `check_bands_cover` builds its STRtree from the geometries directly
      (PR-1). **R4** Log `ru_maxrss` per origin; derive the worker cap from
      physical memory and the measured peak (PR-4). **R5** Compute `cell_class`,
      `speeds`, `country`, `zone` once in `_build_all` and pass them into
      `build_graph` (PR-5, CR-15, J4's seam).
  - [x] **R1** (2026-10-02) Band features carry the shapely geometry, not
        its `mapping()`; `tiles.write_geojson` maps and encodes one feature
        at a time between the separators `json.dump` uses, and
        `check_bands_cover` takes the geometries as they are (a mapping is
        still parsed). Not `shapely.to_geojson` as written above: GEOS's text
        is a different file for the same shapes (spliced in, it turns the
        test red), and the brief was byte-identical tippecanoe input. Proved
        on a Taveuni fixture (every level, wrapping and split cells,
        multipolygons): the file tippecanoe is handed equals one `json.dump`
        of the mapped collection, byte for byte. Mutations, each red: the
        separator, `to_geojson`, bands storing mappings again. What it saves:
        128 bytes per coordinate as Python tuples against GEOS's 16, measured
        on that fixture; the per-worker peak on a real origin is for R4's
        column on the next build to show. Same tiles, so no output change.
  - [x] **R4 (log half)** (2026-10-02) Every per-origin row ends with the
        process's pid and its `ru_maxrss` in MB (bytes on macOS, KB on Linux;
        a high-water mark, so the largest figure per pid is that worker's
        peak). Held against `ps` RSS and physical memory; either wrong unit
        turns the test red. The cap derivation stays open: it needs the peak
        this column will measure on the next full build.
  - [x] **R5** (2026-10-02) `_build_all_locked` derives country, zone, road
        class and speeds once, before the graph, and passes them to
        `build_graph(speeds=, country=, zone=)`, which builds the border rules
        once and hands the same tuple to `hex_edges`, `_span_edges`,
        `_rail_edges` and `_ferry_edges` (country/zone: five derivations ->
        one; road class: four -> two, `nodes.build_index` keeping its own).
        Every argument is optional, so other callers are unchanged. Two
        wiring tests by identity; seven mutations (each builder or the build
        dropping what it was handed) each red. Same arrays, so no output
        change.
- [x] **K7** `native_edges` treats a missing neighbour as resolved when any of
      its `FINE_RES` children is indexed, so the cover gate samples the seam
      (TR-11). **K11** `osm_rail.sh` filters on `route=train` alone (CR-16).
      *(2026-10-02: both halves below were done and the box left empty;
      verified against the code today -- `NATIVE_VERSION = 2` and the split
      test in `grid.native_edges`, `SEAM_EDGE_FRACTIONS` and
      `_interior_split_parents` in `validate.py`, `r/route=train` in
      `scripts/osm_rail.sh`. K7 f383b86 (with f8a682c), K11 ac11bfc.)*
  - [x] **K7** (2026-10-02) `grid.native_edges` counts a split neighbour as
        resolved (`NATIVE_VERSION` v2, so a v1 cache cannot hand back the old
        flag), and `check_bands_cover` also samples split cells a quarter of
        the way along each edge, where the slivers their children leave are
        (measured: all 36 edge points of six split cells). Deleting the
        parent-under-children painting now turns the mixed-grid gate test red;
        with the seam sample removed it stayed green. Gate only, no output
        change.
  - [x] **K11** (2026-10-02) `scripts/osm_rail.sh` filters relations on
        `r/route=train` (osmium's comma separates values, so the old
        expression kept every `type=route` relation). `osm._relations` reads
        only `type=route` + `route=train`, and every service tier -- heritage
        (`service=tourism`) included -- is a tag on those, so the parse is
        unchanged; a test runs the script's own expression against the parser
        on a fixture of train, heritage, light-rail, bus, hiking, road, tram
        and route-master relations, and the old expression turns it red.
        Takes effect only when the extracts are next regenerated; the rail
        and ferry parquet caches key on each extract's size and mtime, so a
        regenerated extract is a miss and no parser-version bump is needed.
        Build output unchanged.
- [x] **L12 / E15** `check_dist` reads `water.pmtiles`' header and metadata and
      checks `maxzoom` and the `water` layer against `emit/water.py`.
      *Done 2026-10-02:* `_water_problems` refuses a tile type other than MVT,
      a header zoom range other than `MIN_ZOOM`-`MAX_ZOOM` (the old z0-12
      archive fails), metadata without `vector_layers`, and layers that do not
      include `water.LAYER`; a test pins the page's `source-layer` to the same
      name. The live `dist/water.pmtiles` (z0-11, `water`) passes.
      `tests/web/test_check_dist.py`, seven mutants.
- [x] **L12 (PR-14 half)** ~~`-D 10` / low-detail for the water layer's z0–2.~~
      **Won't do -- measured 2026-10-02.** A `-D 10` build is 386 MB against
      504 MB, and its tiles are half the size or less (largest tile at z3-z6:
      15-24 KB against 67-100 KB). But tippecanoe's `-D` applies to every zoom
      below the maximum, not to z0-2 alone, and at z7 the coast is visibly
      coarser: Copenhagen's shore and the small lakes go to straight-edged
      polygons (side-by-side crop compared in the browser; 0.5-1.0% of pixels
      differ across four views, concentrated on coasts). Limiting it to z0-2
      would need a second tileset joined with `tile-join` to save about
      0.3 MB of the world view's tiles. Not worth either cost.
- [x] **A10** Stable secondary key in `osm.rail_routes` dedupe. **A12** Count
      and bound dropped ferry crossings; book a ferry leg as ferry when the base
      parents are adjacent. **A14** Monotonic-ground gate over cross-resolution
      edges. **A18 / Q4** `adsb_extract.py`: sanitised tag, https + host
      allow-list, size cap. *(A18 done 2026-10-02 -- see Q4 in the security
      plan; A10, A12 and A14 are still open, so the box stays empty.)*
      *(2026-10-02: all four done; A10 and A12 had landed in earlier commits
      and were never ticked, see below.)*
  - [x] **A10** (verified 2026-10-02; landed 87aec6f, 2026-09-10)
        `_pick_one_extract_per_route` keeps one extract per route, the one
        with most stops, ties broken by extract name
        (`sort(["route_id", "_n", "_extract"])` then `unique(keep="first")`,
        which cycle 15 measured to honour input order). The final
        `sort("route_id", "seq")` has no ties left to order: `seq` is
        `enumerate` within one route of one extract. That commit bumped
        `RAIL_PARSER_VERSION` to 2, so the spliced cache was already a miss;
        nothing changes today, so no bump now. Mutation-checked today, each
        red in `tests/sources/test_osm.py`: the extract-name key dropped, and
        the tie broken the other way.
  - [x] **A12** (verified 2026-10-02; landed 225a012 and 7abbde1)
        `build._ferry_edges` counts every drop by reason, logs them, and
        raises when more than `MAX_OFF_MASK_FERRY_FRACTION` (20%) of the
        crossings in the length window lose an endpoint off the land mask
        (225a012). `modes.mode_minutes_per_node` books a cell-to-cell hop as
        road only when `refine.ground_joined` -- the test the build uses to
        drop a ferry that duplicates a ground edge -- so a sailing between
        adjacent but severed cells is a ferry minute, not a road one
        (7abbde1). Mutation-checked today, each red: the off-mask bound
        removed (`tests/graph/test_ferry.py`), every adjacent hop booked as
        road (`tests/graph/test_landmass.py`).
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
  - [x] **A11** (2026-10-02) `_validated_json` raises `IncompleteResponse`
        (a `RuntimeError`, so every existing catch still holds) for a
        `continue` key or a missing `batchcomplete`; `_crawl_destinations`
        answers it by halving the batch and asking for both halves at once,
        down to one article, which is left unresolved if even that pages.
        Other failures are handled as before. Test: any request for more than
        two titles pages -- seven articles in one batch all resolve and are
        cached, an article that pages alone stays unresolved, no loop; with
        the split removed it is red. Changes only a crawl that used to refuse
        forever: the parse, the per-article cache and the `routes.parquet`
        key are untouched, so no build output changes.
  - [ ] **A9** -- recorded 2026-10-02, NOT implemented: every fix changes the
        tiles. Measured today with the current code: `landmask._pole_cells`
        (19 cells, 4 of them wrapping the antimeridian) still dissolves to an
        INVALID polygon, bounds `[-180, -89.99, 180, -89.82]` at res 6 and
        `[-180, -89.99, 180, -89.94]` at res 7, that leaves 2 of its own 114
        pulled-in vertices uncovered at each. Emitting the cap as a lat/lon
        rectangle, or keeping the pole cells out of `_dissolve`, changes the
        Antarctic cap's band geometry in every origin's PMTiles. The
        gate-only option (drop the pole cells from `check_bands_cover`'s
        sample) would hide the defect rather than fix it, so it was not taken.
        Waits for the owner and the build that would carry it; TE3-8's exit in
        `plan/deferred.md` waits with it.
  - [x] **A15** -- owner approved the model change 2026-10-02 for the NEXT
        full build; implemented 2026-10-03 (`0b36a16` zone membership,
        `6791764` border once per airside journey). In code only: rebuild 27
        does not carry it, and the release steps, measured before/after and
        merge caution are in `plan/2026-10-02-rebuild28-model.md`.
        2026-10-03 notes: (1) checking CR-20's list against official
        sources reversed one item -- the French overseas departments KEEP
        their border (outside Schengen; a Paris flight passes a check at the
        metropolitan airport, Assemblée nationale 15-1639QE), and Andorra
        keeps its own; Åland, Monaco, San Marino, the Vatican and the Crown
        Dependencies moved, Ercan is `CYN`. (2) The airside rule needed
        state, so every airport has a second (international) pair of nodes
        after the stations; `graph/layout.py` replaces the seven
        hand-derived offset sites (J1's code half). (3) The US is the one
        zone with no airside transit, so a US connection pays twice, as
        before. (4) Measured air-only on rebuild 27's inputs: 57.8% of
        airport pairs faster, median 45 min, six slower (all via Ercan).
        Mutation-checked: every new guard in `test_transfers.py`,
        `test_edge_builders.py`, `test_airside_transit.py`,
        `tests/emit/test_intl_layer.py` and `tests/service/test_bundle.py`
        red when its line is broken.
        The 2026-10-02 record, kept: Air reads the country from
        OurAirports' `iso_country` against the Schengen + CTA table in
        `graph/transfers.py`; ground, rail and ferry read Natural Earth's.
        What it would change: flights between France and its overseas
        departments (RE, GP, MQ, GF, YT in OurAirports, `FRA` on the ground)
        would stop paying `border_min`; Åland, the Isle of Man, Jersey,
        Guernsey, Monaco, San Marino and the Vatican would stop being zones
        of their own, so their ferry and ground edges lose the land-border
        minute; Ercan (`CY` in OurAirports, `CYN` cells) would change zone;
        and an airside transit -- Seoul -> NRT -> FRA today pays the border
        charge on both flights (TR-17) -- would pay it once. Every time
        through any of those routes moves, so CLAUDE.md's before/after and a
        calibration note come with it.
  - [ ] **A16** -- recorded 2026-10-02, NOT implemented. A cover gate on the
        tiles is new code (an MVT decoder, which is not a dependency today)
        and, more to the point, needs a tolerance: tippecanoe moves vertices
        by design (`--simplification=8` with Visvalingam, and quantisation to
        the tile grid), so the GeoJSON gate's 3% pull-in would fail tiles
        that are correct. That tolerance has to be measured on a real origin's
        tiles, which this run may not produce (no build against real data
        while rebuild 27 runs), and a gate set without it could refuse origins
        the current build publishes -- a change in what a build produces.
        Waits for that measurement.
  - [ ] **G2** -- recorded 2026-10-02, NOT implemented: it changes what a
        build reads. Keying raw downloads by URL hash renames every raw cache
        (land, countries, places, urban, the GRIP4 rasters, airports,
        borders, water), so the next build would either download again --
        and get whatever the upstream holds now -- or need an adoption path
        for the bare names; an ETag refresh policy exists precisely to pick
        up a moved upstream. When a build may refresh its inputs is the
        owner's policy to set. The derived caches that matter for silent
        staleness already key on their inputs (G1).
- [x] **O6 / E6** `transport-maps assets` (or the last step of `build-all`)
      writes `places.json`, `airports.json`, `borders.json`; README lists it.
      Not run this cycle (writes under `dist/`). *(2026-10-02: code half
      landed -- `transport-maps assets [NAME ...]` calls the three emitters'
      `build(out)` under the build lock; `check_dist` names the producer when
      one is missing. Tested on tmp_path only: all three, a subset, refusal
      under a held lock, unknown names, dispatch, and the airports table's
      shape; dropping an entry, the lock or the dispatch each turns one red.
      Still NOT run against `dist/`, so the live copies remain the
      hand-made ones until the owner runs it. Not taken here: C11's airport
      filtering (a separate web-plan entry, and filtering by the graph would
      need the node index inside `assets`), folding the water build in
      (CR4-aside), and the bare-filename download caches in `places.py` /
      `borders.py` (C11-D1).)*

## Progress

- 2026-09-10 cycle 2: plan written from the cycle-2 aggregate; carries every
  unfinished task from the cycle-1 build plan (now archived) under its original
  ID. Live evidence recorded in the aggregate: `dist/` is a mixed generation
  (L1), `las-vegas.pmtiles-journal` is served live with 200 (L5), eight orphaned
  workers from 09 Sep are still resident (K4).
- 2026-09-10 cycle 2 done: K1/K2 a30ef1b (old lookup red on the split-neighbour and nearest tests; polars mutant red), K5 c22d630 (snapped bound red without it), K3/K4 53cd8cf (SIGKILLed worker aborts under a 15 s alarm; removing the liveness check hangs -> red; dropping O_EXCL -> red), K8/K9/K10 151b1e6, K6 100f2bb (planar pull-in red), A13 ceb2732 (clamp restored red), A6a 12fe779 (in-place write red for each of seven writers), L2/H10/L11/O12 64ab007 (shutil.move red; metadata carries no local path), S1 S-parts + A17 269e17c (slug validation removed red), A7 35320bf (--only publishing red), G1 364986b (25 stamped constants each red when dropped; urban whole-list red), L3/L4 160bb34 (twelve check_dist refusals), L5/L6/L7/L8/L9/L10/K4-deploy 0e74b2b. Every code change takes effect on the next build; the running rebuild16 is untouched.
- 2026-09-10 cycle 2 deploy: DEPLOY_CMD (`scripts/deploy_verify.sh && scripts/browser_verify.sh`) run once at the end of the cycle, at 10:32 KST with rebuild16 227 of 553 origins in and 0 errors. Step 1 refused: `a build-all is running (pids 4144 4145 4146 4147); refusing to deploy a mixed dist/`, exit 1 before any rsync, so neither dist/ nor the server was touched and the rebuild was not disturbed. rebuild16 predates 53cd8cf, so it holds no `dist/.build.lock`; the CPU-threshold fallback added in 0e74b2b is what caught it -- the refusal is the K4/L1 guard working, not a regression. Not retried and no gate weakened (a `--page-only` deploy was available and deliberately not used: the orchestrator's brief allows one attempt at DEPLOY_CMD). Recorded in the cycle report as per-cycle-failed:artifacts-mid-rebuild. Exit criterion for a green deploy is unchanged: rebuild16 finishes, then DEPLOY_CMD passes check_dist on a single-generation dist/.
- 2026-09-10 cycle 2 closed at `29c6330`: every Cycle 2 task above is ticked; the Cycle 3 section stays open, so this plan is not archived. Both gates green on the whole repo at that commit (ruff clean; pytest 356 passed, 4 deselected, 5 warnings, exit 0) -- recorded in `plan/2026-09-10-c2-gates-and-tests.md`.
- 2026-10-02 pipeline close-out, in a worktree while rebuild 27 runs (no build,
  reindex or assets against real data; dist/ and data/ untouched): S2's
  fallbacks 72e0163, R3/H2's remainder 6a23da8, A11 c97bdf4, R1 c93c321 -- none
  changes a build's output, each shown on a fixture and its mutations red.
  Ticked after checking the code: K7/K11, A10, A12. Recorded, not done: A9 and
  G2 (they change what a build produces or reads), A15 (model change, owner),
  A16 (needs a tolerance measured on real tiles); R4's cap and L12's tileset
  half stay open as before. Gates on the worktree: ruff clean; pytest
  `-m "not integration and not network and not real_multi_band"` 1404 passed,
  25 skipped, 53 deselected (the untouched tree: 1397 passed, the same 25
  skipped -- they need data/ or dist/, which a worktree does not have).
