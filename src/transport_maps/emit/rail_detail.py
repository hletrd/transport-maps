"""Which station, line, operator and service number a rail leg used, per cell.

"By rail, 3 h" is the aggregate; this names the last station alighted at, the
line that reached it, who runs it and what the service is called -- "KTX
경부선 to Busan, Korail, 101". One uint16 per hover cell (181,480 bytes over
90,740 cells) indexes a per-origin table of the stations actually used, which
is a few thousand rows rather than the 257,000 stops in the network.

`operator` and `ref` were added because the owner asked for more of this kind
of detail. Coverage measured over all 19,297 train route relations: `operator`
92%, `ref` 88%, and `operator` is the only one of the candidate fields whose
coverage survives leaving Europe. `network` (67%), `colour` (39%) and `via`
(19%) were measured and declined; `2026-09-15-c14-rail-service-tiers.md` says
why for each. The cost is +19.9 KB gzipped per origin against `.r6.bin`'s
5.33 MB on the same city switch.
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import h3
import numpy as np
import polars as pl

from transport_maps import _io, config

NO_RAIL = 0xFFFF
# Ordinal for "this route carries no `operator` tag". 8% of route relations
# worldwide, and 20% in Africa, so it is the common case somewhere and the page
# must render it as an absence rather than as a blank label.
NO_OPERATOR = -1


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


def _line_between(routes: pl.DataFrame, cal) -> dict[tuple[str, str], tuple]:
    """`(from, to)` -> the `(name, operator, ref)` of the service that was TIMED.

    Two things this gets right that the previous version did not.

    **The caption names the service the edge was priced from.** `ride_edges`
    resolves parallel services on a shared segment by `min(minutes)`; this used
    to resolve them by `setdefault` over `group_by("route_id")`, which keeps the
    LOWEST OSM RELATION ID. Those are unrelated orderings: 20.9% of directed
    pairs (30,742 of 147,332) were captioned with a different line than the one
    whose running time the traveller was charged, and 370 of them with a
    different speed class. So the leg time was a Shinkansen's and the name a
    local's. Each pair now keeps the minimum-minutes route, scored with the same
    arithmetic `ride_edges` uses.

    **The reverse direction is no longer filled with the forward name.** It used
    to do `out.setdefault((b, a), name)`, and OSM route names are directional --
    `경부선 KTX: 서울 → 부산`, `東急東横線: 横浜 => 渋谷`. 50.0% of arrow-named
    station pairs (55,500 of 111,051) therefore captioned a ride with the
    service running the other way, and 3,834 shipped rows named the line's own
    ORIGIN terminus as where the traveller was heading. Most lines carry a
    separate relation per direction, so the fix is to key strictly on the
    direction travelled and fall back to an opposite-direction service only when
    no relation runs the way the traveller went -- which is still worth saying,
    because the line is right even when its arrow is not.
    """
    from transport_maps.graph.rail import _haversine_km, station_key

    df = routes.sort(["route_id", "seq"]).with_columns(
        pl.struct("lat", "lon").map_elements(lambda s: station_key(s["lat"], s["lon"]),
                                             return_dtype=pl.Utf8).alias("station"))
    fwd: dict[tuple[str, str], tuple[float, tuple]] = {}
    rev: dict[tuple[str, str], tuple[float, tuple]] = {}
    for _rid, g in df.group_by("route_id", maintain_order=True):
        st = g["station"].to_list()
        lat, lon = g["lat"].to_list(), g["lon"].to_list()
        label = (g["route_name"][0] if "route_name" in g.columns else "",
                 g["operator"][0] if "operator" in g.columns else "",
                 g["ref"][0] if "ref" in g.columns else "")
        tier = g["tier"][0] if "tier" in g.columns else None
        t = cal.tiers.get(tier) if tier is not None else None
        for i, (a, b) in enumerate(pairwise(st)):
            if a == b:
                continue
            if t is None:
                minutes = 0.0
            else:
                km = float(_haversine_km(lat[i], lon[i], lat[i + 1], lon[i + 1]))
                minutes = t.stop_overhead_min + 60.0 * km * cal.detour_factor / t.speed_kmh
            for store, key in ((fwd, (a, b)), (rev, (b, a))):
                if key not in store or minutes < store[key][0]:
                    store[key] = (minutes, label)
    out = {k: v[1] for k, v in fwd.items()}
    for k, v in rev.items():
        out.setdefault(k, v[1])
    return out


def lookup_tables(routes: pl.DataFrame | None, cal=None) -> dict:
    """Everything the per-origin writer needs, as plain dicts.

    Built ONCE in the build's parent process. The writer runs in forked
    workers, and polars' thread pool does not survive a fork: a worker that
    touches a DataFrame blocks on the pool's lock forever, which is exactly
    how the first mixed-resolution build sat for three hours with eight idle
    processes and no output.

    `cal` is the rail calibration, needed only to score which of several
    services on a shared segment is the one the edge was priced from. It is
    loaded here when the caller does not supply it, so the parent pays the
    tomllib read once rather than every forked worker.
    """
    if routes is None:
        return {"lines": {}, "stop_names": {}}
    from transport_maps.graph.rail import load_rail_calibration, station_key

    stop_names: dict[str, str] = {}
    for lat, lon, nm in zip(routes["lat"].to_list(), routes["lon"].to_list(), routes["name"].to_list()):
        # A stop with no name of its own stays empty rather than taking the
        # first named route through it; `railVia` degrades on the empty string.
        stop_names.setdefault(station_key(lat, lon), nm or "")
    return {"lines": _line_between(routes, cal or load_rail_calibration()),
            "stop_names": stop_names}


def write_rail_detail(idx, minutes: np.ndarray, predecessors: np.ndarray,
                      tables: dict | None, out_bin: Path, out_json: Path) -> None:
    """`.rail.bin`: uint16 per hover cell into `.rail.json`'s station table.
    `tables` is `lookup_tables(routes)`; None or empty means no rail."""
    from .hover import _representative_children

    parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})
    chosen = np.full(len(parents), NO_RAIL, dtype=np.int64)
    table: list[list] = []
    # Operator names repeat across nearly every row -- one railway runs hundreds
    # of a city's reachable stations -- so they are interned into their own
    # array and the row carries an ordinal. Measured on a real 2,110-row table:
    # inline costs 10.7 gzipped bytes a row, interned 9.4, and the raw file is
    # 26 KB smaller. NO_OPERATOR (-1) is "OSM did not say", which the page
    # prints as nothing at all rather than as an empty bracket.
    operators: list[str] = []
    op_index: dict[str, int] = {}
    if tables and tables.get("lines") is not None and len(idx.stations):
        first_station = idx.n_cells + 2 * len(idx.airports)
        last = last_station_per_node(idx, minutes, predecessors)
        lines, stop_names = tables["lines"], tables["stop_names"]
        index: dict[tuple, int] = {}
        for p, pos in _representative_children(idx, parents, minutes[: idx.n_cells]).items():
            node = int(last[pos])
            if node < 0:
                continue
            station = idx.stations[node - first_station]
            prev = int(predecessors[node])
            came_from = idx.stations[prev - first_station] if prev >= first_station else ""
            line, operator, ref = (lines.get((came_from, station), ("", "", ""))
                                   if came_from else ("", "", ""))
            key = (station, line, operator, ref)
            if key not in index:
                if operator and operator not in op_index:
                    op_index[operator] = len(operators)
                    operators.append(operator)
                index[key] = len(table)
                table.append([stop_names.get(station, ""), line,
                              op_index.get(operator, NO_OPERATOR), ref])
            chosen[p] = index[key]
    if len(table) >= NO_RAIL:
        # np.minimum used to fold any index past the sentinel into "no rail"
        # silently; a table that large is a bug, not a build.
        raise ValueError(f"rail table has {len(table):,} rows; uint16 holds {NO_RAIL - 1:,}")
    _io.write_bytes(out_bin, chosen.astype("<u2").tobytes())
    _io.write_text(out_json, json.dumps(
        {"fields": ["station", "line", "operator", "ref"],
         "operators": operators, "stations": table},
        ensure_ascii=False, separators=(",", ":")))
