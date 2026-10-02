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
- [ ] **B2 (table move)** `[ground]`, `[urban]` and the air-bound constants
      into `calibration.toml` with labels; one `calibrate.load()` threaded
      through the build context; `_land_border_min` no longer parsed per origin
      (ARCH-8). After the rebuild.
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
