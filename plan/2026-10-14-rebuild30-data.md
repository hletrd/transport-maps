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
