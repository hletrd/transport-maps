"""A forked build worker never calls into polars, pyogrio or rasterio (S2, ARCH-5).

Under fork, a child that touches one of them can hang at 0% CPU with no
traceback: the A3 incident, and the reason `_build_all` loads every parquet-,
GDAL- and raster-backed array in the parent. Two in-function fallbacks used to
reload them whenever a caller dropped a keyword: `modes.mode_minutes_per_node`
(`cell_class` -> `roads.cell_class`, rasterio) and
`validate.check_monotonic_ground` (`country`/`zone` ->
`countries.cell_country`, pyogrio and polars). Both are gone; the arrays are
required.

`tests/test_cli.py::_stub_pipeline` replaces every writer and gate, so it
cannot see a worker take such a path. This runs the real `_solve_one` -- every
writer, the coverage gate and the monotonic-ground gate -- in a forked pool
worker whose polars, pyogrio and rasterio entry points (and the two in-repo
loaders that call them) raise. Only the solve and the band tiles are stubbed:
the fixture is `tests/emit/test_layout_contract.py`'s three hover cells.

Mutations performed and reverted, each red: the `modes` fallback restored and
`_solve_one` passing no `cell_class` (the child raises "called into"); the
`validate` fallback restored and `_solve_one` passing no `country`/`zone`
(same).
"""

from __future__ import annotations

import multiprocessing
import os
import types

import h3
import numpy as np
import pytest

from tests.emit.test_layout_contract import CELL_CLASS, TABLES, _fixture
from transport_maps import cli
from transport_maps.emit import hover, modes


def _refuse(*_args, **_kwargs):
    raise RuntimeError("a forked build worker called into polars, pyogrio or rasterio")


def _poisoned_init(parent_pid: int, context) -> None:
    """The pool initializer, run in the CHILD only: the parent of a real build
    calls these legitimately, before it forks."""
    import polars
    import pyogrio
    import rasterio

    from transport_maps.sources import countries, roads

    for module, name in ((polars, "read_parquet"), (polars, "scan_parquet"),
                         (pyogrio, "read_arrow"), (pyogrio, "read_dataframe"),
                         (rasterio, "open"),
                         (countries, "cell_country"), (roads, "cell_class"),
                         (roads, "road_class_grid")):
        setattr(module, name, _refuse)
    polars.DataFrame.__init__ = _refuse
    cli._init_worker(parent_pid, context)


@pytest.mark.needs_inputs
def test_a_forked_worker_solves_an_origin_without_polars_gdal_or_rasterio(
        monkeypatch, tmp_path):
    from transport_maps.contour import bands
    from transport_maps.emit import tiles
    from transport_maps.graph import ground
    from transport_maps.solve import dijkstra

    idx, minutes, pred, expected, _, _ = _fixture()
    monkeypatch.setattr(dijkstra, "origin_node", lambda idx, lat, lon: 6)
    monkeypatch.setattr(dijkstra, "solve_from",
                        lambda csr, source, with_predecessors=False: (minutes, pred))
    monkeypatch.setattr(bands, "band_feature_collection", lambda *a, **k: {"features": []})
    monkeypatch.setattr(cli.validate, "check_bands_cover", lambda *a, **k: None)
    monkeypatch.setattr(tiles, "write_pmtiles",
                        lambda fc, out, **k: out.write_bytes(b"\0" * 2048))

    parents = hover.hover_cells(idx)
    # Seoul and Busan in Korea, Tokyo in Japan, as the parent would derive
    # them; and a crawling 1 km/h, so the monotonic gate holds on the
    # fixture's hand-made times and runs to the end.
    country = np.array(["JPN" if h3.cell_to_latlng(c)[1] > 135.0 else "KOR" for c in idx.cells])
    shared = {"country": country, "zone": ground.cell_zones(country),
              "cell_class": CELL_CLASS,
              "grid": None, "native": None, "band_flags": None, "rail_tables": TABLES,
              "reading": hover.reading_layout(idx), "variant": None,
              "hover_parents": parents,
              "hover_groups": hover.hover_groups(idx, parents),
              "base_hover": hover.base_hover_index(idx, parents),
              "reachable": cli.validate.reachable_in_principle(idx),
              "border_min": ground._land_border_min(),
              "out_root": tmp_path}
    context = cli.BuildContext(idx, None, np.full(idx.n_cells, 1.0),
                               types.MappingProxyType(shared))

    pool_ctx = multiprocessing.get_context("fork")
    with pool_ctx.Pool(1, initializer=_poisoned_init,
                       initargs=(os.getpid(), context)) as pool:
        row = pool.apply_async(cli._solve_one_forked,
                               ({"slug": "o", "lat": 0.0, "lon": 0.0},)).get(timeout=60)

    assert row.split()[0] == "o"
    # The writers really ran on the fixture, rather than an early return.
    out = tmp_path / "origins"
    mode = np.frombuffer((out / "o.modes.bin").read_bytes(), "<u2").reshape(-1, len(modes.CHANNELS))
    assert mode[:, 0].tolist() == [e["rail_min"] for e in expected]
    for suffix in (".bin", ".r6.bin", ".over.bin", ".json", ".air.bin", ".rail.bin", ".rail.json"):
        assert (out / f"o{suffix}").exists(), suffix
