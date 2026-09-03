import h3
import numpy as np
import pytest

from transport_maps import config, validate


def test_coverage_is_the_reachable_fraction():
    minutes = np.array([10.0, 20.0, np.inf, np.inf])

    class Idx:
        n_cells = 4
    assert validate.check_coverage(minutes, Idx()) == 0.5


def test_low_coverage_trips_the_publish_threshold():
    """build-all compares check_coverage's return against MIN_COVERAGE before
    shipping (see cli._build_all). A gate that always reports full coverage
    would let a broken solve through, so pin that a mostly-unreachable input
    actually lands below the threshold.
    """
    minutes = np.concatenate([np.full(5, 1.0), np.full(95, np.inf)])

    class Idx:
        n_cells = 100
    assert validate.check_coverage(minutes, Idx()) < validate.MIN_COVERAGE


def test_overlapping_bands_are_rejected():
    fc = {"features": [
        {"properties": {"band": 0}, "geometry": {"type": "Polygon", "coordinates": [[
            [0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}},
        {"properties": {"band": 1}, "geometry": {"type": "Polygon", "coordinates": [[
            [1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}},
    ]}
    with pytest.raises(ValueError, match="overlap"):
        validate.check_bands_disjoint(fc)


def test_disjoint_bands_are_accepted():
    fc = {"features": [
        {"properties": {"band": 0}, "geometry": {"type": "Polygon", "coordinates": [[
            [0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}},
        {"properties": {"band": 1}, "geometry": {"type": "Polygon", "coordinates": [[
            [5, 5], [6, 5], [6, 6], [5, 6], [5, 5]]]}},
    ]}
    validate.check_bands_disjoint(fc)  # must not raise


class _TwoCellIdx:
    """Minimal idx double: two genuinely-adjacent H3 cells, nothing else."""

    def __init__(self, cell: str, neighbour: str):
        self.n_cells = 2
        self.cells = [cell, neighbour]
        self._pos = {cell: 0, neighbour: 1}

    def try_cell_index(self, cell: str) -> int | None:
        return self._pos.get(cell)


def _adjacent_pair() -> tuple[str, str]:
    seoul = h3.latlng_to_cell(37.5665, 126.9780, config.SOLVE_RES)
    neighbour = next(c for c in h3.grid_disk(seoul, 1) if c != seoul)
    return seoul, neighbour


def test_inconsistent_neighbour_time_is_rejected():
    """A neighbour reported far more expensive than the actual hop from an
    already-reached cell violates Dijkstra's own invariant.
    """
    cell, neighbour = _adjacent_pair()
    idx = _TwoCellIdx(cell, neighbour)
    # The real one-hop cost between adjacent res-5 cells is at most a few
    # hundred minutes even over roadless terrain (5 km/h floor); 1e6 minutes
    # is unreachable via any legitimate hop cost.
    minutes = np.array([0.0, 1e6])

    with pytest.raises(ValueError, match="inconsistent"):
        validate.check_monotonic_ground(idx, minutes)


def test_consistent_neighbour_time_is_accepted():
    """Sanity companion to the rejection test: a neighbour time within the
    real hop cost of its already-reached neighbour must not raise.
    """
    cell, neighbour = _adjacent_pair()
    idx = _TwoCellIdx(cell, neighbour)
    minutes = np.array([0.0, 0.0])  # reaching the neighbour "for free" only helps

    validate.check_monotonic_ground(idx, minutes)  # must not raise
