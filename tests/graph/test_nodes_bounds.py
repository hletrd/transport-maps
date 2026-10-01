"""`build_index` enforces the dropped-airport bound -- proved on 19 cells.

These lived in `test_nodes.py` under its module-wide `integration` mark and
built the whole 13.8-million-cell index to watch two airports fall in the sea:
44 seconds for a rule that does not depend on the size of the world (TE-26).
The land mask, road grid, urban mask and fixed links are stubbed to a disk of
nineteen cells around Seoul, so `build_index` itself runs end to end -- the
placement, the bound and the `dropped_airports` it reports -- in well under a
second, and with no data/ caches at all.

`test_nodes.py` keeps the one check that is about the real data: how many of
today's airports the real mask drops.
"""

from __future__ import annotations

import h3
import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.graph import nodes

LAND = sorted(h3.grid_disk(h3.latlng_to_cell(37.5665, 126.9780, config.SOLVE_RES), 2))
# Open ocean: mid-Pacific and mid-Atlantic, no land cell within two rings.
OCEAN = [(0.0, -160.0), (30.0, -40.0)]


@pytest.fixture
def tiny_world(monkeypatch):
    from transport_maps.sources import fixed_links, roads, urban

    monkeypatch.setattr(nodes.landmask, "land_cells", lambda res: list(LAND))
    monkeypatch.setattr(roads, "cell_class", lambda cells: np.zeros(len(cells), dtype=np.int64))
    monkeypatch.setattr(urban, "urban_mask", lambda cells: np.zeros(len(cells), dtype=bool))
    monkeypatch.setattr(fixed_links, "fixed_links", lambda **k: None)

    def with_airports(rows):
        monkeypatch.setattr(nodes.airports, "scheduled_airports", lambda: pl.DataFrame(
            rows, schema=["iata", "lat", "lon"], orient="row"))
    return with_airports


def _on_land(n: int) -> list[tuple[str, float, float]]:
    """n airports, each exactly on a land cell's centre (no snap)."""
    return [(f"L{i:02d}", *h3.cell_to_latlng(LAND[i % len(LAND)])) for i in range(n)]


def test_the_dropped_airport_bound_actually_aborts(tiny_world):
    """Proof the bound is a gate and not just a number: put every airport off
    the land mask and build_index must refuse, not return an empty graph.

    Mutation performed and reverted: delete the `raise RuntimeError` under
    `len(dropped) > limit` in `nodes._place_airports` -> red (an index with
    no airports is returned).
    """
    tiny_world([("AAA", *OCEAN[0]), ("BBB", *OCEAN[1])])
    with pytest.raises(RuntimeError, match="land mask has regressed"):
        nodes.build_index()


def test_one_atoll_in_sixty_is_counted_and_the_build_goes_on(tiny_world):
    """Under the bound the airport is dropped, NAMED in `dropped_airports`,
    and every other airport is indexed -- the skip is counted, not silent.

    Mutation performed and reverted: `tuple(dropped)` -> `()` in
    `build_index`'s NodeIndex call -> red (nothing reported dropped).
    """
    rows = [*_on_land(60), ("OFF", *OCEAN[0])]
    tiny_world(rows)
    idx = nodes.build_index()
    assert idx.dropped_airports == ("OFF",)
    assert len(idx.airports) == 60 and "OFF" not in idx.airports
    assert len(idx.dropped_airports) <= nodes.MAX_DROPPED_AIRPORT_FRACTION * len(rows)
    assert idx.cells == LAND, "the stub was not the index's land"
