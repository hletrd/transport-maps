# Deferred findings

Findings from the cycle-1 and cycle-2 reviews that are **not** scheduled in a
plan. Each entry keeps its original severity and confidence (never downgraded),
cites the file and line, gives the concrete reason, and states the exit
criterion that reopens it. Repo rules read before deferring: `CLAUDE.md` (the
only rule file present; no `AGENTS.md`, `.cursorrules`, `CONTRIBUTING.md`;
`.context/` holds only the reviews; `docs/` holds the spec and the original
plan). Deferred work remains bound by every repo rule when picked up (signed
conventional commits with gitmoji, no `--no-verify`, Python ≥ 3.14 via `uv`,
the design policy).

Security, correctness and data-loss findings are not deferred here: they are
scheduled (with a cycle) in the plans, or recorded as blocked-on-owner in
`2026-09-10-c2-security-and-policy.md`. The modelling items below are
correctness-adjacent and are deferred under the CLAUDE.md modelling rule quoted
with them.

Run-level instruction that bounds every deferral: the user's brief for this
run — "more details, higher quality and design and ease of usage and UI. Do not
overwork" — and the orchestrator's constraints (bounded scope per cycle; no
rebuilds; no writes under `dist/`/`data/`).

## Reopened this cycle (exit criterion met; moved to a plan)

| ID | Was deferred because | Evidence this cycle | Now |
|---|---|---|---|
| H1 | "memory pressure aborts a build" | five workers at 11–12 GB, swap 10.7 of 12.3 GB, 60 MB free, 9.6 GB paged out per 16 min (PR-1) | build plan cycle 3 (R1) |
| H4 | "after the res-6/7 contour code settles" | it settled in 47f0baf; the antimeridian double test is ~115 s per origin (PR-2) | build plan cycle 3 (R2) |
| E15 | "the water rebuild is running" | `dist/water.pmtiles` (867 MB, z0–12, HydroLAKES) landed 00:24 (CRIT-18) | build plan cycle 3 (L12) |
| D17 | unknown source | 0 console entries in the designer's session; the seven were the `.rail.*` 404s C12 removed | closed |

## Deferred

| ID | Finding | Sev / Conf | Citation | Reason for deferral | Exit criterion |
|---|---|---|---|---|---|
| B1 | Expected-wait model bypassed by `arr → cell → dep`; route frequency never affects a journey; rail/ferry carry no headway | High / High (CR-2, CRIT-2, ARCH-17, CR-19; cycle 2 CRIT-2, DOC-19) | `src/transport_maps/graph/build.py:150-154,199-207`, `graph/air.py:55-60`, `calibration.toml` | A model change that shifts every far band and needs a calibration decision plus a full rebuild the orchestrator owns. CLAUDE.md modelling rule: "Never silently tune a default … prefer a documented, reproducible error over a hidden one." The copy half (say what is charged) is scheduled in the web plan (O1) this cycle. | Owner chooses the wait model; rebuild scheduled; golden tests updated. |
| A15 | Immigration-zone rules incomplete/inconsistent between air and ground; border control charged on airside transits | Medium / High (CR-20, TR-17) | `graph/build.py:88-93`, `sources/countries.py` | Model change (same CLAUDE.md rule); scheduled as an investigation in the build plan cycle 3, deferred as an implementation until the owner accepts the before/after figures. | Owner accepts the documented before/after on the ground-check routes. |
| H3 | Per-node Python loops over ~10 M nodes with an h3 call per predecessor edge and a 480 MB float64 accumulator | High / High (PR-5 c1, CR-30; cycle 2 PR: ~30–40 s per origin, third behind R2/R3) | `emit/modes.py:60-86` | Performance; vectorising the predecessor walk is a rewrite of `modes.py`/`itinerary.py`; R2/R3 (scheduled) are the larger costs. | R2 and R3 landed and the per-origin time is still above budget; or C2's per-leg accounting touches this code. |
| H5 | Forked workers un-share the 10 M-entry `cells` list and `_cell_pos` dict through refcount traffic | High / Medium (PR-7 c1; cycle 2 PR-19 measured the mechanism) | `graph/nodes.py:41-47,142`, every `enumerate(idx.cells)` in `emit/*` | Architectural change to `NodeIndex` storage (numpy uint64 array + searchsorted). R3 removes the four worst loops without it. | R3 landed and the worker footprint is still above the cap; or the 553-origin build cannot use its planned worker count. |
| H6 | `mousemove` frame does `queryRenderedFeatures`, two gazetteer scans, `innerHTML` writes under `backdrop-filter` panels | Medium / Medium (PR-10 c1; cycle 2 PR-12/PR-13: 34,135-row scan twice per frame; measured 18.6 ms avg frame, p95 16.8 ms) | `web/app.js:691-736` | Not confirmed as user-visible jank (designer measured 120/120 readouts); the one-per-frame `nearestPlace` fix is scheduled (web plan cycle 3 R8). | A trace shows > 16 ms frames on hover on a non-Apple GPU, or a user reports lag. |
| H7 | 900 DOM markers re-projected per `move` frame; O(labels × placed) collision test | Medium / Medium (PR-11 c1; cycle 2 PR-17) | `web/app.js:265-309` | Replacing DOM markers with a symbol layer conflicts with the typeface policy (SDF glyphs vs the vendored Plex); the grid-bucketed collision map is scheduled (web plan cycle 3 R8). | Owner accepts glyph generation for Plex or a capped label count. |
| H8 | `borders.json` and `places.json` parsed on the main thread | Medium / High (PR-12 c1) | `web/app.js:229,399` | Borders-as-URL-source is scheduled with D13 (web plan cycle 3). | Picked up with D13. |
| H9 | 60 M-edge ground adjacency rebuilt in pure Python duplicating the cached `grid.native_edges` | Medium / High (PR-13 c1; cycle 2: ~2–3 min of the serial phase) | `graph/ground.py:81-130` | Performance refactor of graph assembly; R5 (scheduled) removes the duplicated calls around it. | R5 landed and the serial phase is still above budget. |
| H12 | Vendored `maplibre-gl.js` served `no-cache` | Low / High (PR-20 c1; cycle 2 PR-15 gzip level 1 measured) | `deploy/worldmap.atik.kr.conf:44-63` | Content-addressed vendor filenames are a deploy-layout change; A6d's versioned releases (build plan cycle 3) make vendor assets release-addressed, which satisfies this cheaply; `gzip_static` goes with it. | A6d lands. |
| H13 | `hover_cells.bin` is 725 KB of sorted uint64 for ~90 k entries (125 KB gzipped) | Low / High (PR-22 c1) | `emit/index.py:91-99`, `app.js:67` | Format change to the pipeline↔page contract; wait for the contract doc (J1, docs plan cycle 3). | J1 done. |
| H14 | Linear `find`/`filter` over airports and cities per keystroke (2–5 ms measured) | Low / High (PR-23 c1; cycle 2 PR-18) | `web/app.js:825-867` | Below the 50 ms trigger; pre-lower-casing is scheduled with D8's edit (web plan cycle 3 R8). | Search shows > 50 ms input delay in a trace. |
| J2 | `emit` reaches back into `graph`/`sources`; three emitters are really sources | Medium / High (ARCH-9 c1; cycle 2 architect §2a) | `emit/index.py:104-105`, `modes.py:19,47-50`, `rail_detail.py:46,72` | Package re-layout; no user-visible gain; "do not overwork". S2's `BuildContext` (cycle 3) removes the fallbacks that make the reverse edges dangerous. | A second consumer of `borders/places/water` appears, or J1 lands. |
| J3 | `web/app.js` 1,126 lines, 19 mutable globals, `window.__map` | Medium / High (ARCH-10 c1) | `web/app.js` | Module split is a rewrite; the race (C5/M2) and the TDZ hazard (M3) are scheduled this cycle and collapse six globals into one object. | `app.js` passes 1,500 lines or a second page shares its code. |
| J4 | No injection seams in `build_graph`; tests monkeypatch module attributes | Medium / High (ARCH-13 c1) | `graph/build.py:61-184`, `cli.py:22` | R5 (build plan cycle 3) threads `country`/`zone`/`speeds` into `build_graph`, which is the seam F10 needs. | R5 or F10 is picked up. |
| J6 | `check_ramps.py --respace` rewrites `web/app.js`; tests import `scripts/` via `sys.path` | Low / High (ARCH-21 c1; cycle 2 TE-11) | `scripts/check_ramps.py:99-110`, `tests/web/test_ramps.py:5` | The `sys.path` half is scheduled (gates plan P10); `--respace` is tooling hygiene with no user impact. | D20's interpolated-band measurement touches this script. |
| J7 | `config.ROOT` from `__file__`; assumes editable install | Low / High (ARCH-22 c1) | `src/transport_maps/config.py:5` | The package is only ever run from the checkout. | A wheel install is required. |
| J8 | Import-time side effects (`POLARS_MAX_THREADS`, `globals()["_CTX"]`, module caches) | Low / High (ARCH-23 c1) | `cli.py:9,132,211`, `roads.py:26,63-72`, `countries.py:69-80` | S2's `BuildContext` (build plan cycle 3) removes `_CTX`; the rest is a refactor with no user impact. | S2 lands. |
| J9 | `urban_mask` distance ignores the antimeridian; `countries.iso2` re-reads the shapefile on an empty table | Low / High (CR-29 c1) | `sources/urban.py:87-88`, `sources/countries.py` | No real city is affected today (reviewer checked; no origin within 0.5° of ±180). The page twin (M10) is scheduled in the web plan cycle 3. | An origin or urban centre within 0.5° of ±180° is added. |
| E1 (data half) | The served `index.json` is the 157-origin res-5 build while the copy describes the 553/res 6–7 build | Critical / High (CRIT-1 et al.; cycle 2: rebuild at 20 of 553 at 05:10, ~16–17 h projected) | `dist/index.json` | The page copy, the verify scripts and the counts are made lag-tolerant (cycle 1 E1 halves; cycle 2 O4); the data needs the orchestrator's rebuild, which this cycle must not run. | The orchestrator's `build-all` completes and `deploy_verify.sh` passes on it. |
| E13 | `pyproject.toml` author email looks like a placeholder | Low / Low (DOC-26 c1; cycle 2 DOC-22: it matches the git author) | `pyproject.toml:7` | Owner's identity; not for an agent to change. | Owner confirms or edits. |
| K8 (validation) | `hex_edges`/`native_edges` preallocate `8 * n` slots; the true edge count is unmeasured | High / Medium (FD-4) | `graph/ground.py:91-131`, `contour/grid.py:104-124` | The guard (a clear `RuntimeError` instead of a bare `IndexError`) is scheduled this cycle (build plan K8); measuring the true cross-resolution bound needs a full `build_index`, which the CPU budget under the rebuild does not allow. | The next full build logs `m / cap`; if it exceeds 0.9 the cap becomes a computed bound. |
| N22 | Attribution lives only inside the closed "Sources and method" panel | Medium / Medium (DOC-12) | `web/index.html:107,440-453` | Licence-compliance judgement for the owner (OSMF guidelines accept a collapsed credit behind a clearly labelled control; whether "Sources and method" qualifies is a reading). Scheduled as an owner decision in the web plan cycle 3. | Owner chooses the permanent one-line credit or the panel rename. |
| S3 (shape) | Verification as a shell script re-typing the contract, fifteen selectors, a second writer of `dist/` | Medium / High (ARCH-7) | `scripts/deploy_verify.sh`, `scripts/browser_verify.sh` | The concrete defects (L3, L4, L5, L9, L10) are scheduled this cycle as script fixes and `check_dist.py`; the `window.__diagnostics()` contract and assembling the release outside `dist/` are A6b/A6d work (cycle 3). | A6b lands (the release is assembled outside `dist/`). |
| Q2 (rehearsal) | The corrected CSP has never been exercised against the page | Medium / High (SEC-19) | `deploy/worldmap-security-headers.conf:18` | Needs a scratch nginx or a meta-CSP pass with the browser; scheduled cycle 3 in the security plan (not deferred — listed so the owner sees that the first install must be rehearsed). The live page carries no CSP today, so installing the conf cannot break the current page. | Security plan cycle 3. |
| R8 (nginx) | `gzip_comp_level 1` per request; `gzip_static` would cut ~13 % at zero CPU | Low / High (PR-15) | `deploy/worldmap.atik.kr.conf:79-81` | Server-side change bundled with H12/A6d (owner install). | A6d lands. |
| C13's `browser_verify.sh` viewport checks never fold the sheet | Low / High (FD-1 note) | `scripts/browser_verify.sh:77-86` | Scheduled with L9 (build plan) this cycle; listed so it is not lost if L9 is trimmed. | L9 lands. |

Not deferred, for the record: every finding in aggregate sections K, L, M, N, O,
P, Q, R and S is scheduled in a plan with a target cycle unless listed above;
every cycle-1 finding in sections A, C, D, E (except E1's data half, E13), F, G,
I is scheduled; B1, A15 and the H/J items above are the only deferrals of
cycle-1 findings.
