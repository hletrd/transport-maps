"""`transport-maps reindex` rewrites index.json from artifacts already on disk.

The command exists because index.json is written by the build's parent process
at the END of the run, from the emit.index module that parent imported at the
START. A build that outlives an emitter change publishes a stale index for
artifacts that are not stale, and the stale index turns off the page's
mixed-build guard, its channel-order guard and its rail-detail fetch.
"""

import json

import pytest

from transport_maps import cli
from transport_maps.emit import modes

N_CELLS = 5
WIDTHS = {".bin": 2, ".air.bin": 2, ".modes.bin": 2 * len(modes.CHANNELS)}


def _origin(slug, lat=0.0, lon=0.0):
    return {"slug": slug, "name": slug.title(), "lat": lat, "lon": lon}


def _artifacts(dist, slug, *, cells=N_CELLS, rail=False, short=None):
    """Write one origin's file set. `short` names a suffix to truncate."""
    out = dist / "origins"
    out.mkdir(parents=True, exist_ok=True)
    for suffix, width in WIDTHS.items():
        n = cells - 1 if short == suffix else cells
        (out / f"{slug}{suffix}").write_bytes(b"\0" * (n * width))
    (out / f"{slug}.json").write_text('{"offsets":{}}')
    (out / f"{slug}.pmtiles").write_bytes(b"PMTiles" + b"\0" * 120)
    if rail:
        (out / f"{slug}.rail.bin").write_bytes(b"\0" * (cells * 4))
        (out / f"{slug}.rail.json").write_text("{}")


@pytest.fixture
def dist(tmp_path, monkeypatch):
    d = tmp_path / "dist"
    (d / "origins").mkdir(parents=True)
    (d / "hover_cells.bin").write_bytes(b"\0" * (N_CELLS * 8))
    # No real build may interfere, and this machine may genuinely be running
    # one: the guard itself is tested separately.
    monkeypatch.setattr(cli, "_other_builds", lambda: [])
    return d


def _reindex(dist, origins, monkeypatch):
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: origins)
    cli._reindex(dist)
    return json.loads((dist / "index.json").read_text())


def test_reindex_stamps_the_keys_a_long_build_publishes_without(dist, monkeypatch):
    """The six fields a stale emitter omits are exactly what this restores."""
    _artifacts(dist, "seoul", rail=True)
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)

    assert idx["hoverCellCount"] == N_CELLS, "the page's mixed-build guard needs this"
    assert idx["modeChannels"] == list(modes.CHANNELS), "the page re-types the order without it"
    assert idx["railDetail"] is True, "false here means the shipped .rail.* is never fetched"
    assert idx["graph"]["rail"] is True
    assert idx["builtAt"] and idx["reindexedAt"]
    assert [o["slug"] for o in idx["origins"]] == ["seoul"]


def test_an_origin_whose_array_is_short_is_not_listed(dist, monkeypatch):
    """Listing a short array is the blank-globe failure the command prevents."""
    _artifacts(dist, "seoul")
    _artifacts(dist, "tokyo", short=".modes.bin")
    idx = _reindex(dist, [_origin("seoul"), _origin("tokyo")], monkeypatch)
    assert [o["slug"] for o in idx["origins"]] == ["seoul"]


def test_an_origin_missing_a_file_is_not_listed(dist, monkeypatch):
    _artifacts(dist, "seoul")
    _artifacts(dist, "tokyo")
    (dist / "origins" / "tokyo.air.bin").unlink()
    idx = _reindex(dist, [_origin("seoul"), _origin("tokyo")], monkeypatch)
    assert [o["slug"] for o in idx["origins"]] == ["seoul"]


def test_rail_detail_is_false_when_no_origin_has_rail_files(dist, monkeypatch):
    _artifacts(dist, "seoul", rail=False)
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert idx["graph"]["rail"] is False


def test_identity_is_carried_forward_not_restamped(dist, monkeypatch):
    """Stamping today's checkout would assert it produced files it did not."""
    _artifacts(dist, "seoul")
    (dist / "index.json").write_text(json.dumps({
        "inputsHash": "deadbeef", "buildId": "deadbeef-20260910T042333Z",
        "builtAt": "2026-09-10T04:23:33+00:00", "origins": [], "graph": {"ferry": True}}))
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert idx["inputsHash"] == "deadbeef"
    assert idx["buildId"] == "deadbeef-20260910T042333Z"
    assert idx["builtAt"] == "2026-09-10T04:23:33+00:00"
    assert idx["graph"]["ferry"] is True, "what the artifacts cannot show is carried, not dropped"
    assert idx["reindexedAt"] != idx["builtAt"]


def test_built_at_falls_back_to_the_hover_file_the_build_wrote_first(dist, monkeypatch):
    """hover_cells.bin is written before the first origin, so its mtime is the start."""
    import os
    os.utime(dist / "hover_cells.bin", (1_757_000_000, 1_757_000_000))
    _artifacts(dist, "seoul")
    idx = _reindex(dist, [_origin("seoul")], monkeypatch)
    assert idx["builtAt"].startswith("2025-09-")


def test_reindex_refuses_while_another_build_is_running(dist, monkeypatch):
    _artifacts(dist, "seoul")
    monkeypatch.setattr(cli, "_other_builds", lambda: [4143, 4144])
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="4143"):
        cli._reindex(dist)
    assert not (dist / "index.json").exists(), "a refusal must not leave a partial index"
    assert not (dist / cli.LOCK_NAME).exists(), "the lock is released on the refusal path"


def test_reindex_refuses_a_dist_with_no_hover_cells(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_other_builds", lambda: [])
    with pytest.raises(SystemExit, match="hover_cells.bin missing"):
        cli._reindex(tmp_path / "empty")


def test_reindex_refuses_when_no_origin_is_complete(dist, monkeypatch):
    monkeypatch.setattr(cli.index, "load_origins", lambda *a, **k: [_origin("seoul")])
    with pytest.raises(SystemExit, match="complete file set"):
        cli._reindex(dist)
