"""scripts/expand_origins.py: a row the gazetteer corrects is no origin."""

from __future__ import annotations

import importlib.util
import sys
import tomllib

from transport_maps import config

ROOT = config.ROOT
spec = importlib.util.spec_from_file_location("expand_origins", ROOT / "scripts" / "expand_origins.py")
expand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(expand)


def _row(gid, name, lat, lon, pop, cc="CN", fcode="PPL"):
    r = dict.fromkeys(expand.COLS, "")
    r.update(id=str(gid), name=name, ascii=name, lat=str(lat), lon=str(lon), pop=str(pop),
             cc=cc, fcode=fcode)
    return r


def test_a_misplaced_or_inflated_row_is_not_added(tmp_path, monkeypatch):
    """The phantom Changzhi (a Yuncheng village carrying 699,514) and
    Camayenne (a Conakry quarter carrying Conakry's population) were origins
    material by population; the real Yuncheng row beside them is.

    Mutations performed and reverted, each RED: drop the `misplaced` test
    (Changzhi added); rank by the raw population (Camayenne added).
    """
    (tmp_path / "data").mkdir()
    roster = tmp_path / "data" / "origins.toml"
    roster.write_text('[[origin]]\nslug = "seoul"\nname = "Seoul"\nlat = 37.5665\nlon = 126.978\n')
    monkeypatch.setattr(expand.config, "ROOT", tmp_path)
    monkeypatch.setattr(expand, "_land_cells_if_built", lambda: None)
    monkeypatch.setattr(expand, "geonames", lambda: [
        _row(1815463, "Changzhi", 35.20889, 111.73861, 699514),
        _row(2422488, "Camayenne", 9.535, -13.68778, 1871242, cc="GN"),
        _row(1785738, "Yuncheng", 35.02306, 110.99278, 700000),
    ])
    monkeypatch.setattr(sys, "argv", ["expand_origins.py", "--min-pop", "300000"])
    expand.main()
    names = [o["name"] for o in tomllib.loads(roster.read_text())["origin"]]
    assert names == ["Seoul", "Yuncheng"]
