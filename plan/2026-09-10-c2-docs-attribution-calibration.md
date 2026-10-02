# Plan (cycle 2): attribution, docs, calibration provenance, bookkeeping

Source findings: `.context/reviews/_aggregate.md` section O (O2–O16), S1, S6,
plus every unfinished task carried from
`plan/archive/2026-09-10-c1-docs-attribution-calibration.md` (B2, E8, E10, J1,
J5, E11, E14; cycle 3: E13, I5 docs). Per-agent detail: `document-specialist.md`
(DOC-1…27 with the fact table and external sources), `critic.md`, `verifier.md`,
`architect.md` (§2b contract, §4 J1), `code-reviewer.md`.

CLAUDE.md modelling rule is binding: every calibration constant carries a
comment saying whether it is fitted (against what) or a published-figure
default. The comment-only half is safe while the rebuild runs (TOML comments
and README text are not read by the build); the table move waits for the next
build.

## Cycle 2 (this run)

- [x] **O2 / B2 (comment half)** `calibration.toml`: the seven unlabelled
      tables get "Published-figure default; not fitted" (`taxi_out_min`,
      `taxi_in_min`, `frequency.size_weight`, `processing_min`,
      `disembark_min`, `border_min`, `connection_min`); the three false
      "refitted in Task 12/13" claims (:42-43, :48, :95) become "hand-fitted to
      two anchors; no observed-frequency refit has been done"; the header :3
      describes the whole file. `README.md:75-78` says where the ground fit
      lives (`graph/ground.py`, `sources/urban.py`) and that the sampled
      durations stay in `data/build/` (DOC-1, DOC-2). `mode_detail()` reads the
      rail/ferry figures from the calibration loaders instead of literals
      (DOC-26, CR-8). A provenance test parses the raw TOML and asserts every
      table header is preceded by "fitted" or "published-figure default" within
      its comment block (ARCH-8). Mutation: delete one label → red.
- [x] **O3 / E8** JSON-LD `index.html:46` and the ten comment sites
      (`refine.py:3,7`, `bands.py:13,17,148-157`, `tiles.py:11,17`,
      `hover.py:35`, `countries.py:91`, `grid.py:3`, `roads.py:100-101`,
      `ground.py:55-57`, `rail.py:24`) carry the h3 4.5.0 figures: res 4
      26.07 km edge / 1,770 km² / 45 km across; res 6 3.72 km / 36.1 km² /
      6.5 km; res 7 1.41 km / 5.16 km² / 2.4 km (DOC-3, VER-31, CR-9). The
      JSON-LD loses the airport/station/ferry counts (web plan O4).
- [x] **O8** `emit/index.py:19-21` comment; the OSM `usedFor` names rail
      relations, ferry ways, coastlines and GRIP4; README :58/:63 and
      `llms.txt:53` say "ferry ways"; Natural Earth `usedFor` matches the README
      row (DOC-7, VER-32).
- [x] **O10** Stale-number batch: `build.py:380`, `modes.py:10`,
      `calibrate_ground.py:7,47`, the two sample sizes explained in
      `ground.py:17` / `ground_check.py:5` / `urban.py:4-6`, `app.js:233,319,
      618-622`, `places.py:3`, `airports_json.py:3`, `nodes.py:32`,
      `validate.py:14,133`, `cli.py:170`, `bands.py:25`, `tiles.py:9-19,35`,
      `osm_rail.sh:11-16`; delete `landmask._cells_touching` (with G1) (DOC-14,
      VER-37).
- [x] **O5** `web/README.md` pin note: 5.24.0 is the last 5.x and carries
      CVE-2026-85061 (fixed only in 6.4.1); the vendored patch and its hashes
      recorded (security plan Q3) (DOC-4).
- [x] **O7** Bookkeeping: the archived web plan's completion line says
      "verified on the local preview; not deployed"; H2's rail half ticked
      with `bf9e5cc`; E8 one entry; D17 closed; `593c231`'s note corrected
      (old = 90,659 res-5 arrays, new = 90,740 `hover_cells.bin`);
      `plan/README.md` status column and paths; "13 of 15" → the SDD ledger's
      11 complete + 4 done outside the plan; a header on
      `cycle-1/_aggregate.md` saying its status column is a snapshot at
      `edf4b0d` (CRIT-4, VER-28, VER-38, DOC-6, DOC-16, DOC-17, DOC-18).
- [x] **O9 / E10** Spec status → "Superseded in part — see As built"; a short
      "As built (2026-09)" section with the delta table from DOC-9; the pipeline
      plan gets a header pointing at the SDD ledger and stating that Tasks 9,
      10, 12, 13 were completed outside the plan or replaced. The pipeline plan
      stays under `docs/` (its ledger is the record).
- [x] **O12 / E11** `water.py` uses `--no-simplification-of-shared-nodes`
      (takes effect on the next water build); the sky call keeps
      `atmosphere-blend` and a comment names the inert keys (DOC-21).
- [x] **O11** `web/vendor/OFL.txt` (IBM Plex LICENSE.txt) and one line in
      `web/README.md` Typography (DOC-15).
- [x] **O14** `data/origins.toml` header mentions the `expand_origins.py` half
      (DOC-23). **O15** `<meta charset>` first in `<head>` (DOC-25). **O16**
      `llms.txt` states the array sizes and that `hover_cells.bin` orders them
      (DOC-27).
- [x] **E14** Document the `h3shape_to_cells_experimental` dependency in
      `landmask.py` and pin its `contain="overlap"` behaviour with a test on a
      small island polygon (the cache-free islands test already exists — make
      the dependency explicit in its docstring and the README).
- [x] **O4 (docs half)** README "550+" → "the cities in `data/origins.toml`
      (553 today; the live build may lag)"; `llms.txt` coverage sentence →
      the 90 % gate wording (DOC-11, DOC-20).
- [x] **O1 (llms.txt half)** with the web plan.

## Cycle 3

- [x] **J1 / S1 (document)** `docs/contract.md`: file set and suffix table,
      `index.json` schema by `contractVersion`, binary layouts (widths,
      ordering, sentinels, clamp), PMTiles layer/props/LODs, the rendering
      invariants (faster band on top; water above bands), node-offset
      arithmetic, the endianness assumption; `config.CONTRACT_VERSION = 2`;
      the page refuses an unsupported version through `fatal()`;
      `NodeIndex.offsets` replaces the six hand-derived sites; `check_dist`
      derives widths from `modeChannels`; a contract test (design in
      `architect.md` §4 J1). The S parts (`buildId`, `builtAt`,
      `hoverCellCount`, `modeChannels`, `graph`) land in cycle 2 (build plan).
      (2026-10-02, the document half and the version field are DONE; the
      code half is split out as J1b below. `docs/contract.md` now covers the
      owners (pipeline, page, service), versioning, the shared files, the nine
      per-origin files with widths, orderings and sentinels, the variants, what
      is never deployed (`.progress/`, the solver bundle), every `index.json`
      field with the page's fallback, the node-offset arithmetic, byte order,
      and the S6 rules. `places.json`'s largest-first row order is recorded
      there too, which was ARCH3-4's exit criterion. `index.json` carries
      `contractVersion: 2`. It is defined as `emit/index.py:CONTRACT_VERSION`,
      not in `config`, because a `config`-derived payload field joins the
      reindex refusal set and that is J1b's change to make. The new tests are
      `tests/emit/test_index.py::test_index_json_carries_the_contract_version_the_contract_names`,
      whose expected value is read from the document, and
      `tests/test_contract_doc.py`, which compares the document's tables with
      `write_index`'s keys, `progress.SUFFIXES` and `check_dist.REQUIRED_EXTRAS`
      in both directions. All eight mutations listed in those files went RED.
      One deviation from the text above: the page must **warn** on an unknown
      version, never `fatal()`. That is the owner's standing rule that the page
      never goes blank, and every field already has a fallback.)
- [ ] **J1b (code half of J1)**, not doc-only and outside the 2026-10-02
      lane, which could not touch `web/`, `cli.py` or `scripts/`:
      (a) the page reads `meta.contractVersion` and, when it is greater
      than the version it knows, calls `console.warn` with the two numbers
      and carries on. That is one guarded line after the `meta` load in
      `web/app.js`, plus a `tests/web/` source test that strips comments and
      fails on any `fatal(` in that guard. It needs a browser check before it
      ships (CLAUDE.md).
      (b) Add `"contractVersion": lambda: index.CONTRACT_VERSION` to
      `cli._CURRENT_INDEX_CONSTANTS`, so `reindex` refuses to stamp today's
      version over a dist/ built under another one. An absent field still
      passes, as for the other keys.
      (c) One `NodeIndex.offsets` to replace the seven hand-derived sites
      (`docs/contract.md`, "Node-offset arithmetic"). This was ARCH3-3.
      (d) `check_dist` should take the channel width from `index.json`'s
      `modeChannels` rather than the emitter's `CHANNELS`. This was AA44/AA34.
      (2026-10-02, (b) and (d) DONE; (a) and (c) still open, so the box stays
      open. (b): `"contractVersion": lambda: index.CONTRACT_VERSION` is in
      `cli._CURRENT_INDEX_CONSTANTS`; an index without the key still
      reindexes. `tests/cli/test_reindex.py` gains three tests (refusal,
      absent key, the lambda reads today's constant), and its derived-key
      parse now also counts `emit/index.py`'s module-level integer constants,
      which is why it could not see `contractVersion` before.
      `tests/test_contract_doc.py` now keeps the contract's *frozen* marks
      equal to the refusal set, and the `contractVersion` row is marked
      *frozen*. (d): `scripts/check_dist.py` no longer imports `CHANNELS` at
      module level. `_channel_count()` reads `len(modeChannels)` from
      `index.json`, falls back to `emit.modes.CHANNELS` only when the field
      is absent or not a list of names, and reports that case. `n_channels`
      is now an optional extra expectation. Mutations, each RED and restored:
      drop the refusal key (3 tests red); freeze the lambda at 2; use the
      emitter's count in place of the index's; return 0 from the fallback;
      accept any non-None `modeChannels`; drop the *frozen* mark from the
      doc row. Not touched: AA34/AA44's shared publishability predicate,
      which is a separate refactor. The width table is still typed in both
      `cli.py` and `check_dist.py`, but `check_dist`'s copy now follows the
      index and no longer follows the emitter.)
- [x] **B2 (table move)** `[ground]`, `[urban]` and the air-bound constants
      into `calibration.toml` with labels; one `calibrate.load()` threaded
      through the build context; `_land_border_min` no longer parsed per origin
      (ARCH-8). After the rebuild.
      (2026-10-02, DONE except for the single threaded loader, which is
      carried as B2b. `calibration.toml` gains `[ground]`
      speeds with one key per GRIP4 class, `roadless_kmh` to `local_kmh`.
      They are keys and not an array because the licence firewall refuses any
      list in the file. The table is labelled as a mixture: classes 1-4 FITTED to
      2,998 Google Routes journeys, 0 and 5 published-figure defaults, with
      the reasons. It gains `[urban]` `pop_min`, `radius_km` and
      `congestion_factor`, all FITTED jointly to the 112 + 1,383 journey sets.
      `[frequency]` gains `knee_km` and `min_flights_per_week`, labelled NOT
      fitted, as bounds chosen so no anchor moves. The derivations moved with
      the values. `graph/ground.py`, `sources/urban.py` and `graph/air.py` each
      read their table once, at import, through a loader that takes a path
      (`load_ground_calibration`, `load_urban_calibration`,
      `load_frequency_bounds`). The module constants keep their names, so no
      caller changed. `_land_border_min()` now returns the value read at import
      instead of re-parsing the file for every origin's monotonicity gate.
      **The values are identical.** `tests/test_calibration_moved.py` pins
      them against the old literals, typed into the test, and checks that each
      loader follows an edit to the file and that each constant is assigned
      only from its loader. Six mutations, all red.
      **Caches.** The only derived cache any of these govern is the urban mask
      (`urban._mask_cache_path`). It keys on `pop_min`, `radius_km`,
      `PLACES_URL` and the cell list, as before. Its key value does NOT
      change: `urban_mask-81727e55` for the pinned cells, before and after, and
      the test pins that literal. The loader casts to float, because the key
      is digested through json, where 200000 and 200000.0 differ. The ground
      speeds, the congestion factor, the two air bounds and the land-border
      time reach the artifacts only through the graph. No disk cache holds
      them. The per-origin completion records key on `inputsHash`, which
      hashes `calibration.toml` and the package source, so that key DOES
      change. The cost is that `build-all --skip-existing` will not resume a
      build started before this commit; it rebuilds those origins. Any commit
      under `src/` has the same effect. The graph digest in the same records
      is unchanged, because the edge weights are.
      Not done here, and not doc-only: the page's `MODE_FALLBACK` and
      `mode_detail()`'s "halved" still render the congestion factor as a
      word (CR3-7, whose exit criterion "B2 lands" has now fired, in
      `deferred.md`). Three texts still say the fitted values live in
      `graph/ground.py` and `sources/urban.py`, and should name
      `calibration.toml [ground]`/`[urban]` instead: `README.md`'s calibration
      paragraph (around line 110), and the docstrings of
      `scripts/calibrate_ground.py` (lines 12-13) and `scripts/ground_check.py`
      (lines 7-8). All three files were outside this lane. Full gate after the
      move: 1411 passed, 25 skipped, 53 deselected, exit 0. The pre-move
      baseline was 1397 passed, and the 14 new tests account for the
      difference.)
- [x] **CR3-7 (pipeline half)** Derive the road prose's "halved inside cities"
      from `calibration.toml [urban] congestion_factor` instead of typing the
      word. (2026-10-02, DONE. `emit/index.urban_slowdown(factor)` returns
      "halved" only when the factor is exactly 2.0 and otherwise
      "divided by {factor:g}". `mode_detail()` passes it
      `urban.URBAN_CONGESTION_FACTOR`, the value the graph divides speeds by
      in `graph/ground.cell_speed_kmh`. At today's 2.0 the shipped prose is
      byte-identical. The test is
      `tests/emit/test_index.py::test_the_road_prose_says_halved_only_when_the_factor_is_two`,
      which sets the factor to 2.5 and requires "divided by 2.5 inside
      cities" in the highway, major-road and minor-road sentences, with no
      "halved". Three mutations, all RED: the literal back; `urban_slowdown`
      returning "halved" whatever the factor; `mode_detail` passing a frozen
      2.0.)
- [ ] **CR3-7b (page half)** `web/app.js` `MODE_FALLBACK` still says "halved
      inside cities" three times. It was outside this lane, which could not
      edit `web/`. The fallback is used only for an `index.json` with no
      `modeDetail`, so it cannot know the factor. Re-typing "halved" or
      "divided by 2" is the same drift CR3-7 removed from the pipeline.
      `MODE_FALLBACK` must therefore drop the quantity, not restate it. Use
      exactly these three entries, and leave the other three alone:
      ```js
      "highway": "Motorways and expressways at a fitted free-flow speed, slowed inside cities by a fitted congestion factor.",
      "major road": "Primary and secondary roads at fitted speeds, slowed inside cities by a fitted congestion factor.",
      "minor road": "Tertiary roads at a fitted speed; local roads at a published-figure "
                    + "default. Both slowed inside cities by a fitted congestion factor.",
      ```
      Add a `tests/web/` source test, run over the comment-stripped
      `MODE_FALLBACK` literal, that fails on `halved` and on any digit. Mutate
      it by putting "halved" back, and confirm it goes red. A browser check is
      not needed: the fallback is reached only on an `index.json` older than
      `modeDetail`.
- [ ] **B2b** One calibration loader threaded through the build context
      (`calibrate.load()`), replacing the per-module loaders: air, rail,
      ferry, ground, urban and carry-on each still open `calibration.toml`
      themselves (AB46). `air.load_calibration()` alone is called three times
      in `graph/build.py`, and the rail and ferry loaders again in
      `emit/index.mode_detail()`. All of these run before the workers fork.
      The per-origin parse that ARCH-8 named was `_land_border_min()` in
      `validate.check_monotonic_ground`, and that one is gone, which was the
      correctness half. What is left is the refactor half. It touches `cli.py` and `graph/build.py`, so it
      waits for a lane that may edit them.
- [ ] **E13** Owner decision on the `pyproject.toml` author email.
- [x] **I5 (docs part)** The vendored JS hashes table (recorded by the security
      reviewer) in `web/README.md`, and a test that recomputes them (with Q6).
      (2026-10-02: found already done and never ticked. The table landed in
      43eb6b6/773eafe, the recomputing test in 773eafe, and 3ec7e34 then
      704e789 widened it to every file under `vendor/`, both directions.
      The upstream-provenance half that `deferred.md` SEC4-5 folded into this
      task was not done. It is now a "Where each file came from" table in
      `web/README.md`, checked against jsDelivr and IBM/plex on this date.)
- [x] **S6** Name the two cross-layer invariants (mode prose; overlap-by-rim
      and `fill-sort-key`) in the contract document. (2026-10-02:
      `docs/contract.md` "Rules that cross the layer boundary", created for
      this with J1's remaining sections still to come; the spec's As-built
      table gains a row for the false "never learns" sentence. Noted there:
      `test_app_constants.py` pins the sort key's presence, not its sign.)

## Progress

- 2026-09-10 cycle 2: plan written from the cycle-2 aggregate; carries every
  unfinished task from the cycle-1 docs plan (now archived) under its original
  ID. VER-29 (CLAUDE.md band wording) was refuted: the on-disk file already
  says anchors ≥ 6 (changed in `2526673`); D20's wording half stands as done.
- 2026-09-10 cycle 2 done: O2 comment half 30e6034 (provenance test red twice under a deleted label) with the code half in 269e17c; O3 9555045 + 9d0a401 (JSON-LD) + 8129e47 (roads/ground/hover/tiles); O8 9555045 + 269e17c; O10 9555045 + 8129e47; O5 43eb6b6 + 773eafe (hashes recorded after the patch); O7 9b4a248 + a6e6d22; O9 a6e6d22; O12 64ab007 (water flag) + 9d0a401 (sky comment); O11, O16, O4 docs half, O1 llms half 43eb6b6; O14 a6e6d22; O15 9d0a401; E14 364986b (land_cells docstring; the cache-free islands test pins contain=overlap).
- 2026-09-10 cycle 2 closed at `29c6330`: every Cycle 2 task above is ticked; the Cycle 3 section stays open, so this plan is not archived. Both gates green on the whole repo at that commit (ruff clean; pytest 356 passed, 4 deselected, 5 warnings, exit 0) -- recorded in `plan/2026-09-10-c2-gates-and-tests.md`.
- 2026-10-02: the doc-only remainder of this plan. S6 is done (`docs/contract.md`)
  and I5 is ticked above. Three items stay open, none of them doc-only. J1
  bundles the contract document with code (`config.CONTRACT_VERSION`, the page
  refusing an unknown version, `NodeIndex.offsets`, `check_dist` deriving
  widths, a contract test), so only S6's part of the document exists. B2's
  table move changes what a build reads and waits for a rebuild. E13 is the
  owner's call.
