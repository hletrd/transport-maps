# Rebuild 28: model changes waiting for the next full build (2026-10-02)

Rebuild 27 (`plan/2026-10-02-rebuild27-release.md`) was started from
`ee35274` and ships the model it started with. What is listed here is in the
code but in no shipped artifact: it takes effect with the first full
`build-all` started after it is merged, and not before.

**Do not merge these commits into the main checkout while rebuild 27's chain
is still running.** The chain runs full, no-air, no-ferry and no-rail as
separate processes; a step started after a merge would import the new model
and mix two models in one release. `inputsHash` would change, so `--skip-existing`
would not trust the earlier steps' records either.

## A15: border control per zone entered (owner approved 2026-10-02)

Landed 2026-10-03 on branch `worktree-agent-a5f15e75519ed4aa5`:

- `0b36a16` fix(graph): correct immigration-zone membership.
- `6791764` feat(graph): charge the border once per airside journey.

### What changes

1. **Airside transit.** The border charge (`calibration.toml [border_min]`,
   unchanged figures, still published-figure defaults) is paid once per
   airside journey that leaves its zone, by the first flight that crosses, at
   that flight's larger terminal -- the figure a nonstop flight paid before.
   Seoul -> Narita -> Frankfurt now pays 45 min once, not twice. Every
   airport has its two nodes twice (`graph/build.py`, `_air_edges`, has the
   edge table); a landside connection (out through the arrival hall and back
   in), and any connection in the US (`transfers.NO_AIRSIDE_TRANSIT`: every
   arriving passenger is admitted at the first US airport), return the
   traveller to the domestic layer, so the next crossing pays again.
2. **Zone membership** (`graph/transfers.py`, each with its source):
   Åland, Monaco, San Marino and the Vatican join Schengen; the Isle of Man,
   Jersey and Guernsey join the Common Travel Area; Ercan is filed under the
   north (`CYN`), the code the ground already used.
3. **Checked and NOT changed**, against CR-20's premise: the French overseas
   departments keep their border -- they are outside Schengen and a Paris
   flight passes a border check at the metropolitan airport (Assemblée
   nationale question 15-1639QE, answer of 16 Jan 2018; 2010 removed only the
   second check, on arrival). Andorra keeps its border (outside Schengen).
   Liechtenstein was already in Schengen.

### Measured before/after (2026-10-03, read-only, on rebuild 27's own inputs)

Air-only model of rebuild 27's `airports_a1c21b5e` and `routes_21691ca7`
(4,008 airports, 68,368 plausible directed flights): one landside node per
airport with processing, disembark, connection and the same-airport landside
reconnect; no ground between airports. 3,740 origin airports with a
departure, 13.7 M reachable (origin, destination) airport pairs.

| Change | Pairs that move | Direction | Saving where it moves |
|---|---|---|---|
| Zone membership only | 41,574 (0.3%) | 38,698 faster, 2,876 slower | median 42 min |
| Airside rule, on top | 7,931,033 (57.7%) | all faster | median 45 min, max 225 |
| Both | 7,949,820 (57.8%) | 6 slower | median 45 min |

- Savings under 45 min (2.84 M pairs) are smaller terminals' charges (25 or
  35 min) and the B1 interplay: where walking out and checking in again
  (disembark + processing) beats the airside connection, that path re-pays
  the border, so the saving is `B + min(conn, L) - min(conn, L + B)`, between
  0 and B. 1.64 M pairs save 46-90 min and 173 k more than 90 (two or more
  crossings in one airside journey).
- The six slower pairs are ECN<->LCA, ECN<->PFO and LCA<->PFO via Ercan:
  the route network holds ECN-LCA and ECN-PFO (parsed from Ercan's own
  Wikipedia article), which were a border-free "domestic" hop under CY.
- Spot checks (minutes, airport to airport): ICN-FRA, ICN-CDG, ICN-LHR,
  ICN-MEX, CDG-RUN, IST-ECN unchanged (nonstop, or the US rule); ICN-GRU
  1652 -> 1607, ICN-JNB 1251 -> 1206, NRT-ECN 1049 -> 1004; LHR-IOM
  215 -> 170 (CTA); LCA-ECN 143 -> 188.
- Build origins, each read through its nearest airport with departures:
  1,463 of 1,464 change somewhere; median share of destination airports
  that get faster 53.6% (p10 33.3%, p90 82.1%), median saving 45 min. The
  real build adds ground both ends, so the share of CELLS that move will be
  of that order where the fastest route abroad connects in a third zone,
  and zero where it is a nonstop flight.
- Surface edges whose zone charge (45 min, `[land_border]`) goes: ferry
  links parsed in `ferry_links-64a4d35f` with endpoints in the changed
  places, before the length window and dedup -- Åland-Finland 3,
  Åland-Sweden 2, Isle of Man-GB 3, Isle of Man-Ireland 1, Guernsey-GB 2,
  Jersey-GB 2, Guernsey-Jersey 2 (15). Ground edges: Monaco-France (1 cell at
  res 6, 4 at res 7) and San Marino-Italy (2 / 14 cells) lose the crossing
  on 3-17 neighbouring cells; the Vatican has no cell at either resolution.

Scripts: kept outside the repository (scratchpad); the method is above, and
the numbers can be re-taken from any build's airport table and route network.

### Format changes the next build writes

- `.json` per origin: international-layer nodes listed under ids past the
  stations, `offsets.intl` added; the page's entry id is unchanged (the two
  arrival nodes of an airport swap ids where the cell was reached from the
  international one). No `contractVersion` bump: additive, and an older
  page reads it correctly. `docs/contract.md` updated.
- Solver bundle FORMAT 2 (`nNodes = nCells + 4 x nAirports + nStations`).
  The service code from this branch reads FORMAT 1 and 2; an older service
  refuses FORMAT 2 by number. The service code must reach the host with or
  before the first FORMAT-2 bundle; `scripts/deploy_solver.sh` already ships
  the code (step 1) before the bundle (step 3), so one run does both.
- Unchanged: `.air.bin`, `.over.bin` (airport ordinals), `.modes.bin`,
  `.rail.*`, the tiles.

### When the next build runs

- [ ] Merge only after rebuild 27's chain is done (see the top).
- [ ] Integration tests against the real caches, which a worktree could not
      run: `uv run pytest -m integration tests/graph/test_build.py
      tests/test_golden.py` (`test_incheon_reaches_narita_directly` now
      expects the international arrival node; Seoul-London is nonstop and
      should not move).
- [ ] Before/after on the ground-check routes (CLAUDE.md): re-run
      `scripts/ground_check.py`; it is ground-only, so it should not move.
- [ ] Compare three origins' `.bin` against rebuild 27 (Seoul, Paris, a
      small-country origin): the share of cells faster, and that none is
      slower except through Ercan.
- [ ] Browser: a transit itinerary (Seoul -> a South American city) reads
      "Fly ICN -> X", "Connect at X", "Fly X -> Y" with the legs summing to
      the total; an on-demand solve through the bundle shows the same legs.

### Found while measuring, not changed (each a separate decision)

- Puerto Rico, Guam, the US Virgin Islands, American Samoa and the Northern
  Marianas are zones of their own (OurAirports codes), so SJU-JFK pays a
  border it does not have.
- Western Sahara (EH in OurAirports, Morocco on the ground): Laayoune and
  Dakhla flights from Casablanca pay a border.
- Bonaire (BQ, Netherlands on the ground), Christmas Island (CX, Australia's
  Indian Ocean Territories on the ground) and Somaliland (SO in OurAirports,
  SOL on the ground) disagree between the two country sources.
- Guadeloupe-Martinique flights pay a border between two departments
  (each its own code); whether that desk exists was not checked.
- The B1 interplay above: A15's saving is capped wherever the landside
  reconnect is cheaper than the connection.

## Where rebuild 28 runs: h200 (2026-10-04)

The owner asked for faster rebuilds and named h200 (xylolabs-h200 repo: a
rented 8x H200 node, 192 cores, 1.9 TB RAM, user `work`, only `/default`
persistent; it also serves inference, so roughly 687 GB was free when
checked). Rebuild 27 on the 32 GB Mac ran five workers at most and took 30 h
for the full map, because a worker peaks at 8-11 GB.

- Environment, all under `/default/worldmap`: micromamba with tippecanoe
  2.79.0 and osmium-tool 1.19.1 (conda-forge, `tools/`), uv with Python 3.14
  (`uv-python/`, `uv-cache/`), the repo on branch `rebuild28` (`repo/`).
  numpy 2.5.2, scipy 1.18.1, h3 4.5.0, the same as the Mac.
- Workers: `TRANSPORT_MAPS_WORKERS` (bb44988), refused unless 12 GB a worker
  plus 20 GB fits in 80% of MemAvailable. About 40 fit today, which should
  bring the full map from 30 h to roughly 2-3 h.
- Inputs: G2 makes the build fetch what it needs from upstream, so nothing
  but the code is copied there; OSM extracts come from Geofabrik directly.
- Fast suite on h200: 1563 passed, 7 failed, none touching build output --
  two deploy-gate tests that assume `node` is not in /usr/bin (h200 has it;
  nothing deploys from h200), four departure-list page tests under its node
  20 (the Mac's is newer), and the peak-memory test, whose lower bound reads
  a container RSS above getrusage's high-water mark. The unit guard in that
  test does go red on Linux (checked).
- Output comes back to the Mac over ssh (ProxyJump aws-proxy) and is deployed
  from there as usual; h200 holds no credentials for the web host.
