"""Wikidata resolution must not hand back a partial mapping (C1).

`routes.route_network` writes its result to routes.parquet and returns that
file on every later call, so a title silently omitted here is a route
permanently missing from the shipped network -- the "retry on the next call"
the old message promised structurally never happens.
"""

import pytest

from transport_maps import config
from transport_maps.sources import wikidata


def _stub_client(monkeypatch):
    """Neutralise the real HTTP client; _resolve_batch is stubbed per test."""
    class _NoopClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(wikidata.httpx, "Client", lambda **kw: _NoopClient())
    monkeypatch.setattr(wikidata.time, "sleep", lambda s: None)


def test_refuses_when_a_batch_fails_outright(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE", tmp_path)
    _stub_client(monkeypatch)

    def _boom(client, batch):
        raise RuntimeError("API error: readonly")

    monkeypatch.setattr(wikidata, "_resolve_batch", _boom)

    with pytest.raises(RuntimeError, match="refusing to persist a partial route network"):
        wikidata.iata_for_titles(["Alpha", "Beta"])


def test_refuses_when_a_title_is_left_unconfirmed(tmp_path, monkeypatch):
    """The subtler half: the batch succeeded, but one title came back
    unconfirmed (e.g. wbgetentities reported it under a redirect target). It
    is correctly left un-cached -- and must therefore also block the write.
    """
    monkeypatch.setattr(config, "CACHE", tmp_path)
    _stub_client(monkeypatch)
    monkeypatch.setattr(
        wikidata, "_resolve_batch", lambda client, batch: {"Alpha": "AAA"}
    )

    with pytest.raises(RuntimeError, match="Beta"):
        wikidata.iata_for_titles(["Alpha", "Beta"])


def test_everything_resolved_before_the_failure_is_still_cached(tmp_path, monkeypatch):
    """The refusal must not throw away progress: a re-run has to resume cheaply."""
    monkeypatch.setattr(config, "CACHE", tmp_path)
    _stub_client(monkeypatch)
    monkeypatch.setattr(
        wikidata, "_resolve_batch", lambda client, batch: {"Alpha": "AAA"}
    )

    with pytest.raises(RuntimeError):
        wikidata.iata_for_titles(["Alpha", "Beta"])

    assert (tmp_path / "wikidata_iata.json").exists()
    import json
    assert json.loads((tmp_path / "wikidata_iata.json").read_text())["Alpha"] == "AAA"


def test_a_fully_resolved_run_returns_normally(tmp_path, monkeypatch):
    """Companion guard: always raising would pass the three tests above."""
    monkeypatch.setattr(config, "CACHE", tmp_path)
    _stub_client(monkeypatch)
    monkeypatch.setattr(
        wikidata, "_resolve_batch",
        lambda client, batch: {"Alpha": "AAA", "Beta": ""},
    )

    got = wikidata.iata_for_titles(["Alpha", "Beta"])

    assert got == {"Alpha": "AAA"}  # Beta confirmed not an airport, so omitted
