"""The vectorised hover representative must pick exactly what the loop did."""

import h3
import numpy as np
import pytest

from transport_maps import config
from transport_maps.emit import hover


def _idx(seed):
    """Real cells around Seoul: some base cells whole, some split into their
    FINE_RES children, and a few parents' centre cells left OUT (water), so
    both branches of the rule -- centre, and fastest-child fallback -- run."""
    rng = np.random.default_rng(seed)
    base = h3.grid_disk(h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES), 12)
    cells = []
    for b in base:
        if rng.random() < 0.15:
            continue                      # water: absent from the index
        if rng.random() < 0.3:
            cells += h3.cell_to_children(b, config.FINE_RES)
        else:
            cells.append(b)

    class Idx:
        pass

    idx = Idx()
    idx.cells = cells
    return idx


@pytest.mark.parametrize("seed", range(6))
def test_the_vectorised_representative_matches_the_loop(seed):
    idx = _idx(seed)
    parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})
    rng = np.random.default_rng(100 + seed)
    minutes = rng.integers(0, 40, size=len(idx.cells)).astype(float)   # many ties
    minutes[rng.random(len(minutes)) < 0.1] = np.inf                   # unreachable
    slow = hover._representative_children_slow(idx, parents, minutes)
    fast = hover._representative_children(idx, parents, minutes,
                                          groups=hover.hover_groups(idx, parents))
    assert fast == slow
    assert any(hover.hover_groups(idx, parents).centre < 0), \
        "fixture: some parent's centre must be water, or the fallback is untested"


def test_without_groups_the_answer_is_the_loops():
    idx = _idx(0)
    parents = sorted({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})
    minutes = np.arange(len(idx.cells), dtype=float)
    assert hover._representative_children(idx, parents, minutes) == \
        hover._representative_children_slow(idx, parents, minutes)
