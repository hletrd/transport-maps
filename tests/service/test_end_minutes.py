"""Every road journey's two door ends ([ground] end_min), added once per
solve, the same way by the build and by the service.

The fit (scripts/calibrate_ground.py) put 13.8 min on every journey: without
it the residual followed length in every stratum. Half is charged leaving the
departure door -- every node but the source -- and half arriving at a cell;
the airport kerb's halves are on the access edges. The bundle carries the
value, because the service ships without calibration.toml.
"""

from __future__ import annotations

import h3
import numpy as np
from scipy.sparse.csgraph import dijkstra

from tests.service.test_bundle import N_AIR, N_STN, _world
from transport_maps.service import bundle, wire


def test_the_shift_is_half_everywhere_and_whole_at_cells_and_none_at_the_source():
    """Mutations performed and reverted, each RED: add the whole end to
    every node; leave the source shifted."""
    dist = np.array([0.0, 10.0, 20.0, 30.0, np.inf])        # 3 cells, then 2 other nodes
    out = bundle.with_end_minutes(dist, 0, 3, 8.0)
    assert out.tolist() == [0.0, 18.0, 28.0, 34.0, np.inf]
    assert bundle.with_end_minutes(dist, 0, 3, 0.0) is dist


def test_the_service_answers_what_the_build_would_with_the_bundles_end_minutes(tmp_path):
    """The map and the journey from a point both carry the bundle's end
    minutes, from one solve; a bundle without the key answers as before.

    Mutation performed and reverted: GraphSolver._tree not applying
    with_end_minutes -> RED."""
    cells, split, n, csr, _missing = _world()
    out = bundle.write_bundle(tmp_path / "solver", cells, split, n, csr, {"buildId": "t"},
                              n_airports=N_AIR, n_stations=N_STN, end_min=12.0)
    b = bundle.load_bundle(out)
    assert b.meta["endMinutes"] == 12.0
    solver = bundle.GraphSolver(b)
    a, z = h3.cell_to_latlng(cells[0]), h3.cell_to_latlng(cells[-1])
    got = solver.solve(wire.SolveRequest(*a, *z))
    raw = dijkstra(csr, directed=True, indices=0)
    want = bundle.with_end_minutes(raw, 0, len(cells), 12.0)[len(cells) - 1]
    assert got["minutes"] == round(want) == round(raw[len(cells) - 1] + 12.0)
    assert sum(leg["min"] for leg in got["legs"]) == got["minutes"]
