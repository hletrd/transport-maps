"""Task B2: the ground, urban and air-bound constants moved into calibration.toml.

The move must not change a single value. The expectations below are the
literals the modules held before the move (graph/ground.py, sources/urban.py,
graph/air.py at 350eff3), typed here rather than read from the code under
test, plus the urban-mask cache key those literals produced, measured before
the move on the same two cells.

Mutations performed (2026-10-02), each RED, each restored:
  - calibration.toml highway speed 104.0 -> 105.0                 -> RED
  - calibration.toml knee_km 400.0 -> 450.0                       -> RED
  - calibration.toml congestion_factor 2.0 -> 2.5                 -> RED
  - urban.load_urban_calibration without float(), pop_min written
    as the TOML integer 200000                                   -> RED (cache key moves)
  - ground._land_border_min re-reading calibration.toml per call  -> RED
  - ground.py assigning a literal array instead of the loader     -> RED
  - ground.GROUND_KEYS with roadless and highway swapped          -> RED
"""

from __future__ import annotations

import ast
import hashlib

import numpy as np
import pytest

from transport_maps import config
from transport_maps.graph import air, ground
from transport_maps.sources import urban

OLD_SPEEDS = [5.0, 104.0, 57.0, 50.0, 18.0, 25.0]
OLD_URBAN = (200_000.0, 40.0, 2.0)
OLD_AIR_BOUNDS = (400.0, 0.5)
OLD_LAND_BORDER_MIN = 45.0
#: urban._mask_cache_path(CELLS).name before the move.
CELLS = ["8530e08ffffffff", "8530e087fffffff"]
OLD_URBAN_KEY = "urban_mask-81727e55.parquet"


def test_the_ground_speeds_are_the_old_literals():
    speeds = ground.SPEED_BY_ROAD_CLASS_KMH
    assert speeds.dtype == np.float64
    assert speeds.tolist() == OLD_SPEEDS


def test_the_urban_constants_are_the_old_literals():
    got = (urban.URBAN_POP_MIN, urban.URBAN_RADIUS_KM, urban.URBAN_CONGESTION_FACTOR)
    assert got == OLD_URBAN
    assert all(type(v) is float for v in got), [type(v).__name__ for v in got]


def test_the_air_bounds_are_the_old_literals():
    assert (air.KNEE_KM, air.MIN_FLIGHTS_PER_WEEK) == OLD_AIR_BOUNDS


def test_the_land_border_time_is_unchanged():
    assert ground._land_border_min() == OLD_LAND_BORDER_MIN


def test_the_urban_mask_cache_key_did_not_move():
    """The move costs no recompute of the urban mask: same values, same key.
    The key is digested through json, where 200000 and 200000.0 differ."""
    assert urban._mask_cache_path(CELLS).name == OLD_URBAN_KEY
    # ...and the key is still the function of the constants it was, so the
    # equality above is not satisfied by a key that ignores them.
    want = urban._params_hash(*OLD_URBAN[:2], urban.PLACES_URL,
                              hashlib.sha256("".join(CELLS).encode()).hexdigest())
    assert OLD_URBAN_KEY == f"urban_mask-{want}.parquet"


def _edited(tmp_path, old: str, new: str):
    text = (config.ROOT / "calibration.toml").read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    p = tmp_path / "calibration.toml"
    p.write_text(text.replace(old, new), encoding="utf-8")
    return p


def test_each_loader_reads_the_file_not_a_literal(tmp_path):
    """Equal to the old literals is also what an unmoved literal would give.
    Each loader must follow an edit to the file it is pointed at."""
    p = _edited(tmp_path, "highway_kmh = 104.0", "highway_kmh = 111.0")
    assert ground.load_ground_calibration(p)[0][1] == 111.0
    p = _edited(tmp_path, "congestion_factor = 2.0", "congestion_factor = 3.0")
    assert urban.load_urban_calibration(p)[2] == 3.0
    p = _edited(tmp_path, "knee_km = 400.0", "knee_km = 300.0")
    assert air.load_frequency_bounds(p)[0] == 300.0
    p = _edited(tmp_path, "pop_min = 200000.0", "pop_min = 200000")
    assert type(urban.load_urban_calibration(p)[0]) is float


@pytest.mark.parametrize(("module", "names", "loader"), [
    (ground, ("SPEED_BY_ROAD_CLASS_KMH", "LAND_BORDER_MIN"), "load_ground_calibration"),
    (urban, ("URBAN_POP_MIN", "URBAN_RADIUS_KM", "URBAN_CONGESTION_FACTOR"),
     "load_urban_calibration"),
    (air, ("KNEE_KM", "MIN_FLIGHTS_PER_WEEK"), "load_frequency_bounds"),
])
def test_the_module_constants_come_from_the_loader(module, names, loader):
    """Each constant is assigned exactly once, from its loader -- not a
    literal kept beside a loader nobody calls."""
    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    assigns = [n for n in tree.body if isinstance(n, ast.Assign)
               and {getattr(t, "id", None) for t in ast.walk(n.targets[0])} & set(names)]
    assert len(assigns) == 1, f"{module.__name__}: {len(assigns)} assignments to {names}"
    call = assigns[0].value
    assert isinstance(call, ast.Call) and getattr(call.func, "id", None) == loader


def test_the_land_border_time_is_not_reread_per_call(monkeypatch, tmp_path):
    """Read once at import (ARCH-8). The per-origin gate used to re-parse
    calibration.toml for every origin, so an edit mid-build could check an
    origin against a constant its graph was not weighted with."""
    monkeypatch.setattr(config, "ROOT", tmp_path)          # no calibration.toml here
    assert ground._land_border_min() == OLD_LAND_BORDER_MIN
