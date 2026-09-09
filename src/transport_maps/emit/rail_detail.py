"""Which station and line a journey's rail leg used, per hover cell.

"By rail, 3 h" is the aggregate; this names the last station alighted at
and the line that reached it -- "KTX 경부선 to Busan". One uint16 per hover
cell (180 KB) indexes a per-origin table of the stations actually used,
which is a few thousand rows rather than the 257,000 stops in the network.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import h3
import numpy as np
import polars as pl

from transport_maps import config

NO_RAIL = 0xFFFF


def last_station_per_node(idx, minutes: np.ndarray, predecessors: np.ndarray) -> np.ndarray:
    """For every node, the station node it was last reached through (-1: none).
    One pass in distance order, as for airports in itinerary.py."""
    n = len(minutes)
    last = np.full(n, -1, dtype=np.int64)
    first_station = idx.n_cells + 2 * len(idx.airports)
    finite = np.isfinite(minutes)
    for node in np.argsort(np.where(finite, minutes, np.inf), kind="stable"):
        node = int(node)
        if not finite[node]:
            break
        if node >= first_station:
            last[node] = node
            continue
        prev = int(predecessors[node])
        if prev >= 0:
            last[node] = last[prev]
    return last


def _line_between(routes: pl.DataFrame) -> dict[tuple[str, str], str]:
    """Route name for each consecutive stop pair, keyed by station keys."""
    from transport_maps.graph.rail import station_key

    df = routes.sort(["route_id", "seq"]).with_columns(
        pl.struct("lat", "lon").map_elements(lambda s: station_key(s["lat"], s["lon"]),
                                             return_dtype=pl.Utf8).alias("station"))
    out: dict[tuple[str, str], str] = {}
    for _rid, g in df.group_by("route_id", maintain_order=True):
        st = g["station"].to_list()
        name = g["route_name"][0] if "route_name" in g.columns else ""
        for a, b in zip(st, st[1:]):
            out.setdefault((a, b), name)
            out.setdefault((b, a), name)
    return out


def lookup_tables(routes: pl.DataFrame | None) -> dict:
    """Everything the per-origin writer needs, as plain dicts.

    Built ONCE in the build's parent process. The writer runs in forked
    workers, and polars' thread pool does not survive a fork: a worker that
    touches a DataFrame blocks on the pool's lock forever, which is exactly
    how the first mixed-resolution build sat for three hours with eight idle
    processes and no output.
    """
    if routes is None:
        return {"lines": {}, "stop_names": {}}
    from transport_maps.graph.rail import station_key

    stop_names: dict[str, str] = {}
    for lat, lon, nm in zip(routes["lat"].to_list(), routes["lon"].to_list(), routes["name"].to_list()):
        stop_names.setdefault(station_key(lat, lon), nm)
    return {"lines": _line_between(routes), "stop_names": stop_names}


def write_rail_detail(idx, minutes: np.ndarray, predecessors: np.ndarray,
                      tables: dict | None, out_bin: Path, out_json: Path) -> None:
    """`.rail.bin`: uint16 per hover cell into `.rail.json`'s station table.
    `tables` is `lookup_tables(routes)`; None or empty means no rail."""
    from .hover import _representative_children

    parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})
    chosen = np.full(len(parents), NO_RAIL, dtype=np.int64)
    table: list[list[str]] = []
    if tables and tables.get("lines") is not None and len(idx.stations):
        first_station = idx.n_cells + 2 * len(idx.airports)
        last = last_station_per_node(idx, minutes, predecessors)
        lines, stop_names = tables["lines"], tables["stop_names"]
        index: dict[tuple[str, str], int] = {}
        for p, pos in _representative_children(idx, parents, minutes[: idx.n_cells]).items():
            node = int(last[pos])
            if node < 0:
                continue
            station = idx.stations[node - first_station]
            prev = int(predecessors[node])
            came_from = idx.stations[prev - first_station] if prev >= first_station else ""
            line = lines.get((came_from, station), "") if came_from else ""
            key = (station, line)
            if key not in index:
                index[key] = len(table)
                table.append([stop_names.get(station, ""), line])
            chosen[p] = index[key]
    out_bin.parent.mkdir(parents=True, exist_ok=True)
    out_bin.write_bytes(np.minimum(chosen, NO_RAIL).astype("<u2").tobytes())
    out_json.write_text(json.dumps({"fields": ["station", "line"], "stations": table},
                                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
