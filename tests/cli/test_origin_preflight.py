"""Every origin is resolved against the land mask before the graph is built.

The cost of not doing this is on the record. `rebuild19` died at origin 970 of
1,464, 26 hours in, because one city centre (Kota Kinabalu) sits on a res-6
cell the 1:10m coastline cuts outside. Cycle 12 gave `origin_node` a snap, so
that particular coordinate now resolves -- but a coordinate with no land
within two rings still aborts the run, and it still aborts wherever the origin
happens to sit in the queue. A second bad row would cost a second day.

`cli._preflight_origins` closes that: it resolves every SELECTED origin the
moment `nodes.build_index()` returns and before `build.build_graph()` runs,
and it names every bad row at once.

Every test here builds a `NodeIndex` by hand, so none of them needs a land
mask, a graph or a build, and each fails for one reason only.
"""

from __future__ import annotations

import logging

import h3
import pytest

from transport_maps import cli, config
from transport_maps.graph.nodes import NodeIndex

# Real coordinates. Kota Kinabalu is the one that killed rebuild19; the Pacific
# point is mid-ocean with no land for thousands of kilometres.
KOTA_KINABALU = (5.9749, 116.0724)
PACIFIC = (-30.0, -140.0)
ATLANTIC = (-25.0, -25.0)
INDIAN = (-40.0, 80.0)


def _index(cells: list[str]) -> NodeIndex:
    """A NodeIndex that knows only these cells. Nothing else is touched."""
    return NodeIndex(cells=list(cells), airports=[],
                     _cell_pos={c: i for i, c in enumerate(cells)},
                     _airport_pos={}, _airport_cell={})


def _origin(slug: str, lat: float, lon: float) -> dict:
    return {"slug": slug, "name": slug.title(), "lat": lat, "lon": lon}


def _land_at(lat: float, lon: float) -> str:
    return h3.latlng_to_cell(lat, lon, config.SOLVE_RES)


def test_a_good_origin_passes_and_says_nothing(caplog):
    """The ordinary case must be silent, or the warning below means nothing.

    Mutation performed and reverted: make the `km > 0.0` test `km >= 0.0` ->
    red, every origin is reported as snapped.
    """
    lat, lon = KOTA_KINABALU
    idx = _index([_land_at(lat, lon)])
    with caplog.at_level(logging.WARNING, logger="transport_maps.cli"):
        cli._preflight_origins(idx, [_origin("kota-kinabalu", lat, lon)])
    assert not caplog.records, f"a clean roster logged {caplog.records}"


def test_it_names_every_bad_origin_and_not_just_the_first():
    """The whole point. Reporting the first bad row turns two typos into two
    lost days, which is the shape of the original defect.

    THREE bad origins, not two: with two, a `bad[:1]` mutation and a correct
    implementation both produce a message naming the first, and only the count
    distinguishes them. Three also proves the message is not truncated.

    Mutation performed and reverted: replace the loop body's `continue` with
    `raise GateFailure(...)` on the first failure -> red (only `pacific` is
    named, and the count reads 1).
    """
    idx = _index([_land_at(*KOTA_KINABALU)])
    origins = [
        _origin("pacific", *PACIFIC),
        _origin("kota-kinabalu", *KOTA_KINABALU),   # good, and in the middle
        _origin("atlantic", *ATLANTIC),
        _origin("indian", *INDIAN),
    ]
    with pytest.raises(cli.GateFailure) as caught:
        cli._preflight_origins(idx, origins)
    message = str(caught.value)
    for slug in ("pacific", "atlantic", "indian"):
        assert slug in message, f"{slug} is unresolvable and is not named"
    assert "3 of 4" in message, f"the count does not say how many: {message}"
    assert "kota-kinabalu" not in message, "a resolvable origin was named as bad"


def test_the_message_carries_the_coordinate_to_fix():
    """A slug alone sends the reader to grep origins.toml. The number that is
    wrong is the one to print.

    Mutation performed and reverted: drop the lat/lon from the appended
    string -> red.
    """
    idx = _index([_land_at(*KOTA_KINABALU)])
    with pytest.raises(cli.GateFailure) as caught:
        cli._preflight_origins(idx, [_origin("pacific", *PACIFIC)])
    assert "-30.0" in str(caught.value) and "-140.0" in str(caught.value)


def test_a_snapped_origin_is_reported_with_its_distance(caplog):
    """The snap was silent: `dijkstra.snap_origin` logs nothing, so a roster
    expansion could move a city 13 km with nothing said anywhere. It is not a
    failure -- Kota Kinabalu is a real city on a real coast -- but it must be
    on the record.

    Mutation performed and reverted: drop the `log.warning` call -> red.
    """
    lat, lon = KOTA_KINABALU
    own = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    idx = _index(sorted(h3.grid_ring(own, 1)))        # neighbours, but not `own`
    assert idx.try_cell_index(own) is None, "the fixture must exclude the cell"

    # Padded with resolvable origins so the snapped-share bound below is not
    # what this test measures.
    origins = [_origin(f"inland-{i}", *h3.cell_to_latlng(c))
               for i, c in enumerate(idx.cells)] * 20
    origins.append(_origin("kota-kinabalu", lat, lon))
    with caplog.at_level(logging.WARNING, logger="transport_maps.cli"):
        cli._preflight_origins(idx, origins)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "kota-kinabalu" in text, f"the snap was not reported: {text!r}"
    assert "km" in text, "the distance is not reported, only the fact"


def test_a_mask_that_lost_its_coast_fails_even_though_everything_snaps():
    """The bound that the briefed pre-flight would not have had.

    With a snap in place, a land mask missing its entire coastline fails NO
    per-origin check: every coastal city resolves to a cell one ring inland
    and the build spends a day producing a wrong map. Airports have carried
    MAX_SNAPPED_AIRPORT_FRACTION for exactly this reason since the beginning
    (`graph/nodes.py`); origins had nothing.

    Mutation performed and reverted: delete the share check -> red (21 snapped
    origins pass).
    """
    lat, lon = KOTA_KINABALU
    own = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    ring = sorted(h3.grid_ring(own, 1))
    idx = _index(ring)
    # One good origin per ring cell, plus enough snapping ones to break 5%.
    origins = [_origin(f"inland-{i}", *h3.cell_to_latlng(c))
               for i, c in enumerate(ring)] * 30
    coasts = [_origin(f"coast-{i}", lat, lon) for i in range(len(ring) * 30)]
    origins += coasts
    assert len(origins) >= cli.MIN_ORIGINS_FOR_SNAP_BOUND, "the bound is not even armed"
    snapping = len(coasts) / len(origins)
    assert snapping > cli.MAX_SNAPPED_ORIGIN_FRACTION, "the fixture does not exceed the bound"

    with pytest.raises(cli.GateFailure, match="land mask lost coverage"):
        cli._preflight_origins(idx, origins)


def test_one_snap_in_a_thousand_does_not_fail_the_build(caplog):
    """The live roster's real shape: 1 of 1,464 snapped on 2026-09-14. A bound
    that refused that would refuse every build.

    Mutation performed and reverted: make the bound `0.0` -> red.
    """
    lat, lon = KOTA_KINABALU
    own = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    ring = sorted(h3.grid_ring(own, 1))
    idx = _index(ring)
    origins = [_origin(f"inland-{i}", *h3.cell_to_latlng(c))
               for i, c in enumerate(ring)] * 30
    origins.append(_origin("kota-kinabalu", lat, lon))
    assert len(origins) >= cli.MIN_ORIGINS_FOR_SNAP_BOUND, "the bound is not even armed"
    with caplog.at_level(logging.WARNING, logger="transport_maps.cli"):
        cli._preflight_origins(idx, origins)      # must not raise


def test_the_preflight_resolves_origins_the_way_the_solver_does():
    """It must call `snap_origin`, not a private copy of the two-ring walk. A
    copy is free to drift from the search the solve actually performs, and
    then the pre-flight passes an origin `_solve_one` later refuses -- which
    is the 26-hour failure it exists to prevent, restored.

    Mutation performed and reverted: inline a first-found ring search in
    `_preflight_origins` instead of calling `dijkstra.snap_origin` -> red.
    """
    import inspect

    from transport_maps.solve import dijkstra

    source = inspect.getsource(cli._preflight_origins)
    assert "dijkstra.snap_origin(" in source, (
        "the pre-flight no longer resolves through the solver's own snap")
    # ...and the solver's own entry point still goes through it, so the two
    # cannot diverge by changing only one.
    assert "snap_origin(" in inspect.getsource(dijkstra.origin_node)


def test_it_runs_before_the_graph_is_built():
    """Ordering is the entire value: a pre-flight after `build_graph` costs
    the graph assembly (measured at about five minutes, and ~11 GB peak) for
    a message a dictionary lookup could have produced.

    Source order is a weak assertion on its own, so it is paired with the
    behavioural one above. Both would have to be defeated to move the call.

    Mutation performed and reverted: move the `_preflight_origins` call below
    `csr = build.build_graph(...)` -> red.
    """
    import inspect

    source = inspect.getsource(cli._build_all_locked)
    pre = source.index("_preflight_origins(idx, origins)")
    graph = source.index("csr = build.build_graph(")
    assert pre < graph, "the pre-flight runs after the graph is assembled"
    # And after the index, which it needs.
    assert source.index("idx = nodes.build_index(") < pre


def test_it_checks_what_the_run_will_solve_and_not_the_whole_file():
    """`--only seoul` must not abort over a bad coordinate in a city it was
    never going to touch, and `--limit 3` must not skip the check on the three
    it will.

    Mutation performed and reverted: leave `origins = index.load_origins()`
    below the pre-flight and pass the unfiltered list -> red.
    """
    import inspect

    source = inspect.getsource(cli._build_all_locked)
    select = source.index("origins = index.load_origins()")
    pre = source.index("_preflight_origins(idx, origins)")
    assert select < pre, "the pre-flight checks an unfiltered roster"
    assert source.index("origins = origins[:limit]") < pre
    assert source.index('o["slug"] in set(only)') < pre


def test_a_bad_origin_exits_cleanly_rather_than_as_a_traceback():
    """`GateFailure` is a RuntimeError, and the `except GateFailure` that
    turns one into a clean exit sits far below, around the solve loop. A
    pre-flight that raises into the gap reproduces the original defect
    exactly: a traceback out of a build, with no slug.

    Mutation performed and reverted: remove the try/except around the
    pre-flight call -> red.
    """
    import inspect

    source = inspect.getsource(cli._build_all_locked)
    call = source.index("_preflight_origins(idx, origins)")
    window = source[max(0, call - 200):call + 200]
    assert "except GateFailure" in window and "SystemExit" in window, (
        "a pre-flight GateFailure escapes as a traceback")


def test_an_empty_roster_is_not_a_division_by_zero():
    """`--limit 0` is a real invocation (the build has one) and a gate must
    never be the thing that fails a run that has nothing to do.

    Mutation performed and reverted: compute `share` unconditionally -> red
    with ZeroDivisionError.
    """
    cli._preflight_origins(_index([_land_at(*KOTA_KINABALU)]), [])


def test_a_single_snapping_origin_is_not_a_mask_regression():
    """`--only kota-kinabalu` resolves one origin, and that origin snaps. A
    share bound applied to a roster of one reads 100% and aborts the very run
    a maintainer would use to investigate the city that snaps.

    Mutation performed and reverted: drop the MIN_ORIGINS_FOR_SNAP_BOUND
    guard -> red with "the land mask lost coverage".
    """
    lat, lon = KOTA_KINABALU
    own = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    idx = _index(sorted(h3.grid_ring(own, 1)))
    cli._preflight_origins(idx, [_origin("kota-kinabalu", lat, lon)])
