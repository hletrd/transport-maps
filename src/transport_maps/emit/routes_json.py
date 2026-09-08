"""Reachable transport nodes with arrival time and predecessor.

The frontend walks `prev` back to the origin to render a route breakdown such as
`ICN -> DXB -> GRU - 31h 20m`. `offsets` lets it classify a node id without a lookup.
"""

import json
from pathlib import Path

import numpy as np

# scipy marks "no predecessor" with -9999.
NO_PREDECESSOR = -9999


def write_routes(idx, minutes: np.ndarray, predecessors: np.ndarray, out: Path) -> None:
    nodes = []

    def add(node_id: int, kind: str, code: str) -> None:
        if not np.isfinite(minutes[node_id]):
            return
        prev = int(predecessors[node_id])
        nodes.append({
            "id": node_id,
            "kind": kind,
            "code": code,
            "min": round(float(minutes[node_id])),
            "prev": prev if prev != NO_PREDECESSOR else None,
        })

    for iata in idx.airports:
        # BOTH sides. A journey's chain runs cell -> A_dep -> B_arr -> B_dep,
        # so a file holding only departure nodes cannot be walked backwards
        # from where the traveller actually landed -- which is exactly what
        # the per-cell arrival ordinal in `.air.bin` names.
        add(idx.airport_index(iata), "dep", iata)
        add(idx.airport_arr_index(iata), "arr", iata)
    # Rail nodes are added in Task 9, once NodeIndex grows a station_index and
    # a .stations list. Until then there is nothing to emit for "rail" here.

    payload = {
        "offsets": {
            "cells": 0,
            "airports": idx.n_cells,
            # Airports occupy TWO ranges -- departures then arrivals -- so the
            # station range starts after both. Using one length here put the
            # boundary in the middle of the arrival nodes and would have had
            # the frontend read every arrival airport as a rail station.
            "stations": idx.n_cells + 2 * len(idx.airports),
        },
        "nodes": nodes,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
