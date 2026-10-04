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

## A16: plain roads join land parts; short ferries cross a cut (2026-10-04)

Branch `tianjin-fix`, on `origin/rebuild28`. Not merged, not deployed, no
`build-all` run. Measured read-only on rebuild 27's caches and `dist/` through
a scratch mirror (symlinks into `data/cache` and `data/build`, writes kept in
the scratchpad). A new model input: the road-crossing parse
(`sources/road_crossings.py`) reads the same raw extracts as the fixed links,
and its cache is keyed on the land parts as well as the extract.

### What was reported, and what was wrong

1. **Tianjin Binhai (38.7-39.2 N, 117.7-118.1 E): nothing wrong in the
   graph.** Every land cell of the res-6 universe in 38.5-39.4 N,
   116.9-118.9 E reads a time from Seoul -- 438 cells, none unreachable, in
   rebuild 27's `dist/` and in the live build (`366feb5d`) alike. The X's of
   the sketch are cells NOT in the land universe: 256 of open Bohai Bay and
   19 of reclaimed coast Natural Earth's 1:10M polygons predate (3 of them
   at least half OSM land: `863188ba7`, `86318d497`, `863188bb7`, Nangang).
   Their `.r6.bin` slots are padding, written as the sentinel
   (`emit/hover.py`), and reading the array directly calls them
   unreachable. The page does not: `lookupRaw` falls back to the res-4
   reading there, and the bands are painted one cell past the shore. The
   hypothesis -- reclaimed land on a land part of its own, cut by severing --
   was tested and is false here. Not changed.
2. **Daebu-do, Seonjae-do, Yeongheung-do: cut, cause confirmed.** Land
   parts 2755 (Daebu, Seonjae) and 2754 (Yeongheung) against the mainland's
   160. The only road on is the Sihwa seawall, route 301 (`대부황금로`): OSM
   ways 196334400, 196094623, 550251553/4, 196288805, 196091085 and more,
   `highway=primary`/`secondary` with no `bridge`, `tunnel`, `embankment` or
   `man_made` tag over the water. Its one bridge, 550251550/1 at the tidal
   plant, lies inside one fine cell and is rightly dropped by `KEEP_RES`. 27
   severed pairs ring Daebu-do; the Yeongheung Bridge (196373778) is in the
   fixed links and joined Yeongheung to Daebu all along, so the whole chain
   hung on the seawall. Seoul read 65535 for all three.
3. **Sinan.** Per island, from Seoul's `.r6.bin`:
   - Jido, Jeungdo, Imjado (17 cells, "no route"): cause (a). Jido is
     islands joined by polder dikes; route 805 and route 24 (`해제지도로`)
     cross from part 160 to 2747/5808/2106 on plain road over reclaimed
     land. The Jido (278136394) and Jeungdo (361237925) bridges are each
     inside one fine cell. Imja Bridge (1280736564/6) IS a fixed link.
   - Apdo (249 min), Amtae (273), Palgeum (260), Anjwa (275), Jaeun (286):
     reachable, but Mokpo-Apdo only by ferry. Cause (a): the Apdo Bridge's
     decks (1046101699, 1414211461/2) each lie inside one fine cell, and the
     cell boundary 8730c6460 / 8730c6461 falls on 1414211460, the untagged
     road across the islet between them. Cheonsa Bridge on to Amtae was fine.
   - Taedo and Gageodo (Hataedo 3 cells, Gageodo 3, "no route"): cause (b).
     The only line is Heuksando -> Sangtaedo -> Jungtaedo -> Hataedo ->
     Gageodo. Sangtaedo-Jungtaedo (674383655) is 0.85 km, under
     `MIN_FERRY_KM`, and was dropped as "outside length window" -- the floor
     assumes a short crossing duplicates a road, but Sangtaedo (part 5754)
     and Jungtaedo (5746) are severed. Manjaedo has no land cell.
   - Heuksando 563 min, Hongdo 681, Bigeumdo 347, Dochodo 419, Haui-do 357:
     ferry only, reached by ferry. Correct.
4. **Yeongjong (ICN) 64 min, Songdo 41 min:** reachable, unaffected (the
   Yeongjong and Incheon bridges are fixed links). Also spot-checked and
   reachable: Penang, Lantau and Chek Lap Kok, Singapore, Walcheren,
   Schouwen, Goeree, Texel, the Palm Jumeirah, Bahrain, Ganghwa, Gyodong,
   Geoje, Namhae, Wando, Jindo, Zhoushan, Pingtan, Xiamen, Hainan, Key West.

### How large, before the fix

Seoul's `.r6.bin` (rebuild 27): 33,829 land cells outside Antarctica read
"no route", in 2,246 clusters; 15,970 cells in 1,033 clusters border a
reachable land cell -- they were reached before severing existed. The 20
largest of those, by cell count:

| Cells | Lat, lon | Where |
|---:|---|---|
| 1,667 | 75.47, -87.70 | Canadian Arctic (Devon Island) |
| 1,374 | 79.64, -91.27 | Axel Heiberg / Ellesmere |
| 1,025 | -49.90, -74.90 | Patagonian channels, Chile |
| 703 | 75.91, -100.24 | Bathurst / Melville islands |
| 544 | 79.88, 22.65 | Nordaustlandet, Svalbard |
| 398 | -53.76, -72.76 | Fuegian channels, Chile |
| 362 | -45.06, -74.11 | Chonos archipelago |
| 322 | 73.25, -78.68 | Bylot Island |
| 322 | 67.82, -75.74 | Prince Charles Island, Foxe Basin |
| 259 | 77.91, 22.29 | Edgeoya, Svalbard |
| 218 | 0.14, -50.19 | Amazon mouth (Caviana) |
| 205 | 72.66, -23.10 | East Greenland islands |
| 173 | 60.30, 21.23 | Turku archipelago |
| 159 | -0.86, -51.41 | Amazon delta (Gurupa) |
| 156 | 70.73, -26.59 | Milne Land, Scoresby Sund |
| 144 | 73.41, -105.58 | Canadian Arctic island |
| 135 | 70.05, 59.44 | Vaygach |
| 118 | 56.47, -134.09 | Kuiu Island, Alaska |
| 92 | 53.27, -129.81 | Pitt Island, BC |
| 88 | 61.96, -112.24 | Great Slave Lake islands |

These are islands no road reaches, served by air or boat or not at all:
severing is right there, and the top of the list is not where this defect
lives. Its cases are small and many -- Daebu-do 11 cells, Jido 17, Hataedo
3, Gageodo 3 -- and are counted below by what the fix joins.

### The rule (and the three that were measured and dropped)

A pair of adjacent cells on different Natural Earth land parts stays joined
when a ROAD runs from one part onto the other, bridge or not
(`sources/road_crossings.py`, kind "road" rows beside the fixed links):

- Read: the GRIP road classes `graph/landmass.SPAN_ROAD_CLASS` costs a span at
  (motorway .. living_street; no footways, paths or tracks), except ice and
  winter roads and ways that are also `route=ferry`.
- Where: only nodes within `SEAM_RING` (2) rings of a seam -- a land cell
  touching two parts, or within two rings of a cell on a part it does not
  touch. 144,381 res-6 cells, 91,325 of them land (2.2 % of the land).
- How: every located node is placed on the Natural Earth part whose polygon
  holds it at least `COAST_MARGIN_DEG` (0.005 deg, ~550 m) inside its coast,
  or on water. A step from one part straight onto another is a crossing; so
  is every step of a stretch of road over water -- joined through every way
  that shares a node -- that lands on two parts. The rows are the runs of
  such steps along each way; `linked_pairs` and `spanning_links` read them as
  they read a bridge (`graph/landmass.ROAD_KINDS`), but a plain road that
  stops over water is never continued (the islet rule is for bridge decks).

Dropped on the way, each measured on Asia:

| Version | Asia rows | What went wrong |
|---|---:|---|
| cell labels (a step between cells on disjoint parts) | 29,680 | coastal roads through strait cells Natural Earth puts on the far shore joined Bali-Java, Chiloe, Guimaras, K'gari, Rupat, Laut |
| land under the road, way by way | 62 | no single way of a seawall runs land to land: Daebu-do, Jido and Apdo stayed cut |
| land under the road, stitched, no margin | 99,137 | Baubau's streets reached "Muna" through two Natural Earth slivers 19 and 52 m deep; Adonara joined Flores |
| stitched, 0.005-deg margin (shipped) | see below | -- |

Before any of these, an OSM-coastline rule was tried and dropped: "keep a
severed pair joined where the OSM water polygons (the coast `water.pmtiles`
is drawn from) leave land continuous across the two cells". Any land piece
touching both cells joined 16,926 of the 51,439 pairs, Shodoshima and Taedo
among them, through islets straddling the shared edge; each cell's largest
piece joined Bali to Java, Tierra del Fuego, Chiloe, Islay and K'gari,
because Natural Earth labels a mid-strait cell holding a sliver of one island
with the other; demanding that the land touch each cell's own part kept those
cut but missed Sihwa and Apdo, and joined Amazon-delta islands across river
water the coastline does not draw.

Also changed, each found by the measurement:

- `graph/landmass.spanning_links`: a bridge end is dead by its bridge and
  tunnel steps alone. With road rows counted, a causeway's islet road made
  the bridge end beside it look live, the islet rule never ran, and the King
  Fahd Causeway cut Bahrain off (with Wenzhou's and Zhoushan's islets).
  Sample vertices are keyed by row, not way id: one road way can give
  several runs.
- `graph/build._ferry_edges`: a crossing under `MIN_FERRY_KM` is kept when
  its two cells are distinct and open water severs them -- it is then the
  only way across. 54 such crossings worldwide on rebuild 27's index
  (Sangtaedo-Jungtaedo, the Vaxholm and Furusund lines, Bjorko, Cannes -
  Sainte-Marguerite, Kukup, Santos' catraias, Iloilo-Buenavista ...); 52 once
  road crossings joined two of their pairs. The in-window count and its
  off-mask bound are unchanged.

### Measured after (all seven regions parsed, read-only, rebuild 27's inputs)

- Road crossings: 530,393 runs (Asia 197,214, North America 165,898,
  Europe 150,011, South America 12,559, Central America 2,452, Oceania 1,440,
  Africa 819), 529,686 once a run in two extracts is counted once.
- Severed pairs 51,439 -> 49,822 (1,617 joined by a road); road spans over
  water 159 -> 408; short ferries kept across a cut: 52.
- `scripts/check_fixed_links.py` on the real index, every region parsed
  (`before` is the graph with no severing at all, as the script prints it):

  | Case | No severing | Rebuild-28 head | This branch |
  |---|---|---|---|
  | Great Seto, Akashi-Kaikyo, Naruto, Bosphorus, Kanmon, Geoga | joined | joined | joined |
  | Saipan -> Tinian, Shodoshima, Messina | joined | cut | cut |
  | Paris -> Brussels (control) | joined | joined | joined |
  | Oresund, Great Belt, Confederation Bridge | joined / cut / cut | joined | joined |
  | Sihwa Seawall, Siheung -> Daebu-do | joined | **cut** | joined |
  | Yeongheung Br., Daebu-do -> Yeongheung | joined | joined | joined |
  | Jido polders, Muan -> Jeungdo | joined | **cut** | joined |
  | Imja Bridge, Muan -> Imjado | joined | **cut** | joined |
  | Apdo + Cheonsa Br., Mokpo -> Amtae-do | joined | **cut** | joined |
  | Yeongjong Bridge, Incheon -> ICN | joined | joined | joined |
  | Taedo, Sangtaedo -> Jungtaedo (ferry only) | joined | cut, **cut by ferry** | cut, joined by ferry |

  Rebuild-28 head: 13 of the original 13 as expected, 5 of the 7 new cases
  wrong. This branch: all 20 as expected.
- Ground components (union of grid adjacency less the severed pairs, plus
  the spans): 192 components, 8,194 cells (49,931 km2), were cut off and are
  now joined; none that was joined is cut. The largest, each checked against
  what joins it: Manitoulin (Little Current swing bridge and causeway),
  Zhoushan, islands north of Tromso and around Harstad, Padre Island, Whidbey,
  Phuket, Langeland and Tasinge, Jido and Apdo-Amtae (Sinan), Biliran, Cayo
  Coco and Cayo Santa Maria (pedraplenes), the Uists and Benbecula
  (causeways), Hailuoto (`Hailuodon pengertie`, a causeway that opened on
  2026-06-29 -- the rule found a link three months old), Burray and South
  Ronaldsay (Churchill Barriers), Antelope Island, Kotlin (the St Petersburg
  dam), Fehmarn, the Florida Keys, Daebu-do, Mannar, Hecla Island, Pine
  Island, Key Biscayne, Kallandso, Grand Isle (Lake Champlain). One is
  inside an island: North and South Bruny meet over The Neck, and Bruny stays
  ferry-only from Tasmania.
- Still cut, as before and as they should be: Baffin, Sakhalin, Tierra del
  Fuego, Devon, Sicily, Mindoro, Chiloe, Corsica, Bali, the Falklands -- the
  same top of the list, each reached by ferry or air or not at all. Bali,
  Chiloe, Guimaras, K'gari, Rupat and Laut, which the label rule joined, and
  Muna-Buton and Adonara-Flores, which the margin-less rule joined, stay
  cut.

### When the next build runs

- [ ] The road-crossing parse runs once per extract snapshot and land-part
      set, after the fixed-link parse, and needs the raw `*.osm.pbf` (h200
      fetches them from Geofabrik, G2). 80 min for all seven on the 32 GB
      Mac at `nice 19` (Europe 25, Asia 22, North America 18, Africa 7,
      South America 4, Oceania and Central America 1-2 each), part of it
      beside rebuild 27's chain. Peak RSS 8.1 GB, Europe, measured with the
      chunked land test (d6b0b21); 15.8 GB before it, and Europe re-parsed
      with it gave the same 150,011 rows.
      The regions are parsed one after another; on h200 they could run side
      by side, which is not done here. Without a raw extract or a cache for
      any region, `road_crossings()` returns None and the build severs on
      bridges and tunnels alone, as rebuild 27 does, with a warning in the
      log.
- [ ] `scripts/check_fixed_links.py` on the real index: 20 cases, all as
      expected (the table above). Re-run after the merge.
- [ ] Seoul's `.r6.bin` against rebuild 27's: Daebu-do (37.25, 126.58),
      Yeongheung-do (37.25, 126.47), Jido (35.05, 126.21), Jeungdo
      (34.99, 126.15), Imjado (35.08, 126.10), Hataedo (34.39, 125.30) and
      Gageodo (34.06, 125.12) read a time; Apdo (34.86, 126.30) is faster
      than 249 min; Shodoshima, Tinian, Messina stay ferry-only.
- [ ] The log lines `N ferry crossing(s) under 1 km kept` (52 on rebuild
      27's inputs) and `... and N road crossing(s) join ...` (529,686) are
      present.
