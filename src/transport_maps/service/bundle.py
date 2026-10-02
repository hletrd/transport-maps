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


def write_bundle(out: Path, cells: list[str], split, n_nodes: int, csr,
                 identity: dict[str, Any] | None = None) -> Path:
    """Write the bundle to `out`, replacing any previous one in one rename."""
    out = Path(out)
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


def load_bundle(path: Path) -> Bundle:
    """Map a bundle. Refuses a format it was not written for."""
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())
    if meta.get("format") != FORMAT:
        raise ValueError(f"bundle format {meta.get('format')!r}, expected {FORMAT}")
    a = {name: np.load(path / f"{name}.npy", mmap_mode="r") for name in ARRAYS}
    import scipy.sparse as sp

    n = meta["nNodes"]
    csr = sp.csr_matrix((a["data"], a["indices"], a["indptr"]), shape=(n, n), copy=False)
    return Bundle(meta, a["cells"], _SortedLookup(a["sorted_ids"], a["sorted_pos"]),
                  _SortedLookup(a["split"]), csr)


class GraphSolver:
    """`wire.Solver` over a bundle: one exact point to one exact point."""

    def __init__(self, bundle: Bundle) -> None:
        self.bundle = bundle

    def solve(self, req) -> dict[str, Any]:
        from scipy.sparse.csgraph import dijkstra

        from transport_maps.service.wire import WireError, ok_body

        start = self.bundle.snap(req.from_lat, req.from_lon)
        end = self.bundle.snap(req.to_lat, req.to_lon)
        if start is None or end is None:
            raise WireError("not_on_land")
        dist = dijkstra(self.bundle.csr, directed=True, indices=start[0])
        t = float(dist[end[0]])
        lat, lon = self.bundle.centre(start[0])
        return ok_body(minutes=round(t) if math.isfinite(t) else None,
                       snapped_km=start[1], snapped_lat=lat, snapped_lon=lon)
