"""Mode-change penalties."""

from transport_maps.graph.air import Calibration

# Countries sharing one immigration zone: a journey between any two of them
# crosses a national border but no passport desk. The same table serves the
# air model (keyed on OurAirports' `iso_country`) and every surface edge
# (keyed on Natural Earth's ISO_A2_EH, sources/countries.py), so the two
# cannot disagree about a code they both use.
#
# Membership was checked against official sources on 2026-10-02 (A15):
#
# - Schengen: the 29 states the European Commission lists -- 25 EU members
#   plus Iceland, Norway, Switzerland and Liechtenstein. Cyprus "participates"
#   but has not had its internal border controls lifted, and Ireland opts out
#   (https://home-affairs.ec.europa.eu/policies/schengen/schengen-area_en).
# - Åland (AX) is part of Finland and inside Schengen: no border check on the
#   Stockholm and Turku ferries. Its separate status is a TAX border (outside
#   the EU VAT area), which is a customs declaration for goods, not a passport
#   desk (Nordic Council, https://www.norden.org/en/info-norden/
#   passport-requirements-travel-aland; Finnish Tax Administration,
#   https://www.vero.fi/en/businesses-and-corporations/taxes-and-charges/vat/
#   international-commerce/value-added-taxation-of-imported-goods/
#   %C3%A5land-islands-tax-border-and-importing-goods/).
# - Monaco (MC): "the Schengen area, which includes Monaco"; France administers
#   its immigration and there are "no routine border controls between France
#   and Monaco" (GOV.UK, https://www.gov.uk/foreign-travel-advice/monaco/
#   entry-requirements; Singapore MFA, https://www.mfa.gov.sg/
#   travelling-overseas/travel-advisories-notices-and-visa-information/monaco/).
# - San Marino (SM): "San Marino follows Schengen area rules ... You do not
#   need to pass through border controls to enter San Marino" (GOV.UK,
#   https://www.gov.uk/foreign-travel-advice/san-marino/entry-requirements).
# - Vatican City (VA): no airport, no port, and an open border with Rome, so
#   the only way in is through Italy on Italy's Schengen rules. No official
#   page reachable on 2026-10-02 says so in one line (travel.state.gov's Holy
#   See page refused the fetch); the arrangement goes back to the Lateran
#   Treaty of 1929, art. 3 (St Peter's Square open to the public under Italian
#   police), and is summarised at https://en.wikipedia.org/wiki/
#   Italy%E2%80%93Vatican_City_border. A secondary source, recorded as one.
# - Common Travel Area: "the UK, Ireland and the Crown Dependencies (Jersey,
#   Guernsey and the Isle of Man)", with no routine immigration control on a
#   journey inside it (GOV.UK, https://www.gov.uk/guidance/
#   travelling-between-the-uk-and-ireland-isle-of-man-guernsey-or-jersey).
#
# Deliberately NOT in a shared zone, each checked the same day:
#
# - Andorra (AD): "not in the Schengen area" (GOV.UK, https://www.gov.uk/
#   foreign-travel-advice/andorra/entry-requirements). Its roads into France
#   and Spain are Schengen external borders with customs posts, so the land
#   border charge stands.
# - The French overseas departments -- Guadeloupe (GP), Martinique (MQ),
#   French Guiana (GF), Réunion (RE), Mayotte (YT) -- are France but OUTSIDE
#   Schengen, and a flight from Paris passes a border check: "le contrôle des
#   passagers (sortie de l'espace Schengen et entrée dans les 4 DOM) s'effectue
#   donc dans les aéroports métropolitains" (Assemblée nationale, question
#   15-1639QE, answer of 16 January 2018, https://questions.assemblee-
#   nationale.fr/q15/15-1639QE.htm). 2010 removed the SECOND check, on arrival
#   in the department, not the first (question 13-49630QE, answer of
#   14 September 2010). So a Paris-Réunion flight keeps its border charge;
#   CR-20's premise that no desk exists was checked and is wrong. On the
#   ground those cells are Natural Earth's FRA, i.e. Schengen; no surface edge
#   joins a department to Europe, so that reading changes no edge.
IMMIGRATION_ZONES: dict[str, str] = {
    **{c: "SCHENGEN" for c in (
        "AT", "BE", "BG", "CH", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
        "HR", "HU", "IS", "IT", "LI", "LT", "LU", "LV", "MT", "NL", "NO", "PL",
        "PT", "RO", "SE", "SI", "SK",
        # De facto members and a special territory, sourced above.
        "AX", "MC", "SM", "VA",
    )},
    **{c: "CTA" for c in ("IE", "GB", "IM", "JE", "GG")},
}

# Airports whose OurAirports `iso_country` names a different immigration
# authority from the one that actually stamps the passport. Mapped to the code
# the ground side reads for the same land, so air and surface agree.
#
# Ercan (ECN) is listed by OurAirports as CY, but it lies in the north, which
# Natural Earth calls CYN (no ISO code, so countries.iso2 keeps the A3). Its
# arrivals pass the northern administration's passport control, and the
# Republic of Cyprus treats entry there as illegal entry: "If you enter the
# Republic of Cyprus through the north (such as through Ercan Airport),
# authorities will consider you to have entered illegally" (GOV.UK,
# https://www.gov.uk/foreign-travel-advice/cyprus/entry-requirements). Of
# ECN's 30 directed pairs in the route network (measured 2026-10-02 on
# routes_21691ca7), 26 go to Turkey and cross a border either way; the other
# four, ECN<->LCA and ECN<->PFO (parsed from Ercan's own Wikipedia article),
# were a border-free "domestic" hop under CY and now pay the charge, as a
# journey between the two administrations does.
AIRPORT_COUNTRY: dict[str, str] = {
    "ECN": "CYN",
}


# Zones whose airports have no airside transit: every passenger arriving from
# another zone is admitted at the first airport, connecting or not, so a
# connection there is an ENTRY and the onward international flight pays its
# own border (graph/build.py, `_transfer_edges`). Elsewhere a connection stays
# airside and the border is paid once for the whole airside journey.
#
# The United States: "All passengers must be interviewed by U.S. Customs and
# Border Protection (CBP) and claim all checked luggage before being allowed
# to enter the U.S. including connecting travelers" (Port of Seattle,
# https://www.portseattle.org/page/international-connections, read
# 2026-10-02). An airport authority stating the federal rule; CBP's own
# visitor guide could not be read as text that day. Keyed on the zone, so it is OurAirports' "US" only: Puerto Rico, Guam and the other
# territories are zones of their own in this table today, which is a separate
# question (recorded in plan/2026-10-02-rebuild28-model.md).
# Not a calibration constant -- no minutes, only which rule applies -- so it
# lives beside the zone table rather than in calibration.toml.
NO_AIRSIDE_TRANSIT: frozenset[str] = frozenset({"US"})


def airside_transit(zone: str) -> bool:
    """Whether a passenger from another zone can connect in `zone` without
    being admitted to it."""
    return zone not in NO_AIRSIDE_TRANSIT


def immigration_zone(country: str) -> str:
    """The zone a country belongs to; its own code unless it shares one."""
    return IMMIGRATION_ZONES.get(country, country)


def airport_country(iata: str, country: str) -> str:
    """The country whose passport control an airport's arrivals pass:
    OurAirports' `iso_country` unless AIRPORT_COUNTRY corrects it."""
    return AIRPORT_COUNTRY.get(iata, country)


def crosses_border(dep_country: str, arr_country: str) -> bool:
    return immigration_zone(dep_country) != immigration_zone(arr_country)


def processing_min(size: str, cal: Calibration) -> float:
    """Check-in, security and boarding. Independent of where the flight goes."""
    return cal.processing_min[size]


def disembark_min(size: str, cal: Calibration) -> float:
    """Deplane and collect bags. Independent of where the flight came from."""
    return cal.disembark_min[size]


def border_min(size: str, cal: Calibration) -> float:
    """Emigration plus immigration, charged only on a border-crossing flight."""
    return cal.border_min[size]


def connection_min(size: str, cal: Calibration) -> float:
    return cal.connection_min[size]
