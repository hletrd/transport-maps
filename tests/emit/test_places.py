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


def _rows(tmp_path, monkeypatch, rows):
    _build(tmp_path, monkeypatch, rows)
    return json.loads((tmp_path / "places.json").read_text())["places"]


def test_a_quarter_with_its_citys_population_keeps_its_name_but_not_the_citys_rank(
        tmp_path, monkeypatch):
    """Camayenne, a Conakry quarter carrying 1,871,242, ranked above Conakry's
    own row and became a globe label beside it. It stays in the gazetteer and
    ranks as having no population -- while the figure is the one found.

    Mutation performed and reverted: drop the `pop == INFLATED[gid][0]` test
    (an upstream fix stays overridden) -> RED.
    """
    conakry = _row(2422465, "Conakry", 9.538, -13.677, "04", 1928389, cc="GN")
    quarter = _row(2422488, "Camayenne", 9.535, -13.688, "04", 1871242, cc="GN")
    town = _row(1, "Town", 9.9, -13.0, "04", 20000, cc="GN")
    assert [r[0] for r in _rows(tmp_path, monkeypatch, [quarter, town, conakry])] == \
        ["Conakry", "Town", "Camayenne"]
    fixed = _row(2422488, "Camayenne", 9.535, -13.688, "04", 30000, cc="GN")
    assert [r[0] for r in _rows(tmp_path, monkeypatch, [fixed, town, conakry])] == \
        ["Conakry", "Camayenne", "Town"]


def test_a_row_coded_into_another_region_reads_its_own(tmp_path, monkeypatch):
    """Daocheng, in Garze, Sichuan, coded CN.04 (Jiangsu): its hover read
    "Daocheng, Jiangsu".

    Mutation performed and reverted: apply the code whatever was found
    (`a1 = REGION[gid][1]`) -> RED on the second assertion.
    """
    rows = [_row(8395541, "Daocheng", 29.038, 100.297, "04", 31113, cc="CN")]
    files_admin = "CN.04\tJiangsu\tJiangsu\t1\nCN.32\tSichuan\tSichuan\t2\nCN.05\tJilin\tJilin\t3\n"

    def build(rows):
        z = tmp_path / "cities15000.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("cities15000.txt", "\n".join(rows) + "\n")
        a = tmp_path / "admin1CodesASCII.txt"
        a.write_text(files_admin)
        c = tmp_path / "countryInfo.txt"
        c.write_text("CN\tCHN\t156\tCH\tChina\n")
        files = {places.CITIES_URL: z, places.ADMIN1_URL: a, places.COUNTRY_URL: c}
        monkeypatch.setattr(places, "_download", lambda url: files[url])
        places.build(tmp_path / "places.json")
        return json.loads((tmp_path / "places.json").read_text())["places"][0][1]

    assert build(rows) == "Sichuan"
    assert build([_row(8395541, "Daocheng", 29.038, 100.297, "05", 31113, cc="CN")]) == "Jilin"


def test_a_row_standing_for_a_city_under_a_parts_name_reads_the_city(tmp_path, monkeypatch):
    """GeoNames gives Kaiping's population to its seat subdistrict, Changsha,
    and has no Kaiping row: the hover over the origin Kaiping read "Changsha".

    Mutation performed and reverted: rename whatever the row is called
    (`fix[1] if fix`) -> RED on the second assertion.
    """
    row = _row(1796989, "Changsha", 22.381, 112.685, "30", 688242, cc="CN")
    assert _build(tmp_path, monkeypatch, [row]) == ["Kaiping"]
    other = _row(1796989, "Chikan", 22.381, 112.685, "30", 688242, cc="CN")
    assert _build(tmp_path, monkeypatch, [other]) == ["Chikan"]
