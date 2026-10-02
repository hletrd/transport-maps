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
- [ ] Chain finished: `ALL BUILDS DONE` in the log, no `CHAIN STOPPED`.
- [ ] Every variant: no cell faster than the full map (all origins).
- [ ] `hover_cells.bin` and `reading_parents.bin` unchanged against the server
      (the batched deploy requires it; it refuses otherwise).
- [ ] `uv run transport-maps reindex`; index.json lists the variants and
      `solver: {wire: 1}`.
- [ ] Give the bundle its node counts (rebuild 27's bundle predates them, so
      the service would answer without legs):
      `uv run python -m transport_maps.service.bundle add-counts data/build/solver dist`
      -- refuses unless dist/index.json's buildId is the bundle's.
- [ ] `bash scripts/deploy_solver.sh` (bundle from this build; proves a solve).
- [ ] `bash scripts/deploy_verify.sh` (batched if space is short) -- ALL CHECKS.
- [ ] Browser: four viewports; Avoid options; Tinian; a dragged exact point with
      a destination shows the on-demand line; console clean.
- [ ] Then, separately: drop `blob:` from `script-src` and `worker-src` in
      `deploy/worldmap-security-headers.conf` (MapLibre 6 no longer needs it;
      measured working without it), install the snippet, and verify in the
      browser. Not before the new page is live: the MapLibre 5 page still
      needs `blob:` and would draw an empty globe without it.
