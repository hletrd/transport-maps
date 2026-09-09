# Deferred findings

Findings from the cycle-1 review that are **not** scheduled in a plan. Each
entry keeps its original severity and confidence (never downgraded), cites the
file and line, gives the concrete reason, and states the exit criterion that
reopens it. Repo rules read before deferring: `CLAUDE.md` (the only rule file
present; no `AGENTS.md`, `.cursorrules`, `CONTRIBUTING.md`; `.context/` holds
only the reviews; `docs/` holds the spec and the original plan). Deferred work
remains bound by every repo rule when picked up (signed conventional commits
with gitmoji, no `--no-verify`, Python ≥ 3.14 via `uv`, the design policy).

Security, correctness and data-loss findings are not deferred here: they are
scheduled (with a cycle) in the plans, or recorded as blocked-on-owner in
`2026-09-10-c1-security-and-policy.md`. The two modelling items below are
correctness-adjacent and are deferred under the CLAUDE.md modelling rule quoted
with them.

Run-level instruction that bounds every deferral: the user's brief for this
run — "more details, higher quality and design and ease of usage and UI. Do not
overwork" — and the orchestrator's constraints (bounded scope per cycle; no
rebuilds; no writes under `dist/`/`data/`).

| ID | Finding | Sev / Conf | Citation | Reason for deferral | Exit criterion |
|---|---|---|---|---|---|
| B1 | Expected-wait model bypassed by `arr → cell → dep`; route frequency never affects a journey; rail/ferry carry no headway; contradicts "leave now" copy | High / High (CR-2, CRIT-2, ARCH-17, CR-19) | `src/transport_maps/graph/build.py:163-213,232-334`, `graph/air.py`, `calibration.toml` | A model change that shifts every far band and needs a calibration decision plus a full rebuild the orchestrator owns. CLAUDE.md modelling rule permits documenting rather than silently tuning: "Never silently tune a default … prefer a documented, reproducible error over a hidden one." The *copy* half (say what is and is not waited for) is scheduled in the docs plan (B2) and web plan (D12). | Owner chooses the wait model (connection edge floor, per-class rail headway, ferry headway); rebuild scheduled; golden tests updated with the new figures. |
| A15 | Immigration-zone rules incomplete/inconsistent between air and ground; border control charged on airside transits | Medium / High (CR-20, TR-17) | `graph/build.py:88-93`, `sources/countries.py` | Model change (same CLAUDE.md rule as B1); scheduled as an investigation in the build plan cycle 3, deferred as an implementation until the owner accepts the before/after figures. | Owner accepts the documented before/after on the ground-check routes. |
| H1 | Bands round-trip `mapping()` → `json.dump` (100+ MB/origin) → tippecanoe → `shape()`; 1–3 GB peak per worker | High / High (PR-3) | `contour/bands.py:187`, `emit/tiles.py:28-30` | Performance refactor of the tile path; not user-visible; "do not overwork". | A build wall-clock budget is set by the owner, or memory pressure aborts a build. |
| H3 | Per-node Python loops over ~10 M nodes with an h3 call per predecessor edge and a 480 MB float64 accumulator | High / High (PR-5, CR-30) | `emit/modes.py:60-86` | Performance; vectorising the predecessor walk is a rewrite of `modes.py`/`itinerary.py`. | Same budget trigger as H1; or when C2's per-leg accounting (web plan cycle 3) touches this code anyway. |
| H4 | `_interior` recomputes the slowest-neighbour reduction per band; `_dissolve` overlays already-valid geometries; antimeridian test evaluated twice | High / High (PR-6, PR-21) | `contour/bands.py:120-121,195-197` | Performance; bounded but the contour module is under active change for the res-6/7 levels of detail. | After the res-6/7 contour code settles (first successful 553-origin build). |
| H5 | Forked workers un-share the 10 M-entry `cells` list and `_cell_pos` dict through refcount traffic; caps the build at 5 workers | High / Medium (PR-7) | `graph/nodes.py:42-44,60,123`, `cli.py` | Architectural change to `NodeIndex` storage (numpy uint64 array + searchsorted). | Same as H1, or when memory prevents the 553-origin build from using its planned worker count. |
| H6 | `mousemove` frame does `queryRenderedFeatures`, two gazetteer scans, three `innerHTML` writes under `backdrop-filter` panels | Medium / Medium (PR-10) | `web/app.js:578-639` | Needs a Performance-panel trace to quantify; not confirmed as a user-visible jank. | A trace shows > 16 ms frames on hover, or a user reports hover lag. |
| H7 | 900 DOM markers re-projected per `move` frame | Medium / Medium (PR-11) | `web/app.js:166-219` | Replacing DOM markers with a symbol layer conflicts with the typeface policy (MapLibre symbol layers need SDF glyphs, not the vendored Plex) — needs a design decision. | Owner accepts either glyph generation for Plex or a capped label count. |
| H8 | `borders.json` and `places.json` parsed on the main thread | Medium / High (PR-12) | `web/app.js:151-160,319-331` | Bounded, but overlaps the web plan's D13 (lazy `places.json`) which is scheduled; borders-as-URL-source is a one-line change scheduled with D13. | Picked up with D13 in web plan cycle 3. |
| H9 | 60 M-edge ground adjacency rebuilt in pure Python duplicating the cached `grid.native_edges` | Medium / High (PR-13) | `graph/ground.py:81-130` | Performance refactor of graph assembly. | Same as H1. |
| H12 | Vendored `maplibre-gl.js` (1.05 MB) served `no-cache` | Low / High (PR-20) | `deploy/worldmap.atik.kr.conf:44-63` | Content-addressed vendor filenames are a deploy-layout change; `deploy/README.md` explains why `no-cache` was chosen. | When the vendor directory is next refreshed (I2). |
| H13 | `hover_cells.bin` is 725 KB of sorted uint64 for ~90 k entries | Low / High (PR-22) | `emit/index.py:91-99`, `app.js:38-40` | Format change to the pipeline↔page contract; wait for the contract doc (J1, docs plan cycle 2). | J1 done. |
| H14 | Linear `find`/`filter` over airports and cities per keystroke | Low / High (PR-23) | `web/app.js:504-507,728-770,855` | Not measurable as lag at 4 k rows; indexing adds code for no visible gain. | Search shows measurable input delay (> 50 ms) in a trace. |
| J2 | `emit` reaches back into `graph`/`sources`; three emitters are really sources | Medium / High (ARCH-9) | `emit/index.py:104-105`, `modes.py:35,57`, `rail_detail.py:45,72` | Package re-layout; no user-visible gain; "do not overwork". | When a second consumer of `borders/places/water` appears or J1 lands. |
| J3 | `web/app.js` 999 lines, 17 mutable globals | Medium / High (ARCH-10) | `web/app.js` | Module split is a rewrite; the race it hides (C5) is scheduled in the web plan cycle 2. | `app.js` passes 1,500 lines or a second page shares its code. |
| J4 | No injection seams in `build_graph`; tests monkeypatch module attributes | Medium / High (ARCH-13) | `graph/build.py:61-184`, `cli.py:22` | Refactor; partially addressed by F8/F10 tests which will introduce the seams they need. | F10 (graph edge unit tests) is picked up. |
| J6 | `check_ramps.py --respace` rewrites `web/app.js`; tests import `scripts/` via `sys.path` | Low / High (ARCH-21) | `scripts/check_ramps.py:99-110`, `tests/web/test_ramps.py:5` | Tooling hygiene; no user impact. | D20's interpolated-band measurement touches this script. |
| J7 | `config.ROOT` from `__file__`; assumes editable install | Low / High (ARCH-22) | `src/transport_maps/config.py:5` | The package is only ever run from the checkout. | A wheel install is required. |
| J8 | Import-time side effects (`POLARS_MAX_THREADS`, `globals()["_CTX"]`, module caches) | Low / High (ARCH-23) | `cli.py:9,111,188`, `roads.py:26,65`, `countries.py:69-8x` | Refactor with no user impact. | J4 refactor. |
| J9 | `urban_mask` distance ignores the antimeridian; `countries.iso2` re-reads the shapefile on an empty table | Low / High (CR-29) | `sources/urban.py`, `sources/countries.py` | No real city is affected today (reviewer checked). | An origin or urban centre within 0.5° of ±180° is added. |
| E1 (data half) | The served `index.json` is the 157-origin res-5 build while the copy describes 553/res 6-7 | Critical / High (CRIT-1 et al.) | `dist/index.json` | The page-copy and verify-script halves are scheduled (cycle 1); the data half needs the 553-origin rebuild the orchestrator owns and this cycle must not run. | The orchestrator's `build-all` completes and `deploy_verify.sh` passes on it. |
| E15 | Shipped `water.pmtiles` is zoom 11 without lakes | Medium / High (CRIT-19) | `dist/water.pmtiles` vs `emit/water.py:33,121` | The water rebuild is running under the orchestrator; the metadata gate is scheduled in the build plan cycle 3. | The water build lands. |
| E13 | `pyproject.toml` author email looks like a placeholder | Low / Low (DOC-26) | `pyproject.toml:7` | Owner's identity; not for an agent to change. | Owner confirms or edits. |
| I2 (decision) | MapLibre 5.24.0 CVE-2026-85061 | Medium / High (SEC-4) | `web/vendor/maplibre-gl.js` | Not deferred: scheduled in the security plan cycle 2 (patch check / vendored patch). Listed here only so the decision "5.x patch vs local patch vs 6.x" is visible to the owner. | Security plan cycle 2. |
| D17 | Seven unlabelled `console.error("Error")` entries on load | Low / Low (UX-23) | unknown | Scheduled in web plan cycle 2 as an investigation; listed here because its source is unknown and may be outside the repo (extension/harness). | Reproduced in a clean profile. |

Not deferred, for the record: every finding in aggregate sections A (except
A15), C, D (except D17's investigation), E (except E1's data half, E13, E15),
F, G, I is scheduled in a plan with a target cycle.
