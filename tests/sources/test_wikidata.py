"""Wikidata resolution must not hand back a partial mapping (C1).

`routes.route_network` writes its result to a stamped routes_<key>.parquet and
returns that file on every later call with the same inputs, so a title
silently omitted here is a route
permanently missing from the shipped network -- the "retry on the next call"
the old message promised structurally never happens.
"""

import pytest

from transport_maps import config
from transport_maps.sources import wikidata


@pytest.fixture(autouse=True)
def _online():
    """The client is stubbed in every test here (G2: the suite runs offline)."""
    from transport_maps.sources import _fetch

    _fetch.set_offline(False)


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
    assert wikidata._load_cache()["Alpha"] == "AAA"


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


# --- G2: titles are re-resolved after TITLE_MAX_AGE --------------------------


def _ago(**kw) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(**kw)).replace(microsecond=0).isoformat()


def test_a_title_older_than_the_max_age_is_resolved_again(tmp_path, monkeypatch):
    """Mutation: resolve only the uncached titles (the pre-G2 rule) -> red."""
    monkeypatch.setattr(config, "CACHE", tmp_path)
    _stub_client(monkeypatch)
    wikidata._save_cache({"Old": "OLD", "New": "NEW"},
                         {"Old": _ago(days=31), "New": _ago(days=1)})
    asked: list[list[str]] = []
    monkeypatch.setattr(wikidata, "_resolve_batch",
                        lambda client, batch: asked.append(list(batch)) or {"Old": "MOV"})
    got = wikidata.iata_for_titles(["Old", "New"])
    assert asked == [["Old"]]
    assert got == {"Old": "MOV", "New": "NEW"}


def test_a_legacy_cache_is_re_resolved_and_a_failure_keeps_its_codes(tmp_path, monkeypatch):
    """A flat pre-version cache has no times; every title is due. Wikidata
    failing must not fail a build that has a code for every title.
    Mutation: count a failed refresh as unresolved -> red (refusal)."""
    monkeypatch.setattr(config, "CACHE", tmp_path)
    _stub_client(monkeypatch)
    (tmp_path / "wikidata_iata.json").write_text('{"Narita International Airport": "NRT"}')

    def boom(client, batch):
        raise RuntimeError("API error: maxlag")
    monkeypatch.setattr(wikidata, "_resolve_batch", boom)
    assert wikidata.iata_for_titles(["Narita International Airport"]) == {
        "Narita International Airport": "NRT"}


def test_offline_asks_nothing_and_refuses_what_was_never_resolved(tmp_path, monkeypatch):
    from transport_maps.sources import _fetch

    monkeypatch.setattr(config, "CACHE", tmp_path)
    wikidata._save_cache({"Old": "OLD"}, {"Old": _ago(days=90)})
    _fetch.set_offline(True)
    monkeypatch.setattr(wikidata.httpx, "Client", lambda **kw: pytest.fail("a client offline"))
    assert wikidata.iata_for_titles(["Old"]) == {"Old": "OLD"}
    with pytest.raises(RuntimeError, match="Never"):
        wikidata.iata_for_titles(["Old", "Never"])
