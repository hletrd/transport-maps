"""index.json plus the shared hover-cell ordering."""

import json
import tomllib
from pathlib import Path

import h3
import numpy as np

from transport_maps import config
from transport_maps.emit import hover

# Redistribution obligations of the open datasets this artifact is derived from.
# The licence firewall (tests/test_licence_firewall.py) only proves that NO
# commercial flight records leaked into dist/; it says nothing about crediting
# the sources that legitimately did. Shipping the map without this block leaves
# the CC-BY-SA and ODbL obligations unmet while every gate reports green.
#
# GRIP4 is itself built from many sources INCLUDING OpenStreetMap, which is why
# OSM appears here even though this pipeline never queries OSM directly: the
# road-density rasters that set every ground speed are downstream of it.
ATTRIBUTION: tuple[dict[str, str], ...] = (
    {
        "name": "Wikipedia",
        "licence": "CC BY-SA 4.0",
        "url": "https://en.wikipedia.org/",
        "usedFor": "airline route network, from 'Airlines and destinations' sections",
    },
    {
        "name": "Wikidata",
        "licence": "CC0 1.0",
        "url": "https://www.wikidata.org/",
        "usedFor": "resolving destination articles to IATA codes (property P238)",
    },
    {
        "name": "OurAirports",
        "licence": "Public Domain",
        "url": "https://ourairports.com/data/",
        "usedFor": "airport locations, sizes and scheduled-service status",
    },
    {
        "name": "Natural Earth",
        "licence": "Public Domain",
        "url": "https://www.naturalearthdata.com/",
        "usedFor": "1:10m land polygons defining the H3 cell universe",
    },
    {
        "name": "GRIP4 (Global Roads Inventory Project)",
        "licence": "CC0 1.0",
        "url": "https://www.globio.info/download-grip-dataset",
        "usedFor": "road-density rasters setting per-cell ground speed",
    },
    {
        "name": "OpenStreetMap",
        "licence": "ODbL 1.0",
        "url": "https://www.openstreetmap.org/copyright",
        "usedFor": "coastlines (water polygons via osmdata.openstreetmap.de); rail route relations; upstream source of the GRIP4 road network",
    },
    {
        "name": "GeoNames",
        "licence": "CC BY 4.0",
        "url": "https://www.geonames.org/",
        "usedFor": "departure cities and the place names under the cursor",
    },
    {
        "name": "HydroLAKES",
        "licence": "CC BY 4.0",
        "url": "https://www.hydrosheds.org/products/hydrolakes",
        "usedFor": "lake outlines drawn on the map (Messager et al. 2016)",
    },
    {
        "name": "adsb.lol",
        "licence": "ODbL 1.0",
        "url": "https://adsb.lol/",
        "usedFor": "observed flights behind the fitted cruise speed and "
                   "climb/descent penalty",
    },
)


def load_origins(path: Path | None = None) -> list[dict]:
    path = path or (config.DATA / "origins.toml")
    with open(path, "rb") as fh:
        origins = tomllib.load(fh).get("origin", [])
    if not origins:
        # A valid index.json with no origins is a page that throws on its
        # first line (cities[0]) -- the blank-globe class of failure.
        raise ValueError(f"{path} lists no origins")
    slugs = [o["slug"] for o in origins]
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate origin slug in origins.toml")
    return origins


def write_hover_cells(idx, out: Path) -> None:
    """Sorted res-4 cell ids as little-endian uint64, matching the .bin ordering.

    The frontend computes h3.latLngToCell(lat, lon, 4), converts it to its integer
    form, and binary-searches this array to get the index into each origin's .bin.
    """
    ids = np.array([h3.str_to_int(c) for c in hover.hover_cells(idx)], dtype="<u8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(ids.tobytes())


def mode_detail() -> dict[str, str]:
    """One sentence per surface mode, with the calibrated speeds it uses."""
    from transport_maps.graph import ground
    from transport_maps.sources import urban

    kmh = ground.SPEED_BY_ROAD_CLASS_KMH
    halved = f"halved inside cities (within {urban.URBAN_RADIUS_KM:.0f} km of a city over {urban.URBAN_POP_MIN:,})"
    return {
        "rail": "Scheduled trains from OpenStreetMap route relations, stop to stop; "
                "high-speed lines at 200 km/h, conventional at 75 km/h along the track, plus boarding time.",
        "ferry": "Scheduled ferry routes from OpenStreetMap, at 35 km/h plus 30 min at the terminals.",
        "highway": f"Motorways and expressways (GRIP4 class 1), fitted at {kmh[1]:.0f} km/h free-flow, {halved}.",
        "major road": f"Primary and secondary roads (GRIP4 classes 2-3), fitted at {kmh[2]:.0f}-{kmh[3]:.0f} km/h, {halved}.",
        "minor road": f"Tertiary and local roads (GRIP4 classes 4-5), fitted at {kmh[4]:.0f}-{kmh[5]:.0f} km/h, {halved}.",
        "track": f"No mapped road: {kmh[0]:.0f} km/h, walking pace.",
    }


def write_index(origins: list[dict], out: Path) -> None:
    payload = {
        "bandEdgesMin": list(config.BAND_EDGES_MIN),
        "unreachable": config.UNREACHABLE,
        "hoverRes": config.HOVER_RES,
        "solveRes": config.SOLVE_RES,
        "fineRes": config.FINE_RES,
        # How each surface mode was modelled, for the route's hover notes.
        "modeDetail": mode_detail(),
        # This emitter writes {slug}.rail.bin/.rail.json; the page asks for them
        # only when this is present, so an older build is not two 404s per origin.
        "railDetail": True,
        "hoverCellsUrl": "hover_cells.bin",
        "attribution": [dict(entry) for entry in ATTRIBUTION],
        "origins": [
            {"slug": o["slug"], "name": o["name"], "lat": o["lat"], "lon": o["lon"]}
            for o in origins
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
