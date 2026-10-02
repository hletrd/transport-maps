"""The suite never asks an upstream about a raw input, including from a
module-scoped fixture (G2).

pytest builds a module-scoped fixture before the function-scoped fixtures of
the test that first uses it, so a per-test "go offline" ran too late for one:
tests/sources/test_airports.py's `df` fetched OurAirports live that way.

Two witnesses, each a module-scoped fixture recording `_fetch.offline()` when
it is built: one built for the FIRST test here (what the session starts as,
when this file runs alone), one first built after a test that turned the
network on (what a test's teardown leaves). Mutations performed and reverted,
running this file alone, each red: drop conftest's session-scoped
`_offline_session` (the first witness); have `_offline_inputs`'s teardown
restore None instead of True (the second).
"""

import pytest

from transport_maps.sources import _fetch


@pytest.fixture(scope="module", autouse=True)
def _no_offline_env():
    """No TRANSPORT_MAPS_OFFLINE in the environment, so only the fixtures can
    make the answer True."""
    mp = pytest.MonkeyPatch()
    mp.delenv(_fetch.OFFLINE_ENV, raising=False)
    yield
    mp.undo()


@pytest.fixture(scope="module")
def at_session_start():
    return _fetch.offline()


@pytest.fixture(scope="module")
def after_an_online_test():
    return _fetch.offline()


def test_a_module_fixture_built_first_runs_offline(at_session_start):
    assert at_session_start, "the session starts online: a first module fixture would fetch live"


def test_a_test_that_turns_the_network_on():
    """Leaves the state a stub-driven test leaves: online."""
    _fetch.set_offline(False)
    assert not _fetch.offline()


def test_a_module_fixture_built_after_it_runs_offline(after_an_online_test):
    assert after_an_online_test, (
        "a module-scoped fixture ran with the network on; one that reads an input "
        "would fetch it live, into the real data/cache for an integration test")
