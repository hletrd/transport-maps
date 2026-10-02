"""The ferry wait model: tag parsing, both bounds, and the anchor residuals.

Every assertion here was checked by mutation -- break the thing it names and
this file goes red. The mutations are recorded beside each test, because
CLAUDE.md's rule is that a test which passes on deliberately broken code is
worse than none, and this repository has shipped several of those.

Every certificate was re-run on 2026-10-02 (DOC13-13). Five said something the
run did not show and are corrected beside their tests; one of them, on the
bucket-median test, named a mutation that leaves that test green.
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
    Mutation: drop the ISO branch -> the three PT cases and P12D go red (four;
    this said three until it was re-run on 2026-10-02)."""
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
    -> 14 of the 19 cases go red. Not every case, as this used to claim: None,
    "", "   ", "PT" and "P" return before reaching that line, so they stay
    green under it (re-run 2026-10-02)."""
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

    Mutation: drop MIN_SAILINGS_PER_WEEK from sailings_per_week -> red: with
    service_fraction=0.0 the weekly count is 0, the wait becomes
    headway.NO_SERVICE (10,000,000 min) and the crossing far exceeds the
    sentinel. (This said "196,560 min, three times the sentinel", a figure no
    run of this mutation produces; re-run 2026-10-02.)"""
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


def test_the_critics_two_recorded_objections_hold_for_the_shipped_fit():
    """c8 T1.9 recorded three of the critic's five objections in the [ferry]
    comment and ticked all five (C13-11 / V13-3). The other two are now in the
    comment with figures, and this test re-derives those figures from the
    anchors so the comment cannot drift from the fit it describes.

    Mutations performed (2026-10-02), each RED, each restored:
      - interval_decay 1.5137 -> 1.40 in calibration.toml     -> RED
      - "falls from 1.514 to 1.401" -> "to 1.45" in the comment -> RED
      - "charges 35 h of the 84 h" -> "50 h" in the comment     -> RED
    """
    from transport_maps import config

    text = (config.ROOT / "calibration.toml").read_text(encoding="utf-8")
    x = np.log([max(km, ferry.KNEE_KM) for _, km, _ in ANCHORS])
    y = np.log([hours for _, _, hours in ANCHORS])

    # The shipped coefficients ARE the log-space least-squares fit to the eight.
    decay, log_base = np.polyfit(x, y, 1)
    assert CAL.interval_decay == pytest.approx(decay, abs=5e-4)
    assert CAL.interval_base_h == pytest.approx(np.exp(log_base), rel=1e-3)

    # Objection 1: on the Arctic Umiaq Line the prior charges 41% of the wait.
    umiaq_h = ferry.prior_interval_min(372, CAL) / 60.0
    assert round(umiaq_h) == 69 and round(umiaq_h / 168.0, 2) == 0.41
    assert f"charges\n#   {round(umiaq_h / 2)} h of the {168 // 2} h expected wait" in text

    # Objection 2: the three weekly anchors within 141 km carry the exponent.
    weekly = [i for i, (_, _, h) in enumerate(ANCHORS) if h == 168.0]
    kms = [ANCHORS[i][1] for i in weekly]
    assert len(weekly) == 3 and max(kms) - min(kms) == 141
    keep = [i for i in range(len(ANCHORS)) if i not in weekly]
    decay_without, log_base_without = np.polyfit(x[keep], y[keep], 1)
    at_372 = np.exp(log_base_without) * 372 ** decay_without
    assert (f"the decay falls from {CAL.interval_decay:.3f}\n#   to {decay_without:.3f} "
            f"and the 372 km interval from {umiaq_h:.0f} h to {at_372:.0f} h") in text


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

    Mutation: drop `cal.berth_min +` from ferry.sailing_min -> red: the
    inversion above no longer reproduces any bucket's median.

    NOT this one, which the docstring certified until 2026-10-02: setting
    berth_min to 0.0 in calibration.toml leaves THIS test green. At 29.1 km/h
    the 1-10 km median implies 9.7 km, still inside the bucket, and every other
    row stays inside its own; the final assertion is arithmetic on constants
    (20 min at the old 35 km/h) and cannot see calibration.toml at all. That
    mutation is caught by
    test_the_sailing_coefficients_are_the_ones_calibration_toml_documents
    instead."""
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


# ---- the floor's upper end, on the only two inhabited places the map declines


#: Of every populated place in the gazetteer above 60N or below 40S, exactly
#: two read unreachable from Seoul in the shipped build, and both are
#: defensible rather than defects: Port-aux-Francais on Kerguelen, whose supply
#: ship sails about four times a year, and Grytviken on South Georgia, which
#: has no scheduled service at all. Neither has a `route=ferry` way in the
#: extracts, so the model does not reach them and is not asked to.
#:
#: They are still the right regression cases for the floor's UPPER end, because
#: they are the sparsest real services anywhere near the data. The rule they
#: pin: if a crossing like this ever does enter the data, the model must
#: produce WEEKS, not days, and must stay inside the uint16 sentinel rather
#: than silently becoming "no scheduled route".
SPARSEST = [
    # (label, km, sailings per year or None where there is no schedule)
    ("Reunion - Kerguelen (Marion Dufresne)", 3398.0, 4),
    ("Falklands - South Georgia (no schedule)", 1451.0, None),
]


@pytest.mark.parametrize("label,km,per_year", SPARSEST, ids=[s[0] for s in SPARSEST])
def test_the_sparsest_plausible_crossings_cost_weeks_and_stay_inside_the_sentinel(
        label, km, per_year):
    """Mutation: drop MIN_SAILINGS_PER_WEEK -> the Kerguelen case exceeds the
    sentinel. Mutation: raise the floor to 1.0/week -> both cases go red, but
    not both on "weeks, not days" as this used to say: South Georgia falls to
    5.6 days and fails that assertion, while Kerguelen stays at 8.4 days and
    fails the 3x-the-old-model assertion instead (re-run 2026-10-02)."""
    modelled = ferry.crossing_min(km, CAL)
    assert modelled < hover.MAX_MINUTES, (
        f"{label} costs {modelled:,.0f} min, at or above the {hover.MAX_MINUTES:,} "
        "sentinel: a real if rare service would ship as 'no scheduled route'")
    assert modelled > 7 * 1440, (
        f"{label} costs only {modelled / 1440:.1f} days; a crossing this sparse "
        "must read as weeks")
    # The teeth: the OLD model charged the same two crossings 1.7 and 4.0 days,
    # because it charged a flat half hour of waiting whatever the timetable.
    old_model = 60.0 * km / 35.0 + 30.0
    assert old_model < 5 * 1440
    assert modelled > 3 * old_model


def test_the_floor_clamps_kerguelen_and_the_plan_says_by_how_much():
    """The one place the floor is known to bind, recorded rather than hidden.

    Four sailings a year is 0.0769 per week, below the 0.1 floor, so the model
    charges the floor's 35-day ceiling against a true expected wait of about
    45.5 days. That understatement is the price of keeping the total inside the
    uint16 sentinel, and it is stated in calibration.toml and the cycle plan
    rather than left for someone to discover.

    Mutation: lower MIN_SAILINGS_PER_WEEK below 0.0769 -> the clamp assertion
    goes red, and the sentinel headroom shrinks toward the overflow the floor
    exists to prevent."""
    km, per_week = 3398.0, 4 / 52.0
    assert per_week < ferry.MIN_SAILINGS_PER_WEEK, (
        "Kerguelen is no longer below the floor; the clamp this test describes "
        "has gone away and calibration.toml should say so")
    assert ferry.sailings_per_week(km, CAL) == pytest.approx(ferry.MIN_SAILINGS_PER_WEEK)
    clamped = ferry.expected_wait_min(ferry.MIN_SAILINGS_PER_WEEK)
    true_wait = (7 * 24 * 60) / per_week / 2
    assert clamped < true_wait, "the floor is meant to UNDER-state a sub-floor service"
    # ...and the understatement stays within the factor the documents claim.
    assert true_wait / clamped == pytest.approx(1.3, abs=0.05)
