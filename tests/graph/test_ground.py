import numpy as np
import pytest

from transport_maps.graph import ground, nodes

# Builds the full node index from the cached universe: minutes, real caches.
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def idx():
    return nodes.build_index()


def test_every_cell_has_a_positive_speed(idx):
    speeds = ground.cell_speed_kmh(idx)
    assert len(speeds) == idx.n_cells
    assert (speeds > 0).all()


def test_speeds_span_the_full_range(idx):
    speeds = ground.cell_speed_kmh(idx)
    assert speeds.min() == ground.SPEED_BY_ROAD_CLASS_KMH.min()
    assert speeds.max() == ground.SPEED_BY_ROAD_CLASS_KMH.max()


def test_roadless_terrain_is_slower_than_motorway_terrain(idx):
    speeds = ground.cell_speed_kmh(idx)
    # Through the index, which knows whether a point sits in a base cell or a
    # fine child; a literal resolution went stale when the grid changed.
    sahara = idx.cell_index(idx.cell_at(23.0, 10.0))
    seoul = idx.cell_index(idx.cell_at(37.5665, 126.9780))
    assert speeds[sahara] < speeds[seoul]


def test_hex_edge_cost_uses_destination_speed_not_source(idx, monkeypatch):
    """A speeds[c]/speeds[r] swap in hex_edges must turn this red.

    Phase A's uniform speed made source and destination indistinguishable by
    cost -- both charged the same 45 km/h regardless of which side of the
    swap `hex_edges` picked. With a real per-cell field, u->v and v->u can
    now be forced to genuinely differ, so this pins the direction down.
    """
    import h3

    # Find a pair of adjacent land cells so both u->v and v->u edges exist.
    u = v = None
    for candidate in range(idx.n_cells):
        cell = idx.cells[candidate]
        for neighbour in h3.grid_disk(cell, 1):
            if neighbour == cell:
                continue
            pos = idx.try_cell_index(neighbour)
            if pos is not None:
                u, v = candidate, pos
                break
        if u is not None:
            break
    assert u is not None, "no adjacent land cell pair found"

    fast, slow = 85.0, 5.0
    fake_speeds = np.full(idx.n_cells, 45.0, dtype=np.float64)
    fake_speeds[u] = fast
    fake_speeds[v] = slow
    monkeypatch.setattr(ground, "cell_speed_kmh", lambda _idx: fake_speeds)

    r, c, minutes = ground.hex_edges(idx)
    uv = minutes[(r == u) & (c == v)]
    vu = minutes[(r == v) & (c == u)]
    assert uv.size == 1 and vu.size == 1

    centroids = np.array([h3.cell_to_latlng(cell) for cell in idx.cells], dtype=np.float64)
    dist_km = ground.haversine_km(centroids[u : u + 1], centroids[v : v + 1])[0]

    # u -> v enters the slow cell; v -> u enters the fast cell. Charging the
    # source's speed instead would swap these two expected values.
    assert uv[0] == pytest.approx(dist_km / slow * 60.0)
    assert vu[0] == pytest.approx(dist_km / fast * 60.0)
