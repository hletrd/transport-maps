"""Plain roads across a land-part seam: which are read, and which are kept.

The owner's cases: Daebu-do (the Sihwa seawall), Jido and Apdo were joined to
the mainland by roads that carry no bridge tag where the land part changes,
and read "no route" from every origin. Synthetic cells and a synthetic extract
here; `scripts/check_fixed_links.py` checks the named crossings on the real
index.
"""

import h3
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
    assert s.parts[ints[A]] == {1} and h3.str_to_int(W) not in s.parts


def test_a_straddler_is_a_seam_and_a_pole_cell_never_makes_one():
    s = rc.seams([F], [(3, 4)])
    assert h3.str_to_int(F) in s.vicinity, "a cell touching two parts is a seam by itself"
    s = rc.seams([A, B], [(), (1,)])
    assert not s.vicinity, "a cell on no part is no evidence of another part nearby"


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
    assert LAND([a[0], b[0], w[0]], [a[1], b[1], w[1]]) == [{1}, {2}, frozenset()]


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


def test_a_road_on_one_part_through_a_cell_labelled_another_crosses_nothing(tmp_path):
    """Bali: a coastal road through a strait cell Natural Earth's coarse coast
    labels Java. The cell labels flag the step; the road never leaves Bali,
    and the first version, judging by the labels, joined the two islands."""
    a, b = h3.cell_to_latlng(A), h3.cell_to_latlng(B)
    _write(tmp_path / "x.osm.pbf", {1: a, 2: b}, [(10, [1, 2], {"highway": "trunk"})])
    s = rc.seams(CELLS, PARTS)
    assert rc._step_matters(a, b, s), "fixture: the labels must flag the step"
    assert rc._crossings(tmp_path / "x.osm.pbf", s, _land(p1=[A, B, C, F, F2])) == []


def test_a_stretch_is_cut_where_the_road_leaves_the_seams(tmp_path):
    """A node outside the vicinity was never located: the stretch ends there."""
    centre = {c: h3.cell_to_latlng(c) for c in (A, B, F)}
    _write(tmp_path / "x.osm.pbf", {1: centre[F], 2: centre[A], 3: centre[B]},
           [(10, [1, 2, 3], {"highway": "trunk"})])
    rows = rc._crossings(tmp_path / "x.osm.pbf", rc.seams(CELLS, PARTS), LAND)
    assert len(rows) == 1
    assert rows[0]["lat"] == pytest.approx([centre[A][0], centre[B][0]], abs=1e-6)


def test_a_stretch_ends_at_a_step_across_the_antimeridian():
    """Interpolated, that step would run the long way round the globe."""
    assert rc._stretches([(-16.8, 179.9), (-16.8, -179.9)]) == []
    assert rc._stretches([(0.0, 1.0), None, (0.0, 2.0), (0.0, 2.1)]) == [[(0.0, 2.0), (0.0, 2.1)]]


def test_two_crossings_on_one_way_are_two_stretches_not_one(tmp_path):
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


def test_a_crossing_inside_one_fine_cell_joins_nothing_and_is_dropped(tmp_path):
    """The fixed-link rule: a road from part 3 onto part 4 whose two nodes
    share a fine cell cannot join two graph cells."""
    f = h3.cell_to_latlng(F)
    f2 = (f[0] + 0.0001, f[1])
    assert h3.latlng_to_cell(*f, fixed_links.KEEP_RES) == h3.latlng_to_cell(*f2, fixed_links.KEEP_RES)
    mid = f[0] + 0.00005
    split = rc.LandParts([(3, shapely.box(f[1] - 1, f[0] - 1, f[1] + 1, mid)),
                          (4, shapely.box(f[1] - 1, mid, f[1] + 1, f[0] + 1))])
    assert split([f[0], f2[0]], [f[1], f2[1]]) == [{3}, {4}], "fixture: a real crossing"
    _write(tmp_path / "x.osm.pbf", {1: f, 2: f2}, [(10, [1, 2], {"highway": "trunk"})])
    assert rc._crossings(tmp_path / "x.osm.pbf", rc.seams([F], [(3, 4)]), split) == []


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
