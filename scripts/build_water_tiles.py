#!/usr/bin/env python3
"""Build the static coastline layer, dist/water.pmtiles.

    uv run python scripts/build_water_tiles.py

Independent of the per-origin build: run it once, and again only when the
OSM water polygons are refreshed (osmdata.openstreetmap.de publishes daily).
"""

from transport_maps import config
from transport_maps.emit import water

if __name__ == "__main__":
    water.build(config.DIST / "water.pmtiles")
