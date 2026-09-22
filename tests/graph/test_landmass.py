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
    return pl.DataFrame([{"way_id": i, "kind": "highway", "name": "",
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


def test_hex_edges_builds_no_road_across_a_severed_pair(monkeypatch):
    idx = _index([A, B, C], {(0, 1), (1, 0)})
    monkeypatch.setattr(ground, "cell_speed_kmh", lambda _idx: np.full(3, 50.0))
    r, c, _ = ground.hex_edges(idx)
    edges = set(zip(r.tolist(), c.tolist()))
    assert (0, 1) not in edges and (1, 0) not in edges
    assert (0, 2) in edges and (2, 0) in edges, "an unsevered neighbour is still joined"


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
