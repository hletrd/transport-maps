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


def _speeds(monkeypatch, classes, scaled, groups, limits=None, regions=None):
    n = len(classes)
    monkeypatch.setattr(urban, "scaled_city_distance",
                        lambda cells: (np.asarray(scaled, dtype=float), np.zeros(len(cells))))
    monkeypatch.setattr(countries, "cell_income_group", lambda country: np.asarray(groups))
    monkeypatch.setattr(countries, "cell_driving_region",
                        lambda country: np.asarray(regions if regions is not None else [0] * n))
    monkeypatch.setattr(ground.motorways, "motorway_limit",
                        lambda idx, *a, **k: np.asarray(limits if limits is not None
                                                        else [np.nan] * n, dtype=float))
    idx = SimpleNamespace(cells=[f"c{i}" for i in range(n)], base_cells=[])
    return ground.cell_speed_kmh(idx, np.asarray(classes), country=np.array([""] * n))


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
    # Lower-middle and low are one fitted multiplier since rebuild 33.
    assert m[0] > m[1] == 1.0 > m[2] >= m[3]


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
                        lambda idx, rule=None: (np.zeros(4, bool) if rule == "any"
                                                else np.array([True, True, False, False])))
    cls = ground.cell_class(SimpleNamespace(cells=list("abcd"), base_cells=[]))
    assert cls.tolist() == [ground.MOTORWAY_CLASS, ground.MOTORWAY_CLASS, 3, 5]


def test_an_osm_trunk_raises_a_cell_grip4_grades_below_primary(monkeypatch):
    """GRIP4 misses roads OSM has: the coast road from Tawau to its airport is
    OSM trunk and GRIP4 roadless and tertiary, so a 27 km run went 145 km
    round inland (rebuild 32). A cell any OSM motorway or trunk crosses is at
    least primary where GRIP4 graded it roadless, tertiary or local; a better
    GRIP4 grade (highway, secondary) is kept, and a motorway still wins.

    Mutation performed and reverted: drop the trunk floor from cell_class ->
    RED."""
    monkeypatch.setattr(ground, "grip_class", lambda idx: np.array([0, 4, 5, 1, 3, 0, 0]))
    any_trunk = np.array([True, True, True, True, True, False, True])
    motorway = np.array([False, False, False, False, False, False, True])
    monkeypatch.setattr(ground.motorways, "motorway_mask",
                        lambda idx, rule=None: any_trunk if rule == "any" else motorway)
    cls = ground.cell_class(SimpleNamespace(cells=list("abcdefg"), base_cells=[]))
    assert cls.tolist() == [2, 2, 2, 1, 3, 0, ground.MOTORWAY_CLASS]


def test_a_motorway_runs_at_the_speed_of_its_signed_limit(monkeypatch):
    """No signed limit, under 95, 95-115 and 115 km/h or more each have their
    fitted speed (calibration.toml [ground_motorway]): the desert motorway
    from Cairo to Alexandria is signed 100-120 and drove at the country's
    average motorway speed before (rebuild 32: 214 min against 151).

    Mutation performed and reverted: drop the limit lookup (every motorway at
    motorway_kmh) -> RED."""
    t = ground.MOTORWAY_SPEED_BY_LIMIT_KMH
    mw = ground.MOTORWAY_CLASS
    v = _speeds(monkeypatch, [mw] * 4, [9.0] * 4, [1] * 4, limits=[np.nan, 80.0, 100.0, 120.0])
    assert np.allclose(v, t)
    assert len(set(t.tolist())) == 4


def test_north_america_drives_faster_than_its_income_group(monkeypatch):
    """With one high-income multiplier North American journeys came out 9%
    too slow (rebuild 32's fit); [ground_region] north_america scales the
    fitted classes on top of the income multiplier, and nothing else.

    Mutation performed and reverted: drop the region multiplier -> RED."""
    k, m = ground.SPEED_BY_ROAD_CLASS_KMH, ground.INCOME_SPEED_MULTIPLIER
    r = ground.REGION_SPEED_MULTIPLIER
    v = _speeds(monkeypatch, [1, 1, 5], [9.0] * 3, [0, 0, 0], regions=[1, 0, 1])
    assert np.allclose(v, [k[1] * m[0] * r[1], k[1] * m[0], k[5]])
    assert r[1] > 1.0


def test_a_motorway_cell_runs_at_the_motorway_speed(monkeypatch):
    """Its own fitted speed, income-scaled exactly when the fit chose that
    (INCOME_SCALED_CLASSES), and slowed in a city like any road."""
    m = ground.INCOME_SPEED_MULTIPLIER
    mw = ground.MOTORWAY_CLASS
    base = ground.MOTORWAY_SPEED_BY_LIMIT_KMH[0]
    scale = m[3] if mw in ground.INCOME_SCALED_CLASSES else 1.0
    # 0.75 radii: inside the built-up disc, outside its core (rebuild 34).
    v = _speeds(monkeypatch, [mw, mw], [9.0, 0.75], [3, 3])
    assert np.allclose(v, [base * scale, base * scale / urban.URBAN_BUILT_UP_FACTOR])


def test_a_city_core_is_slowed_twice(monkeypatch):
    """Inside `core_extent` built-up radii a road cell pays the core factor on
    top of the built-up one; at the core's edge it pays the built-up factor
    alone (rebuild 34: city-centre departures ran 12% fast).

    Mutation performed and reverted: drop the core line from
    cell_speed_kmh -> RED."""
    k, f, c = ground.SPEED_BY_ROAD_CLASS_KMH, urban.URBAN_BUILT_UP_FACTOR, urban.URBAN_CORE_FACTOR
    e = urban.URBAN_CORE_EXTENT
    v = _speeds(monkeypatch, [2, 2, 0], [0.99 * e, e, 0.1], [1, 1, 1])
    assert np.allclose(v, [k[2] / (f * c), k[2] / f, k[0]])
    assert c > 1.0 and e < urban.URBAN_BUILT_UP_EXTENT
