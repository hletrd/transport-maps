from pathlib import Path

import pytest

from transport_maps.sources import routes, wikidata

FIXTURE = Path(__file__).parent.parent / "fixtures" / "icn_wikitext.txt"


def test_parses_destination_article_titles_from_real_page():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    assert len(titles) > 50
    # Narita and Los Angeles are long-standing ICN destinations.
    assert any("Narita" in t for t in titles)
    assert any("Los_Angeles" in t or "Los Angeles" in t for t in titles)


def test_ignores_non_destination_links():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    # File and category wikilinks must not leak into the destination list.
    assert not any(t.startswith(("File:", "Category:", "Help:")) for t in titles)


def test_ignores_cargo_subsection():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    # ICN's Cargo subsection lists freight-only carriers that never appear
    # among its passenger destinations.
    assert "Cargolux" not in titles


@pytest.mark.network
def test_resolves_article_titles_to_iata_codes():
    got = wikidata.iata_for_titles([
        "Narita International Airport",
        "Incheon International Airport",
        "Seoul",  # a city, not an airport -> must be absent
    ])
    assert got["Narita International Airport"] == "NRT"
    assert got["Incheon International Airport"] == "ICN"
    assert "Seoul" not in got


@pytest.mark.network
def test_resolves_underscore_titles_under_the_exact_key_passed_in():
    # parse_destinations() always yields underscore-form titles (see its
    # ".replace(' ', '_')"). MediaWiki's `query.normalized` reports these
    # relative to the space-form title, so the resolver must map back to
    # the underscore form the caller actually asked for -- not silently
    # drop it. This is the exact bug class that once poisoned the whole
    # destination cache with empty results for real, resolvable airports.
    got = wikidata.iata_for_titles(["Aalborg_Airport"])
    assert got["Aalborg_Airport"] == "AAL"


@pytest.mark.network
def test_resolves_both_titles_when_two_collapse_to_the_same_page():
    # "Narita_Airport" redirects to the same article that "Narita_
    # International_Airport" already names directly, so in one batch
    # request both titles collapse to a single returned page. A page-keyed
    # alias map can only hand that one page back to ONE of the two inputs
    # and silently drops the other as "not an airport" -- this is the exact
    # bug that once left ICN->NRT missing from a fully-built route network.
    got = wikidata.iata_for_titles(["Narita_Airport", "Narita_International_Airport"])
    assert got["Narita_Airport"] == "NRT"
    assert got["Narita_International_Airport"] == "NRT"
