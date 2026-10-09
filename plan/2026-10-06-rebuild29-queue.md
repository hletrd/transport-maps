# Rebuild 29: what waits for it (opened 2026-10-06)

The owner's decision (2026-10-06): fixes that only reach visitors through a
rebuild are collected here and shipped together, not one rebuild each. The
release checklist is `plan/2026-10-02-rebuild27-release.md`, as run for
rebuild 28.

## Queued

- [ ] **Ferry landings on every shore of a water straddler** (a87abc1).
      Rupat read "no route" from every origin: Natural Earth's coast puts the
      Tanjung Kapal pier in water nearer Sumatra, so the Dumai ferry joined
      Sumatra to itself. Measured from Seoul on the full graph: 321 cells
      gained (Rupat 154, Moere og Romsdal 61, Aland/Turku 32, Batam 29,
      Troms 19, Natuna 12, Maldives, Penghu, Paracels, Sulu), 1,929 faster
      (median 8 min), none lost or slower.
      Verify after the rebuild: `?from=seoul&to=1.85,101.55` gives a time with
      a Dumai ferry leg.

- [ ] **Build speed** (2026-10-07..09), measured on h200 with one origin
      (Seoul) alone, outputs byte-identical to the code before:
      setup 20.2 -> 9.7 min, origin 14.2 -> 5.0 min. GC paused for setup and
      frozen before origins (3fb7059); prepared band cover (24f1249); h3 and
      GeoJSON coordinates via numpy (e40b74c, 696c3d2); road lookup
      vectorised (19bf623, 2a1b90e); tree passes vectorised (48604d0).
      Launch with `scripts/h200_rebuild.sh start` (no numactl, no trust
      override), release with `finish`, deploy with deploy_from_h200.sh.
      Measure the parallel per-origin time: rebuild 28 ran ~2.8x slower per
      origin in parallel than alone.

## When to start

When the owner asks, or when the next rebuild-gated fix lands here.
