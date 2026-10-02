"""The graph a resident solver needs, written once by the build and memory-mapped.

The web host has 5 GB of memory and three cores. Assembling the graph there is
out of the question -- `build_index` plus `build_graph` peak near 11 GB and take
minutes -- and holding the build's own `NodeIndex` costs 2.3 GB of Python
strings and dict slots for a question a request asks twice ("which node is
this point?"). So the build writes what a solve needs as plain `.npy` arrays,
and the service maps them:

    cells.npy       uint64  the h3 id of every cell node, in node order
    sorted_ids.npy  uint64  the same ids, sorted, for a binary-search lookup
    sorted_pos.npy  int32   node position of each sorted id
    split.npy       uint64  sorted ids of the base cells split into FINE_RES
    indptr.npy      int32   \
    indices.npy     int32    > the CSR graph, exactly as the build solved it
    data.npy        float64 /
    meta.json               counts, resolutions, the build's identity, FORMAT

`meta.json` names the node layout the build solved on -- cells `[0, nCells)`,
then `nAirports` departure nodes, `nAirports` arrival nodes and `nStations`
station nodes (docs/contract.md, "Node-offset arithmetic") -- which is what
lets a solve say how the journey went (`journey_legs`) rather than only how
long it took. The first FORMAT-1 bundles were written without the two counts;
they still load, answer a number with no legs, and can be given the counts
afterwards by `add_counts`, which checks them against `nNodes`.

`data` stays float64 and `indices` int32 because those are the dtypes
`scipy.sparse.csgraph` works in: anything else is converted, which is a copy,
which is the 1 GB this format exists not to allocate.

Nothing here imports the graph package (service/__init__.py): the snap is
`transport_maps.snap`, the one implementation the build uses too.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h3
import numpy as np

from transport_maps import config
from transport_maps.snap import _nearest_land

FORMAT = 1
ARRAYS = ("cells", "sorted_ids", "sorted_pos", "split", "indptr", "indices", "data")


def _ids(cells) -> np.ndarray:
    return np.fromiter((int(c, 16) for c in cells), dtype=np.uint64)


def _check_layout(n_cells: int, n_nodes: int, n_airports: int, n_stations: int) -> None:
    """The node layout adds up, or ValueError. A count that is off by one moves
    every airport ordinal after it, and an itinerary read through it names the
    wrong airports with every figure still right -- so it is refused here
    rather than discovered on the page."""
    for name, v in (("nAirports", n_airports), ("nStations", n_stations)):
        if type(v) is not int or v < 0:
            raise ValueError(f"{name} must be a non-negative integer, not {v!r}")
    if n_cells + 2 * n_airports + n_stations != n_nodes:
        raise ValueError(
            f"nCells {n_cells} + 2 x nAirports {n_airports} + nStations {n_stations} "
            f"is not nNodes {n_nodes}")


def write_bundle(out: Path, cells: list[str], split, n_nodes: int, csr,
                 identity: dict[str, Any] | None = None, *,
                 n_airports: int, n_stations: int) -> Path:
    """Write the bundle to `out`, replacing any previous one in one rename."""
    out = Path(out)
    _check_layout(len(cells), int(n_nodes), n_airports, n_stations)
    tmp = out.with_name(out.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    ids = _ids(cells)
    order = np.argsort(ids, kind="stable")
    csr = csr.tocsr()
    if csr.nnz >= 2**31 or n_nodes >= 2**31:
        raise ValueError("the graph no longer fits int32 indices; the bundle format must widen")
    arrays = {
        "cells": ids,
        "sorted_ids": ids[order],
        "sorted_pos": order.astype(np.int32),
        "split": np.sort(_ids(split)),
        "indptr": csr.indptr.astype(np.int32, copy=False),
        "indices": csr.indices.astype(np.int32, copy=False),
        "data": csr.data.astype(np.float64, copy=False),
    }
    for name, arr in arrays.items():
        np.save(tmp / f"{name}.npy", arr)
    meta = {"format": FORMAT, "nCells": len(cells), "nNodes": int(n_nodes),
            "nAirports": n_airports, "nStations": n_stations,
            "nnz": int(csr.nnz), "solveRes": config.SOLVE_RES, "fineRes": config.FINE_RES,
            "identity": identity or {}}
    (tmp / "meta.json").write_text(json.dumps(meta, indent=1))
    if out.exists():
        old = out.with_name(out.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        os.replace(out, old)
        os.replace(tmp, out)
        shutil.rmtree(old, ignore_errors=True)
    else:
        os.replace(tmp, out)
    return out


class _SortedLookup:
    """`in` and `.get` over h3 cell strings, backed by sorted uint64 ids --
    the interface `snap._nearest_land` reads from a dict or a set."""

    def __init__(self, ids: np.ndarray, pos: np.ndarray | None = None) -> None:
        self._ids, self._pos = ids, pos

    def _find(self, cell: str) -> int:
        key = np.uint64(int(cell, 16))
        i = int(np.searchsorted(self._ids, key))
        return i if i < len(self._ids) and self._ids[i] == key else -1

    def __contains__(self, cell: str) -> bool:
        return self._find(cell) >= 0

    def get(self, cell: str, default=None):
        i = self._find(cell)
        if i < 0:
            return default
        return int(self._pos[i]) if self._pos is not None else i


@dataclass
class Bundle:
    meta: dict[str, Any]
    cells: np.ndarray
    cell_pos: _SortedLookup
    split: _SortedLookup
    csr: Any

    def cell_at(self, lat: float, lon: float) -> str:
        """As NodeIndex.cell_at: the fine cell where the base cell was split."""
        base = h3.latlng_to_cell(lat, lon, self.meta["solveRes"])
        if base in self.split:
            return h3.latlng_to_cell(lat, lon, self.meta["fineRes"])
        return base

    def snap(self, lat: float, lon: float) -> tuple[int, float] | None:
        """(node, km moved) as solve.dijkstra.snap_origin, or None off land."""
        cell = self.cell_at(lat, lon)
        pos = self.cell_pos.get(cell)
        if pos is not None:
            return pos, 0.0
        return _nearest_land(cell, self.cell_pos, lat, lon, self.split)

    def centre(self, pos: int) -> tuple[float, float]:
        return h3.cell_to_latlng(format(int(self.cells[pos]), "x"))

    @property
    def layout(self) -> tuple[int, int] | None:
        """(nCells, nAirports), or None for a bundle written before meta.json
        carried the counts -- which answers a number and no legs."""
        if "nAirports" not in self.meta or "nStations" not in self.meta:
            return None
        return self.meta["nCells"], self.meta["nAirports"]


def load_bundle(path: Path) -> Bundle:
    """Map a bundle. Refuses a format it was not written for, and a node
    layout that does not add up; accepts one with no layout at all."""
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())
    if meta.get("format") != FORMAT:
        raise ValueError(f"bundle format {meta.get('format')!r}, expected {FORMAT}")
    if "nAirports" in meta or "nStations" in meta:
        _check_layout(meta["nCells"], meta["nNodes"], meta.get("nAirports"), meta.get("nStations"))
    a = {name: np.load(path / f"{name}.npy", mmap_mode="r") for name in ARRAYS}
    import scipy.sparse as sp

    n = meta["nNodes"]
    csr = sp.csr_matrix((a["data"], a["indices"], a["indptr"]), shape=(n, n), copy=False)
    return Bundle(meta, a["cells"], _SortedLookup(a["sorted_ids"], a["sorted_pos"]),
                  _SortedLookup(a["split"]), csr)


def add_counts(path: Path, n_airports: int, n_stations: int) -> dict[str, Any]:
    """Give a bundle written without them its airport and station counts.

    For the FORMAT-1 bundles written before `write_bundle` recorded the node
    layout. Nothing but `meta.json` changes, and it is replaced in one rename.
    Refuses counts that do not make `nNodes` (nCells + 2 x nAirports +
    nStations), and counts that contradict ones already there. The counts
    come from a per-origin `.json` of the SAME build (`counts_from_dist`).
    """
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())
    if meta.get("format") != FORMAT:
        raise ValueError(f"bundle format {meta.get('format')!r}, expected {FORMAT}")
    _check_layout(meta["nCells"], meta["nNodes"], n_airports, n_stations)
    for name, v in (("nAirports", n_airports), ("nStations", n_stations)):
        if name in meta and meta[name] != v:
            raise ValueError(f"the bundle already says {name} {meta[name]}, not {v}")
    meta["nAirports"], meta["nStations"] = n_airports, n_stations
    tmp = path / "meta.json.part"
    tmp.write_text(json.dumps(meta, indent=1))
    os.replace(tmp, path / "meta.json")
    return meta


def counts_from_dist(bundle_path: Path, dist: Path) -> tuple[int, int]:
    """(nAirports, nStations) for a bundle, read from the dist/ of its build.

    `offsets.airports` in a per-origin `.json` is where the cells end, and
    `offsets.stations` is past both airport ranges, so nAirports is half the
    gap and nStations is what is left of `nNodes`. Refuses a dist/ from
    another build (index.json's `buildId` against the bundle's), and offsets
    whose airports do not start where the bundle's cells end: counts are
    meaningful only for the graph they were counted on.
    """
    meta = json.loads((Path(bundle_path) / "meta.json").read_text())
    index = json.loads((Path(dist) / "index.json").read_text())
    want = meta.get("identity", {}).get("buildId")
    if not want or index.get("buildId") != want:
        raise ValueError(f"dist/ is build {index.get('buildId')!r}, the bundle is {want!r}")
    slug = index["origins"][0]["slug"]
    off = json.loads((Path(dist) / "origins" / f"{slug}.json").read_text())["offsets"]
    if off["airports"] != meta["nCells"]:
        raise ValueError(f"{slug}.json puts airports at {off['airports']}, "
                         f"the bundle has {meta['nCells']} cells")
    span = off["stations"] - off["airports"]
    if span < 0 or span % 2:
        raise ValueError(f"{slug}.json's airport range is {span} nodes, not two equal halves")
    return span // 2, meta["nNodes"] - off["stations"]


def journey_legs(path: list[int], minutes: np.ndarray, n_cells: int,
                 n_airports: int) -> list[dict[str, Any]]:
    """The journey along `path` (node ids, departure first) as legs.

    Each node is classified by its range in the layout docs/contract.md
    describes, and each edge by the two nodes it joins -- the distinctions
    `emit/itinerary.py` and `emit/modes.py` draw, read off node ranges alone:

    - departure airport -> arrival airport is a flight,
      `{"kind": "fly", "from": a, "to": b, "min": m}`;
    - arrival airport -> departure airport is a connection, the only edge the
      graph builds between the two (graph/build.py, `_transfer_edges`),
      `{"kind": "connect", "at": a, "min": m}`;
    - everything else is surface, and a run of it is one leg,
      `{"kind": "surface", "min": m, "railMin": r}`: cell to cell, boarding,
      riding and alighting a train, and the access to and egress from an
      airport, check-in and the baggage belt included, as the map's own
      itinerary counts them. `r` is the time on edges that touch a station
      node, which is how `.modes.bin` counts rail.

    Airport ordinals are positions in the build's airport list, the ordinals
    `.air.bin` carries: ordinal k is departure node nCells + k and arrival
    node nCells + nAirports + k.

    Surface is NOT split into road and ferry. The build tells them apart with
    `refine.ground_joined`, which needs the landmass data (`severed`, `spans`)
    the bundle does not carry, so a cell-to-cell edge here could be either and
    the leg names neither. Only rail is split out of it.

    Minutes are rounded at each node and a leg is the difference of its two
    ends, so the legs sum exactly to the rounded total and `railMin` never
    exceeds its leg.
    """
    first_arr = n_cells + n_airports
    first_stn = n_cells + 2 * n_airports
    at = [round(float(minutes[v])) for v in path]
    legs: list[dict[str, Any]] = []
    for k in range(1, len(path)):
        u, v = path[k - 1], path[k]
        m = at[k] - at[k - 1]
        if n_cells <= u < first_arr and first_arr <= v < first_stn:
            legs.append({"kind": "fly", "from": u - n_cells, "to": v - first_arr, "min": m})
        elif first_arr <= u < first_stn and n_cells <= v < first_arr:
            legs.append({"kind": "connect", "at": u - first_arr, "min": m})
        else:
            rail = m if (u >= first_stn or v >= first_stn) else 0
            if legs and legs[-1]["kind"] == "surface":
                legs[-1]["min"] += m
                legs[-1]["railMin"] += rail
            else:
                legs.append({"kind": "surface", "min": m, "railMin": rail})
    if not legs:                         # the departure and the destination are one node
        legs.append({"kind": "surface", "min": 0, "railMin": 0})
    return legs


# scipy's "no predecessor".
_NO_PRED = -9999


def walk_back(predecessors: np.ndarray, start: int, end: int) -> list[int]:
    """The shortest path from `start` to `end`, departure first, read from
    scipy's predecessor array. ValueError if the chain does not reach `start`:
    an unreachable `end`, or an array from another solve."""
    path = [end]
    while path[-1] != start:
        prev = int(predecessors[path[-1]])
        if prev == _NO_PRED or len(path) > len(predecessors):
            raise ValueError(f"node {end} is not reached from {start}")
        path.append(prev)
    path.reverse()
    return path


class GraphSolver:
    """`wire.Solver` over a bundle: one exact point to one exact point."""

    def __init__(self, bundle: Bundle) -> None:
        self.bundle = bundle

    def solve(self, req) -> dict[str, Any]:
        """The minutes and, when the bundle names its node layout, the legs.

        Predecessors are asked for only when they can be read: a bundle with
        no layout answers a number and no `legs`, as before legs existed.
        """
        from scipy.sparse.csgraph import dijkstra

        from transport_maps.service.wire import WireError, ok_body

        start = self.bundle.snap(req.from_lat, req.from_lon)
        end = self.bundle.snap(req.to_lat, req.to_lon)
        if start is None or end is None:
            raise WireError("not_on_land")
        layout = self.bundle.layout
        if layout is None:
            dist, pred = dijkstra(self.bundle.csr, directed=True, indices=start[0]), None
        else:
            dist, pred = dijkstra(self.bundle.csr, directed=True, indices=start[0],
                                  return_predecessors=True)
        t = float(dist[end[0]])
        reachable = math.isfinite(t)
        legs = None
        if reachable and pred is not None:
            legs = journey_legs(walk_back(pred, start[0], end[0]), dist, *layout)
        lat, lon = self.bundle.centre(start[0])
        return ok_body(minutes=round(t) if reachable else None,
                       snapped_km=start[1], snapped_lat=lat, snapped_lon=lon, legs=legs)


def main(argv: list[str] | None = None) -> None:
    """Give a bundle written without them its node counts, from its build's dist/.

        python -m transport_maps.service.bundle add-counts BUNDLE DIST
    """
    import argparse

    ap = argparse.ArgumentParser(description=main.__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add-counts", help="read the counts from DIST and write them")
    add.add_argument("bundle")
    add.add_argument("dist")
    args = ap.parse_args(argv)
    n_air, n_stn = counts_from_dist(args.bundle, args.dist)
    meta = add_counts(args.bundle, n_air, n_stn)
    print(f"nAirports {meta['nAirports']}, nStations {meta['nStations']}: {args.bundle}")


if __name__ == "__main__":
    main()
