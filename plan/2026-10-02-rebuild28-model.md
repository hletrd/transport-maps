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

## Year-round scheduled service only (owner decision 2026-10-04)

Reported: China Eastern's Shanghai Pudong-Adelaide flights are seasonal
(20 June - 2 August 2026; chinadaily.com.cn 2026-03-03, visahq 2026-02-01),
yet the network had PVG<->ADL as if year-round. Both articles mark it
'''Seasonal:''', and the parser read every link regardless of its label.

Decision: only year-round scheduled service is a route. Seasonal, Charter,
Seasonal charter and suspended or terminated service is not. "begins <date>"
and "resumes <date>" count once the date is on or before the build date,
"ends <date>" while the date is after it.

Landed on branch `year-round` (from `origin/rebuild28`):

- `5ef2610` feat(routes): parse each destination's service class and dates.
- `5087011` feat(routes): keep only year-round scheduled pairs on the build day.

### What changes (`sources/routes.py`; the rules, with examples, are its docstring)

1. **Each link is a `Listing`**: its class (scheduled, seasonal, charter,
   seasonal charter, or "other" for any other label such as
   '''Hajj & Umrah:'''), any begins/ends/resumes/suspended change with its
   date, and the airline of its row. A label runs to the end of its table
   cell, not just to the next `<br>`. A month or a year alone is read at its
   conservative end (begins June 2027 = 30 June; ends 2027 = 1 January), and
   a date that does not parse ("begins TBA") leaves the link out.
   "(suspended until <date>)" counts as resuming on that date.
2. **Only destination tables are read.** Links in prose ("formerly served
   by", "no scheduled services"), references, footnotes and destination maps
   (`{{Location map~}}` pins mark seasonal and future service by colour
   alone) are not. Neither are subsections headed Charter, Seasonal,
   Historical / Former / Previous, Statistics / Top destinations / Busiest,
   Map(s), Military or Medevac (Cargo was already cut).
3. **Two articles that disagree.** A pair is usually listed by both
   airports. If one lists an airline's service as year-round and the other
   lists the same airline's as seasonal (Aberdeen and Charles de Gaulle on
   easyJet's Paris flights), that airline does not keep the pair; another
   airline flying it year-round does.
4. **Build date.** `routes.service_date()`: the UTC day the process first
   asks, fixed for the run (`TRANSPORT_MAPS_SERVICE_DATE=YYYY-MM-DD` pins it,
   for an offline rebuild of a past build). It is in the route network's key
   and recorded as `serviceDate` in index.json's
   `inputs["wikipedia:airline-destinations"]`.
5. **Caches.** `PARSER_VERSION` 3, and every new pattern is in
   `_parser_key`, so `airline_destinations.json` is re-crawled (about 80
   requests, which G2 already makes once a day). The article cache keeps the
   parse, not the decision, so a build on another day judges the dates again
   without fetching anything.

### Measured (2026-10-04, worktree re-crawl)

Method: one fresh fetch of all 3,962 articles linked from rebuild 27's
airport table (`airports_a1c21b5e`, 4,008 airports) and its OurAirports CSV,
written only into the worktree; titles resolved through a copy of the
resolver cache. "Before" is rebuild 28's parser on the same wikitext.
Scripts kept in the session scratchpad, not the repository.

| Network | Undirected pairs | Directed pairs |
|---|---|---|
| Rebuild 27 (`routes_21691ca7`, crawled 2026-10-02) | 34,187 | 68,374 |
| Before: rebuild 28 parser, this crawl | 34,203 | 68,406 |
| After, service date 2026-10-04 | 25,899 | 51,798 |
| After, service date 2026-10-26 (winter schedule) | 25,967 | 51,934 |

8,304 undirected pairs dropped (24.3%), none added. By why (a pair counts
under the classes of all its listings):

| Why | Pairs |
|---|---|
| Seasonal | 5,420 |
| Seasonal charter | 874 |
| Disputed: the other article lists the same airline's service as not year-round | 872 |
| No longer read (prose, map, reference, statistics or other subsection) | 333 |
| Begins after the build date | 269 |
| Seasonal and seasonal charter | 221 |
| Charter | 141 |
| Resumes after the build date | 53 |
| Begins later and seasonal | 27 |
| Suspended | 22 |
| Charter and seasonal | 17 |
| Charter and seasonal charter | 14 |
| Other mixes, each under 10 (5 ended, 3 other labels, ...) | 41 |

Listing-level on 2026-10-04: 17,951 seasonal, 2,400 seasonal charter, 1,019
begin later, 443 charter, 298 resume later, 184 suspended, 24 ended, 11
other labels, 3 undated changes.

Samples:

- PVG-ADL dropped (seasonal in both articles). Pudong loses 3 pairs (ADL
  seasonal, ALG begins 26 October, MDC charter); Adelaide 8 (CHC, HKG, LST,
  PPP, PVG, SFO seasonal; PUG, PXH charter).
- Leisure airports lose most: PMI 153, RHO 138, HER 133, AYT 133, CFU 105,
  ZRH 97, CPH 95, PRG 95, HRG 90, CHQ 88, FRA 87, LGW 85.
- ICN loses 13: ATH, MRS, SAI (seasonal charter), DAC, OSL (charter), MEL,
  TOY, YUL, YYC, ZAG, ZRH (seasonal), BTH (resumes 23 December), TLV
  (begins/resumes later).
- LHR loses 48, nearly all seasonal sun routes (ADB, BJV, CFU, DBV, FAO,
  HER, IBZ, ...), plus MEL (resumes later), DND (ended) and CGK (read from a
  prose comparison in Jakarta's article -- never a route).
- DEN loses 29: BIH, BZE, FAI, FCO, GCM, NAS, PVD, SJO, ... (seasonal), CDG
  (Air France seasonal, ending 10 October; United's begins later), PLS
  (begins later).
- Hub to hub (rebuild 27 degree >= 150): 155 of 1,627 pairs go, e.g.
  ATH-JFK, JFK-LGW (Norse, seasonal at both ends), LGW-VIE, STN-ZRH, BER-DXB
  (disputed: Condor seasonal at BER, year-round at DXB), FRA-KUL and MAD-SIN
  (both resume in late October).
- No longer read, e.g. ABQ-LGB (a future-destination map pin), ABL-ORV (a
  statistics table), ARM-ABX (history prose), AAA-PPT (Anaa's section is one
  sentence of prose, and no table lists the pair).

Spot checks, all still present on 2026-10-04: ICN-NRT, LHR-JFK, ICN-TAG,
PUS-TAG, SIN-SYD (one airline's listing begins later, others year-round),
ICN-HND, GMP-HND, ICN-KIX, ICN-FUK, ICN-CJU, GMP-CJU, ICN-BKK, ICN-SGN,
ICN-CEB, ICN-DPS, ICN-GUM, ICN-SPN, ICN-CXR, ICN-DAD, ICN-LAX, ICN-PVG,
LHR-CDG, CDG-JFK, FRA-JFK, DXB-JFK, DXB-LHR, HKG-TPE, HND-CTS, JFK-LAX,
LAX-SFO, ATL-LAX, SYD-MEL, SYD-AKL, ADL-SYD, PVG-SYD. 51,798 directed pairs
is well above route_network's 20,000-pair floor, and its sanity pair ICN-NRT
is in.

### Ambiguities, and which way each was resolved

- A link after a `<br>` that follows a label, with no new label: about a
  dozen in the whole crawl, read as the label's class (Norse at JFK:
  "'''Seasonal:''' Athens, London-Gatwick, <br />Rome", the comma before
  the break showing the list goes on).
- 216 pairs are still kept on one article's word while the other article
  lists them only as not year-round: the year-round listing names an
  airline the other article does not list on that pair (an omission, or
  the same airline under another link, [[Jet2.com]] / [[Jet2]]), so the two
  are not compared.
- `(both begin <date>)` covers the two links before it, `(all ...)` every
  link in the cell.

### When the next build runs

- [ ] The network depends on the day the build starts: net +68 undirected
      pairs between 4 and 26 October as the winter schedule begins.
      index.json records the day as `serviceDate`.
- [ ] Check the built `routes_*.parquet` (PVG-ADL absent, ICN-NRT present)
      and the build log's `routes:` line (pairs, listings left out by
      reason, disputed pairs).
- [ ] When this ships, say "year-round scheduled flights" where the page and
      `web/llms.txt` describe the route network. Not changed here: no shipped
      artifact is year-round only until rebuild 28 is.
