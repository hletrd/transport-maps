"""Derived caches must key on the constants that produced them.

Every intermediate cache used to key on a bare `.exists()`. Concretely: lower
DENSITY_THRESHOLD, re-run `build-all`, and road_class_grid.npy short-circuits --
the change silently never takes effect and every test still passes, because
they all read back the same stale artifact. That is this project's signature
failure mode, so the stamping is pinned from both directions: the path must
move when a governing constant moves, and must NOT move otherwise.
"""

import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import airports, landmask, roads
from transport_maps.sources._utils import _params_hash


def test_hash_is_stable_across_calls():
    assert _params_hash(1.0, {"a": 1}) == _params_hash(1.0, {"a": 1})


def test_hash_ignores_dict_ordering_but_not_values():
    assert _params_hash({"a": 1, "b": 2}) == _params_hash({"b": 2, "a": 1})
    assert _params_hash({"a": 1}) != _params_hash({"a": 2})


def test_hash_separates_values_that_repr_alike():
    # 1 and 1.0 are equal but not interchangeable as a threshold.
    assert _params_hash(1) != _params_hash(1.0)


# --- road grid ---------------------------------------------------------------


def test_road_grid_path_moves_when_the_density_threshold_moves(monkeypatch):
    before = roads._grid_cache_path()
    monkeypatch.setattr(roads, "DENSITY_THRESHOLD", roads.DENSITY_THRESHOLD / 2)
    assert roads._grid_cache_path() != before


def test_road_grid_path_is_stable_when_nothing_changes():
    """The other half: a stamp that changed on every call would pass the test
    above while destroying the cache entirely.
    """
    assert roads._grid_cache_path() == roads._grid_cache_path()


def test_road_grid_reads_the_stamped_path(tmp_path, monkeypatch):
    """Proves _grid_cache_path is the path road_class_grid actually uses, so a
    changed constant really does miss rather than merely naming a new file.
    """
    monkeypatch.setattr(config, "BUILD", tmp_path)
    monkeypatch.setattr(roads, "_grid_cache", None)
    sentinel = np.full((roads.GRID_ROWS, roads.GRID_COLS), 3, dtype=np.uint8)
    with roads._grid_cache_path().open("wb") as fh:
        np.save(fh, sentinel)

    assert roads.road_class_grid()[0, 0] == 3

    # Now move the governing constant: the sentinel must no longer be found.
    monkeypatch.setattr(roads, "_grid_cache", None)
    monkeypatch.setattr(roads, "DENSITY_THRESHOLD", 99.0)
    assert not roads._grid_cache_path().exists()


# --- airport table -----------------------------------------------------------


def test_airport_table_path_moves_when_the_size_mapping_moves(monkeypatch):
    before = airports._table_cache_path()
    monkeypatch.setattr(
        airports, "SIZE_BY_TYPE", {**airports.SIZE_BY_TYPE, "seaplane_base": "small"}
    )
    assert airports._table_cache_path() != before


def test_airport_table_path_moves_when_required_columns_move(monkeypatch):
    before = airports._table_cache_path()
    monkeypatch.setattr(
        airports, "REQUIRED_SOURCE_COLUMNS", airports.REQUIRED_SOURCE_COLUMNS | {"elevation_ft"}
    )
    assert airports._table_cache_path() != before


def test_airport_table_reads_the_stamped_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BUILD", tmp_path)
    pl.DataFrame({"iata": ["ZZZ"]}).write_parquet(airports._table_cache_path())

    assert airports.scheduled_airports()["iata"].to_list() == ["ZZZ"]

    monkeypatch.setattr(airports, "SIZE_BY_TYPE", {"large_airport": "large"})
    assert not airports._table_cache_path().exists()


# --- land mask ---------------------------------------------------------------


def test_land_cells_path_still_separates_resolutions():
    assert landmask._cells_cache_path(4) != landmask._cells_cache_path(5)


def test_land_cells_path_moves_when_the_antarctica_cutoff_moves(monkeypatch):
    before = landmask._cells_cache_path(5)
    monkeypatch.setattr(landmask, "ANTARCTICA_MAX_LAT", -55.0)
    assert landmask._cells_cache_path(5) != before


def test_land_cells_reads_the_stamped_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BUILD", tmp_path)
    pl.DataFrame({"cell": ["8530e08ffffffff"]}).write_parquet(landmask._cells_cache_path(5))

    assert landmask.land_cells(5) == ["8530e08ffffffff"]

    monkeypatch.setattr(landmask, "ANTARCTICA_MAX_LAT", -55.0)
    assert not landmask._cells_cache_path(5).exists()


@pytest.mark.parametrize(
    "path_fn",
    [roads._grid_cache_path, airports._table_cache_path, lambda: landmask._cells_cache_path(5)],
)
def test_every_stamped_path_carries_a_hash(path_fn):
    """A stamp silently dropped from the f-string would leave the old bare
    filename and reinstate the bug, while the "path moves" tests above could
    still pass if the constant leaked in some other way.
    """
    stem = path_fn().stem
    assert any(len(part) == 8 and part.isalnum() for part in stem.split("_"))


def test_atomically_written_files_are_readable_by_other_users(tmp_path):
    """mkstemp creates 0600 and os.replace preserves it.

    Every artifact in dist/ goes out through this helper, and a web server
    serving one of them as 0600 answers 403 -- which is exactly how the
    gazetteer shipped invisible.
    """
    import os
    import stat

    from transport_maps.sources._utils import _atomic_write

    out = tmp_path / "artifact.json"
    # The helper honours the umask, so under `umask 077` a 0600 result is
    # correct; pin the umask so the verdict is about the chmod, not the shell.
    previous = os.umask(0o022)
    try:
        _atomic_write(out, lambda p: p.write_text("{}"))
    finally:
        os.umask(previous)
    mode = stat.S_IMODE(os.stat(out).st_mode)
    assert mode & stat.S_IRGRP, f"group cannot read (mode {mode:o})"
    assert mode & stat.S_IROTH, f"others cannot read (mode {mode:o})"
