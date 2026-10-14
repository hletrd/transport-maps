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

- [ ] E1 E2 E3 E4 (main session)
- [ ] E5 M3 rail (worktree)
- [ ] M1 ferries (worktree)
- [ ] M2 airspace (worktree)
- [ ] M4 calibration (worktree)
- [ ] merge, full tests on h200, rebuild 30, re-measure every pair above, deploy
