<div align="center">

# Isochronic Passage Chart

**How long it takes to reach anywhere on Earth from 550+ cities, door to door.**

[![Live site](https://img.shields.io/badge/live-worldmap.atik.kr-1f6feb)](https://worldmap.atik.kr/)
![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab)
![MapLibre GL JS 5](https://img.shields.io/badge/MapLibre_GL_JS-5.24-396cb2)
![PMTiles](https://img.shields.io/badge/tiles-PMTiles-6b4fbb)
![H3](https://img.shields.io/badge/grid-H3_res_6%2F7-e8802b)
![Open data](https://img.shields.io/badge/data-OpenStreetMap_%C2%B7_Natural_Earth_%C2%B7_GeoNames-2e8b57)
![No liability](https://img.shields.io/badge/for_reference_only-no_liability-777)

`isochrone` `travel-time` `globe` `maplibre` `pmtiles` `h3` `openstreetmap` `dijkstra` `air-routes` `rail` `ferries` `door-to-door`

[**Open the map**](https://worldmap.atik.kr/) · [How it is built](#development) · [Data sources](#data-sources-and-attribution)

<img src="web/preview.png" alt="The globe, seen from above East Asia, painted in travel-time bands from Seoul" width="720">

</div>


A pipeline for building global travel-time isochrone maps from open geodata.

This project generates accessibility data showing travel times from any location in the world using H3 hexagonal indexing and open-source routing data.

## Development

```bash
uv sync
uv run pytest
uv run transport-maps build-all            # every origin -> dist/
uv run python scripts/build_water_tiles.py # the coast, once -> dist/water.pmtiles
```

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
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | ODbL 1.0 | coastlines drawn on the map (water polygons via [osmdata.openstreetmap.de](https://osmdata.openstreetmap.de/)); rail route relations; upstream source of the GRIP4 road network |
| [GeoNames](https://www.geonames.org/) | CC BY 4.0 | departure cities and the place names under the cursor (cities15000) |
| [HydroLAKES](https://www.hydrosheds.org/products/hydrolakes) | CC BY 4.0 | lake outlines drawn on the map (Messager et al. 2016) |
| [adsb.lol](https://adsb.lol/) | ODbL 1.0 | observed flights behind the fitted cruise speed and climb/descent penalty |

GRIP4 is itself compiled from many road datasets **including OpenStreetMap**,
which is why OSM is credited here even though this pipeline never queries OSM
directly: the road-density rasters that set every ground speed are downstream
of it.

GRIP4 asks to be cited as: Meijer, J.R., Huijbregts, M.A.J., Schotten, C.G.J.
and Schipper, A.M. (2018): Global patterns of current and future road
infrastructure. *Environmental Research Letters* 13-064006.

No commercial flight data (schedules, frequencies or positions) is used
anywhere in this pipeline; `tests/test_licence_firewall.py` enforces that.
