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

# ~200 m edge (0.35 km across): comfortably merges the platforms of one station while
# keeping genuinely separate city stations apart.
STATION_RES = 9


@dataclass(frozen=True)
class RailCalibration:
    highspeed_kmh: float
    conventional_kmh: float
    detour_factor: float
    boarding_min: float
    alighting_min: float


def load_rail_calibration(path=None) -> RailCalibration:
    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        raw = tomllib.load(fh)["rail"]
    return RailCalibration(**raw)


def station_key(lat: float, lon: float) -> str:
    return h3.latlng_to_cell(lat, lon, STATION_RES)


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
    """One row per physical station, with the cell it sits in."""
    df = routes.with_columns(
        pl.struct("lat", "lon")
        .map_elements(lambda s: station_key(s["lat"], s["lon"]), return_dtype=pl.Utf8)
        .alias("station")
    )
    return (df.group_by("station")
              .agg(pl.col("lat").mean(), pl.col("lon").mean(),
                   pl.col("name").first())
              .with_columns(
                  pl.struct("lat", "lon").map_elements(
                      lambda s: h3.latlng_to_cell(s["lat"], s["lon"], config.SOLVE_RES),
                      return_dtype=pl.Utf8).alias("cell"))
              .sort("station"))


def ride_edges(routes: pl.DataFrame, cal) -> pl.DataFrame:
    """Running time between consecutive stops, in minutes.

    Consecutive means consecutive in `seq` WITHIN one route; the shift must be
    partitioned or the last stop of one route joins to the first of the next
    and invents an edge across the country.
    """
    df = routes.with_columns(
        pl.struct("lat", "lon")
        .map_elements(lambda s: station_key(s["lat"], s["lon"]), return_dtype=pl.Utf8)
        .alias("station")
    ).sort("route_id", "seq")

    nxt = df.with_columns(
        pl.col("station").shift(-1).over("route_id").alias("to_station"),
        pl.col("lat").shift(-1).over("route_id").alias("to_lat"),
        pl.col("lon").shift(-1).over("route_id").alias("to_lon"),
    ).drop_nulls("to_station").filter(pl.col("station") != pl.col("to_station"))

    km = _haversine_km(nxt["lat"].to_numpy(), nxt["lon"].to_numpy(),
                       nxt["to_lat"].to_numpy(), nxt["to_lon"].to_numpy())
    speed = np.where(nxt["highspeed"].to_numpy(), cal.highspeed_kmh, cal.conventional_kmh)
    minutes = 60.0 * km * cal.detour_factor / speed

    out = pl.DataFrame({"from_station": nxt["station"], "to_station": nxt["to_station"],
                        "minutes": minutes})
    # Several routes share a track segment at different speeds; the fastest
    # service that actually runs is the one a traveller would take.
    return out.group_by("from_station", "to_station").agg(pl.col("minutes").min())
