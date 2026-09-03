"""Mode-change penalties."""

from transport_maps.graph.air import Calibration

# Defined here for Task 9 (rail) to consume once station nodes exist in the
# graph. Not wired into build_graph yet -- there is no station_index to wire
# them to (Task 9 is blocked on the OSM extract). Intentionally unused for now.
STATION_ACCESS_MIN = 15.0
STATION_EGRESS_MIN = 10.0


def access_min(size: str, international: bool, cal: Calibration) -> float:
    key = "international" if international else "domestic"
    return cal.access_min[key][size]


def egress_min(size: str, international: bool, cal: Calibration) -> float:
    key = "international" if international else "domestic"
    return cal.egress_min[key][size]


def connection_min(size: str, cal: Calibration) -> float:
    return cal.connection_min[size]
