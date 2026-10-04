"""borders.pmtiles: which lines are drawn, how each is classed, how fine.

The emitter reads two GeoPackage-shaped inputs, so each test writes a few
lines of its own in the source's schema instead of downloading 70 MB: LSIB's
RANK and COUNTRY1/2, Natural Earth's ne_id and FEATURECLA. The tiling tests
run the real tippecanoe and read the archive back with tippecanoe-decode.
"""

import json
import re
import shutil
import subprocess

import pyarrow as pa
import pyogrio
import pytest
import shapely

from transport_maps import config
from transport_maps.emit import borders

needs_tippecanoe = pytest.mark.skipif(
    shutil.which("tippecanoe") is None or shutil.which("tippecanoe-decode") is None,
    reason="tippecanoe is not on PATH")


def _write(path, layer, rows):
    """A GeoPackage line layer of `rows`, each a dict with a "geometry"."""
    cols = {k: [r[k] for r in rows] for k in rows[0] if k != "geometry"}
    table = pa.table({**{k: pa.array(v) for k, v in cols.items()},
                      "geom": pa.array([shapely.to_wkb(r["geometry"]) for r in rows],
                                       type=pa.binary())})
    pyogrio.write_arrow(table, path, layer=layer, driver="GPKG", geometry_name="geom",
                        geometry_type="LineString", crs="EPSG:4326")
    return path


def _lsib(tmp_path, rows, layer=borders.LSIB_LAYER):
    full = [{"ID": str(i), "COUNTRY1": "A", "COUNTRY2": "B", **r} for i, r in enumerate(rows)]
    return _write(tmp_path / "lsib.gpkg", layer, full)


LINE = shapely.LineString([(35.0, 31.0), (35.1, 31.1)])


def test_each_lsib_rank_gets_its_own_kind(tmp_path):
    """LSIB asks a map to keep its three ranks visually distinct; the page
    can only do that if the rank survives as `kind`."""
    path = _lsib(tmp_path, [{"RANK": "1", "geometry": LINE},
                            {"RANK": "2", "geometry": LINE},
                            {"RANK": "3", "geometry": LINE}])
    assert [f["kind"] for f in borders.lsib_features(path)] == [
        "international", "other", "special"]


def test_the_golan_lines_are_not_drawn_as_international_boundaries(tmp_path):
    """LSIB ranks Israel/Syria (the 1974 line) and the Golan's edge with
    Lebanon as international since the 2019 U.S. recognition; Natural Earth,
    the previous source, does not. Mutation performed and reverted: emptying
    GOLAN_PAIRS turns this red."""
    path = _lsib(tmp_path, [
        {"RANK": "1", "COUNTRY1": "ISRAEL", "COUNTRY2": "SYRIA", "geometry": LINE},
        {"RANK": "1", "COUNTRY1": "ISRAEL", "COUNTRY2": "LEBANON", "geometry": LINE},
        {"RANK": "1", "COUNTRY1": "ISRAEL", "COUNTRY2": "JORDAN", "geometry": LINE},
        {"RANK": "1", "COUNTRY1": "SYRIA", "COUNTRY2": "ISRAEL", "geometry": LINE}])
    assert [f["kind"] for f in borders.lsib_features(path)] == [
        "other", "other", "international", "other"]


def test_a_new_lsib_edition_is_refused_until_it_is_reviewed(tmp_path):
    """The corrections were reviewed against one edition, and the URL always
    serves the newest. Mutation performed and reverted: dropping the layer
    check reads the renamed layer and turns this red."""
    path = _lsib(tmp_path, [{"RANK": "1", "geometry": LINE}],
                 layer="Department of State LSIB v12.0 01Jan2027")
    with pytest.raises(RuntimeError, match="new LSIB edition"):
        borders.lsib_features(path)


def test_an_unknown_rank_is_refused_rather_than_drawn_as_something(tmp_path):
    path = _lsib(tmp_path, [{"RANK": "4", "geometry": LINE}])
    with pytest.raises(RuntimeError, match="rank '4'"):
        borders.lsib_features(path)


def test_the_lsib_cache_is_keyed_on_its_edition(monkeypatch):
    """CLAUDE.md: a cache keys on the constants that govern it. The URL never
    changes between editions, so a cache named for the URL alone would keep
    the old edition after LSIB_LAYER moved. Mutation performed and reverted:
    naming the cache "LSIB.gpkg" turns this red."""
    names = []
    monkeypatch.setattr(borders, "_download", lambda url, name: names.append(name))
    borders._lsib_path()
    monkeypatch.setattr(borders, "LSIB_LAYER", "Department of State LSIB v12.0 01Jan2027")
    borders._lsib_path()
    assert names[0] != names[1]
    assert all(n.endswith(".gpkg") for n in names)


def _ne(tmp_path, rows):
    return _write(tmp_path / "ne.gpkg", "ne", rows)


def test_natural_earth_lines_are_kept_only_by_id_and_classed_by_feature(tmp_path, monkeypatch):
    """Only the reviewed lines come from Natural Earth; its overlay and lease
    limits are LSIB's rank 3 (DMZ edges, Guantanamo), everything else rank 2.
    Mutation performed and reverted: keeping every Natural Earth line turns
    this red, as does classing every kept line `other`."""
    monkeypatch.setattr(borders, "NE_KEPT", {11: "a de facto line", 12: "a buffer zone"})
    path = _ne(tmp_path, [
        {"ne_id": 10, "FEATURECLA": "International boundary (verify)", "geometry": LINE},
        {"ne_id": 11, "FEATURECLA": "Disputed (please verify)", "geometry": LINE},
        {"ne_id": 12, "FEATURECLA": "Overlay limit", "geometry": LINE}])
    assert [f["kind"] for f in borders.ne_features(path)] == ["other", "special"]


def test_a_natural_earth_edition_missing_a_kept_line_is_refused(tmp_path, monkeypatch):
    """Dropping one silently would merge, say, Northern Cyprus into Cyprus on
    the map without anyone deciding it. Mutation performed and reverted:
    removing the `missing` check turns this red."""
    monkeypatch.setattr(borders, "NE_KEPT", {11: "a de facto line", 13: "the gone one"})
    path = _ne(tmp_path, [{"ne_id": 11, "FEATURECLA": "Disputed (please verify)",
                           "geometry": LINE}])
    with pytest.raises(RuntimeError, match=r"\[13\].*the gone one"):
        borders.ne_features(path)


def test_the_kept_natural_earth_lines_each_carry_a_reason():
    assert borders.NE_KEPT and all(isinstance(k, int) and v.strip()
                                   for k, v in borders.NE_KEPT.items())


def _page_max_zoom() -> int:
    app = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"maxZoom:\s*(\d+)", app)
    assert m, "web/app.js no longer sets maxZoom on the Map"
    return int(m.group(1))


def test_the_tileset_spans_exactly_the_zooms_the_page_can_ask_for():
    """Below the page's maximum the deepest zoom is overzoomed from coarser
    tiles, which is the 2 km line this module replaced; above it the tiles
    are bytes no view can fetch."""
    assert borders.MIN_ZOOM == 0
    assert borders.MAX_ZOOM == _page_max_zoom()


def _decode(archive, z, x, y) -> list[dict]:
    out = subprocess.run(["tippecanoe-decode", str(archive), str(z), str(x), str(y)],
                         check=True, capture_output=True, text=True).stdout
    return [f for layer in json.loads(out)["features"] for f in layer["features"]]


def _tile(lon, lat, z):
    import math
    n = 2 ** z
    return z, int((lon + 180) / 360 * n), int(
        (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)


@needs_tippecanoe
def test_the_deepest_tiles_keep_detail_a_pixel_can_show(tmp_path):
    """A line zigzagging 12 m either side of its axis every 200 m, which at
    the page's maximum zoom is a third of a 38 m pixel: the z11 tiles must
    keep it. A tileset that stopped at z9, or simplified harder, would draw
    the axis and lose it -- the straight multi-km segments this replaced.
    Mutations performed and reverted: MAX_ZOOM = 9 and --simplification=10
    each turn this red."""
    lat0, lon0 = 31.5, 35.48
    dlat = 12 / 110_574
    dlon = 200 / (111_320 * 0.8526)
    pts = [(lon0 + i * dlon, lat0 + (dlat if i % 2 else -dlat)) for i in range(20)]
    line = shapely.LineString(pts)
    out = tmp_path / "borders.pmtiles"
    assert borders.tile([{"kind": "international", "geometry": line}], out) == 1

    z, x0, y0 = _tile(pts[0][0], lat0 + dlat, borders.MAX_ZOOM)
    _, x1, y1 = _tile(pts[-1][0], lat0 - dlat, borders.MAX_ZOOM)
    feats = [f for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)
             for f in _decode(out, z, x, y)]
    drawn = shapely.union_all([shapely.geometry.shape(f["geometry"]) for f in feats])
    to_m = lambda g: shapely.transform(g, lambda c: c * [111_320 * 0.8526, 110_574])  # noqa: E731
    # Every input vertex survives to within one z11 tile unit (4.8 m) or so.
    worst = max(to_m(shapely.Point(p)).distance(to_m(drawn)) for p in pts[2:-2])
    assert worst < 6, f"a 12 m zigzag vertex is {worst:.1f} m from the z11 line"


@needs_tippecanoe
def test_the_archive_is_the_layer_the_page_draws_with_kind_on_every_line(tmp_path):
    out = tmp_path / "borders.pmtiles"
    borders.tile([{"kind": "international", "geometry": LINE},
                  {"kind": "other", "geometry": shapely.LineString([(35.2, 31.0), (35.3, 31.1)])}],
                 out)
    head = out.read_bytes()[:127]
    assert head[:7] == b"PMTiles" and (head[100], head[101]) == (borders.MIN_ZOOM,
                                                                 borders.MAX_ZOOM)
    feats = _decode(out, *_tile(35.15, 31.05, 5))
    assert sorted(f["properties"]["kind"] for f in feats) == ["international", "other"]
    assert all(set(f["properties"]) == {"kind"} for f in feats)

    meta = subprocess.run(["tippecanoe-decode", "-c", str(out), "0", "0", "0"],
                          capture_output=True, text=True).stdout
    assert str(tmp_path) not in meta and "/Users/" not in meta and "/home/" not in meta


def test_the_page_draws_the_layer_and_the_kinds_the_emitter_writes():
    """Mutation performed and reverted: `"source-layer": "borders"` ->
    `"lines"` in web/app.js turns this red, and so does a dashed layer
    filtering on a kind the emitter never writes."""
    app = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
    layers = re.findall(r'source: BORDERS_SOURCE, "source-layer": "([^"]+)"', app)
    assert layers and set(layers) == {borders.LAYER}, layers
    assert 'url: "pmtiles://./borders.pmtiles"' in app
    section = app[app.index("map.addSource(BORDERS_SOURCE"):]
    section = section[:section.index("\n\n")]
    kinds = set(re.findall(r'\["get", "kind"\], "([^"]+)"', section))
    assert kinds and kinds <= set(borders.KIND_BY_RANK.values()), kinds
    assert '"line-dasharray"' in app[app.index('id: "borders-other"'):][:400], (
        "the lines LSIB does not rank as international are no longer dashed")
