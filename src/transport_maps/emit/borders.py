"""International boundaries as one GeoJSON, for a line layer on the map.

Natural Earth's boundary lines rather than the country polygons: the lines
carry each border once, where dissolving polygon edges would draw every
shared border twice and disputed ones inconsistently. Simplified to about
1 km, which at the zooms this map reaches is below a pixel.
"""

import json
from pathlib import Path

import httpx
import pyogrio
import shapely

from .. import config
from ..sources._utils import _atomic_write

URL = ("https://naturalearth.s3.amazonaws.com/10m_cultural/"
       "ne_10m_admin_0_boundary_lines_land.zip")
SIMPLIFY_DEG = 0.01


def build(out: Path) -> int:
    cached = config.CACHE / "ne_10m_admin_0_boundary_lines_land.zip"
    if not cached.exists():
        r = httpx.get(URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        _atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    meta, table = pyogrio.read_arrow(f"/vsizip/{cached.resolve()}")
    geom_col = next(c for c in table.schema.names if "geom" in c.lower())
    geoms = shapely.from_wkb(table.column(geom_col).to_pylist())
    feats = []
    for g in geoms:
        if g is None or g.is_empty:
            continue
        g = shapely.simplify(g, SIMPLIFY_DEG)
        feats.append({"type": "Feature", "properties": {},
                      "geometry": shapely.geometry.mapping(g)})
    payload = {"type": "FeatureCollection", "features": feats}
    _atomic_write(out, lambda tmp: tmp.write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"))
    return len(feats)
