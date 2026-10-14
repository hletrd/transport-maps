"""OSM motorways onto cells (sources/motorways.py): which ways count, how a
way is sampled, and which cells of a mixed-resolution index it marks."""

from __future__ import annotations

from types import SimpleNamespace

import h3
import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import motorways


def test_maxspeed_reads_numbers_and_mph_and_refuses_the_rest():
    assert motorways.parse_maxspeed("100") == 100.0
    assert motorways.parse_maxspeed("100;80") == 100.0
    assert motorways.parse_maxspeed("70 mph") == pytest.approx(112.65, abs=0.01)
    for raw in (None, "", "none", "signals", "RU:motorway"):
        assert motorways.parse_maxspeed(raw) is None


def _ways(rows):
    return pl.DataFrame([{"way_id": i, "highway": hw, "expressway": ex, "maxspeed_kmh": ms,
                          "lat": la, "lon": lo} for i, (hw, ex, ms, la, lo) in enumerate(rows)],
                        schema=motorways.SCHEMA)


def test_each_rule_counts_exactly_its_ways():
    """Mutation performed and reverted: "expressway" not admitting the
    tagged trunk -> RED."""
    df = _ways([("motorway", False, None, [0, 1], [0, 1]),
                ("trunk", True, None, [0, 1], [0, 1]),
                ("trunk", False, 110.0, [0, 1], [0, 1]),
                ("trunk", False, 80.0, [0, 1], [0, 1])])
    got = {r: sorted(motorways.selected(df, r)["way_id"].to_list()) for r in motorways.RULES}
    assert got == {"motorway": [0], "expressway": [0, 1], "fast_trunk": [0, 1, 2]}
    with pytest.raises(ValueError):
        motorways.selected(df, "everything")


def test_densify_samples_every_step_and_never_bridges_two_ways():
    """Two ways end to end in the arrays: the gap between the first's last
    node and the second's first is not a road, and an antimeridian segment
    is not drawn the long way round.

    Mutation performed and reverted: drop `seg[ends - 1] = False` -> RED."""
    lat = np.array([0.0, 0.0, 10.0, 10.0, 20.0, 20.0])
    lon = np.array([0.0, 0.009, 0.0, 0.009, 179.99, -179.99])     # ~1 km, ~1 km, antimeridian
    plat, plon = motorways.densify(lat, lon, np.array([0, 2, 4]), step_km=0.4)
    assert not ((plat > 0.5) & (plat < 9.5)).any(), "a point between the two ways"
    assert not (plat == 20.0).any(), "the antimeridian segment was drawn"
    first = np.sort(plon[plat == 0.0])
    assert first[0] == 0.0 and first[-1] == pytest.approx(0.009)
    assert np.diff(first).max() * 111.0 <= 0.4 + 1e-9


def test_the_mask_marks_the_cells_the_way_crosses_at_the_index_resolution(monkeypatch, tmp_path):
    """A way across a base cell and a split base cell marks the base cell
    and only the fine children it crosses; a cell off the way stays clear.

    Mutation performed and reverted: look every point up at the base
    resolution, split or not -> RED."""
    lat0, lon0 = 37.5, 127.0
    a = h3.latlng_to_cell(lat0, lon0, config.SOLVE_RES)
    b = h3.latlng_to_cell(lat0, lon0 + 0.15, config.SOLVE_RES)
    assert a != b
    off = h3.latlng_to_cell(lat0 + 0.3, lon0, config.SOLVE_RES)
    children = sorted(h3.cell_to_children(b, config.FINE_RES))
    cells = [a, off, *children]
    pos = {c: i for i, c in enumerate(cells)}
    idx = SimpleNamespace(cells=cells, n_cells=len(cells), _split=frozenset({b}),
                          try_cell_index=pos.get)
    df = _ways([("motorway", False, None, [lat0, lat0], [lon0, lon0 + 0.3])])
    monkeypatch.setattr(motorways, "ways", lambda **_: (df, "k"))
    monkeypatch.setattr(config, "CACHE", tmp_path)
    mask = motorways.motorway_mask(idx, "motorway")
    assert mask[pos[a]] and not mask[pos[off]]
    crossed = [c for c in children if mask[pos[c]]]
    assert 0 < len(crossed) < len(children), "the split cell's children are all-or-nothing"
    # The cache answers the second call, and keys on the rule.
    assert motorways._mask_cache_path(cells, "k", "motorway").exists()
    assert (motorways.motorway_mask(idx, "motorway") == mask).all()
    assert motorways._mask_cache_path(cells, "k", "motorway") != \
        motorways._mask_cache_path(cells, "k", "expressway")


def test_the_parser_reads_a_real_extract(tmp_path):
    """A written .osm.pbf, not a stub: nodes resolved to coordinates, the
    expressway spellings and maxspeed read, other highways and a way with
    unresolvable nodes left out.

    Mutation performed and reverted: read WAY entities alone (no location
    cache can be built) -> RED."""
    import osmium

    path = tmp_path / "x-roads.osm.pbf"
    with osmium.SimpleWriter(str(path)) as w:
        for i, (la, lo) in enumerate([(0.0, 0.0), (0.0, 0.01), (0.0, 0.02)], start=1):
            w.add_node(osmium.osm.mutable.Node(id=i, location=(lo, la)))
        w.add_way(osmium.osm.mutable.Way(id=10, nodes=[1, 2], tags={"highway": "motorway"}))
        w.add_way(osmium.osm.mutable.Way(id=11, nodes=[2, 3], tags={
            "highway": "trunk", "motorroad": "yes", "maxspeed": "60 mph"}))
        w.add_way(osmium.osm.mutable.Way(id=12, nodes=[1, 3], tags={"highway": "primary"}))
        w.add_way(osmium.osm.mutable.Way(id=13, nodes=[1, 99], tags={"highway": "motorway"}))
    rows = {r["way_id"]: r for r in motorways._ways(path)}
    assert sorted(rows) == [10, 11]
    assert rows[10]["lon"] == pytest.approx([0.0, 0.01]) and not rows[10]["expressway"]
    assert rows[11]["expressway"] and rows[11]["maxspeed_kmh"] == pytest.approx(96.56, abs=0.01)


def test_a_point_is_looked_up_as_the_index_looks_it_up(monkeypatch, tmp_path):
    """H3 children do not nest inside their parent's outline: near an edge a
    point lies in base cell b while its fine cell's parent is the neighbour
    c. With c split and b not, NodeIndex.cell_at says b -- and so must the
    mask, or a motorway along b's edge marks a cell of c it never enters.

    Mutation performed and reverted: take the fine cell's parent as the
    base cell -> RED."""
    from transport_maps.graph.nodes import NodeIndex

    rng = np.random.default_rng(0)
    for _ in range(20000):
        la, lo = 37.5 + rng.uniform(-0.2, 0.2), 127.0 + rng.uniform(-0.2, 0.2)
        b = h3.latlng_to_cell(la, lo, config.SOLVE_RES)
        f = h3.latlng_to_cell(la, lo, config.FINE_RES)
        c = h3.cell_to_parent(f, config.SOLVE_RES)
        if c != b:
            break
    else:
        pytest.fail("no point found whose fine cell's parent is not its base cell")
    cells = [b, *sorted(h3.cell_to_children(c, config.FINE_RES))]
    idx = NodeIndex(cells, [], {x: i for i, x in enumerate(cells)}, {}, {}, (), _split=frozenset({c}))
    assert idx.cell_at(la, lo) == b
    df = _ways([("motorway", False, None, [la, la], [lo, lo + 1e-7])])
    monkeypatch.setattr(motorways, "ways", lambda **_: (df, "k2"))
    monkeypatch.setattr(config, "CACHE", tmp_path)
    mask = motorways.motorway_mask(idx, "motorway")
    assert mask.tolist() == [True] + [False] * (len(cells) - 1)
