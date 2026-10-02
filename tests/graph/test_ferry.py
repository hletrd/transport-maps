"""Ferry crossings as cell-to-cell edges."""

import h3
import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.graph import build, ferry, ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources.osm import FERRY_SCHEMA

# The shipped calibration, not a copy of its numbers: these tests are about the
# model's SHAPE, and pinning the constants here would let calibration.toml and
# the graph drift apart with every test still green.
CAL = ferry.load_ferry_calibration()

# Helsinki and Tallinn: a real 80 km crossing, and comfortably distinct cells.
HEL = (60.15, 24.95)
TLL = (59.44, 24.75)


#: The fixture crossing's own great-circle length, measured rather than
#: remembered: the edge weight is a function of it and a hardcoded 80.0 was
#: half a minute out.
_KM_HEL_TLL = float(ground.haversine_km(np.array([list(HEL)]), np.array([list(TLL)]))[0])


def _links(rows):
    return pl.DataFrame(rows, schema=FERRY_SCHEMA)


def _link(way_id, a, b, name="ferry", **tags):
    """A parsed ferry way. `tags` carries duration_min / interval_min /
    service_fraction, all None by default -- which is what OSM gives for most
    crossings and is the case the fitted prior exists to answer."""
    return {"way_id": way_id, "from_lat": a[0], "from_lon": a[1],
            "to_lat": b[0], "to_lon": b[1], "name": name,
            "duration_min": tags.get("duration_min"),
            "interval_min": tags.get("interval_min"),
            "service_fraction": tags.get("service_fraction")}


def _index(points):
    cells = [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo in points]
    cells = list(dict.fromkeys(cells))
    return NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, ())


@pytest.mark.needs_inputs
def test_a_crossing_becomes_a_two_way_edge_with_a_plausible_time():
    idx = _index([HEL, TLL])
    r, c, d = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert len(r) == 2, "a crossing must be traversable both ways"
    assert set(zip(r, c)) == {(0, 1), (1, 0)}
    assert d[0] == pytest.approx(d[1])
    # The edge is sail + terminal + expected wait, and the bound is derived
    # from the model rather than from a remembered number, so it moves with a
    # recalibration instead of going red on one.
    #
    # The old assertion here was `100 <= d[0] <= 200`, which admitted anything
    # from 27 to 69 km/h with anywhere between zero and double the terminal
    # time -- wide enough that deleting the terminal term entirely left it
    # green (proven by mutation in the cycle-8 review).
    km = _KM_HEL_TLL
    sail = CAL.berth_min + 60.0 * km / CAL.speed_kmh
    wait = ferry.expected_wait_min(ferry.sailings_per_week(km, CAL))
    assert d[0] == pytest.approx(sail + wait + CAL.terminal_min, rel=0.02)
    # ...and each of the three components is actually in there. A crossing this
    # long cannot cost less than the time afloat plus the boarding.
    assert d[0] > sail + CAL.terminal_min, "the expected wait is not charged"
    assert d[0] > wait + CAL.terminal_min, "the sailing time is not charged"
    assert d[0] > sail + wait, "the terminal time is not charged"


@pytest.mark.needs_inputs
def test_a_crossing_inside_one_cell_is_dropped():
    """A self-loop is a positive-weight edge Dijkstra could sit on.

    The two points must be at least MIN_FERRY_KM apart or the LENGTH filter
    rejects the link one branch earlier and this test never reaches the guard
    it is named after. The old fixture used points 124 m apart -- 0.124 km
    against a 1.0 km floor -- so deleting `u == v` left it green.

    `build_graph`'s own `(data <= 0).any()` check cannot catch this either: a
    3 km self-loop has a perfectly positive weight.
    """
    a = (60.15, 24.95)
    b = (60.175, 24.95)                       # ~2.8 km north: past the 1 km floor
    km = ground.haversine_km(np.array([list(a)]), np.array([list(b)]))[0]
    assert km >= 1.0, "fixture: the length filter would reject this before the guard"
    assert h3.latlng_to_cell(*a, config.SOLVE_RES) == h3.latlng_to_cell(*b, config.SOLVE_RES), \
        "fixture: both points must land in ONE cell for this to be a self-loop"
    idx = _index([a])
    r, _, _ = build._ferry_edges(idx, _links([_link(1, a, b)]), CAL)
    assert len(r) == 0


@pytest.mark.needs_inputs
def test_two_ways_joining_the_same_cells_collapse_to_the_quickest():
    """build_graph refuses duplicate (row, col) pairs, so this must not emit
    them -- and the survivor must be the faster crossing, not the sum."""
    idx = _index([HEL, TLL])
    direct = _link(1, HEL, TLL)
    detour = _link(2, HEL, (59.40, 25.30))     # same cells, longer sail
    r, c, d = build._ferry_edges(idx, _links([direct, detour]), CAL)
    assert len(r) == len(set(zip(r, c))), "emitted a duplicate (row, col) pair"
    solo, _, solo_d = build._ferry_edges(idx, _links([direct]), CAL)
    assert d.min() == pytest.approx(solo_d.min())


@pytest.mark.needs_inputs
def test_crossings_outside_the_plausible_range_are_dropped():
    idx = _index([HEL, TLL, (10.0, 10.0)])
    absurd = _link(1, (60.15, 24.95), (-40.0, -70.0))   # > 4000 km
    r, _, _ = build._ferry_edges(idx, _links([absurd]), CAL)
    assert len(r) == 0


@pytest.mark.needs_inputs
def test_a_crossing_to_a_cell_outside_the_land_mask_is_dropped():
    idx = _index([HEL])                     # Tallinn's cell is absent
    r, _, _ = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert len(r) == 0


@pytest.mark.needs_inputs
def test_a_ferry_between_adjacent_cells_is_skipped():
    """The ground network already joins neighbouring cells.

    Emitting the crossing too duplicates a (row, col) pair, and coo_matrix SUMS
    duplicates -- so the shared edge would cost the road time PLUS the sailing
    instead of the cheaper of the two. build_graph refuses such a list outright,
    which is how this was caught: the first full rail build aborted on it.
    """
    centre = h3.latlng_to_cell(60.15, 24.95, config.SOLVE_RES)
    neighbour = [c for c in h3.grid_disk(centre, 1) if c != centre][0]
    a = h3.cell_to_latlng(centre)
    b = h3.cell_to_latlng(neighbour)
    idx = _index([a, b])
    links = _links([_link(1, a, b, "river ferry")])
    r, _, _ = build._ferry_edges(idx, links, CAL)
    assert len(r) == 0


@pytest.mark.needs_inputs
def test_a_ferry_between_distant_cells_is_still_kept():
    idx = _index([HEL, TLL])
    r, _, _ = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert len(r) == 2


@pytest.mark.needs_inputs
def test_a_ferry_into_a_sealed_country_is_dropped():
    """An OSM ferry way across the Yellow Sea carried travellers from Seoul into
    North Korea with every land border sealed: ferry edges never consulted the
    closed-border list. Now they do."""
    # Inland so both cells resolve by centroid; the rule under test is the
    # border, not the shoreline, and _ferry_edges only needs a non-adjacent
    # pair within range.
    south = (37.57, 126.98)           # Seoul, KOR
    north = (37.97, 126.55)           # Kaesong, PRK
    idx = _index([south, north])
    from transport_maps.sources import countries
    codes = countries.cell_country(idx.cells)
    assert set(codes) == {"KOR", "PRK"}, codes
    r, _, _ = build._ferry_edges(idx, _links([_link(1, south, north, "Yellow Sea")]), CAL)
    assert len(r) == 0, "a ferry crossed the sealed inter-Korean border"


@pytest.mark.needs_inputs
def test_the_off_mask_drops_are_counted_and_reported():
    """1,872 in-window crossings (12.4%) are lost this way on the real extracts
    -- Sanya-Yongshu at 1,034 km, Donghae-Vladivostok at 570 km -- and the
    previous code dropped them with a bare `continue`: no count, no log, no
    bound, and no gate able to see an island going missing."""
    idx = _index([HEL])                       # Tallinn's cell is absent
    dropped = {}
    build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL, dropped)
    assert dropped.get("endpoint off the land mask") == 1, dropped


@pytest.mark.needs_inputs
def test_too_many_off_mask_drops_refuse_the_build():
    """A land-mask regression must be loud. Above the bound the build stops.

    The bound needs MIN_FERRY_LINKS_TO_BOUND crossings before it applies, for
    the same reason `_air_edges` bounds a FRACTION and not a count: two missing
    fixtures in a unit test are not a regression, and 12.4% of 15,080 real
    crossings are already lost this way."""
    idx = _index([HEL])
    n = build.MIN_FERRY_LINKS_TO_BOUND
    links = _links([_link(i, HEL, TLL) for i in range(n)])
    with pytest.raises(RuntimeError, match="not in the land mask"):
        build._ferry_edges(idx, links, CAL)


@pytest.mark.needs_inputs
def test_a_few_off_mask_drops_do_not_refuse_the_build():
    idx = _index([HEL])
    links = _links([_link(i, HEL, TLL) for i in range(build.MIN_FERRY_LINKS_TO_BOUND - 1)])
    r, _, _ = build._ferry_edges(idx, links, CAL)      # must not raise
    assert len(r) == 0


@pytest.mark.needs_inputs
def test_a_rare_crossing_costs_far_more_than_a_frequent_one_of_the_same_length():
    """The whole point of the cycle. Two crossings between the same pair of
    cells, identical in every way but their timetable: the one that sails once
    a week must cost days more than the one that sails hourly.

    Before this model both cost `60*km/speed + 30` exactly, so this test could
    not have been written -- the two numbers were equal."""
    idx = _index([HEL, TLL])
    hourly = _links([_link(1, HEL, TLL, interval_min=60.0)])
    weekly = _links([_link(1, HEL, TLL, interval_min=7 * 24 * 60.0)])
    _, _, d_hourly = build._ferry_edges(idx, hourly, CAL)
    _, _, d_weekly = build._ferry_edges(idx, weekly, CAL)
    # Half of a weekly headway is 84 h; half of an hourly one is 30 min.
    assert d_weekly.min() - d_hourly.min() == pytest.approx(0.5 * (7 * 24 * 60 - 60), rel=0.01)


@pytest.mark.needs_inputs
def test_a_tagged_interval_beats_the_prior():
    idx = _index([HEL, TLL])
    _, _, tagged = build._ferry_edges(
        idx, _links([_link(1, HEL, TLL, interval_min=120.0)]), CAL)
    _, _, modelled = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert tagged.min() != pytest.approx(modelled.min()), \
        "the OSM interval tag was parsed and then ignored"
    assert tagged.min() == pytest.approx(
        ferry.sailing_min(_KM_HEL_TLL, CAL) + CAL.terminal_min + 60, rel=0.03)


@pytest.mark.needs_inputs
def test_a_tagged_duration_beats_the_speed_model():
    idx = _index([HEL, TLL])
    _, _, tagged = build._ferry_edges(
        idx, _links([_link(1, HEL, TLL, duration_min=125.0)]), CAL)
    _, _, modelled = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    # The real Helsinki-Tallinn sailing is about 2 h; the model says ~3 h.
    assert tagged.min() < modelled.min()
    assert tagged.min() - modelled.min() == pytest.approx(
        125.0 - ferry.sailing_min(_KM_HEL_TLL, CAL), rel=0.01)


@pytest.mark.needs_inputs
def test_seasonal_service_is_charged_a_longer_wait():
    """A summer-only ferry met in February is genuinely not there. The map has
    no date, so the frequency is scaled to a year average."""
    idx = _index([HEL, TLL])
    _, _, year = build._ferry_edges(
        idx, _links([_link(1, HEL, TLL, interval_min=120.0)]), CAL)
    _, _, summer = build._ferry_edges(
        idx, _links([_link(1, HEL, TLL, interval_min=120.0, service_fraction=0.25)]), CAL)
    # A quarter of the year is a quarter of the sailings, so four times the wait.
    assert summer.min() - year.min() == pytest.approx(0.5 * (480 - 120), rel=0.01)


@pytest.mark.needs_inputs
def test_a_ferry_between_immigration_zones_pays_the_crossing():
    """Helsinki-Tallinn is Schengen-internal: no charge. Singapore-Batam is not."""
    sg, batam = (1.27, 103.85), (1.13, 104.05)
    idx = _index([sg, batam])
    _, _, d_sg = build._ferry_edges(idx, _links([_link(1, sg, batam)]), CAL)
    idx2 = _index([HEL, TLL])
    _, _, d_eu = build._ferry_edges(idx2, _links([_link(2, HEL, TLL)]), CAL)
    # Both are ~20-80 km; the Singapore one carries the crossing on top.
    from transport_maps.graph import ground
    assert d_sg.min() > ground._land_border_min(), "SG->ID ferry paid no crossing"
    from transport_maps.graph import ground as _g
    assert d_eu.min() < ferry.crossing_min(_KM_HEL_TLL, CAL) + _g._land_border_min(), \
        "a Schengen-internal ferry was charged a crossing"


def _mixed_index(centre_latlng):
    """The tracer's fixture: one base cell split into its seven fine children
    amid six unsplit neighbours, the shape of every harbour at the edge of a
    built-up area."""
    from transport_maps.graph import refine
    centre = h3.latlng_to_cell(*centre_latlng, config.SOLVE_RES)
    base = sorted(h3.grid_disk(centre, 1))
    cells, base_index, fine = refine.refine(base, np.array([c == centre for c in base]))
    idx = NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, (),
                    base_cells=base, base_index=base_index, fine=fine, _split=frozenset({centre}))
    neighbour = next(c for c in base if c != centre)
    kids = [c for c, f in zip(cells, fine) if f]

    def km(k):
        return h3.great_circle_distance(h3.cell_to_latlng(k), h3.cell_to_latlng(neighbour), unit="km")
    return idx, neighbour, min(kids, key=km), max(kids, key=km)


def _no_air(monkeypatch):
    empty = (np.array([], dtype=np.int64), np.array([], dtype=np.int64), np.array([], dtype=np.float64))
    monkeypatch.setattr(build, "_air_edges", lambda *a, **k: empty)
    monkeypatch.setattr(build, "_access_edges", lambda idx: empty)
    monkeypatch.setattr(build, "_transfer_edges", lambda idx: empty)


@pytest.mark.needs_inputs
def test_a_ferry_between_a_fine_cell_and_its_adjacent_base_cell_is_skipped(monkeypatch):
    """Mixed resolution. ground.hex_edges joins an edge child of the split cell
    to the unsplit base cell beyond its ring, so a short ferry between the two
    duplicates that (row, col) pair and build_graph refuses the whole graph.
    Adjacency judged by grid_disk at one resolution cannot see the pair at
    all: a res-6 id is never in a res-7 cell's disk.
    """
    from transport_maps.graph import ground
    idx, neighbour, edge_kid, _ = _mixed_index(HEL)
    u, v = idx.cell_index(edge_kid), idx.cell_index(neighbour)
    r, c, _ = ground.hex_edges(idx)
    assert (u, v) in set(zip(r.tolist(), c.tolist())), "fixture: the ground network does not join the pair"

    links = _links([_link(1, h3.cell_to_latlng(edge_kid), h3.cell_to_latlng(neighbour), "harbour ferry")])
    fr, _, _ = build._ferry_edges(idx, links, CAL)
    assert len(fr) == 0, "the ferry duplicated a cross-resolution ground edge"
    _no_air(monkeypatch)
    build.build_graph(idx, ferry_links=links)   # must not refuse a duplicate pair


@pytest.mark.needs_inputs
def test_a_ferry_the_ground_network_does_not_duplicate_is_kept_on_the_mixed_grid(monkeypatch):
    """The far child of the split cell does not touch the neighbouring base
    cell, so hex_edges never joins them and a ferry between them is a real
    crossing. Comparing base parents instead called them adjacent and dropped
    it -- a harbour ferry a few kilometres long, silently gone."""
    from transport_maps.graph import ground
    idx, neighbour, _, far_kid = _mixed_index(HEL)
    u, v = idx.cell_index(far_kid), idx.cell_index(neighbour)
    r, c, _ = ground.hex_edges(idx)
    assert (u, v) not in set(zip(r.tolist(), c.tolist())), "fixture: the ground network joins the pair"

    links = _links([_link(1, h3.cell_to_latlng(far_kid), h3.cell_to_latlng(neighbour), "harbour ferry")])
    fr, fc, _ = build._ferry_edges(idx, links, CAL)
    assert set(zip(fr, fc)) == {(u, v), (v, u)}, "a crossing the ground network does not cover was dropped"
    _no_air(monkeypatch)
    build.build_graph(idx, ferry_links=links)   # both edge sets, no duplicate pair


@pytest.mark.needs_inputs
def test_the_edge_capacity_guard_names_the_problem_instead_of_an_index_error(monkeypatch):
    """The preallocated edge arrays were sized from one measurement with no
    check; an overflow was a bare IndexError hours into a build."""
    from transport_maps.contour import grid as grid_mod
    from transport_maps.graph import ground
    centre = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    cells = [centre, *h3.grid_ring(centre, 1)]           # the centre alone has six edges
    idx = NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, ())
    monkeypatch.setattr(ground, "EDGE_SLOTS_PER_CELL", 1)
    with pytest.raises(RuntimeError, match="edge capacity exceeded"):
        ground.hex_edges(idx)
    monkeypatch.setattr(grid_mod, "EDGE_SLOTS_PER_CELL", 1)
    with pytest.raises(RuntimeError, match="edge capacity exceeded"):
        grid_mod.native_edges(idx)
