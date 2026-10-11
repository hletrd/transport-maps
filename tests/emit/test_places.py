"""emit/places.py: the gazetteer the hover readout names places from."""

from __future__ import annotations

import json
import zipfile

from transport_maps.emit import places

COLS = places.COLS


def _row(gid, name, lat, lon, a1, pop, cc="KR"):
    r = dict.fromkeys(COLS, "")
    r.update(id=str(gid), name=name, lat=str(lat), lon=str(lon), cc=cc, a1=a1, pop=str(pop))
    return "\t".join(r[c] for c in COLS)


def _build(tmp_path, monkeypatch, rows):
    z = tmp_path / "cities15000.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("cities15000.txt", "\n".join(rows) + "\n")
    admin1 = tmp_path / "admin1CodesASCII.txt"
    admin1.write_text("KR.18\tGwangju\tGwangju\t1\nKR.20\tGyeongsangnam-do\tG\t2\n")
    countries = tmp_path / "countryInfo.txt"
    countries.write_text("KR\tKOR\t410\tKS\tSouth Korea\n")
    files = {places.CITIES_URL: z, places.ADMIN1_URL: admin1, places.COUNTRY_URL: countries}
    monkeypatch.setattr(places, "_download", lambda url: files[url])
    out = tmp_path / "places.json"
    places.build(out)
    return [r[0] for r in json.loads(out.read_text())["places"]]


def test_a_misplaced_geonames_row_is_left_out_while_it_stays_misplaced(tmp_path, monkeypatch):
    """GeoNames 1841246 put Masan's 434,371 people on a Gwangju village, and
    the hover over Gwangju read "Masan" (2026-10-12). Left out while it is at
    that position; kept once upstream moves it.

    Mutation performed and reverted: the position test removed (the row
    dropped wherever it is) -> red.
    """
    rows = [_row(1841811, "Gwangju", 35.15472, 126.91556, "18", 1401235),
            _row(1841246, "Masan", 35.12725, 126.83149, "18", 434371),
            _row(1846326, "Changwon", 35.22806, 128.68111, "20", 1025702)]
    assert _build(tmp_path, monkeypatch, rows) == ["Gwangju", "Changwon"]
    fixed = [*rows[:1], _row(1841246, "Masan", 35.2, 128.57, "20", 434371), rows[2]]
    assert _build(tmp_path, monkeypatch, fixed) == ["Gwangju", "Changwon", "Masan"]
