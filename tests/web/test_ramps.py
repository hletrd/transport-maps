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
    """The globe must stand off the page: sea above SPACE (the ground behind
    the globe, not the page background), and below every band so the darkest
    band still reads as land. Measured by the script itself, as the README
    and CLAUDE.md say it is."""
    space = check_ramps.constant("SPACE")
    for key, r in check_ramps.ramps().items():
        assert not [p for p in check_ramps.scheme_problems(r, space) if "sea" in p], \
            f"{key}: {check_ramps.scheme_problems(r, space)}"


def test_every_schemes_grey_is_separable_from_all_37_bands(check_ramps):
    """One shared grey sat 0.9 from a Mono band and 6.1 from a Muted one; the
    legend entry for 'no scheduled route' is only useful if the swatch is
    visibly not a band."""
    space = check_ramps.constant("SPACE")
    for key, r in check_ramps.ramps().items():
        bands = check_ramps.expand(r["c"])
        d = min(check_ramps.delta_e(check_ramps.srgb_to_oklab(r["grey"]), b) for b in bands)
        assert d >= check_ramps.MIN_GREY_DELTA_E, f"{key}: grey {r['grey']} is {d:.1f} from a band"
        assert not [p for p in check_ramps.scheme_problems(r, space) if "grey" in p]


def test_a_grey_that_matches_a_band_is_caught(check_ramps):
    r = dict(check_ramps.ramps()["mono"])
    r["grey"] = "#4a4d50"                      # the old shared grey, 0.9 from band 28
    assert any("grey" in p for p in check_ramps.scheme_problems(r, check_ramps.constant("SPACE")))
