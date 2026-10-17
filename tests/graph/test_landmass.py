"""Adjacent land cells that open water separates, and everything that must agree on it.

The owner's case: Saipan and Tinian are separate islands 8 km apart, their
cells were H3 neighbours, and the graph drove across the sea in 7.1 minutes of
"major road". Every test here is on synthetic cells, so the rule is pinned
without the 70 GB of extracts; `scripts/check_fixed_links.py` checks named
real bridges and ferry-only crossings against the built index.
"""

from typing import ClassVar

import h3
import numpy as np
import polars as pl
import pytest
import shapely

from transport_maps import config
from transport_maps.emit import modes
from transport_maps.graph import build, ferry, ground, landmass, refine
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import fixed_links, landmask
from transport_maps.sources.osm import FERRY_SCHEMA

A = h3.latlng_to_cell(60.15, 24.95, config.SOLVE_RES)
RING = sorted(c for c in h3.grid_ring(A, 1))
B = RING[0]
# C: a second neighbour of A that does NOT touch B, so the A-C pair is judged
# on its own and never through B.
C = next(c for c in RING[1:] if not h3.are_neighbor_cells(c, B))


def _severed(parts, *, split=(), linked=()):
    cells = [A, B, C]
    graph_cells = []
    for c in cells:
        graph_cells += h3.cell_to_children(c, config.FINE_RES) if c in split else [c]
    pos = {c: i for i, c in enumerate(graph_cells)}
    out = landmass.severed_pairs(cells, parts, set(split), pos, set(linked))
    return out, pos


def test_neighbours_on_different_landmasses_with_no_link_are_severed_both_ways():
    out, pos = _severed([(1,), (2,), (1,)])
    assert (pos[A], pos[B]) in out and (pos[B], pos[A]) in out
    assert (pos[A], pos[C]) not in out, "A and C share landmass 1"


def test_a_cell_straddling_both_shores_joins_them():
    """The stated resolution limit: a strait narrower than a cell stays joined."""
    out, _ = _severed([(1, 2), (2,), (1,)])
    assert not out


def test_a_bridge_between_the_two_cells_keeps_them_joined():
    _, pos = _severed([(1,), (2,), (1,)])
    out, _ = _severed([(1,), (2,), (1,)], linked={(pos[A], pos[B]), (pos[B], pos[A])})
    assert not out


@pytest.mark.parametrize("parts", [[(), (2,), (1,)], [(1,), (), (2,)]],
                         ids=["first-of-pair", "second-of-pair"])
def test_a_cell_that_touches_no_land_part_is_never_severed(parts):
    """The South Pole cells are added by id and touch no polygon: they carry
    no evidence of water, so they must not be cut off from the continent.

    Both positions: the guard is written once for each cell of the pair, and a
    fixture with the empty tuple on one side only leaves the other unguarded.
    """
    out, pos = _severed(parts)
    assert (pos[A], pos[B]) not in out


def test_a_split_cell_is_severed_only_where_its_children_actually_meet_the_other_shore():
    out, pos = _severed([(1,), (2,), (1,)], split={A})
    kids = h3.cell_to_children(A, config.FINE_RES)
    touching = [k for k in kids if refine.ground_adjacent(k, B)]
    assert touching and len(touching) < len(kids), "fixture: some children must not touch B"
    for k in kids:
        assert ((pos[k], pos[B]) in out) == (k in touching), k
    assert not any((pos[a], pos[b]) in out for a in kids for b in kids), \
        "children of one base cell share its landmass"


def test_a_bridge_protects_only_the_cells_it_actually_passes_between():
    """A bridge is one crossing point, not permission to cross the whole shore."""
    _, pos = _severed([(1,), (2,), (1,)], split={A})
    kids = [k for k in h3.cell_to_children(A, config.FINE_RES) if refine.ground_adjacent(k, B)]
    bridged, other = kids[0], kids[1]
    out, pos = _severed([(1,), (2,), (1,)], split={A},
                        linked={(pos[bridged], pos[B]), (pos[B], pos[bridged])})
    assert (pos[bridged], pos[B]) not in out
    assert (pos[other], pos[B]) in out


def _links(*spans):
    return pl.DataFrame([{"way_id": i, "kind": "highway", "highway": "primary", "name": "",
                          "lat": [p[0] for p in s], "lon": [p[1] for p in s]}
                         for i, s in enumerate(spans)], schema=fixed_links.SCHEMA)


def _at(cells):
    pos = {c: i for i, c in enumerate(cells)}
    return lambda lat, lon: pos.get(h3.latlng_to_cell(lat, lon, config.SOLVE_RES))


def test_a_link_between_two_cells_links_them_both_ways():
    got = landmass.linked_pairs(_links([h3.cell_to_latlng(A), h3.cell_to_latlng(B)]), _at([A, B]))
    assert got == {(0, 1), (1, 0)}


def test_a_link_that_crosses_a_water_cell_links_nothing_across_the_gap():
    """A and the cell two rings out are not neighbours; the cell between is
    off the land mask, so the span leaves land on the way."""
    far = next(c for c in h3.grid_ring(A, 2))
    got = landmass.linked_pairs(_links([h3.cell_to_latlng(A), h3.cell_to_latlng(far)]),
                                _at([A, far]))
    assert got == set()


def test_a_segment_across_the_antimeridian_is_not_interpolated_the_long_way_round():
    """Every cell counts as land here, so the long way round WOULD link things.

    The first version looked up only the two end cells. Deleting the guard then
    left it green: the samples interpolated through longitude 0 all missed the
    lookup, the chain broke on its own, and the result was empty either way.
    """
    pos: dict[str, int] = {}

    def everywhere(lat, lon):
        return pos.setdefault(h3.latlng_to_cell(lat, lon, config.SOLVE_RES), len(pos))

    got = landmass.linked_pairs(_links([(-16.8, 179.99), (-16.8, -179.99)]), everywhere)
    assert got == set()


def _index(cells, severed=frozenset()):
    return NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, (),
                     severed=frozenset(severed))


def test_ground_joined_is_adjacency_less_the_severed_pairs():
    assert refine.ground_joined(_index([A, B]), 0, 1)
    assert not refine.ground_joined(_index([A, B], {(0, 1), (1, 0)}), 0, 1)


@pytest.mark.needs_inputs
def test_hex_edges_builds_no_road_across_a_severed_pair(monkeypatch):
    idx = _index([A, B, C], {(0, 1), (1, 0)})
    monkeypatch.setattr(ground, "cell_speed_kmh", lambda _idx, **_kw: np.full(3, 50.0))
    r, c, _ = ground.hex_edges(idx)
    edges = set(zip(r.tolist(), c.tolist()))
    assert (0, 1) not in edges and (1, 0) not in edges
    assert (0, 2) in edges and (2, 0) in edges, "an unsevered neighbour is still joined"


@pytest.mark.needs_inputs
def test_the_real_ferry_across_a_severed_strait_is_kept_not_dropped_as_a_duplicate():
    """The second half of the defect: with the phantom road in place, the
    crossing's real ferry was thrown away as a duplicate of it."""
    la, lo = h3.cell_to_latlng(A)
    lb, lob = h3.cell_to_latlng(B)
    links = pl.DataFrame([{"way_id": 1, "from_lat": la, "from_lon": lo, "to_lat": lb,
                           "to_lon": lob, "name": "strait", "duration_min": None,
                           "interval_min": None, "service_fraction": None}], schema=FERRY_SCHEMA)
    cal = ferry.load_ferry_calibration()

    joined: dict[str, int] = {}
    r, _, _ = build._ferry_edges(_index([A, B]), links, cal, dropped_out=joined)
    assert len(r) == 0 and joined.get("duplicates a ground edge") == 1, \
        "fixture: between joined neighbours the ferry IS a duplicate"

    severed: dict[str, int] = {}
    r, c, _ = build._ferry_edges(_index([A, B], {(0, 1), (1, 0)}), links, cal, dropped_out=severed)
    assert set(zip(r.tolist(), c.tolist())) == {(0, 1), (1, 0)}
    assert not severed.get("duplicates a ground edge")


def test_a_hop_across_a_severed_pair_is_booked_as_ferry_not_road():
    class Idx:
        n_cells = 3
        airports: ClassVar[list[str]] = []
        stations = ()
        cells: ClassVar[list[str]] = [A, B, C]
        severed = frozenset({(0, 1), (1, 0)})

    minutes = np.array([0.0, 30.0, 12.0])
    prev = np.array([-9999, 0, 0])
    acc = modes.mode_minutes_per_node(Idx(), minutes, prev, cell_class=np.array([2, 2, 2]))
    ferry_ch, road_ch = modes.CHANNELS.index("ferry"), modes.CHANNELS.index("major road")
    assert acc[1][ferry_ch] == 30.0 and acc[1][road_ch] == 0.0, "the severed hop is a sailing"
    assert acc[2][road_ch] == 12.0, "the unsevered neighbour is still road"


# ---- landmask: which parts each cell touches ----------------------------------

def _square(lat, lon, d=0.3):
    return shapely.box(lon - d, lat - d, lon + d, lat + d)


@pytest.mark.needs_inputs
def test_antarctic_wedges_are_one_landmass_and_the_pole_cell_is_a_wildcard(monkeypatch, hermetic_build):
    """_land_parts cuts Antarctica into wedges so H3 can polyfill it. Numbered
    apart, the continent would be severed along every wedge seam."""
    helsinki = _square(60.15, 24.95)
    tallinn = _square(59.44, 24.75)
    wedge_w, wedge_e = shapely.box(9.0, -75.3, 10.0, -74.7), shapely.box(10.0, -75.3, 11.0, -74.7)
    parts = [helsinki, tallinn, wedge_w, wedge_e]
    cells = set()
    for p in parts:
        cells |= set(h3.h3shape_to_cells_experimental(h3.geo_to_h3shape(p), config.SOLVE_RES,
                                                        contain="overlap"))
    pole = h3.latlng_to_cell(-90.0, 0.0, config.SOLVE_RES)
    ordered = sorted(cells | {pole})
    monkeypatch.setattr(landmask, "_land_parts", lambda: parts)
    monkeypatch.setattr(landmask, "land_cells", lambda res: ordered)

    got = dict(zip(ordered, landmask.land_cell_landmasses(config.SOLVE_RES)))
    hel = h3.latlng_to_cell(60.15, 24.95, config.SOLVE_RES)
    tll = h3.latlng_to_cell(59.44, 24.75, config.SOLVE_RES)
    ant_w = h3.latlng_to_cell(-75.0, 9.5, config.SOLVE_RES)
    ant_e = h3.latlng_to_cell(-75.0, 10.5, config.SOLVE_RES)
    assert got[hel] == (0,) and got[tll] == (1,), "separate landmasses keep separate ids"
    assert got[ant_w] == got[ant_e] == (landmask.ANTARCTICA_LANDMASS,)
    assert got[pole] == ()


@pytest.fixture(autouse=True)
def _no_real_fixed_links(monkeypatch):
    """Nothing here may reach the real extracts, whatever the cache holds."""
    monkeypatch.setattr(fixed_links, "_links", lambda path: pytest.fail(f"parsed {path}"))


# ---- B2: a base cell straddling a strait, judged child by child --------------

def _straddle_fixture():
    """A split base cell A, half of it on landmass 1 (west) and half on 2 (east).

    Two land parts are built as boxes meeting a gap along A's centre meridian,
    so some of A's seven children touch only the west box, some only the east,
    and the centre one -- which the gap runs through -- touches neither.
    """
    la, lo = h3.cell_to_latlng(A)
    west = shapely.box(lo - 1.0, la - 1.0, lo - 0.004, la + 1.0)
    east = shapely.box(lo + 0.004, la - 1.0, lo + 1.0, la + 1.0)
    polygons = {1: west, 2: east}
    return polygons


def test_a_straddling_cells_children_are_assigned_to_their_own_shore():
    polygons = _straddle_fixture()
    got = landmass.fine_cell_parts([A], [(1, 2)], {A}, polygons)
    kids = h3.cell_to_children(A, config.FINE_RES)
    assert set(got) == set(kids)
    lo = h3.cell_to_latlng(A)[1]
    for k in kids:
        if k == h3.cell_to_center_child(A, config.FINE_RES):
            continue
        klo = h3.cell_to_latlng(k)[1]
        want = 1 if klo < lo else 2
        assert want in got[k], (k, klo, got[k])


def test_a_water_child_takes_the_nearest_shore_not_both():
    """Left inheriting both shores it would be a free bridge across the strait."""
    la, lo = h3.cell_to_latlng(A)
    # The gap is now wide enough that the centre child touches neither box.
    polygons = {1: shapely.box(lo - 1.0, la - 1.0, lo - 0.02, la + 1.0),
                2: shapely.box(lo + 0.03, la - 1.0, lo + 1.0, la + 1.0)}
    centre = h3.cell_to_center_child(A, config.FINE_RES)
    got = landmass.fine_cell_parts([A], [(1, 2)], {A}, polygons)
    assert got[centre] == (1,), "nearer to the west shore, so west -- and only west"


def test_siblings_on_opposite_shores_are_severed_from_each_other():
    polygons = _straddle_fixture()
    fine = landmass.fine_cell_parts([A], [(1, 2)], {A}, polygons)
    kids = h3.cell_to_children(A, config.FINE_RES)
    pos = {c: i for i, c in enumerate(kids)}
    out = landmass.severed_pairs([A], [(1, 2)], {A}, pos, set(), fine_parts=fine)
    cross = [(a, b) for a in kids for b in kids
             if a != b and h3.are_neighbor_cells(a, b) and not set(fine[a]) & set(fine[b])]
    assert cross, "fixture: some adjacent siblings must sit on opposite shores"
    for a, b in cross:
        assert (pos[a], pos[b]) in out
    same = [(a, b) for a in kids for b in kids
            if a != b and h3.are_neighbor_cells(a, b) and set(fine[a]) & set(fine[b])]
    for a, b in same:
        assert (pos[a], pos[b]) not in out, "siblings on one shore stay joined"


def _wide_strait():
    """A's centre child in open water between a west shore (1) and an east
    shore (2): the water child `fine_cell_parts` gives the nearer, west."""
    la, lo = h3.cell_to_latlng(A)
    polygons = {1: shapely.box(lo - 1.0, la - 1.0, lo - 0.02, la + 1.0),
                2: shapely.box(lo + 0.03, la - 1.0, lo + 1.0, la + 1.0)}
    water: set[str] = set()
    fine = landmass.fine_cell_parts([A], [(1, 2)], {A}, polygons, water=water)
    kids = h3.cell_to_children(A, config.FINE_RES)
    return fine, water, kids, {c: i for i, c in enumerate(kids)}


def test_a_water_child_is_given_a_landing_on_each_shore():
    fine, water, kids, pos = _wide_strait()
    centre = h3.cell_to_center_child(A, config.FINE_RES)
    assert water == {centre} and fine[centre] == (1,)
    got = landmass.shore_landings(fine, water, pos)
    assert set(got) == {pos[centre]}
    shores = {fine[kids[i]] for i in got[pos[centre]]}
    assert shores == {(1,), (2,)}, "one landing per shore, the guessed one and the other"
    la, lo = h3.cell_to_latlng(centre)
    for i in got[pos[centre]]:
        part = fine[kids[i]]
        rivals = [k for k in kids if k not in water and fine[k] == part]
        dist = lambda k: landmass._haversine_km(la, lo, *h3.cell_to_latlng(k))  # noqa: E731
        assert dist(kids[i]) == min(dist(k) for k in rivals), "the nearest of that shore"


def test_a_ferry_landing_in_a_water_child_crosses_to_the_shore_the_coast_missed():
    """Rupat (2026-10-06): its pier lies in water Natural Earth gives to
    Sumatra, so the Dumai ferry joined Sumatra to Sumatra -- dropped as a
    duplicate of the road -- and the island read "no route" from everywhere.

    Mutation performed and reverted: the landings dropped from both loops in
    build._ferry_edges, leaving `(u,)` and `(v,)` -> red.
    """
    fine, water, kids, pos = _wide_strait()
    centre = h3.cell_to_center_child(A, config.FINE_RES)
    lo = h3.cell_to_latlng(A)[1]
    west = next(k for k in kids if k not in water and fine[k] == (1,)
                and h3.are_neighbor_cells(k, centre) and h3.cell_to_latlng(k)[1] < lo)
    severed = landmass.severed_pairs([A], [(1, 2)], {A}, pos, set(), fine_parts=fine)
    landings = landmass.shore_landings(fine, water, pos)
    (wla, wlo), (cla, clo) = h3.cell_to_latlng(west), h3.cell_to_latlng(centre)
    links = pl.DataFrame([{"way_id": 1, "from_lat": wla, "from_lon": wlo, "to_lat": cla,
                           "to_lon": clo, "name": "Dumai - Tanjung Kapal (Rupat)",
                           "duration_min": 30.0, "interval_min": None,
                           "service_fraction": None}], schema=FERRY_SCHEMA)
    rules = (np.array(["IDN"] * 7), np.array(["I"] * 7), 45.0, lambda a, b: False)
    cal = ferry.load_ferry_calibration()
    east = {pos[k] for k in kids if fine[k] == (2,)}

    def run(landings):
        idx = NodeIndex(kids, [], pos, {}, {}, (), _split=frozenset({A}), severed=severed,
                        landings=landings)
        dropped: dict[str, int] = {}
        r, c, _ = build._ferry_edges(idx, links, cal, dropped_out=dropped, rules=rules)
        return set(zip(r.tolist(), c.tolist())), dropped

    edges, _ = run(landings)
    assert any(b in east for a, b in edges if a == pos[west]), "the crossing to the east shore"
    edges, dropped = run({})
    assert not any(b in east for _, b in edges), "control: without landings, no crossing"
    assert dropped == {"duplicates a ground edge": 1}


def test_without_child_parts_a_straddler_still_joins_both_shores():
    """The control: the previous behaviour, and the limit this closes."""
    kids = h3.cell_to_children(A, config.FINE_RES)
    pos = {c: i for i, c in enumerate(kids)}
    assert not landmass.severed_pairs([A], [(1, 2)], {A}, pos, set())


# ---- B3: road links whose span crosses a water cell ---------------------------

FAR = next(c for c in h3.grid_ring(A, 2))


def _span_links(highway, kind="highway", far=FAR):
    return pl.DataFrame([{"way_id": 1, "kind": kind, "highway": highway, "name": "",
                          "lat": [h3.cell_to_latlng(A)[0], h3.cell_to_latlng(far)[0]],
                          "lon": [h3.cell_to_latlng(A)[1], h3.cell_to_latlng(far)[1]]}],
                        schema=fixed_links.SCHEMA)


def test_a_road_bridge_over_a_water_cell_becomes_an_edge_costed_at_its_class():
    speeds = ground.SPEED_BY_ROAD_CLASS_KMH
    got = landmass.spanning_links(_span_links("motorway"), _at([A, FAR]), speeds)
    assert set(got) == {(0, 1), (1, 0)}
    km = landmass._haversine_km(*h3.cell_to_latlng(A), *h3.cell_to_latlng(FAR))
    # Charged from where the link leaves A to where it enters FAR, so at most
    # the whole centre-to-centre length and at least most of it.
    mw = speeds[ground.MOTORWAY_CLASS]           # a motorway bridge: the OSM motorway class
    assert 60 * 0.5 * km / mw < got[(0, 1)] <= 60 * km / mw + 1e-9


@pytest.mark.parametrize("highway,kind", [("footway", "highway"), ("cycleway", "highway"),
                                          ("", "railway")])
def test_footbridges_and_railways_do_not_become_road_spans(highway, kind):
    got = landmass.spanning_links(_span_links(highway, kind), _at([A, FAR]),
                                  ground.SPEED_BY_ROAD_CLASS_KMH)
    assert got == {}


def test_a_span_longer_than_any_real_crossing_is_refused(monkeypatch):
    monkeypatch.setattr(landmass, "MAX_SPAN_KM", 1.0)
    got = landmass.spanning_links(_span_links("motorway"), _at([A, FAR]),
                                  ground.SPEED_BY_ROAD_CLASS_KMH)
    assert got == {}


def _index_spans(cells, spans):
    return NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, (), spans=spans)


def test_a_span_is_joined_and_becomes_a_graph_edge(monkeypatch):
    idx = _index_spans([A, FAR], {(0, 1): 9.0, (1, 0): 9.0})
    assert refine.ground_joined(idx, 0, 1)
    assert not refine.ground_joined(_index_spans([A, FAR], {}), 0, 1), "control"
    monkeypatch.setattr(build, "_border_rules",
                        lambda _idx: (np.array(["DNK", "DNK"]), np.array(["S", "S"]), 45.0,
                                      lambda a, b: False))
    r, c, d = build._span_edges(idx)
    assert set(zip(r.tolist(), c.tolist())) == {(0, 1), (1, 0)} and d.tolist() == [9.0, 9.0]


def test_a_span_across_a_closed_border_is_cut_and_a_zone_change_charged(monkeypatch):
    idx = _index_spans([A, FAR], {(0, 1): 9.0, (1, 0): 9.0})
    monkeypatch.setattr(build, "_border_rules",
                        lambda _idx: (np.array(["KOR", "PRK"]), np.array(["K", "P"]), 45.0,
                                      lambda a, b: {a, b} == {"KOR", "PRK"}))
    r, _, _ = build._span_edges(idx)
    assert len(r) == 0
    monkeypatch.setattr(build, "_border_rules",
                        lambda _idx: (np.array(["DNK", "SWE"]), np.array(["S", "X"]), 45.0,
                                      lambda a, b: False))
    _, _, d = build._span_edges(idx)
    assert d.tolist() == [54.0, 54.0]


def test_a_hop_along_a_span_is_booked_as_road_not_ferry():
    class Idx:
        n_cells = 2
        airports: ClassVar[list[str]] = []
        stations = ()
        cells: ClassVar[list[str]] = [A, FAR]
        spans: ClassVar[dict] = {(0, 1): 9.0, (1, 0): 9.0}

    acc = modes.mode_minutes_per_node(Idx(), np.array([0.0, 9.0]), np.array([-9999, 0]),
                                      cell_class=np.array([1, 1]))
    assert acc[1][modes.CHANNELS.index("highway")] == 9.0
    assert acc[1][modes.CHANNELS.index("ferry")] == 0.0


def test_a_straddlers_children_are_judged_against_a_neighbour_that_shares_one_of_its_parts():
    """The shortcut that dismisses any base pair sharing a part must NOT apply
    when either base is a refined straddler.

    A straddles parts 1 and 2; its western neighbour W is on part 2 alone. The
    base pair shares part 2, so the old shortcut skipped it -- and A's western
    children, on part 1, stayed joined to W across the strait. Found by
    mutation: with only a single base cell in the fixture, reverting to the old
    shortcut left every test green.
    """
    polygons = _straddle_fixture()
    lo = h3.cell_to_latlng(A)[1]
    west = min((c for c in h3.grid_ring(A, 1)), key=lambda c: h3.cell_to_latlng(c)[1])
    fine = landmass.fine_cell_parts([A], [(1, 2)], {A}, polygons)
    kids = h3.cell_to_children(A, config.FINE_RES)
    cells = kids + [west]
    pos = {c: i for i, c in enumerate(cells)}
    out = landmass.severed_pairs([A, west], [(1, 2), (2,)], {A}, pos, set(), fine_parts=fine)
    facing = [k for k in kids if refine.ground_adjacent(k, west) and fine[k] == (1,)]
    assert facing, "fixture: some western child must be on part 1 and touch W"
    assert h3.cell_to_latlng(west)[1] < lo
    for k in facing:
        assert (pos[k], pos[west]) in out


def test_build_graph_includes_the_span_edges(monkeypatch):
    """_span_edges being right is worth nothing if build_graph never calls it.

    Every other part is stubbed to nothing, so the only edges in the matrix are
    the ones the spans produce.
    """
    empty = (np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64), np.zeros(0))
    monkeypatch.setattr(ground, "hex_edges", lambda _idx, **kw: empty)
    for name in ("_air_edges", "_access_edges", "_transfer_edges"):
        monkeypatch.setattr(build, name, lambda *a, **k: empty)
    monkeypatch.setattr(build, "_border_rules",
                        lambda _idx, *a: (np.array(["DNK", "DNK"]), np.array(["S", "S"]), 45.0,
                                      lambda a, b: False))
    idx = _index_spans([A, FAR], {(0, 1): 9.0, (1, 0): 9.0})
    csr = build.build_graph(idx)
    assert csr[0, 1] == 9.0 and csr[1, 0] == 9.0


def test_a_crossing_split_into_ways_that_meet_over_water_is_one_span():
    """OSM splits a long crossing into deck, tunnel and viaduct ways that share
    a node OVER THE WATER. Taken way by way none runs land to land, and the
    first version found no span for the Great Belt, the Oresund, the
    Confederation Bridge or the Busan-Geoje link -- measured on the real index,
    not caught by the single-way fixtures above."""
    a, far = h3.cell_to_latlng(A), h3.cell_to_latlng(FAR)
    mid = ((a[0] + far[0]) / 2, (a[1] + far[1]) / 2)
    links = pl.DataFrame([
        {"way_id": 1, "kind": "highway", "highway": "motorway", "name": "deck",
         "lat": [a[0], mid[0]], "lon": [a[1], mid[1]]},
        {"way_id": 2, "kind": "highway", "highway": "primary", "name": "tunnel",
         "lat": [mid[0], far[0]], "lon": [mid[1], far[1]]},
    ], schema=fixed_links.SCHEMA)
    speeds = ground.SPEED_BY_ROAD_CLASS_KMH
    got = landmass.spanning_links(links, _at([A, FAR]), speeds)
    assert set(got) == {(0, 1), (1, 0)}
    # Each half costed at its own class: slower than all-motorway, faster than all-primary.
    km = landmass._haversine_km(*a, *far)
    mw = speeds[ground.MOTORWAY_CLASS]
    assert 60 * km / mw * 0.5 < got[(0, 1)] < 60 * km / speeds[2]


def test_a_motorway_span_is_the_motorway_class():
    """landmass cannot import graph/ground (a cycle through graph/nodes), so
    the class is a literal there; it must be ground's.

    Mutation performed and reverted: SPAN_ROAD_CLASS["motorway"] back to 1 ->
    RED."""
    assert landmass.SPAN_ROAD_CLASS["motorway"] == ground.MOTORWAY_CLASS
    assert landmass.SPAN_ROAD_CLASS["motorway_link"] == ground.MOTORWAY_CLASS


def test_two_ways_meeting_on_land_are_not_a_span():
    """A shared node on land joins nothing across water."""
    a, b = h3.cell_to_latlng(A), h3.cell_to_latlng(B)
    links = pl.DataFrame([
        {"way_id": 1, "kind": "highway", "highway": "motorway", "name": "",
         "lat": [a[0], b[0]], "lon": [a[1], b[1]]},
    ], schema=fixed_links.SCHEMA)
    assert landmass.spanning_links(links, _at([A, B]), ground.SPEED_BY_ROAD_CLASS_KMH) == {}


def test_a_coastal_node_does_not_turn_its_land_neighbour_into_a_span():
    """A node on the shore touching water on one side (a pier, a way ending in
    the sea) and another land cell on the other: the step onto land is not a
    crossing. Found by mutation -- the land-only fixture above never starts a
    search, so dropping this guard left it green."""
    a, b, far = h3.cell_to_latlng(A), h3.cell_to_latlng(B), h3.cell_to_latlng(FAR)
    seaward = ((a[0] + far[0]) / 2, (a[1] + far[1]) / 2)
    links = pl.DataFrame([
        {"way_id": 1, "kind": "highway", "highway": "motorway", "name": "",
         "lat": [a[0], b[0]], "lon": [a[1], b[1]]},
        {"way_id": 2, "kind": "highway", "highway": "motorway", "name": "pier",
         "lat": [a[0], seaward[0]], "lon": [a[1], seaward[1]]},
    ], schema=fixed_links.SCHEMA)
    assert landmass.spanning_links(links, _at([A, B]), ground.SPEED_BY_ROAD_CLASS_KMH) == {}


def test_a_span_between_grid_neighbours_is_a_protected_adjacency_not_an_edge():
    """As an edge it would duplicate the ground edge between them, and
    build_graph refuses a duplicate pair -- the build would stop at the graph."""
    cells = [A, B, FAR]
    spans, linked = landmass.split_spans({(0, 1): 5.0, (1, 0): 5.0, (0, 2): 9.0, (2, 0): 9.0},
                                         set(), cells)
    assert spans == {(0, 2): 9.0, (2, 0): 9.0}
    assert linked == {(0, 1), (1, 0)}


# ---- dead ends over water: islets and short shores the land mask lacks ------

def _way(wid, highway, pts):
    return {"way_id": wid, "kind": "highway", "highway": highway, "name": "",
            "lat": [p[0] for p in pts], "lon": [p[1] for p in pts]}


def _between(p, q, t):
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


FAR3 = next(c for c in h3.grid_ring(A, 3))


def test_two_major_road_dead_ends_near_each_other_are_one_crossing_over_an_islet():
    """Sprogo, the Great Belt's midpoint island, is not on the land mask and its
    road is not a bridge: the East and West Bridges each dead-end over "water",
    3.2 km apart, and the crossing did not exist.

    Mutation performed and reverted: landmass._rank ordering the motorway
    class (6) by its number, below local roads -> RED."""
    a, far = h3.cell_to_latlng(A), h3.cell_to_latlng(FAR3)
    e1, e2 = _between(a, far, 0.45), _between(a, far, 0.55)      # the islet
    links = pl.DataFrame([_way(1, "motorway", [a, e1]), _way(2, "motorway", [e2, far])],
                         schema=fixed_links.SCHEMA)
    assert landmass._haversine_km(*e1, *e2) < landmass.MAX_ISLET_KM, "fixture"
    got = landmass.spanning_links(links, _at([A, FAR3]), ground.SPEED_BY_ROAD_CLASS_KMH)
    assert set(got) == {(0, 1), (1, 0)}


FAR6 = next(c for c in h3.grid_ring(A, 6))


@pytest.mark.parametrize("highway,gap,far_cell", [("service", 0.1, FAR3), ("motorway", 0.6, FAR6)],
                         ids=["a-service-road-is-never-continued", "too-far-apart"])
def test_dead_ends_that_are_not_one_crossing_stay_apart(highway, gap, far_cell):
    """Both ends genuinely out over the water. The first "too far apart"
    fixture put them inside the land cells, so neither was a dead end at all
    and removing the distance cap stayed green."""
    a, far = h3.cell_to_latlng(A), h3.cell_to_latlng(far_cell)
    lo_, hi_ = 0.5 - gap / 2, 0.5 + gap / 2
    ends = (_between(a, far, lo_), _between(a, far, hi_))
    links = pl.DataFrame([_way(1, highway, [a, ends[0]]), _way(2, highway, [ends[1], far])],
                         schema=fixed_links.SCHEMA)
    at = _at([A, far_cell])
    assert at(*ends[0]) is None and at(*ends[1]) is None, "fixture: both ends over water"
    if highway == "motorway":
        assert landmass._haversine_km(*ends[0], *ends[1]) > landmass.MAX_ISLET_KM, "fixture"
    got = landmass.spanning_links(links, at, ground.SPEED_BY_ROAD_CLASS_KMH)
    assert got == {}


def test_a_major_road_dead_end_one_cell_short_of_shore_makes_landfall():
    """The Confederation Bridge's New Brunswick end falls in a cell the coarse
    coast calls water, one ring short of land."""
    a, far = h3.cell_to_latlng(A), h3.cell_to_latlng(FAR)
    ring = h3.grid_ring(FAR, 1)
    shore = next(c for c in ring if not h3.are_neighbor_cells(c, A) and c != A)
    # The bridge runs from A to FAR, and FAR itself is NOT land -- only `shore`,
    # a neighbour of FAR, is.
    links = pl.DataFrame([_way(1, "trunk", [a, far])], schema=fixed_links.SCHEMA)
    got = landmass.spanning_links(links, _at([A, shore]), ground.SPEED_BY_ROAD_CLASS_KMH)
    assert set(got) == {(0, 1), (1, 0)}


# ---- A16: plain roads across a seam (sources/road_crossings) -----------------

def _road(wid, highway, pts):
    return {**_way(wid, highway, pts), "kind": "road"}


def test_a_plain_road_over_water_is_a_span_as_a_bridge_is():
    """The Sihwa seawall: 12.7 km of primary road over cells the land mask
    lacks, with no bridge tag on it. Read as a bridge would be."""
    links = pl.DataFrame([_road(1, "primary", [h3.cell_to_latlng(A), h3.cell_to_latlng(FAR)])],
                         schema=fixed_links.SCHEMA)
    got = landmass.spanning_links(links, _at([A, FAR]), ground.SPEED_BY_ROAD_CLASS_KMH)
    assert set(got) == {(0, 1), (1, 0)}


def test_a_plain_road_dead_ending_over_water_is_not_continued():
    """The islet rule joins two bridge ends that stop over water. Two plain
    roads that stop over water a few kilometres apart are two quays or two
    ferry ramps on facing shores, and joining them would build the road the
    ferry exists because there is none of."""
    a, far = h3.cell_to_latlng(A), h3.cell_to_latlng(FAR3)
    e1, e2 = _between(a, far, 0.45), _between(a, far, 0.55)
    at = _at([A, FAR3])
    assert at(*e1) is None and at(*e2) is None, "fixture: both ends over water"
    bridge = pl.DataFrame([_way(1, "motorway", [a, e1]), _way(2, "motorway", [e2, far])],
                          schema=fixed_links.SCHEMA)
    assert landmass.spanning_links(bridge, at, ground.SPEED_BY_ROAD_CLASS_KMH), \
        "control: as bridges the two ends ARE one crossing over an islet"
    roads = pl.DataFrame([_road(1, "motorway", [a, e1]), _road(2, "motorway", [e2, far])],
                         schema=fixed_links.SCHEMA)
    assert landmass.spanning_links(roads, at, ground.SPEED_BY_ROAD_CLASS_KMH) == {}


def test_a_road_stretch_touching_a_bridge_end_does_not_stop_it_being_continued():
    """The King Fahd Causeway: bridge decks between islets, the road across
    each islet a plain road that itself stops over "water" the coarse coast
    does not have. With that road counted, a bridge end looked live, was not
    continued, and Bahrain -- joined before road stretches were read -- was
    cut (2026-10-04)."""
    a, far = h3.cell_to_latlng(A), h3.cell_to_latlng(FAR3)
    e1, e2 = _between(a, far, 0.45), _between(a, far, 0.55)
    on_islet = _between(a, far, 0.47)
    at = _at([A, FAR3])
    assert at(*on_islet) is None, "fixture: the islet road ends over water too"
    links = pl.DataFrame([_way(1, "motorway", [a, e1]), _way(2, "motorway", [e2, far]),
                          _road(3, "primary", [e1, on_islet])], schema=fixed_links.SCHEMA)
    got = landmass.spanning_links(links, at, ground.SPEED_BY_ROAD_CLASS_KMH)
    assert set(got) == {(0, 1), (1, 0)}


def test_two_stretches_of_one_road_way_do_not_share_samples():
    """sources/road_crossings can give one way several stretches. Keyed by way
    id, the k-th sample of each was one vertex, and two stretches that each
    stop over water joined across it."""
    a, far = h3.cell_to_latlng(A), h3.cell_to_latlng(FAR3)
    links = pl.DataFrame([_road(7, "primary", [a, _between(a, far, 0.4)]),
                          _road(7, "primary", [_between(a, far, 0.6), far])],
                         schema=fixed_links.SCHEMA)
    assert landmass.spanning_links(links, _at([A, FAR3]), ground.SPEED_BY_ROAD_CLASS_KMH) == {}


def test_a_road_crossing_keeps_a_pair_joined_as_a_bridge_does(monkeypatch):
    """Through nodes._severed, which is what the build calls: the road rows
    must reach the severing at all."""
    from transport_maps.graph import nodes
    from transport_maps.sources import road_crossings

    cells = [A, B]
    pos = {c: i for i, c in enumerate(cells)}
    monkeypatch.setattr(landmask, "land_cell_landmasses", lambda res: [(1,), (2,)])
    monkeypatch.setattr(landmask, "_land_parts", lambda: [])
    monkeypatch.setattr(fixed_links, "fixed_links",
                        lambda **k: pl.DataFrame([], schema=fixed_links.SCHEMA))
    seawall = pl.DataFrame([_road(1, "primary", [h3.cell_to_latlng(A), h3.cell_to_latlng(B)])],
                           schema=fixed_links.SCHEMA)

    def cell_at(lat, lon):
        return h3.latlng_to_cell(lat, lon, config.SOLVE_RES)

    monkeypatch.setattr(road_crossings, "road_crossings", lambda **k: None)
    severed, _, _ = nodes._severed(cells, set(), pos, cell_at)
    assert (0, 1) in severed, "control: without the road the two parts are cut"
    monkeypatch.setattr(road_crossings, "road_crossings", lambda **k: seawall)
    severed, _, _ = nodes._severed(cells, set(), pos, cell_at)
    assert not severed


def test_a_ferry_under_the_length_floor_is_kept_where_it_is_the_only_way_across():
    """Sangtaedo to Jungtaedo is 0.85 km, under MIN_FERRY_KM, and the first hop
    of the only line on to Hataedo and Gageodo. The floor stands for "a river
    crossing the road already makes"; across a severed pair it is not one."""
    ca, cb = h3.cell_to_latlng(A), h3.cell_to_latlng(B)
    p, q = _between(ca, cb, 0.47), _between(ca, cb, 0.53)
    assert h3.latlng_to_cell(*p, config.SOLVE_RES) == A and h3.latlng_to_cell(*q, config.SOLVE_RES) == B
    assert landmass._haversine_km(*p, *q) < ferry.MIN_FERRY_KM, "fixture: under the floor"
    links = pl.DataFrame([{"way_id": 1, "from_lat": p[0], "from_lon": p[1], "to_lat": q[0],
                           "to_lon": q[1], "name": "Sangtaedo - Jungtaedo", "duration_min": None,
                           "interval_min": None, "service_fraction": None}], schema=FERRY_SCHEMA)
    rules = (np.array(["KOR", "KOR"]), np.array(["K", "K"]), 45.0, lambda a, b: False)
    cal = ferry.load_ferry_calibration()

    dropped: dict[str, int] = {}
    r, c, _ = build._ferry_edges(_index([A, B], {(0, 1), (1, 0)}), links, cal,
                                 dropped_out=dropped, rules=rules)
    assert set(zip(r.tolist(), c.tolist())) == {(0, 1), (1, 0)} and not dropped

    dropped = {}
    r, _, _ = build._ferry_edges(_index([A, B]), links, cal, dropped_out=dropped, rules=rules)
    assert len(r) == 0 and dropped == {"outside length window": 1}, \
        "between joined neighbours the floor still drops it"


# ---- Water cells: no road across a gulf both of whose shores are one landmass --

def _gulf(gap_w, gap_e, linked=(), cut_east=False, landfalls=()):
    """A's seven-cell patch, every cell split, over a north-south channel of
    water with land either side -- both shores ONE landmass, as the Gulf of
    Aqaba's are, so `severed_pairs` (which compares parts) sees nothing to cut.
    Returns the hex adjacency left once `water_pairs` is applied."""
    la, lo = h3.cell_to_latlng(A)
    polygons = [shapely.box(lo - 1.0, la - 1.0, lo - gap_w, la + 1.0),
                shapely.box(lo + gap_e, la - 1.0, lo + 1.0, la + 1.0)]
    bases = [A, *RING]
    cells = [k for b in bases for k in h3.cell_to_children(b, config.FINE_RES)]
    pos = {c: i for i, c in enumerate(cells)}
    water = landmass.water_cells(bases, polygons)
    east = {c for c in cells if polygons[1].intersects(
        shapely.Polygon([(x, y) for y, x in h3.cell_to_boundary(c)]))}
    # The east shore as an island `severed_pairs` already cut every water cell from.
    before = frozenset((pos[w], pos[n]) for w in water for n in h3.grid_ring(w, 1)
                       if n in east) if cut_east else frozenset()
    before = before | {(b, a) for a, b in before}
    cut = landmass.water_pairs(water, pos, set(linked), polygons, before,
                               frozenset(pos[c] for c in landfalls)) | before
    adj = {c: {n for n in h3.grid_ring(c, 1) if n in pos and (pos[c], pos[n]) not in cut}
           for c in cells}
    shore = {c: next((i for i, p in enumerate(polygons)
                      if p.intersects(shapely.Polygon([(x, y) for y, x in h3.cell_to_boundary(c)]))),
                     None) for c in cells}
    return adj, water, shore, pos, cut


def _reach(adj, start):
    seen, todo = {start}, [start]
    while todo:
        for n in adj[todo.pop()]:
            if n not in seen:
                seen.add(n)
                todo.append(n)
    return seen


def test_no_chain_of_water_cells_joins_two_shores_of_one_landmass():
    """Rebuild 34: Taba -> Haql read 122 min, driven down the middle of the
    Gulf of Aqaba over cells that touch no land at all.

    Mutations performed and reverted: water-water pairs left joined in
    water_pairs (`if n in water: continue` in the final loop) -> red; no edge
    kept from an offshore cell towards land -> red. (Every land neighbour kept
    rather than the nearest shore's turns the next test red.)
    """
    adj, water, shore, _, _ = _gulf(0.08, 0.09)
    offshore = [w for w in water if all(shore[n] is None for n in h3.grid_ring(w, 1) if n in shore)]
    assert offshore, "fixture: the channel must hold cells out of sight of land"
    west = next(c for c, s in shore.items() if s == 0)
    east = {c for c, s in shore.items() if s == 1}
    assert not _reach(adj, west) & east, "a road across the water"
    for w in water:
        assert any(shore[c] is not None for c in _reach(adj, w)), f"{w} cut off from both shores"


def test_a_water_cell_touching_both_shores_keeps_only_the_nearer():
    """A channel one cell wide: each water cell borders land on both sides."""
    adj, water, shore, _, _ = _gulf(0.02, 0.03)
    assert water
    for w in water:
        sides = {shore[n] for n in adj[w]} - {None}
        assert len(sides) == 1, f"{w} joins shores {sides}, want only its nearer one"


def test_a_water_cell_the_island_was_cut_from_keeps_the_main_shore():
    """Rebuild 35's first try left 3,194 cells unreachable (Aland, Lofoten,
    the Korean and Dalmatian islands): a water cell `severed_pairs` had cut
    from an island kept only its edge to that island, the nearer shore.

    Mutation performed and reverted: water_pairs ignoring `severed` -> red.
    """
    adj, water, shore, _, _ = _gulf(0.02, 0.025, cut_east=True)
    for w in water:
        assert any(shore[c] == 0 for c in _reach(adj, w)), f"{w} reaches no shore"


def test_a_trunk_road_over_natural_earths_water_keeps_its_cells_joined():
    """The road check of 2026-10-17: 408 motorway and trunk hops (349 ways)
    ran between cells this rule had cut -- reclaimed coast in Jiangsu, the
    Pingtan approach -- where OSM has road and Natural Earth has sea.

    Mutation performed and reverted: road_hops joining no hop -> red.
    """
    la, lo = h3.cell_to_latlng(A)
    _, water, _, pos, _ = _gulf(0.04, 0.05)
    at = lambda y, x: pos.get(h3.latlng_to_cell(y, x, config.FINE_RES))  # noqa: E731
    road = pl.DataFrame({"way_id": [1], "highway": ["trunk"], "lat": [[la, la]],
                         "lon": [[lo - 0.1, lo + 0.1]]})
    hops = landmass.road_hops(road, water, pos, at)
    assert hops
    adj, _, shore, _, _ = _gulf(0.04, 0.05, linked=hops)
    west = at(la, lo - 0.08)
    cells = list(pos)
    assert any(shore[c] == 1 for c in _reach(adj, cells[west])), "the trunk road crosses"


def test_a_bridge_ending_in_a_water_cell_keeps_it_joined_to_both_shores():
    """The Ikema Ohashi's Miyako end falls in a cell Natural Earth calls sea;
    tied to the nearer land, Ikema's, the bridge led nowhere.

    Mutation performed and reverted: water_pairs ignoring `landfalls` -> red.
    """
    _, water, _, _, _ = _gulf(0.02, 0.03)
    end = sorted(water)[0]
    adj, _, shore, _, _ = _gulf(0.02, 0.03, landfalls={end})
    assert {shore[n] for n in adj[end]} - {None} == {0, 1}


def test_a_bridge_over_the_water_keeps_its_pairs():
    _, _, _, pos, cut = _gulf(0.04, 0.05)
    linked = {p for u, v in sorted(cut)[:6] for p in ((u, v), (v, u))}
    _, _, _, _, cut2 = _gulf(0.04, 0.05, linked=linked)
    assert not linked & cut2 and cut - linked <= cut2
