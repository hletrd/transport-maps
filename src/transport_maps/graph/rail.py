"""Rail edges from OSM route relations.

Stations are nodes of their own rather than being folded into their H3 cell,
so that boarding cost is charged once per journey. Cell-to-cell rail edges
would charge it on every hop, making a twenty-stop local ride absurd; and
riding through a station you do not alight at must cost only the running time.

Platforms are merged into one station: OSM models a large interchange as many
`stop_position` nodes metres apart, and treating each as its own station would
invent free transfers between them while inflating the node count.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass

import h3
import numpy as np
import polars as pl

from .. import config
from ..sources import osm

# ~200 m edge (0.35 km across): comfortably merges the platforms of one station while
# keeping genuinely separate city stations apart.
STATION_RES = 9


@dataclass(frozen=True)
class RailTier:
    """One speed tier: a running speed and the cost of making one stop.

    The overhead is charged PER LEG, which is per intermediate call, and it is
    not a decoration. Fitted without it, implied speed inside a single tier
    drifts by a factor of two with route length -- `regional` runs 39 km/h over
    0-20 km and 70 km/h over 150-400 km -- because a fixed per-call cost
    (decelerate, dwell, accelerate) is being spread over the distance. It is
    the same structure `[ferry]` found and named `berth_min`.
    """

    speed_kmh: float
    stop_overhead_min: float
    # Where the relation's own line speed is mapped: running speed as a share
    # of it, and the per-stop overhead fitted with that. None for a tier where
    # the tier speed fits better (`high_speed`) or n is too small (`tourism`).
    line_speed_factor: float | None = None
    line_overhead_min: float | None = None
    # Since rebuild 33, the line-speed price of a leg whose line speed is v:
    #   line_overhead_min + line_stop_loss_min * v/100
    #     + 60 km / (line_speed_factor * v + line_speed_floor_kmh)
    # The stop costs more the faster the line (braking from it and climbing
    # back to it), and a slow line is run nearer its limit than a fast one.
    # Without these the error ran with line speed: slope -0.27 (commuter) to
    # -0.31 (regional) in log(predicted/observed) per log line speed, lines
    # under 80 km/h 10-22% too slow. Zero leaves the old form; which tier
    # uses which term was chosen out of fold (calibration.toml [rail.tiers]).
    line_stop_loss_min: float = 0.0
    line_speed_floor_kmh: float = 0.0
    # Whether the tier's trains run at `maxspeed:tilting` where the track
    # carries one (`rail_track.way_speeds`). Chosen out of fold.
    line_speed_tilting: bool = False


@dataclass(frozen=True)
class RailCalibration:
    detour_factor: float
    boarding_min: float
    alighting_min: float
    tiers: dict[str, RailTier]
    # Running speed on the track network's links (`sources/rail_track`) as a
    # share of the line speed the track's `maxspeed` sets. Fitted; see
    # `[rail] track_speed_factor`.
    track_speed_factor: float = 1.0
    # Share of a relation's member track that must carry `maxspeed` before its
    # line speed is used over its tier's (`[rail] line_speed_min_cover`).
    line_speed_min_cover: float = 0.5


def load_rail_calibration(path=None) -> RailCalibration:
    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = dict(tomllib.load(fh)["rail"])
    tiers = {name: RailTier(**vals) for name, vals in raw.pop("tiers").items()}
    # A tier the parser can emit but the calibration does not price would
    # otherwise surface as a KeyError deep inside a forked worker, hours into a
    # build. Say it here, naming the tier.
    missing = [t for t in osm.RAIL_TIERS if t not in tiers]
    if missing:
        raise ValueError(
            f"calibration.toml [rail.tiers] is missing {', '.join(missing)}; "
            f"sources/osm.RAIL_TIERS names {len(osm.RAIL_TIERS)} tiers")
    return RailCalibration(tiers=tiers, **raw)


def station_key(lat: float, lon: float) -> str:
    return h3.latlng_to_cell(lat, lon, STATION_RES)


# The key suffix of a station's ALIGHT-ONLY twin: where a timetabled leg
# (sources/gtfs_rail) arrives. The twin has no ride edge out, so a traveller
# who wants another train goes out to the cell and pays alighting and
# boarding again (`[rail]`, 20 min) -- a connection, where the plain station
# lets OSM's through-rides chain for free. Without it every leg was the
# fastest train for its own pair and a journey chained them free of charge:
# Berlin -> Munich in 217 min, which no single train runs and the fastest ICE
# takes 236 for.
ALIGHT_SUFFIX = "~a"


def row_stations(df: pl.DataFrame) -> pl.Series:
    """The station key of each stop row: its res-9 cell, with ALIGHT_SUFFIX
    where the row is the alighting end of a timetabled leg."""
    keys = df.select(pl.struct("lat", "lon").map_elements(
        lambda s: station_key(s["lat"], s["lon"]), return_dtype=pl.Utf8)).to_series()
    if "alight_only" not in df.columns:
        return keys.alias("station")
    alight = df["alight_only"].fill_null(False)
    return (pl.select(pl.when(alight).then(keys + ALIGHT_SUFFIX).otherwise(keys))
              .to_series().alias("station"))


# A second haversine, separate from `ground.haversine_km`, whose signature
# takes four scalar/array arguments rather than two (n,2) pair arrays. Same
# formula, same radius. Collapsing the two touches the rail build path's
# numerics and is deferred (plan DEF8-10); `ground.haversine_km`'s docstring
# claiming "rail and ferry use it" has been corrected in the meantime, because
# this module imports nothing from `ground` at all.
def _haversine_km(lat1, lon1, lat2, lon2):
    r1, r2 = np.radians(lat1), np.radians(lat2)
    dlat, dlon = r2 - r1, np.radians(lon2) - np.radians(lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(r1) * np.cos(r2) * np.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * np.arcsin(np.sqrt(a))


def stations(routes: pl.DataFrame) -> pl.DataFrame:
    """One row per physical station (and per alight-only twin), with the
    cell it sits in."""
    df = routes.with_columns(row_stations(routes))
    return (df.group_by("station")
              .agg(pl.col("lat").mean(), pl.col("lon").mean(),
                   pl.col("name").first())
              .with_columns(
                  pl.struct("lat", "lon").map_elements(
                      lambda s: h3.latlng_to_cell(s["lat"], s["lon"], config.SOLVE_RES),
                      return_dtype=pl.Utf8).alias("cell"))
              .sort("station"))


def _line_price(c: RailTier, km: float, v: float) -> float:
    """A leg of `km` along track at line speed `v`, by the tier's line terms."""
    return (c.line_overhead_min + c.line_stop_loss_min * v / 100.0
            + 60.0 * km / (c.line_speed_factor * v + c.line_speed_floor_kmh))


def leg_minutes(tiers, km, line_h, cal, vmax=None, cover=None, leg_km=None,
                leg_line_h=None, leg_unknown_km=None, leg_line_h_tilt=None,
                leg_unknown_km_tilt=None) -> np.ndarray:
    """Minutes for each leg: the ONE pricing `ride_edges` and the captions in
    `emit/rail_detail` both use, so the service a caption names is the one
    that set the time.

    A relation's leg is its tier's overhead plus the chord at its tier speed
    -- or, where the tier carries line-speed terms and the relation's own
    line speed `vmax` is mapped over `line_speed_min_cover` of its track,
    `line_overhead_min` plus the chord at `line_speed_factor x vmax`.
    A track-network link (`line_h` set: hours at the line speed its track's
    `maxspeed` allows) is that time at `track_speed_factor`, with no stop
    overhead -- the link is part of an express ride, and the stop it would pay
    for is the one at the end, which boarding and alighting already charge.

    Since rebuild 33 a relation leg whose OWN track is known
    (`leg_km`, `leg_line_h`, `leg_unknown_km` from `rail_track.leg_profiles`)
    with `maxspeed` over `line_speed_min_cover` of it is priced from that
    track rather than from the relation's average: `line_overhead_min` plus
    its hours at line speed, its unmapped km at the relation's line speed
    (else the tier's, along track), over `line_speed_factor`. A line is not
    one speed: the KTX via Suwon runs 111 km of 150 km/h conventional line
    between Suwon and Daejeon, which the relation's 196 km/h average priced
    at 41 min against an hour.
    """
    tiers = list(tiers)
    km = np.asarray(km, float)
    n = len(km)

    def column(v):
        return np.full(n, np.nan) if v is None else np.asarray(
            [np.nan if x is None else x for x in v], float)

    line_h, vmax, cover = column(line_h), column(vmax), column(cover)
    lk, lh, lu = column(leg_km), column(leg_line_h), column(leg_unknown_km)
    lht, lut = column(leg_line_h_tilt), column(leg_unknown_km_tilt)
    lht, lut = np.where(np.isnan(lht), lh, lht), np.where(np.isnan(lut), lu, lut)
    profiled = (~np.isnan(lk) & ~np.isnan(lh) & (np.nan_to_num(lk) > 0)
                & (1 - np.nan_to_num(lu) / np.where(np.nan_to_num(lk) > 0, lk, 1.0)
                   >= cal.line_speed_min_cover))
    link = ~np.isnan(line_h)
    # A tier the calibration does not price must be a loud failure NAMING it,
    # not a null that becomes a NaN edge and a silently unreachable station.
    # polars' own `replace_strict` error says only "incomplete mapping", which
    # would send a reader to the wrong file.
    unpriced = sorted({t for t, is_link in zip(tiers, link) if not is_link} - set(cal.tiers))
    if unpriced:
        raise ValueError(
            f"no rail calibration for service tier(s) {', '.join(map(str, unpriced))}; "
            f"calibration.toml [rail.tiers] prices {', '.join(sorted(cal.tiers))}")
    out = np.empty(n)
    for i, (t, is_link) in enumerate(zip(tiers, link)):
        if is_link:
            out[i] = 60.0 * line_h[i] / cal.track_speed_factor
            continue
        c = cal.tiers[t]
        if c.line_speed_factor is not None and profiled[i]:
            # The leg's own track: its length, and its speed as its length
            # over its hours at mapped maxspeed (unmapped km at the relation's
            # line speed, else the tier's along track).
            fill = vmax[i] if vmax[i] > 0 else c.speed_kmh * cal.detour_factor
            h_i, u_i = (lht[i], lut[i]) if c.line_speed_tilting else (lh[i], lu[i])
            hours = h_i + np.nan_to_num(u_i) / fill
            out[i] = _line_price(c, lk[i], lk[i] / hours if hours > 0 else fill)
        elif (c.line_speed_factor is not None and vmax[i] > 0
                and cover[i] >= cal.line_speed_min_cover):
            out[i] = _line_price(c, km[i] * cal.detour_factor, vmax[i])
        else:
            out[i] = c.stop_overhead_min + 60.0 * km[i] * cal.detour_factor / c.speed_kmh
    return out


def priced_legs(routes: pl.DataFrame, cal) -> pl.DataFrame:
    """Every route's legs between consecutive stops and their minutes:
    `route_id`, `from_station`, `to_station`, `minutes`. What `ride_edges`
    resolves to a graph and what `emit/rail_detail` captions -- one pricing.

    Consecutive means consecutive in `seq` WITHIN one route; the shift must be
    partitioned or the last stop of one route joins to the first of the next
    and invents an edge across the country.

    A relation's own `duration` is NOT applied to its legs, though 2,385
    relations carry one: it times one train, and the stop list is often
    another -- a Nozomi relation listing six stops without Nagoya under a
    144 min tag, a Hayabusa listing the 18 stops of every Hayabusa under one
    train's 237. Scaled to those, Tokyo-Shin-Osaka rode in 110 min and
    Tokyo-Sendai in 68 (rebuild 33's trial). The durations are what the tier
    terms are fitted on instead, where such errors average out.
    """
    df = routes.with_columns(row_stations(routes)).sort("route_id", "seq")

    nxt = df.with_columns(
        pl.col("station").shift(-1).over("route_id").alias("to_station"),
        pl.col("lat").shift(-1).over("route_id").alias("to_lat"),
        pl.col("lon").shift(-1).over("route_id").alias("to_lon"),
    ).drop_nulls("to_station").filter(pl.col("station") != pl.col("to_station"))

    km = _haversine_km(nxt["lat"].to_numpy(), nxt["lon"].to_numpy(),
                       nxt["to_lat"].to_numpy(), nxt["to_lon"].to_numpy())

    def col(name):
        return nxt[name].to_list() if name in nxt.columns else None

    minutes = leg_minutes(nxt["tier"].to_list(), km, col("line_h"), cal,
                          vmax=col("vmax_kmh"), cover=col("vmax_cover"),
                          leg_km=col("leg_km"), leg_line_h=col("leg_line_h"),
                          leg_unknown_km=col("leg_unknown_km"),
                          leg_line_h_tilt=col("leg_line_h_tilt"),
                          leg_unknown_km_tilt=col("leg_unknown_km_tilt"))
    # A leg a timetable times (sources/gtfs_rail) is the scheduled minutes,
    # not a price: the observation itself, where a feed has one.
    timed = (nxt["timetabled_min"].to_numpy(allow_copy=True).astype(float)
             if "timetabled_min" in nxt.columns else np.full(len(nxt), np.nan))
    minutes = np.where(np.isnan(timed), minutes, timed)
    return pl.DataFrame({"route_id": nxt["route_id"], "from_station": nxt["station"],
                         "to_station": nxt["to_station"], "minutes": minutes,
                         "timetabled": ~np.isnan(timed)})


def ride_edges(routes: pl.DataFrame, cal) -> pl.DataFrame:
    """Running time between consecutive stops, in minutes: the fastest service
    over each hop of `priced_legs`.

    Each leg is priced by its route's SERVICE TIER. This replaced a two-speed
    model -- 200 km/h if the relation carried `highspeed=yes` or
    `service=high_speed`, else 75 -- whose selector 1% of route relations on
    Earth carry and 0% outside Europe, so a Tokyo commuter train and a
    Shinkansen were the same train. Against 2,338 OSM `duration` tags the two
    speeds ran a median 0.74 of observed and twice too fast below 20 km; the
    tiers run 1.04 with no residual distance trend.
    """
    out = priced_legs(routes, cal).drop("route_id")
    # Where a timetable times a pair of stations, its fastest train IS the
    # service, and an OSM price between the same two stations -- a guess at
    # trains no faster than it -- does not get to undercut it. The timetabled
    # leg arrives at the station's alight-only twin, so the pair is matched on
    # the station itself.
    base_to = pl.col("to_station").str.replace(f"{ALIGHT_SUFFIX}$", "")
    timed = (out.filter(pl.col("timetabled"))
                .select("from_station", base_to.alias("_to")).unique())
    out = (out.with_columns(base_to.alias("_to"))
              .join(timed.with_columns(pl.lit(True).alias("_covered")),
                    on=["from_station", "_to"], how="left")
              .filter(pl.col("timetabled") | pl.col("_covered").is_null())
              .drop("_to", "_covered", "timetabled"))
    # Several routes share a track segment at different speeds; the fastest
    # service that actually runs is the one a traveller would take.
    return out.group_by("from_station", "to_station").agg(pl.col("minutes").min())
