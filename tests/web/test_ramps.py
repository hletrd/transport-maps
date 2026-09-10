"""Every colour scheme shipped in web/app.js is measured, not eyeballed.

`check_ramps` is the scripts/check_ramps.py module, loaded by a conftest
fixture rather than by mutating sys.path for the whole session.
"""


def test_every_ramp_is_monotonic_and_separable(check_ramps):
    found = check_ramps.ramps()
    # `>= 6` tolerated losing half the schemes: app.js ships twelve, and a
    # parser that silently matched only the first six would have kept this
    # green while six schemes went unmeasured.
    assert len(found) == 12, f"RAMPS parsed {len(found)} schemes from app.js, expected 12"
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


def test_the_band_count_follows_the_emitter_not_a_literal(check_ramps, monkeypatch):
    """`expand()` and `scheme_problems()` hard-coded 37. The number of painted
    bands is one more than config.BAND_EDGES_MIN, and the moment an edge is
    added or removed a literal stops describing the legend the page draws --
    the gate would keep measuring 37 colours for a ramp that no longer has 37,
    and every guarantee in this file would be about the wrong colours.

    This test used to be unable to detect that. It asserted
    `N_BANDS == len(BAND_EDGES_MIN) + 1`, which reads 37 == 37 whether N_BANDS
    is derived or the literal it replaced; `len(expand(c)) == N_BANDS` compared
    N_BANDS with expand's own default, which WAS N_BANDS; and
    `len(expand(c, 11)) == 11` checked a literal the test passed in. Reverting
    the whole fix left all seven ramp tests green -- exactly the vacuity
    CLAUDE.md says to assume until shown otherwise. The fix that made it
    testable is in the source: a function read at call time, not a constant
    frozen at import into a default argument.
    """
    from transport_maps import config

    r = check_ramps.ramps()["muted"]
    real = len(config.BAND_EDGES_MIN) + 1
    assert check_ramps.n_bands() == real
    assert len(check_ramps.expand(r["c"])) == real

    # Move the ladder and the gate must follow it, with no argument passed.
    monkeypatch.setattr(config, "BAND_EDGES_MIN", tuple(range(10, 10 + 12)))
    assert check_ramps.n_bands() == 13, "the count is frozen at import, not read from the emitter"
    assert len(check_ramps.expand(r["c"])) == 13, "expand() kept its old default"
    assert len(check_ramps.expand(r["c"], 11)) == 11, "an explicit count must still win"
    # ...and the measurements built on it follow too, rather than silently
    # continuing to grade a 37-band ladder that no longer exists.
    assert check_ramps.scheme_problems(r, check_ramps.constant("SPACE")) == \
        check_ramps.scheme_problems(r, check_ramps.constant("SPACE"), 13)
