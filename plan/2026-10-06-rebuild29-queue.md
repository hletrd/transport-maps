# Rebuild 29: what waits for it (opened 2026-10-06)

The owner's decision (2026-10-06): fixes that only reach visitors through a
rebuild are collected here and shipped together, not one rebuild each. The
release checklist is `plan/2026-10-02-rebuild27-release.md`, as run for
rebuild 28.

## Queued

- [x] **Ferry landings on every shore of a water straddler** (a87abc1).
      Rupat read "no route" from every origin: Natural Earth's coast puts the
      Tanjung Kapal pier in water nearer Sumatra, so the Dumai ferry joined
      Sumatra to itself. Measured from Seoul on the full graph: 321 cells
      gained (Rupat 154, Moere og Romsdal 61, Aland/Turku 32, Batam 29,
      Troms 19, Natuna 12, Maldives, Penghu, Paracels, Sulu), 1,929 faster
      (median 8 min), none lost or slower.
      Verify after the rebuild: `?from=seoul&to=1.85,101.55` gives a time with
      a Dumai ferry leg.

- [x] **Build speed** (2026-10-07..09), measured on h200 with one origin
      (Seoul) alone, outputs byte-identical to the code before:
      setup 20.2 -> 9.7 min, origin 14.2 -> 5.0 min. GC paused for setup and
      frozen before origins (3fb7059); prepared band cover (24f1249); h3 and
      GeoJSON coordinates via numpy (e40b74c, 696c3d2); road lookup
      vectorised (19bf623, 2a1b90e); tree passes vectorised (48604d0).
      Launch with `scripts/h200_rebuild.sh start` (no numactl, no trust
      override), release with `finish`, deploy with deploy_from_h200.sh.
      Measure the parallel per-origin time: rebuild 28 ran ~2.8x slower per
      origin in parallel than alone.

## Shipped 2026-10-10 (build 534dec3b-20261010T113421Z)

Started 15:44 with `scripts/h200_rebuild.sh start 2026-10-10`; inputs checked
online first (ourairports.csv updated; Wikipedia 3,985 articles, 51,806
year-round pairs; Natural Earth, GRIP4 and the OSM extracts unchanged).

- Variants finished 19:09 (no-rail), 19:22 (no-ferry), 19:48 (no-air): about
  4 h from setup, against ~12-16 h in rebuild 28 on the same workers.
- The full map lost an hour: 48 workers did not fit the memory pre-flight
  (12 GB each against 693 GB available) and the launcher's subshell died
  without logging it (fixed, cdc3ee5); restarted at 44, then split with a
  56-worker tail in repo-rail once two variants were done (r29-full-tail.sh
  on h200), final pass exit 0 at 20:44.
- finish: 1,464 origins, 0 variant cells faster than the full map.
- Solver deployed (the first pull broke through aws-proxy and redeployed the
  old bundle; the retry carried the new one, buildId checked).
- deploy_from_h200.sh: 10 batches of ~15 GB, 21:10 -> 22:16 including the
  gates and the browser stage, against ~6 h through the Mac. ALL CHECKS PASSED.
- By hand on the live site: Rupat 17 h 38 from Seoul via KUL -> PKU with
  1 h 05 by ferry (was "no route"); Yeongheung-do 2 h 18; Heuksando 9 h 02,
  10 h 09 avoiding rail, no route avoiding ferries; the destination dot
  follows a drag with the route put away and redrawn on release; the map
  from a point off Hwaseong-si shown; console clean.

## When to start

When the owner asks, or when the next rebuild-gated fix lands here.
