"""The road speed a cell is charged: class speed x income multiplier, slowed
inside a city's own built-up radius.

Since rebuild 31 (calibration.toml [ground], [ground_income], [urban]) the
penalty is drawn per city at `built_up_extent` of its built-up radius
(sources/urban.scaled_city_distance), not at one radius around every city of
200,000 -- which left London's outer half at highway speed -- and the fitted
class speeds are an upper-middle-income country's, scaled by the cell's
World Bank income group.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from transport_maps.graph import ground
from transport_maps.sources import countries, urban


def _speeds(monkeypatch, classes, scaled, groups):
    monkeypatch.setattr(urban, "scaled_city_distance",
                        lambda cells: (np.asarray(scaled, dtype=float), np.zeros(len(cells))))
    monkeypatch.setattr(countries, "cell_income_group", lambda country: np.asarray(groups))
    idx = SimpleNamespace(cells=[f"c{i}" for i in range(len(classes))], base_cells=[])
    return ground.cell_speed_kmh(idx, np.asarray(classes), country=np.array([""] * len(classes)))


def test_the_penalty_is_drawn_at_each_citys_own_extent(monkeypatch):
    """A cell under `built_up_extent` city radii is slowed, one at it is not.

    Mutation performed and reverted: built_up_mask comparing with
    URBAN_RADIUS_KM (the 40 km refinement radius) instead of the extent ->
    RED (both cells slowed)."""
    e = urban.URBAN_BUILT_UP_EXTENT
    k, f = ground.SPEED_BY_ROAD_CLASS_KMH, urban.URBAN_BUILT_UP_FACTOR
    v = _speeds(monkeypatch, [1, 1], [0.99 * e, e], [1, 1])
    assert np.allclose(v, [k[1] / f, k[1]])


def test_the_income_multiplier_scales_the_fitted_classes_only(monkeypatch):
    """Highway in a high-income country runs at the class speed times its
    multiplier; roadless and local keep their published defaults wherever
    they are.

    Mutations performed and reverted, each RED: drop the multiplier; apply
    it to every class."""
    k, m = ground.SPEED_BY_ROAD_CLASS_KMH, ground.INCOME_SPEED_MULTIPLIER
    far = [9.0, 9.0, 9.0, 9.0]
    v = _speeds(monkeypatch, [1, 4, 0, 5], far, [0, 3, 0, 3])
    assert np.allclose(v, [k[1] * m[0], k[4] * m[3], k[0], k[5]])
    assert m[0] > m[1] == 1.0 > m[2] > m[3]


def test_roadless_terrain_is_never_slowed_by_traffic(monkeypatch):
    """Walking pace is not slowed by traffic.

    Mutation performed and reverted: drop `& (classes > 0)` -> RED."""
    k = ground.SPEED_BY_ROAD_CLASS_KMH
    v = _speeds(monkeypatch, [0], [0.1], [1])
    assert v.tolist() == [k[0]]


def test_an_osm_motorway_raises_a_cell_to_the_motorway_class(monkeypatch):
    """GRIP4 grades an expressway like any national highway; a cell an OSM
    motorway crosses is MOTORWAY_CLASS whatever GRIP4 said, even roadless,
    and every other cell keeps its GRIP4 class.

    Mutation performed and reverted: cell_class returning grip_class
    alone -> RED."""
    monkeypatch.setattr(ground, "grip_class", lambda idx: np.array([1, 0, 3, 5]))
    monkeypatch.setattr(ground.motorways, "motorway_mask",
                        lambda idx: np.array([True, True, False, False]))
    cls = ground.cell_class(SimpleNamespace(cells=list("abcd"), base_cells=[]))
    assert cls.tolist() == [ground.MOTORWAY_CLASS, ground.MOTORWAY_CLASS, 3, 5]


def test_a_motorway_cell_runs_at_the_motorway_speed(monkeypatch):
    """Its own fitted speed, income-scaled exactly when the fit chose that
    (INCOME_SCALED_CLASSES), and slowed in a city like any road."""
    k, m = ground.SPEED_BY_ROAD_CLASS_KMH, ground.INCOME_SPEED_MULTIPLIER
    mw = ground.MOTORWAY_CLASS
    scale = m[3] if mw in ground.INCOME_SCALED_CLASSES else 1.0
    v = _speeds(monkeypatch, [mw, mw], [9.0, 0.1], [3, 3])
    assert np.allclose(v, [k[mw] * scale, k[mw] * scale / urban.URBAN_BUILT_UP_FACTOR])
