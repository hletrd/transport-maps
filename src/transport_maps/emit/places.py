"""A gazetteer so the readout can name the place under the cursor.

GeoNames cities15000 -- every place over 15,000 people, about 34,000 (2026-09)
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

from .. import config
from .._io import atomic_write
from ..sources import _fetch

CITIES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
ADMIN1_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
COUNTRY_URL = "https://download.geonames.org/export/dump/countryInfo.txt"

COLS = ("id", "name", "ascii", "alt", "lat", "lon", "fclass", "fcode", "cc", "cc2",
        "a1", "a2", "a3", "a4", "pop", "elev", "dem", "tz", "mod")


#: GeoNames rows that are wrong in a way the page would repeat, by geonameid:
#: the position the row was found at, and why. A row is left out only while it
#: is still there (within 0.05 deg), so an upstream fix is picked up rather
#: than overridden.
MISPLACED = {
    # "Masan" (alt. Masan-ni, 마산), a village in Gwangju, carrying 434,371
    # people -- the population of Masan, the former city on the south coast
    # merged into Changwon in 2010, 160 km east. With that figure it made the
    # cities15000 cut and named every hover in south-west Gwangju "Masan"
    # (owner, 2026-10-12). Changwon's own row covers the real Masan.
    1841246: ((35.127, 126.831), "a Gwangju village carrying the population of Masan, Changwon"),
    # The rest found by the audit of 2026-10-12 (plan/2026-10-06-rebuild29-
    # queue.md, "Data errors"): a name that is not the place's, or a copy of
    # another place's row. The eight marked "twin" carry EXACTLY the
    # population of the same-named row given, which is a real town elsewhere.
    11209896: ((32.779, 130.745), "Tokyo's Koto ward (543,730) on a row in east Kumamoto"),
    2460584: ((10.383, -7.150), "Bamba, Gao (17.03N 1.40W), placed in southern Mali"),
    1815463: ((35.209, 111.739), "a Yuncheng village as 'Changzhi' with 699,514; Changzhi is 1808956"),
    1798425: ((29.457, 119.889), "Pujiang's seat as 'Puyang' with 3,590,000, Puyang, Henan's figure"),
    3688452: ((3.583, -77.000), "Buenaventura municipality, 33 km south of the city's row (3688451)"),
    124878: ((35.829, 59.633), "twin of 124877 Maragheh, East Azerbaijan, 1,200 km west"),
    125206: ((27.849, 52.423), "twin of 125205 Maku, West Azerbaijan, 1,470 km north-west"),
    48918: ((28.835, 53.173), "twin of 145449 Abadeh, Fars, 260 km north"),
    193627: ((-0.700, 37.183), "twin of 193624 Karuri, Kiambu, 70 km south-west"),
    197335: ((-0.212, 36.272), "twin of 197334 Gilgil, 33 km south"),
    12718630: ((-1.300, 36.990), "twin of 197226 Githunguri, Kiambu, 36 km north-west"),
    2241372: ((-9.050, 15.317), "twin of 2241371 Dondo, Cuanza Norte, 120 km south-west"),
    129664: ((35.347, 51.844), "twin of 11980175 Kahrizak, 48 km north-west"),
    1332083: ((30.551, 73.391), "twin of 1183883 Bahawalnagar, 63 km south"),
    404592: ((35.714, 51.471), "twin of 8420881 Vahidiyeh, 41 km west, labelling east Tehran"),
}

#: Rows in the right place under their own name that carry a whole city's
#: population: a neighbourhood ranked as the city, so it outranks the city row
#: in the gazetteer's population order and becomes a globe label beside it
#: (Camayenne, Conakry's 1.87 M, at rank 237). Kept -- the name is right where
#: it is nearest -- but ranked as having no population, while the figure is
#: still the one found. geonameid: (population as found, why).
INFLATED = {
    2422488: (1871242, "Camayenne, a Conakry quarter, with Conakry's population"),
    101760: (946697, "Sultanah, a Madinah district, with Madinah's population"),
    1771023: (833571, "Kampung Baru Subang, a Shah Alam suburb, with a city's population"),
    1852383: (375339, "Minato, a Wakayama district, with more than Wakayama's 356,729"),
    1701500: (454150, "Mansilingan, a Bacolod barangay, with Bacolod's population"),
    1687687: (298976, "Santol, an Angeles barangay, with a city's population"),
    11679708: (300104, "Gundupalaiyam, a village, with Ozhukarai's 300,104"),
}

#: Rows that stand for a city under the name of one of its parts:
#: geonameid: (name as found, the city's name, why). Applied only while the
#: name is the one found. GeoNames has no row for Kaiping (748,777 in 2020)
#: and gives its population to its seat subdistrict, Changsha, so the hover
#: over Kaiping -- an origin since 2026-10-12 -- read "Changsha, Guangdong".
RENAMED = {
    1796989: ("Changsha", "Kaiping", "Kaiping's seat subdistrict carrying Kaiping's 688,242"),
}

#: Rows whose admin1 code names another region: geonameid: (code as found,
#: the right code, why). Applied only while the code is the one found.
REGION = {
    8395541: ("04", "32", "Daocheng (稻城), Garze, Sichuan (CN.32), coded Jiangsu (CN.04)"),
}


def misplaced(gid: int | None, lat: float, lon: float) -> bool:
    """Whether a row is one MISPLACED names, still where it was found."""
    bad = MISPLACED.get(gid)
    return bool(bad) and abs(lat - bad[0][0]) < 0.05 and abs(lon - bad[0][1]) < 0.05


def ranked_population(gid: int | None, pop: int) -> int:
    """A row's population for ranking: 0 for one INFLATED names, while it
    still carries the figure found."""
    return 0 if gid in INFLATED and pop == INFLATED[gid][0] else pop


def place_name(gid: int | None, name: str) -> str:
    """A row's name, or the city's where RENAMED says the row stands for one."""
    fix = RENAMED.get(gid)
    return fix[1] if fix and name == fix[0] else name


def _download(url: str) -> pathlib.Path:
    """One GeoNames file, checked against the upstream on every run (G2)."""
    return _fetch.fetch(url, config.CACHE / url.rsplit("/", 1)[-1]).path


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
        gid = int(r["id"]) if r["id"].isdigit() else None
        if misplaced(gid, lat, lon):
            continue
        a1 = r["a1"]
        if gid in REGION and a1 == REGION[gid][0]:
            a1 = REGION[gid][1]
        region = admin1.get(f"{r['cc']}.{a1}", "")
        rows.append([place_name(gid, r["name"]), region, countries.get(r["cc"], r["cc"]),
                     round(lat, 3), round(lon, 3)])
        pops.append(ranked_population(gid, int(r["pop"] or 0)))
    if not rows:
        raise RuntimeError("GeoNames extract yielded no usable rows")
    # Largest first, so a consumer can treat row index as rank.
    order = sorted(range(len(rows)), key=lambda i: -pops[i])
    rows = [rows[i] for i in order]
    payload = {"fields": ["name", "region", "country", "lat", "lon"], "places": rows}
    atomic_write(out, lambda tmp: tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"))
    return len(rows)
