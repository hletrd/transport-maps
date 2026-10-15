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
3. **A published headway** for a handful of busy corridors whose ways carry
   no `interval` (`PUBLISHED_HEADWAYS`): each row is an operator timetable,
   cited and dated, not a fitted number.
4. **A distance-based prior** for the headway otherwise, fitted to eight
   published anchors. Crossing length predicts headway across four orders of
   magnitude, which is why this is the honest fallback rather than a constant.
   Its spread is wide and `calibration.toml` says so.
"""

from __future__ import annotations

import math
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
# "no scheduled route" sentinel. A crossing costs
# wait + sailing + terminal + border, and at 0.1 sailings per week the wait is
# 50,400 minutes.
#
# What that guarantees, exactly. For a crossing whose sailing time this module
# MODELS -- `berth_min + 60 * km / speed_kmh` -- the worst case is
# MAX_FERRY_KM at the fitted speed: 11.2 + 60 * 4000 / 29.1 = 8,258 min, and
# 50,400 + 8,258 + 30 + 45 = 58,733. Inside the sentinel, with room.
#
# What it does NOT guarantee, and this comment used to claim it did. A crossing
# that carries a `duration` TAG is trusted up to `plausible_speed`'s lower
# bound, so the accepted sailing is bounded by MAX_FERRY_KM at
# MIN_SAILING_KMH -- 4000 / 5 = 800 h = 48,000 min, not the 8,640 this
# derivation used to substitute for it (8,640 is 144 h, the largest tagged
# duration actually observed, which is a different quantity). The real worst
# case is 50,400 + 48,000 + 30 + 45 = 98,475, which OVERFLOWS the sentinel and
# would ship as "no scheduled route" while `check_coverage` still counts the
# cell covered.
#
# No such crossing exists in the extracts today -- it needs a 4,000 km link
# tagged at about 5 km/h AND at the sailings floor -- so this is a latent gap,
# not a live defect. The fix is a clamp on `crossing_min`, which changes an
# emitted number and therefore waits for a cycle that may rebuild; it is
# recorded as DEF9-8 in plan/2026-09-13-c9-page-failure-paths.md.
#
# Raising the floor would clamp real services: Tristan da Cunha runs about nine
# sailings a year, 0.173 per week, so at 0.1 no published anchor is clamped by
# this bound at all.
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
class PublishedHeadway:
    """One busy corridor's headway, read off its operators' timetables.

    `a` and `b` are the two terminals as the OSM ways map them; a way whose two
    ends lie within `radius_km` of them, either way round, is on the corridor.
    `headway_min` is the mean gap between departures over the hours the
    corridor is served -- the same quantity as OSM's `interval` tag and as the
    published anchors the prior was fitted to, so a night with no sailing is not
    charged, here or anywhere else in the ferry model. `sailing_min`, where
    given, is the timetabled time afloat, used for a way with no usable
    `duration` tag -- the same quantity as that tag. `basis` says how the
    figures came out of the timetable, `source` where the timetable is, and
    `checked` when it was read.
    """

    name: str
    a: tuple[float, float]
    b: tuple[float, float]
    radius_km: float
    headway_min: float
    basis: str
    source: str
    checked: str
    sailing_min: float | None = None


# Published-figure inputs, not fitted constants: the corridors where the prior
# was wrong by HOURS of waiting, which `calibration.toml` documents as its
# real limitation ("distance alone cannot tell a remote lifeline route from a
# busy short-sea one") and which the audit of 2026-10-14 found on the map:
# Hong Kong -> Macau read 2 h 47 overland because the prior charged the
# TurboJET 131-138 min of waiting, and Helsinki -> Tallinn without flights
# read 5 h 53 against 3 h 06 for a 200 min wait on a crossing that sails every
# 85 min. A crossing whose wait the prior already gets within about a factor
# of 1.5 is left to it (Naples-Capri, Piraeus-Aegina, Tarifa-Tangier,
# Algeciras-Ceuta, Singapore-Batam: 41-49 min against 20-40 published), as is
# every short crossing at the 8 km knee (Bosphorus, Staten Island, Messina,
# Helsingor: 6-8 min), and Busan-Fukuoka, where the prior's 28 h headway is
# the real one now that the Queen Beetle has stopped. An OSM `interval` tag on
# a way still wins over a row here: it is that way's own figure.
PUBLISHED_HEADWAYS = (
    PublishedHeadway(
        "Hong Kong (Sheung Wan) - Macau (Outer Harbour)",
        (22.2888, 114.1528), (22.1968, 113.5605), 1.5, 39.0,
        "TurboJET, 25 sailings each way 07:30-23:00: 930 min / 24 gaps",
        "https://www.turbojet.com.hk/en/routing-sailing-schedule/hong-kong-macau/sailing-schedule-fares",
        "2026-10-14 (timetable effective 2026-02-11)"),
    PublishedHeadway(
        "Hong Kong (Sheung Wan) - Macau (Taipa)",
        (22.2885, 114.1528), (22.1666, 113.5762), 1.5, 200.0,
        "TurboJET, 11:00, 14:30, 18:00, 21:00: 600 min / 3 gaps",
        "https://www.turbojet.com.hk/en/routing-sailing-schedule/hong-kong-macau/sailing-schedule-fares",
        "2026-10-14 (timetable effective 2026-02-11)"),
    PublishedHeadway(
        "Helsinki - Tallinn",
        (60.155, 24.935), (59.444, 24.766), 3.0, 85.0,
        "Tallink, Viking Line and Eckero Line, 11 departures 07:30-21:40 "
        "on 2026-10-15: 850 min / 10 gaps; the 12 direct sailings of 2026-10-16 "
        "take 120 (Tallink), 135 (Eckero) and 150 (Viking XPRS) min, median "
        "135, for the one way with no duration tag (the prior gave it 174)",
        "https://laivaliput.fi/timetables/eng/helsinki-tallinn.html",
        "2026-10-15", sailing_min=135.0),
    PublishedHeadway(
        "Dover - Calais",
        (51.125, 1.335), (50.972, 1.862), 2.0, 48.0,
        "P&O, DFDS and Irish Ferries, 211 sailings a week round the clock: "
        "10,080 min / 211",
        "https://www.directferries.com/dover_calais_ferry.htm",
        "2026-10-14"),
    PublishedHeadway(
        "Dar es Salaam - Zanzibar",
        (-6.8208, 39.2889), (-6.1572, 39.1916), 1.5, 95.0,
        "Azam Marine 07:00, 09:30, 12:30, 16:00 and Zan Fast Ferries 07:00, "
        "12:00, 14:15, 16:30: 7 departures, 570 min / 6 gaps; the crossing "
        "\"takes 1 1/2 to 2 hours, depending on the vessel\": 105 min. The OSM "
        "way has no duration, and the speed prior sailed it in 165",
        "https://wildtosea.com/en/plan/dar-zanzibar-ferry/",
        "2026-10-15 (page updated 2026-09-25)", sailing_min=105.0),
    PublishedHeadway(
        "Wellington - Picton",
        (-41.272, 174.785), (-41.284, 174.005), 2.0, 229.0,
        "Interislander 19 and Bluebridge 25 sailings a week, 02:00-20:30, "
        "week of 2026-10-05: 10,080 min / 44; both take \"around 3 hours 30 "
        "minutes\": 210 min, which the tagged ways say too -- the one untagged "
        "way sailed in 146 under the prior and undercut them",
        "https://www.directferries.com/wellington_picton_ferry.htm",
        "2026-10-15", sailing_min=210.0),
    PublishedHeadway(
        "Dalian (Dalian Bay) - Yantai",
        (39.026, 121.739), (37.578, 121.383), 3.0, 197.0,
        "Bohai Ferry and others from Dalian Bay, 2026-10-01: 12:50, 22:00, "
        "22:10, 22:40, 590 min / 3 gaps; sailing \"6-7 hours\" there and 7 h "
        "on the operators' 2023 table: 420 min. The operator's own site "
        "(bohaiferry.com) refused connections; the prior charged 552 min of "
        "waiting and sailed it in 5 h 30. The old port's ways keep the prior",
        "https://www.sina.cn/news/article/nitrshv1838393.html",
        "2026-10-15 (article 2026-10-01; table "
        "http://dl.bendibao.com/traffic/2023825/79395.shtm, 2023-08-25)",
        sailing_min=420.0),
)


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = math.pi / 180.0
    h = (math.sin((b[0] - a[0]) * r / 2) ** 2
         + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin((b[1] - a[1]) * r / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def published_row(from_ll: tuple[float, float], to_ll: tuple[float, float]) -> PublishedHeadway | None:
    """The PUBLISHED_HEADWAYS row for a way with these two ends, or None."""
    for row in PUBLISHED_HEADWAYS:
        for p, q in ((from_ll, to_ll), (to_ll, from_ll)):
            if _km(p, row.a) <= row.radius_km and _km(q, row.b) <= row.radius_km:
                return row
    return None


def published_headway_min(from_ll: tuple[float, float], to_ll: tuple[float, float]) -> float | None:
    """The PUBLISHED_HEADWAYS headway for a way with these two ends, or None."""
    row = published_row(from_ll, to_ll)
    return row.headway_min if row is not None else None


def published_sailing_min(from_ll: tuple[float, float], to_ll: tuple[float, float]) -> float | None:
    """The PUBLISHED_HEADWAYS sailing time for a way with these two ends, or None."""
    row = published_row(from_ll, to_ll)
    return row.sailing_min if row is not None else None


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
