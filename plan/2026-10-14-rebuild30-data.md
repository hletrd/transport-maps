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
- [ ] merge, full tests on h200, rebuild 30, re-measure every pair above, deploy
