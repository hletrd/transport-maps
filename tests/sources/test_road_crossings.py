"""Plain roads across a land-part seam: which are read, and which are kept.

The owner's cases: Daebu-do (the Sihwa seawall), Jido and Apdo were joined to
the mainland by roads that carry no bridge tag where the land part changes,
and read "no route" from every origin. Synthetic cells and a synthetic extract
here; `scripts/check_fixed_links.py` checks the named crossings on the real
index.
"""

import h3
import numpy as np
import osmium
import polars as pl
import pytest
import shapely

from transport_maps import config
from transport_maps.graph import landmass
from transport_maps.sources import fixed_links
from transport_maps.sources import road_crossings as rc

A = h3.latlng_to_cell(60.15, 24.95, config.SOLVE_RES)
RING = sorted(h3.grid_ring(A, 1))
B = RING[0]
# C: a neighbour of A not touching B, on A's land part.
C = next(c for c in RING[1:] if not h3.are_neighbor_cells(c, B))
# W: a neighbour of A off the land mask -- water.
W = next(c for c in RING if c not in (B, C))
# F, F2: land on A's part, far beyond SEAM_RING of anything on another part.
F = sorted(h3.grid_ring(A, 6))[0]
F2 = next(c for c in sorted(h3.grid_ring(F, 1)) if h3.grid_distance(A, c) >= 6)
CELLS = [A, B, C, F, F2]
PARTS = [(1,), (2,), (1,), (1,), (1,)]
WATER = rc.WATER


def test_the_highways_read_are_the_classes_a_span_is_costed_at():
    """Two lists of one thing: a class read here with no fitted speed would
    be dropped by spanning_links, and a class costed there but never read
    could not join anything."""
    assert rc.ROAD_HIGHWAYS == set(landmass.SPAN_ROAD_CLASS)


def test_seams_are_cells_near_another_land_part_and_nowhere_else():
    s = rc.seams(CELLS, PARTS)
    ints = {c: h3.str_to_int(c) for c in CELLS}
    assert ints[A] in s.vicinity and ints[B] in s.vicinity and ints[C] in s.vicinity
    assert h3.str_to_int(W) in s.vicinity, "the water a causeway runs over is read too"
    assert ints[F] not in s.vicinity, "land far from any other part is never read"


def test_a_straddler_is_a_seam_and_a_pole_cell_never_makes_one():
    s = rc.seams([F], [(3, 4)])
    assert h3.str_to_int(F) in s.vicinity, "a cell touching two parts is a seam by itself"
    s = rc.seams([A, B], [(), (1,)])
    assert not s.vicinity, "a cell on no part is no evidence of another part nearby"


# ---- which steps belong to a crossing, on bare arrays -----------------------

def _edges(steps, part):
    a = np.array([x for x, _ in steps]); b = np.array([y for _, y in steps])
    return rc._crossing_edges(a, b, np.array(part)).tolist()


def test_a_step_from_one_part_straight_onto_another_is_a_crossing():
    assert _edges([(0, 1), (1, 2)], [1, 2, 2]) == [True, False]


def test_road_over_water_that_lands_on_two_parts_is_a_crossing_however_it_is_cut():
    """The Sihwa seawall is a dozen ways, none running land to land: its
    steps over water are one stretch, and it lands on two parts."""
    #       land 1 -> water -> water -> water -> land 2
    steps = [(0, 1), (1, 2), (2, 3), (3, 4)]
    assert _edges(steps, [1, WATER, WATER, WATER, 2]) == [True] * 4


def test_road_out_over_water_and_back_to_the_same_part_is_no_crossing():
    """A coastal road on reclaimed land Natural Earth lacks, both ends ashore."""
    steps = [(0, 1), (1, 2), (2, 3)]
    assert _edges(steps, [1, WATER, WATER, 1]) == [False] * 3


def test_two_stretches_over_water_are_judged_apart():
    """Ferry ramps on facing shores: each stretch lands on one part only, and
    nothing joins them, so neither is a crossing."""
    steps = [(0, 1), (2, 3)]
    assert _edges(steps, [1, WATER, WATER, 2]) == [False, False]


def _write(path, nodes, ways):
    w = osmium.SimpleWriter(str(path))
    for nid, (lat, lon) in nodes.items():
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat), tags={}))
    for wid, refs, tags in ways:
        w.add_way(osmium.osm.mutable.Way(id=wid, nodes=refs, tags=tags))
    w.close()


def _hexagon(cell):
    return shapely.Polygon([(lo, la) for la, lo in h3.cell_to_boundary(cell)])


def _land(**parts):
    """LandParts over whole hexagons: part id -> the cells it covers."""
    return rc.LandParts([(int(pid[1:]), shapely.union_all([_hexagon(c) for c in cells]))
                         for pid, cells in parts.items()])


# Part 1 is A, C, F and F2; part 2 is B; W is water. The labels agree.
LAND = _land(p1=[A, C, F, F2], p2=[B])


def test_land_parts_are_read_at_each_point():
    a, b, w = h3.cell_to_latlng(A), h3.cell_to_latlng(B), h3.cell_to_latlng(W)
    assert LAND([a[0], b[0], w[0]], [a[1], b[1], w[1]]).tolist() == [1, 2, WATER]


def test_the_parse_keeps_only_the_roads_that_run_from_one_part_onto_another(tmp_path):
    centre = {c: h3.cell_to_latlng(c) for c in (A, B, C, W, F, F2)}
    nodes = {1: centre[A], 2: centre[B], 3: centre[C], 4: centre[W], 5: centre[F],
             6: centre[F2], 7: centre[A], 8: centre[B], 9: centre[W]}
    primary = {"highway": "primary"}
    _write(tmp_path / "x.osm.pbf", nodes, [
        (10, [1, 2], {**primary, "name": "causeway"}),       # part 1 onto part 2
        (11, [1, 3], primary),                               # within part 1
        (12, [7, 8], {"highway": "footway"}),                # not a road
        (13, [7, 8], {**primary, "ice_road": "yes"}),        # not all year
        (14, [3, 4, 1], {"highway": "residential"}),         # out over water and back
        (15, [5, 6], primary),                               # far from every seam
        (16, [7, 8], {**primary, "route": "ferry"}),         # a sailing
        (17, [7, 9, 8], {**primary, "name": "seawall"}),     # over water onto part 2
    ])
    rows = rc._crossings(tmp_path / "x.osm.pbf", rc.seams(CELLS, PARTS), LAND)
    got = {r["way_id"]: r for r in rows}
    assert set(got) == {10, 17}
    assert got[10]["kind"] == "road" and got[10]["name"] == "causeway"
    assert got[10]["highway"] == "primary", "costed at its class, like a bridge"
    assert len(got[17]["lat"]) == 3, "the stretch over water keeps both its land ends"


def test_a_seawall_cut_into_several_ways_is_read_whole(tmp_path):
    """Judged way by way, no piece runs from land to land and none is kept --
    which is how the second version missed Daebu-do, Jido and Apdo."""
    a, b, w = h3.cell_to_latlng(A), h3.cell_to_latlng(B), h3.cell_to_latlng(W)
    w2 = (w[0] + 0.001, w[1])
    assert h3.latlng_to_cell(*w2, config.SOLVE_RES) == W, "fixture: both wet nodes over water"
    _write(tmp_path / "x.osm.pbf", {1: a, 2: w, 3: w2, 4: b},
           [(20, [1, 2], {"highway": "secondary"}), (21, [2, 3], {"highway": "primary"}),
            (22, [3, 4], {"highway": "secondary"})])
    rows = rc._crossings(tmp_path / "x.osm.pbf", rc.seams(CELLS, PARTS), LAND)
    assert sorted(r["way_id"] for r in rows) == [20, 21, 22]
    assert {r["highway"] for r in rows} == {"primary", "secondary"}, "each piece at its class"


def test_a_road_on_one_part_through_a_cell_labelled_another_crosses_nothing(tmp_path):
    """Bali: a coastal road through a strait cell Natural Earth's coarse coast
    labels Java. The road never leaves Bali; the first version, judging by the
    labels, joined the two islands."""
    a, b = h3.cell_to_latlng(A), h3.cell_to_latlng(B)
    _write(tmp_path / "x.osm.pbf", {1: a, 2: b}, [(10, [1, 2], {"highway": "trunk"})])
    s = rc.seams(CELLS, PARTS)
    assert h3.str_to_int(B) in s.vicinity, "fixture: B is read, and labelled part 2"
    assert rc._crossings(tmp_path / "x.osm.pbf", s, _land(p1=[A, B, C, F, F2])) == []


def test_a_road_is_read_only_inside_the_seams(tmp_path):
    """A node outside the vicinity was never located: its steps are not read."""
    centre = {c: h3.cell_to_latlng(c) for c in (A, B, F)}
    _write(tmp_path / "x.osm.pbf", {1: centre[F], 2: centre[A], 3: centre[B]},
           [(10, [1, 2, 3], {"highway": "trunk"})])
    rows = rc._crossings(tmp_path / "x.osm.pbf", rc.seams(CELLS, PARTS), LAND)
    assert len(rows) == 1
    assert rows[0]["lat"] == pytest.approx([centre[A][0], centre[B][0]], abs=1e-6)


def test_two_crossings_on_one_way_are_two_runs_not_one(tmp_path):
    """Out onto part 2, along it, and back: the stretch along part 2 joins
    nothing and must not be carried, or the two crossings would read as one
    road straight across."""
    a, b = h3.cell_to_latlng(A), h3.cell_to_latlng(B)
    b2 = (b[0] + 0.0005, b[1])                     # 55 m on, still in B
    assert h3.latlng_to_cell(*b2, config.SOLVE_RES) == B, "fixture"
    _write(tmp_path / "x.osm.pbf", {1: a, 2: b, 3: b2, 4: a},
           [(10, [1, 2, 3, 4], {"highway": "trunk"})])
    rows = rc._crossings(tmp_path / "x.osm.pbf", rc.seams(CELLS, PARTS), LAND)
    assert [len(r["lat"]) for r in rows] == [2, 2]


def test_a_step_across_the_antimeridian_is_not_read(tmp_path):
    """Interpolated, it would run the long way round the globe."""
    x, y = (-16.8, 179.995), (-16.8, -179.995)
    cx, cy = (h3.latlng_to_cell(*p, config.SOLVE_RES) for p in (x, y))
    assert cx != cy and h3.are_neighbor_cells(cx, cy), "fixture: neighbours across it"
    land = rc.LandParts([(1, shapely.box(179.9, -17.0, 180.0, -16.6)),
                         (2, shapely.box(-180.0, -17.0, -179.9, -16.6))])
    _write(tmp_path / "x.osm.pbf", {1: x, 2: y}, [(10, [1, 2], {"highway": "trunk"})])
    assert rc._crossings(tmp_path / "x.osm.pbf", rc.seams([cx, cy], [(1,), (2,)]), land) == []


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE", tmp_path)
    (tmp_path / "osm").mkdir()
    monkeypatch.setattr(rc, "_landmass_key", lambda: "land_landmasses_r6_test.parquet")
    return tmp_path


def test_one_missing_region_returns_none_without_parsing(cache, monkeypatch):
    for region in fixed_links.REGIONS[1:]:
        (cache / "osm" / f"{region}.osm.pbf").write_bytes(b"not parsed")
    monkeypatch.setattr(rc, "_crossings", lambda *a: pytest.fail("parsed with coverage incomplete"))
    assert rc.road_crossings() is None


def test_a_complete_set_of_caches_is_used_without_the_raw_extracts(cache):
    for i, region in enumerate(fixed_links.REGIONS):
        pl.DataFrame([{"way_id": i, "kind": "road", "highway": "primary", "name": region,
                       "lat": [0.0, 0.1], "lon": [0.0, 0.1]}], schema=fixed_links.SCHEMA
                     ).write_parquet(rc._cache_path(region, "k"))
    df = rc.road_crossings()
    assert df is not None and sorted(df["name"].to_list()) == sorted(fixed_links.REGIONS)


def test_the_parse_is_keyed_on_the_land_parts_it_was_drawn_from(monkeypatch):
    """The seams move with the coast: a parse drawn from other land parts is a
    miss, not a silent reuse."""
    monkeypatch.setattr(rc, "_landmass_key", lambda: "land_landmasses_r6_aaaa.parquet")
    before = rc._cache_path("asia", "k")
    monkeypatch.setattr(rc, "_landmass_key", lambda: "land_landmasses_r6_bbbb.parquet")
    assert rc._cache_path("asia", "k") != before
    assert before.name.startswith("road_crossings_asia_")
