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

## When to start

When the owner asks, or when the next rebuild-gated fix lands here.
