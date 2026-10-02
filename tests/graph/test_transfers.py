"""Airport time, split by what it actually depends on.

The previous model lumped check-in, security, boarding, emigration, baggage and
immigration into one "access"/"egress" pair with a domestic and an international
variant, and — because the graph is built before any journey is known — applied
the international variant everywhere. That charged a Frankfurt-Munich hop for a
border it never crosses and an Amsterdam-Milan flight for a passport desk that
does not exist.

Now: processing and disembark are properties of the AIRPORT and stay on the
cell<->airport edges; border control is a property of the ROUTE and is charged
on the flight edge, only when the flight leaves its immigration zone.
"""

import pytest

from transport_maps.graph import air, transfers

SIZES = ("large", "medium", "small")


@pytest.fixture(scope="module")
def cal():
    return air.load_calibration()


# --- immigration zones -------------------------------------------------------

@pytest.mark.parametrize("dep,arr", [("KR", "JP"), ("KR", "US"), ("GB", "FR"), ("US", "MX")])
def test_flights_leaving_the_immigration_zone_cross_a_border(dep, arr):
    assert transfers.crosses_border(dep, arr)


@pytest.mark.parametrize("dep,arr,why", [
    ("DE", "DE", "same country"),
    ("NL", "IT", "both Schengen"),
    ("FR", "ES", "both Schengen"),
    ("IE", "GB", "Common Travel Area"),
])
def test_flights_inside_one_immigration_zone_do_not(dep, arr, why):
    assert not transfers.crosses_border(dep, arr), why


def test_schengen_is_one_zone_but_not_the_whole_world():
    """Guards against a zone table so broad it makes every border vanish."""
    assert transfers.immigration_zone("NL") == transfers.immigration_zone("IT")
    assert transfers.immigration_zone("NL") != transfers.immigration_zone("US")
    assert transfers.immigration_zone("JP") == "JP"


# --- component magnitudes ----------------------------------------------------

def test_processing_exceeds_disembark_at_every_size(cal):
    """Getting onto an aircraft takes longer than getting off one: check-in and
    security have no counterpart on arrival once border control is separated out.
    """
    for size in SIZES:
        assert transfers.processing_min(size, cal) > transfers.disembark_min(size, cal)


@pytest.mark.parametrize("fn", ["processing_min", "disembark_min", "border_min", "connection_min"])
def test_every_component_decreases_with_airport_size(fn, cal):
    """Terminal size is the proxy for queue length, so all four must order the
    same way. A swapped pair of entries in any one table would pass a test that
    only checked large vs small on a single component.
    """
    f = getattr(transfers, fn)
    large, medium, small = (f(s, cal) for s in SIZES)
    assert large > medium > small


def test_components_match_the_calibration_file(cal):
    """Pins the middle tier too: a medium/small swap changes no other assertion."""
    assert transfers.processing_min("large", cal) == 70.0
    assert transfers.processing_min("medium", cal) == 55.0
    assert transfers.disembark_min("large", cal) == 30.0
    assert transfers.disembark_min("medium", cal) == 22.0
    assert transfers.border_min("large", cal) == 45.0
    assert transfers.border_min("medium", cal) == 35.0


def test_border_is_a_real_cost_not_a_rounding_error(cal):
    """If border time were negligible the split would buy nothing; it should be
    a material share of the airport overhead it was carved out of.
    """
    for size in SIZES:
        assert transfers.border_min(size, cal) >= 0.3 * transfers.processing_min(size, cal)


# --- zone membership, checked against official sources 2026-10-02 (A15) -----
#
# Each pair names the sourced fact in `graph/transfers.py`. Mutations performed
# and reverted, each -> red: drop "AX" from the Schengen list (Åland pairs);
# drop "MC", "SM" or "VA" (its own pair); drop "IM", "JE" or "GG" from the CTA
# (its pairs); add "AD" to Schengen, or any overseas department to it (the
# not-shared pairs); empty AIRPORT_COUNTRY (Ercan).

@pytest.mark.parametrize("a,b,why", [
    ("AX", "FI", "Åland is Finland, inside Schengen; its border is for tax"),
    ("AX", "SE", "the Stockholm-Mariehamn ferry passes no passport desk"),
    ("MC", "FR", "Monaco: Schengen through France, no routine control"),
    ("SM", "IT", "San Marino follows Schengen rules, no border control"),
    ("VA", "IT", "Vatican City: open border with Rome"),
    ("LI", "CH", "Liechtenstein is a full Schengen member"),
    ("IM", "GB", "Isle of Man: Common Travel Area"),
    ("JE", "GB", "Jersey: Common Travel Area"),
    ("GG", "IE", "Guernsey: Common Travel Area"),
    ("JE", "GG", "between two Crown Dependencies"),
])
def test_corrected_members_share_a_zone(a, b, why):
    assert not transfers.crosses_border(a, b), why


@pytest.mark.parametrize("a,b,why", [
    ("AD", "FR", "Andorra is outside Schengen"),
    ("AD", "ES", "Andorra is outside Schengen"),
    ("RE", "FR", "Réunion: France, but outside Schengen, checked at Paris"),
    ("GP", "FR", "Guadeloupe: outside Schengen"),
    ("MQ", "FR", "Martinique: outside Schengen"),
    ("GF", "FR", "French Guiana: outside Schengen"),
    ("YT", "FR", "Mayotte: outside Schengen"),
    ("CY", "GR", "Cyprus has not had internal controls lifted"),
    ("CYN", "CY", "the Green Line is a controlled crossing"),
    ("IM", "FR", "the CTA is not Schengen"),
])
def test_places_that_keep_a_border_keep_it(a, b, why):
    assert transfers.crosses_border(a, b), why


def test_ercan_is_the_norths_airport_and_no_other_cypriot_one_is():
    """OurAirports files ECN under CY; its passengers pass the northern
    administration's control, which the ground calls CYN."""
    assert transfers.airport_country("ECN", "CY") == "CYN"
    assert transfers.crosses_border(transfers.airport_country("ECN", "CY"), "CY")
    assert transfers.airport_country("LCA", "CY") == "CY"
    assert transfers.airport_country("PFO", "CY") == "CY"


def test_air_and_ground_put_each_corrected_place_in_the_same_zone(monkeypatch):
    """The air model reads OurAirports' code for an airport, the ground reads
    Natural Earth's for a cell; through one table they must name one zone.
    The ISO_A2_EH values are Natural Earth 10m's own (CYN has none, so
    `countries.iso2` keeps the A3), read from the cached zip on 2026-10-02.

    Mutation performed and reverted: route `ground.cell_zones` around
    `immigration_zone` -> red.
    """
    from transport_maps.graph import ground
    from transport_maps.sources import countries

    monkeypatch.setattr(countries, "A3_TO_A2", {
        "ALD": "AX", "FIN": "FI", "IMN": "IM", "JEY": "JE", "GGY": "GG", "GBR": "GB",
        "MCO": "MC", "FRA": "FR", "SMR": "SM", "VAT": "VA", "ITA": "IT", "CYP": "CY",
    })
    # (Natural Earth A3 of the land, OurAirports iso_country and IATA of an
    # airport on it)
    for a3, oa_country, iata in (("ALD", "FI", "MHQ"), ("IMN", "IM", "IOM"),
                                 ("JEY", "JE", "JER"), ("GGY", "GG", "GCI"),
                                 ("CYN", "CY", "ECN"), ("CYP", "CY", "LCA")):
        ground_zone = ground.cell_zones([a3])[0]
        air_zone = transfers.immigration_zone(transfers.airport_country(iata, oa_country))
        assert ground_zone == air_zone, (a3, iata, ground_zone, air_zone)
    assert len(set(ground.cell_zones(["MCO", "FRA", "SMR", "VAT", "ITA", "ALD", "FIN"]))) == 1
    assert len(set(ground.cell_zones(["IMN", "JEY", "GGY", "GBR"]))) == 1

