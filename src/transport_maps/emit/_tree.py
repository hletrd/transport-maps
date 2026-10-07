"""Whole-array passes down a shortest-path tree.

Two emitters walked the tree one node at a time in distance order --
`modes.mode_minutes_per_node` and `itinerary.arrival_airport_per_node`, ~60 s
of an origin together over 13.8 M nodes (py-spy, Seoul, 2026-10-07). Both are
"each node takes something from its predecessor", which numpy can do a whole
tree level at a time, or by pointer doubling, in a few dozen array passes.
"""

from __future__ import annotations

import numpy as np


def _parents(predecessors: np.ndarray, reached: np.ndarray) -> np.ndarray:
    """Each reached node's predecessor, or itself for a root (no predecessor)
    and for every node not reached."""
    n = len(predecessors)
    me = np.arange(n, dtype=np.int64)
    prev = predecessors.astype(np.int64, copy=False)
    return np.where(reached & (prev >= 0), prev, me)


def depth(predecessors: np.ndarray, reached: np.ndarray) -> np.ndarray:
    """Edges from each reached node up to its root, by pointer doubling;
    0 for roots and for nodes not reached."""
    up = _parents(predecessors, reached)
    d = (up != np.arange(len(up))).astype(np.int64)
    while True:
        nd = d + d[up]
        nup = up[up]
        if np.array_equal(nup, up):
            return d
        d, up = nd, nup


def by_level(predecessors: np.ndarray, reached: np.ndarray) -> list[np.ndarray]:
    """The reached non-root nodes grouped by depth, shallowest first: every
    node's predecessor sits in an earlier group (or is a root)."""
    d = depth(predecessors, reached)
    nodes = np.flatnonzero(reached & (d > 0))
    if not len(nodes):
        return []
    order = nodes[np.argsort(d[nodes], kind="stable")]
    cuts = np.flatnonzero(np.diff(d[order])) + 1
    return np.split(order, cuts)


def nearest_marked_ancestor(mark: np.ndarray, predecessors: np.ndarray,
                            reached: np.ndarray) -> np.ndarray:
    """For every reached node, the nearest node on its path to the root,
    itself included, for which `mark` holds; -1 where there is none and for
    nodes not reached."""
    me = np.arange(len(mark), dtype=np.int64)
    up = np.where(mark, me, _parents(predecessors, reached))
    while True:
        nup = up[up]
        if np.array_equal(nup, up):
            break
        up = nup
    return np.where(reached & mark[up], up, -1)
