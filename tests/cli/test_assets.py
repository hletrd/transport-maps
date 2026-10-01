"""`transport-maps assets`: the static page files, from the repository (E6 / O6).

places.json, airports.json and borders.json are required by check_dist and
fetched by the page, and until this command nothing in the repository called
the three `build(out)` functions that write them. Every test points the
command at a tmp_path; none touches the real dist/.
"""

import json
import os
import sys

import polars as pl
import pytest

from transport_maps import cli
from transport_maps.emit import airports_json, borders, places


@pytest.fixture
def stub_emitters(monkeypatch):
    """Each emitter replaced by one that writes its own name: the command's
    sequencing is under test here, not the downloads behind it."""
    calls: list[str] = []

    def fake(name):
        def build(out):
            calls.append(name)
            out.write_text(name)
            return 1
        return build

    monkeypatch.setattr(places, "build", fake("places"))
    monkeypatch.setattr(airports_json, "build", fake("airports"))
    monkeypatch.setattr(borders, "build", fake("borders"))
    return calls


def test_assets_writes_all_three_files_and_releases_the_lock(tmp_path, stub_emitters):
    """Mutation performed and reverted: dropping an entry from cli.ASSETS
    turns this red."""
    cli._assets(tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {"places.json", "airports.json", "borders.json"}
    assert sorted(stub_emitters) == ["airports", "borders", "places"]
    assert not (tmp_path / cli.LOCK_NAME).exists()


def test_assets_writes_only_the_files_named(tmp_path, stub_emitters):
    cli._assets(tmp_path, ["airports.json"])
    assert stub_emitters == ["airports"]
    assert [p.name for p in tmp_path.iterdir()] == ["airports.json"]


def test_assets_refuses_while_a_build_holds_dist(tmp_path, stub_emitters):
    """It writes into the directory a build-all or reindex rewrites, so it
    takes the same lock. Mutation performed and reverted: skipping
    `_acquire_lock` turns this red (the files are written under a live
    build's lock)."""
    (tmp_path / cli.LOCK_NAME).write_text(f"{os.getpid()} 2026-10-02T00:00:00Z\n")
    with pytest.raises(SystemExit, match="held by a running build"):
        cli._assets(tmp_path)
    assert stub_emitters == []
    assert sorted(p.name for p in tmp_path.iterdir()) == [cli.LOCK_NAME]


def test_an_unknown_asset_is_refused_before_anything_is_written(tmp_path, stub_emitters):
    with pytest.raises(SystemExit, match="unknown asset"):
        cli._assets(tmp_path, ["places.json", "water.pmtiles"])
    assert stub_emitters == []
    assert list(tmp_path.iterdir()) == []


def test_the_subcommand_dispatches_to_assets(monkeypatch):
    """Mutation performed and reverted: removing the `assets` branch from
    main() turns this red (argparse accepts the command, nothing runs)."""
    seen: list = []
    monkeypatch.setattr(cli, "_assets", lambda names=None: seen.append(names))
    monkeypatch.setattr(cli.config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(sys, "argv", ["transport-maps", "assets", "borders.json"])
    cli.main()
    assert seen == [["borders.json"]]


def test_airports_json_is_the_columnar_table_the_page_reads(tmp_path, monkeypatch):
    """The real emitter on a stubbed source: the column order app.js reads by
    position, rounded coordinates, and the count it reports."""
    monkeypatch.setattr(airports_json.airports, "scheduled_airports", lambda: pl.DataFrame({
        "iata": ["ICN", "GMP"], "name": ["Incheon", "Gimpo"], "country": ["KR", "KR"],
        "lat": [37.46019, 37.55831], "lon": [126.44070, 126.79061], "size": ["large", "large"]}))
    assert cli.ASSETS["airports.json"] == "airports_json"
    out = tmp_path / "airports.json"
    assert airports_json.build(out) == 2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["fields"] == ["iata", "name", "country", "lat", "lon", "size"]
    assert payload["airports"][0] == ["ICN", "Incheon", "KR", 37.46, 126.441, "large"]
