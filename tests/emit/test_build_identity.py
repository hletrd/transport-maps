"""inputsHash must move when any input that shapes the artifacts moves.

`build_identity()` exists so two builds can be told apart. Its docstring lists
what it covers, and nothing checked the list: dropping `SOLVE_RES`, `FINE_RES`
and `BAND_EDGES_MIN` from the `params_hash` call left the whole suite green,
and a res-5 build and a res-6 build then shared a `buildId` -- exactly the
mixture `scripts/check_dist.py` says "passes every length check".

Each term is tested by MOVING it and asserting the hash moves, which is the
only form of this test that cannot pass with the term removed.
"""

import pytest

from transport_maps import config
from transport_maps.emit import index, modes

#: Every constant `build_identity`'s docstring claims to cover, with a value
#: that differs from the real one. A term missing from the hash fails here.
STAMPED = {
    "SOLVE_RES": (config, 5),
    "FINE_RES": (config, 8),
    "HOVER_RES": (config, 3),
    "BAND_EDGES_MIN": (config, (30, 60, 120)),
    "UNREACHABLE": (config, 65534),
    "READING_RES": (config, 5),
    "READING_PARENT_RES": (config, 2),
    "READING_SLOTS": (config, 49),
}


def test_the_stamp_exists_at_all():
    ident = index.build_identity()
    assert ident["inputsHash"] and ident["buildId"].startswith(ident["inputsHash"])
    assert ident["builtAt"]


@pytest.mark.parametrize("name", sorted(STAMPED))
def test_moving_a_governing_constant_moves_the_stamp(name, monkeypatch):
    before = index.build_identity()["inputsHash"]
    module, other = STAMPED[name]
    assert getattr(module, name) != other, f"{name}'s test value equals its real one"
    monkeypatch.setattr(module, name, other)
    after = index.build_identity()["inputsHash"]
    assert after != before, (
        f"inputsHash does not cover {name}: two builds differing only in it would "
        "share a buildId, and the field that exists to tell artifacts apart could "
        "not tell those two apart")


def test_the_mode_channel_order_is_stamped(monkeypatch):
    """.modes.bin's channel order is a wire format. Two builds with different
    channel orders produce arrays of identical length."""
    before = index.build_identity()["inputsHash"]
    monkeypatch.setattr(modes, "CHANNELS", tuple(reversed(modes.CHANNELS)))
    assert index.build_identity()["inputsHash"] != before


def test_two_runs_of_one_input_set_stay_distinguishable():
    """buildId adds the start time, so an aborted run and its retry differ."""
    from datetime import UTC, datetime
    a = index.build_identity(datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC))
    b = index.build_identity(datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC))
    assert a["inputsHash"] == b["inputsHash"]
    assert a["buildId"] != b["buildId"]


def test_every_constant_the_docstring_names_is_in_the_table():
    """Guards the table above: a term added to params_hash without a row here
    would be untested, which is how the three missing ones got in."""
    import inspect
    source = inspect.getsource(index.build_identity)
    body = "\n".join(ln for ln in source.splitlines() if not ln.strip().startswith("#"))
    called = {n for n in STAMPED if f"config.{n}" in body}
    assert called == set(STAMPED), (
        f"params_hash references config constants with no row in STAMPED: "
        f"{sorted(set(called) ^ set(STAMPED))}")
    for name in STAMPED:
        assert f"config.{name}" in body, f"{name} has a row here but is not stamped"
