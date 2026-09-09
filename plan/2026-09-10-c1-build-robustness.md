# Plan: build-all failure modes, artifact consistency, verification scripts

Source findings: `_aggregate.md` section A (A3–A18), E1 (verify half), E15,
G1–G2, H2, H10, H11, I4. Per-agent detail: `code-reviewer.md`, `perf-reviewer.md`,
`verifier.md`, `test-engineer.md`, `tracer.md`, `architect.md`, `debugger.md`,
`security-reviewer.md`.

A1 and A2 (numpy import; keyword station maps) were fixed by another agent in
`7b7e601` and `edf4b0d` while the review ran and are closed.

Orchestrator constraint: a `build-all` and a water build owned by the
orchestrator are running; do not start/stop them, do not rewrite `dist/` or
`data/`. Source edits here do not affect already-running processes.

## Cycle 1 (this run)

- [x] **A3** A failing gate inside a forked worker must abort the run, not hang
      it: `_solve_one` returns a failure record (or raises a plain `Exception`
      that `multiprocessing.pool` propagates) instead of `SystemExit`; the
      parent terminates the pool and exits non-zero with the message
      (`cli.py:83-88,109-112,187-191`). Test: forked pool with two origins,
      one failing → `main()` raises `SystemExit` within a timeout. Mutation:
      restore `raise SystemExit` in the worker → test times out/fails.
- [x] **A5** `sources/urban.py:34-46` downloads its own Natural Earth populated
      places zip through `sources/_utils` (URL constant in `urban.py`) instead
      of calling `emit.places._download()` with the wrong signature and
      dataset; the cache key includes the URL. Test: with an empty cache dir
      and a stubbed download, `_places()` reads the zip it fetched. Mutation:
      revert to the `places_mod._download()` call → `TypeError`.
- [x] **A8** `validate.check_coverage` treats an empty considered set as
      coverage 0.0 (fails the gate) rather than NaN (`validate.py:33-39`).
      Test: all-excluded universe → gate raises. Mutation: drop the guard →
      NaN passes.
- [x] **A4** `_ferry_edges` recognises a fine cell and its adjacent unsplit base
      cell as ground-adjacent (compare at the base resolution:
      `cell_to_parent(fine, SOLVE_RES)` adjacency, and fine-to-fine across a
      split boundary) so the ferry does not duplicate the `hex_edges` cross
      edge (`build.py:301-307`). Test: the tracer's 7-cell synthetic fixture
      builds. Mutation: restore same-resolution `grid_disk` only → duplicate
      pair `RuntimeError`.
- [x] **E1 (verify half)** `scripts/browser_verify.sh` derives the expected city
      count and band count from the deployed `index.json` (`curl` it) instead
      of hard-coding 157/37; the scheme count stays a page fact (12) but is
      read from a single place. `scripts/deploy_verify.sh` checks that
      `web/index.html` does not state a city count that disagrees with
      `index.json` (grep) before rsync.
- [x] **D14/FD-5** `browser_verify.sh` asserts on `borders` and on a *visible*
      disclaimer element, not the `<noscript>` text.

## Cycle 2

- [ ] **A6a** Write every per-origin artifact through `_utils._atomic_write`
      (tmp + rename in the same directory) — `hover.py:71-72`,
      `itinerary.py:70-71`, `modes.py:109-110`, `rail_detail.py:90-93`,
      `routes_json.py:53-54`; `tiles.py` already moves atomically (verify it
      is a rename, not a copy, on this filesystem).
- [ ] **A6b** Write `hover_cells.bin` and `index.json` *last*, after every origin
      succeeded (`cli.py:174`).
- [ ] **A6c** Build identity: `build_id` in `index.json` and a
      `dist/origins/{slug}.meta.json` sidecar per origin; `deploy_verify.sh`
      refuses when any sidecar id differs from `index.json`'s.
- [ ] **A6d** `deploy_verify.sh`: stage to `/var/www/worldmap.new` and swap
      with a rename (or rsync into a versioned directory + symlink) instead of
      in-place `--delete`; deploy `index.json` last.
- [ ] **A7** Make `solve` and `index` call the same `solve_and_emit` as
      `build-all` (same file layout, same gates) or remove them; `index`
      refuses to list an origin whose files are missing (`cli.py:233-263`).
- [ ] **A10** Stable secondary key in `osm.rail_routes` de-duplication
      (`osm.py:202-207`).
- [ ] **G1** Cache keys: `routes.parquet` and the parsed-destination cache keyed
      on `_params_hash` of the airports table hash, `_SANITY_PAIRS`, cargo
      regex, `_SKIP_PREFIXES` and the wikitext cache stamp (`routes.py:242-244`);
      `urban_mask` keyed on the full cell-list hash and `PLACES_ZIP`
      (`urban.py:51-52`); `ferry_links` includes `ANTIMERIDIAN_EPS_DEG`
      (`osm.py:180-185`); `road_class_grid` includes `GRIP4_URL` (`roads.py:59`);
      land-cell stamp names the polyfill method (`landmask.py:176-178`).
      Each gets a `test_cache_provenance.py` case whose mutation is "change
      the constant, cache still hits".
- [ ] **H2** Hoist `stop_names` and `_line_between(routes)` into `_build_all`'s
      `shared` (computed once in the parent) so no polars runs inside forked
      workers (`rail_detail.py:43-75`, `cli.py:102-103,149-151`); likewise
      hover parents / representative children (`hover.py`, `itinerary.py:57-58`,
      `modes.py:98-99`).
- [ ] **H10** `tiles.py`: write tippecanoe input under `data/build/tmp/`, always
      delete it in `finally`, and cap tippecanoe threads to the worker budget.
- [ ] **A12** Count and log dropped ferry crossings; fail above a bound like the
      airport drop bound (`build.py:279-334`); book a ferry leg as ferry even
      when the base parents are adjacent (`modes.py`).
- [ ] **A13** Clamp emitted minutes to 65,534 and treat 65,535 as unreachable
      on both sides (`hover.py:67-69`, `app.js`).
- [ ] **A14** Monotonic-ground gate covers cross-resolution edges (`validate.py`).
- [ ] **I4/VER-20** Remove `dist/origins/las-vegas.pmtiles-journal` and exclude
      `*-journal`, dotfiles and `tmp*` from the deploy rsync
      (`deploy_verify.sh:41`). The deletion under `dist/` waits for the
      orchestrator's go-ahead (its rule on `dist/`); the rsync exclusion can
      land now.
- [ ] **A17** Validate slugs in `load_origins` with `_SLUG_RE`; escape names in
      `scripts/expand_origins.py:94-99` with `tomllib`-safe quoting.
- [ ] **A18** `scripts/adsb_extract.py`: sanitise the tag into the cache path
      and bound the download size.

## Cycle 3+

- [ ] **A6e** Resumability: `--skip-existing` that trusts a sidecar with the
      current `build_id`; unordered `imap_unordered` for progress (H11).
- [ ] **A9** Investigate the south-pole cap dissolve with the debugger's fixture;
      either handle the polar cap as a special geometry or exclude it from
      `check_bands_cover`'s sample (`landmask.py:135-144,217`, `bands.py:62-85`).
- [ ] **A11** Make a `continue`-triggering wikitext batch resolvable
      (`routes.py` crawl loop) with a test.
- [ ] **A15** Immigration-zone rules: one table used by air and ground; no border
      charge on airside transits (`build.py:88-93`, `countries.py`). Model
      change — document the before/after per CLAUDE.md.
- [ ] **A16** `check_bands_cover` samples the tiles tippecanoe wrote (read the
      PMTiles back) rather than the GeoJSON.
- [ ] **G2** Raw downloads: cache by URL hash with a recorded ETag/size; refresh
      policy documented.
- [ ] **E15** Once the orchestrator's water rebuild lands, `deploy_verify.sh`
      checks `water.pmtiles` metadata (`maxzoom`, layer fields) against
      `emit/water.py`'s constants.

## Progress

- 2026-09-10 cycle 1: plan written; cycle-1 tasks implemented in the cycle-1 commits.
