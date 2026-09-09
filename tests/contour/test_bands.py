from typing import ClassVar

import h3
import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon

from transport_maps import config, validate
from transport_maps.contour import bands
from transport_maps.graph import build, nodes
from transport_maps.solve import dijkstra


def test_band_boundaries_are_inclusive_of_the_lower_band():
    # Expressed against the configured first edge, not a literal: the ladder
    # has changed once already (120 min -> 30 min) and will again.
    e0 = config.BAND_EDGES_MIN[0]
    assert bands.band_of(0.0) == 0
    assert bands.band_of(e0 - 1.0) == 0
    assert bands.band_of(float(e0)) == 0      # exactly on the edge is still the first band
    assert bands.band_of(e0 + 1.0) == 1


def test_beyond_the_last_edge_is_the_open_ended_band():
    last = len(config.BAND_EDGES_MIN)
    assert bands.band_of(config.BAND_EDGES_MIN[-1] + 1) == last
    assert bands.band_of(float("inf")) == bands.UNREACHABLE_BAND


def test_feature_collection_has_one_feature_per_occupied_band():
    class FakeIndex:
        cells: ClassVar[list[str]] = ["8530e08ffffffff", "8530e087fffffff"]
        n_cells = 2
    fc = bands.band_feature_collection(FakeIndex(), np.array([10.0, 5000.0]))
    assert fc["type"] == "FeatureCollection"
    expected = {bands.band_of(10.0), bands.band_of(5000.0)}
    assert expected == {0, len(config.BAND_EDGES_MIN)}, "fixture no longer spans first and open band"
    # Every level of detail carries one feature per occupied band.
    for lod in range(len(bands.LODS)):
        feats = bands.lod_features(fc, lod)
        assert len(feats) == 2, f"level {lod}"
        assert {f["properties"]["band"] for f in feats} == expected
    assert len(fc["features"]) == 2 * len(bands.LODS)


def test_bands_are_emitted_in_ascending_order():
    """Bands are drawn as stacked fills on the frontend; emitting the slow
    bands before the fast ones would paint the fast bands underneath."""
    class FakeIndex:
        cells: ClassVar[list[str]] = ["8530e08ffffffff", "8530e087fffffff", "852f5a37fffffff"]
        n_cells = 3
    # Insertion order (slow, fast, middle) deliberately does not match ascending
    # band order, so a reversed or unsorted emission order would show up here.
    times = [3000.0, 10.0, 1000.0]
    fc = bands.band_feature_collection(FakeIndex(), np.array(times))
    expected = sorted(bands.band_of(t) for t in times)
    assert len(set(expected)) == 3, "fixture times must land in three distinct bands"
    for lod in range(len(bands.LODS)):
        assert [f["properties"]["band"] for f in bands.lod_features(fc, lod)] == expected


def test_max_minutes_matches_the_band_edge_and_is_none_past_the_last_edge():
    class FakeIndex:
        cells: ClassVar[list[str]] = ["8530e08ffffffff", "8530e087fffffff", "852f5a37fffffff"]
        n_cells = 3
    # a near band, a middle band, and past the last edge (5000 min -> open band)
    fc = bands.band_feature_collection(FakeIndex(), np.array([10.0, 1000.0, 5000.0]))
    by_band = {f["properties"]["band"]: f["properties"]["max_minutes"] for f in fc["features"]}
    near, mid = bands.band_of(10.0), bands.band_of(1000.0)
    assert by_band[near] == config.BAND_EDGES_MIN[near]
    assert by_band[mid] == config.BAND_EDGES_MIN[mid]
    assert by_band[len(config.BAND_EDGES_MIN)] is None


def test_cell_minutes_shorter_than_the_cell_universe_is_rejected():
    class FakeIndex:
        cells: ClassVar[list[str]] = ["8530e08ffffffff", "8530e087fffffff"]
        n_cells = 2
    with pytest.raises(ValueError, match="cell_minutes shorter than the cell universe"):
        bands.band_feature_collection(FakeIndex(), np.array([10.0]))


# A real H3 res-5 cell near Fiji whose boundary straddles +/-180. Confirmed by
# search: max(lons) - min(lons) > 180 for its raw h3.cell_to_boundary output.
ANTIMERIDIAN_CELL = "859b400bfffffff"


def test_antimeridian_cell_naively_read_is_invalid_and_globe_spanning():
    """Pins the bug this fix exists for: building a polygon straight from the
    raw H3 boundary (no unwrapping) makes a wrapping cell's ring invalid and
    inflates its area by three orders of magnitude -- 0.02 deg^2 of real land
    read as 27+ deg^2, which is what made isochrone bands appear to overlap.
    """
    assert bands._crosses_antimeridian(ANTIMERIDIAN_CELL)
    boundary = h3.cell_to_boundary(ANTIMERIDIAN_CELL)
    naive = Polygon([(lon, lat) for lat, lon in boundary])
    assert not naive.is_valid
    assert naive.area == pytest.approx(27.316365837306222, rel=1e-9)


def test_antimeridian_cell_splits_into_a_valid_geometry_at_its_true_area():
    """The fix: dissolving the same cell must produce a VALID geometry whose
    area matches its true unwrapped size, not the globe-spanning naive one.
    """
    # Tests the splitter directly: _dissolve now also clips bands to the real
    # coastline, which legitimately trims an ocean-side cell like this one, so
    # going through it would no longer isolate the antimeridian behaviour.
    parts = bands._split_at_antimeridian(ANTIMERIDIAN_CELL)
    geometry = shapely.union_all(parts)
    assert geometry.is_valid
    assert geometry.area == pytest.approx(0.020117758657720624, rel=1e-9)
    # Nowhere near the 27+ deg^2 the naive (buggy) reading produced.
    assert geometry.area < 1.0


@pytest.fixture(scope="module")
def seoul_band_feature_collection():
    idx = nodes.build_index()
    csr = build.build_graph(idx)
    source = dijkstra.origin_node(idx, 37.5665, 126.9780)
    minutes = dijkstra.solve_from(csr, source)
    return bands.band_feature_collection(idx, minutes[: idx.n_cells])


def test_real_multi_band_solve_passes_the_cover_gate(seoul_band_feature_collection):
    """A real Seoul solve -- far bands with hundreds of globe-scattered
    components, antimeridian-crossing cells, one-cell-wide bands everywhere --
    must leave no hex vertex unpainted. This is the gate the build runs.
    """
    from transport_maps.contour import grid
    assert len(bands.lod_features(seoul_band_feature_collection, 0)) > 5  # the far bands too
    cells, nb, ring = grid.universe(nodes.build_index().cells)
    validate.check_bands_cover(cells, nb, ring, seoul_band_feature_collection)  # must not raise


def test_no_gap_opens_between_bands_however_they_meet():
    """Random bands make every hex vertex a junction of up to three bands and
    every boundary a jump of several bands at once -- the worst case for the
    old per-band smoothing, which opened a hole at each such junction.
    """
    from transport_maps.contour import grid
    centre = h3.latlng_to_cell(37.5, 127.0, 5)
    cells = sorted(h3.grid_disk(centre, 6))
    rng = np.random.default_rng(1)
    edges = np.asarray(config.BAND_EDGES_MIN, dtype=float)
    band = rng.integers(0, 9, size=len(cells))
    minutes = np.where(band == 0, 1.0, edges[np.maximum(band - 1, 0)] + 1.0)

    class Idx:
        pass
    idx = Idx(); idx.cells = cells; idx.n_cells = len(cells)
    fc = bands.band_feature_collection(idx, minutes)
    assert len(bands.lod_features(fc, 0)) >= 8
    universe, nb, ring = grid.universe(cells)
    validate.check_bands_cover(universe, nb, ring, fc, samples=len(universe))  # every vertex


def test_each_level_of_detail_is_bounded_to_its_zooms():
    """The copies must not overlap in zoom, or a tile would carry two of them."""
    zooms = [(l["minzoom"], l["maxzoom"] if l["maxzoom"] is not None else 99) for l in bands.LODS]
    covered = sorted(zooms)
    assert covered[0][0] == 0
    for (a0, a1), (b0, b1) in zip(covered, covered[1:]):
        assert a1 + 1 == b0, f"levels {a0}-{a1} and {b0}-{b1} leave a gap or overlap"


def test_the_sea_fringe_is_painted_with_the_fastest_neighbour():
    """A water-centroid cell next to land is painted, and takes the FASTER of
    two land neighbours. Without the fringe a single hexagon's smoothed
    polygon cannot contain a neighbour's centroid at all.
    """
    from shapely.geometry import Point, shape
    a = h3.latlng_to_cell(37.5, 127.0, 5)
    b = h3.grid_ring(a, 1)[0]
    shared = [c for c in h3.grid_ring(a, 1) if h3.are_neighbor_cells(c, b)]
    assert shared, "fixture: no common neighbour"

    class Idx:
        cells = [a, b]
        n_cells = 2
    fc = bands.band_feature_collection(Idx(), np.array([1.0, 3000.0]))
    fine = bands.lod_features(fc, 0)
    fast = next(shape(f["geometry"]) for f in fine if f["properties"]["band"] == 0)
    la, lo = h3.cell_to_latlng(shared[0])
    assert fast.contains(Point(lo, la)), "common fringe cell not painted with the faster band"
    # A ring-2 cell of `a` that is not also a neighbour of `b` -- otherwise it
    # is b's legitimate fringe.
    far = next(c for c in h3.grid_ring(a, 2) if c not in h3.grid_disk(b, 1))
    la, lo = h3.cell_to_latlng(far)
    assert not any(shape(f["geometry"]).contains(Point(lo, la)) for f in fine), \
        "ring 2 must stay unpainted at the fine level: its fringe is one cell"


def test_unreachable_land_is_emitted_rather_than_dropped():
    """Antarctica is in the land mask but no scheduled service reaches it.

    Dropping unreachable cells left it with no polygon at all, so it rendered
    as open ocean -- the mask had the continent, the map did not.
    """
    import numpy as np

    from transport_maps.contour import bands

    class Idx:
        cells = [h3.latlng_to_cell(-77.8, 166.7, 5),      # Ross Island
                 h3.latlng_to_cell(37.5, 127.0, 5)]       # Seoul
        n_cells = 2

    fc = bands.band_feature_collection(Idx(), np.array([np.inf, 30.0]))
    band_ids = [f["properties"]["band"] for f in fc["features"]]
    assert bands.UNREACHABLE_BAND in band_ids, "unreachable land emitted no feature"

    unreachable = next(f for f in fc["features"]
                       if f["properties"]["band"] == bands.UNREACHABLE_BAND)
    assert unreachable["properties"]["max_minutes"] is None, \
        "unreachable band indexed BAND_EDGES_MIN from the end"


def _turn_angles(geom):
    """Absolute heading change at each boundary vertex, in degrees."""
    import numpy as np
    import shapely

    out = []
    parts = shapely.get_parts(geom) if geom.geom_type == "MultiPolygon" else [geom]
    for poly in parts:
        if poly.geom_type != "Polygon":
            continue
        p = np.asarray(poly.exterior.coords)[:-1]
        if len(p) < 3:
            continue
        v = np.roll(p, -1, axis=0) - p
        a = np.arctan2(v[:, 1], v[:, 0])
        out.append(np.abs(np.degrees((np.roll(a, -1) - a + np.pi) % (2 * np.pi) - np.pi)))
    return np.concatenate(out) if out else np.array([])


def test_smoothing_actually_removes_the_hexagon_signature():
    """A hex tiling turns 60 degrees at every corner; smoothing must reduce that.

    This is not a formality. An earlier simplification tolerance (0.013) pulled
    the cut corners straight back onto the vertices they came from and left the
    boundary MORE hexagonal than the raw union -- 16.5% of turns near 60 deg
    against 10.4% -- while every other test still passed, because the code did
    run and did produce valid geometry. Only the shape was wrong.
    """
    import numpy as np
    import shapely
    from shapely.ops import unary_union

    from transport_maps.contour import bands

    centre = h3.latlng_to_cell(37.5, 127.0, 5)
    cells = list(h3.grid_disk(centre, 6))
    raw = shapely.make_valid(unary_union(
        [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in cells]))
    smoothed = bands._smooth(raw)

    def near60(g):
        t = _turn_angles(g)
        return float(((t > 45) & (t < 75)).mean())

    raw_share, smooth_share = near60(raw), near60(smoothed)
    assert smooth_share < raw_share * 0.8, (
        f"smoothing left {smooth_share:.1%} of turns near 60 deg against "
        f"{raw_share:.1%} raw -- the hexagon corners survived"
    )
    assert np.median(_turn_angles(smoothed)) < np.median(_turn_angles(raw))
