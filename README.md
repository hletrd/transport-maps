<div align="center">

# Isochronic Passage Chart

**An interactive world isochrone map of door-to-door travel times from the cities in `data/origins.toml`.** The count is not repeated here: it has been wrong in this file twice, and `dist/index.json` is the only place that knows what was actually built.

[![Live site](https://img.shields.io/badge/live-worldmap.atik.kr-1f6feb)](https://worldmap.atik.kr/)
![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab)
![MapLibre GL JS 6.11](https://img.shields.io/badge/MapLibre_GL_JS-6.11-396cb2)
![PMTiles](https://img.shields.io/badge/tiles-PMTiles-6b4fbb)
![H3 resolution 6/7](https://img.shields.io/badge/grid-H3_res_6%2F7-e8802b)

[**Open the interactive isochrone map**](https://worldmap.atik.kr/) · [How it is built](#development) · [Data sources](#data-sources-and-attribution)

<img src="web/preview.png" alt="The globe, seen from above East Asia, painted in travel-time bands from Seoul" width="720">

</div>


A pipeline for building global travel-time isochrone maps from open geodata.

It computes expected door-to-door travel time from each departure city in
`data/origins.toml` to every land cell on Earth (H3 resolution 6, refined to 7
in dense regions), by air, rail, ferry and road, and emits one PMTiles band
set plus binary time, airport, mode and rail-station arrays per departure.

## Documentation

| Topic | Guide |
| --- | --- |
| Current hosting, loading flow and performance measurements | [Site delivery](docs/site-delivery.md) |
| Deploy, verify and recover a release | [Deployment runbook](deploy/README.md) |
| Browser modules, vendored assets and design | [Frontend](web/README.md) |
| Dataset formats and pipeline/page compatibility | [Data contract](docs/contract.md) |
| Work records and prior reviews | [Plans and rollout history](plan/README.md) |

The main site connects directly to Seoul. Public map data can use a separate
Cloudflare hostname when the browser measures a faster path. Map tiles and
basic times load before optional route data, with visible loading and retry
states. See the delivery guide for measured results and their limits.

## Development

```bash
uv sync
uv run ruff check .
uv run pytest                              # the gate; -m "not integration" for a fast loop
uv run transport-maps build-all            # every origin -> dist/ (one build per dist/ at a time)
uv run transport-maps build-all --only seoul,tokyo   # a smoke test through every gate; index.json untouched
uv run transport-maps build-all --skip-existing     # resume a build that died: rebuild only unfinished origins
uv run transport-maps build-all --offline  # read every raw input from data/cache, ask no upstream
uv run transport-maps reindex              # rewrite dist/index.json from the artifacts on disk
uv run transport-maps assets               # places.json, airports.json, borders.pmtiles -> dist/
uv run python scripts/check_dist.py        # is dist/ consistent enough to deploy?
uv run python scripts/build_water_tiles.py # the coast, once -> dist/water.pmtiles
```

`assets` writes the three static files the page loads beside the per-origin
arrays (`transport-maps assets airports.json` for one). They depend on no graph
and no origin, so `build-all` does not write them; rerun it when the GeoNames,
OurAirports, LSIB or Natural Earth inputs change. `borders.pmtiles` needs
tippecanoe, like the coast, and refuses a new LSIB edition until
`emit/borders.py` has been reviewed against it. It takes the same build lock
as `build-all` and `reindex`.

`--only` and `--limit` make a PARTIAL build: `index.json` is left untouched, but
`dist/hover_cells.bin` and the named origins under `dist/origins/` **are**
rewritten, so a smoke test against a published `dist/` mixes generations. Point
it at a scratch `dist/` unless you mean to replace those origins.

Each origin's files carry a completion record, `.progress/<slug>.json` beside
`origins/` (never deployed). It says "writing" from before the origin's first
file is replaced until after its last, then "complete" with every file's size,
keyed on the run's `inputsHash` (code by content, `calibration.toml`,
`origins.toml`, format constants) and a digest of the graph (the data inputs).
`--skip-existing` leaves alone an origin whose record is complete under the
current key with its files at the recorded sizes and builds the rest, so a run
that died is resumed with the same command plus the flag (`--exclude <mode>`
for a variant). The graph is rebuilt either way: skipping saves the per-origin
solves, not the graph build. `index.json` and a variant's `variant.json` are
written only once every origin is complete for the run, whichever run built it.
`scripts/check_dist.py` refuses an origin whose record still says "writing".

Every build first asks each upstream whether its raw input changed and
downloads what did (`sources/_fetch.py`): a conditional request per file
(ETag / Last-Modified, from a `<file>.meta.json` sidecar beside it in
`data/cache`) for OurAirports, Natural Earth, GRIP4, GeoNames and the water
polygons; Geofabrik's `state.txt` against the snapshot in each OSM extract's
header, re-extracting a region more than `TRANSPORT_MAPS_OSM_MAX_AGE_DAYS`
(default 7) behind through `scripts/osm_fixed_links.sh` / `osm_rail.sh` with
`OSM_REPLACE=1`; and the Wikipedia crawl, whose articles are refetched once a
day old (Wikidata codes once a month old). A failed check keeps the cached
copy and says so; a missing input with no copy fails. Every derived cache keys
on its input's content, so a changed input rebuilds exactly what depends on
it, and `index.json` records what was read under `inputs`. `--offline` (or
`TRANSPORT_MAPS_OFFLINE=1`) asks nothing and reads the cache as it is -- use it
to reproduce a past build, and with `--skip-existing` to resume one on the
inputs it read.

`reindex` writes `index.json` and nothing else. It is for the case where a build
outlives a change to the index emitter: the parent process writes `index.json`
at the end of the run using the module it imported at the start, so a sixteen-hour
build can publish an index that predates its own artifacts. It takes the build
lock, lists only origins whose whole file set is present and the right length,
and carries the previous index's build identity forward rather than stamping the
current checkout.

The bands are painted one cell past the shore and the static `water.pmtiles`
layer, built once from OpenStreetMap water polygons, cuts them back to the real
coastline on the page. It is not produced by `build-all`; rebuild it when the
water polygons change -- the script checks them against the upstream itself.

## Data sources and attribution

This project redistributes data derived from the sources below. Anything built
from `dist/` must carry the same credits; `dist/index.json` ships them in its
`attribution` block for exactly that purpose.

| Source | Licence | Used for |
| --- | --- | --- |
| [Wikipedia](https://en.wikipedia.org/) | CC BY-SA 4.0 | airline route network, from 'Airlines and destinations' sections |
| [Wikidata](https://www.wikidata.org/) | CC0 1.0 | resolving destination articles to IATA codes (property P238) |
| [OurAirports](https://ourairports.com/data/) | Public Domain | airport locations, sizes and scheduled-service status |
| [Natural Earth](https://www.naturalearthdata.com/) | Public Domain | 1:10m land polygons defining the H3 cell universe; the de facto lines LSIB does not draw (Crimea, Northern Cyprus, Somaliland, Western Sahara, Siachen); populated places behind the urban mask |
| [LSIB (U.S. Department of State)](https://catalog.data.gov/dataset/large-scale-international-boundaries) | Public Domain | international boundaries and other lines of separation (Large Scale International Boundaries, v11.4) |
| [GRIP4 (Global Roads Inventory Project)](https://www.globio.info/download-grip-dataset) | CC0 1.0 | road-density rasters setting per-cell ground speed |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | ODbL 1.0 | coastlines drawn on the map (water polygons via [osmdata.openstreetmap.de](https://osmdata.openstreetmap.de/)); rail route relations and ferry ways; upstream source of the GRIP4 road network |
| [GeoNames](https://www.geonames.org/) | CC BY 4.0 | departure cities and the place names under the cursor (cities15000) |
| [HydroLAKES](https://www.hydrosheds.org/products/hydrolakes) | CC BY 4.0 | lake outlines drawn on the map (Messager et al. 2016) |
| [DELFI e.V. (German timetable, via gtfs.de)](https://gtfs.de/en/feeds/de_fv/) | CC BY 4.0 | scheduled journey times of German long-distance trains (ICE, IC, EC) |
| [KorailGTFS (Mikołaj Kuranowski)](https://mkuran.pl/gtfs/) | CC BY 4.0 | scheduled journey times of Korail intercity trains (KTX, ITX, Mugunghwa) |
| [SNCF Voyageurs (French timetable, via transport.data.gouv.fr)](https://transport.data.gouv.fr/datasets/horaires-sncf) | ODbL 1.0 | scheduled journey times of TGV INOUI, OUIGO, Intercités, Lyria and ICE trains in France |
| [Renfe Viajeros (Spanish timetable, data.renfe.com)](https://data.renfe.com/dataset/horarios-de-alta-velocidad-larga-distancia-y-media-distancia) | CC BY 4.0 | scheduled journey times of AVE, Avlo, Avant, Euromed, Alvia and Intercity trains |
| [opentransportdata.swiss (Swiss timetable)](https://opentransportdata.swiss/en/terms-of-use/) | opentransportdata.swiss terms of use | scheduled journey times of Swiss intercity trains (IC, IR, EC, ICE, TGV) |
| [ÖBB-Personenverkehr (Austrian timetable, data.oebb.at)](https://data.oebb.at/de/datensaetze~soll-fahrplan-gtfs~) | CC BY 4.0 | scheduled journey times of Railjet, Nightjet, EuroCity, InterCity and ICE trains in Austria |
| [OVapi (Dutch timetable, gtfs.ovapi.nl)](https://openov.nl/) | CC0 1.0 | scheduled journey times of Dutch Intercity, Intercity direct and international trains |
| [NMBS/SNCB (Belgian timetable, via the Belgian Mobility Open Data Portal)](https://data.belgianmobility.io/en/terms.html) | CC BY 4.0 | scheduled journey times of InterCity and EuroCity trains in Belgium |
| [Entur (Norwegian timetable; contains data under the Norwegian licence for Open Government data, NLOD)](https://developer.entur.org/stops-and-timetable-data) | NLOD 2.0 | scheduled journey times of Vy, SJ Nord and Go-Ahead Norge long-distance trains |
| [Fintraffic / digitraffic.fi (Finnish timetable)](https://www.digitraffic.fi/en/railway-traffic/) | CC BY 4.0 | scheduled journey times of VR Pendolino, InterCity and night trains |
| [Rejseplanen (Danish timetable)](https://datavejviser-indtastning.digst.govcloud.dk/dataset/rejseplanen-gtfs) | CC BY 4.0 | scheduled journey times of DSB InterCity, IC Lyn and EuroCity trains |
| [VIA Rail Canada (Canadian timetable)](https://www.viarail.ca/en/developer-resources) | Open Government Licence - Canada 2.0 | scheduled journey times of VIA Rail intercity and long-distance trains |
| [Published timetables of JR East, JR Central, JR West, JR Kyushu, China Railway (12306) and Amtrak](https://timetables.jreast.co.jp/) | timetable facts, each cited to its operator's page | scheduled journey times of the fastest Shinkansen, Chinese high-speed and Acela trains between major stations |
| [adsb.lol](https://adsb.lol/) | ODbL 1.0 | observed flights behind the fitted cruise speed and climb/descent penalty |

OpenStreetMap enters three ways: rail route relations and ferry ways
(`route=ferry`) are parsed from Geofabrik PBF extracts (`sources/osm.py`), the
coastline layer is built from OSM water polygons (`emit/water.py`), and GRIP4
is itself compiled from many road datasets **including OpenStreetMap**, so the
road-density rasters that set every ground speed are downstream of it as well.

GRIP4 asks to be cited as: Meijer, J.R., Huijbregts, M.A.J., Schotten, C.G.J.
and Schipper, A.M. (2018): Global patterns of current and future road
infrastructure. *Environmental Research Letters* 13-064006.

No commercial flight data (schedules, frequencies or positions) is used
anywhere in this pipeline; `tests/test_licence_firewall.py` checks that no
provider fingerprint reaches `dist/`. One commercial service is used during
**calibration only**: `scripts/calibrate_ground.py` samples driving times from
Google Routes and fits four of the six per-road-class speeds (classes 1-4)
and the urban factor, which `calibration.toml` (`[ground]`, `[urban]`) records
with their provenance and `graph/ground.py` and `sources/urban.py` read.
Roadless terrain and local roads keep published-figure defaults: for roadless
terrain the fit returned a negative time per kilometre (a reciprocal of
-0.00978 h/km, about -102 km/h, from 2,272 km across 55 journeys), which the
fit's sign filter refuses, and local roads drew 116 km across four journeys,
which its support guard refuses. `graph/ground.py` says which is which
at the constant itself, as CLAUDE.md's calibration rule requires. The sampled durations stay in
`data/build/` (gitignored) and nothing from them reaches `dist/`.

## Licence

The code in this repository is released under the [MIT License](LICENSE). That
covers the code only: the maps in `dist/` are derived from the data sources
above and carry their licences, notably OpenStreetMap's ODbL and the CC BY /
CC BY-SA attribution terms.
