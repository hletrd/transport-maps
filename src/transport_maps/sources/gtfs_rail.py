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
account required) and Korail's (data.go.kr, an API key) among them. Two open
downloads were read and left out on 2026-10-20 for their terms: Amtrak's
(content.amtrak.com/content/gtfs/GTFS.zip), whose only statement is a FOIA
answer allowing use "as long as the user has the intent to benefit Amtrak",
which is not a licence a derived map can meet; and Trenitalia's, whose NeTEx
on Italy's National Access Point states no licence at all (the CC BY 4.0
GTFS conversion at github.com/deryclem/trenitalia-gtfs licenses only the
converter's own work).
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import pathlib
import re
import time
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
    # ---- added in rebuild 37 (owner, 2026-10-20: every official timetable
    # that is open). Each licence page was read on `checked`; none needs an
    # account or a key to download. Feeds that carry every regional, suburban
    # and bus service in their country take only the intercity trains, by
    # `select` (`tier_of`): OSM's relations keep the rest.
    {
        "name": "fr_sncf",
        "url": "https://eu.ftp.opendatasoft.com/sncf/plandata/"
               "Export_OpenData_SNCF_GTFS_NewTripId.zip",
        "what": "SNCF TGV INOUI, OUIGO, Intercités, Lyria and ICE in France",
        "publisher": "SNCF Voyageurs, via transport.data.gouv.fr",
        "licence": "ODbL 1.0",
        "licence_url": "https://transport.data.gouv.fr/datasets/horaires-sncf",
        "checked": "2026-10-20",
        "tier": "high_speed",
        # The export says which train a trip is only in its stop ids
        # ("StopPoint:OCETGV INOUI-87686006"); TER and its coaches are left.
        "select": (("stop_id", r"^StopPoint:OCE(TGV INOUI|OUIGO|ICE|Lyria)-", "high_speed"),
                   ("stop_id", r"^StopPoint:OCEINTERCITES( de nuit)?-", "long_distance")),
        "supersedes": r"^SNCF",
        "supersedes_tiers": ("high_speed", "long_distance"),
    },
    {
        "name": "es_renfe",
        "url": "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip",
        "what": "Renfe AVE, Avlo, Avant, Euromed, Alvia and Intercity",
        "publisher": "Renfe Viajeros, via data.renfe.com",
        "licence": "CC BY 4.0",
        "licence_url": "https://data.renfe.com/dataset/"
                       "horarios-de-alta-velocidad-larga-distancia-y-media-distancia",
        "checked": "2026-10-20",
        "tier": "high_speed",
        "select": (("route_short_name", r"^(AVE|AVE INT|AVLO|AVANT|AVANT EXP|EUROMED)$",
                    "high_speed"),
                   ("route_short_name", r"^(ALVIA|Intercity|TRENCELTA)$", "long_distance")),
        "supersedes": r"^Renfe",
        "supersedes_tiers": ("high_speed", "long_distance"),
    },
    {
        "name": "ch_sbb",
        # The permalink follows each year's file (gtfs_fp2026_YYYYMMDD.zip).
        "url": "https://data.opentransportdata.swiss/en/dataset/"
               "timetable-2026-gtfs2020/permalink",
        "what": "Swiss intercity rail (SBB, BLS, SOB and partners: IC, IR, EC, ICE, TGV)",
        "publisher": "opentransportdata.swiss (SBB, on behalf of the Swiss public transport sector)",
        "licence": "opentransportdata.swiss terms of use (open use, source must be cited)",
        "licence_url": "https://opentransportdata.swiss/en/terms-of-use/",
        "checked": "2026-10-20",
        "tier": "long_distance",
        # GTFS extended types: 101 high speed, 102 long distance, 103
        # inter-regional; 106 (RE, R) and 109 (S-Bahn) stay OSM's.
        "select": (("route_type", r"^101$", "high_speed"),
                   ("route_type", r"^10[23]$", "long_distance")),
        "supersedes": r"^(SBB|BLS|SOB)\b",
        "supersedes_tiers": ("high_speed", "long_distance"),
    },
    {
        "name": "at_oebb",
        # One file per timetable year: valid 2025-12-14 to 2026-12-12, then
        # GTFS_Fahrplan_2027.zip. The download page asks for the terms to be
        # ticked, not for an account.
        "url": "https://static.web.oebb.at/open-data/soll-fahrplan-gtfs/GTFS_Fahrplan_2026.zip",
        "what": "ÖBB Railjet, Nightjet, EuroCity, InterCity and ICE in Austria",
        "publisher": "ÖBB-Personenverkehr AG, via data.oebb.at",
        "licence": "CC BY 4.0",
        "licence_url": "https://data.oebb.at/de/datensaetze~soll-fahrplan-gtfs~",
        "checked": "2026-10-20",
        "tier": "high_speed",
        "select": (("trip_short_name", r"^(RJX|RJ|ICE|TGV) ", "high_speed"),
                   ("trip_short_name", r"^(EC|ECE|IC|NJ|EN|D) ", "long_distance")),
        "supersedes": r"ÖBB|^OeBB",
        "supersedes_tiers": ("high_speed", "long_distance"),
    },
    {
        "name": "nl_ovapi",
        "url": "https://gtfs.ovapi.nl/nl/gtfs-nl.zip",
        "what": "Dutch Intercity, Intercity direct and international trains (NS and others)",
        "publisher": "OVapi (Stichting OpenGeo), from NDOV timetable data",
        "licence": "CC0 1.0",
        "licence_url": "https://openov.nl/",
        "checked": "2026-10-20",
        "tier": "long_distance",
        "select": (("route_short_name", r"^(Intercity direct|ICE|Eurostar)", "high_speed"),
                   ("route_short_name", r"^(Intercity|Nightjet|GoVolta|European Sleeper)",
                    "long_distance")),
        "supersedes": r"^Nederlandse Spoorwegen|NS International",
        "supersedes_tiers": ("high_speed", "long_distance"),
    },
    {
        "name": "be_sncb",
        # The anonymous tier of the Belgian Mobility Open Data Portal: no key,
        # 100 requests a day, which a daily input check stays well inside.
        "url": "https://api-management-discovery-production.azure-api.net/"
               "api/gtfs/feed/nmbssncb/static",
        "what": "SNCB/NMBS InterCity and EuroCity trains in Belgium",
        "publisher": "NMBS/SNCB, via the Belgian Mobility Open Data Portal",
        "licence": "CC BY 4.0",
        "licence_url": "https://data.belgianmobility.io/en/terms.html",
        "checked": "2026-10-20",
        "tier": "long_distance",
        "select": (("route_short_name", r"^(IC|EC|NJ)$", "long_distance"),),
        "supersedes": r"^NMBS/SNCB",
        "supersedes_tiers": ("long_distance",),
    },
    {
        "name": "no_vy",
        "url": "https://storage.googleapis.com/marduk-production/outbound/gtfs/"
               "rb_vyg-aggregated-gtfs.zip",
        "what": "Vy long-distance trains in Norway (Bergensbanen, Dovre- and Sørlandsbanen)",
        "publisher": "Entur AS",
        "licence": "NLOD 2.0",
        "licence_url": "https://developer.entur.org/stops-and-timetable-data",
        "checked": "2026-10-20",
        "tier": "long_distance",
        # Norway's line codes: F long-distance, R regional, L local.
        "select": (("route_short_name", r"^F\d", "long_distance"),),
        "supersedes": r"^(Vy( Tog| Tåg)?|NSB)$",
        "supersedes_tiers": ("long_distance",),
    },
    {
        "name": "no_sjn",
        "url": "https://storage.googleapis.com/marduk-production/outbound/gtfs/"
               "rb_sjn-aggregated-gtfs.zip",
        "what": "SJ Nord long-distance trains in Norway (Dovrebanen, Nordlandsbanen)",
        "publisher": "Entur AS",
        "licence": "NLOD 2.0",
        "licence_url": "https://developer.entur.org/stops-and-timetable-data",
        "checked": "2026-10-20",
        "tier": "long_distance",
        "select": (("route_short_name", r"^F\d", "long_distance"),),
        "supersedes": r"^SJ No(rd|rge)",
        "supersedes_tiers": ("long_distance",),
    },
    {
        "name": "no_goa",
        "url": "https://storage.googleapis.com/marduk-production/outbound/gtfs/"
               "rb_goa-aggregated-gtfs.zip",
        "what": "Go-Ahead Norge long-distance trains (Sørlandsbanen)",
        "publisher": "Entur AS",
        "licence": "NLOD 2.0",
        "licence_url": "https://developer.entur.org/stops-and-timetable-data",
        "checked": "2026-10-20",
        "tier": "long_distance",
        "select": (("route_short_name", r"^F\d", "long_distance"),),
        "supersedes": r"^Go-Ahead Norge",
        "supersedes_tiers": ("long_distance",),
    },
    {
        "name": "fi_vr",
        "url": "https://rata.digitraffic.fi/api/v1/trains/gtfs-passenger.zip",
        "what": "VR long-distance trains in Finland (Pendolino, InterCity, night trains)",
        "publisher": "Fintraffic / digitraffic.fi",
        "licence": "CC BY 4.0",
        "licence_url": "https://www.digitraffic.fi/en/railway-traffic/",
        "checked": "2026-10-20",
        "tier": "long_distance",
        # S is the Pendolino, P an express, PYO a night train; museum
        # trains (MUS) and the commuter letters stay out.
        "select": (("route_short_name", r"^(IC|S|P|PYO) \d", "long_distance"),),
        "supersedes": r"^VR$",
        "supersedes_tiers": ("long_distance",),
    },
    {
        "name": "dk_rejseplanen",
        "url": "https://www.rejseplanen.info/labs/GTFS.zip",
        "what": "DSB InterCity, IC Lyn and EuroCity trains in Denmark",
        "publisher": "Rejseplanen A/S",
        "licence": "CC BY 4.0",
        "licence_url": "https://datavejviser-indtastning.digst.govcloud.dk/dataset/rejseplanen-gtfs",
        "checked": "2026-10-20",
        "tier": "long_distance",
        "select": (("route_short_name", r"^(IC|ICL|IC3|ECE|EC|RJ)$", "long_distance"),),
        "supersedes": r"^DSB$",
        "supersedes_tiers": ("long_distance",),
    },
    {
        "name": "ca_via",
        "url": "https://www.viarail.ca/sites/all/files/gtfs/viarail.zip",
        "what": "VIA Rail Canada intercity and long-distance trains",
        "publisher": "VIA Rail Canada",
        "licence": "Open Government Licence - Canada 2.0",
        "licence_url": "https://www.viarail.ca/en/developer-resources",
        "checked": "2026-10-20",
        "tier": "long_distance",
        "supersedes": r"^VIA Rail",
        "supersedes_tiers": ("long_distance", "regional", "default"),
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
# 5: a tier per pattern (a feed's `select`), and the tier in the route id.
GTFS_PARSER_VERSION = 5

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


def _member(z: zipfile.ZipFile, name: str) -> str:
    """`name` in the archive, at its root or in the one folder some exports
    put everything in (ÖBB's GTFS_Fahrplan_2026/stops.txt)."""
    names = z.namelist()
    if name in names:
        return name
    inside = [n for n in names if n.endswith("/" + name) and n.count("/") == 1]
    if len(inside) != 1:
        raise KeyError(f"{name} not in {z.filename}")
    return inside[0]


def _read(z: zipfile.ZipFile, name: str) -> list[dict]:
    with z.open(_member(z, name)) as fh:
        return list(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8-sig")))


# The fields a feed's `select` rules may test: the GTFS columns of those names,
# `agency` (the route's agency_name), and `stop_id`, the trip's first call --
# the only place SNCF's export says which train it is ("StopPoint:OCETGV
# INOUI-87686006").
SELECT_FIELDS = ("agency", "route_type", "route_short_name", "route_long_name",
                 "route_desc", "trip_short_name", "stop_id")


def tier_of(feed: dict | None, fields: dict) -> str | None:
    """The tier a trip is timed under, or None when the feed does not take it.

    A feed without `select` takes every train at its own `tier`. With one, the
    first rule (field, regex, tier) whose regex `re.search`es the field
    decides, a rule whose tier is None refuses the trip, and a trip no rule
    matches is not taken: a feed that carries every regional and suburban
    train in its country contributes only the services it was chosen for.
    """
    if feed is None or not feed.get("select"):
        return (feed or {}).get("tier", "long_distance")
    for field, pattern, tier in feed["select"]:
        if re.search(pattern, str(fields.get(field) or "")):
            return tier
    return None


def _needs_stop(feed: dict | None) -> bool:
    return any(f == "stop_id" for f, _p, _t in (feed or {}).get("select") or ())


def patterns(path: pathlib.Path, feed: dict | None = None) -> list[dict]:
    """The feed's stop patterns: `stops` [(station id, name, lat, lon)],
    `minutes` {(i, j): fastest scheduled departure(i) -> arrival(j)},
    `route_name`, `operator`, `tier`, and how many trips run the pattern.

    stop_times.txt is streamed and only the calls of trips the feed takes are
    kept: Switzerland's is 3.7 GB, most of it buses, trams and S-Bahn."""
    by_stop = _needs_stop(feed)
    with zipfile.ZipFile(path) as z:
        stops = {s["stop_id"]: s for s in _read(z, "stops.txt")}
        routes = {r["route_id"]: r for r in _read(z, "routes.txt")}
        agency = {a.get("agency_id", ""): a["agency_name"] for a in _read(z, "agency.txt")}
        if len(agency) == 1:
            agency[""] = next(iter(agency.values()))   # agency_id is optional then
        taken: dict[str, tuple[dict, dict, str | None]] = {}
        for t in _read(z, "trips.txt"):
            route = routes.get(t["route_id"])
            if route is None or int(route.get("route_type") or -1) not in RAIL_ROUTE_TYPES:
                continue
            fields = {**route, **t, "agency": agency.get(route.get("agency_id", ""), "")}
            # Decided here unless a rule reads the first call, which comes below.
            tier = None if by_stop else tier_of(feed, fields)
            if tier is not None or by_stop:
                taken[t["trip_id"]] = (route, fields, tier)
        calls: dict[str, list[tuple]] = {}
        with z.open(_member(z, "stop_times.txt")) as fh:
            rd = csv.reader(io.TextIOWrapper(fh, encoding="utf-8-sig"))
            col = {c: i for i, c in enumerate(next(rd))}
            ti, si, qi = col["trip_id"], col["stop_id"], col["stop_sequence"]
            ai, di = col["arrival_time"], col["departure_time"]
            for r in rd:
                if r[ti] in taken:
                    calls.setdefault(r[ti], []).append((int(r[qi]), r[si], r[ai], r[di]))

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
        route, fields, tier = taken[trip_id]
        rows.sort()
        if tier is None:
            tier = tier_of(feed, {**fields, "stop_id": rows[0][1]})
            if tier is None:
                continue
        seq, arr, dep = [], [], []
        for _q, stop_id, a_t, d_t in rows:
            if stop_id not in stops or not (a_t or d_t):
                # A call at a stop stops.txt lacks (Amtrak's "OSM"), or one
                # with no time at all (VIA's request stops, which GTFS leaves
                # to be interpolated): neither is a timed call.
                continue
            st = station(stop_id)
            a = _minutes(a_t or d_t)
            d = _minutes(d_t or a_t)
            if seq and seq[-1][0] == st[0]:
                dep[-1] = d               # two platforms of one station: one call
                continue
            seq.append(st)
            arr.append(a)
            dep.append(d)
        if len(seq) < 2 or any(arr[k + 1] < dep[k] for k in range(len(seq) - 1)):
            continue                      # too short, or a malformed trip
        key = (tier, *(s[0] for s in seq))
        legs = {(i, j): arr[j] - dep[i] for i in range(len(seq)) for j in range(i + 1, len(seq))}
        p = out.get(key)
        if p is None:
            name = " ".join(x for x in (route.get("route_short_name") or "",
                                        fields.get("trip_short_name") or "") if x).strip()
            out[key] = {"stops": seq, "minutes": legs,
                        "route_name": name or route.get("route_long_name") or "",
                        "operator": fields["agency"], "tier": tier, "trips": 1}
        else:
            p["minutes"] = {k: min(v, legs[k]) for k, v in p["minutes"].items()}
            p["trips"] += 1
    return list(out.values())


def _cache_path(fingerprints) -> pathlib.Path:
    return config.CACHE / ("gtfs_rail-" + _params_hash(
        [fp.sha256 for fp in fingerprints], [f["name"] for f in FEEDS],
        [f["tier"] for f in FEEDS], [list(f.get("select") or ()) for f in FEEDS],
        sorted(RAIL_ROUTE_TYPES), GTFS_PARSER_VERSION)
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
        t0 = time.monotonic()
        pats = patterns(fp.path, feed)
        for pat in pats:
            base = "|".join((feed["name"], pat["tier"], *(s[0] for s in pat["stops"])))
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
                                 "lat": lat, "lon": lon, "name": name, "tier": pat["tier"],
                                 "route_name": pat["route_name"], "operator": pat["operator"],
                                 "ref": "", "stops_listed": 2,
                                 "timetabled_min": minutes if seq == 0 else None,
                                 "alight_only": seq == 1,
                                 "feed": feed["name"]})
        logger.info("gtfs %s: %d patterns, %d trips, %.0f s", feed["name"], len(pats),
                    sum(p["trips"] for p in pats), time.monotonic() - t0)
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
    # The trains no open feed carries, from their operators' published pages
    # (sources/rail_published), are timed the same way.
    from . import rail_published

    timed = pl.concat([timetable_rows(), rail_published.rows()])
    tt = snap(timed.drop("feed"), kept)
    return pl.concat([kept, tt], how="diagonal_relaxed")
