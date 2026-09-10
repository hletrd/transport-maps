"""Derived caches must key on the constants that produced them.

Every intermediate cache used to key on a bare `.exists()`. Concretely: lower
DENSITY_THRESHOLD, re-run `build-all`, and road_class_grid.npy short-circuits --
the change silently never takes effect and every test still passes, because
they all read back the same stale artifact. That is this project's signature
failure mode, so the stamping is pinned from both directions: the path must
move when a governing constant moves, and must NOT move otherwise.
"""

import hashlib

import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import (
    airports,
    countries,
    landmask,
    osm,
    roads,
    routes,
    urban,
    wikidata,
)
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


# --- every stamped constant, by name -----------------------------------------
#
# One case per constant per stamp: the list documents the governing set, and a
# name dropped from a stamp turns its case red (the older tests covered five
# of fourteen). `new` must differ from the current value.

STAMPED = [
    (roads, "GRIP4_URL", "https://example.invalid/grip4_{n}.zip", roads._grid_cache_path),
    (roads, "DENSITY_THRESHOLD", 0.5, roads._grid_cache_path),
    (roads, "GRID_ROWS", 2159, roads._grid_cache_path),
    (roads, "GRID_COLS", 4319, roads._grid_cache_path),
    (roads, "N_TYPES", 4, roads._grid_cache_path),
    (airports, "AIRPORTS_URL", "https://example.invalid/airports.csv", airports._table_cache_path),
    (airports, "SIZE_BY_TYPE", {"large_airport": "large"}, airports._table_cache_path),
    (airports, "REQUIRED_SOURCE_COLUMNS", frozenset({"iata_code"}), airports._table_cache_path),
    (landmask, "LAND_URL", "https://example.invalid/land.zip", lambda: landmask._cells_cache_path(6)),
    (landmask, "ICE_URL", "https://example.invalid/ice.zip", lambda: landmask._cells_cache_path(6)),
    (landmask, "LAKES_URL", "https://example.invalid/lakes.zip", lambda: landmask._cells_cache_path(6)),
    (landmask, "ANTARCTICA_MAX_LAT", -55.0, lambda: landmask._cells_cache_path(6)),
    (landmask, "POLE_CLIP_LAT", -89.5, lambda: landmask._cells_cache_path(6)),
    (landmask, "WEDGE_COUNT", 6, lambda: landmask._cells_cache_path(6)),
    (landmask, "POLYFILL_METHOD", "centre-containment", lambda: landmask._cells_cache_path(6)),
    (urban, "URBAN_POP_MIN", 100_000.0, lambda: urban._mask_cache_path(["a", "b"])),
    (urban, "URBAN_RADIUS_KM", 20.0, lambda: urban._mask_cache_path(["a", "b"])),
    (urban, "PLACES_URL", "https://example.invalid/places.zip", lambda: urban._mask_cache_path(["a", "b"])),
    (osm, "ANTIMERIDIAN_EPS_DEG", 1e-3, lambda: osm._ferry_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "MIN_FERRY_KM", 2.0, lambda: osm._ferry_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "MAX_FERRY_KM", 3000.0, lambda: osm._ferry_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "MIN_STOPS", 3, lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    (routes, "PARSER_VERSION", 999, routes._network_cache_path),
    (routes, "_SANITY_PAIRS", (("AAA", "BBB"),), routes._network_cache_path),
    (routes, "_SKIP_PREFIXES", ("Nowhere:",), routes._network_cache_path),
    (wikidata, "RESOLVER_VERSION", 999, routes._network_cache_path),
]


@pytest.mark.parametrize("module,name,new,path_fn", STAMPED,
                         ids=[f"{m.__name__.split('.')[-1]}.{n}" for m, n, _, _ in STAMPED])
def test_the_cache_path_moves_when_a_stamped_constant_moves(monkeypatch, module, name, new, path_fn):
    before = path_fn()
    assert getattr(module, name) != new, "fixture value equals the current one"
    monkeypatch.setattr(module, name, new)
    assert path_fn() != before, f"{module.__name__}.{name} is not in the cache stamp"


def test_the_urban_mask_key_covers_the_whole_cell_list():
    """Same length, same first and last cell, different middle: the old key
    (len, first, last) served one universe's mask to the other."""
    a = urban._mask_cache_path(["c1", "c2", "c3"])
    b = urban._mask_cache_path(["c1", "cX", "c3"])
    assert a != b


def test_the_country_key_covers_the_whole_cell_list(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE", tmp_path)
    seen = []
    monkeypatch.setattr(countries, "_polygons", lambda: (_ for _ in ()).throw(AssertionError("computed")))
    for cells in (["c1", "c2", "c3"], ["c1", "cX", "c3"]):
        key = countries._params_hash(countries.COUNTRIES_URL, "filled-blanks-nearest",
                                     hashlib.sha256("".join(cells).encode()).hexdigest())
        pl.DataFrame({"country": ["KOR"] * 3}).write_parquet(tmp_path / f"cell_country-{key}.parquet")
        seen.append(countries.cell_country(cells).tolist())
    assert seen == [["KOR"] * 3] * 2


def test_the_route_network_path_carries_a_stamp_and_adopts_the_legacy_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(config, "BUILD", tmp_path)
    assert routes._network_cache_path().name != "routes.parquet"
    pl.DataFrame({"src": ["AAA"], "dst": ["BBB"]}).write_parquet(tmp_path / "routes.parquet")
    df = routes.route_network()
    assert df["src"].to_list() == ["AAA"]
    assert "legacy" in capsys.readouterr().out


def test_a_parser_version_change_empties_the_destination_cache_but_a_legacy_file_is_adopted(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE", tmp_path)
    (tmp_path / "airline_destinations.json").write_text('{"ICN": ["Tokyo"]}')   # legacy flat
    assert routes._load_destination_cache() == {"ICN": ["Tokyo"]}
    routes._save_destination_cache({"ICN": ["Tokyo"]})
    assert routes._load_destination_cache() == {"ICN": ["Tokyo"]}
    monkeypatch.setattr(routes, "PARSER_VERSION", routes.PARSER_VERSION + 1)
    assert routes._load_destination_cache() == {}
    (tmp_path / "wikidata_iata.json").write_text('{"Narita International Airport": "NRT"}')
    assert wikidata._load_cache() == {"Narita International Airport": "NRT"}
    wikidata._save_cache({"X": "XXX"})
    monkeypatch.setattr(wikidata, "RESOLVER_VERSION", wikidata.RESOLVER_VERSION + 1)
    assert wikidata._load_cache() == {}


def test_params_hash_refuses_a_set_rather_than_hashing_its_repr():
    """`default=repr` accepted a set, and a set's repr follows iteration order,
    which for strings depends on PYTHONHASHSEED: params_hash({'a'...'g'})
    digests to 652072a0 under seed 1 and ed78b352 under seed 2.

    The failure mode is silent and permanent -- every run misses the cache,
    re-downloads GRIP4 and re-polyfills four million cells, and reports
    success. Refusing at the boundary makes the caller sort it and say so.
    """
    import pytest

    from transport_maps._io import params_hash

    with pytest.raises(TypeError, match="refuses a set"):
        params_hash({"a", "b", "c"})
    with pytest.raises(TypeError, match="refuses a set"):
        params_hash({"key": [1, {"x", "y"}]})          # nested, too
    # The sorted form is what a call site should pass, and it is stable.
    assert params_hash(sorted({"c", "a", "b"})) == params_hash(["a", "b", "c"])


def test_the_real_cache_path_names_are_stable_across_interpreter_hash_seeds():
    """The seed hazard is about the paths the BUILD computes, not about three
    literals.

    This test used to hash ['a','b','c'], {'k': 1} and (2, 3) in a subprocess
    under four seeds. Those inputs are order-stable under
    json.dumps(sort_keys=True) whatever `default=` does, so deleting the
    _reject_unordered guard the test was written to protect left it green --
    a permanent pass. (The guard IS covered, by the test above that passes a
    set and requires a raise; this one added nothing.)

    What actually matters is that the derived cache paths do not move between
    runs. A seed-dependent digest is silent: it is a permanent cache miss that
    re-downloads GRIP4 and re-polyfills four million cells on every run while
    reporting success. `airports._table_cache_path` is the live example --
    `sorted(REQUIRED_SOURCE_COLUMNS)` is exactly the sort that stops a set's
    repr reaching the digest, and dropping it is a one-character edit.
    """
    import subprocess
    import sys

    code = (
        "import sys; sys.path.insert(0, 'src');"
        "from transport_maps.sources import airports, landmask, roads;"
        "print(airports._table_cache_path().name);"
        "print(landmask._cells_cache_path(6).name);"
        "print(roads._grid_cache_path().name)"
    )
    out = set()
    for seed in (0, 1, 2, 7, 31):
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={"PYTHONHASHSEED": str(seed), "PATH": "/usr/bin:/bin"},
                           check=True)
        out.add(r.stdout.strip())
    assert len(out) == 1, (
        "a derived cache path moved with PYTHONHASHSEED, so every run is a cache "
        f"miss that re-downloads its source and reports success:\n{chr(10).join(sorted(out))}")
    # ...and the names really are digests, not constants that could not move.
    names = next(iter(out)).splitlines()
    assert len(names) == 3
    assert all(any(ch.isdigit() for ch in n) and len(n) > 12 for n in names), names
