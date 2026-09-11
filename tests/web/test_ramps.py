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


def test_respace_writes_atomically(check_ramps):
    """--respace is the one writer in the repo that truncates a tracked source
    file in place. A crash part-way through leaves web/app.js truncated, and on
    the --page-only deploy path nothing would open the result before it ships.
    """
    src = (check_ramps.__file__ and open(check_ramps.__file__, encoding="utf-8").read())
    assert "atomic_write(APP" in src
    assert "APP.write_text(" not in src, "a bare write_text truncates before it writes"


# --- the ocean palette, chosen independently of the colour scheme ----------

def test_every_ocean_clears_the_sea_rules_against_every_scheme(check_ramps):
    """A scheme's own `sea` only has to work with that scheme's bands. An
    OCEAN is picked independently, so it has to work with all twelve at once:
    lighter than SPACE or the globe's edge vanishes into the page, darker than
    the darkest band of every scheme or that band stops reading as land, and
    at least MIN_GREY_DELTA_E from all 37 painted bands of every scheme or the
    sea reads as a band.

    Those three leave a lightness window of about 0.17 to 0.22 in OKLab, so
    what the palette varies is hue, not brightness. The worst margin of the
    five shipped is charcoal at 8.8 against the floor of 8.
    """
    space = check_ramps.constant("SPACE")
    schemes = check_ramps.ramps()
    found = check_ramps.oceans()
    assert len(found) == 5, f"parsed {len(found)} fixed oceans from app.js, expected 5"
    for key, sea in found.items():
        assert not check_ramps.ocean_problems(sea, space, schemes), \
            f"{key}: {check_ramps.ocean_problems(sea, space, schemes)}"


def test_the_default_ocean_follows_the_scheme_and_carries_no_colour(check_ramps):
    """The first entry must stay `sea: null`: it means "whatever the scheme
    says", which is the behaviour every build before this one had, and it is
    what keeps this setting additive rather than a redefinition."""
    src = (check_ramps.APP).read_text(encoding="utf-8")
    import re
    m = re.search(r"const OCEANS = \{(.*?)\n\};", src, re.S)
    assert m, "OCEANS not found"
    first = m.group(1).strip().splitlines()[0]
    assert first.lstrip().startswith("scheme:"), f"first ocean is {first!r}"
    assert "sea: null" in first, "the default ocean must carry no fixed colour"


def test_the_oceans_are_told_apart_from_each_other(check_ramps):
    """Five swatches a visitor chooses between; two that look identical are
    one choice wearing two names."""
    found = list(check_ramps.oceans().items())
    worst = min(
        (check_ramps.delta_e(check_ramps.srgb_to_oklab(a[1]),
                             check_ramps.srgb_to_oklab(b[1])), a[0], b[0])
        for i, a in enumerate(found) for b in found[i + 1:])
    assert worst[0] >= 3.0, f"{worst[1]} and {worst[2]} are only {worst[0]:.1f} apart"


def test_the_page_reads_the_sea_from_one_place(check_ramps):
    """The globe, the legend's "open water" key and the picker's own swatch
    must agree. Before the ocean setting they each derived it separately, and
    adding a second source of sea colour is exactly how they drift."""
    src = (check_ramps.APP).read_text(encoding="utf-8")
    assert "const seaNow = () =>" in src
    # The legend key and the globe both go through it.
    assert '$("sw-sea").style.background = seaNow();' in src
    assert src.count('RAMPS[rampName]?.sea ?? SEA') <= 2, (
        "more than the two deliberate uses (seaNow itself, and what "
        '"Match the scheme" shows in the picker) derive the sea directly')
