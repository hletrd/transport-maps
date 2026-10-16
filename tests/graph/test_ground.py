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
    """From walking pace up to a high-income country's open motorway: the
    fastest class -- since rebuild 33 a motorway signed 115 km/h or more --
    times the largest income and region multipliers (graph/ground.py); a US
    interstate signed 75 mph is that cell."""
    speeds = ground.cell_speed_kmh(idx)
    k, m = ground.SPEED_BY_ROAD_CLASS_KMH, ground.INCOME_SPEED_MULTIPLIER
    fastest = max(k[list(ground.INCOME_SCALED_CLASSES)].max(),
                  ground.MOTORWAY_SPEED_BY_LIMIT_KMH.max())
    assert speeds.min() == k.min()
    assert np.isclose(speeds.max(), fastest * m.max() * ground.REGION_SPEED_MULTIPLIER.max())


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
    monkeypatch.setattr(ground, "cell_speed_kmh", lambda _idx, **_kw: fake_speeds)

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


def test_a_border_port_island_takes_its_listed_zone_only_where_no_country_is_drawn(monkeypatch):
    """The HZMB lands on a reclaimed island Natural Earth does not draw; its
    cells took China from Zhuhai and Hong Kong -> Macau paid two crossings.
    PORT_ZONES relabels the cells in the box whose centroid is in no country
    -- and nothing else: Zhuhai's drawn land beside it keeps China.

    Mutations performed and reverted, each RED: relabel every cell in the box
    (drop the sea test); drop the row (Hong Kong -> Macau pays two again).
    """
    import itertools

    import h3

    island = h3.latlng_to_cell(22.2217, 113.5915, 7)   # the port island (sea centroid)
    zhuhai = h3.latlng_to_cell(22.2391, 113.5760, 7)   # Zhuhai's drawn shore
    macau = h3.latlng_to_cell(22.1949, 113.5386, 7)    # Macau, outside the box
    cells = [zhuhai, island, macau]

    class Idx:
        def try_cell_index(self, c):
            return cells.index(c) if c in cells else None

    monkeypatch.setattr(ground, "_sea_centroid", lambda cs: np.array([c == island for c in cs]))
    monkeypatch.setattr(ground, "cell_zones",
                        lambda cc: np.array([{"CHN": "CN", "MAC": "MO"}[c] for c in cc]))
    zone = ground.zones_at(Idx(), np.array(["CHN", "CHN", "MAC"]))
    assert zone.tolist() == ["CN", "HK", "MO"]
    crossing = 45.0
    def charged(z):
        return sum(crossing for a, b in itertools.pairwise(z) if a and b and a != b)
    # Hong Kong -> the island -> Macau, and Hong Kong -> the island -> Zhuhai:
    # one crossing each where the island read China.
    assert charged(["HK", zone[1], zone[2]]) == crossing
    assert charged(["HK", zone[1], zone[0]]) == crossing
