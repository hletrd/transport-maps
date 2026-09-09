"""A gazetteer so the readout can name the place under the cursor.

GeoNames cities15000 -- every place over 15,000 people, about 31,000 of them
-- reduced to name, region, country and position. Shipped as one JSON the page
loads once: half a megabyte gzipped buys a name for every hover, where a
reverse-geocoding request would cost a round trip per pointer move and a
dependency on somebody else's uptime. (The page does ask Nominatim for a
proper address when a point is CLICKED; that is one request, not hundreds.)

Natural Earth's populated places, used before, had 7,342 entries and named
the nearest of them however far away it was.
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import zipfile

import httpx

from .. import config
from ..sources._utils import _atomic_write

CITIES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
COUNTRY_URL = "https://download.geonames.org/export/dump/countryInfo.txt"

COLS = ("id", "name", "ascii", "alt", "lat", "lon", "fclass", "fcode", "cc", "cc2",
        "a1", "a2", "a3", "a4", "pop", "elev", "dem", "tz", "mod")


def _download(url: str) -> pathlib.Path:
    cached = config.CACHE / url.rsplit("/", 1)[-1]
    if not cached.exists():
        r = httpx.get(url, follow_redirects=True, timeout=180)
        r.raise_for_status()
        _atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    return cached


def _tsv(text: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
            if row and not row[0].startswith("#")]


def build(out: pathlib.Path) -> int:
    with zipfile.ZipFile(_download(CITIES_URL)) as z:
        cities = _tsv(z.read("cities15000.txt").decode("utf-8"))
    admin1 = {row[0]: row[1] for row in _tsv(_download(ADMIN1_URL).read_text(encoding="utf-8"))}
    countries = {row[0]: row[4] for row in _tsv(_download(COUNTRY_URL).read_text(encoding="utf-8"))
                 if len(row) > 4}

    rows, pops = [], []
    for raw in cities:
        r = dict(zip(COLS, raw))
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except ValueError:
            continue
        region = admin1.get(f"{r['cc']}.{r['a1']}", "")
        rows.append([r["name"], region, countries.get(r["cc"], r["cc"]),
                     round(lat, 3), round(lon, 3)])
        pops.append(int(r["pop"] or 0))
    if not rows:
        raise RuntimeError("GeoNames extract yielded no usable rows")
    # Largest first, so a consumer can treat row index as rank.
    order = sorted(range(len(rows)), key=lambda i: -pops[i])
    rows = [rows[i] for i in order]
    payload = {"fields": ["name", "region", "country", "lat", "lon"], "places": rows}
    _atomic_write(out, lambda tmp: tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"))
    return len(rows)
