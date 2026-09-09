"""Every colour scheme shipped in web/app.js is measured, not eyeballed.

`check_ramps` is the scripts/check_ramps.py module, loaded by a conftest
fixture rather than by mutating sys.path for the whole session.
"""


def test_every_ramp_is_monotonic_and_separable(check_ramps):
    found = check_ramps.ramps()
    assert len(found) >= 6, "RAMPS not parsed from app.js"
    for key, r in found.items():
        assert len(r["c"]) == 11, f"{key}: {len(r['c'])} anchors, expected 11"
        assert not check_ramps.problems(r["c"]), f"{key}: {check_ramps.problems(r['c'])}"


def test_a_ramp_with_a_lightness_reversal_is_caught(check_ramps):
    bad = ["#faefc5", "#f6d49c", "#f5b77b", "#ef9a69", "#e27e65", "#cd686a",
           "#b0586f", "#8f4d6e", "#6d4464", "#503955", "#6d4464"]  # last is lighter again
    assert any("decreasing" in p for p in check_ramps.problems(bad))


def test_two_near_identical_anchors_are_caught(check_ramps):
    bad = ["#faefc5", "#f9eec4", "#f5b77b", "#ef9a69", "#e27e65", "#cd686a",
           "#b0586f", "#8f4d6e", "#6d4464", "#503955", "#392b49"]
    assert any("under" in p for p in check_ramps.problems(bad))


def test_every_sea_is_darker_than_the_darkest_band_and_lighter_than_space(check_ramps):
    """The globe must stand off the page: sea above the ground's lightness,
    and below every band so the darkest band still reads as land."""
    space_l = check_ramps.srgb_to_oklab("#0a0b0d")[0]
    for key, r in check_ramps.ramps().items():
        sea_l = check_ramps.srgb_to_oklab(r["sea"])[0]
        darkest = check_ramps.srgb_to_oklab(r["c"][-1])[0]
        assert sea_l > space_l + 0.05, f"{key}: sea {sea_l:.2f} too close to space {space_l:.2f}"
        assert sea_l < darkest - 0.04, f"{key}: sea {sea_l:.2f} not darker than last band {darkest:.2f}"
