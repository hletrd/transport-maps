"""The whole-array tree passes (emit/_tree) give what the node-by-node loops
they replaced gave, on random shortest-path trees.

The reference loops are the shipped ones as of 2026-10-07, kept here verbatim
apart from their names.
"""

from __future__ import annotations

import numpy as np
import pytest

from transport_maps.emit import _tree, itinerary, modes
from transport_maps.graph.layout import layout_of


class Idx:
    def __init__(self, n_cells, n_airports, n_stations):
        self.n_cells = n_cells
        self.airports = [f"A{i}" for i in range(n_airports)]
        self.stations = tuple(f"s{i}" for i in range(n_stations))
        self.cells = [f"c{i}" for i in range(n_cells)]

    @property
    def n(self):
        return layout_of(self).n


def _random_tree(idx, seed, unreachable=0.05):
    """minutes strictly increasing from parent to child, a few nodes left
    unreached, one root (the origin)."""
    rng = np.random.default_rng(seed)
    n = idx.n
    order = rng.permutation(n)
    minutes = np.full(n, np.inf)
    pred = np.full(n, -9999, dtype=np.int64)
    root = order[0]
    minutes[root] = 0.0
    placed = [root]
    for node in order[1:]:
        if rng.random() < unreachable:
            continue
        parent = placed[int(rng.integers(0, len(placed)))]
        pred[node] = parent
        minutes[node] = minutes[parent] + float(rng.uniform(0.1, 30.0))
        placed.append(node)
    return minutes, pred


def _modes_by_loop(idx, minutes, predecessors, cell_class, joined):
    n_cells = idx.n_cells
    is_station = layout_of(idx).is_station
    acc = np.zeros((len(minutes), len(modes.CHANNELS)), dtype=np.float64)
    finite = np.isfinite(minutes)
    order = np.argsort(np.where(finite, minutes, np.inf), kind="stable")
    for node in order:
        node = int(node)
        if not finite[node]:
            break
        prev = int(predecessors[node])
        if prev < 0:
            continue
        acc[node] = acc[prev]
        cost = minutes[node] - minutes[prev]
        prev_cell, node_cell = prev < n_cells, node < n_cells
        prev_stn, node_stn = is_station(prev), is_station(node)
        if prev_cell and node_cell:
            if joined(prev, node):
                acc[node][modes.ROAD_CHANNEL[int(cell_class[node])]] += cost
            else:
                acc[node][1] += cost
        elif prev_stn or node_stn:
            acc[node][0] += cost
    return acc


def _arrival_by_loop(idx, minutes, predecessors):
    n = len(minutes)
    last = np.full(n, -1, dtype=np.int64)
    is_arrival = layout_of(idx).is_arrival
    finite = np.isfinite(minutes)
    for node in np.argsort(np.where(finite, minutes, np.inf), kind="stable"):
        node = int(node)
        if not finite[node]:
            break
        if is_arrival(node):
            last[node] = node
            continue
        prev = int(predecessors[node])
        if prev >= 0:
            last[node] = last[prev]
    return last


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_modes_match_the_loop_with_ferries_read_off_the_ferry_keys(seed, monkeypatch):
    """Mutation performed and reverted: `acc[level] = acc[prev_all[level]]`
    dropped (a node no longer inherits its predecessor's totals) -> red."""
    idx = Idx(n_cells=1500, n_airports=25, n_stations=60)
    minutes, pred = _random_tree(idx, seed)
    rng = np.random.default_rng(seed + 100)
    cell_class = rng.integers(0, 6, size=idx.n_cells)
    cell_edges = [(int(pred[v]), v) for v in range(idx.n_cells)
                  if np.isfinite(minutes[v]) and 0 <= pred[v] < idx.n_cells]
    assert len(cell_edges) > 100
    ferries = {e for e in cell_edges if rng.random() < 0.2}
    keys = np.array(sorted(u * idx.n + v for u, v in ferries), dtype=np.int64)
    want = _modes_by_loop(idx, minutes, pred, cell_class, lambda u, v: (u, v) not in ferries)
    got = modes.mode_minutes_per_node(idx, minutes, pred, cell_class, ferry_keys=keys)
    assert np.array_equal(got, want)
    assert (want[:, 1] > 0).any() and (want[:, 0] > 0).any() and (want[:, 2:] > 0).any()
    # Without the keys the pairs are asked one by one, and agree too.
    monkeypatch.setattr(modes, "ground_joined", lambda _idx, u, v: (u, v) not in ferries)
    assert np.array_equal(modes.mode_minutes_per_node(idx, minutes, pred, cell_class), want)


@pytest.mark.parametrize("seed", [4, 5, 6])
def test_arrival_airport_matches_the_loop(seed):
    """Mutation performed and reverted: `mark[up]` dropped from the final
    `where` (a root counted as an arrival) -> red."""
    idx = Idx(n_cells=1500, n_airports=40, n_stations=60)
    minutes, pred = _random_tree(idx, seed)
    want = _arrival_by_loop(idx, minutes, pred)
    got = itinerary.arrival_airport_per_node(idx, minutes, pred)
    assert np.array_equal(got, want)
    assert (want >= 0).any() and (want == -1).any()


def test_depth_counts_edges_to_the_root():
    pred = np.array([-9999, 0, 1, 1, 3, -9999], dtype=np.int64)
    reached = np.array([True, True, True, True, True, False])
    assert _tree.depth(pred, reached).tolist() == [0, 1, 2, 2, 3, 0]
    levels = [lv.tolist() for lv in _tree.by_level(pred, reached)]
    assert levels == [[1], [2, 3], [4]]
