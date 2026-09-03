import pytest

from transport_maps.sources import airports


@pytest.fixture(scope="module")
def df():
    return airports.scheduled_airports()


def test_required_columns_present(df):
    assert set(df.columns) >= {"iata", "name", "lat", "lon", "size", "country"}


def test_incheon_present_with_correct_coordinates(df):
    icn = df.filter(df["iata"] == "ICN")
    assert len(icn) == 1
    assert icn["lat"][0] == pytest.approx(37.46, abs=0.05)
    assert icn["lon"][0] == pytest.approx(126.44, abs=0.05)
    assert icn["size"][0] == "large"


def test_no_missing_coordinates_and_plausible_count(df):
    assert df["lat"].null_count() == 0
    assert df["lon"].null_count() == 0
    assert 2_000 < len(df) < 6_000


def test_iata_codes_are_unique_three_letter(df):
    assert df["iata"].n_unique() == len(df)
    assert df["iata"].str.len_chars().min() == 3
