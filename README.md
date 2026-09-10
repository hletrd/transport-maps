<div align="center">

# Isochronic Passage Chart

**How long it takes to reach anywhere on Earth, door to door, from the cities in `data/origins.toml` (553 today; the live build may lag).**

[![Live site](https://img.shields.io/badge/live-worldmap.atik.kr-1f6feb)](https://worldmap.atik.kr/)
![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab)
![MapLibre GL JS 5.24](https://img.shields.io/badge/MapLibre_GL_JS-5.24-396cb2)
![PMTiles](https://img.shields.io/badge/tiles-PMTiles-6b4fbb)
![H3 resolution 6/7](https://img.shields.io/badge/grid-H3_res_6%2F7-e8802b)

[**Open the map**](https://worldmap.atik.kr/) · [How it is built](#development) · [Data sources](#data-sources-and-attribution)

<img src="web/preview.png" alt="The globe, seen from above East Asia, painted in travel-time bands from Seoul" width="720">

</div>


A pipeline for building global travel-time isochrone maps from open geodata.

It computes expected door-to-door travel time from each departure city in
`data/origins.toml` to every land cell on Earth (H3 resolution 6, refined to 7
in dense regions), by air, rail, ferry and road, and emits one PMTiles band
set plus binary time, airport, mode and rail-station arrays per departure.

## Development

```bash
uv sync
uv run ruff check .
uv run pytest                              # the gate; -m "not integration" for a fast loop
uv run transport-maps build-all            # every origin -> dist/ (one build per dist/ at a time)
uv run transport-maps build-all --only seoul,tokyo   # a smoke test through every gate; index.json untouched
uv run transport-maps reindex              # rewrite dist/index.json from the artifacts on disk
uv run python scripts/check_dist.py        # is dist/ consistent enough to deploy?
uv run python scripts/build_water_tiles.py # the coast, once -> dist/water.pmtiles
```

`--only` and `--limit` make a PARTIAL build: `index.json` is left untouched, but
`dist/hover_cells.bin` and the named origins under `dist/origins/` **are**
rewritten, so a smoke test against a published `dist/` mixes generations. Point
it at a scratch `dist/` unless you mean to replace those origins.

`reindex` writes `index.json` and nothing else. It is for the case where a build
outlives a change to the index emitter: the parent process writes `index.json`
at the end of the run using the module it imported at the start, so a sixteen-hour
build can publish an index that predates its own artifacts. It takes the build
lock, lists only origins whose whole file set is present and the right length,
and carries the previous index's build identity forward rather than stamping the
current checkout.

The bands are painted one cell past the shore and the static `water.pmtiles`
layer, built once from OpenStreetMap water polygons, cuts them back to the real
coastline on the page. It is not produced by `build-all`; rebuild it only when
refreshing the OSM download.

## Data sources and attribution

This project redistributes data derived from the sources below. Anything built
from `dist/` must carry the same credits; `dist/index.json` ships them in its
`attribution` block for exactly that purpose.

| Source | Licence | Used for |
| --- | --- | --- |
| [Wikipedia](https://en.wikipedia.org/) | CC BY-SA 4.0 | airline route network, from 'Airlines and destinations' sections |
| [Wikidata](https://www.wikidata.org/) | CC0 1.0 | resolving destination articles to IATA codes (property P238) |
| [OurAirports](https://ourairports.com/data/) | Public Domain | airport locations, sizes and scheduled-service status |
| [Natural Earth](https://www.naturalearthdata.com/) | Public Domain | 1:10m land polygons defining the H3 cell universe; country borders; populated places behind the urban mask |
| [GRIP4 (Global Roads Inventory Project)](https://www.globio.info/download-grip-dataset) | CC0 1.0 | road-density rasters setting per-cell ground speed |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | ODbL 1.0 | coastlines drawn on the map (water polygons via [osmdata.openstreetmap.de](https://osmdata.openstreetmap.de/)); rail route relations and ferry ways; upstream source of the GRIP4 road network |
| [GeoNames](https://www.geonames.org/) | CC BY 4.0 | departure cities and the place names under the cursor (cities15000) |
| [HydroLAKES](https://www.hydrosheds.org/products/hydrolakes) | CC BY 4.0 | lake outlines drawn on the map (Messager et al. 2016) |
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
Google Routes and fits the per-road-class speeds in `graph/ground.py` and the
urban factor in `sources/urban.py`. The sampled durations stay in
`data/build/` (gitignored) and nothing from them reaches `dist/`.
