# Rebuild 29: what waits for it (opened 2026-10-06)

The owner's decision (2026-10-06): fixes that only reach visitors through a
rebuild are collected here and shipped together, not one rebuild each. The
release checklist is `plan/2026-10-02-rebuild27-release.md`, as run for
rebuild 28.

## Queued

- [x] **Ferry landings on every shore of a water straddler** (a87abc1).
      Rupat read "no route" from every origin: Natural Earth's coast puts the
      Tanjung Kapal pier in water nearer Sumatra, so the Dumai ferry joined
      Sumatra to itself. Measured from Seoul on the full graph: 321 cells
      gained (Rupat 154, Moere og Romsdal 61, Aland/Turku 32, Batam 29,
      Troms 19, Natuna 12, Maldives, Penghu, Paracels, Sulu), 1,929 faster
      (median 8 min), none lost or slower.
      Verify after the rebuild: `?from=seoul&to=1.85,101.55` gives a time with
      a Dumai ferry leg.

- [x] **Build speed** (2026-10-07..09), measured on h200 with one origin
      (Seoul) alone, outputs byte-identical to the code before:
      setup 20.2 -> 9.7 min, origin 14.2 -> 5.0 min. GC paused for setup and
      frozen before origins (3fb7059); prepared band cover (24f1249); h3 and
      GeoJSON coordinates via numpy (e40b74c, 696c3d2); road lookup
      vectorised (19bf623, 2a1b90e); tree passes vectorised (48604d0).
      Launch with `scripts/h200_rebuild.sh start` (no numactl, no trust
      override), release with `finish`, deploy with deploy_from_h200.sh.
      Measure the parallel per-origin time: rebuild 28 ran ~2.8x slower per
      origin in parallel than alone.

## Shipped 2026-10-10 (build 534dec3b-20261010T113421Z)

Started 15:44 with `scripts/h200_rebuild.sh start 2026-10-10`; inputs checked
online first (ourairports.csv updated; Wikipedia 3,985 articles, 51,806
year-round pairs; Natural Earth, GRIP4 and the OSM extracts unchanged).

- Variants finished 19:09 (no-rail), 19:22 (no-ferry), 19:48 (no-air): about
  4 h from setup, against ~12-16 h in rebuild 28 on the same workers.
- The full map lost an hour: 48 workers did not fit the memory pre-flight
  (12 GB each against 693 GB available) and the launcher's subshell died
  without logging it (fixed, cdc3ee5); restarted at 44, then split with a
  56-worker tail in repo-rail once two variants were done (r29-full-tail.sh
  on h200), final pass exit 0 at 20:44.
- finish: 1,464 origins, 0 variant cells faster than the full map.
- Solver deployed (the first pull broke through aws-proxy and redeployed the
  old bundle; the retry carried the new one, buildId checked).
- deploy_from_h200.sh: 10 batches of ~15 GB, 21:10 -> 22:16 including the
  gates and the browser stage, against ~6 h through the Mac. ALL CHECKS PASSED.
- By hand on the live site: Rupat 17 h 38 from Seoul via KUL -> PKU with
  1 h 05 by ferry (was "no route"); Yeongheung-do 2 h 18; Heuksando 9 h 02,
  10 h 09 avoiding rail, no route avoiding ferries; the destination dot
  follows a drag with the route put away and redrawn on release; the map
  from a point off Hwaseong-si shown; console clean.

## Follow-ups after the release (2026-10-11..12)

- Isolated airports re-measured on rebuild 29's inputs: 37 of 3,996, none
  new, none gone; KNOWN_ISOLATED_AIRPORTS stands.
- airports.json regenerated from the updated OurAirports table (6 rows moved:
  SVO's position, HUI/MPN/SUI/YQG size classes, RRG) and deployed.
- Disputed boundaries dashed (29b325b, 6824083): China/India, Guyana/
  Venezuela, and the 22nd parallel in all three of LSIB's pieces (EGYPT|SUDAN,
  EGYPT|EGYPT, SUDAN|SUDAN -- the last two found by querying the live map,
  which still drew 33.17-36.88 E solid); borders.pmtiles rebuilt and deployed.
- Worker memory budget measured (5ea57bf): private peak 5.53 GB max, median
  3.80 GB on the 16 largest origins, parent 13.2 GB; WORKER_PEAK_GB 12 -> 7.
- `h200_rebuild.sh split MAP TREE` (984e7a2) replaces the hand-run tail
  scripts of rebuilds 28 and 29.
- h200 tidied: one-off scripts and logs in archive-r28-r29/, the scratch
  trees repo-rail2 and repo-ferry2 (~190 GB) and profiling output removed.

## The hover reads the drawn cell; the data audit (2026-10-12)

**"Why does the hexagon grow and shrink?"** Three causes, measured:

- At zoom 7+ the tiles draw res-7 cells where a base cell was split; the
  hover read and ringed the res-6 cell (its centre child's time). At zoom
  3-6 a split cell is drawn in its FASTEST child's band, the hover still read
  the centre child. Live, zoom 9 around Seoul: the hover's band matched the
  drawn band at 127 of 156 points.
- While the res-6 tier loads (every city switch) the ring was the 45 km res-4
  cell for a second, then shrank.
- A truncated minute on a band edge (80 = [80, 81)) was put in the band
  below the one the tiles used.

Owner chose option 2 of the two offered (the solver over a res-7 rebuild):
`/api/cells` (197372f) answers a res-3 block of the solver's own cells from
a kept tree (<1 ms; a solve it starts is rationed to one per 20 s), and the
page (4eababd, ad902dd) reads the drawn cell at the drawn level, withholds
the stopgap ring, and bands truncated minutes as the tiles did. Measured
after deploy, zoom 9 Seoul: 154 of 156 match (4eababd's message says 144
for the intermediate state; it was 137). Gwangju z10 160/160, Tokyo z9
144/146, Mongolia z8 94/96, Seoul z5.5 60/63; the misses sit on band
boundaries. Not covered: zoom 0-2, where the tiles draw res-4 cells by their
fastest child and the ring is the res-6 cell -- a pixel at that scale.

**Data audit** ("다른 데이터에러 또 없는지 검사해"), after GeoNames put Masan's
population on a Gwangju village (32774ec):

- Gazetteer (7e536d2): 15 rows dropped (a name not the place's, or an exact
  copy of another town's row), 7 quarters carrying their city's population
  re-ranked to 0, Daocheng's region code corrected. expand_origins applies
  the same corrections (119a55f). DEF17-1 closed (the second Changzhi was the
  phantom).
- Origins (d6f786e): changzhi-cn (phantom) and puyang (Pujiang under
  Puyang, Henan's row; Puyang is puyang-cn) dropped, changsha-cn renamed
  kaiping, Buenaventura and Chongqing moved to their centres (33 and 37 km).
  The three are re-solved in all four maps on h200 with `--only` on the same
  graph (service date 2026-10-10, offline inputs: graphHash 17625577a759f327
  in every new record, as in Seoul's; inputsHash differs because it covers
  the package and origins.toml, which check_dist only warns on), the variant
  markers' rosters edited to match, and reindexed: 1,462 origins, buildId
  534dec3b kept for the solver bundle, check_variants 0 faster cells, 10
  duplicate names (was 13).
- Airports: clean; two doubled spaces in names collapsed (225a9e7).
- Left as found: Sahiwal (Sargodha) carries Sahiwal city's population (a real
  town, so only its rank is wrong); disputed-territory polygons put a few
  origins and airports "outside" their country, which is the polygon, not
  the data.

## When to start

When the owner asks, or when the next rebuild-gated fix lands here.
