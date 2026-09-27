# Close every open item (owner: "complete all todo items", 2026-09-24)

Owner decision for the mode filter (asked 2026-09-24): **precomputed
exclusions** -- extra map sets for "no flights", "no ferries", "no trains",
built by the normal pipeline, the site stays static. Exclusion only, no
weighting. Cost accepted: ~3x storage and ~4x build time.

Ordered so every pipeline change lands before the next (37 h) rebuild, and the
three exclusion builds run after it.

## Pipeline (one rebuild carries all of these)

- [x] **B1 Tinian's route panel.** LIVE 2026-09-26: ICN->SPN, connect, SPN->TIQ, onward 24 min, 9 h 32. Measured live at 15.00N 145.635E from Seoul:
      total 9 h 34 (right, from the res-6 tier) but legs "Fly ICN -> SPN ...
      Onward from SPN 2 h 15 ... 1 h 3 min by highway" -- the itinerary and mode
      arrays are per res-4 hover cell, whose representative child is on Saipan.
      Exit: at that point the page names the TIQ leg and books no highway across
      the channel, while Saipan is unchanged.
- [x] **B2 Straits narrower than a base cell** -- Messina cut on the real index, live 2026-09-26. (Messina, Helsingor-Helsingborg).
      Landmass parts judged per graph cell (fine where split) instead of per
      base cell. Exit: measured on the named cases in check_fixed_links.py.
- [x] **B3 Fixed links that span a water cell** -- Great Belt, Oresund, Confederation joined; needed way stitching and islet/landfall continuation. Live 2026-09-26. (Great Belt, Oresund Bridge,
      Confederation Bridge) become explicit ground edges, highway links only
      (railway links are already in the rail graph). Exit: those three joined in
      check_fixed_links.py, the six judged bridges still joined, Tinian and
      Shodoshima still cut.
- [x] **B4 The 부산 KTX label** -- via-qualifiers the ride never passed are dropped. Live 2026-09-26. names the plain corridor, not a (...경유)
      variant, at equal cost. Exit: live seoul.rail.json reads
      `경부선 KTX: 서울 → 부산` at 부산.

## Exclusion variants (after B1-B4)

- [x] **V1** `build-all --exclude air|ferry|rail` -- no-air at 63.9% coverage from Seoul, ~1 MB tiles per origin; the three builds running 2026-09-26. writes a variant tree beside
      the normal one; cache keys, index and deploy aware of it.
- [x] **V2** The page offers "avoid flights / ferries / trains", loads the
      variant, says which map is showing, and keeps it in the permalink.
      LIVE 2026-09-27, browser-checked from Seoul: no flights -> New York and
      Tinian "no scheduled route", Okayama 23 h 21 (5 h 18 with flights);
      no trains -> Gumi 3 h 05 (2 h 41 with trains).
      Known limit: variants ship no res-6 reading tier or fine-route
      override, so a variant reads the ~20 km area's representative -- and
      can print LESS than the full map, which reads the point itself
      (Tinian with ferries avoided: 7 h 38, the Saipan-side time, against
      9 h 32). Fix: build the variants with the reading tier and override
      (~35 h, ~50 GB); not done without the owner's go-ahead.

## Page

- [x] **P1 Carry-on only.** LIVE: 15 + 10 min off flown journeys, IATA GPS 2024 and BCAS 2024, disclosed. Page-side, for the journey on screen, disclosed as
      such; the bag share of the airport constants declared with provenance.
- [x] **P2 Place name at Tinian** -- 'a point near Saipan' (20 km threshold). Live. reads "Saipan": the gazetteer (GeoNames
      cities15000) has no town on Tinian.

## Order of builds

1. B1-B4 + V1 merged and tested -> normal rebuild -> deploy -> verify.
2. The three variant builds -> deploy -> verify V2.

## Status 2026-09-27

Everything is live, V2 included (deploy 2026-09-27, all checks passed).

## Status 2026-09-26

Everything but V2 is live and browser-verified (rebuild26, deploy 2026-09-26,
all checks passed, 0 console errors). V2 -- the page's Avoid selector -- is
built and tested but shows nothing until the three variant sets are complete
and reindexed; they are building now.
