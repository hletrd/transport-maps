"""An origin whose coordinate misses the land mask must snap, not kill the run.

`data/origins.toml` carries gazetteer city centres; the land mask is a 1:10m
outline. The two disagree on any shore the outline cuts inside, and on
2026-09-14 exactly one of the 1,464 origins fell in that gap: Kota Kinabalu at
5.9749, 116.0724 sits on res-6 cell `8668156e7ffffff`, absent from the mask,
with three land cells in ring 1 and the nearest 4.2 km east.

What made that a build-killer rather than a rounding detail is the exception
type. `origin_node` raised a bare `ValueError`; `GateFailure` is a
`RuntimeError` and `cli.py` catches only `GateFailure`; so the run died with a
traceback that did not even name the slug -- at origin 970 of 1,464, 26 hours
in. Airports have had this snap since the beginning (`_place_airports` is
`_nearest_land`'s only other caller). Origins had nothing.

Both tests here run against a hand-built `NodeIndex`, so they need no land
mask, no graph and no build, and they fail for one reason only.
"""

from __future__ import annotations

import h3
import pytest

from transport_maps import config
from transport_maps.emit import index
from transport_maps.graph.nodes import NodeIndex
from transport_maps.solve import dijkstra

# The real coordinate, from data/origins.toml.
KOTA_KINABALU = (5.9749, 116.0724)


def _index(cells: list[str]) -> NodeIndex:
    """A NodeIndex that knows only these cells. Nothing else is touched."""
    return NodeIndex(cells=list(cells), airports=[],
                     _cell_pos={c: i for i, c in enumerate(cells)},
                     _airport_pos={}, _airport_cell={})


def test_an_origin_just_off_the_mask_snaps_to_its_neighbour():
    """Kota Kinabalu's own cell is missing; ring 1 has land. It must resolve.

    Mutation performed and reverted: drop the `_nearest_land` branch from
    `origin_node` -> `ValueError: origin (5.9749, 116.0724) is not on a land
    cell`, which is exactly what killed rebuild19.
    """
    lat, lon = KOTA_KINABALU
    own = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    assert own == "8668156e7ffffff", "the fixture coordinate moved; re-derive it"

    ring = sorted(h3.grid_ring(own, 1))
    idx = _index(ring)                      # every neighbour, but NOT `own`
    assert idx.try_cell_index(own) is None, "the fixture must exclude the cell"

    pos = dijkstra.origin_node(idx, lat, lon)
    assert ring[pos] in ring


def test_the_snap_picks_the_nearest_neighbour_not_the_first_one():
    """`_nearest_land` compares every candidate by distance. If it returned
    first-found instead, an origin would be wired to a cell on the wrong side
    of itself -- silently, since any neighbour resolves to *a* node.

    Mutation performed and reverted: make `_nearest_land` return on its first
    hit -> red (picks the ring in iteration order, 8.0 km away, not 4.2).
    """
    lat, lon = KOTA_KINABALU
    own = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    ring = sorted(h3.grid_ring(own, 1))
    idx = _index(ring)

    pos = dijkstra.origin_node(idx, lat, lon)
    chosen = ring[pos]
    km = {c: h3.great_circle_distance((lat, lon), h3.cell_to_latlng(c), unit="km")
          for c in ring}
    assert chosen == min(km, key=km.get), (
        f"snapped to {chosen} at {km[chosen]:.1f} km when "
        f"{min(km, key=km.get)} is {min(km.values()):.1f} km away")


class _ReachedTheSolver(Exception):
    """Raised by the stubbed solver so a test can stop `_solve_one` right
    after the origin was resolved, and read WHICH node it was resolved to."""

    def __init__(self, source):
        super().__init__(source)
        self.source = source


def _stop_at_the_solver(monkeypatch):
    def solve_from(csr, source, **kwargs):
        raise _ReachedTheSolver(source)
    monkeypatch.setattr(dijkstra, "solve_from", solve_from)


def test_an_origin_in_open_ocean_is_a_named_gate_failure_not_a_traceback(monkeypatch):
    """Two rings reach about 13 km. Beyond that the coordinate is wrong, and
    the run must still abort -- but saying which origin, which is the whole
    difference between a five-minute fix and a lost multi-day build.

    This goes through `cli._solve_one` itself. The version it replaces caught
    the `ValueError` and raised the `GateFailure` in its own body, so it stayed
    green with the guard in `_solve_one` deleted: the mutation certificate
    C12-1c was ticked on was false (C13-11, V13-7). The solver is stubbed to
    fail loudly -- an unresolvable origin must never reach it, and nothing
    after the origin lookup is needed to prove that.

    Mutation performed and reverted: delete the `try`/`except ValueError`
    around `dijkstra.origin_node` in `cli._solve_one` -> red (`ValueError:
    origin (-30.0, -140.0) is not on a land cell` escapes, not `GateFailure`).
    """
    from transport_maps import cli

    # Mid-Pacific. No land within two rings of anything.
    lat, lon = -30.0, -140.0
    own = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    far = h3.latlng_to_cell(0.0, 0.0, config.SOLVE_RES)
    idx = _index([far])
    assert idx.try_cell_index(own) is None
    _stop_at_the_solver(monkeypatch)

    origin = {"slug": "nowhere-pacific", "lat": lat, "lon": lon}
    with pytest.raises(cli.GateFailure, match="not on a land cell") as caught:
        cli._solve_one(origin, idx, csr=None, speeds=None, shared={})
    assert str(caught.value).startswith("nowhere-pacific:"), (
        "the failure must name the slug to fix, not only the coordinate")
    assert isinstance(caught.value.__cause__, ValueError)
    # ...and it is the type the CLI's top level actually catches.
    assert issubclass(cli.GateFailure, RuntimeError)


def test_the_build_solves_a_snapped_origin_from_its_nearest_neighbour(monkeypatch):
    """The other half of C12-1c on the same real code path: `_solve_one` must
    hand the solver the SNAPPED node for Kota Kinabalu rather than abort.

    Mutation performed and reverted: drop the `_nearest_land` branch from
    `dijkstra.snap_origin` -> red (`GateFailure: kota-kinabalu: origin
    (5.9749, 116.0724) is not on a land cell`: rebuild19's failure, now with
    the slug attached).
    """
    from transport_maps import cli

    lat, lon = KOTA_KINABALU
    own = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    ring = sorted(h3.grid_ring(own, 1))
    idx = _index(ring)
    assert idx.try_cell_index(own) is None
    _stop_at_the_solver(monkeypatch)

    km = {c: h3.great_circle_distance((lat, lon), h3.cell_to_latlng(c), unit="km")
          for c in ring}
    with pytest.raises(_ReachedTheSolver) as reached:
        cli._solve_one({"slug": "kota-kinabalu", "lat": lat, "lon": lon}, idx,
                       csr=None, speeds=None, shared={})
    assert ring[reached.value.source] == min(km, key=km.get)


def test_every_charted_origin_has_a_plausible_coordinate():
    """A land/sea check needs the mask, which is a build artifact. What can be
    checked everywhere is cheaper and still catches the class of typo that put
    an origin in the sea: a coordinate outside the valid range, a duplicate
    slug, or a (lat, lon) pair swapped.
    """
    origins = index.load_origins()
    assert len(origins) > 500, "origins.toml did not load"

    slugs = [o["slug"] for o in origins]
    assert len(set(slugs)) == len(slugs), "duplicate slug in data/origins.toml"

    for o in origins:
        assert -90.0 <= o["lat"] <= 90.0, f"{o['slug']}: latitude out of range"
        assert -180.0 <= o["lon"] <= 180.0, f"{o['slug']}: longitude out of range"
        assert not (o["lat"] == 0.0 and o["lon"] == 0.0), f"{o['slug']}: null island"
