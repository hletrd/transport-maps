"""The road speed penalty uses the congestion radius, not the refinement one.

Since 2026-10-14 calibration.toml [urban] has two radii: `radius_km` (40)
decides which cells are split finer, `congestion_radius_km` (20) which cells'
roads are slowed. Reading the wrong one would put the old 40 km penalty back
under the refitted speeds -- every city's surroundings 1.6x too slow, with no
error anywhere.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from transport_maps.graph import ground
from transport_maps.sources import urban


def test_the_penalty_is_drawn_at_the_congestion_radius(monkeypatch):
    """Mutation performed and reverted: congestion_mask passing
    URBAN_RADIUS_KM -> RED."""
    asked = []

    def mask(cells, radius_km=urban.URBAN_RADIUS_KM):
        asked.append(radius_km)
        return np.array([True, True, False])

    monkeypatch.setattr(urban, "urban_mask", mask)
    idx = SimpleNamespace(cells=["a", "b", "c"], base_cells=[])
    classes = np.array([1, 0, 1])
    v = ground.cell_speed_kmh(idx, classes)
    assert asked == [urban.URBAN_CONGESTION_RADIUS_KM] != [urban.URBAN_RADIUS_KM]
    k = ground.SPEED_BY_ROAD_CLASS_KMH
    assert v.tolist() == [k[1] / urban.URBAN_CONGESTION_FACTOR, k[0], k[1]]
