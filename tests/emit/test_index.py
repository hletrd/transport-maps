import json
from typing import ClassVar

import numpy as np

from transport_maps import config
from transport_maps.emit import index, modes


class FakeIndex:
    cells: ClassVar[list[str]] = ["8530e08ffffffff", "8530e087fffffff", "85754e63fffffff"]
    n_cells = 3


def test_hover_cell_ids_are_sorted_ascending(tmp_path):
    out = tmp_path / "hover_cells.bin"
    index.write_hover_cells(FakeIndex(), out)
    ids = np.frombuffer(out.read_bytes(), dtype="<u8")
    assert len(ids) > 0
    assert (np.diff(ids.astype(object)) > 0).all()


# --- Attribution (C2) --------------------------------------------------------
#
# The licence firewall proves only that no commercial flight records leaked
# into dist/. It says nothing about crediting the open sources that legitimately
# did, so without these tests every gate reports green while the CC-BY-SA and
# ODbL redistribution obligations go unmet.

REQUIRED_ATTRIBUTION = {
    "Wikipedia": "CC BY-SA",
    "OpenStreetMap": "ODbL",
    "GRIP4": None,
    "OurAirports": None,
    "Natural Earth": None,
    "GeoNames": "CC BY",
    "HydroLAKES": "CC BY",
    # The fitted cruise speed and climb/descent penalty are derived from their
    # data, so the ODbL attribution obligation applies to us too.
    "adsb.lol": "ODbL",
}


def _written_index(tmp_path) -> dict:
    out = tmp_path / "index.json"
    index.write_index(
        [{"slug": "seoul", "name": "Seoul", "lat": 37.5665, "lon": 126.9780}], out
    )
    return json.loads(out.read_text(encoding="utf-8"))


def test_index_json_attributes_every_required_source(tmp_path):
    payload = _written_index(tmp_path)
    assert payload["attribution"], "index.json ships no attribution at all"

    by_name = {entry["name"]: entry for entry in payload["attribution"]}
    for required, licence_fragment in REQUIRED_ATTRIBUTION.items():
        match = next((v for k, v in by_name.items() if required in k), None)
        assert match is not None, f"index.json does not attribute {required}"
        assert match["licence"].strip(), f"{required} has an empty licence"
        assert match["url"].strip(), f"{required} has no url"
        if licence_fragment is not None:
            assert licence_fragment in match["licence"], (
                f"{required} must ship under {licence_fragment}, got {match['licence']!r}"
            )


def test_attribution_entries_are_complete_records(tmp_path):
    """Every entry must carry all four fields, so a half-filled row cannot pass
    the per-source lookup above by name alone.
    """
    payload = _written_index(tmp_path)
    for entry in payload["attribution"]:
        assert set(entry) == {"name", "licence", "url", "usedFor"}
        assert all(str(v).strip() for v in entry.values())


def test_index_json_advertises_rail_detail(tmp_path):
    """The page asks for {slug}.rail.bin/.rail.json only when this key is
    present; a build that drops it silently loses station naming.
    """
    assert _written_index(tmp_path)["railDetail"] is True


def test_readme_documents_the_same_sources():
    """The obligation is on the artifact AND on the repo that produces it, and
    the two lists must not drift apart.
    """
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    for entry in index.ATTRIBUTION:
        assert entry["name"] in readme, f"README.md does not credit {entry['name']}"
        assert entry["licence"] in readme, f"README.md omits {entry['name']}'s licence"


def test_an_origins_file_with_no_origins_is_refused(tmp_path):
    """A valid index.json listing nothing is a page that throws on cities[0]."""
    import pytest

    empty = tmp_path / "origins.toml"
    empty.write_text("# nothing here\norigin = []\n")
    with pytest.raises(ValueError, match="no origins"):
        index.load_origins(empty)
    (tmp_path / "none.toml").write_text("title = 'x'\n")
    with pytest.raises(ValueError, match="no origins"):
        index.load_origins(tmp_path / "none.toml")


def test_index_json_can_carry_the_build_identity_the_hover_count_and_the_graph_flags(tmp_path):
    out = tmp_path / "index.json"
    identity = index.build_identity()
    assert set(identity) == {"inputsHash", "buildId", "builtAt"}
    assert identity["buildId"].startswith(identity["inputsHash"] + "-")
    index.write_index([{"slug": "seoul", "name": "Seoul", "lat": 37.5, "lon": 127.0}], out,
                      hover_cell_count=90_740, graph={"rail": True, "ferry": False}, identity=identity)
    payload = json.loads(out.read_text())
    assert payload["hoverCellCount"] == 90_740
    assert payload["graph"] == {"rail": True, "ferry": False}
    assert payload["buildId"] == identity["buildId"] and payload["builtAt"] == identity["builtAt"]
    assert payload["modeChannels"] == list(modes.CHANNELS)


def test_the_build_identity_moves_with_the_inputs(monkeypatch):
    before = index.build_identity()["inputsHash"]
    monkeypatch.setattr(index.config, "HOVER_RES", 3)
    assert index.build_identity()["inputsHash"] != before


def test_mode_detail_reads_the_calibration_it_describes(monkeypatch):
    """The tooltips hard-coded 200/75/35/30, equal to calibration.toml only by
    luck; a 'city over 200,000.0' also reached every road tooltip."""
    from transport_maps.graph import rail

    detail = index.mode_detail()
    assert "200,000 people" in detail["highway"] and "200,000.0" not in detail["highway"]
    assert "GRIP4 class" not in detail["highway"]
    rc = rail.load_rail_calibration()
    assert f"{rc.highspeed_kmh:.0f} km/h" in detail["rail"]
    monkeypatch.setattr(rail, "load_rail_calibration",
                        lambda path=None: rail.RailCalibration(highspeed_kmh=321.0, conventional_kmh=75.0,
                                                               detour_factor=1.2, boarding_min=15.0, alighting_min=5.0))
    assert "321 km/h" in index.mode_detail()["rail"]


def test_origin_slugs_are_validated_where_they_are_read(tmp_path):
    import pytest

    for bad in ("../x", "-seoul", "seo ul", ".hidden", "a/b"):
        f = tmp_path / "o.toml"
        f.write_text(f'[[origin]]\nslug = "{bad}"\nname = "X"\nlat = 0.0\nlon = 0.0\n')
        with pytest.raises(ValueError, match="invalid origin slug"):
            index.load_origins(f)


def test_the_page_credit_fallbacks_agree_with_the_emitters_licences():
    """web/app.js repeats GeoNames and HydroLAKES in PAGE_CREDITS so a build
    whose index.json predates their rows still credits them; the licence
    strings must be the emitter's, not a second opinion."""
    import re

    app = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
    block = app[app.index("const PAGE_CREDITS = ["):]
    block = block[: block.index("];")]
    page = dict(re.findall(r'name: "([^"]+)", licence: "([^"]+)"', block))
    ours = {a["name"]: a["licence"] for a in index.ATTRIBUTION}
    repeated = {n: lic for n, lic in page.items() if n in ours}
    assert repeated, "PAGE_CREDITS no longer repeats an emitter source; drop this test"
    for name, lic in repeated.items():
        assert lic == ours[name], f"{name}: page says {lic}, emitter says {ours[name]}"
