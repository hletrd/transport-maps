"""Ferry crossing time, sailing frequency and expected wait.

The ferry model used to be spread across three files in two layers: the
calibration dataclass sat in `graph/rail.py` (a ferry is not a train), the
crossing-time formula was inlined in `graph/build.py::_ferry_edges`, and no
file answered "how does the ferry model work" the way `graph/air.py` does for
flights. This module is the ferry's `air.py`.

What changed in substance, not just in location: **a ferry now pays for
waiting.** Before, every crossing on Earth was charged
`60*km/speed_kmh + terminal_min` -- a flat half hour -- so the Staten Island
Ferry and the twice-yearly Cape Town-Tristan da Cunha sailing cost the same
wait. Against the eight published headways in `calibration.toml` the error ran
from +7 minutes to -689 hours, median about -47 hours, which is six to fifteen
bands of a ladder whose ratio is 1.1526.

Three things supply the numbers, in descending order of how much they deserve
to be trusted:

1. **The OSM `duration` tag** for sailing time, where it parses and implies a
   plausible speed. Measured coverage over the 30,629 ferry ways in the
   extracts rises monotonically with distance -- 7.4% under 1 km to 66.7% at
   1,000-4,000 km -- so it is densest exactly where a straight-line chord is
   worst. It is measurement, not inference.
2. **The OSM `interval` tag** for the headway, where it parses. Only 1.8% of
   ways carry one (max 6.5% in any distance bucket), so it cannot be the
   primary source -- but where it exists it beats any model.
3. **A distance-based prior** for the headway otherwise, fitted to eight
   published anchors. Crossing length predicts headway across four orders of
   magnitude, which is why this is the honest fallback rather than a constant.
   Its spread is wide and `calibration.toml` says so.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass

from transport_maps import config
from transport_maps.graph.headway import MINUTES_PER_WEEK, expected_wait_min

# Shorter than this is a river crossing whose terminals land in one H3 cell
# anyway; longer than this is not a scheduled ferry route. The longest real
# link in the extracts is 2,793 km (Cape Town-Tristan da Cunha), so the upper
# bound has headroom and binds on nothing today.
#
# These are the ferry's `IMPLAUSIBLE_LONGHAUL_KM`: a hard plausibility bound
# with a fixed rationale, not a figure anyone would re-fit. They lived in
# `sources/osm.py`, whose job is to fetch and cache raw input, and they were
# hashed into the ferry parquet's cache key on the stated grounds that they
# "govern the parquet's content" -- which was never true, because the filter
# that applies them is here in the graph layer.
MIN_FERRY_KM, MAX_FERRY_KM = 1.0, 4000.0

# Below the shortest published anchor (Staten Island, 8 km) the headway prior
# is extrapolation, and a power law with a positive exponent collapses toward
# zero: at 1 km it predicts a 32-second headway and so a 16-second wait. Held
# flat at the anchor's own value instead, which is the same guard `air.KNEE_KM`
# applies at the other end of the same problem.
KNEE_KM = 8.0

# Floor on sailings per week, so a plausible-but-rare service is slow rather
# than infinite and stays inside the band ladder instead of silently becoming
# "no route".
#
# The value is DERIVED, not chosen to taste. `emit/hover.py` ships readings as
# uint16 with `MAX_MINUTES = 65534`; anything at or above it is written as the
# "no scheduled route" sentinel. A crossing costs at most
# wait + sailing + terminal + border, and the largest sailing this module will
# accept is bounded by MAX_FERRY_KM at MIN_SAILING_KMH. At 0.1 sailings per
# week the wait is 50,400 minutes, and 50,400 + 8,640 + 30 + 45 = 59,115 --
# inside the sentinel with room to spare. Raising the floor would clamp real
# services: Tristan da Cunha runs about nine sailings a year, 0.173 per week,
# so at 0.1 no published anchor is clamped by this bound at all.
MIN_SAILINGS_PER_WEEK = 0.1

# A parsed `duration` is trusted only if it implies a plausible average speed
# over the straight-line chord. This is what separates the three `HHH:MM`
# duration values in the extracts: `144:00` on the 2,793 km Tristan crossing is
# 19.4 km/h and is the real six-day sailing, while the same string on a 50 km
# hop would be 0.3 km/h and is a weekly INTERVAL written in the wrong field.
# Rejecting every `HHH:MM` would throw away the one genuine case; rejecting by
# implied speed keeps it and still refuses the mis-tagged ones.
#
# The chord understates the sailed path, so the implied speed is a LOWER bound
# on the vessel's own. 120 km/h (65 knots) is above any commercial ferry, and
# 5 km/h is slower than a rowing boat.
MIN_SAILING_KMH, MAX_SAILING_KMH = 5.0, 120.0

# A parsed `interval` is trusted within the same spirit: no scheduled service
# runs more often than every five minutes, and none less often than yearly.
# Tristan, the sparsest published anchor, is 1,251 h.
MIN_INTERVAL_MIN, MAX_INTERVAL_MIN = 5.0, 366 * 24 * 60.0


@dataclass(frozen=True)
class FerryCalibration:
    speed_kmh: float
    berth_min: float
    terminal_min: float
    interval_base_h: float
    interval_decay: float


def load_ferry_calibration(path=None) -> FerryCalibration:
    path = path or (config.ROOT / "calibration.toml")
    with open(path, "rb") as fh:
        return FerryCalibration(**tomllib.load(fh)["ferry"])


def plausible_crossing(km: float) -> bool:
    return MIN_FERRY_KM <= km <= MAX_FERRY_KM


def trusted_duration_min(km: float, duration_min: float | None) -> float | None:
    """The OSM sailing time, or None if it implies an impossible speed."""
    if duration_min is None or duration_min <= 0 or km <= 0:
        return None
    kmh = 60.0 * km / duration_min
    return duration_min if MIN_SAILING_KMH <= kmh <= MAX_SAILING_KMH else None


def sailing_min(km: float, cal: FerryCalibration, duration_min: float | None = None) -> float:
    """Time afloat: the tagged duration where it is usable, else the model.

    The model is AFFINE -- a fixed term plus a rate -- and that shape is the
    finding, not a stylistic choice. Rail solves its own version of this with a
    `detour_factor` on the distance, and a factor was tried here first: fitted
    against the tagged durations it came out at 2.90 in the 1-10 km bucket and
    1.18 above 1,000 km, so no single number serves both ends. The reason is
    that the short-range excess is not tortuosity at all. It is a per-crossing
    overhead -- casting off, manoeuvring out of the harbour, and berthing at
    the far side -- which is roughly constant and therefore dominates a 3 km
    crossing and vanishes on a 3,000 km one.

    With the overhead given its own term the rate stops fighting it: median
    predicted/observed is 1.00 overall and stays between 0.92 and 1.07 in every
    distance bucket from 1 km to 4,000 km. `calibration.toml` records the fit.

    `berth_min` is inside the SCHEDULED sailing time, which is what OSM's
    `duration` measures; `terminal_min` is the vehicle and foot loading either
    side of it, which a timetable does not include. They are separate charges
    for separate things, and the boundary between them is the moment the
    sailing is scheduled to begin.
    """
    tagged = trusted_duration_min(km, duration_min)
    if tagged is not None:
        return tagged
    return cal.berth_min + 60.0 * km / cal.speed_kmh


def prior_interval_min(km: float, cal: FerryCalibration) -> float:
    """The fitted distance-headway prior, held flat below the shortest anchor."""
    return 60.0 * cal.interval_base_h * max(km, KNEE_KM) ** cal.interval_decay


def sailings_per_week(
    km: float,
    cal: FerryCalibration,
    interval_min: float | None = None,
    service_fraction: float = 1.0,
) -> float:
    """Weekly sailings on a crossing known to exist.

    `service_fraction` is the share of the year the service runs, from the
    `seasonal` and `opening_hours` tags. A page with no date on it can only
    answer "leave now" as a year average, and a summer-only ferry that a
    traveller meets in February is genuinely not there -- so the frequency is
    scaled rather than the wait being quoted as if the boat ran all year.
    """
    usable = interval_min if interval_min and MIN_INTERVAL_MIN <= interval_min <= MAX_INTERVAL_MIN \
        else prior_interval_min(km, cal)
    per_week = MINUTES_PER_WEEK / usable
    return max(per_week * max(service_fraction, 0.0), MIN_SAILINGS_PER_WEEK)


def crossing_min(
    km: float,
    cal: FerryCalibration,
    *,
    duration_min: float | None = None,
    interval_min: float | None = None,
    service_fraction: float = 1.0,
    extra: float = 0.0,
) -> float:
    """Door-to-door cost of one crossing: wait, sail, terminal, border.

    All three components land on this single edge because a ferry deliberately
    has no node of its own (see `build._ferry_edges`). Air splits the same
    three across three edges only because it HAS intermediate nodes to hang
    them on; with one edge the sum is the same model, not a different one.
    """
    wait = expected_wait_min(sailings_per_week(km, cal, interval_min, service_fraction))
    return wait + sailing_min(km, cal, duration_min) + cal.terminal_min + extra
