# Rebuild 30: the travel times the audits of 2026-10-14 found wrong

The owner asked for the data to be checked ("쓸데없는 테스트보다 데이터가 맞게
나오는지가 중요해"). Two audits ran on build 534dec3b:

- internal consistency over every origin (symmetry, implied speeds,
  reachability, spikes, own-cell times);
- 54 city pairs against Google Routes, timetables and published block times.

Full reports were kept in the session scratchpad (audit2/internal.md,
audit2/external.md); the findings that matter are restated here. The owner
chose to fix all of them in one rebuild (2026-10-14).

Every fix is judged by the numbers it moves, not by a test passing. Each item
names the pairs that must move and where to; they are re-measured after the
rebuild with the same script.

## Errors (fix, no decision needed)

| # | Finding | Measured | Where |
|---|---|---|---|
| E1 | Wikidata IATA collisions: Lasondre (Nias) -> LSE (La Crosse, WI), Seko -> SKO (Sokoto, NG). Seven fake edges, PDG-LSE 15,089 km, TRT-SKO 12,764 km. | Makassar 372 cells a median 276 min too fast; Padang 3,206 cells 82 min | `sources/wikidata.py`, `sources/routes.py` |
| E2 | One-stop through-flights (QF1, BA15) flown as nonstops. Nine routes over 15,400 km (longest scheduled nonstop is SIN-JFK, 15,341 km). | SYD->LHR 24 h door to door against ~26.5-27 h real | `sources/routes.py` |
| E3 | Reading tier (and res-4 hover tier) holds a split cell's CENTRE child; the tiles draw a split cell at zoom 3-6 by its FASTEST child, the res-4 cell at zoom 0-2 by its fastest. | Iloilo own cell 59 min (land children 0-11); 9,900 split cells' centre >30 min slower than the fastest | `emit/hover.py`, `service/hovermap.py` |
| E4 | GRIP4 NoData (-9999) and all-zero density read as roadless inside cities. | Beira 63, Zanzibar 62, Sochi 28, Chita 28 min own cell; 16 places >=100k | `sources/roads.py` |
| E5 | Shinkansen relations carry no high-speed tag: all 20 priced at 81.8 km/h. | Tokyo->Nagoya 3 h 46 (real ~2 h 05), Osaka->Hiroshima 4 h 14 (~1 h 55) | `sources/osm.py` `service_tier` |

## Model additions the owner chose

| # | Finding | Measured | Where |
|---|---|---|---|
| M1 | Ferry frequency from distance alone: busy short crossings get hours of wait. | HK->Macau 2 h 47 overland (TurboJET 1 h 57, 15-30 min headway); Helsinki->Tallinn no-air 5 h 53 (3 h 06) | `graph/ferry*`, `calibration.toml` |
| M2 | Europe-East Asia flights on the great circle; Russian airspace closed to most carriers since 2022. | HND-CDG block 12 h 11 vs 14 h 30-14 h 40 scheduled | `graph/air*`, `sources/routes.py` |
| M3 | Mainland China high-speed rail absent: OSM has ~470 train route relations in China, 21 of them G/D trains. | Shanghai->Hangzhou 3 h 04 (1 h 45), Beijing->Shanghai no-air 15 h 52 (~5 h) | new: track-based HSR from `railway=rail` + `highspeed=yes` ways |
| M4 | Calibration review: tertiary 18 km/h (fitted) below local 25 (default) and x2.0 urban congestion -> 9 km/h; one high-speed tier speed for every line; UK 125 mph intercity at the long-distance tier. | Minna->Abuja airport 104 km 384 min; Seoul->Busan 2 h 38 (~2 h 55); London->Manchester rail 3 h 41 (2 h 49); LA->San Diego 3 h 03 (1 h 58) | `calibration.toml`, `scripts/ground_check.py` |

CLAUDE.md's calibration rule holds for M1, M2 and M4: a constant is either
fitted (against a named, reproducible reference set) or a published figure,
and says which. No constant is moved to make a hand-picked pair come out
right; the pairs above are the check, not the fit.

## Not in scope

- Wind (westbound Atlantic ~30-60 min short): no data source chosen.
- One-stops under 15,400 km (IST-SYD): needs schedule data with stops.

## Progress

- [x] E3 (6a97681): measured on 534dec3b's graph, Maputo->Beira 283 -> 251 min,
  Dar es Salaam->Zanzibar 230 -> 199, Manila->Iloilo 218 -> 212.
- [x] E1 E2 M2 air: E1 drops a listing whose title OurAirports links to another
  airport >300 km away (5 dropped: Lasondre->LSE x2, Seko->SKO, John
  Becker->KSX, Bolognesi->BLP); E2 drops pairs >15,400 km (9 routes; SYD-LHR
  20.9 h nonstop -> 22.8 h with a connection); M2 routes 1,352 directed
  flights round closed airspace on a taut res-3 corridor (HND-CDG 12 h 11 ->
  14 h 10 vs 14 h 30-14 h 40 westbound). Open: map lines stay great circles;
  one-stops under 15,400 km stay.
- [x] E4 + M4 roads: GRIP4 NoData kept apart from zero density; an all-NoData
  cell takes the best class one grid cell out, else local inside the urban
  mask; a cell touching a GeoNames town's built-up disc (4,200/km2,
  Demographia 2023) gets at least local. 1,543 base cells move up; the six
  origin cells go 0 -> 5. Refit on 750 resampled journeys (762 Google calls),
  log error, 5-fold CV by town: highway/primary/secondary/tertiary
  87.3/51.9/51.7/27.9 km/h, urban x1.6 within 20 km (was x2.0 within 40).
  Minna->ABV 366 -> 201 min, Damietta->PSD 310 -> 120, LA->San Diego 232 ->
  172 (Google 118), Sochi->AER 356 -> 70. Open: airport access now ~23% fast
  at the median (spread better, bias worse); Tawau->TWU 256 min for 27 km.
  cities15000 is now a build input (inputs check online before the build).
- [x] E5 M3 rail (d879205, 3069650): relations with no `service` tag promoted to
  high_speed on >=50% high-speed track averaging >=200 km/h (every
  Shinkansen, THSR); high-speed track no relation runs over built as links
  (98,309 km, 1,313 stations; China 92,012 km); tiers refitted on 2,360
  timetabled trains, non-HSR tiers at 0.69-0.79 of mapped line speed.
  Ride minutes: Tokyo->Shin-Osaka 370 -> 153 (147), Shanghai->Hangzhou
  none -> 38 (45), Beijing->Shanghai none -> 270 (258). Still off: Tokyo->
  Sendai 112 (90), Shin-Osaka->Hiroshima 111 (81), Seoul->Busan 121 (150),
  Euston->Manchester 176 (128, no relation).
- [x] M1 ferries (9d55601): published headways for six corridors (TurboJET,
  Helsinki-Tallinn, Dover-Calais, Dar-Zanzibar, Wellington-Picton), OSM
  `interval` first. Edge cost HK-Macau 223 -> 105 min, Helsinki-Tallinn
  349-404 -> 192-246. Open: Dalian-Yantai (sources disagree), Dar-Zanzibar
  sailing 165 min without a duration tag (~2 h real).
- [x] merged (ee2d9e3), 1,591 tests passed; rebuild 30 started 2026-10-14 ~19:00.
- [ ] Early re-measure (origins done first): Shanghai->Hangzhou 3h04 -> 1h22
  (~1h45), Tokyo->Osaka 3h27 -> 3h01 (~2h55), HK->Macau 1h52 (1h57),
  Beijing->Shanghai no-air 15h52 -> 5h13 (~5h), Helsinki->Tallinn no-air
  5h53 -> 3h14 (3h06), Tokyo->Paris 15h24 -> 17h16 (~17h30). BUT the road
  refit drives big-city corridors faster than free-flow Google DRIVE:
  Mumbai->Pune 118 (159), Mexico->Puebla 100 (134), Lagos->Ibadan 100 (124),
  Copenhagen->Malmo 31 (47); LA->San Diego 171 (118) still slow. Road
  calibration redone for rebuild 31 (metro bias); rebuild 30 runs on to
  validate rail, air and ferry end to end.

## Rebuild 31: roads, re-measured (2026-10-15)

Rebuild 30's door-to-door minutes came out FASTER than free-flow driving
between big cities (Mumbai->Pune 118 vs Google 159, Mexico City->Puebla 100
vs 134) while US freeways stayed slow (LA->San Diego 171 vs 118). Cause,
from walking the ground paths (scratchpad decompose.py):

- In a city every cell holds some GRIP4 highway, so the hex path runs a
  straight line across the city at highway speed: London -> LHR was 22 km of
  class-1 cells (22 path km for 23 crow km) in 23 min against Google's 45.
  The flat 20 km penalty radius covered a town whole and London's outer half
  not at all.
- One speed per class for the world: out of fold the rebuild-30 fit was 23%
  too slow on North American town journeys, 24% too fast in low-income ones.
- The fit set had almost no city-centre journeys (random towns), and its
  target was free-flow time.
- Residuals followed journey length in every stratum (rural 30-80 km 1.28,
  over 200 km 0.97): a per-journey cost the model lacked.

Refit (scripts/calibrate_ground.py, calibration.toml [ground],
[ground_income], [urban]): 1,396 journeys -- rebuild 30's 750 re-observed
plus 646 from 150 city centres of 1 M+ -- against Google's typical-traffic
time for a Tuesday 10:00 departure; structure chosen out of fold over 48
candidates. Speeds by World Bank income group (highway 92 km/h high income,
52 low), x1.39 inside each city's own built-up radius (population at
4,200/km2), and 13.8 min per journey at its two ends (half per door in every
solve, half per airport kerb on the access edges). Out of fold, median
|log| metro 0.238 -> 0.147, intercity 0.139 -> 0.135, rural 0.175 -> 0.149,
airport 0.421 -> 0.177.

Check pairs, ground minutes (rebuild 30 -> 31 vs Google typical): London->
LHR 23 -> 34 (51), Paris->CDG 25 -> 36 (48), NYC->JFK 27 -> 36 (48),
Tokyo->NRT 62 -> 78 (84), Mumbai->Pune 120 -> 176 (161), Mexico City->
Puebla 104 -> 129 (142), Lagos->Ibadan 100 -> 153 (129), LA->San Diego
176 -> 165 (123), Chicago->Milwaukee 140 -> 120 (93). Worse: Cairo->
Alexandria 171 -> 252 (151), Delhi->Agra 262 -> 283 (204) -- expressways
GRIP4 grades like any national highway, in lower-middle-income countries;
a highway-only income multiplier fitted no better. Open: that, US
interstates still ~30% slow, metro airport runs still ~25% fast.

## Rebuild 30 result and rebuild 31 start (2026-10-15)

Rebuild 30 finished 2026-10-14 23:54, all four maps exit 0, check_variants 0
faster cells. Own-cell minutes: Beira 63 -> 10, Zanzibar 62 -> 9, Iloilo
out of the top; median 0 (Kota Kinabalu's coordinate sits on a non-land
res-6 slot, as before, and the page reads its res-4 cell). NOT deployed: its
road constants run metro driving and airport access too fast (out of fold
airport access 50% fast), which every flown journey pays. Rebuild 31 started
2026-10-15 from b3f62d2 with the stratified, traffic-aware road refit; the
OSM motorway class (Cairo->Alexandria, Delhi->Agra, US interstates) follows
in the next build.
## Rebuild 32: an OSM motorway class (2026-10-15)

The open item above: GRIP4 grades an expressway like any national highway.
A cell an OSM motorway crosses is now class 6 (graph/ground.MOTORWAY_CLASS)
with its own fitted speed, income-scaled like the rest; GRIP4's class 1
keeps the highways OSM does not call motorways.

- Input: scripts/osm_roads.sh filters the full continental extracts to
  highway=motorway,trunk ({region}-roads.osm.pbf): 573 s wall on h200 for
  all seven in parallel, 8.3 GB summed RSS, 424 MB out. sources/motorways.py
  parses that in 117 s at 10.2 GB peak (3.39 M ways; cached on the
  extracts' snapshot) and marks the cells a rule's ways cross, at the index's
  own resolution, in 36-48 s (cached per index). The build now refuses to
  start without the -roads extracts; run the script before the next build.
- Rule, out of fold (mean of strata's median |log|): motorway only 0.138,
  plus trunk tagged motorway/expressway/motorroad=yes 0.133, plus trunk
  signed 100 km/h+ ("fast_trunk") 0.127. Each re-planned under its own fit
  (three rounds for fast_trunk; the last moved no constant more than 3%).
  Income-scaled motorway 0.127 vs one speed everywhere 0.142; class 6 merged
  back into class 1 on the same paths 0.142 -- the gain is the class.
- Fit (1,396 journeys, typical traffic): motorway 87.8 km/h (102 high
  income, 71 low), highway 42.9, primary 49.7, secondary 55.6, tertiary
  36.3; income x1.167/0.824/0.812; built-up x1.36; 11.4 end minutes.
  Out of fold vs rebuild 31: metro 0.147 -> 0.131, intercity 0.135 ->
  0.089, rural 0.149 -> 0.135, airport 0.177 -> 0.153.
- Motorway bridges and tunnels now cost class 6 too (graph/landmass), with
  the dead-end rules ranking it above highway rather than below local.
- Check pairs (ground minutes, rebuild 31 -> 32, Google typical): Cairo->
  Alexandria 252 -> 214 (151), Delhi->Agra 283 -> 221 (204), LA->San Diego
  165 -> 157 (123), Chicago->Milwaukee 120 -> 108 (93), Mumbai->Pune 176 ->
  171 (161), Lagos->Ibadan 154 -> 137 (129), Mexico City->Puebla 129 -> 117
  (142, now fast). Airport runs faster: LHR 34 -> 31 (51), CDG 36 -> 35
  (48), JFK 36 -> 33 (48), NRT 78 -> 73 (84).

## Rebuild 31 stopped, rebuild 32 started (2026-10-15)

The motorway class (ec53ce0, b7b00d5) beat the rebuild-31 road fit in every
stratum out of fold (metro 0.147 -> 0.131, intercity 0.135 -> 0.089, rural
0.149 -> 0.135, airport 0.177 -> 0.153), so rebuild 31 was stopped at about
half (full map 672/1462) rather than finished and deployed, and rebuild 32
started from fffd1c1 after scripts/osm_roads.sh filtered the seven extracts
on h200 (513 s for Europe, the slowest).

## Rebuild 32 shipped (2026-10-15)

Rebuild 32 (a2df09c1-20261014T181857Z, from fffd1c1) finished 08:15, all four
maps exit 0, check_variants 0 faster cells; solver deployed (Seoul->Gumi 163
-> 119 min), data and page deployed through deploy_from_h200.sh (10 chunks,
~145 GB), ALL CHECKS PASSED at the four viewports. airports.json regenerated
from the build's OurAirports (6 rows changed); places.json is the audited
Sep 9 gazetteer.

Live checks: Shanghai->Hangzhou 1 h 30 via 沪昆高速线 (~1 h 45), Tokyo->Osaka
3 h 08 via のぞみ (~2 h 55), Mumbai->Pune 2 h 39 (Google 2 h 39), HK->Macau
1 h 57 (1 h 57); hover band = drawn band at 156 of 156 points at zoom 9 around
Seoul (live before: 127). Still off (from the 54 pairs): Cairo->Alexandria
3 h 33 (2 h 30 drive), LA->San Diego +31%, Chicago->Milwaukee +20%, London->
Manchester rail 3 h 31 (2 h 49), Mexico City->Puebla -16%, KTX ~15% fast.

Found on the live check: the itinerary of a SURFACE journey is the res-4
representative's, and `.over.bin` replaces it with the reading cell's own
route only when the ARRIVAL AIRPORT differs. Where the two take different
surface modes the legs describe another journey: HK->Macau lists 38 min by
highway (the res-4 cell's bridge route) under a 1 h 57 total by ferry;
London->Calais lists 1 h 39 by road under 3 h 29. Fix: emit an override
entry when the mode breakdown differs too (emit/override.py), which needs
the per-origin solve -- the next rebuild.

## Rebuild 33 scope (owner, 2026-10-15: "다 고치고 돌려")

Everything still off goes into rebuild 33, in three worktree forks (h200 use
capped so the three together stay inside the owner's ~64 threads):

- roads: Cairo->Alexandria slow, US metro freeways slow (LA->San Diego,
  Chicago->Milwaukee), Mexico City->Puebla fast, metro airport runs fast,
  Tawau->TWU;
- rail: London->Manchester (no relation; fast conventional lines),
  per-line high-speed speeds (KTX fast, Tohoku/Sanyo slow), Delhi->Agra,
  Milan->Turin;
- misc: ferry sailing durations missing from OSM (Dar->Zanzibar), Dalian->
  Yantai headway, Kota Kinabalu's own reading slot, flight lines drawn round
  closed airspace, a cheap re-audit of the live rebuild-32 data;
- and 2f7c421 (legs of a surface journey that rides a train or a ferry its
  res-4 representative does not), which needs the per-origin solve.

### Rebuild 33 progress

- misc (69ce809..79fab7a): published sailing times where OSM has none
  (Dar->Zanzibar edge 243 -> 183 min), Dalian Bay->Yantai timetable row
  (965-999 -> 548 min; news-article source), coastal towns' cells join the
  land set (Kota Kinabalu, Bodo, Tarawa: 11 cells), flights drawn round closed
  airspace (dist/airspace.json, `airspaceUrl`), and a regression found in
  the LIVE rebuild 32: the fastest-child rule read a border-straddling cell
  from the far side (Hong Kong->Shenzhen 25 min against 72 by the graph,
  Pyongyang->Dandong 167 vs 351) -- now the fastest child in the cell's home
  zone, and the solver block refines readings at zoom 7+ only.
- rail (cfc95af..009482a): each leg priced from its own track and speed
  limit; maxspeed:forward/backward and :tilting read; fast conventional
  track no relation runs (160-200 km/h) built as links (25,530 km). Out of
  fold high_speed 0.087 -> 0.050. Rides: Tokyo->Sendai 112 -> 86 (90),
  Delhi->Agra 153 -> 109 (100), Paris->Lyon 132 -> 117 (116), London->
  Manchester 176 -> 157 (128); WORSE Berlin->Hamburg 104 -> 131 (105, only a
  stopping ICE in OSM). Follow-up running: stops on track-built links (Korea
  fast, Chengdu->Chongqing slow) and Berlin.
- rail follow-up (e9ffd02): no change, on evidence -- a fitted stop share on
  track links scored 0.164 against express 0.070 out of fold; Korea is a
  5-stop KTX relation (Daejeon->Busan nonstop), not track links;
  Chengdu->Chongqing was a check-station artefact (61 vs 62 to Shapingba);
  Berlin->Hamburg needs a timetable source (OSM maps 160 where LZB runs 230).
- roads (ed6364f..654349a): motorway speed by its signed limit (73.6 / 89.1
  / 102.4 km/h), a North America multiplier 1.231, lower-middle and low
  income merged, an OSM trunk floor; out of fold metro 0.131 -> 0.113,
  intercity 0.089 -> 0.074, rural 0.135 -> 0.095, airport 0.153 -> 0.156.
  Cairo->Alexandria 214 -> 193 (151), LA->San Diego 157 -> 140 (123). Open:
  city-centre airport runs (London->LHR 35 vs 51), Lagos->Ibadan, Mexico
  City->Puebla, Tawau (the coast severs the town cell; road_crossings).
- Rebuild 33 started from 654349a with 64 workers (30/4/15/15).

## Rebuild 33 shipped (2026-10-16)

21005af1-20261015T080404Z from 654349a, 64 workers (30/4/15/15): full map
05:44, no-air 07:43 (about a day at 64 threads); check_variants 0 faster.
Solver deployed (Seoul->Gumi 121 min), data and page deployed. The first
browser_verify run failed (opening view over 90 s, nothing painted at zoom
3, 3 console errors) right after the 145 GB sync with the web host's page
cache cold; rerun minutes later: ALL CHECKS PASSED, console 0, opening view
28 s cold and 3 s warm. Readings in the first minutes after a deploy come
from the res-4 tier until the 10 MB `.r6.bin` arrives ("read from the wider
grid"); not a defect, but worth warming the cache after a deploy.

Live (r6): Hong Kong->Shenzhen 1 h 24 (rebuild 32: 25 min, the cross-border
child), Tokyo->Osaka 3 h 04 via のぞみ, London->Calais 3 h 15, Delhi->Agra
3 h 03, LA->San Diego 2 h 18, Cairo->Alexandria 3 h 12, Haneda->Paris drawn
round closed airspace (peak 49.1 N), Kota Kinabalu own cell 0 min; hover
band = drawn band at 155 of 156 points (zoom 9, Seoul).

Open after rebuild 33:
- Hong Kong->Macau 2 h 40 (real ~1 h 57): the HZMB's mid-bridge island and
  the Zhuhai/Macau port fall in res-6 cells assigned to China, so the bridge
  route pays two land crossings (HK->CN->MO, 45 min each) where a traveller
  clears one; its legs list the res-4 cell's 42 min (same mode, so no
  override entry).
- Berlin->Hamburg 2 h 43 (~2 h 17): OSM maps 160 km/h on LZB-230 track and
  has no limited-stop ICE; needs a timetable source (DELFI GTFS).
- KTX ~15% fast (a 5-stop relation), London->Manchester rail slow, city-centre
  airport runs ~30% fast, Lagos->Ibadan +12%, Mexico City->Puebla -12%.

## Rebuild 34 scope (owner, 2026-10-16: "go on fix all")

Three worktree forks, ~64 threads on h200 between them:
- zones: split base cells whose res-7 children span two immigration zones
  (or another general rule) so a bridge like the HZMB pays one crossing;
  legs that describe the headline's journey when the totals differ;
- rail: open timetable feeds (GTFS, licences checked) where OSM lacks the
  service or the speed -- Berlin->Hamburg, London->Manchester, KTX, Sanyo;
- access: city-centre airport runs ~30% fast (London->LHR 35 vs 51).

### Rebuild 34 progress

- zones (1e590a3, c336e2a -> 41431f5): the HZMB island's sea-centroid cells
  were majority-filled as China, so the bridge paid HK->CN and CN->MO;
  `PORT_ZONES` (sourced boxes) relabels them HK: HK->Macau 150 -> 105 in the
  graph (~1 h 55 door to door; real ~1 h 57), none slower from HK. A general
  "transit" rule was tried and rejected (13 M cells slower from HK). Legs:
  `.over.bin` also lists a reading cell in another zone than its res-4
  representative, or whose total parts by > 60 min and > half (+14%).
  The other 24 third-zone blank cells are being checked (ports fork).
- access (ea6f5d9, 4371627 -> 3b841e8): a second slowdown in a city's core
  (x1.242 inside half its built-up radius), refit on 1,603 journeys incl. a
  207-journey airport probe: mean out-of-fold 0.1108 -> 0.1077; London->LHR
  36 (51) barely moves -- the error is leaving the centre and differs by
  city. A measured per-airport access term for the busiest airports is being
  built (airports fork).
- ports (a2ced87, 3be39d2 -> c956957): the remaining third-zone sea cells,
  case by case. Fixed: Cyprus's UN buffer zone and base areas (Larnaca->
  Ayia Napa 122 -> 32), the open Saint-Martin border (Philipsburg->Marigot
  55 -> 10), the head of the Gulf of Aqaba (Egypt and Jordan joined across
  the water; Taba->Aqaba 64 -> 107 via Eilat as in reality), Gibraltar's
  North Mole berth. Left: Egypt<->Saudi mid-gulf (the 1:10m mask makes the
  gulf land; closing EGY-SAU would also cut real ferries), BES read
  SCHENGEN (no edge affected).
- rail GTFS (8cb81d7, 3d33129, 01513b0 -> 4912197): DELFI German
  long-distance (gtfs.de, CC BY 4.0) and KorailGTFS (CC BY 4.0) time their
  operators' rides stop to stop: Berlin->Hamburg 131 -> 107 (107), Seoul->
  Busan 120 -> 138 (138), Seoul->Gimcheon-Gumi 67 -> 80 (84), Berlin->
  Munich 224 -> 242 (246). Not available openly: National Rail (account),
  JR West.
- Nicosia (ab552d0) departs from Eleftheria Square, the Republic side.
- airport access table (worktree-agent-a4a7989cd4d4d43f2: ace1ec2, 804c6a4;
  NOT merged): a signed per-airport access minute for 1,227 airports from
  2,582 Google Routes typical-traffic drives, shrunk toward 0; airport
  stratum 0.139 -> 0.124 out of fold (mean 0.1077 -> 0.1041), centre runs
  barely move (London->LHR 36 -> 40 vs 51; Paris->CDG and Singapore->SIN
  move the wrong way). Held back for the owner: it ships a per-airport table
  derived from Google Maps Platform data, which may not fit its terms.
- Rebuild 34 started from ad73f52 (64 workers) without that table; both
  GTFS feeds fetched by the inputs check.

## Rebuild 34 shipped (2026-10-17)

2f990555-20261016T083038Z from ad73f52, 64 workers; all four maps exit 0,
check_variants 0 faster. Solver, data and page deployed; browser_verify
passed first time (opening view 2 s, console 0). Live: Hong Kong->Macau
1 h 56 (real 1 h 57; legs now 1 h 56 too), Berlin->Hamburg 2 h 20 via ICE
28 (~2 h 17), Seoul->Busan 2 h 59 via KTX-청룡 (~2 h 55-3 h), hover band =
drawn band 155/156 (zoom 9, Seoul). Other pairs moved 2-4 min slower (the
core slowdown and 11.0 end minutes).

Still open: the per-airport access table (owner's call on Google terms);
London->Manchester rail (National Rail needs an account); Shin-Osaka->
Hiroshima (no open JR West timetable); city-centre airport runs ~25-35%
fast; Egypt<->Saudi across the Gulf of Aqaba (land in the 1:10m mask).

## Rebuild 35 scope (owner, 2026-10-17: "gogo fix all")

Owner's decisions: the per-airport access table derived from Google Routes
is NOT shipped (Google Maps Platform terms; branch deleted); Britain's rail
stays on OSM (no National Rail account). Two forks:
- access: city-centre airport runs from open data only (OSM road circuity,
  street network), Google only as the fit reference;
- straits: sever ground edges across water OSM shows as sea where the 1:10m
  mask closes a narrow gulf or strait (Gulf of Aqaba first), unless a fixed
  link or ferry serves it.
- access (no commit): motorway speed only on the cell steps an OSM motorway
  runs along (413,470 pairs), refit and re-planned: mean out-of-fold 0.1072
  -> 0.1060, but +-0.005 over fold seeds and bootstrap (0.47 chance worse),
  and the airport stratum did not slow. Not shipped. The sample shows no
  centre-run bias (0.96-1.05 obs/pred); London/Paris/NYC's 25-35% are
  specific to those check points. Patch kept in the session scratchpad.
- straits (58d070a -> 3195a72): a split coastal cell's open-sea children took
  the base cell's landmass, so chains of them drove down gulfs where both
  shores share a landmass (Sinai-Hejaz). Water cells now keep edges only to
  their nearest shore; fixed links, road crossings and OSM motorway/trunk
  steps are kept. 193,456 cell pairs cut (0.47% of edges); no motorway or
  trunk way crosses a cut. Taba->Haql 122 -> 176 (via Eilat and Aqaba);
  Bosporus, Messina, Kerch, Oresund, Johor unchanged. ~3 min more build.
- Rebuild 35 started from 3195a72.

## Rebuild 35 discarded, rebuild 36 (2026-10-18)

Rebuild 35 finished (all four maps exit 0) but check_variants failed: every
avoid-a-mode map read faster than the full map somewhere (no-ferry 217,839
reading cells, no-rail 267,423, no-air 1,384; worst 114 min at Samarkand).
Cause: landmass.water_pairs kept an offshore water cell's edge towards the
first neighbour a breadth-first walk reached it from, iterating a SET of cell
strings -- so each build process, with its own PYTHONHASHSEED, kept
different edges (the four logs severed 193,405-193,416 pairs). Not deployed.
Fixed by walking in sorted order, with a test under four hash seeds;
rebuild 36 started from it.

## Rebuild 36 shipped (2026-10-18)

2a1950e9-20261017T232044Z from 53ead6f: the four maps severed the same
193,412 water pairs, check_variants 0 faster cells. Solver, data and page
deployed; browser_verify passed first time (opening view 1 s, console 0).
Live: Hong Kong->Macau 1 h 58, Berlin->Hamburg 2 h 20 (ICE 28), Seoul->
Busan 2 h 59 (KTX), Cairo->Taba 5 h 27 by CAI->AQJ (no road over the
gulf); hover band = drawn band 155/156 at zoom 9. Of the 54 audit pairs
only Hong Kong->Macau moved against rebuild 34 (1 h 56 -> 1 h 58).

Left, by the owner's decisions or for want of open data: per-airport access
(Google terms), British rail (National Rail account), JR West, city-centre
airport runs (no bias in the sample; London/Paris/NYC specific).
