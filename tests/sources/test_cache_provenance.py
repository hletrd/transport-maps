"""Derived caches must key on the constants that produced them.

Every intermediate cache used to key on a bare `.exists()`. Concretely: lower
DENSITY_THRESHOLD, re-run `build-all`, and road_class_grid.npy short-circuits --
the change silently never takes effect and every test still passes, because
they all read back the same stale artifact. That is this project's signature
failure mode, so the stamping is pinned from both directions: the path must
move when a governing constant moves, and must NOT move otherwise.

What the STAMPED table below could not see until cycle 16: nothing checked it
against the code at all. `tests/emit/test_build_identity.py` had a check of the
right shape and it was vacuous -- it built its "called" set by filtering the
table, so it was a subset of the table by construction and could never name a
constant the table lacked -- and this file was handed the same table with not
even that much. A constant that reaches a cache key with no row here is simply
never mutation-tested, which is the precise state that lets it be dropped from
the key later with every test green. The completeness check now reads each
stamping function's own AST. Reading the CODE rather than the table is what
makes that direction possible, and it found two on its first run:
`routes._SECTION_RE` and `routes._CARGO_RE` -- the very constants
`routes.PARSER_VERSION`'s comment names as the things a parse change is
announced through.

Mutations performed and reverted, with measured results:

- delete the `osm.RAIL_PARSER_VERSION` row from STAMPED (a hashed constant
  with no row). 1 failed, 60 passed: "constants reach a cache stamp with no
  row in STAMPED: ['osm.RAIL_PARSER_VERSION']".
- drop `countries.cell_country` from `_NOT_IN_THIS_TABLE`. 1 failed:
  "new, with no rows in STAMPED: ['countries.cell_country']" -- so the
  discovery half is live and a NEW stamping function cannot appear unnoticed.
- add a constant (`RASTER_DTYPE`) to `_params_hash` in a mutated COPY of
  sources/roads.py -- the real file could not be edited, a 38-hour `build-all`
  had it imported -- and run `_constants_hashed_by` against the copy:
  unrowed == `['roads.RASTER_DTYPE']`, red. Dropping `N_TYPES` from the same
  call instead: unhashed == `['roads.N_TYPES']`, red the other way. The
  unmutated copy: both empty, green.
"""

import ast
import hashlib
import importlib
import inspect
import pkgutil
import re
import sys
import textwrap

import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import (
    airports,
    countries,
    fixed_links,
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
    [roads._grid_cache_path, airports._table_cache_path, lambda: landmask._cells_cache_path(5),
     lambda: landmask._landmasses_cache_path(5),
     lambda: fixed_links._cache_path("north-america", "0123abcd"),
     lambda: routes._network_cache_path(["AAA"], {"AAA": "Alpha_Airport"})],
)
def test_every_stamped_path_carries_a_hash(path_fn):
    """A stamp silently dropped from the f-string would leave the old bare
    filename and reinstate the bug, while the "path moves" tests above could
    still pass if the constant leaked in some other way.
    """
    # The predicate used to be `any(len(part) == 8 and part.isalnum() ...)`,
    # which "airports" satisfies by itself -- eight alphanumerics -- so dropping
    # the stamp from airports._table_cache_path left this green. The stamp is a
    # HEX digest, so require that: eight characters, all hex, and not a word
    # that happens to be eight letters long.
    stem = path_fn().stem
    parts = stem.split("_")
    stamps = [p for p in parts
              if len(p) == 8 and all(c in "0123456789abcdef" for c in p)
              and any(c.isdigit() for c in p)]
    assert stamps, (
        f"{stem!r} carries no 8-character hex stamp, so the derived cache is "
        "keyed on a bare filename again and a constant change is a cache HIT")


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


def _routes_path():
    """The route network's path for one fixed pair of inputs."""
    return routes._network_cache_path(["AAA", "BBB"], {"AAA": "Alpha_Airport"})


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
    # MIN_FERRY_KM / MAX_FERRY_KM used to be stamped here. They never governed
    # the parquet's content -- nothing in sources/osm.py filters by length; the
    # bound is applied in graph/ferry.plausible_crossing at graph-build time --
    # and they now live there. What DOES govern the content is the parser
    # version and the two seasonality constants the tag parse applies.
    (osm, "FERRY_PARSER_VERSION", 999, lambda: osm._ferry_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "SEASON_MONTHS", 4, lambda: osm._ferry_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "UNSPECIFIED_SEASON_MONTHS", 6, lambda: osm._ferry_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "FERRY_SCHEMA", {"way_id": pl.Int64}, lambda: osm._ferry_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "MIN_STOPS", 3, lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    # The rail half of this table was ONE entry, MIN_STOPS, while the rail
    # parquet's content is governed by eight more. RAIL_PARSER_VERSION is the
    # one that matters most: it is the constant a parse change is supposed to
    # be announced through, and nothing checked that it reached the key.
    (osm, "RAIL_PARSER_VERSION", 999, lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "STOP_ROLES", ("stop",), lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "PLATFORM_ROLES", ("platform",), lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "SCHEMA", {"route_id": pl.Int64}, lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "RAIL_TIERS", ("slow", "fast"), lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "DEFAULT_TIER", "unknown", lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    (osm, "_TIER_BY_SERVICE", {"maglev": "fast"}, lambda: osm._rail_cache_path([("d", "x.pbf", 1, 2)])),
    (routes, "PARSER_VERSION", 999, _routes_path),
    (routes, "_SANITY_PAIRS", (("AAA", "BBB"),), _routes_path),
    (routes, "_SKIP_PREFIXES", ("Nowhere:",), _routes_path),
    # Both regexes reach the stamp as `.pattern`, and neither had a row until
    # the completeness check below was made to read the CODE rather than the
    # table. They are exactly the constants routes.PARSER_VERSION's own comment
    # says a parse change is announced through ("Bump when parse_destinations,
    # _SKIP_PREFIXES, _CARGO_RE or _SECTION_RE change") -- so a change to
    # either that forgot the version bump was relying on a stamp nothing
    # checked.
    (routes, "_SECTION_RE", re.compile(r"^==+\s*Destinations\s*==+$"), _routes_path),
    (routes, "_CARGO_RE", re.compile(r"^(===+)\s*Mail[^=]*=+$"), _routes_path),
    # The other two regexes parse_destinations applies (CR13-13). Both now
    # reach the network path through routes._parser_key, so each row proves
    # the constant is in that key AND that the key is in the path.
    (routes, "_NEXT_TOP_HEADING_RE", re.compile(r"^=[^=]", re.MULTILINE), _routes_path),
    (routes, "_LINK_RE", re.compile(r"\[\[([^\]|]+?)\]\]"), _routes_path),
    (wikidata, "RESOLVER_VERSION", 999, _routes_path),
    # The landmass ids are computed over the land universe, so anything that
    # moves `land_cells` must move them too. They reach the key through
    # `_cells_cache_path(res).name`, a call the AST reader rightly drops as
    # "how the key is computed" -- so this row is what proves the dependency.
    (landmask, "LAND_URL", "https://example.invalid/land2.zip", lambda: landmask._landmasses_cache_path(6)),
    (landmask, "ANTARCTICA_LANDMASS", -2, lambda: landmask._landmasses_cache_path(6)),
    (landmask, "LANDMASS_VERSION", 999, lambda: landmask._landmasses_cache_path(6)),
    (fixed_links, "_ABSENT", frozenset({"no", "none"}), lambda: fixed_links._cache_path("asia", "k")),
    (fixed_links, "_NOT_BUILT", frozenset({"proposed"}), lambda: fixed_links._cache_path("asia", "k")),
    (fixed_links, "KEEP_RES", 8, lambda: fixed_links._cache_path("asia", "k")),
    (fixed_links, "SCHEMA", {"way_id": pl.Int64}, lambda: fixed_links._cache_path("asia", "k")),
    (fixed_links, "FIXED_LINK_PARSER_VERSION", 999, lambda: fixed_links._cache_path("asia", "k")),
]


@pytest.mark.parametrize("module,name,new,path_fn", STAMPED,
                         ids=[f"{m.__name__.split('.')[-1]}.{n}" for m, n, _, _ in STAMPED])
def test_the_cache_path_moves_when_a_stamped_constant_moves(monkeypatch, module, name, new, path_fn):
    before = path_fn()
    assert getattr(module, name) != new, "fixture value equals the current one"
    monkeypatch.setattr(module, name, new)
    assert path_fn() != before, f"{module.__name__}.{name} is not in the cache stamp"


# --- and the table itself, checked against the code ---------------------------
#
# The table above is only as good as its completeness, and nothing checked
# that. `tests/emit/test_build_identity.py` had a check of this shape and it
# was vacuous -- it built the "called" set by filtering the table, so it was a
# subset of the table by construction and could never name a constant the table
# lacked. This file was given the table without even that much. So the set of
# constants is read out of each stamping function's OWN AST and compared with
# the table BOTH ways: a constant hashed with no row (never mutation-tested,
# the failure this file exists for) and a row for a constant no longer hashed
# both fail. Reading the code, not the table, is what makes the first direction
# possible at all -- and it immediately found two: routes._SECTION_RE and
# routes._CARGO_RE.

#: Stamping functions whose constants the table above is responsible for.
_COVERED_BY_TABLE = {
    "roads._grid_cache_path",
    "airports._table_cache_path",
    "landmask._cells_cache_path",
    "urban._mask_cache_path",
    "osm._ferry_cache_path",
    "osm._rail_cache_path",
    "routes._network_cache_path",
    "routes._parser_key",
    "landmask._landmasses_cache_path",
    "fixed_links._params_key",
}
#: Stamping functions deliberately outside it, each with the reason. A new
#: entry here is a decision someone has to write down, not a silent omission.
_NOT_IN_THIS_TABLE = {
    # `countries.cell_country` computes its key inline and has no path helper
    # to parametrise, so there is nothing to call with a monkeypatched
    # constant. KNOWN GAP: COUNTRIES_URL therefore has no mutation test.
    # `test_the_country_key_covers_the_whole_cell_list` below covers only the
    # cell-list half of that key, and it does so by re-typing the key
    # construction rather than calling the code.
    "countries.cell_country": "key built inline; no path helper to parametrise",
    # The INPUT half of the fixed-link key: the extract's own name, size and
    # mtime, and no module constant at all -- there is no row to write.
    # `tests/sources/test_fixed_links.py::test_a_newer_download_is_a_cache_miss`
    # pins it instead, and goes red when the source key is ignored.
    "fixed_links._source_key": "hashes the extract's name/size/mtime, no constant",
}


def _callee(node) -> str:
    return getattr(node, "attr", getattr(node, "id", "")) if node is not None else ""


def _params_hash_calls(fndef) -> list[ast.Call]:
    return [n for n in ast.walk(fndef)
            if isinstance(n, ast.Call)
            and _callee(n.func) in {"params_hash", "_params_hash"}]


def _stamping_functions() -> dict[str, object]:
    """Every module-level function in `transport_maps.sources` that hashes.

    Discovered from the package, not listed here, so a brand-new derived cache
    with brand-new constants cannot be added without this file noticing.
    """
    import transport_maps.sources as pkg

    found: dict[str, object] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
        for name, obj in vars(mod).items():
            if not (inspect.isfunction(obj) and obj.__module__ == mod.__name__):
                continue
            tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
            if _params_hash_calls(tree):
                found[f"{info.name}.{name}"] = obj
    return found


def _constants_hashed_by(fn) -> set[tuple[str, str]]:
    """(module, name) of every module-level constant reaching fn's params_hash.

    Resolution rules, each one load-bearing:

    * A bare `Name` is a module global of the defining module, or it is a
      parameter/comprehension variable and is ignored (`res`, `cells`,
      `fingerprint`, `k`, `v`).
    * `mod.ATTR` where `mod` resolves to a module is that module's constant --
      this is how `wikidata.RESOLVER_VERSION` reaches `routes`' stamp.
    * Modules and callables are dropped: `hashlib.sha256` and
      `airports._table_cache_path()` are how the key is COMPUTED, not
      constants that govern it (the airport table's own stamp is in its name,
      and has its own rows).
    * A local is followed back to what was assigned to it, which is how
      `schema = sorted((k, str(v)) for k, v in SCHEMA.items())` still reports
      `SCHEMA`.
    """
    module = sys.modules[fn.__module__]
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    assigned: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).append(node.value)

    found: set[tuple[str, str]] = set()

    def record(owner, attr: str) -> None:
        if not hasattr(owner, attr):
            return
        value = getattr(owner, attr)
        if inspect.ismodule(value) or callable(value):
            return
        found.add((owner.__name__, attr))

    def visit(node, depth: int = 0) -> None:
        if depth > 4:
            return
        for sub in ast.walk(node):
            if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
                owner = fn.__globals__.get(sub.value.id)
                if inspect.ismodule(owner):
                    record(owner, sub.attr)
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                if sub.id in assigned:
                    for rhs in assigned[sub.id]:
                        visit(rhs, depth + 1)
                elif sub.id in fn.__globals__:
                    record(module, sub.id)

    for call in _params_hash_calls(tree):
        for arg in call.args:
            visit(arg)
    return found


def test_every_function_that_stamps_a_cache_is_accounted_for():
    """A whole new derived cache must not slip past the table unnoticed."""
    discovered = set(_stamping_functions())
    declared = _COVERED_BY_TABLE | set(_NOT_IN_THIS_TABLE)
    assert discovered == declared, (
        "the set of functions that stamp a cache key has changed.\n"
        f"  new, with no rows in STAMPED: {sorted(discovered - declared)}\n"
        f"  gone from the code: {sorted(declared - discovered)}\n"
        "Add its constants to STAMPED, or record in _NOT_IN_THIS_TABLE why not.")


def test_the_table_and_the_stamps_cover_exactly_the_same_constants():
    """Both directions, and the first one is the one that was missing.

    A row for a constant that no longer reaches its stamp already turns that
    row's parametrised case red. A constant that reaches a stamp with NO row is
    what nothing caught: it is simply never mutation-tested, so dropping it
    from the key later is a silent cache hit on a stale artifact -- this
    project's signature failure, restated at the top of this file.
    """
    fns = _stamping_functions()
    hashed: set[tuple[str, str]] = set()
    for dotted in sorted(_COVERED_BY_TABLE):
        hashed |= _constants_hashed_by(fns[dotted])
    table = {(module.__name__, name) for module, name, _, _ in STAMPED}

    unrowed = sorted(f"{m.rsplit('.', 1)[-1]}.{n}" for m, n in hashed - table)
    unhashed = sorted(f"{m.rsplit('.', 1)[-1]}.{n}" for m, n in table - hashed)
    assert not unrowed, (
        f"constants reach a cache stamp with no row in STAMPED: {unrowed}. "
        "Nothing mutation-tests them, so dropping one from its key would be a "
        "silent cache HIT on the artifact built under the old value, with every "
        "test green -- add a row whose `new` differs from the current value")
    assert not unhashed, (
        f"STAMPED rows for constants that no longer reach any stamp: {unhashed}. "
        "Either the constant was dropped from its key or the row is stale")


def test_a_rail_schema_DTYPE_change_moves_the_key(monkeypatch):
    """`sorted(SCHEMA)` yields the KEYS only.

    So changing a column's type -- `tier` from Boolean to Utf8, exactly what
    this cycle did -- left the key unchanged, and the stale parquet was read
    back and reinterpreted under the new schema. The names are identical here;
    only a dtype differs.
    """
    fp = [("d", "x.pbf", 1, 2)]
    before = osm._rail_cache_path(fp)
    widened = {**osm.SCHEMA, "lat": pl.Float32}
    assert sorted(widened) == sorted(osm.SCHEMA), "the fixture must change only a dtype"
    monkeypatch.setattr(osm, "SCHEMA", widened)
    assert osm._rail_cache_path(fp) != before


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


@pytest.mark.parametrize("iatas,titles", [
    (["AAA", "BBB", "CCC"], {"AAA": "Alpha_Airport"}),        # an airport added
    (["AAA", "BBB"], {"AAA": "Alpha_International_Airport"}),  # an article re-pointed
    (["AAA", "BBB"], {"AAA": "Alpha_Airport", "BBB": "B"}),    # a link added
])
def test_the_route_network_path_moves_with_its_inputs(iatas, titles):
    """The constants are half the key; the airports a pair may join and the
    article crawled for each are the other half (CLAUDE.md: constants AND
    inputs). Mutation, measured: dropping `sorted(titles_by_iata.items())`
    from the stamp turns the last two cases red."""
    assert routes._network_cache_path(iatas, titles) != _routes_path()


def test_the_route_network_path_is_stable_when_nothing_changes():
    assert _routes_path() == _routes_path()
    assert _routes_path().name != "routes.parquet"
    # Insertion order is not an input.
    assert (routes._network_cache_path(["BBB", "AAA"], {"BBB": "B", "AAA": "A"})
            == routes._network_cache_path(["AAA", "BBB"], {"AAA": "A", "BBB": "B"}))


def test_a_section_regex_FLAG_change_moves_the_parser_key(monkeypatch):
    """`.pattern` alone would not see this: same text, different headings
    matched ("== AIRLINES AND DESTINATIONS ==" stops matching)."""
    before = routes._parser_key()
    monkeypatch.setattr(routes, "_SECTION_RE", re.compile(routes._SECTION_RE.pattern, re.MULTILINE))
    assert routes._parser_key() != before


@pytest.mark.parametrize("name,new", [
    ("PARSER_VERSION", 999),
    ("_LINK_RE", re.compile(r"\[\[([^\]|]+?)\]\]")),
    ("_NEXT_TOP_HEADING_RE", re.compile(r"^=[^=]", re.MULTILINE)),
])
def test_a_parser_change_empties_the_destination_cache(monkeypatch, tmp_path, name, new):
    """The per-airport cache stores PARSED titles, so it is the cache a parser
    fix has to get past. CR13-13: `_LINK_RE` never reached its version check,
    so the fragment-link fix (CR13-6) would have been read back as a hit.

    Mutation, measured: dropping `_LINK_RE.pattern, _LINK_RE.flags` from
    `routes._parser_key` turns the `_LINK_RE` case red (and the STAMPED row).
    """
    monkeypatch.setattr(config, "CACHE", tmp_path)
    routes._save_destination_cache({"ICN": ["Tokyo"]})
    assert routes._load_destination_cache() == {"ICN": ["Tokyo"]}
    monkeypatch.setattr(routes, name, new)
    assert routes._load_destination_cache() == {}


@pytest.mark.parametrize("legacy", [
    '{"ICN": ["Tokyo"]}',                                          # flat, pre-versioning
    '{"_parser_version": 1, "airports": {"ICN": ["Tokyo"]}}',      # PARSER_VERSION era
])
def test_a_destination_cache_from_before_the_parser_key_is_a_miss(monkeypatch, tmp_path, legacy):
    """Both older formats used to be adopted as "version 1". Neither records
    which regexes produced it, so neither can be trusted under a fixed parser.

    Mutation, measured: restoring the flat-format adoption (`return raw` when
    the file carries no stamp at all) turns the flat case red.
    """
    monkeypatch.setattr(config, "CACHE", tmp_path)
    (tmp_path / "airline_destinations.json").write_text(legacy)
    assert routes._load_destination_cache() == {}


def test_the_resolver_cache_still_adopts_its_legacy_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CACHE", tmp_path)
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
    # `len(n) > 12 and any(ch.isdigit())` is satisfied by "land_cells_r6" on its
    # own -- it has a digit and thirteen characters -- so dropping the stamp
    # from landmask._cells_cache_path left this green too. Require the hex
    # stamp itself, the same way the parametrised test above now does.
    names = next(iter(out)).splitlines()
    assert len(names) == 3
    for n in names:
        stem = n.rsplit(".", 1)[0]
        assert any(len(p) == 8 and all(c in "0123456789abcdef" for c in p)
                   and any(c.isdigit() for c in p)
                   for p in stem.split("_")), (
            f"{n!r} is not a stamped name: no 8-character hex digest in it")
