# Rebuild 27: what it carries and how it ships (2026-10-02)

Started 2026-10-02 17:20 from `ee35274` (chain: full, no-air, no-ferry,
no-rail; log `data/build/rebuild27.log`).

## Carried by the rebuild
- Every base cell a strait runs through is split and judged shore by shore
  (`graph/refine.straddler_mask`): 3,542 cells split for that reason alone.
- Routes re-crawled after the C13-7 cache and parser fixes: 68,374 pairs
  (68,152 before; 518 added, 296 dropped).
- The solver bundle (`data/build/solver`) written from the full build's graph.
- The heritage-rail clause in `modeDetail.rail` (DEF16-3).

## Not carried, by decision
- Per-fine-cell mode splits in `.over.bin` (the Gumi-style breakdown that
  differs from the total): measured from Seoul at +1.0-3.2 M entries per
  origin (19-62 MB raw), ~100 GB over the full set and the three variants --
  more than the web host has free. The page already notes when the itemised
  modes and the total differ.
- **A15** (border control per zone entered; zone memberships), owner
  approved 2026-10-02, landed in code 2026-10-03 AFTER this rebuild started.
  It is a model change for the NEXT full build, not this one:
  `plan/2026-10-02-rebuild28-model.md` has the change, the measured
  before/after and its release steps. Do not merge it into the main checkout
  while this chain runs -- a later chain step would import the new model.
  The `add-counts` step below still works with that code (FORMAT-1 bundles
  stay readable and are the only ones `add-counts` accepts).

## Code freeze while the chain runs
Each step of the chain is a fresh `uv run` from the main checkout, so the
variant builds use whatever `src/` holds when they start. The full build ran
from `ee35274`; the variants will run with the commits merged since, all
designed and tested output-identical (fa12fdd, 4924efb, 4d49eb8, 14b7d00,
72e0163, 6a23da8, c97bdf4, c93c321, 48ca6bb, 353d7a7, 7db64fe, 3c94bfb,
b3806b3 -- identity, progress records, speed, calibration values moved with
values unchanged, wording). Nothing that changes the model or the inputs is
merged until `ALL BUILDS DONE`: A15 waits on branch `rebuild28`, G2 likewise.
The "no cell faster than the full map" check below is the backstop.

## Release checklist (in this order)
- [x] Chain finished: `ALL BUILDS DONE` in the log, no `CHAIN STOPPED`.
- [x] Every variant: no cell faster than the full map (all origins).
- [x] `hover_cells.bin` and `reading_parents.bin` unchanged against the server
      (the batched deploy requires it; it refuses otherwise).
- [x] `uv run transport-maps reindex`; index.json lists the variants and
      `solver: {wire: 1}`.
- [x] Give the bundle its node counts (rebuild 27's bundle predates them, so
      the service would answer without legs):
      `uv run python -m transport_maps.service.bundle add-counts data/build/solver dist`
      -- refuses unless dist/index.json's buildId is the bundle's.
- [x] `bash scripts/deploy_solver.sh` (bundle from this build; proves a solve).
- [x] `bash scripts/deploy_verify.sh` (batched if space is short) -- ALL CHECKS.
- [x] Browser: four viewports; Avoid options; Tinian; a dragged exact point with
      a destination shows the on-demand line; console clean.
- [x] Map from any point (merged 2026-10-04, 3d7878a): drop the marker away from
      a city -> the loading notice (counter, bar, Cancel) -> the hexagon map
      "measured from the point you chose" -> hover readings -> a destination's
      legs answered from the kept tree -> Back to the city's map; Cancel and a
      failure fall back to the city's map. `curl /api/map` shows mapVersion 1
      and count 90,740 (deploy_solver.sh checks both).
- [x] Then, separately: drop `blob:` from `script-src` and `worker-src` in
      `deploy/worldmap-security-headers.conf` (MapLibre 6 no longer needs it;
      measured working without it), install the snippet, and verify in the
      browser. Not before the new page is live: the MapLibre 5 page still
      needs `blob:` and would draw an empty globe without it.

## Shipped as rebuild 28 (2026-10-06)

Rebuild 27 was skipped (owner, 2026-10-05); the checklist above ran against
rebuild 28, built on h200 (build 54623628-20261005T063921Z, service date
2026-10-04). Every box was ticked on this build:

- Four builds, each `exit 0`: full map 03:19, no-air 21:32 (10-05), no-ferry
  03:30, no-rail 04:14. The no-ferry and no-rail builds were split across a
  second checkout and merged back (`r28-handoff.sh` on h200).
- No variant cell faster than the full map: 0 cells in r6 and hover arrays,
  all 1,464 origins, all three variants (and not vacuous: from Seoul, 3.69 M
  cells slower without flights, 279 k without trains, 36 k without ferries).
- reindex: 1,464 origins, variants air/ferry/rail. Bundle is FORMAT 2 with
  nAirports and nStations, so no add-counts.
- deploy_solver: Seoul -> Gumi 163 min; /api/map mapVersion 1, 90,740 cells.
- deploy_verify: batched (67 GiB free, 144 GiB to stage), ALL CHECKS PASSED,
  console clean at 1280x800, 820x1180, 390x844, 844x390.
- By hand on the live site: Yeongheung-do 2 h 18 by road; Heuksando 9 h 02 and
  Bigeum 5 h 23 by ferry (no route with ferries avoided, 10 h 09 without
  trains); the map from a point off Hwaseong-si -- loading notice with Cancel,
  then the hexagon map "measured from the point you chose" after 11 s; LSIB
  borders, West Bank, Gaza and Golan dashed.
- CSP: `blob:` dropped from script-src and worker-src after a report-only run
  refused nothing; browser_verify passes against it (ac39c9e).
- Found on the way: the batch free-space check read one xargs run's `du`
  total (a72b5bf); eight more airports cut off by year-round service, named
  in validate.KNOWN_ISOLATED_AIRPORTS (4e5cdee).
- Open, not acted on: GA4 now posts to `analytics.google.com` and
  `www.google.com/g/collect`, which connect-src does not allow (it has
  `*.analytics.google.com`, which does not match the bare host), so the
  enforced CSP blocks collection today. Widening it is the owner's call.
