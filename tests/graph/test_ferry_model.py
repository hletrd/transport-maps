"""The ferry wait model: tag parsing, both bounds, and the anchor residuals.

Every assertion here was checked by mutation -- break the thing it names and
this file goes red. The mutations are recorded beside each test, because
CLAUDE.md's rule is that a test which passes on deliberately broken code is
worse than none, and this repository has shipped several of those.
"""

import numpy as np
import pytest

from transport_maps.emit import hover
from transport_maps.graph import ferry
from transport_maps.sources import osm

CAL = ferry.load_ferry_calibration()

# The eight published headways calibration.toml names as the fit's anchors:
# (label, great-circle km, published interval in hours).
ANCHORS = [
    ("Staten Island", 8, 0.4),
    ("Dover-Calais", 42, 1.5),
    ("Helsinki-Tallinn", 82, 3.0),
    ("Naples-Palermo", 315, 24.0),
    ("Arctic Umiaq Line", 372, 168.0),
    ("Torshavn-Seydisfjordur", 508, 168.0),
    ("AMHS Whittier-Yakutat", 513, 168.0),
    ("Cape Town-Tristan da Cunha", 2793, 1251.0),
]


# ---- the tag parser -------------------------------------------------------
# The accepted set is the OBSERVED set: measured over all 30,629 route=ferry
# ways in the seven extracts, these five forms cover 99.7% of `duration` and
# 92.4% of `interval`.

@pytest.mark.parametrize("raw,minutes", [
    ("02:30", 150.0),            # HH:MM -- 3,583 of 4,598 duration tags
    ("00:05", 5.0),
    ("1:50", 110.0),             # H:MM -- 631
    ("0:15", 15.0),
    ("35", 35.0),                # bare minutes -- 226
    ("08", 8.0),
    ("00:45:00", 45.0),          # H:MM:SS -- 102
    ("06:30:00", 390.0),
    ("PT1H", 60.0),              # ISO-8601 -- 40
    ("PT15M", 15.0),
    ("PT20S", pytest.approx(1 / 3)),
    ("P12D", 12 * 1440.0),       # a real multi-day sailing, on a relation
    ("144:00", 8640.0),          # HHH:MM: the genuine Tristan sailing
    (" 02:30 ", 150.0),          # surrounding whitespace is not a rejection
])
def test_parse_minutes_accepts_every_observed_format(raw, minutes):
    """Mutation: drop the _BARE_MIN branch -> the '35' and '08' cases go red.
    Mutation: drop the ISO branch -> the three PT cases go red."""
    assert osm.parse_minutes(raw) == minutes


@pytest.mark.parametrize("raw", [
    "1:00, 0:30 (Peak), On request",   # free text: 27 of 552 interval tags
    "three_times_a_day",               # day/count phrase: 10
    "2 per week",
    "at_least:180",
    "on demand",
    "IV - V: 3x/semaine;VI-IX: daily",
    "24:30 h",                         # a unit word after the time
    "15min",
    "2,5",                             # comma decimal
    "6分钟",
    "00:2",                            # malformed
    "00:8",
    "20, 40",
    "01:70",                           # 70 minutes is not a time
    "",
    "   ",
    None,
    "PT",                              # says nothing
    "P",
])
def test_parse_minutes_rejects_what_it_cannot_read(raw):
    """Rejected, not guessed at. A value like "1:00, 0:30 (Peak), On request"
    carries real information that no single number represents, and inventing
    one would be worse than admitting there is none.

    Mutation: make the final `return None` fall through to `float(t.split(':')[0])`
    -> every case here goes red."""
    assert osm.parse_minutes(raw) is None


def test_a_three_digit_duration_is_kept_or_dropped_by_implied_speed():
    """The one place the parser cannot decide and the model can.

    `144:00` appears on the 2,793 km Cape Town-Tristan crossing, where it is
    the real six-day sailing at 19.4 km/h. The same string on a 50 km hop is a
    weekly INTERVAL written into the duration field, and accepting it would
    book a five-day sail across the Baltic. Rejecting every HHH:MM would throw
    the genuine case away with the mis-tagged ones, so the test is the implied
    speed rather than the string.

    Mutation: return `duration_min` unconditionally from
    trusted_duration_min -> the second assertion goes red."""
    assert ferry.trusted_duration_min(2793.0, 8640.0) == 8640.0
    assert ferry.trusted_duration_min(50.0, 8640.0) is None
    # ...and impossibly FAST is refused too: 4,000 km in an hour is not a boat.
    assert ferry.trusted_duration_min(4000.0, 60.0) is None


# ---- seasonality ----------------------------------------------------------

@pytest.mark.parametrize("tags,fraction", [
    ({}, 1.0),
    ({"seasonal": "no"}, 1.0),
    ({"opening_hours": "24/7"}, 1.0),
    ({"seasonal": "yes"}, 5 / 12),                       # 71 ways
    ({"seasonal": "summer"}, 3 / 12),                    # 96 ways
    ({"seasonal": "spring;summer;autumn"}, 9 / 12),      # 39 ways
    ({"seasonal": "April-October"}, 7 / 12),             # 4 ways
    ({"seasonal": "yes", "opening_hours": "24/7"}, 1.0),  # 24/7 wins: it says so
    ({"opening_hours": "Mo-Fr 08:00-18:00"}, 1.0),       # within-day: NOT modelled
    ({"seasonal": "limited"}, 1.0),                      # unparseable, so unchanged
])
def test_the_service_fraction_reads_the_tags_it_can_and_leaves_the_rest(tags, fraction):
    """Mutation: return 1.0 unconditionally -> the four seasonal cases go red.

    The last two cases are the honest limits, asserted so they cannot be
    quietly "improved" into a guess: an opening_hours expression restricted
    within the day is not modelled at all (879 ways carry one), and a
    `seasonal` value in no recognised shape is left alone rather than assumed
    to mean half a year."""
    assert osm.service_fraction(tags) == pytest.approx(fraction)


# ---- the two bounds -------------------------------------------------------

def test_the_knee_holds_the_prior_flat_below_the_shortest_anchor():
    """Below 8 km -- the Staten Island crossing, the shortest published anchor
    -- the prior is extrapolation, and a power law with a positive exponent
    collapses toward zero: unheld, a 1 km river crossing gets a 32-second
    headway and a 16-second wait.

    Mutation: replace `max(km, KNEE_KM)` with `km` -> the first assertion goes
    red (0.53 min instead of 12.4)."""
    at_knee = ferry.prior_interval_min(ferry.KNEE_KM, CAL)
    assert ferry.prior_interval_min(1.0, CAL) == pytest.approx(at_knee)
    assert ferry.prior_interval_min(0.01, CAL) == pytest.approx(at_knee)
    # ...and it must not bind on anything above the knee.
    assert ferry.prior_interval_min(ferry.KNEE_KM * 2, CAL) > at_knee


def test_the_floor_keeps_the_whole_crossing_inside_the_uint16_sentinel():
    """The reason the floor exists, stated as arithmetic.

    Readings ship as uint16 and `hover.MAX_MINUTES` is the largest value that
    is not the "no scheduled route" sentinel. A correct Pitcairn wait is about
    65,700 minutes -- over the sentinel -- so without a floor a real, slow,
    correctly-modelled crossing would ship as UNREACHABLE while check_coverage
    still counted the cell covered.

    Mutation: drop MIN_SAILINGS_PER_WEEK from sailings_per_week -> red at
    4,000 km (196,560 min, three times the sentinel)."""
    worst = ferry.crossing_min(
        ferry.MAX_FERRY_KM, CAL,
        interval_min=ferry.MAX_INTERVAL_MIN,     # the sparsest service accepted
        service_fraction=0.0,                    # and out of season on top
        extra=60.0,                              # and across a border
    )
    assert worst < hover.MAX_MINUTES, (
        f"a plausible-but-rare crossing costs {worst:,.0f} min, at or above the "
        f"{hover.MAX_MINUTES:,} sentinel: it would ship as 'no scheduled route'")


def test_the_floor_does_not_clamp_any_published_anchor():
    """A floor that hides a real value behind a principled-looking constant
    would be worse than none -- the ferry tail is genuinely long (Tristan runs
    about nine sailings a year, 0.173 per week). 0.1 per week sits below every
    anchor, so the floor bounds the sentinel without touching the model.

    Mutation: raise MIN_SAILINGS_PER_WEEK to 0.5 -> red on Tristan."""
    for label, km, hours in ANCHORS:
        published_per_week = (7 * 24) / hours
        assert published_per_week > ferry.MIN_SAILINGS_PER_WEEK, (
            f"the floor clamps {label}, a real published service")


# ---- the fit, against its own anchors -------------------------------------

def test_the_prior_matches_its_anchors_within_the_documented_spread():
    """calibration.toml records a log-residual sd of 0.679, i.e. a factor of
    1.97 at one sigma, and per-anchor ratios from 0.41 to 2.34. Those numbers
    are the published error; this test is what stops them drifting silently
    away from the coefficients actually shipped.

    Mutation: change interval_decay to 1.40 in calibration.toml -> red (the sd
    rises to 0.83 and Tristan's ratio falls to 0.53)."""
    ratios = np.array([ferry.prior_interval_min(km, CAL) / (hours * 60.0)
                       for _, km, hours in ANCHORS])
    sd = float(np.log(ratios).std(ddof=1))
    assert sd == pytest.approx(0.679, abs=0.02), f"log-residual sd is {sd:.3f}"
    assert ratios.min() == pytest.approx(0.41, abs=0.03)
    assert ratios.max() == pytest.approx(2.34, abs=0.05)


def test_the_sailing_coefficients_are_the_ones_calibration_toml_documents():
    """calibration.toml prints a residual table for `berth_min = 11.2` and
    `speed_kmh = 29.1`. If the shipped values move, that table is describing a
    fit the model no longer applies -- which is exactly the defect the
    [frequency] table above it is on record for.

    Mutation: change either value in calibration.toml -> red."""
    assert CAL.berth_min == pytest.approx(11.2, abs=0.05)
    assert CAL.speed_kmh == pytest.approx(29.1, abs=0.05)


def test_the_sailing_model_reproduces_the_published_bucket_medians():
    """The fit's claim, checked without needing the sample.

    Inverting is what makes this testable: `sailing_min` is monotone, so for
    each distance bucket there is exactly one distance at which the model
    predicts that bucket's published median observed time -- and if the fit is
    good, that distance falls INSIDE the bucket. All six do.

    The final assertion is the point of the affine form. For the 1-10 km
    bucket, the old pure-35 km/h model reproduces the 20-minute median only at
    11.7 km, outside the bucket entirely: a short crossing takes far longer
    than its length implies, because casting off and berthing do not scale
    with distance. That is the failure no single detour factor could fix, and
    it is why `berth_min` exists.

    Mutation: set berth_min to 0.0 -> the 1-10 km row implies 9.7 km, and the
    final assertion's `old` figure becomes the model's own, so the last line
    goes red."""
    # (bucket, median observed minutes) -- calibration.toml's own table
    for (lo, hi), observed in [((1, 10), 20.0), ((10, 50), 60.0), ((50, 150), 200.0),
                               ((150, 400), 570.0), ((400, 1000), 1200.0),
                               ((1000, 4000), 2280.0)]:
        km = (observed - CAL.berth_min) * CAL.speed_kmh / 60.0
        assert lo <= km <= hi, (
            f"the fit reproduces the {lo}-{hi} km bucket's {observed:.0f} min median "
            f"only at {km:.0f} km, outside the bucket")
        assert ferry.sailing_min(km, CAL) == pytest.approx(observed, rel=1e-6)

    # The old model, on the bucket where it was worst.
    old_km = 20.0 * 35.0 / 60.0
    assert old_km > 10, (
        "the pure-speed model reproduces the 1-10 km median inside the bucket, so "
        "berth_min is not carrying the per-crossing overhead it was fitted for")


def test_the_expected_wait_is_half_the_headway_and_says_so():
    """Mutation: change the /2.0 in headway.expected_wait_min to /1.0 -> red."""
    from transport_maps.graph import headway
    assert headway.expected_wait_min(7.0) == 720        # daily -> 12 h
    assert headway.expected_wait_min(14.0) == 360       # twice daily -> 6 h
    assert headway.expected_wait_min(1.0) == 5040       # weekly -> 84 h
    assert headway.expected_wait_min(0.0) == headway.NO_SERVICE
