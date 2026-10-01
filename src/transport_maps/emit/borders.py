"""International boundaries as one GeoJSON, for a line layer on the map.

Natural Earth's boundary lines rather than the country polygons: the lines
carry each border once, where dissolving polygon edges would draw every
shared border twice and disputed ones inconsistently. Simplified at
SIMPLIFY_DEG (0.0005 deg, about 55 m), which keeps Natural Earth's own
vertices and drops only the collinear ones; see the constant for why.

Coordinates are rounded to COORD_DP. The default json encoder writes a float's
full repr, e.g. [-124.75886592699995,48.49401784300004] -- 38 characters for a
position already simplified to tens of metres. At the page's
maxZoom of 11 one pixel is 38.2 m, so the simplification is about 1.5 px and
the 6 dp rounding (0.11 m) is 0.003 px: the rounding cannot move a drawn line.
Measured on the shipped file (2026-10-02): 515 features, 70,681 vertices,
1,617,350 bytes raw, 577,747 gzipped.

This docstring used to measure everything against the 0.01 deg (1.1 km)
tolerance and 4 dp the module has since left: 31,182 vertices, 221,784 bytes
gzipped, and "4 dp is 0.29 px where the simplification is already 29 px" --
the simplification's share of a pixel is now 20x smaller and the file 2.6x
larger, because 59ffd73 chose Natural Earth's own resolution over size.
"""

import json
from pathlib import Path

import httpx
import pyogrio
import shapely

from .. import config
from .._io import atomic_write

URL = ("https://naturalearth.s3.amazonaws.com/10m_cultural/"
       "ne_10m_admin_0_boundary_lines_land.zip")
#: Natural Earth's own vertices are about 2 km apart at the median, so
#: simplifying at 0.01 deg (~1.1 km) threw away 60% of them and stretched the
#: median drawn segment to 6.6 km -- a straight line 348 pixels long at the
#: page's maximum zoom, beside a coastline drawn at ~10 m. At 0.0005 deg the
#: median segment returns to Natural Earth's own 2.07 km and only the
#: genuinely collinear points are dropped (77,295 vertices -> 70,681), which
#: costs about 0.6 MB gzipped. 2 km is this source's floor, not a choice:
#: finer borders need OpenStreetMap admin relations, which the rail-filtered
#: extracts do not carry.
SIMPLIFY_DEG = 0.0005
#: Decimal places kept per coordinate. 6 dp is about 0.11 m at the equator, 500
#: times finer than SIMPLIFY_DEG and far under a pixel at the page's maximum
#: zoom, so it cannot move a drawn line. 4 dp was fine against the old 1.1 km
#: tolerance; against 55 m it would be only 5x finer, and 5 dp is exactly 50x,
#: which the guard rejects as too close to call.
COORD_DP = 6


def _round(obj):
    """Round every coordinate in a GeoJSON geometry mapping to COORD_DP.

    Recursive rather than clever: a geometry mapping is nested tuples of
    floats to an unknown depth (LineString, MultiLineString, and Natural
    Earth ships both).
    """
    if isinstance(obj, float):
        return round(obj, COORD_DP)
    if isinstance(obj, (list, tuple)):
        return [_round(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    return obj


def build(out: Path) -> int:
    cached = config.CACHE / "ne_10m_admin_0_boundary_lines_land.zip"
    if not cached.exists():
        r = httpx.get(URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    meta, table = pyogrio.read_arrow(f"/vsizip/{cached.resolve()}")
    geom_col = next(c for c in table.schema.names if "geom" in c.lower())
    geoms = shapely.from_wkb(table.column(geom_col).to_pylist())
    feats = []
    for g in geoms:
        if g is None or g.is_empty:
            continue
        g = shapely.simplify(g, SIMPLIFY_DEG)
        feats.append({"type": "Feature", "properties": {},
                      "geometry": _round(shapely.geometry.mapping(g))})
    payload = {"type": "FeatureCollection", "features": feats}
    atomic_write(out, lambda tmp: tmp.write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"))
    return len(feats)
