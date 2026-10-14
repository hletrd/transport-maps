"""Urban congestion must slow cities and leave open country alone."""

import h3
import numpy as np
import pytest

from transport_maps import config
from transport_maps.graph import ground
from transport_maps.graph.nodes import NodeIndex
from transport_maps.sources import urban


def _idx(points):
    cells = [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo in points]
    cells = list(dict.fromkeys(cells))
    return NodeIndex(cells, [], {c: i for i, c in enumerate(cells)}, {}, {}, ())


@pytest.mark.needs_inputs
def test_cities_are_marked_and_empty_country_is_not():
    pts = [(51.5074, -0.1278),    # London
           (35.6762, 139.6503),   # Tokyo
           (-25.0, 132.0),        # central Australian desert
           (68.0, 100.0)]         # central Siberia
    mask = urban.urban_mask(
        [h3.latlng_to_cell(la, lo, config.SOLVE_RES) for la, lo in pts])
    assert mask[0] and mask[1], "a major city was not marked urban"
    assert not mask[2] and not mask[3], "empty country was marked urban"


@pytest.mark.needs_inputs
def test_an_urban_cell_is_slower_than_the_same_class_in_open_country():
    """The whole point: GRIP4 gives both the grade of their best road."""
    idx = _idx([(51.5074, -0.1278), (-25.0, 132.0)])
    speeds = ground.cell_speed_kmh(idx)
    mask = ground.built_up_mask(idx)
    assert mask[0] and not mask[1]
    # London's cell holds a motorway, so without the factor it would be fastest.
    fastest = ground.SPEED_BY_ROAD_CLASS_KMH.max() * ground.INCOME_SPEED_MULTIPLIER.max()
    assert speeds[0] <= fastest / urban.URBAN_BUILT_UP_FACTOR + 1e-9


@pytest.mark.needs_inputs
def test_the_factor_actually_divides():
    """London: a high-income cell inside the city's built-up radius."""
    idx = _idx([(51.5074, -0.1278)])
    from transport_maps.sources import countries

    cls = ground.cell_class(idx)          # GRIP4's, or the OSM motorway class
    raw = ground.SPEED_BY_ROAD_CLASS_KMH[cls][0]
    if cls[0] in ground.INCOME_SCALED_CLASSES:
        raw *= ground.INCOME_SPEED_MULTIPLIER[countries.INCOME_GROUPS.index("high")]
    got = ground.cell_speed_kmh(idx)[0]
    assert np.isclose(got, raw / urban.URBAN_BUILT_UP_FACTOR)


@pytest.mark.needs_inputs
def test_a_megacitys_built_up_radius_reaches_its_airport_and_a_towns_does_not():
    """The extent scales with the city: LHR, 23 km out, is inside London's
    disc; a cell 23 km from a city of 300,000 is not inside that one's."""
    s, pop = urban.scaled_city_distance([h3.latlng_to_cell(51.4700, -0.4543, config.SOLVE_RES)])
    assert s[0] < urban.URBAN_BUILT_UP_EXTENT and pop[0] > 5e6
    assert urban.city_radius_km(np.array([3e5]))[0] < 23.0 < urban.city_radius_km(np.array([9e6]))[0]


@pytest.mark.needs_inputs
def test_roadless_terrain_is_never_slowed_by_traffic():
    """A roadless cell is already at walking pace.

    Applying congestion to it produced 2.5 km/h -- below the table's own floor
    for the slowest terrain on Earth, which is how the range test caught it.
    """
    # A roadless cell that nonetheless falls inside a city radius.
    idx = _idx([(51.5074, -0.1278), (-25.0, 132.0), (68.0, 100.0)])
    speeds = ground.cell_speed_kmh(idx)
    cls = ground.cell_class(idx)
    for i, c in enumerate(cls):
        if c == 0:
            assert speeds[i] == ground.SPEED_BY_ROAD_CLASS_KMH[0], \
                "traffic was applied to roadless terrain"
    assert speeds.min() >= ground.SPEED_BY_ROAD_CLASS_KMH.min()


def _places_archive(tmp_path) -> bytes:
    """A Natural Earth-shaped populated-places shapefile, zipped: one place
    above URBAN_POP_MIN at (10, 20) and one below it at (30, 40)."""
    import io
    import zipfile

    import pyarrow as pa
    import pyogrio
    import shapely

    rows = [(10.0, 20.0, urban.URBAN_POP_MIN + 1.0), (30.0, 40.0, urban.URBAN_POP_MIN - 1.0)]
    table = pa.table({
        "latitude": [r[0] for r in rows],
        "longitude": [r[1] for r in rows],
        "pop_max": [r[2] for r in rows],
        "geometry": [shapely.to_wkb(shapely.Point(r[1], r[0])) for r in rows],
    })
    shp = tmp_path / "shp"
    shp.mkdir()
    pyogrio.write_arrow(table, shp / "ne_10m_populated_places_simple.shp",
                        driver="ESRI Shapefile", geometry_name="geometry",
                        geometry_type="Point", crs="EPSG:4326")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for part in sorted(shp.iterdir()):
            z.write(part, part.name)
    return buf.getvalue()


def test_places_reads_the_archive_it_downloaded(tmp_path, monkeypatch):
    """A fresh cache must be able to fetch the archive itself.

    This used to call emit.places._download(), whose signature had changed
    to take a URL (and which fetches GeoNames, not this archive), so every
    fresh clone died with TypeError in the index preamble; it only worked
    here because the zip happened to be in data/cache already.
    """
    import contextlib

    import httpx

    from transport_maps.sources import _fetch

    payload = _places_archive(tmp_path)
    monkeypatch.setattr(config, "CACHE", tmp_path / "cache")   # does not exist yet
    fetched: list[str] = []

    class Response:
        status_code = 200
        headers = httpx.Headers({})

        def iter_bytes(self, _n):
            yield payload

        def raise_for_status(self):
            pass

    def fake_stream(url, headers, timeout):
        fetched.append(url)
        return contextlib.nullcontext(Response())
    _fetch.set_offline(False)
    monkeypatch.setattr(_fetch, "_stream", fake_stream)

    lat, lon = urban._places()
    assert fetched == [urban.PLACES_URL]
    assert (tmp_path / "cache" / urban.PLACES_ZIP).read_bytes() == payload
    # Only the place above the threshold, read back from the fetched archive.
    assert lat.tolist() == [10.0] and lon.tolist() == [20.0]
    # The second call is served from the archive it just wrote: one check per
    # build (sources/_fetch.py), not one per call.
    urban._places()
    assert fetched == [urban.PLACES_URL]


def test_urban_mask_cache_key_includes_the_source_archive(tmp_path, monkeypatch):
    """Changing the gazetteer must miss the cache rather than read back the
    mask built from the old one."""
    import types

    monkeypatch.setattr(config, "CACHE", tmp_path)
    monkeypatch.setattr(urban, "_places", lambda: (np.array([51.5]), np.array([-0.1])))
    source = types.SimpleNamespace(sha256="a" * 64)
    monkeypatch.setattr(urban, "_source", lambda: source)
    cells = [h3.latlng_to_cell(51.5074, -0.1278, config.SOLVE_RES)]
    urban.urban_mask(cells)
    monkeypatch.setattr(urban, "PLACES_URL", "https://example.invalid/other_places.zip")
    urban.urban_mask(cells)
    assert len(list(tmp_path.glob("urban_mask-*.parquet"))) == 2, "a different archive hit the cache"
    # The same URL with new content (G2): a re-downloaded release must miss
    # too. Mutation: drop `source` from _mask_cache_path's key -> red.
    source.sha256 = "b" * 64
    urban.urban_mask(cells)
    assert len(list(tmp_path.glob("urban_mask-*.parquet"))) == 3, "new content hit the cache"
