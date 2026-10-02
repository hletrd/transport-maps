"""The solver bundle answers what the build's own index and solver answer.

The service never sees a NodeIndex: it reads arrays the build wrote. Every
test here builds a small mixed-resolution world, solves it the build's way, and
holds the bundle to the same answer -- the snap (including the split-neighbour
case `_nearest_land` exists for) and the minutes.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import h3
import numpy as np
import pytest
import scipy.sparse as sp
from scipy.sparse.csgraph import dijkstra

from transport_maps import config
from transport_maps.service import bundle, server, wire
from transport_maps.snap import _nearest_land

CENTRE = (37.5665, 126.9780)


N_AIR, N_STN = 2, 2


def _world(cut_last: bool = False):
    """Ring-2 res-6 disk with its centre split into res-7 children, a chain of
    edges through every cell, and the centre's own cell left out of the land
    set's ring-2 corner so a snap has something to do.

    Laid out as the build lays a graph out (docs/contract.md): the 24 cells,
    then departure nodes for airports 0 and 1, their arrival nodes, then two
    stations. The chain from cell 0 to the last cell costs 322 min; the
    journey that beats it, at 284.7, rides the train, flies 0 -> 1, connects
    at 1 and flies 1 -> 0 (airport 1 has no way out to the ground), so one
    solve crosses every kind of edge:

        cell 0 -> stn 0 -> stn 1 -> cell 5     4.4 + 10.3 + 3.2   rail
        cell 5 -> dep 0                        60.6               access
        dep 0 -> arr 1                         90.2               flight
        arr 1 -> dep 1                         45.4               connection
        dep 1 -> arr 0                         30.1               flight
        arr 0 -> cell 22 -> cell 23            15.5 + 25          egress, road

    `cut_last` drops every edge into the last cell, which makes it unreachable.
    """
    base = h3.latlng_to_cell(*CENTRE, config.SOLVE_RES)
    disk = sorted(h3.grid_disk(base, 2))
    split = {base}
    cells = [c for c in disk if c not in split] + sorted(h3.cell_to_children(base, config.FINE_RES))
    missing = disk[0]                      # an off-mask base cell: a point here must snap
    cells.remove(missing)
    nc = len(cells)
    dep, arr, stn = (lambda k: nc + k), (lambda k: nc + N_AIR + k), (lambda k: nc + 2 * N_AIR + k)
    n = nc + 2 * N_AIR + N_STN
    edges = []
    for i in range(nc - 1):                # a path through every cell, both ways
        edges += [(i, i + 1, 3.0 + i), (i + 1, i, 2.0 + i)]
    edges += [(0, stn(0), 4.4), (stn(0), stn(1), 10.3), (stn(1), 5, 3.2),
              (5, dep(0), 60.6), (dep(0), arr(1), 90.2), (arr(1), dep(1), 45.4),
              (dep(1), arr(0), 30.1), (arr(0), 22, 15.5)]
    if cut_last:
        edges = [e for e in edges if e[1] != nc - 1]
    rows, cols, w = zip(*edges, strict=True)
    csr = sp.csr_matrix((w, (rows, cols)), shape=(n, n))
    return cells, split, n, csr, missing


def _write(tmp_path, cut_last=False, name="solver"):
    cells, split, n, csr, missing = _world(cut_last)
    out = bundle.write_bundle(tmp_path / name, cells, split, n, csr, {"buildId": "t"},
                              n_airports=N_AIR, n_stations=N_STN)
    return cells, split, csr, missing, out


@pytest.fixture
def built(tmp_path):
    cells, split, csr, missing, out = _write(tmp_path)
    return cells, split, csr, missing, bundle.load_bundle(out)


def _strip_counts(path):
    """The bundle as the first FORMAT-1 builds wrote it: no node counts."""
    meta = json.loads((path / "meta.json").read_text())
    del meta["nAirports"], meta["nStations"]
    (path / "meta.json").write_text(json.dumps(meta))


def _between(cells, i, j):
    return wire.SolveRequest(*h3.cell_to_latlng(cells[i]), *h3.cell_to_latlng(cells[j]))


def test_the_bundle_finds_every_cell_where_the_build_put_it(built):
    """Mutation performed and reverted: write `sorted_pos` as `order` of the
    REVERSED ids -> red."""
    cells, _split, _csr, _missing, b = built
    for i, c in enumerate(cells):
        assert b.cell_pos.get(c) == i
    assert b.cell_pos.get(h3.latlng_to_cell(0.0, 0.0, config.SOLVE_RES)) is None


def test_the_bundle_snaps_as_the_build_does(built):
    """Including the split neighbour: the snap must look through a split base
    cell to its children, which a plain lookup by base cell cannot see.

    Mutation performed and reverted: write an empty `split.npy` -> red.
    """
    cells, split, _csr, missing, b = built
    pos = {c: i for i, c in enumerate(cells)}
    lat, lon = h3.cell_to_latlng(missing)
    want = _nearest_land(missing, pos, lat, lon, frozenset(split))
    assert want is not None
    assert b.snap(lat, lon) == want
    # A point inside the split cell lands on its res-7 child, as cell_at does.
    child = h3.latlng_to_cell(*CENTRE, config.FINE_RES)
    assert b.snap(*CENTRE) == (pos[child], 0.0)


def test_the_solver_returns_the_build_graphs_minutes(built):
    """Mutation performed and reverted: save `data` reversed -> red."""
    cells, _split, csr, _missing, b = built
    a, z = cells[3], cells[-1]
    want = dijkstra(csr, directed=True, indices=3)[len(cells) - 1]
    req = wire.SolveRequest(*h3.cell_to_latlng(a), *h3.cell_to_latlng(z))
    body = bundle.GraphSolver(b).solve(req)
    assert body["minutes"] == round(want) and body["reachable"] is True
    assert body["snappedKm"] == 0.0


def test_the_bundle_does_not_copy_the_graph(built):
    """1 GB of edges is the reason the format exists; the CSR the solver uses
    must still be the mapped file, not a private copy.

    Mutation performed and reverted: `copy=True` in load_bundle -> red.
    """
    *_rest, b = built
    chain, a = [], b.csr.data
    while a is not None:
        chain.append(a)
        a = getattr(a, "base", None)
    assert any(isinstance(x, np.memmap) for x in chain), [type(x).__name__ for x in chain]


def test_a_point_off_land_is_not_on_land(built):
    *_rest, b = built
    req = wire.SolveRequest(0.0, -30.0, *CENTRE)
    with pytest.raises(wire.WireError) as err:
        bundle.GraphSolver(b).solve(req)
    assert err.value.code == "not_on_land"


def test_a_bundle_of_another_format_is_refused(built, tmp_path):
    *_rest, _b = built
    meta = tmp_path / "solver" / "meta.json"
    m = json.loads(meta.read_text())
    m["format"] = bundle.FORMAT + 1
    meta.write_text(json.dumps(m))
    with pytest.raises(ValueError):
        bundle.load_bundle(tmp_path / "solver")


def test_the_server_speaks_the_wire_format(built):
    """Over a real socket: a solve, an unknown path, and a bad query."""
    cells, _split, _csr, _missing, b = built
    httpd = server._Server(("127.0.0.1", 0), server.make_handler(bundle.GraphSolver(b)))
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        (la, lo), (lb, lob) = h3.cell_to_latlng(cells[2]), h3.cell_to_latlng(cells[5])
        url = f"http://127.0.0.1:{port}/api/solve?from={la},{lo}&to={lb},{lob}"
        with urllib.request.urlopen(url) as r:
            body = json.loads(r.read())
            assert r.status == 200 and body["status"] == "ok" and body["v"] == wire.WIRE_VERSION
            assert sum(leg["min"] for leg in body["legs"]) == body["minutes"]
        for path, status in (("/elsewhere", 404), ("/api/solve?from=nan,1&to=1,1", 400)):
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}")
            assert err.value.code == status
            assert json.loads(err.value.read())["status"] == "error"
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---- the journey, not just the number ------------------------------------

# What `_world` routes from cell 0 to cell 23, at the node times 0, 4.4, 14.7,
# 17.9, 78.5, 168.7, 214.1, 244.2, 259.7 and 284.7 -- rounded at each node to
# 0, 4, 15, 18, 78, 169, 214, 244, 260 and 285.
JOURNEY = [
    {"kind": "surface", "min": 78, "railMin": 18},
    {"kind": "fly", "from": 0, "to": 1, "min": 91},
    {"kind": "connect", "at": 1, "min": 45},
    {"kind": "fly", "from": 1, "to": 0, "min": 30},
    {"kind": "surface", "min": 41, "railMin": 0},
]


def test_a_solve_says_how_the_journey_went(built):
    """Rail, the airport, two flights, a connection and the road out, each
    classified by the node range it falls in, with ordinals as `.air.bin`
    numbers airports.

    Mutations performed and reverted, each RED: swap `from` and `to` in the
    fly leg; drop the station test from `rail`; classify arr -> dep as
    surface; read an arrival node's ordinal as `v - n_cells`; walk the
    predecessors back from the start instead of the end.
    """
    cells, _split, csr, _missing, b = built
    body = bundle.GraphSolver(b).solve(_between(cells, 0, len(cells) - 1))
    assert body["minutes"] == round(dijkstra(csr, indices=0)[len(cells) - 1]) == 285
    assert body["legs"] == JOURNEY


def test_the_legs_sum_to_the_figure_they_break_down(built):
    """Rounded once per node, not once per leg. Rounding each leg's own
    float gives 78 + 90 + 45 + 30 + 40 = 283 under a figure of 285 here, which
    is a breakdown that does not add up.

    Mutation performed and reverted: round each edge's own float difference
    instead of the node times -> RED.
    """
    cells, _split, _csr, _missing, b = built
    solver = bundle.GraphSolver(b)
    for i in range(len(cells)):
        body = solver.solve(_between(cells, i, len(cells) - 1))
        assert sum(leg["min"] for leg in body["legs"]) == body["minutes"], i
        for leg in body["legs"]:
            if leg["kind"] == "surface":
                assert 0 <= leg["railMin"] <= leg["min"]


def test_an_overland_journey_is_one_surface_leg(built):
    """Cell 1 to cell 3 along the chain: no airport, no station.

    Mutation performed and reverted: start a new surface leg on every edge
    instead of extending the last one -> RED.
    """
    cells, _split, _csr, _missing, b = built
    body = bundle.GraphSolver(b).solve(_between(cells, 1, 3))
    assert body["legs"] == [{"kind": "surface", "min": body["minutes"], "railMin": 0}]
    same = bundle.GraphSolver(b).solve(_between(cells, 4, 4))
    assert same["minutes"] == 0
    assert same["legs"] == [{"kind": "surface", "min": 0, "railMin": 0}]


def test_an_unreachable_destination_has_no_legs(tmp_path):
    """`minutes: null` and no `legs` key at all -- not an empty list, which a
    page could read as "nothing to itemise" under a figure that does not
    exist.

    Mutation performed and reverted: drop `reachable and` from the guard in
    GraphSolver.solve -> RED (walk_back raises ValueError).
    """
    cells, *_rest, out = _write(tmp_path, cut_last=True)
    body = bundle.GraphSolver(bundle.load_bundle(out)).solve(_between(cells, 0, len(cells) - 1))
    assert body["minutes"] is None and body["reachable"] is False
    assert "legs" not in body
    with pytest.raises(ValueError):
        bundle.walk_back(np.full(len(cells) + 6, -9999, dtype=np.int32), 0, len(cells) - 1)


def test_a_bundle_written_before_the_counts_still_answers_a_number(tmp_path):
    """The bundle the running rebuild writes is FORMAT 1 with no node counts.
    It must load and answer exactly as before -- the figure, and no `legs`.

    Mutation performed and reverted: read the counts unconditionally in
    `Bundle.layout` -> RED (KeyError).
    """
    cells, *_rest, out = _write(tmp_path)
    _strip_counts(out)
    b = bundle.load_bundle(out)
    assert b.layout is None
    body = bundle.GraphSolver(b).solve(_between(cells, 0, len(cells) - 1))
    assert body["minutes"] == 285 and "legs" not in body


def test_add_counts_gives_an_old_bundle_its_legs(tmp_path):
    """Mutation performed and reverted: drop the `_check_layout` call from
    add_counts -> RED, the (2, 3) row is written."""
    cells, *_rest, out = _write(tmp_path)
    _strip_counts(out)
    before = (out / "meta.json").read_text()
    for bad in ((2, 3), (3, 1), (-1, 8), (2.0, 2)):
        with pytest.raises(ValueError):
            bundle.add_counts(out, *bad)
        assert (out / "meta.json").read_text() == before, f"{bad} was written"
    meta = bundle.add_counts(out, N_AIR, N_STN)
    assert (meta["nAirports"], meta["nStations"]) == (N_AIR, N_STN)
    assert not list(out.glob("*.part")), "the temporary meta.json was left behind"
    body = bundle.GraphSolver(bundle.load_bundle(out)).solve(_between(cells, 0, len(cells) - 1))
    assert body["legs"] == JOURNEY
    # Idempotent with the same counts; a contradiction is refused.
    bundle.add_counts(out, N_AIR, N_STN)
    with pytest.raises(ValueError):
        bundle.add_counts(out, 1, 4)


def test_a_layout_that_does_not_add_up_is_refused_at_load_and_at_write(tmp_path):
    """An airport count off by one shifts every ordinal after it: every
    airport in every itinerary renamed, every figure still right.

    Mutations performed and reverted: drop the `_check_layout` call from
    load_bundle -> RED; from write_bundle -> RED.
    """
    cells, split, n, csr, _missing = _world()
    with pytest.raises(ValueError):
        bundle.write_bundle(tmp_path / "w", cells, split, n, csr, n_airports=3, n_stations=2)
    *_rest, out = _write(tmp_path)
    meta = json.loads((out / "meta.json").read_text())
    meta["nAirports"] = 3
    (out / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError):
        bundle.load_bundle(out)


def _dist(root, build_id="t", airports=None, stations=None):
    nc = len(_world()[0])
    d = root / "dist"
    (d / "origins").mkdir(parents=True)
    (d / "index.json").write_text(json.dumps(
        {"buildId": build_id, "origins": [{"slug": "seoul"}]}))
    a = nc if airports is None else airports
    s = a + 2 * N_AIR if stations is None else stations
    (d / "origins" / "seoul.json").write_text(json.dumps(
        {"offsets": {"cells": 0, "airports": a, "stations": s}, "nodes": []}))
    return d


def test_the_counts_come_from_the_same_builds_dist(tmp_path):
    """And from nowhere else: another build's offsets, or offsets that do not
    start where the bundle's cells end, are refused.

    Mutations performed and reverted: drop the buildId comparison -> RED on
    "another build"; drop the `airports != nCells` test -> RED on "shifted".
    """
    *_rest, out = _write(tmp_path)
    _strip_counts(out)
    assert bundle.counts_from_dist(out, _dist(tmp_path)) == (N_AIR, N_STN)
    nc = len(_world()[0])
    for name, kw in (("another build", {"build_id": "other"}),
                     ("shifted", {"airports": nc + 1, "stations": nc + 1 + 2 * N_AIR}),
                     ("odd", {"stations": nc + 2 * N_AIR + 1})):
        sub = tmp_path / name
        sub.mkdir()
        with pytest.raises(ValueError):
            bundle.counts_from_dist(out, _dist(sub, **kw))
    bundle.main(["add-counts", str(out), str(_dist(tmp_path / "cli"))])
    assert bundle.load_bundle(out).layout == (nc, N_AIR)
