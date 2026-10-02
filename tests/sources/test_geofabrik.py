"""OSM extracts against Geofabrik's replication state (G2).

The build reads each region's state.txt through `_fetch._stream`, replaced
here by a stub; the re-extract scripts are never run (`subprocess.run` is
replaced too). PBFs are written here with the header timestamp a Geofabrik
extract carries, so the snapshot every OSM cache now keys on is known.
"""

import contextlib
import logging
import os
from datetime import datetime

import httpx
import osmium
import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import _fetch, fixed_links, geofabrik, osm

SEP20 = "2026-09-20T20:22:06Z"
OCT01 = "2026-10-01T20:21:30Z"
TRAIN = {"type": "route", "route": "train", "name": "Test Line"}


def write_pbf(path, ts=SEP20, names=("A", "B")):
    header = osmium.io.Header()
    if ts:
        header.set("osmosis_replication_timestamp", ts)
    w = osmium.SimpleWriter(str(path), header=header, overwrite=True)
    for i, name in enumerate(names, start=1):
        w.add_node(osmium.osm.mutable.Node(id=i, location=(float(i), 40.0),
                                           tags={"name": name}))
    w.add_relation(osmium.osm.mutable.Relation(
        id=7, members=[("n", i, "stop") for i in range(1, len(names) + 1)], tags=TRAIN))
    w.close()


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class _State:
    status_code = 200

    def __init__(self, body: bytes):
        self.headers = httpx.Headers({})
        self._body = body

    def iter_bytes(self, _n):
        yield self._body

    def raise_for_status(self):
        pass


@pytest.fixture
def geofabrik_says(monkeypatch):
    """Answer every state.txt with one timestamp (or a failure), online."""
    asked: list[str] = []

    def install(ts: str | None):
        def stream(url, headers, timeout):
            asked.append(url)
            if ts is None:
                raise httpx.ConnectError("download.geofabrik.de unreachable")
            body = f"#Thu Oct 01 21:00:00 UTC 2026\nsequenceNumber=4931\ntimestamp={ts.replace(':', chr(92) + ':')}\n"
            return contextlib.nullcontext(_State(body.encode()))
        _fetch.set_offline(False)
        monkeypatch.setattr(_fetch, "_stream", stream)
        return asked
    return install


@pytest.fixture
def runs(monkeypatch):
    """Every script refresh() would run, recorded instead of run."""
    calls: list[tuple[list[str], dict]] = []

    def run(cmd, env, check):
        calls.append((cmd, env))
        return type("Done", (), {"returncode": 0})()
    monkeypatch.setattr(geofabrik.subprocess, "run", run)
    return calls


# --- reading the two timestamps ------------------------------------------------


def test_the_snapshot_is_the_header_timestamp_and_absent_without_one(tmp_path):
    write_pbf(tmp_path / "a.osm.pbf")
    write_pbf(tmp_path / "b.osm.pbf", ts=None)
    assert geofabrik.snapshot(tmp_path / "a.osm.pbf") == _dt(SEP20)
    assert geofabrik.snapshot(tmp_path / "b.osm.pbf") is None


def test_state_txt_is_parsed_with_its_escaped_colons(geofabrik_says):
    asked = geofabrik_says(OCT01)
    assert geofabrik.upstream("asia") == _dt(OCT01)
    assert asked == ["https://download.geofabrik.de/asia-updates/state.txt"]


def test_stale_means_behind_by_the_max_age(monkeypatch):
    e = geofabrik.Extract("asia", "rail", _dt(SEP20), _dt(OCT01))     # 11 days behind
    assert e.stale
    monkeypatch.setenv(geofabrik.MAX_AGE_ENV, "30")
    assert not e.stale
    monkeypatch.setenv(geofabrik.MAX_AGE_ENV, "0")
    assert geofabrik.Extract("asia", "rail", _dt(SEP20), _dt("2026-09-21T20:22:06Z")).stale, \
        "0 means any newer dated file is re-extracted"
    assert not geofabrik.Extract("asia", "rail", _dt(OCT01), _dt(OCT01)).stale, \
        "an extract at the upstream's snapshot is current even at 0 (mutation: >= alone -> red)"
    assert not geofabrik.Extract("asia", "rail", _dt(SEP20), None).stale, "unchecked is not stale"
    assert geofabrik.Extract("asia", "rail", None, _dt(OCT01)).stale, "absent is stale"


# --- refresh(): which scripts run ---------------------------------------------


def test_only_the_stale_regions_are_re_extracted(tmp_path, geofabrik_says, runs, monkeypatch):
    """Mutation: run the script for every region regardless of staleness ->
    red (asia, current, is re-downloaded)."""
    monkeypatch.setattr(geofabrik.shutil, "which", lambda tool: "/usr/bin/osmium")
    write_pbf(tmp_path / "europe.osm.pbf", ts=SEP20)
    write_pbf(tmp_path / "europe-rail.osm.pbf", ts=SEP20)
    write_pbf(tmp_path / "asia.osm.pbf", ts=OCT01)
    write_pbf(tmp_path / "asia-rail.osm.pbf", ts=OCT01)
    geofabrik_says(OCT01)
    geofabrik.refresh(tmp_path, regions=("europe", "asia"))
    assert [(c[0][1].rsplit("/", 1)[-1], c[0][2:]) for c in runs] == [
        ("osm_fixed_links.sh", ["europe"]), ("osm_rail.sh", ["europe"])]
    for _cmd, env in runs:
        assert env["OSM_REPLACE"] == "1" and env["OSM_DIR"] == str(tmp_path)


def test_without_the_osmium_tool_a_stale_rail_extract_is_kept_and_said(
        tmp_path, geofabrik_says, runs, monkeypatch, caplog):
    monkeypatch.setattr(geofabrik.shutil, "which", lambda tool: None)
    write_pbf(tmp_path / "europe.osm.pbf", ts=OCT01)
    write_pbf(tmp_path / "europe-rail.osm.pbf", ts=SEP20)
    geofabrik_says(OCT01)
    with caplog.at_level(logging.WARNING):
        geofabrik.refresh(tmp_path, regions=("europe",))
    assert runs == []
    assert any("osmium command-line tool is not installed" in r.getMessage()
               for r in caplog.records)


def test_an_unreachable_geofabrik_runs_nothing_and_builds_on(
        tmp_path, geofabrik_says, runs, caplog):
    """A failed check is a warning, never a dead build (and never a 70 GB
    download on the strength of a missing answer)."""
    write_pbf(tmp_path / "europe-rail.osm.pbf", ts=SEP20)
    geofabrik_says(None)
    with caplog.at_level(logging.WARNING):
        found = geofabrik.refresh(tmp_path, regions=("europe",))
    assert runs == [] and not any(e.stale for e in found)
    assert any("could not read" in r.getMessage() for r in caplog.records)


def test_offline_asks_nothing_and_runs_nothing(tmp_path, runs, monkeypatch, caplog):
    """Mutation: drop the offline branch in refresh() -> red. (`get_text`
    refuses offline as well, so nothing would be asked either way; what the
    branch adds is that offline is a choice, not seven "could not read"
    warnings in the build log.)"""
    monkeypatch.setattr(_fetch, "_stream", lambda *a: pytest.fail("asked Geofabrik offline"))
    _fetch.set_offline(True)
    write_pbf(tmp_path / "europe-rail.osm.pbf", ts=SEP20)
    with caplog.at_level(logging.WARNING):
        found = geofabrik.refresh(tmp_path, regions=("europe",))
    assert not caplog.records, [r.getMessage() for r in caplog.records]
    assert runs == []
    rail = next(e for e in found if e.kind == "rail")
    assert rail.local == _dt(SEP20) and rail.upstream is None
    assert _fetch.used()["geofabrik:europe-rail"]["snapshot"] == _dt(SEP20).isoformat()


def test_a_full_extract_deleted_after_its_parse_is_dated_by_its_cache(
        tmp_path, monkeypatch, geofabrik_says, runs):
    """The raw extracts are 70 GB and may go once parsed; the cache's name
    then says which snapshot it holds, so a current cache is not refreshed.
    Mutation: drop the snapshot from the fixed-link source key -> red."""
    monkeypatch.setattr(config, "CACHE", tmp_path)
    (tmp_path / "osm").mkdir()
    raw = tmp_path / "osm" / "europe.osm.pbf"
    write_pbf(raw, ts=OCT01)
    pl.DataFrame([], schema=fixed_links.SCHEMA).write_parquet(
        fixed_links._cache_path("europe", fixed_links._source_key(raw)))
    raw.unlink()
    assert fixed_links.cached_snapshot("europe") == _dt(OCT01)
    geofabrik_says(OCT01)
    monkeypatch.setattr(geofabrik.shutil, "which", lambda tool: None)
    found = geofabrik.refresh(tmp_path / "osm", regions=("europe",))
    assert not next(e for e in found if e.kind == "full").stale
    assert runs == [], "a current cache sent the region to osm_fixed_links.sh"


# --- the derived caches key on the snapshot ------------------------------------


def test_the_rail_cache_follows_the_snapshot_not_the_mtime(tmp_path):
    """A copy (new mtime, same snapshot) is the same extract; a new snapshot
    of the same size is not. Mutation: key on mtime again -> red at the copy
    (a needless re-parse); drop the size and snapshot -> red at the refresh."""
    p = tmp_path / "x-rail.osm.pbf"
    write_pbf(p, ts=SEP20)
    parsed = []
    real = osm._parse
    osm_parse = lambda path: parsed.append(path) or real(path)  # noqa: E731
    import unittest.mock
    with unittest.mock.patch.object(osm, "_parse", osm_parse):
        osm.rail_routes(extracts_dir=tmp_path)
        t = os.stat(p).st_mtime_ns + 5_000_000_000
        os.utime(p, ns=(t, t))                      # copied: same bytes, new mtime
        osm.rail_routes(extracts_dir=tmp_path)
        assert len(parsed) == 1, "a copied extract was parsed again"
        write_pbf(p, ts=OCT01, names=("C", "D"))     # same size, a newer snapshot
        os.utime(p, ns=(t, t))                      # and even the same mtime
        assert osm.rail_routes(extracts_dir=tmp_path)["name"].to_list() == ["C", "D"]
        assert len(parsed) == 2


def test_a_cache_keyed_by_mtime_before_g2_is_adopted_not_reparsed(tmp_path):
    """Its old key names exactly this file (name, size, mtime), so it is the
    same answer. Mutation: drop the adopt() call -> red (a re-parse)."""
    p = tmp_path / "x-rail.osm.pbf"
    write_pbf(p, ts=SEP20)
    legacy = osm._rail_cache_path(osm._fingerprint(tmp_path, [p], by_mtime=True))
    sentinel = osm.rail_routes(extracts_dir=tmp_path).with_columns(pl.lit("adopted").alias("name"))
    osm._rail_cache_path(osm._fingerprint(tmp_path, [p])).unlink()
    sentinel.write_parquet(legacy)
    assert set(osm.rail_routes(extracts_dir=tmp_path)["name"]) == {"adopted"}
    assert not legacy.exists()


def test_a_fixed_link_cache_keyed_by_mtime_is_adopted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE", tmp_path)
    (tmp_path / "osm").mkdir()
    raw = tmp_path / "osm" / "asia.osm.pbf"
    write_pbf(raw, ts=SEP20)
    legacy = fixed_links._cache_path("asia", fixed_links._mtime_key(raw))
    pl.DataFrame([], schema=fixed_links.SCHEMA).write_parquet(legacy)
    got = fixed_links._source("asia", tmp_path / "osm")
    assert got == fixed_links._cache_path("asia", fixed_links._source_key(raw))
    assert got.exists() and not legacy.exists()
    assert fixed_links._source_key(raw).startswith("20260920T202206Z-")
