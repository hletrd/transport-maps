"""Reachable transport nodes with arrival time and predecessor.

The frontend walks `prev` back to the origin to render a route breakdown such as
`ICN -> DXB -> GRU - 31h 20m`. `offsets` lets it classify a node id without a lookup.
"""

import json
from pathlib import Path

import numpy as np

from transport_maps import _io
from transport_maps.emit.hover import MAX_MINUTES
from transport_maps.graph.layout import layout_of

# scipy marks "no predecessor" with -9999.
NO_PREDECESSOR = -9999


def write_routes(idx, minutes: np.ndarray, predecessors: np.ndarray, out: Path) -> None:
    """Every reachable airport node, keyed by id, with its time and `prev`.

    The page enters this file at id `offsets.airports + n_air + k` for the
    `.air.bin` ordinal k, and walks `prev` from there. Since A15 an airport has
    two arrival nodes (graph/layout.py): the domestic one and the
    international one, where a journey from another immigration zone lands.
    Which of them a cell was reached through is fixed per airport: the only
    way out of either is into the airport's own cell, so every cell that names
    airport k descends from that cell, and its predecessor is the one arrival
    node they all share. Where that is the international node, the two swap
    ids in this file, so the id the page enters at is the node the journey
    actually left the airport from and the page needs no new arithmetic. Every
    `prev` is renamed the same way, so each chain still reads end to end.

    International nodes are listed only where a chain the page can walk passes
    through them -- back from an entry or from a domestic node -- which keeps
    the file near its old size.
    """
    lay = layout_of(idx)
    # A graph built before the international layer existed ends at the
    # stations; it has nothing to swap or add.
    intl = len(minutes) >= lay.n
    rename: dict[int, int] = {}
    if intl:
        for k, iata in enumerate(idx.airports):
            arr, xarr = lay.first_arrival + k, lay.first_intl_arrival + k
            if int(predecessors[idx.airport_cell_index(iata)]) == xarr:
                rename[arr], rename[xarr] = xarr, arr

    def rid(node: int) -> int:
        return rename.get(node, node)

    nodes = []

    def add(node_id: int, kind: str, code: str) -> bool:
        # Unreachable, or so far out (45 days) that the hover array calls it
        # unreachable: the page would otherwise print a finite leg under an
        # infinite total.
        if not np.isfinite(minutes[node_id]) or minutes[node_id] >= MAX_MINUTES:
            return False
        prev = int(predecessors[node_id])
        nodes.append({
            "id": rid(node_id),
            "kind": kind,
            "code": code,
            "min": round(float(minutes[node_id])),
            "prev": rid(prev) if prev != NO_PREDECESSOR else None,
        })
        return True

    listed: list[int] = []
    for k, iata in enumerate(idx.airports):
        # BOTH sides. A journey's chain runs cell -> A_dep -> B_arr -> B_dep,
        # so a file holding only departure nodes cannot be walked backwards
        # from where the traveller actually landed -- which is exactly what
        # the per-cell arrival ordinal in `.air.bin` names.
        for node, kind in ((idx.airport_index(iata), "dep"), (idx.airport_arr_index(iata), "arr")):
            if add(node, kind, iata):
                listed.append(node)
    if intl:
        def is_airport(node: int) -> bool:
            return (lay.first_departure <= node < lay.first_station
                    or lay.first_intl_departure <= node < lay.n)

        starts = listed + [lay.first_intl_arrival + k for k in range(len(idx.airports))
                           if lay.first_arrival + k in rename]
        seen: set[int] = set()
        wanted: list[int] = []
        for node in starts:
            while node >= 0 and is_airport(node) and node not in seen:
                seen.add(node)
                if node >= lay.first_intl_departure:
                    wanted.append(node)
                node = int(predecessors[node])
        for node in sorted(wanted):
            k = (node - lay.first_intl_departure) % len(idx.airports)
            kind = "dep" if node < lay.first_intl_arrival else "arr"
            add(node, kind, idx.airports[k])
    # Airport nodes only. Cells are never listed: the page reads a hover
    # cell's time, arrival airport and surface modes from the per-origin
    # arrays (.bin, .air.bin, .modes.bin), enters this file at that arrival
    # node and walks `prev` while it lands on airport nodes. Stations are not
    # listed either; the rail leg is itemised from .rail.bin/.rail.json.

    offsets = {
        "cells": 0,
        "airports": idx.n_cells,
        # Airports occupy TWO ranges -- departures then arrivals -- so the
        # station range starts after both. Using one length here put the
        # boundary in the middle of the arrival nodes and would have had
        # the frontend read every arrival airport as a rail station.
        "stations": lay.first_station,
    }
    if intl:
        # Ids from here on are the international airport layer, departures
        # then arrivals. Informational: the page walks them by id alone.
        offsets["intl"] = lay.first_intl_departure
    _io.write_text(out, json.dumps({"offsets": offsets, "nodes": nodes}, separators=(",", ":")))
