"""A small gazetteer so the readout can name the place under the cursor.

Natural Earth's populated-places set, reduced to name, country and position.
Shipped as one JSON the page loads once: a few hundred kilobytes buys a
name for every hover, where a reverse-geocoding request would cost a round
trip per pointer move and a dependency on somebody else's uptime.
"""

from __future__ import annotations

import json
import pathlib

import httpx
import pyogrio

from .. import config
from ..sources._utils import _atomic_write

PLACES_URL = "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_populated_places_simple.zip"
# Rank 1 is a world city, 10 a village. Everything is kept: the point of the
# gazetteer is to name remote places, which is exactly where the big cities
# are not.
FIELDS = ("name", "adm0name", "adm1name", "latitude", "longitude", "pop_max")


def _download() -> pathlib.Path:
    cached = config.CACHE / "ne_10m_populated_places_simple.zip"
    if not cached.exists():
        r = httpx.get(PLACES_URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        _atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    return cached


def build(out: pathlib.Path) -> int:
    path = _download().resolve()
    _meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    cols = {name: table.column(name).to_pylist()
            for name in FIELDS if name in table.schema.names}

    rows = []
    for i in range(len(cols["name"])):
        lat, lon = cols["latitude"][i], cols["longitude"][i]
        if lat is None or lon is None:
            continue
        rows.append([
            cols["name"][i] or "",
            cols.get("adm1name", [None] * (i + 1))[i] or "",
            cols.get("adm0name", [None] * (i + 1))[i] or "",
            round(float(lat), 3),
            round(float(lon), 3),
        ])
    if not rows:
        raise RuntimeError("populated-places extract yielded no usable rows")

    # Columnar, not a list of objects: the same data as records is roughly
    # three times the bytes over the wire for no gain on the client.
    payload = {
        "fields": ["name", "region", "country", "lat", "lon"],
        "places": rows,
    }
    _atomic_write(out, lambda tmp: tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8"))
    return len(rows)
