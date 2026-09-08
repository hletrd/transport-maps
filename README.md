# Transport Maps

A pipeline for building global travel-time isochrone maps from open geodata.

This project generates accessibility data showing travel times from any location in the world using H3 hexagonal indexing and open-source routing data.

## Development

```bash
uv sync
uv run pytest
```

## Data sources and attribution

This project redistributes data derived from the sources below. Anything built
from `dist/` must carry the same credits; `dist/index.json` ships them in its
`attribution` block for exactly that purpose.

| Source | Licence | Used for |
| --- | --- | --- |
| [Wikipedia](https://en.wikipedia.org/) | CC BY-SA 4.0 | airline route network, from 'Airlines and destinations' sections |
| [Wikidata](https://www.wikidata.org/) | CC0 1.0 | resolving destination articles to IATA codes (property P238) |
| [OurAirports](https://ourairports.com/data/) | Public Domain | airport locations, sizes and scheduled-service status |
| [Natural Earth](https://www.naturalearthdata.com/) | Public Domain | 1:10m land polygons defining the H3 cell universe |
| [GRIP4 (Global Roads Inventory Project)](https://www.globio.info/download-grip-dataset) | CC0 1.0 | road-density rasters setting per-cell ground speed |
| [OpenStreetMap](https://www.openstreetmap.org/copyright) | ODbL 1.0 | upstream source of the GRIP4 road network; rail route relations |
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
