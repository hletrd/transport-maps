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


def _world():
    """Ring-2 res-6 disk with its centre split into res-7 children, a chain of
    edges through every cell, and the centre's own cell left out of the land
    set's ring-2 corner so a snap has something to do."""
    base = h3.latlng_to_cell(*CENTRE, config.SOLVE_RES)
    disk = sorted(h3.grid_disk(base, 2))
    split = {base}
    cells = [c for c in disk if c not in split] + sorted(h3.cell_to_children(base, config.FINE_RES))
    missing = disk[0]                      # an off-mask base cell: a point here must snap
    cells.remove(missing)
    n_air = 2
    n = len(cells) + n_air
    rows, cols, w = [], [], []
    for i in range(len(cells) - 1):        # a path through every cell, both ways
        rows += [i, i + 1]
        cols += [i + 1, i]
        w += [3.0 + i, 2.0 + i]
    rows += [0, len(cells)]
    cols += [len(cells), len(cells) + 1]   # cell 0 -> airport -> airport
    w += [40.0, 90.0]
    csr = sp.csr_matrix((w, (rows, cols)), shape=(n, n))
    return cells, split, n, csr, missing


@pytest.fixture
def built(tmp_path):
    cells, split, n, csr, missing = _world()
    out = bundle.write_bundle(tmp_path / "solver", cells, split, n, csr, {"buildId": "t"})
    return cells, split, csr, missing, bundle.load_bundle(out)


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
        for path, status in (("/elsewhere", 404), ("/api/solve?from=nan,1&to=1,1", 400)):
            with pytest.raises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}")
            assert err.value.code == status
            assert json.loads(err.value.read())["status"] == "error"
    finally:
        httpd.shutdown()
        httpd.server_close()
