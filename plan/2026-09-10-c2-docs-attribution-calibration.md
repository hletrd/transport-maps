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

- [ ] **O2 / B2 (comment half)** `calibration.toml`: the seven unlabelled
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
- [ ] **O3 / E8** JSON-LD `index.html:46` and the ten comment sites
      (`refine.py:3,7`, `bands.py:13,17,148-157`, `tiles.py:11,17`,
      `hover.py:35`, `countries.py:91`, `grid.py:3`, `roads.py:100-101`,
      `ground.py:55-57`, `rail.py:24`) carry the h3 4.5.0 figures: res 4
      26.07 km edge / 1,770 km² / 45 km across; res 6 3.72 km / 36.1 km² /
      6.5 km; res 7 1.41 km / 5.16 km² / 2.4 km (DOC-3, VER-31, CR-9). The
      JSON-LD loses the airport/station/ferry counts (web plan O4).
- [ ] **O8** `emit/index.py:19-21` comment; the OSM `usedFor` names rail
      relations, ferry ways, coastlines and GRIP4; README :58/:63 and
      `llms.txt:53` say "ferry ways"; Natural Earth `usedFor` matches the README
      row (DOC-7, VER-32).
- [ ] **O10** Stale-number batch: `build.py:380`, `modes.py:10`,
      `calibrate_ground.py:7,47`, the two sample sizes explained in
      `ground.py:17` / `ground_check.py:5` / `urban.py:4-6`, `app.js:233,319,
      618-622`, `places.py:3`, `airports_json.py:3`, `nodes.py:32`,
      `validate.py:14,133`, `cli.py:170`, `bands.py:25`, `tiles.py:9-19,35`,
      `osm_rail.sh:11-16`; delete `landmask._cells_touching` (with G1) (DOC-14,
      VER-37).
- [ ] **O5** `web/README.md` pin note: 5.24.0 is the last 5.x and carries
      CVE-2026-85061 (fixed only in 6.4.1); the vendored patch and its hashes
      recorded (security plan Q3) (DOC-4).
- [ ] **O7** Bookkeeping: the archived web plan's completion line says
      "verified on the local preview; not deployed"; H2's rail half ticked
      with `bf9e5cc`; E8 one entry; D17 closed; `593c231`'s note corrected
      (old = 90,659 res-5 arrays, new = 90,740 `hover_cells.bin`);
      `plan/README.md` status column and paths; "13 of 15" → the SDD ledger's
      11 complete + 4 done outside the plan; a header on
      `cycle-1/_aggregate.md` saying its status column is a snapshot at
      `edf4b0d` (CRIT-4, VER-28, VER-38, DOC-6, DOC-16, DOC-17, DOC-18).
- [ ] **O9 / E10** Spec status → "Superseded in part — see As built"; a short
      "As built (2026-09)" section with the delta table from DOC-9; the pipeline
      plan gets a header pointing at the SDD ledger and stating that Tasks 9,
      10, 12, 13 were completed outside the plan or replaced. The pipeline plan
      stays under `docs/` (its ledger is the record).
- [ ] **O12 / E11** `water.py` uses `--no-simplification-of-shared-nodes`
      (takes effect on the next water build); the sky call keeps
      `atmosphere-blend` and a comment names the inert keys (DOC-21).
- [ ] **O11** `web/vendor/OFL.txt` (IBM Plex LICENSE.txt) and one line in
      `web/README.md` Typography (DOC-15).
- [ ] **O14** `data/origins.toml` header mentions the `expand_origins.py` half
      (DOC-23). **O15** `<meta charset>` first in `<head>` (DOC-25). **O16**
      `llms.txt` states the array sizes and that `hover_cells.bin` orders them
      (DOC-27).
- [ ] **E14** Document the `h3shape_to_cells_experimental` dependency in
      `landmask.py` and pin its `contain="overlap"` behaviour with a test on a
      small island polygon (the cache-free islands test already exists — make
      the dependency explicit in its docstring and the README).
- [ ] **O4 (docs half)** README "550+" → "the cities in `data/origins.toml`
      (553 today; the live build may lag)"; `llms.txt` coverage sentence →
      the 90 % gate wording (DOC-11, DOC-20).
- [ ] **O1 (llms.txt half)** with the web plan.

## Cycle 3

- [ ] **J1 / S1 (document)** `docs/contract.md`: file set and suffix table,
      `index.json` schema by `contractVersion`, binary layouts (widths,
      ordering, sentinels, clamp), PMTiles layer/props/LODs, the rendering
      invariants (faster band on top; water above bands), node-offset
      arithmetic, the endianness assumption; `config.CONTRACT_VERSION = 2`;
      the page refuses an unsupported version through `fatal()`;
      `NodeIndex.offsets` replaces the six hand-derived sites; `check_dist`
      derives widths from `modeChannels`; a contract test (design in
      `architect.md` §4 J1). The S parts (`buildId`, `builtAt`,
      `hoverCellCount`, `modeChannels`, `graph`) land in cycle 2 (build plan).
- [ ] **B2 (table move)** `[ground]`, `[urban]` and the air-bound constants
      into `calibration.toml` with labels; one `calibrate.load()` threaded
      through the build context; `_land_border_min` no longer parsed per origin
      (ARCH-8). After the rebuild.
- [ ] **E13** Owner decision on the `pyproject.toml` author email.
- [ ] **I5 (docs part)** The vendored JS hashes table (recorded by the security
      reviewer) in `web/README.md`, and a test that recomputes them (with Q6).
- [ ] **S6** Name the two cross-layer invariants (mode prose; overlap-by-rim
      and `fill-sort-key`) in the contract document.

## Progress

- 2026-09-10 cycle 2: plan written from the cycle-2 aggregate; carries every
  unfinished task from the cycle-1 docs plan (now archived) under its original
  ID. VER-29 (CLAUDE.md band wording) was refuted: the on-disk file already
  says anchors ≥ 6 (changed in `2526673`); D20's wording half stands as done.
