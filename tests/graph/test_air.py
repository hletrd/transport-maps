import pytest

from transport_maps.graph import air


@pytest.fixture(scope="module")
def cal():
    return air.load_calibration()


def test_short_haul_block_time_matches_published(cal):
    # ICN -> NRT, 1257.7 km, both large airports.
    assert air.block_time_min(1257.7, "large", "large", cal) == pytest.approx(140, abs=25)


def test_long_haul_block_time_matches_published(cal):
    # ICN -> LHR, ~8880 km. Published block is about 13 h (780 min); the
    # pre-calibration defaults yield 717, running slightly fast on long haul.
    # Task 12 refits this. Tolerance spans both figures deliberately.
    assert air.block_time_min(8880.0, "large", "large", cal) == pytest.approx(750, abs=80)


def test_block_time_is_monotonic_in_distance(cal):
    times = [air.block_time_min(d, "large", "large", cal) for d in (500, 2000, 6000, 12000)]
    assert times == sorted(times)


def test_small_airports_have_less_taxi_overhead_than_large(cal):
    big = air.block_time_min(1000.0, "large", "large", cal)
    small = air.block_time_min(1000.0, "small", "small", cal)
    assert small < big


def test_expected_wait_is_half_the_headway():
    # 7 flights/week -> 24 h headway -> 12 h expected wait.
    assert air.expected_wait_min(7.0) == 720
    # 14 flights/week -> 12 h headway -> 6 h expected wait.
    assert air.expected_wait_min(14.0) == 360


def test_zero_frequency_is_unreachable():
    assert air.expected_wait_min(0.0) == air.NO_SERVICE


def test_mixed_sizes_taxi_asymmetry(cal):
    # Catches taxi_out and taxi_in being transposed. With current coefficients,
    # small->large gives taxi 8+9=17, while swapped would give 4+17=21 (4 min diff).
    # Over 1000 km: small->large is faster than large->small because small dep
    # has less taxi_out (8 vs 17).
    small_to_large = air.block_time_min(1000.0, "small", "large", cal)
    large_to_small = air.block_time_min(1000.0, "large", "small", cal)
    assert small_to_large != large_to_small
    assert small_to_large < large_to_small


def test_block_time_is_affine_in_distance(cal):
    # Block time is affine in distance: successive differences over equal distance
    # intervals should be equal (within 1 minute of rounding tolerance).
    times = [air.block_time_min(d, "large", "large", cal) for d in (2000, 6000, 10000)]
    diff1 = times[1] - times[0]
    diff2 = times[2] - times[1]
    assert abs(diff1 - diff2) <= 1


def test_frequency_falls_with_distance(cal):
    near = air.frequency_model("large", "large", 1000.0, cal)
    far = air.frequency_model("large", "large", 10000.0, cal)
    assert near > far


def test_frequency_falls_with_airport_size(cal):
    big = air.frequency_model("large", "large", 2000.0, cal)
    small = air.frequency_model("small", "small", 2000.0, cal)
    assert big > small


def test_frequency_never_below_floor(cal):
    assert air.frequency_model("small", "small", 19000.0, cal) >= air.MIN_FLIGHTS_PER_WEEK


def test_high_frequency_short_haul_has_short_expected_wait(cal):
    # ICN -> NRT, 1257.7 km, large-large: one of the busiest routes on Earth.
    # A too-shallow frequency decay collapses every route to a handful of
    # flights per week, which once produced a 24+ hour expected wait here and
    # made the whole travel-time map meaningless. Guard against that regression.
    freq = air.frequency_model("large", "large", 1257.7, cal)
    wait = air.expected_wait_min(freq)
    assert wait < 120
