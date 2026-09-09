"""Mode-change penalties."""

from transport_maps.graph.air import Calibration

# Countries sharing one immigration zone: a flight between any two of them
# crosses a national border but no passport desk. Schengen plus the
# Ireland/UK Common Travel Area.
IMMIGRATION_ZONES: dict[str, str] = {
    **{c: "SCHENGEN" for c in (
        "AT", "BE", "BG", "CH", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
        "HR", "HU", "IS", "IT", "LI", "LT", "LU", "LV", "MT", "NL", "NO", "PL",
        "PT", "RO", "SE", "SI", "SK",
    )},
    **{c: "CTA" for c in ("IE", "GB")},
}


def immigration_zone(country: str) -> str:
    """The zone a country belongs to; its own code unless it shares one."""
    return IMMIGRATION_ZONES.get(country, country)


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
