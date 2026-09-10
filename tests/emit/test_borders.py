"""borders.json: the coordinate precision that actually ships.

This module had no tests at all -- it is one of the four REQUIRED_EXTRAS whose
only verification was that the file exists.

The precision matters because the default json encoder writes a float's full
repr, so a geometry already simplified to a kilometre shipped as
[-124.75886592699995,48.49401784300004]: 38 characters for a position accurate
to about 1,100 m. Measured over the shipped file (515 features, 31,182
vertices), rounding to 4 dp took it from 1,278,586 raw / 402,313 gzipped to
622,428 / 191,485 -- 211 KB off every cold load -- while moving no vertex
further than 5.57 m.
"""

import json
import math

import pytest

from transport_maps.emit import borders


def test_rounding_reaches_every_coordinate_in_a_geojson_geometry():
    """A geometry mapping nests tuples of floats to a depth that depends on the
    geometry type, and Natural Earth ships both LineString and
    MultiLineString."""
    line = {"type": "LineString",
            "coordinates": ((-124.75886592699995, 48.49401784300004), (1.5, 2.5))}
    multi = {"type": "MultiLineString",
             "coordinates": (((0.123456789, 1.987654321),), ((2.0, 3.0),))}
    assert borders._round(line)["coordinates"] == [[-124.7589, 48.494], [1.5, 2.5]]
    assert borders._round(multi)["coordinates"] == [[[0.1235, 1.9877]], [[2.0, 3.0]]]


def test_rounding_leaves_everything_that_is_not_a_number_alone():
    g = {"type": "LineString", "properties": None, "n": 3, "coordinates": ((1.25, 2.25),)}
    out = borders._round(g)
    assert out["type"] == "LineString" and out["properties"] is None and out["n"] == 3


def test_the_precision_kept_is_far_finer_than_the_simplification_applied():
    """The rounding must be incapable of moving a line the eye could follow.

    Two independent bounds, both of which must hold: it has to be much finer
    than the simplification the same module applies, and much finer than one
    pixel at the page's own maximum zoom.
    """
    step_deg = 10 ** -borders.COORD_DP
    assert step_deg < borders.SIMPLIFY_DEG / 50, (
        "rounding is within a factor of 50 of the simplification; it could move a vertex")

    # One pixel at zoom 11, 512px tiles: 40,075,016.686 m / (512 * 2**11).
    px_m = 40_075_016.686 / (512 * 2 ** 11)
    step_m = step_deg * 40_075_016.686 / 360
    assert step_m < px_m / 2, f"{step_m:.1f} m per step against a {px_m:.1f} m pixel"


@pytest.mark.parametrize("value", [0.0, -180.0, 179.99999, 1e-9, -1e-9])
def test_rounding_is_stable_and_never_leaves_a_long_repr(value):
    r = borders._round(value)
    assert isinstance(r, float)
    assert abs(r - value) <= 0.5 * 10 ** -borders.COORD_DP
    assert len(json.dumps(r)) <= len(json.dumps(value))


def test_the_emitted_json_carries_no_more_digits_than_it_claims(monkeypatch, tmp_path):
    """End to end through build(), with the download and the reader stubbed:
    the file on disk must not contain a coordinate longer than COORD_DP.
    """
    import shapely

    geom = shapely.LineString([(-124.75886592699995, 48.49401784300004),
                               (-124.6, 48.4), (-124.0, 48.0)])

    class _Table:
        schema = type("S", (), {"names": ["geometry"]})()

        def column(self, _name):
            return type("C", (), {"to_pylist": staticmethod(lambda: [shapely.to_wkb(geom)])})()

    monkeypatch.setattr(borders.pyogrio, "read_arrow", lambda *a, **k: (None, _Table()))
    monkeypatch.setattr(borders.config, "CACHE", tmp_path)
    (tmp_path / "ne_10m_admin_0_boundary_lines_land.zip").write_bytes(b"stub")

    out = tmp_path / "borders.json"
    assert borders.build(out) == 1
    text = out.read_text(encoding="utf-8")
    payload = json.loads(text)
    for x, y in payload["features"][0]["geometry"]["coordinates"]:
        for v in (x, y):
            frac = json.dumps(v).partition(".")[2]
            assert len(frac) <= borders.COORD_DP, f"{v!r} carries {len(frac)} decimals"
            assert math.isfinite(v)
    assert "48.49401784300004" not in text, "a full-precision float reached the file"
