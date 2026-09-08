"""Rail routes from OpenStreetMap `type=route, route=train` relations.

A route relation carries an ORDERED list of stop members, which is the station
sequence directly. The tempting alternative -- walking the member ways' geometry
and inferring which station comes next -- is wrong on every branching line,
every reversal, and every route whose ways are not contiguous in the relation.
Member order is authoritative; geometry is not consulted at all.

Two passes are required and cannot be merged: relations name their stops by node
id, and a PBF stores nodes before relations, so the ids to look up are not known
until after the node block has already streamed past.
"""

from __future__ import annotations

import osmium
import polars as pl

from .. import config
from ._utils import _atomic_write, _params_hash

# Members carrying the passenger stop sequence. A route may use the modern
# `stop*` roles or only the older `platform*` ones; preferring stops and falling
# back keeps both shapes usable instead of silently yielding an empty sequence.
STOP_ROLES = ("stop", "stop_entry_only", "stop_exit_only")
PLATFORM_ROLES = ("platform", "platform_entry_only", "platform_exit_only")
# Below this a "route" is a fragment or a tagging error, not a service.
MIN_STOPS = 2

SCHEMA = {
    "route_id": pl.Int64, "seq": pl.Int64, "stop_id": pl.Int64,
    "lat": pl.Float64, "lon": pl.Float64, "name": pl.Utf8, "highspeed": pl.Boolean,
}


def _is_highspeed(tags) -> bool:
    """OSM spells this two ways; both are in active use."""
    return tags.get("highspeed") == "yes" or tags.get("service") == "high_speed"


def _relations(path) -> tuple[dict, set[int]]:
    """Ordered stop-node ids per train route, plus every id to resolve."""
    routes, wanted = {}, set()
    for obj in osmium.FileProcessor(str(path), osmium.osm.RELATION):
        t = obj.tags
        if t.get("type") != "route" or t.get("route") != "train":
            continue
        for roles in (STOP_ROLES, PLATFORM_ROLES):
            ids = [m.ref for m in obj.members
                   if m.type == "n" and m.role in roles]
            if len(ids) >= MIN_STOPS:
                routes[obj.id] = {"stops": ids,
                                  "name": t.get("name") or "",
                                  "highspeed": _is_highspeed(t)}
                wanted.update(ids)
                break
    return routes, wanted


def _nodes(path, wanted: set[int]) -> dict:
    """Coordinates and names for the stop ids a relation pass asked for."""
    found = {}
    if not wanted:
        return found
    for obj in osmium.FileProcessor(str(path), osmium.osm.NODE):
        if obj.id in wanted:
            found[obj.id] = (obj.location.lat, obj.location.lon,
                             obj.tags.get("name") or "")
    return found


def _parse(path) -> list[dict]:
    routes, wanted = _relations(path)
    coords = _nodes(path, wanted)
    rows = []
    for route_id, r in routes.items():
        # A stop whose node the extract does not contain (a route crossing the
        # region boundary) is dropped, not guessed at. Renumber so `seq` stays
        # gapless and a consumer can trust consecutive pairs are adjacent stops.
        resolved = [(sid, coords[sid]) for sid in r["stops"] if sid in coords]
        if len(resolved) < MIN_STOPS:
            continue
        for seq, (sid, (lat, lon, node_name)) in enumerate(resolved):
            rows.append({"route_id": route_id, "seq": seq, "stop_id": sid,
                         "lat": lat, "lon": lon,
                         "name": node_name or r["name"],
                         "highspeed": r["highspeed"]})
    return rows


FERRY_SCHEMA = {
    "way_id": pl.Int64, "from_lat": pl.Float64, "from_lon": pl.Float64,
    "to_lat": pl.Float64, "to_lon": pl.Float64, "name": pl.Utf8,
}
# Shorter than this is a river crossing whose terminals land in one H3 cell
# anyway; longer than this is not a scheduled ferry route.
MIN_FERRY_KM, MAX_FERRY_KM = 1.0, 4000.0
# A node sitting exactly on the antimeridian is where the extract cut the way,
# not where the ferry calls. Measuring to it invented two 4,800 km crossings
# out of one Pacific route. Real terminals do not land on the line to six
# decimal places.
ANTIMERIDIAN_EPS_DEG = 1e-6


def _ferries(path) -> list[dict]:
    """Ferry ways reduced to their two endpoints.

    A ferry way's intermediate nodes trace the sea crossing and carry no
    information the graph can use: what matters is which two places it joins.
    """
    ways, wanted = {}, set()
    for obj in osmium.FileProcessor(str(path), osmium.osm.WAY):
        if obj.tags.get("route") != "ferry":
            continue
        refs = [n.ref for n in obj.nodes]
        if len(refs) < 2 or refs[0] == refs[-1]:
            continue
        ways[obj.id] = (refs[0], refs[-1], obj.tags.get("name") or "")
        wanted.update((refs[0], refs[-1]))

    coords = {}
    if wanted:
        for obj in osmium.FileProcessor(str(path), osmium.osm.NODE):
            if obj.id in wanted:
                coords[obj.id] = (obj.location.lat, obj.location.lon)

    rows = []
    for way_id, (a, b, name) in ways.items():
        if a in coords and b in coords:
            if any(abs(abs(coords[n][1]) - 180.0) < ANTIMERIDIAN_EPS_DEG for n in (a, b)):
                continue
            rows.append({"way_id": way_id,
                         "from_lat": coords[a][0], "from_lon": coords[a][1],
                         "to_lat": coords[b][0], "to_lon": coords[b][1],
                         "name": name})
    return rows


def ferry_links(*, extracts_dir=None) -> pl.DataFrame:
    """Every ferry crossing's two endpoints, across all filtered extracts."""
    extracts_dir = extracts_dir or (config.CACHE / "osm")
    paths = sorted(extracts_dir.glob("*-rail.osm.pbf"))
    if not paths:
        raise FileNotFoundError(
            f"no *-rail.osm.pbf in {extracts_dir}; run scripts/osm_rail.sh first"
        )
    fingerprint = [(str(extracts_dir), p.name, p.stat().st_size, p.stat().st_mtime_ns)
                   for p in paths]
    cached = config.CACHE / f"ferry_links-{_params_hash(fingerprint)}.parquet"
    if cached.exists():
        return pl.read_parquet(cached)

    rows = []
    for p in paths:
        rows.extend(_ferries(p))
    # A crossing mapped in two regional extracts appears twice under one id.
    df = pl.DataFrame(rows, schema=FERRY_SCHEMA).unique(subset=["way_id"], keep="first")
    _atomic_write(cached, lambda tmp: df.write_parquet(tmp))
    return df


def rail_routes(*, extracts_dir=None) -> pl.DataFrame:
    """Every train route's ordered stops, across all filtered regional extracts."""
    extracts_dir = extracts_dir or (config.CACHE / "osm")
    paths = sorted(extracts_dir.glob("*-rail.osm.pbf"))
    if not paths:
        raise FileNotFoundError(
            f"no *-rail.osm.pbf in {extracts_dir}; run scripts/osm_rail.sh first"
        )

    # The key must cover the INPUT BYTES, not just the filenames. Keying on
    # names alone means a re-downloaded extract -- same name, new contents --
    # silently reuses the stale parquet, and two callers pointing at different
    # directories that happen to hold "europe-rail.osm.pbf" read each other's
    # results. Size and mtime are what change when a file is replaced.
    fingerprint = [(str(extracts_dir), p.name, p.stat().st_size, p.stat().st_mtime_ns)
                   for p in paths]
    key = _params_hash(fingerprint, STOP_ROLES, PLATFORM_ROLES, MIN_STOPS)
    cached = config.CACHE / f"rail_routes-{key}.parquet"
    if cached.exists():
        return pl.read_parquet(cached)

    rows = []
    for p in paths:
        before = len(rows)
        rows.extend(_parse(p))
        print(f"  {p.name}: {len(rows) - before:,} stop rows", flush=True)

    df = pl.DataFrame(rows, schema=SCHEMA)
    if df.is_empty():
        raise RuntimeError(
            "parsed every extract and found no train routes at all; the filter "
            "step most likely dropped the route relations"
        )
    # One route id can appear in two regional extracts (a cross-border service),
    # each holding only the stops inside that region. Keeping both would emit
    # two conflicting sequences under the same id, so the longer one wins.
    df = (df.sort("route_id", "seq")
            .join(df.group_by("route_id").len().rename({"len": "_n"}), on="route_id")
            .sort("_n", descending=True)
            .unique(subset=["route_id", "seq"], keep="first")
            .drop("_n")
            .sort("route_id", "seq"))
    _atomic_write(cached, lambda tmp: df.write_parquet(tmp))
    return df
