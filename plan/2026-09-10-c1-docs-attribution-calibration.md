# Plan: attribution, stale docs and comments, calibration provenance

Source findings: `_aggregate.md` E2, E5–E14, B2, D20, J1, J5. Per-agent
detail: `document-specialist.md` (DOC-*), `critic.md`, `verifier.md`,
`architect.md`, `feature-dev-code-reviewer.md` (FD-6..8), `tracer.md` (TR-20),
`debugger.md` (DBG-20).

## Cycle 1 (this run)

- [ ] **E2** Attribution for GeoNames (CC BY 4.0) and HydroLAKES (CC BY 4.0):
      README table rows, `web/llms.txt` source list, the page's credit line
      (`#key .src`) and the `<noscript>` block; JSON-LD `license` replaced by a
      note that the dataset combines ODbL, CC BY-SA and CC BY inputs with a
      link to the credits. Also credit Nominatim/OSM beside address results.
- [ ] **E5** `web/llms.txt`: one consistent description (res 6 refined to 7,
      36 edges / 37 bands, rail and ferry in the graph, HydroLAKES lakes).
- [ ] **E7** `web/README.md`: one font family; twelve measured multi-hue schemes;
      runtime calls to Nominatim and the Google tag disclosed; MapLibre 6 note
      states the cause. `deploy/README.md`: document the `web/ → dist/` copy
      step and the uncached asset classes.
- [ ] **E9** Stale comments and dead constants: `config.py:11,19-24` (grid size,
      "11th band"), `emit/hover.py:7`, `modes.py:95`, `itinerary.py:51`
      (res-5 → `SOLVE_RES`), `app.js:29-34,573-577` ("fastest child" → centre
      child; `solveRes ?? 5` → 6), `app.js:376,923-924` (`band-seams` never
      added), `transfers.py:5-9,53-54` (duplicate unused `STATION_*` and the
      test that pins them), `src/transport_maps/__init__.py` stub `main`,
      `routes_json.py` "Task 9" comment.
- [ ] **E12** README factual claims (lakes source, coast zoom, band count,
      grid resolution) brought in line with the code.
- [ ] **D20** State one separation threshold: CLAUDE.md says ~8, `check_ramps.py`
      uses 6; `app.js:5-12` says 8. Chosen: the measured anchor threshold in
      `check_ramps.py` is the rule; the comment in `app.js` and CLAUDE.md wording
      say "anchors ≥ 6, target 8"; interpolated-band measurement is a
      cycle-3 task in the web plan.

## Cycle 2

- [ ] **B2** `calibration.toml`: every table gets a comment saying *fitted
      against what* or *published-figure default* (six tables lack it:
      identify them from `document-specialist.md` DOC-8); remove the two
      "refitted in Task 12/13" claims that did not happen; move the fitted
      ground speed table and urban factor from `graph/ground.py` into the
      file with their provenance; `mode_detail()` in `emit/index.py:110-112`
      and the page tooltips read the figures from the calibration object
      rather than hard-coding them. Needs care: the running build reads the
      current file — land the comment-only changes first, the table move
      after the orchestrator's rebuild.
- [ ] **E8** Cell-size figures: recompute with h3 v4 `average_hexagon_edge_length`
      / `cell_area` at res 4/6/7 and update every doc and comment that quotes
      them (DOC-9 lists the locations).
- [ ] **E10** Mark the design spec "superseded in part" with a short as-built
      section; tick the pipeline plan's checkboxes to match the SDD ledger,
      and archive it under `plan/archive/` once the last two tasks are
      recorded.
- [ ] **J1** Write `docs/contract.md`: `index.json` schema, binary layouts
      (widths, ordering, sentinel), tile layer/attribute names, mode-channel
      order, node-offset arithmetic; add `contractVersion` to `index.json`,
      check it in `app.js`, and derive `deploy_verify.sh`'s widths from it.
      Then replace the seven hand-derived `n_cells + 2*n_airports` sites with
      one helper on `NodeIndex` (ARCH-14).
- [ ] **J5** `scripts/deploy_verify.sh` and `browser_verify.sh`: repo root from
      the script's own path; host and URL from an env file (`deploy/.env`
      pattern already in `.gitignore`); no `cd /tmp`; screenshots under a
      run-specific directory.
- [ ] **E11** Replace tippecanoe's deprecated `--detect-shared-borders`
      (`water.py:105-108`); drop the inert sky properties under globe in
      `app.js`, keep `atmosphere-blend`.
- [ ] **E14** Document the dependency on `h3shape_to_cells_experimental`
      (`landmask.py:222`) and pin the behaviour with a test.

## Cycle 3+

- [ ] **E13** Owner decision on the `pyproject.toml` author email.
- [ ] **I5 (docs part)** Record the vendored JS hashes in `web/README.md`.

## Progress

- 2026-09-10 cycle 1: plan written; cycle-1 tasks implemented in the cycle-1 commits.
