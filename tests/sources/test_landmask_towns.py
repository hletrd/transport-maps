"""A town the 1:10m coastline leaves at sea gets its cell, when land is beside it."""

import h3
import numpy as np
import shapely

from transport_maps import config
from transport_maps.sources import landmask, roads

KOTA_KINABALU = (5.9749, 116.0724)


def test_a_coastal_towns_cell_joins_and_an_isolated_ones_does_not(monkeypatch):
    """Downtown Kota Kinabalu (500,421 people, a departure city) touched no
    1:10m land polygon, so the city itself read "open water". Its cell joins
    the universe because a neighbour is land; a town in open water with no
    land cell beside it does not; a town already on land changes nothing.

    Mutations performed and reverted, each RED: drop the neighbour test
    (the isolated town joins); stop adding town cells in land_cells (the
    second test).
    """
    kk = h3.latlng_to_cell(*KOTA_KINABALU, config.SOLVE_RES)
    land = set(h3.grid_ring(kk, 1))
    sea_town = (0.0, -30.0)
    inland = h3.cell_to_latlng(sorted(land)[0])
    monkeypatch.setattr(roads, "_settlements", lambda: (
        np.array([KOTA_KINABALU[0], sea_town[0], inland[0]]),
        np.array([KOTA_KINABALU[1], sea_town[1], inland[1]]),
        np.array([500_421.0, 20_000.0, 30_000.0])))
    assert landmask._town_cells(config.SOLVE_RES, land) == {kk}


def test_land_cells_carries_the_town_cells(tmp_path, monkeypatch):
    """The universe is the polyfill plus the town cells, cached under a stamp
    that names the method."""
    monkeypatch.setattr(config, "BUILD", tmp_path)
    kk = h3.latlng_to_cell(*KOTA_KINABALU, config.SOLVE_RES)
    neighbour = sorted(h3.grid_ring(kk, 1))[0]
    la, lo = h3.cell_to_latlng(neighbour)
    monkeypatch.setattr(landmask, "_land_parts",
                        lambda: [shapely.box(lo - 0.001, la - 0.001, lo + 0.001, la + 0.001)])
    monkeypatch.setattr(landmask, "_sources", lambda: ["stub"])
    monkeypatch.setattr(roads, "_settlements", lambda: (
        np.array([KOTA_KINABALU[0]]), np.array([KOTA_KINABALU[1]]), np.array([500_421.0])))
    cells = set(landmask.land_cells(config.SOLVE_RES))
    assert neighbour in cells and kk in cells
    assert "town" in landmask.POLYFILL_METHOD
