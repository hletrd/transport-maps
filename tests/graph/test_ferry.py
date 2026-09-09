"""Ferry crossings as cell-to-cell edges."""

import h3
import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.graph import build, rail
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources.osm import FERRY_SCHEMA

CAL = rail.FerryCalibration(speed_kmh=35.0, terminal_min=30.0)

# Helsinki and Tallinn: a real 80 km crossing, and comfortably distinct cells.
HEL = (60.15, 24.95)
TLL = (59.44, 24.75)


def _links(rows):
    return pl.DataFrame(rows, schema=FERRY_SCHEMA)


def _link(way_id, a, b, name="ferry"):
    return {"way_id": way_id, "from_lat": a[0], "from_lon": a[1],
            "to_lat": b[0], "to_lon": b[1], "name": name}


def _index(points):
    cells = [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo in points]
    cells = list(dict.fromkeys(cells))
    return NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, ())


def test_a_crossing_becomes_a_two_way_edge_with_a_plausible_time():
    idx = _index([HEL, TLL])
    r, c, d = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert len(r) == 2, "a crossing must be traversable both ways"
    assert set(zip(r, c)) == {(0, 1), (1, 0)}
    # ~80 km at 35 km/h plus 30 min terminal: the real sailing is about 2 h.
    assert 100 <= d[0] <= 200
    assert d[0] == pytest.approx(d[1])


def test_a_crossing_inside_one_cell_is_dropped():
    """A self-loop is a zero-length edge Dijkstra could sit on forever."""
    near = (60.15, 24.95), (60.151, 24.951)
    idx = _index([near[0]])
    r, _, _ = build._ferry_edges(idx, _links([_link(1, *near)]), CAL)
    assert len(r) == 0


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


def test_crossings_outside_the_plausible_range_are_dropped():
    idx = _index([HEL, TLL, (10.0, 10.0)])
    absurd = _link(1, (60.15, 24.95), (-40.0, -70.0))   # > 4000 km
    r, _, _ = build._ferry_edges(idx, _links([absurd]), CAL)
    assert len(r) == 0


def test_a_crossing_to_a_cell_outside_the_land_mask_is_dropped():
    idx = _index([HEL])                     # Tallinn's cell is absent
    r, _, _ = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert len(r) == 0


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


def test_a_ferry_between_distant_cells_is_still_kept():
    idx = _index([HEL, TLL])
    r, _, _ = build._ferry_edges(idx, _links([_link(1, HEL, TLL)]), CAL)
    assert len(r) == 2


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
    km_eu = 80.0
    assert d_eu.min() < 60.0 * km_eu / CAL.speed_kmh + CAL.terminal_min + 5, \
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
