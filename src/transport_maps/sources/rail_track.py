"""What the track says that the route relations do not.

`sources/osm.py` builds rail from `type=route, route=train` relations: an
ordered stop list per service. Two things that list cannot carry, measured on
the rebuild-29 extracts (2026-10-14):

1. HOW FAST THE LINE IS. The relation's `service` tag picks a speed tier, and
   26.7% of relations carry none. Every one of the twenty Shinkansen relations
   in the Asia extract is untagged and was priced at the `default` tier's
   81.8 km/h. The ways the relation runs over say otherwise: 110,000 of Asia's
   987,000 `railway=rail` ways carry `highspeed=yes`, and 296,000 a
   `maxspeed`. `relation_profile` reads a relation's member ways for the share
   of its length that is high-speed track and the harmonic mean of the line
   speed over it.

2. THAT THE LINE IS THERE AT ALL. Mainland China's 40,000 km of high-speed
   railway is almost absent as relations -- about 470 train relations in the
   whole country, 21 of them G or D trains -- while its track is mapped
   end to end. `network` builds rail from the high-speed track itself:
   stations along it, the track distance between neighbouring stations, and
   the time at line speed.

What the track network does NOT know, and must not be read as knowing: which
trains stop where. It is an express network -- a ride between any two of its
stations pays one boarding and running time, no intermediate stops -- because
the long-distance service on a high-speed line is an express (a Nozomi calls
at four of the Tokaido line's sixteen stations, a G train at a handful of
twenty-odd). It is therefore optimistic by the dwell of the stops a real train
makes on the way, a few minutes each; `[rail] track_speed_factor` is fitted on
timetabled services that did stop, which absorbs part of that.

Charging a share of those stops was tried and is worse (rebuild 33). The 29
high-speed relations with a `duration` that re-ride whole over a network built
from ALL high-speed track (16 services, Asia and Europe) call at 0.39 of the
stations they pass, and across 1,847 called pairs of 413 relations the share
runs from 0.13 (ДОСС) and 0.23 (DB) to 0.64 (THSR) and 0.78 (JR West). Each
link charged a fitted share p of the high_speed tier's per-stop cost, run at
its line factor: out of fold (five folds by service) median |log p/o| 0.164,
log-sd 0.270, p 0.22-0.44 by fold -- against 0.070 and 0.293 for this express
pricing. A single share prices every service as the average train, so a
Nozomi and a Madrid-Barcelona nonstop run slow and a Kodama still runs fast;
what would separate them is which trains run, which OSM does not say here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

# A line is high-speed track at 200 km/h and above: the UIC's own threshold for
# an upgraded line (250 for a new one). OSM's `highspeed=yes` is honoured
# whatever the `maxspeed`, as `osm.service_tier` honours it on a relation.
HS_MIN_KMH = 200.0
# Track that belongs to a high-speed line: the running lines and the loops and
# crossovers in its stations. Yards, spurs and depots do not carry passengers.
HS_SERVICES = ("", "siding", "crossover")
EXCLUDED_USAGE = ("industrial", "military", "tourism", "test")
# Running speed where a way carries no `maxspeed`. Published-figure defaults,
# not fitted. 250 km/h is the UIC minimum for a NEW high-speed line, which is
# what an untagged `highspeed=yes` way most often is; 80 km/h is the speed of
# the turnouts and platform roads of a station throat (60-80 km/h is the
# common figure for the switches that lead into one).
HS_DEFAULT_KMH = 250.0
STATION_TRACK_KMH = 80.0
# Gaps in the mapped track. OSM splits a line into thousands of ways, and two
# that should share a node sometimes end metres apart (the Tokaido Shinkansen
# breaks four times between Tokyo and Shin-Osaka); and a line's own station
# roads are often untagged. A dead end within 50 m of another piece is joined;
# two pieces are bridged through at most 3 km of other main or station track.
GAP_SNAP_KM = 0.05
BRIDGE_KM = 3.0
CONNECTOR_MAX_WAY_KM = 5.0
# A station belongs to the line when it lies within 0.8 km of its running track
# and within 1.0 km of a switch on it: a station has turnouts, a viaduct
# passing over one does not. A big Chinese terminal puts its station node at
# the building, up to 0.7 km from the tracks; tighter radii lost 杭州东, 成都东
# and 重庆西 outright.
STATION_TRACK_KM = 0.8
STATION_SWITCH_KM = 1.0
# A relation is high-speed when at least half its member track is.
PROMOTE_SHARE = 0.5
# Placing a stop on its relation's track (`leg_profiles`): a platform node
# beside the line is placed at the nearest track node within this distance,
# and a leg whose track runs more than LEG_MAX_DETOUR times its chord is a
# misplaced stop or a broken chain, not a route (rail track rarely exceeds
# 1.5x; the worst real mountain lines approach 2.5x).
STOP_TRACK_KM = 0.5
LEG_MAX_DETOUR = 3.0
_EARTH_KM = 6371.0088
_MAXSPEED = re.compile(r"^(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?$")
_NOT_MAINLINE_STATION = ("subway", "light_rail", "monorail", "funicular", "miniature", "tram")
# Bumped when what this module derives changes without a constant changing.
# 2: promotion only of untagged relations whose line speed is high-speed.
# 3: track a high-speed relation runs over is left out of the network.
# 4: ... and track any train relation runs over.
# 5: each relation leg's own track profile (`leg_profiles`).
# 6: directional and tilting maxspeed (`way_speeds`).
# 7: the fast conventional network (`Track.fast`).
TRACK_VERSION = 7
# The lowest line speed of the fast conventional network: the commonest
# upgraded main-line speed (160 km/h -- China's K/T/Z lines, Russia's
# Moscow-Nizhny Novgorod, Germany's Ausbaustrecken) and the floor of the
# UIC's "upgraded line" band. A modelling threshold, not fitted.
FAST_MIN_KMH = 160.0


def params() -> tuple:
    """Everything here that governs the rail parquet's content, for its key."""
    return (HS_MIN_KMH, HS_SERVICES, EXCLUDED_USAGE, HS_DEFAULT_KMH, STATION_TRACK_KMH,
            GAP_SNAP_KM, BRIDGE_KM, CONNECTOR_MAX_WAY_KM, STATION_TRACK_KM,
            STATION_SWITCH_KM, PROMOTE_SHARE, _NOT_MAINLINE_STATION, _MAXSPEED.pattern,
            STOP_TRACK_KM, LEG_MAX_DETOUR, FAST_MIN_KMH, TRACK_VERSION)


def parse_maxspeed(raw: str | None) -> float | None:
    """A `maxspeed` value in km/h, or None. `125 mph` is the UK's one form;
    `signals`, `none` and anything conditional say nothing usable."""
    if not raw:
        return None
    m = _MAXSPEED.match(raw.strip().lower())
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2) == "mph":
        v *= 1.609344
    return v if 5.0 <= v <= 600.0 else None


def way_speeds(tags) -> tuple[float | None, float | None]:
    """(line speed, line speed for a tilting train) of a track way, km/h.

    `maxspeed`, else the faster of `maxspeed:forward` and `:backward` -- about
    14,000 European ways carry only the directional pair and read as unmapped
    before rebuild 33. The tilting speed is `maxspeed:tilting` where it is
    higher (16,150 European ways: the West Coast Main Line is 110 mph and 125
    for a Pendolino), else the line speed. Which tiers run at it is fitted
    (`[rail.tiers]` `line_speed_tilting`).
    """
    v = parse_maxspeed(tags.get("maxspeed"))
    if v is None:
        d = [x for x in (parse_maxspeed(tags.get("maxspeed:forward")),
                         parse_maxspeed(tags.get("maxspeed:backward"))) if x is not None]
        v = max(d) if d else None
    tilt = parse_maxspeed(tags.get("maxspeed:tilting"))
    return v, (max(tilt, v) if (tilt is not None and v is not None) else v)


def is_high_speed(tags_highspeed: str | None, vmax: float | None) -> bool:
    return tags_highspeed == "yes" or (vmax is not None and vmax >= HS_MIN_KMH)


def _hav(la1, lo1, la2, lo2):
    r1, r2 = np.radians(la1), np.radians(la2)
    a = (np.sin((r2 - r1) / 2) ** 2
         + np.cos(r1) * np.cos(r2) * np.sin(np.radians(lo2 - lo1) / 2) ** 2)
    return _EARTH_KM * 2 * np.arcsin(np.sqrt(a))


def _xyz(lat, lon):
    la, lo = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)],
                    axis=-1).reshape(-1, 3) * _EARTH_KM


@dataclass
class Track:
    """One extract's track, as `scan` reads it."""

    # way id -> (length km, maxspeed km/h or None, high-speed?) for every
    # `railway=rail` way: what relation_profile reads.
    ways: dict[int, tuple[float, float | None, bool]] = field(default_factory=dict)
    # High-speed running, siding and crossover ways, with their geometry.
    hs: dict[int, tuple] = field(default_factory=dict)
    # Fast conventional running track, FAST_MIN_KMH up to high-speed, with its
    # geometry: the second track network (`network(..., pool=track.fast)`).
    fast: dict[int, tuple] = field(default_factory=dict)
    # Short other main and station track, for bridging gaps and finding switches.
    conn: dict[int, tuple] = field(default_factory=dict)
    # railway=station|halt nodes that a main-line train can call at.
    stations: list[tuple] = field(default_factory=list)
    # Coordinates and names of the relation stop nodes asked for.
    nodes: dict[int, tuple] = field(default_factory=dict)
    # way id -> (node ids, lats, lons, maxspeed or None) for every way a train
    # relation lists: the track `leg_profiles` walks between two stops.
    member: dict[int, tuple] = field(default_factory=dict)


def scan(path, wanted_nodes: set[int], member_ways: frozenset | set = frozenset()) -> Track:
    """One pass over an extract's nodes and ways, with locations. The
    geometry of `member_ways` -- the ways the train relations list -- is kept
    for `leg_profiles`."""
    import osmium

    out = Track()
    fp = osmium.FileProcessor(str(path), osmium.osm.NODE | osmium.osm.WAY).with_locations()
    for o in fp:
        t = o.tags
        if o.is_node():
            if o.id in wanted_nodes:
                out.nodes[o.id] = (o.location.lat, o.location.lon, t.get("name") or "")
            if (t.get("railway") in ("station", "halt") and t.get("train") != "no"
                    and t.get("station") not in _NOT_MAINLINE_STATION):
                out.stations.append((o.location.lat, o.location.lon,
                                     t.get("name") or t.get("name:en") or "",
                                     t.get("railway"), t.get("operator") or ""))
            continue
        if t.get("railway") != "rail":
            continue
        try:
            lat = np.fromiter((n.lat for n in o.nodes), float)
            lon = np.fromiter((n.lon for n in o.nodes), float)
        except osmium.InvalidLocationError:
            continue
        if len(lat) < 2:
            continue
        km = float(_hav(lat[:-1], lon[:-1], lat[1:], lon[1:]).sum())
        vmax, vtilt = way_speeds(t)
        hs = is_high_speed(t.get("highspeed"), vmax)
        svc = t.get("service") or ""
        out.ways[o.id] = (km, vmax, hs)
        ids = np.fromiter((n.ref for n in o.nodes), np.int64)
        if o.id in member_ways:
            out.member[o.id] = (ids, lat, lon, (vmax, vtilt))
        if svc not in HS_SERVICES:
            continue
        if hs and t.get("usage") not in EXCLUDED_USAGE:
            out.hs[o.id] = (ids, lat, lon, vmax, svc, t.get("name") or "",
                            t.get("operator") or "")
            continue
        if (not svc and vmax is not None and vmax >= FAST_MIN_KMH
                and t.get("usage") not in EXCLUDED_USAGE):
            out.fast[o.id] = (ids, lat, lon, vmax, svc, t.get("name") or "",
                              t.get("operator") or "")
        if km <= CONNECTOR_MAX_WAY_KM:
            out.conn[o.id] = (ids, lat, lon, svc)
    return out


def promotes(hs_share: float, vmax: float | None) -> bool:
    """Whether an UNTAGGED relation is a high-speed service by its track: most
    of its length high-speed, and the line speed over it -- where mapped -- a
    high-speed line's. A stopping train on a 200 km/h upgraded line has the
    first and not, on average over its route, the second."""
    return hs_share >= PROMOTE_SHARE and (vmax is None or vmax >= HS_MIN_KMH)


def relation_profile(member_ways, ways) -> tuple[float, float, float | None, float]:
    """(member km, high-speed share, harmonic-mean maxspeed, maxspeed cover).

    Over the relation's member ways the extract holds. The mean is
    length-weighted and HARMONIC -- time is length over speed, so a 50 km
    section at 100 km/h costs what 150 km at 300 does, and an arithmetic mean
    would hide it. None where no member way carries a `maxspeed`.
    """
    total = hs_km = cov_km = inv = 0.0
    for w in member_ways:
        rec = ways.get(w)
        if rec is None:
            continue
        km, vmax, hs = rec
        total += km
        if hs:
            hs_km += km
        if vmax:
            cov_km += km
            inv += km / vmax
    if total <= 0:
        return 0.0, 0.0, None, 0.0
    return total, hs_km / total, (cov_km / inv if inv > 0 else None), cov_km / total


def _chain(member_ways, member):
    """A relation's member track as one ordered polyline: node ids, lats,
    lons, and from its start to each node the km, the hours at mapped line
    speed and the km with no `maxspeed`. Each way is turned to start where the
    previous one ended; a way that does not touch it (OSM relations do skip
    pieces) is joined by a straight hop counted as km with no line speed.
    None when the relation lists no way the extract holds."""
    ws = [member[w] for w in member_ways if w in member]
    if not ws:
        return None
    if len(ws) > 1:
        (i0, a0, o0, v0), nxt = ws[0], ws[1][0]
        if i0[-1] not in (nxt[0], nxt[-1]) and i0[0] in (nxt[0], nxt[-1]):
            ws[0] = (i0[::-1], a0[::-1], o0[::-1], v0)

    def speeds(v, n):
        """(n, 2): the way's line speed and tilting speed on n segments."""
        return np.tile([np.nan if x is None else x for x in v], (n, 1)).astype(float)

    i0, a0, o0, v0 = ws[0]
    ids, las, los = [i0], [a0], [o0]
    segv = [speeds(v0, len(i0) - 1)]
    for wi, wla, wlo, v in ws[1:]:
        end, ela, elo = ids[-1][-1], las[-1][-1], los[-1][-1]
        if wi[0] != end and (wi[-1] == end
                             or float(_hav(ela, elo, wla[-1], wlo[-1]))
                             < float(_hav(ela, elo, wla[0], wlo[0]))):
            wi, wla, wlo = wi[::-1], wla[::-1], wlo[::-1]
        if wi[0] == end:
            ids.append(wi[1:]); las.append(wla[1:]); los.append(wlo[1:])
            segv.append(speeds(v, len(wi) - 1))
        else:
            ids.append(wi); las.append(wla); los.append(wlo)
            segv.append(np.r_[np.full((1, 2), np.nan), speeds(v, len(wi) - 1)])
    nid, la, lo = np.concatenate(ids), np.concatenate(las), np.concatenate(los)
    seg = _hav(la[:-1], lo[:-1], la[1:], lo[1:])[:, None]
    v = np.concatenate(segv)
    known = np.isfinite(v)
    km = np.r_[0.0, np.cumsum(seg[:, 0])]
    # (n, 2) each: column 0 at the line speed, column 1 at the tilting speed.
    h = np.r_[[[0.0, 0.0]], np.cumsum(np.where(known, seg / np.where(known, v, 1.0), 0.0), axis=0)]
    unk = np.r_[[[0.0, 0.0]], np.cumsum(np.where(known, 0.0, seg), axis=0)]
    return nid, la, lo, km, h, unk


def leg_profiles(stops, stop_coords, member_ways, member) -> list[tuple | None] | None:
    """For each pair of consecutive stops, (track km, hours at mapped line
    speed, km with no maxspeed, the same two at the tilting speed) along the
    relation's own track, or None where the stops cannot be placed on it.

    A relation is priced from these rather than from one speed over its
    whole length because a line is not one speed: the KTX that runs via
    Suwon takes the 150 km/h conventional line between Suwon and Daejeon and
    the 300 km/h one beyond, and a Komachi's nonstop Omiya-Sendai leg is all
    320 km/h track while its Akita end is a 130 km/h mini-shinkansen. Priced
    at the relation's average, the first leg was 41 min for an hour's ride.

    A stop is placed at its own node where the track passes through it (a
    stop position), else at the nearest track node within STOP_TRACK_KM (a
    platform beside the line), and always after the previous stop. A leg
    whose track is shorter than its chord, or more than LEG_MAX_DETOUR times
    it, is a misplaced stop or a broken chain and gets None.
    """
    ch = _chain(member_ways, member)
    if ch is None:
        return None
    nid, la, lo, km, h, unk = ch
    where: dict[int, list[int]] = {}
    for i, x in enumerate(nid.tolist()):
        where.setdefault(x, []).append(i)
    xyz = _xyz(la, lo)

    def place(sid, lat, lon, after):
        for i in where.get(sid, ()):
            if i >= after:
                return i
        d = np.linalg.norm(xyz[after:] - _xyz([lat], [lon])[0], axis=1) if after < len(nid) else []
        if len(d) and d.min() <= STOP_TRACK_KM:
            return after + int(d.argmin())
        return None

    def run(order):
        pos, after = [], 0
        for sid, (lat, lon) in order:
            i = place(sid, lat, lon, after)
            pos.append(i)
            if i is not None:
                after = i
        return pos

    seq = [(sid, stop_coords[sid]) for sid in stops]
    pos = run(seq)
    if sum(p is None for p in pos) > len(pos) // 2:
        # The track listed the other way round from the stops.
        nid, la, lo = nid[::-1], la[::-1], lo[::-1]
        km, h, unk = km[-1] - km[::-1], h[-1] - h[::-1], unk[-1] - unk[::-1]
        where = {}
        for i, x in enumerate(nid.tolist()):
            where.setdefault(x, []).append(i)
        xyz = _xyz(la, lo)
        pos = run(seq)
    out = []
    for (a, (sa, ca)), (b, (sb, cb)) in zip(zip(pos, seq), zip(pos[1:], seq[1:])):
        if a is None or b is None or b <= a:
            out.append(None)
            continue
        tk = float(km[b] - km[a])
        chord = float(_hav(ca[0], ca[1], cb[0], cb[1]))
        if tk < 0.9 * chord or (chord > 1.0 and tk > LEG_MAX_DETOUR * chord):
            out.append(None)
            continue
        dh, du = h[b] - h[a], unk[b] - unk[a]
        out.append((tk, float(dh[0]), float(du[0]), float(dh[1]), float(du[1])))
    return out


@dataclass(frozen=True)
class Link:
    """Two neighbouring stations on high-speed track."""

    a: tuple[float, float, str]
    b: tuple[float, float, str]
    track_km: float
    line_h: float          # hours at line speed, sum of length / maxspeed
    name: str
    operator: str


def network(track: Track, covered_ways: set[int], pool: dict | None = None) -> list[Link]:
    """The high-speed track no train relation runs over, as station-to-station
    links.

    `covered_ways` are the ways the extract's train relations run over, and
    they are left out: where OSM says which trains call where, the relations
    price it, and an express link laid over the same track counts the line
    twice -- a UK 125 mph main line is high-speed track by `maxspeed` and was
    given 592 km of links over the track its `long_distance` relations already
    run. A station is a mainline
    station within STATION_TRACK_KM of the running track and STATION_SWITCH_KM
    of a switch on it, the switch's own nearest one -- preferring a station of
    the track's operator, then a station over a halt.

    `pool` is the track to build from: the high-speed track by default, or
    `track.fast` for the fast conventional lines (since rebuild 33) -- China's
    21,700 km and Russia's 6,500 km of 160-200 km/h main line that no train
    relation runs over, which carried no train at all before.
    """
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components, dijkstra
    from scipy.spatial import cKDTree

    pool = track.hs if pool is None else pool
    if not pool:
        return []
    node_of: dict[int, int] = {}
    lats: list[float] = []
    lons: list[float] = []

    def index(ids, lat, lon):
        out = np.empty(len(ids), np.int64)
        for k, nd in enumerate(ids.tolist()):
            i = node_of.get(nd)
            if i is None:
                i = node_of[nd] = len(lats)
                lats.append(lat[k]); lons.append(lon[k])
            out[k] = i
        return out

    ea, eb, ek, eh, kind = [], [], [], [], []
    node_op: dict[int, str] = {}
    node_name: dict[int, str] = {}
    for wid, (ids, lat, lon, vmax, svc, name, op) in pool.items():
        if wid in covered_ways:
            continue
        ix = index(ids, lat, lon)
        km = _hav(lat[:-1], lon[:-1], lat[1:], lon[1:])
        v = vmax or (HS_DEFAULT_KMH if not svc else STATION_TRACK_KMH)
        ea.append(ix[:-1]); eb.append(ix[1:]); ek.append(km); eh.append(km / v)
        kind.append(np.full(len(km), {"": 0, "siding": 1, "crossover": 2}[svc], np.int8))
        for i in ix.tolist():
            if op:
                node_op.setdefault(i, op)
            if name and not svc:
                node_name.setdefault(i, name)
    n_hs = len(lats)
    if not n_hs:
        return []
    ca, cb, ck, cx = [], [], [], []
    for _, (ids, lat, lon, svc) in track.conn.items():
        ix = index(ids, lat, lon)
        ca.append(ix[:-1]); cb.append(ix[1:])
        ck.append(_hav(lat[:-1], lon[:-1], lat[1:], lon[1:]))
        cx.append(np.full(len(ix) - 1, svc == "crossover"))
    LAT, LON = np.asarray(lats), np.asarray(lons)
    n = len(LAT)
    a, b = np.concatenate(ea), np.concatenate(eb)
    km, h, kind = np.concatenate(ek), np.concatenate(eh), np.concatenate(kind)

    def labels(a, b):
        G = sp.coo_matrix((np.ones(2 * len(a)), (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
        return G, connected_components(G, directed=False)[1]

    # 1. topology gaps: a dead end within GAP_SNAP_KM of another piece's node
    G, lab = labels(a, b)
    dead = np.flatnonzero(np.diff(G.indptr)[:n_hs] == 1)
    if len(dead):
        tree = cKDTree(_xyz(LAT[:n_hs], LON[:n_hs]))
        gx, gy, gk = [], [], []
        for u, cands in zip(dead, tree.query_ball_point(_xyz(LAT[dead], LON[dead]), r=GAP_SNAP_KM)):
            best = min(((float(_hav(LAT[u], LON[u], LAT[v], LON[v])), v)
                        for v in cands if lab[v] != lab[u]), default=None)
            if best:
                gx.append(u); gy.append(best[1]); gk.append(best[0])
        if gx:
            gk = np.asarray(gk)
            a, b = np.r_[a, gx], np.r_[b, gy]
            km, h = np.r_[km, gk], np.r_[h, gk / STATION_TRACK_KMH]
            kind = np.r_[kind, np.full(len(gk), 3, np.int8)]
    # 2. bridges through short other track between different pieces
    if ca:
        ca, cb, ck, cx = (np.concatenate(ca), np.concatenate(cb), np.concatenate(ck),
                          np.concatenate(cx))
        G, lab = labels(a, b)
        C = sp.coo_matrix((np.r_[ck, ck], (np.r_[ca, cb], np.r_[cb, ca])), shape=(n, n)).tocsr()
        touch = np.unique(np.r_[ca, cb])
        touch = touch[touch < n_hs]
        if len(touch):
            Dc, _, Sc = dijkstra(C, directed=False, indices=touch, min_only=True,
                                 return_predecessors=True, limit=BRIDGE_KM)
            sx, sy = Sc[ca], Sc[cb]
            tot = Dc[ca] + ck + Dc[cb]
            ok = (sx >= 0) & (sy >= 0) & (tot <= BRIDGE_KM)
            ok &= lab[np.maximum(sx, 0)] != lab[np.maximum(sy, 0)]
            br: dict[tuple[int, int], float] = {}
            for x, y, t in zip(sx[ok].tolist(), sy[ok].tolist(), tot[ok].tolist()):
                k = (min(x, y), max(x, y))
                br[k] = min(t, br.get(k, np.inf))
            if br:
                bk = np.fromiter(br.values(), float)
                a = np.r_[a, [k[0] for k in br]]
                b = np.r_[b, [k[1] for k in br]]
                km, h = np.r_[km, bk], np.r_[h, bk / STATION_TRACK_KMH]
                kind = np.r_[kind, np.full(len(bk), 3, np.int8)]
    else:
        ca = cb = np.zeros(0, np.int64)
        cx = np.zeros(0, bool)

    # 3. stations
    main = np.unique(np.r_[a[kind == 0], b[kind == 0]])
    if not len(main):
        return []
    main_tree = cKDTree(_xyz(LAT[main], LON[main]))
    chosen: dict[int, tuple[float, float, str]] = {}
    nc = kind != 2
    ee = np.r_[np.stack([a[nc], b[nc]], 1), np.stack([ca[~cx], cb[~cx]], 1)]
    ee = np.unique(np.sort(ee, axis=1), axis=0)
    deg = np.bincount(ee.ravel(), minlength=n)
    sw = np.flatnonzero(deg[:n_hs] >= 3)
    if len(sw) and track.stations:
        st = track.stations
        S = _xyz([s[0] for s in st], [s[1] for s in st])
        tdist, tnear = main_tree.query(S, distance_upper_bound=STATION_TRACK_KM)
        stree = cKDTree(S)
        SW = _xyz(LAT[sw], LON[sw])
        for s_i, p, cands in zip(sw.tolist(), SW, stree.query_ball_point(SW, r=STATION_SWITCH_KM)):
            op = node_op.get(s_i, "")
            best = None
            for i in cands:
                if not np.isfinite(tdist[i]):
                    continue
                sop = st[i][4]
                match = 1 if not (op and sop) else (0 if (op in sop or sop in op) else 2)
                rank = (match, 0 if st[i][3] == "station" else 1, float(np.linalg.norm(S[i] - p)))
                if best is None or rank < best[0]:
                    best = (rank, i)
            if best:
                i = best[1]
                chosen.setdefault(int(main[tnear[i]]), (st[i][0], st[i][1], st[i][2]))
    if len(chosen) < 2:
        return []

    # 4. neighbouring stations by time along the track, with its length
    src = np.asarray(sorted(chosen), np.int64)
    Gh = sp.coo_matrix((np.r_[h, h], (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
    Gh.sum_duplicates()
    D, P, SRC = dijkstra(Gh, directed=False, indices=src, min_only=True, return_predecessors=True)
    # km along each node's time-shortest path from its station
    edge_km: dict[tuple[int, int], float] = {}
    for x, y, k in zip(a.tolist(), b.tolist(), km.tolist()):
        key = (x, y) if x < y else (y, x)
        edge_km[key] = min(k, edge_km.get(key, np.inf))
    DK = np.zeros(n)
    for v in np.argsort(D, kind="stable").tolist():
        p = P[v]
        if p >= 0 and np.isfinite(D[v]):
            DK[v] = DK[p] + edge_km[(p, v) if p < v else (v, p)]
    sa, sb = SRC[a], SRC[b]
    cross = (sa >= 0) & (sb >= 0) & (sa != sb)
    best: dict[tuple[int, int], tuple[float, float, int]] = {}
    for x, y, hh, kk, u, v in zip(sa[cross].tolist(), sb[cross].tolist(), h[cross].tolist(),
                                  km[cross].tolist(), a[cross].tolist(), b[cross].tolist()):
        key = (x, y) if x < y else (y, x)
        t = D[u] + hh + D[v]
        if t < best.get(key, (np.inf,))[0]:
            best[key] = (t, DK[u] + kk + DK[v], u)
    links = []
    for (x, y), (t, kk, u) in sorted(best.items()):
        name = node_name.get(u) or node_name.get(x) or node_name.get(y) or ""
        op = node_op.get(u) or node_op.get(x) or node_op.get(y) or ""
        links.append(Link(chosen[x], chosen[y], float(kk), float(t), name, op))
    return links
