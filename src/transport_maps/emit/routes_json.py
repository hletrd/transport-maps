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
            "min": int(round(float(minutes[node_id]))),
            "prev": prev if prev != NO_PREDECESSOR else None,
        })

    for iata in idx.airports:
        add(idx.airport_index(iata), "air", iata)
    # Rail nodes are added in Task 9, once NodeIndex grows a station_index and
    # a .stations list. Until then there is nothing to emit for "rail" here.

    payload = {
        "offsets": {
            "cells": 0,
            "airports": idx.n_cells,
            # No rail nodes exist yet (Task 9); keep this equal to the end of
            # the airport range so the format stays stable once they land.
            "stations": idx.n_cells + len(idx.airports),
        },
        "nodes": nodes,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
