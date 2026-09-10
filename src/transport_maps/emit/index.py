"""index.json plus the shared hover-cell ordering."""

import hashlib
import json
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import h3
import numpy as np

from transport_maps import _io, config
from transport_maps.emit import hover, modes

# Origin slugs become filenames under dist/origins and path segments in the
# page's fetch URLs, so reject anything that could escape the directory or
# start with a dot or dash: letters, digits, '_' and '-' only, and a
# letter or digit first. One grammar, checked where the slugs are read.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Redistribution obligations of the open datasets this artifact is derived from.
# The licence firewall (tests/test_licence_firewall.py) only proves that NO
# commercial flight records leaked into dist/; it says nothing about crediting
# the sources that legitimately did. Shipping the map without this block leaves
# the CC-BY-SA and ODbL obligations unmet while every gate reports green.
#
# OSM enters three ways: rail route relations and ferry ways parsed from
# Geofabrik extracts (sources/osm.py), the coastline layer (emit/water.py), and
# GRIP4, which is compiled partly from OSM.
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
        "usedFor": "1:10m land polygons defining the H3 cell universe; country borders; populated places behind the urban mask",
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
        "usedFor": "coastlines (water polygons via osmdata.openstreetmap.de); rail route relations and ferry ways; upstream source of the GRIP4 road network",
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
    slugs = [str(o.get("slug", "")) for o in origins]
    bad = [s for s in slugs if not _SLUG_RE.fullmatch(s)]
    if bad:
        raise ValueError(f"invalid origin slug(s) in {path}: {bad[:5]} -- letters, digits, "
                         "'_' and '-' only, starting with a letter or digit")
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate origin slug in origins.toml")
    return origins


def write_hover_cells(idx, out: Path) -> None:
    """Sorted res-4 cell ids as little-endian uint64, matching the .bin ordering.

    The frontend computes h3.latLngToCell(lat, lon, 4), converts it to its integer
    form, and binary-searches this array to get the index into each origin's .bin.
    """
    ids = np.array([h3.str_to_int(c) for c in hover.hover_cells(idx)], dtype="<u8")
    _io.write_bytes(out, ids.tobytes())


def mode_detail() -> dict[str, str]:
    """One sentence per surface mode, with the calibrated speeds it uses.

    Every figure comes from the calibration objects the graph itself uses,
    so the tooltips cannot drift from the model (they hard-coded 200/75/35/30
    before, which were equal to calibration.toml only by luck).
    """
    from transport_maps.graph import ground, rail
    from transport_maps.sources import urban

    kmh = ground.SPEED_BY_ROAD_CLASS_KMH
    rc, fc = rail.load_rail_calibration(), rail.load_ferry_calibration()
    halved = (f"halved inside cities (within {urban.URBAN_RADIUS_KM:.0f} km of a city "
              f"over {urban.URBAN_POP_MIN:,.0f} people)")
    return {
        "rail": "Scheduled trains from OpenStreetMap route relations, stop to stop; "
                f"high-speed lines at {rc.highspeed_kmh:.0f} km/h, conventional at "
                f"{rc.conventional_kmh:.0f} km/h along the track, plus {rc.boarding_min:.0f} min "
                "to board.",
        "ferry": f"Scheduled ferry routes from OpenStreetMap, at {fc.speed_kmh:.0f} km/h plus "
                 f"{fc.terminal_min:.0f} min at the terminals.",
        "highway": f"Motorways and expressways, fitted at {kmh[1]:.0f} km/h free-flow, {halved}.",
        # sorted(): the table is ordered by road class, not by speed, so
        # classes 2 and 3 (57 and 50 km/h) printed "fitted at 57-50 km/h" --
        # a backwards range, shipped in index.json and read out in the page's
        # route tooltip beside an ascending "18-25".
        "major road": f"Primary and secondary roads, fitted at "
                      f"{min(kmh[2], kmh[3]):.0f}-{max(kmh[2], kmh[3]):.0f} km/h, {halved}.",
        "minor road": f"Tertiary and local roads, fitted at "
                      f"{min(kmh[4], kmh[5]):.0f}-{max(kmh[4], kmh[5]):.0f} km/h, {halved}.",
        "track": f"No mapped road: {kmh[0]:.0f} km/h, walking pace.",
    }


def _git_head() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=config.ROOT, capture_output=True, text=True, check=True).stdout
        return head + ("-dirty" if dirty.strip() else "")
    except (OSError, subprocess.CalledProcessError):
        return "nogit"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else "absent"


def build_identity(started: datetime | None = None) -> dict[str, str]:
    """Which inputs and which run produced an artifact.

    `inputsHash` covers the code (git head, dirty flag), the two hand-edited
    inputs (calibration.toml, origins.toml) and the constants that shape the
    grid, the bands and the mode channels; `buildId` adds the start time so
    two runs of one input set (one of them aborted) stay distinguishable.
    """
    started = started or datetime.now(UTC)
    # Everything below is sampled NOW, so this must be called when the build
    # STARTS. It used to be called as the last statement of _build_all_locked,
    # which recorded the checkout as it stood when the build stopped: for the
    # 553-origin run that meant a git head 38 commits ahead and hashes of a
    # calibration.toml and origins.toml rewritten 70 minutes after the graph
    # had already read them. `inputsHash` then named inputs the artifacts were
    # not built from -- the exact opposite of its purpose.
    inputs = _io.params_hash(
        _git_head(), _sha256(config.ROOT / "calibration.toml"),
        _sha256(config.DATA / "origins.toml"),
        config.SOLVE_RES, config.FINE_RES, config.HOVER_RES, config.BAND_EDGES_MIN,
        modes.CHANNELS)
    return {"inputsHash": inputs,
            "buildId": f"{inputs}-{started:%Y%m%dT%H%M%SZ}",
            "builtAt": started.replace(microsecond=0).isoformat()}


def write_index(origins: list[dict], out: Path, *, hover_cell_count: int | None = None,
                graph: dict | None = None, identity: dict | None = None,
                modes_detail: dict[str, str] | None = None,
                rail_detail: bool = True) -> None:
    """index.json: what the page needs to read every other artifact.

    `hover_cell_count` is checked by the page against the length of
    hover_cells.bin itself (app.js: `meta.hoverCellCount !== hoverCells.length`
    -> fatal), which catches an index.json and a cell ordering from two
    different builds. It is NOT what validates the per-origin arrays -- those
    are checked against `hoverCells.length` on arrival, whether or not this
    field is present; `graph` says whether rail and ferries
    were in the build (a road-and-air build is otherwise indistinguishable);
    `identity` is build_identity(). All are optional so a stale index.json is
    still valid -- the page has a fallback for each.

    `modes_detail` should be sampled when the build STARTS. Called here it
    re-reads calibration.toml at write time, which for a sixteen-hour build is
    sixteen hours after the graph was weighted: the prose would describe
    constants the artifacts were not built with.

    `rail_detail` says whether {slug}.rail.bin/.rail.json are on disk. It
    defaults True because this emitter's own build always writes them (see
    emit.rail_detail.write_rail_detail, which writes both even when the tables
    are empty), but it MUST be passed by any caller indexing artifacts it did
    not produce -- `reindex` over a dist/ from an older emitter, above all.
    Writing True over a dist/ with no rail files makes the page fetch two 404s
    per origin switch, which browser_verify.sh fails the deploy for, and makes
    check_dist report one problem per origin naming `reindex` as the remedy for
    a state `reindex` created.
    """
    payload = {
        "bandEdgesMin": list(config.BAND_EDGES_MIN),
        "unreachable": config.UNREACHABLE,
        "hoverRes": config.HOVER_RES,
        "solveRes": config.SOLVE_RES,
        "fineRes": config.FINE_RES,
        # Channel order of .modes.bin, so the page never re-types it.
        "modeChannels": list(modes.CHANNELS),
        # How each surface mode was modelled, for the route's hover notes.
        "modeDetail": modes_detail if modes_detail is not None else mode_detail(),
        # The page asks for {slug}.rail.bin/.rail.json only when this is true,
        # so an older build is not two 404s per origin switch.
        "railDetail": bool(rail_detail),
        "hoverCellsUrl": "hover_cells.bin",
        "attribution": [dict(entry) for entry in ATTRIBUTION],
        "origins": [
            {"slug": o["slug"], "name": o["name"], "lat": o["lat"], "lon": o["lon"]}
            for o in origins
        ],
    }
    if hover_cell_count is not None:
        payload["hoverCellCount"] = int(hover_cell_count)
    if graph is not None:
        payload["graph"] = dict(graph)
    if identity is not None:
        payload.update(identity)
    _io.write_text(out, json.dumps(payload, separators=(",", ":")))
