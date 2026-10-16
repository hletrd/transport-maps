"""Rail legs timed from open GTFS timetables, where OSM does not know the train.

OSM route relations say which stations a service calls at and, for 2,360 of
them, one train's `duration`; the track says how fast the line may be run.
Neither says how fast a given train IS run, and on two corridors that is the
whole error (plan/2026-10-14-rebuild30-data.md): Germany maps 160 km/h on track
LZB signals at 230 and has no relation for the limited-stop ICE, so Berlin ->
Hamburg rode the stopping ICE at 131 min against 103-107 timetabled.

A timetable is the observation itself. Each feed in FEEDS is an open GTFS
export of scheduled passenger trains; its trips become two-stop routes in the
same frame `osm.rail_routes` builds, each with `timetabled_min` -- the
scheduled minutes between its two calls -- which `graph/rail.priced_legs` uses
in place of a tier price, and which wins the station pair outright in
`graph/rail.ride_edges` (the timetable is what runs; an OSM relation over the
same pair is a guess at it). Everything else -- the
pairs no feed covers, every country without one -- stays OSM's.

What a leg's minutes are. Every pair of calls (i, j) on a train is a leg of
its own, timed departure(i) -> arrival(j): exactly what a traveller boarding
at i and alighting at j rides, dwells at the calls between included and the
dwell at i (Berlin Hbf's 8 min on the ICE 28) not. Timing consecutive calls
alone cannot be exact for both ends -- arrival-to-arrival charges the dwell
at the boarding call (Berlin -> Hamburg 115 against the 107 the train takes),
departure-to-departure the dwell at the alighting one. Of all the trips that
call at the same stops in the same order (a "pattern"), each leg takes the
fastest. Times past 24:00 are GTFS's own continuation of the service day.

The trains a feed times in full are its operator's; an OSM relation of the
same operator (`supersedes`) is a priced guess at one of them, and is dropped
where the feed is loaded (Berlin -> Munich rode an OSM-priced ICE chain in
226 min against the 236 the fastest ICE takes).

Stations. A timetable stop is snapped to the OSM stop within SNAP_M, so its
station is the one OSM's relations and the cells already use -- the station
node a traveller boards at does not depend on which source timed the train.
A stop with no OSM stop that close keeps its own position and becomes a
station of its own. A timetabled leg ARRIVES at the station's alight-only
twin (`alight_only`, graph/rail.ALIGHT_SUFFIX), which no ride leaves: one
train is one leg, and changing trains goes through the cell and pays the
alighting and boarding charges, as a connection should.

Sources are listed with their licence, the attribution they ask for, and the
date the licence was read (emit/index.ATTRIBUTION credits them). A feed that
needs registration, or whose terms forbid redistributing derived data, is not
listed -- Britain's National Rail timetable (opendata.nationalrail.co.uk, an
account required) and Korail's (data.go.kr, an API key) among them.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import pathlib
import zipfile

import numpy as np
import polars as pl

from .. import config
from . import _fetch
from ._utils import _atomic_write, _params_hash

logger = logging.getLogger(__name__)

# Open GTFS feeds of scheduled passenger rail. `tier` is the service tier a
# row is captioned and fallback-priced under; its legs are timed by the feed.
FEEDS: tuple[dict, ...] = (
    {
        "name": "de_fv",
        "url": "https://download.gtfs.de/germany/fv_free/latest.zip",
        "what": "German long-distance rail (ICE, IC, EC and partners), 1.2 k stops",
        "publisher": "DELFI e.V., via gtfs.de",
        "licence": "CC BY 4.0",
        "licence_url": "https://gtfs.de/en/feeds/de_fv/",
        "checked": "2026-10-16",
        "tier": "long_distance",
        # OSM relations of this operator, at these tiers, are the trains this
        # feed times in full.
        "supersedes": r"^DB Fernverkehr",
        "supersedes_tiers": ("high_speed", "long_distance"),
    },
    {
        "name": "kr_korail",
        "url": "https://mkuran.pl/gtfs/korail.zip",
        "what": "Korail intercity rail (KTX, ITX, Saemaeul, Mugunghwa, Nuriro), "
                "built from Korail's published timetables",
        "publisher": "Mikołaj Kuranowski (KorailGTFS)",
        "licence": "CC BY 4.0",
        "licence_url": "https://mkuran.pl/gtfs/",
        "checked": "2026-10-16",
        "tier": "long_distance",
        # Korail also runs Seoul's commuter lines, which this feed does not
        # carry: only its intercity tiers are superseded.
        "supersedes": r"한국철도공사|코레일|^Korail",
        "supersedes_tiers": ("high_speed", "long_distance", "regional"),
    },
)

# A timetable stop joins the OSM stop this close: a large station's OSM stop
# positions and GTFS platforms sit within a few hundred metres of each other,
# and the next station along a main line is kilometres away. A modelling
# threshold, not fitted.
SNAP_M = 600.0

# Bumped when the parse changes shape, so a parquet written by older code is a
# MISS rather than a silently reused wrong answer (osm.RAIL_PARSER_VERSION).
# 2: a leg per pair of calls, departure(i) -> arrival(j).
# 3: the alighting row marked `alight_only` (graph/rail.ALIGHT_SUFFIX).
# 4: legs of no running time dropped.
GTFS_PARSER_VERSION = 4

# GTFS route_type values that are trains: 2 (rail) and the extended 100-117
# (railway service). Buses a rail feed carries (replacement services) are not.
RAIL_ROUTE_TYPES = {2, *range(100, 118)}


def feed_path(feed: dict) -> pathlib.Path:
    return config.CACHE / f"gtfs-{feed['name']}.zip"


def refresh() -> list[_fetch.Fingerprint]:
    """Every feed, checked against its upstream once per process (G2)."""
    return [_fetch.fetch(f["url"], feed_path(f)) for f in FEEDS]


def _minutes(t: str) -> float:
    h, m, s = (int(x) for x in t.split(":"))
    return h * 60 + m + s / 60


def _read(z: zipfile.ZipFile, name: str) -> list[dict]:
    with z.open(name) as fh:
        return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))


def patterns(path: pathlib.Path) -> list[dict]:
    """The feed's stop patterns: `stops` [(station id, name, lat, lon)],
    `minutes` {(i, j): fastest scheduled departure(i) -> arrival(j)},
    `route_name`, `operator`, and how many trips run the pattern."""
    with zipfile.ZipFile(path) as z:
        stops = {s["stop_id"]: s for s in _read(z, "stops.txt")}
        routes = {r["route_id"]: r for r in _read(z, "routes.txt")}
        agency = {a.get("agency_id", ""): a["agency_name"] for a in _read(z, "agency.txt")}
        trips = {t["trip_id"]: t for t in _read(z, "trips.txt")}
        calls: dict[str, list[dict]] = {}
        for r in _read(z, "stop_times.txt"):
            calls.setdefault(r["trip_id"], []).append(r)

    def station(stop_id: str) -> tuple[str, str, float, float]:
        # The parent station's id and position, the platform's own name: this
        # feed names a parent "Hamburg, Hamburg Hbf" and its platforms
        # "Hamburg Hbf", which is the name OSM and the page use.
        s = stops[stop_id]
        p = stops.get(s.get("parent_station") or "")
        where = p or s
        return (where["stop_id"], s["stop_name"], float(where["stop_lat"]),
                float(where["stop_lon"]))

    out: dict[tuple, dict] = {}
    for trip_id, rows in calls.items():
        trip = trips.get(trip_id)
        route = routes.get(trip["route_id"]) if trip else None
        if route is None or int(route.get("route_type") or -1) not in RAIL_ROUTE_TYPES:
            continue
        rows.sort(key=lambda r: int(r["stop_sequence"]))
        seq, arr, dep = [], [], []
        for r in rows:
            st = station(r["stop_id"])
            a = _minutes(r["arrival_time"] or r["departure_time"])
            d = _minutes(r["departure_time"] or r["arrival_time"])
            if seq and seq[-1][0] == st[0]:
                dep[-1] = d               # two platforms of one station: one call
                continue
            seq.append(st)
            arr.append(a)
            dep.append(d)
        if len(seq) < 2 or any(arr[k + 1] < dep[k] for k in range(len(seq) - 1)):
            continue                      # too short, or a malformed trip
        key = tuple(s[0] for s in seq)
        legs = {(i, j): arr[j] - dep[i] for i in range(len(seq)) for j in range(i + 1, len(seq))}
        p = out.get(key)
        if p is None:
            name = " ".join(x for x in (route.get("route_short_name") or "",
                                        trip.get("trip_short_name") or "") if x).strip()
            out[key] = {"stops": seq, "minutes": legs,
                        "route_name": name or route.get("route_long_name") or "",
                        "operator": agency.get(route.get("agency_id", ""), ""),
                        "trips": 1}
        else:
            p["minutes"] = {k: min(v, legs[k]) for k, v in p["minutes"].items()}
            p["trips"] += 1
    return list(out.values())


def _cache_path(fingerprints) -> pathlib.Path:
    return config.CACHE / ("gtfs_rail-" + _params_hash(
        [fp.sha256 for fp in fingerprints], [f["name"] for f in FEEDS],
        [f["tier"] for f in FEEDS], sorted(RAIL_ROUTE_TYPES), GTFS_PARSER_VERSION)
        + ".parquet")


def timetable_rows() -> pl.DataFrame:
    """Every feed's legs as unsnapped two-stop routes: one per pair of calls
    on each pattern, `timetabled_min` on the boarding row, null on the
    alighting one."""
    fps = refresh()
    cached = _cache_path(fps)
    if cached.exists():
        return pl.read_parquet(cached)
    rows = []
    for feed, fp in zip(FEEDS, fps, strict=True):
        pats = patterns(fp.path)
        for pat in pats:
            base = feed["name"] + "|" + "|".join(s[0] for s in pat["stops"])
            for (i, j), minutes in pat["minutes"].items():
                if minutes <= 0:
                    # A timing point the train passes in the same minute
                    # (DB's border marker "Kehl(Gr)"): no ride, and a
                    # zero-weight edge the graph build refuses. The stops
                    # either side still join through their longer pairs.
                    continue
                key = f"{base}|{i}|{j}".encode()
                rid = -(int.from_bytes(hashlib.sha1(b"gtfs|" + key).digest()[:6], "big") + 1)
                for seq, k in enumerate((i, j)):
                    _sid, name, lat, lon = pat["stops"][k]
                    rows.append({"route_id": rid, "seq": seq, "stop_id": rid * 2 - seq,
                                 "lat": lat, "lon": lon, "name": name, "tier": feed["tier"],
                                 "route_name": pat["route_name"], "operator": pat["operator"],
                                 "ref": "", "stops_listed": 2,
                                 "timetabled_min": minutes if seq == 0 else None,
                                 "alight_only": seq == 1,
                                 "feed": feed["name"]})
        logger.info("gtfs %s: %d patterns, %d trips", feed["name"], len(pats),
                    sum(p["trips"] for p in pats))
    df = pl.DataFrame(rows, schema={
        "route_id": pl.Int64, "seq": pl.Int64, "stop_id": pl.Int64, "lat": pl.Float64,
        "lon": pl.Float64, "name": pl.Utf8, "tier": pl.Utf8, "route_name": pl.Utf8,
        "operator": pl.Utf8, "ref": pl.Utf8, "stops_listed": pl.Int64,
        "timetabled_min": pl.Float64, "alight_only": pl.Boolean, "feed": pl.Utf8})
    _atomic_write(cached, lambda tmp: df.write_parquet(tmp))
    return df


def snap(tt: pl.DataFrame, osm_routes: pl.DataFrame, max_m: float = SNAP_M) -> pl.DataFrame:
    """`tt` with each stop moved onto the nearest OSM stop within `max_m`, so
    both sources meet at one station node."""
    from scipy.spatial import cKDTree

    if tt.is_empty() or osm_routes.is_empty():
        return tt
    ref = osm_routes.select("lat", "lon").unique()

    def xyz(lat, lon):
        la, lo = np.radians(lat), np.radians(lon)
        return np.c_[np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)]

    tree = cKDTree(xyz(ref["lat"].to_numpy(), ref["lon"].to_numpy()))
    d, i = tree.query(xyz(tt["lat"].to_numpy(), tt["lon"].to_numpy()))
    near = d * 6_371_008.8 <= max_m
    lat = np.where(near, ref["lat"].to_numpy()[i], tt["lat"].to_numpy())
    lon = np.where(near, ref["lon"].to_numpy()[i], tt["lon"].to_numpy())
    logger.info("gtfs: %d of %d calls snapped to an OSM stop within %.0f m",
                int(near.sum()), len(near), max_m)
    return tt.with_columns(pl.Series("lat", lat), pl.Series("lon", lon))


def superseded(osm_routes: pl.DataFrame) -> pl.Series:
    """True on the OSM rows of a relation whose trains a feed times in full:
    its operator matches the feed's `supersedes` and its tier is one of the
    feed's `supersedes_tiers`."""
    out = pl.Series([False] * len(osm_routes))
    if "operator" not in osm_routes.columns or "tier" not in osm_routes.columns:
        return out
    op = osm_routes["operator"].fill_null("")
    tier = osm_routes["tier"].fill_null("")
    for f in FEEDS:
        if f.get("supersedes"):
            out = out | (op.str.contains(f["supersedes"])
                         & tier.is_in(list(f.get("supersedes_tiers") or ())))
    return out


def with_timetables(osm_routes: pl.DataFrame) -> pl.DataFrame:
    """`osm_routes` without the relations the feeds time in full, plus every
    feed's legs snapped onto OSM's stations; `timetabled_min` is null on
    every OSM row."""
    drop = superseded(osm_routes)
    kept = osm_routes.filter(~drop)
    logger.info("gtfs: %d OSM relations superseded by a timetable",
                osm_routes.filter(drop)["route_id"].n_unique())
    tt = snap(timetable_rows().drop("feed"), kept)
    return pl.concat([kept, tt], how="diagonal_relaxed")
