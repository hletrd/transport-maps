"""`scheduled_airports()` filters OurAirports. Make it actually run.

Until cycle 15 this file called `airports.scheduled_airports()` and asserted on
what came back -- and what came back was a **parquet the last real build had
left in `data/build/`**, because the builder opens with

    out = _table_cache_path()
    if out.exists():
        return pl.read_parquet(out)

`tests/conftest.py` redirects `config.CACHE` for every test but deliberately
does not redirect `config.BUILD`, so not one line of the filter ever executed.
Proven, not suspected: mutating **four** separate things at once --
`scheduled_service == "yes"` -> `!= "no"`, deleting the three-character IATA
test, `keep="first"` -> `keep="last"`, and deleting `.sort("iata")` -- left
this file at **4 passed, GREEN**.

Worse, the old file was undeclared. On a clone with no `data/build/` it would
have fallen through to `_download()` and fetched
`davidmegginson.github.io/ourairports-data/airports.csv` over the network,
with no `network` marker saying so.

Both halves are fixed here:

* **The filter tests** build a synthetic OurAirports CSV covering every branch
  and run the real builder against `hermetic_build` with `_download` stubbed.
  They touch no network and no warm artifact, and every row exists to make one
  decision go the other way.
* **The shipped-table tests** keep checking the real data -- that is worth
  having, it is how "ICN is where ICN is" stays true -- but they are marked
  `integration`, which is what they always were. `integration` is IN the gate
  (`pyproject.toml` excludes only `network` and `real_multi_band`), so nothing
  is removed from the suite by saying out loud what these read.

MUTATIONS PERFORMED against the filter tests, each run:

  - delete `str.len_chars() == 3`                 -> RED (3 failed)
  - `keep="first"` -> `keep="last"`               -> RED (2 failed)
  - delete `.sort("iata")`                        -> RED (2 failed)
  - delete `.drop_nulls(["lat", "lon"])`          -> RED (3 failed)
  - all four of the original four at once         -> RED (4 failed)

The last line is the point: that exact combination was GREEN before.

  - `== "yes"` -> `!= "no"`                       -> RED (1 failed), but only
    after a test was added for it, and the reason is worth reading.

The fifth mutation came back GREEN at first against the six tests above, and
so it should have: the real column's domain was MEASURED and holds exactly two
values -- `no` 81,692 rows, `yes` 4,334, no blanks -- so on today's data the
two spellings select the same rows. (A null would behave alike too: polars
propagates it and `filter` drops it either way.) On the shipped data the
mutation is not a behaviour change at all, and no honest test can go red for
one that is not.

So what the sixth test pins is the property that makes the difference matter
IF OurAirports ever grows a third value: membership is positive, and an
unrecognised value is left out until somebody decides what it means rather
than silently counted as scheduled. Its fixture row is synthetic on purpose,
and that is not a fabrication about what the file contains -- the measurement
above says plainly that it does not -- it is the specification this filter
should hold to. With it, `!= "no"` is RED.
"""

from __future__ import annotations

import polars as pl
import pytest

from transport_maps.sources import airports

# A synthetic OurAirports extract. Every row is here to flip one decision.
#
# Columns are the real ones the builder requires (REQUIRED_SOURCE_COLUMNS)
# plus `id`, which OurAirports carries and the builder ignores -- present so
# the fixture cannot accidentally test a narrower schema than the real file.
SOURCE_CSV = """\
id,type,name,latitude_deg,longitude_deg,iso_country,scheduled_service,iata_code
1,large_airport,Incheon Intl,37.46,126.44,KR,yes,ICN
2,medium_airport,Gimpo Intl,37.55,126.79,KR,yes,GMP
3,small_airport,Yangyang Intl,38.06,128.66,KR,yes,YNY
4,large_airport,No Service Intl,10.00,10.00,XX,no,NOS
5,heliport,Downtown Heliport,11.00,11.00,XX,yes,HEL
6,closed,Closed Field,12.00,12.00,XX,yes,CLO
7,seaplane_base,Harbour Base,13.00,13.00,XX,yes,SEA
8,large_airport,No Iata At All,14.00,14.00,XX,yes,
9,large_airport,Two Letter Code,15.00,15.00,XX,yes,AB
10,large_airport,Four Letter Code,16.00,16.00,XX,yes,ABCD
11,large_airport,Missing Latitude,,17.00,XX,yes,MLA
12,large_airport,Missing Longitude,18.00,,XX,yes,MLO
13,large_airport,Duplicate First,19.00,19.00,XX,yes,DUP
14,medium_airport,Duplicate Second,20.00,20.00,YY,yes,DUP
"""

#: What the filter must return, in order. Written out by hand from the rules in
#: `sources/airports.py`, not from a run of it.
EXPECTED = [
    ("DUP", "Duplicate First", 19.0, 19.0, "large", "XX"),
    ("GMP", "Gimpo Intl", 37.55, 126.79, "medium", "KR"),
    ("ICN", "Incheon Intl", 37.46, 126.44, "large", "KR"),
    ("YNY", "Yangyang Intl", 38.06, 128.66, "small", "KR"),
]


@pytest.fixture
def built(hermetic_build, monkeypatch) -> pl.DataFrame:
    """The real `scheduled_airports()`, over the synthetic CSV, in a scratch
    `config.BUILD`.

    `hermetic_build` is what makes this test a test: without it the builder
    returns the parquet the last real build wrote and the stub below is never
    reached.
    """
    calls = []

    def fake_download() -> bytes:
        calls.append(1)
        return SOURCE_CSV.encode("utf-8")

    monkeypatch.setattr(airports, "_download", fake_download)
    df = airports.scheduled_airports()
    assert calls, (
        "scheduled_airports() returned without calling _download(): it read a "
        "cached table instead of building one, and this test is measuring "
        "nothing. Is `hermetic_build` still redirecting config.BUILD?")
    return df


def test_the_filter_keeps_exactly_the_right_rows(built: pl.DataFrame) -> None:
    """The whole table, exactly, in order.

    Exact equality and not a set of spot checks: a spot check for "ICN is
    present" is true of a filter that keeps everything, which is what
    `!= "no"` amounts to on this fixture.
    """
    got = [tuple(r) for r in built.select(
        "iata", "name", "lat", "lon", "size", "country").iter_rows()]
    assert got == EXPECTED, (
        "the OurAirports filter no longer produces the expected table.\n"
        f"  got      {got}\n  expected {EXPECTED}")


def test_unscheduled_and_non_airport_types_are_dropped(built: pl.DataFrame) -> None:
    """`scheduled_service == "yes"` AND a type in SIZE_BY_TYPE.

    Named separately from the table test so a failure says WHICH rule broke.
    NOS is a real airport with no scheduled service; HEL, CLO and SEA all have
    scheduled_service=yes and a type that is not one of the three.
    """
    codes = set(built["iata"])
    for code, why in (("NOS", "scheduled_service is 'no'"),
                      ("HEL", "type is heliport"),
                      ("CLO", "type is closed"),
                      ("SEA", "type is seaplane_base")):
        assert code not in codes, f"{code} survived the filter but {why}"


def test_a_service_value_that_is_neither_yes_nor_no_is_excluded(
        hermetic_build, monkeypatch) -> None:
    """Membership is positive: only `scheduled_service == "yes"` counts.

    Today this is untestable from the real data and the file says so -- the
    column's measured domain is exactly {"no": 81,692, "yes": 4,334}, so
    `== "yes"` and `!= "no"` select identically and no mutation between them
    can be caught. The row below is therefore synthetic ON PURPOSE, and it is
    not a fabrication about what OurAirports contains: it is the specification
    this filter should hold to if the upstream vocabulary ever grows.

    "seasonal" is the realistic candidate -- an airport with scheduled service
    for part of the year is not one this model can price, and admitting it
    silently would put a phantom year-round flight in the graph. Under
    `!= "no"` it would be admitted.
    """
    csv = SOURCE_CSV + "15,large_airport,Seasonal Only,21.00,21.00,XX,seasonal,SSN\n"
    monkeypatch.setattr(airports, "_download", lambda: csv.encode("utf-8"))
    built = airports.scheduled_airports()
    assert "SSN" not in set(built["iata"]), (
        "an airport whose scheduled_service is neither 'yes' nor 'no' was "
        "counted as having scheduled service. The filter should test for "
        "'yes', not against 'no', so an unrecognised value is left out until "
        "somebody decides what it means.")
    # ...and the control, so this cannot pass by excluding everything.
    assert "ICN" in set(built["iata"])


def test_only_three_character_iata_codes_survive(built: pl.DataFrame) -> None:
    """A null code, a two-letter code and a four-letter code.

    OurAirports really does carry all three: `iata_code` is blank for most
    small fields, and a handful of rows hold an ICAO-shaped value.
    """
    codes = set(built["iata"])
    assert "AB" not in codes, "a two-character IATA code survived"
    assert "ABCD" not in codes, "a four-character IATA code survived"
    assert all(len(c) == 3 for c in codes), f"a non-three-character code survived: {codes}"
    assert len(built) == 4, (
        f"expected 4 rows after filtering, got {len(built)}: the row with no "
        "iata_code at all may have survived as a null")


def test_a_row_with_no_coordinate_is_dropped(built: pl.DataFrame) -> None:
    """`drop_nulls(["lat", "lon"])`. A null coordinate would be placed at the
    origin of the coordinate system -- an airport in the Gulf of Guinea.
    """
    codes = set(built["iata"])
    assert "MLA" not in codes, "a row with no latitude survived"
    assert "MLO" not in codes, "a row with no longitude survived"
    assert built["lat"].null_count() == 0
    assert built["lon"].null_count() == 0


def test_a_duplicate_iata_keeps_the_first_row_in_sorted_order(built: pl.DataFrame) -> None:
    """`unique(subset=["iata"], keep="first")` runs BEFORE `.sort("iata")`, so
    "first" means first in the SOURCE file, not first alphabetically.

    The two DUP rows differ in every other column, so keeping the wrong one is
    visible rather than a coin toss -- `keep="last"` would give the medium
    airport in YY at (20, 20).
    """
    dup = built.filter(pl.col("iata") == "DUP")
    assert len(dup) == 1, f"the duplicate IATA code was not collapsed: {dup}"
    assert dup["name"][0] == "Duplicate First", (
        f"the duplicate resolved to {dup['name'][0]!r}; keep='first' means the "
        "first row in the source file")
    assert dup["country"][0] == "XX"
    assert dup["size"][0] == "large"


def test_the_table_is_sorted_by_iata(built: pl.DataFrame) -> None:
    """`.sort("iata")`. The fixture is deliberately NOT in alphabetical order
    -- ICN, GMP, YNY, then DUP last -- so an unsorted result differs.
    """
    codes = list(built["iata"])
    assert codes == sorted(codes), f"the table is not sorted by iata: {codes}"
    assert codes[0] == "DUP", (
        f"the table starts at {codes[0]!r}; DUP sorts first and appears last "
        "in the source, so this is the assertion that sees .sort() disappear")


def test_a_changed_source_schema_is_refused_rather_than_guessed(
        hermetic_build, monkeypatch) -> None:
    """The branch above the filter. OurAirports renaming a column must raise,
    not produce a table missing a field the graph depends on.
    """
    trimmed = "\n".join(
        ln.replace("scheduled_service,", "").replace(",yes,", ",").replace(",no,", ",")
        for ln in SOURCE_CSV.splitlines())
    monkeypatch.setattr(airports, "_download", lambda: trimmed.encode("utf-8"))
    with pytest.raises(RuntimeError, match="schema changed"):
        airports.scheduled_airports()


def test_the_cache_stamp_moves_when_the_rules_move(hermetic_build, monkeypatch) -> None:
    """CLAUDE.md: derived caches key on `_params_hash` of the constants that
    govern them, never on a bare `.exists()`.

    Changing which types count as scheduled service must MISS the cache. If it
    hits, the next build silently serves the table built under the old rules --
    which is the same class of defect as the one that made this whole file
    vacuous.
    """
    before = airports._table_cache_path("sha")
    monkeypatch.setitem(airports.SIZE_BY_TYPE, "seaplane_base", "small")
    after = airports._table_cache_path("sha")
    assert before != after, (
        "changing SIZE_BY_TYPE did not move the cache path, so a rebuild would "
        f"read back the table built under the old rules ({before.name})")


# --- the shipped table -------------------------------------------------------
#
# These read `data/build/`'s real parquet, which is what they are for: the
# synthetic fixture above cannot tell you that ICN is at 37.46. Marked
# `integration` because that is what they do -- and `integration` is part of
# the gate, so nothing leaves the suite by being honest about it.

@pytest.fixture(scope="module")
def df():
    return airports.scheduled_airports()


@pytest.mark.integration
def test_required_columns_present(df):
    assert set(df.columns) >= {"iata", "name", "lat", "lon", "size", "country"}


@pytest.mark.integration
def test_incheon_present_with_correct_coordinates(df):
    icn = df.filter(df["iata"] == "ICN")
    assert len(icn) == 1
    assert icn["lat"][0] == pytest.approx(37.46, abs=0.05)
    assert icn["lon"][0] == pytest.approx(126.44, abs=0.05)
    assert icn["size"][0] == "large"


@pytest.mark.integration
def test_no_missing_coordinates_and_plausible_count(df):
    assert df["lat"].null_count() == 0
    assert df["lon"].null_count() == 0
    assert 2_000 < len(df) < 6_000


@pytest.mark.integration
def test_iata_codes_are_unique_three_letter(df):
    assert df["iata"].n_unique() == len(df)
    assert df["iata"].str.len_chars().min() == 3
