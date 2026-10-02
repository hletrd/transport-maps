"""`build-all` checks every raw input before anything reads one (G2), and
`--offline` asks nothing at all.

The upstreams are a stub behind `_fetch._stream` that records every URL it is
asked for; the OSM scripts and the route crawl are stubbed out (they have
their own tests: tests/sources/test_geofabrik.py, tests/test_osm_scripts.py,
tests/sources/test_routes.py). What is under test is the LIST: that a build
asks about each input it reads, and that offline it asks about none.
"""

import contextlib
import sys

import httpx
import pytest

from tests.test_cli import _stub_pipeline
from transport_maps import cli, config
from transport_maps.sources import (
    _fetch,
    airports,
    countries,
    geofabrik,
    landmask,
    roads,
    routes,
    urban,
)


def _file_urls() -> set[str]:
    return ({airports.AIRPORTS_URL, landmask.LAND_URL, landmask.ICE_URL, landmask.LAKES_URL,
             countries.COUNTRIES_URL, urban.PLACES_URL}
            | {roads.GRIP4_URL.format(n=n) for n in range(1, roads.N_TYPES + 1)})


def _state_urls() -> set[str]:
    return {geofabrik.STATE_URL.format(region=r) for r in geofabrik.REGIONS}


class _Resp:
    def __init__(self, status, body=b""):
        self.status_code = status
        self.headers = httpx.Headers({"etag": '"e"'})
        self._body = body

    def iter_bytes(self, _n):
        yield self._body

    def raise_for_status(self):
        pass


@pytest.fixture
def world(tmp_path, monkeypatch):
    """An empty cache, every upstream answering, the scripts and crawl stubbed."""
    monkeypatch.setattr(config, "CACHE", tmp_path)
    asked: list[str] = []

    def stream(url, headers, timeout):
        asked.append(url)
        if url.endswith("state.txt"):
            return contextlib.nullcontext(_Resp(200, b"timestamp=2026-10-01T20\\:21\\:30Z\n"))
        return contextlib.nullcontext(_Resp(304 if headers else 200, b"bytes of " + url.encode()))
    monkeypatch.setattr(_fetch, "_stream", stream)
    crawled: list[int] = []
    monkeypatch.setattr(routes, "route_network", lambda: crawled.append(1))
    monkeypatch.setattr(geofabrik.subprocess, "run",
                        lambda cmd, env, check: type("D", (), {"returncode": 0})())
    monkeypatch.setattr(geofabrik.shutil, "which", lambda tool: None)
    return asked, crawled


def test_a_build_asks_about_every_input_it_reads(world):
    """Mutation: drop any one line of `_check_inputs` -> red (its URLs are
    missing from what was asked)."""
    asked, crawled = world
    _fetch.set_offline(False)
    cli._check_inputs()
    assert set(asked) == _file_urls() | _state_urls()
    assert len(asked) == len(set(asked)), "an input was asked about twice in one build"
    assert crawled == [1], "the Wikipedia crawl is an input too"
    assert set(_fetch.used()) >= _file_urls() | {f"geofabrik:{r}-rail" for r in geofabrik.REGIONS}


def test_a_no_air_variant_does_not_crawl_the_route_network(world):
    _asked, crawled = world
    _fetch.set_offline(False)
    cli._check_inputs(exclude="air")
    assert crawled == []


def test_offline_asks_no_upstream_and_reads_every_cached_input(world, tmp_path):
    """Mutation: make `--offline` set nothing (below), or let `_fetch.fetch`
    ignore offline() -> red (requests are made)."""
    asked, crawled = world
    _fetch.set_offline(False)
    cli._check_inputs()                              # a first, online build fills the cache
    asked.clear()
    _fetch.reset()
    _fetch.set_offline(True)
    cli._check_inputs()
    assert asked == []
    assert set(_fetch.used()) >= _file_urls()
    assert {fp.status for fp in _fetch.checked()} == {"offline"}


def test_offline_with_an_input_missing_fails_rather_than_fetching(world, tmp_path):
    asked, _ = world
    _fetch.set_offline(True)
    with pytest.raises(_fetch.MissingInput, match="offline"):
        cli._check_inputs()
    assert asked == []


@pytest.mark.parametrize("argv,offline", [
    (["build-all", "--offline"], True),
    (["build-all"], False),
    (["assets", "--offline"], True),
])
def test_the_offline_flag_reaches_the_input_layer(monkeypatch, argv, offline):
    """Mutation: drop `_fetch.set_offline(True)` from main() -> red."""
    seen: list[bool] = []
    monkeypatch.setattr(cli, "_build_all", lambda **kw: seen.append(_fetch.offline()))
    monkeypatch.setattr(cli, "_assets", lambda **kw: seen.append(_fetch.offline()))
    _fetch.set_offline(False)
    monkeypatch.setattr(sys, "argv", ["transport-maps", *argv])
    cli.main()
    assert seen == [offline]


def test_the_inputs_are_checked_before_the_identity_records_them(monkeypatch, tmp_path):
    """build_identity records `_fetch.used()`; sampled before the check, it
    would name inputs from an older run's cache, or none. Mutation: move
    `_check_inputs` after `build_identity` -> red."""
    monkeypatch.setattr(cli.config, "DIST", tmp_path)
    _stub_pipeline(monkeypatch, [], coverages=[1.0, 1.0])
    order: list[str] = []
    monkeypatch.setattr(cli, "_check_inputs", lambda exclude=None: order.append("inputs"))
    real = cli.index.build_identity
    monkeypatch.setattr(cli.index, "build_identity",
                        lambda started=None: (order.append("identity"), real(started))[1])
    monkeypatch.setattr(cli.index, "write_index", lambda origins, out, **kw: None)
    cli._build_all()
    assert order == ["inputs", "identity"]
