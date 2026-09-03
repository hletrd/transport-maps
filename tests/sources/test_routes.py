from pathlib import Path

import pytest

from transport_maps.sources import routes, wikidata

FIXTURE = Path(__file__).parent.parent / "fixtures" / "icn_airlines_table.html"


def test_parses_destination_article_titles_from_real_page():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    assert len(titles) > 50
    # Narita and Los Angeles are long-standing ICN destinations.
    assert any("Narita" in t for t in titles)
    assert any("Los_Angeles" in t or "Los Angeles" in t for t in titles)


def test_ignores_non_destination_links():
    titles = routes.parse_destinations(FIXTURE.read_text(encoding="utf-8"))
    # Citation, file and category links must not leak into the destination list.
    assert not any(t.startswith(("File:", "Category:", "Help:", "#cite")) for t in titles)


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
