"""The Tohoku Shinkansen paragraph, pinned to the arithmetic it describes.

Both `web/index.html` and `web/llms.txt` tell a visitor why the model's largest
known error is its largest known error. Until cycle 16 both said the error had
"two causes, and neither is speed", and that "the per-stop allowance for the
other fifteen dominates the journey". Recomputed from `graph/rail.ride_edges`'s
own formula and `calibration.toml`'s own figures, that is false and backwards:

    edge_min = stop_overhead_min + 60 * chord_km * detour_factor / speed_kmh

    as priced, tier `default`   572.1 min running + 49.2 min allowance
                                = 621.3 min, of which running is 92.1%
    the fifteen extra calls     36.9 min, 5.9% of the journey
    tier corrected alone        removes 301.1 of the 431.3 min error, 69.8%
    stop count corrected alone  removes 36.9 min, 8.6%

Running time is the journey, the allowance is a twelfth of it, and the second
cause the paragraph named -- `highspeed` sitting on the way members rather than
on the route relation -- is precisely why the speed is wrong. `calibration.toml`
says as much two lines below the citation ("this model if it were tiered
high_speed 5.3 h") and the paragraph misread it.

This file exists so that the next person to retune `[rail.tiers]` is told the
copy has gone stale rather than left to find out from a reader. Nothing here
asserts a number this file chose: every figure is recomputed from
`load_rail_calibration()` and from the Tohoku relation's shape as
`calibration.toml`'s own `[rail]` header records it, and every sentence that
header is read from is anchored by a regex that fails loudly if the header is
rewritten. A guard that silently stops checking is the failure mode this
repository has shipped before.

MUTATIONS PERFORMED, with the results as measured -- not as estimated. Seven
tests collect from this file. Each mutation was made by editing the prose and
undone by editing it back, never by checkout.

1. `web/index.html`: "take about 5 hours off, 70% of the error" -> "40% of the
   error". **1 failed, 6 passed.** `test_the_two_shares_are_the_arithmetic_s`
   reported `web/index.html prints 40% as the share of the error the tier
   correction removes; calibration.toml's own figures give 69.2-69.8%`.

2. `web/llms.txt`: "is 37 minutes, 9% of the error" -> "30% of the error".
   **1 failed, 6 passed.** The same test, naming `web/llms.txt` and
   `8.5-8.6%`. The two files are ranged separately, so a correction applied to
   only one of them is caught.

3. `web/index.html`: "priced at the default, 82 km/h" -> "75 km/h" -- the
   pre-tier speed, i.e. the edit someone making the page agree with an older
   build would make. **1 failed, 6 passed.**
   `test_both_files_price_the_shinkansen_at_the_default_tier` reported
   `web/index.html says the Shinkansen relations are priced at 75 km/h;
   calibration.toml's [rail.tiers.default] is 81.8 km/h`.

4. `web/index.html`: restore the whole pre-cycle-16 paragraph, retracted claim
   and all. **6 failed, 1 passed** -- every test but
   `test_both_files_quote_the_relation_s_own_call_count`, which the old
   paragraph also satisfied because 21, six and fifteen were the only figures
   it got right. The first failure names the phrase:
   `web/index.html still carries the retracted claim 'neither is speed';
   running time is 92% of the journey as priced`.

5. `web/index.html`: "returns about 10 hours" -> "about 8 hours".
   **1 failed, 6 passed**, in
   `test_the_journey_hours_the_prose_prints_are_the_computed_ones`.

6. `web/llms.txt`: "the other fifteen is 37 minutes" -> "the others is 37
   minutes". **1 failed, 6 passed**, in
   `test_both_files_quote_the_relation_s_own_call_count`.

7. Vacuity check on the guards themselves. `calibration.toml` is outside this
   task's file set, so rather than edit it the module was imported with
   `config.ROOT` pointed at a scratch tree holding a copy whose anchor
   `"published Tokyo -> Shin-Aomori"` reads `"published Tokyo to
   Shin-Aomori"`. `_anchor` raised at import, so **all seven tests error at
   collection** with `calibration.toml no longer carries the sentence this
   guard reads for the published journey time ...; the rail copy in
   web/index.html and web/llms.txt is now unchecked against it` -- rather than
   passing on a stale default.

Every one of the seven tests is reddened by at least one mutation above.
No mutation came back green.
"""

from __future__ import annotations

import re

from transport_maps import config
from transport_maps.graph.rail import load_rail_calibration

CAL_PATH = config.ROOT / "calibration.toml"
CAL_TEXT = CAL_PATH.read_text(encoding="utf-8")
HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
LLMS = (config.ROOT / "web" / "llms.txt").read_text(encoding="utf-8")

CAL = load_rail_calibration(CAL_PATH)

_WORDS = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20}


def _flat(text: str) -> str:
    return " ".join(text.split())


# ---- the Tohoku figures, read out of calibration.toml rather than retyped ----
#
# `[rail]`'s header is where this journey is documented, and it is a comment
# block, so tomllib cannot see it. Stripping the leading `#` and collapsing the
# wrapping is what makes its sentences greppable; the wrapping is why a regex
# written against the raw file matches "21 stops, 650 km of chord" and misses
# "runs it in 3 h 10 calls at / about six", which straddles two lines.

CAL_PROSE = _flat(re.sub(r"(?m)^#\s?", "", CAL_TEXT))


def _anchor(pattern: str, what: str) -> re.Match[str]:
    """A sentence of `calibration.toml`'s `[rail]` header, or a loud failure.

    Every figure below is parsed, not retyped, so a rewrite of that header
    must not leave this file quietly checking nothing.
    """
    m = re.search(pattern, CAL_PROSE)
    assert m is not None, (
        f"calibration.toml no longer carries the sentence this guard reads "
        f"for {what} (pattern {pattern!r}); the rail copy in web/index.html "
        "and web/llms.txt is now unchecked against it")
    return m


_shape = _anchor(
    r"Relation \d+[^:]*: (\d+) stops, ([\d,]+) km of chord, (\d+) legs",
    "the Tohoku relation's shape")
STOPS = int(_shape.group(1))
CHORD_KM = float(_shape.group(2).replace(",", ""))
LEGS = int(_shape.group(3))

_fast = _anchor(
    r"lists (\d+) calls; the Hayabusa that runs it in (\d+) h (\d+) calls "
    r"at about (\w+)\.",
    "the fastest train's calls and journey time")
FAST_CALLS = _WORDS[_fast.group(4)]
# Two published figures for the same journey live in that header: "3 h 10" in
# the sentence above and "~3.1 h" in the table. They differ by four minutes,
# which moves the shares below by less than a point, so both ends are carried
# and the page is checked against the range rather than against a coin toss.
PUBLISHED_MIN = (
    float(_anchor(r"published Tokyo -> Shin-Aomori ~([\d.]+) h",
                  "the published journey time")
          .group(1)) * 60.0,
    int(_fast.group(2)) * 60.0 + int(_fast.group(3)),
)

AS_PRICED_H = float(
    _anchor(r"this model, tier `default` \([\d.]+\) ([\d.]+) h",
            "the journey as priced").group(1))
IF_TIERED_H = float(
    _anchor(r"this model if it were tiered high_speed ([\d.]+) h",
            "the journey if it were tiered high_speed").group(1))


def _journey_min(tier: str, legs: int) -> float:
    """`ride_edges`'s own formula, summed over a whole journey."""
    t = CAL.tiers[tier]
    return legs * t.stop_overhead_min + 60.0 * CHORD_KM * CAL.detour_factor / t.speed_kmh


PRICED = _journey_min("default", LEGS)
TIER_FIXED = _journey_min("high_speed", LEGS)
STOPS_FIXED = _journey_min("default", FAST_CALLS - 1)
BOTH_FIXED = _journey_min("high_speed", FAST_CALLS - 1)

#: Share of the error each single correction removes, as a (low, high) band
#: over the two published figures the header gives.
def _share_band(corrected: float) -> tuple[float, float]:
    shares = sorted(100.0 * (PRICED - corrected) / (PRICED - p) for p in PUBLISHED_MIN)
    return shares[0], shares[-1]


TIER_SHARE = _share_band(TIER_FIXED)
STOP_SHARE = _share_band(STOPS_FIXED)


# ---- the two surfaces the claim is shipped on ------------------------------

def _page_rail_paragraph() -> str:
    """The `<p><b>Rail.</b> ... </p>` block, tags and entities out.

    Sliced rather than searched whole-file so that a figure printed somewhere
    else on the page -- the air paragraph carries its own percentages -- cannot
    satisfy a guard about the rail one.
    """
    body = re.sub(r"<!--.*?-->", " ", HTML, flags=re.S)
    m = re.search(r"<p><b>Rail\.</b>(.*?)</p>", body, flags=re.S)
    assert m is not None, "web/index.html has no <p><b>Rail.</b> paragraph"
    text = re.sub(r"<[^>]+>", " ", m.group(1))
    return _flat(text.replace("&rsquo;", "'").replace("&mdash;", "--")
                     .replace("&ndash;", "-").replace("&nbsp;", " "))


def _llms_rail_section() -> str:
    m = re.search(r"## What the numbers mean(.*?)\n## ", LLMS, flags=re.S)
    assert m is not None, "web/llms.txt has no 'What the numbers mean' section"
    body = m.group(1)
    assert "Shinkansen" in body, (
        "web/llms.txt's 'What the numbers mean' section no longer discusses the "
        "Shinkansen; this guard would check nothing")
    return _flat(body)


SURFACES = {"index.html": _page_rail_paragraph(), "llms.txt": _llms_rail_section()}


# ---- what the two surfaces must not say ------------------------------------

#: The retracted claims, in the spellings the two files shipped them in and in
#: the near spellings a partial revert would produce.
_RETRACTED = (
    r"neither is speed",
    r"speed is not (?:the|a) cause",
    r"allowance for the other \w+ dominates",
    r"per-stop allowance .{0,40}dominates",
)


def test_neither_file_still_says_speed_is_not_the_cause():
    """Running time is 92% of the journey as priced, so it cannot be true that
    speed is not a cause of the journey being too long.

    Mutation: restore "Two causes, and neither is speed" in web/index.html
    -> red, naming the phrase.
    """
    run = 60.0 * CHORD_KM * CAL.detour_factor / CAL.tiers["default"].speed_kmh
    assert run / PRICED > 0.5, (
        "running time is no longer the majority of the Tohoku journey as priced "
        f"({run:.0f} of {PRICED:.0f} min); the paragraph this guard pins was "
        "rewritten on the premise that it is")
    for name, text in SURFACES.items():
        for pat in _RETRACTED:
            assert not re.search(pat, text, re.I), (
                f"web/{name} still carries the retracted claim {pat!r}; running "
                f"time is {100 * run / PRICED:.0f}% of the journey as priced")


def test_both_files_name_the_missing_service_tag_as_the_dominant_cause():
    """The dominant cause is that all three relations carry no `service` tag,
    so all three price at the default tier.

    Mutation: restore the pre-cycle-16 sentence in web/index.html -> red.
    """
    for name, text in SURFACES.items():
        assert re.search(r"all three .{0,60}relations", text, re.I), (
            f"web/{name} does not say that ALL THREE Shinkansen relations are "
            "affected, which is what calibration.toml measured")
        assert re.search(r"no\s+`?<?code>?service", text, re.I) or \
               re.search(r"carry no .{0,20}service", text, re.I), (
            f"web/{name} no longer names the missing `service` tag as the reason "
            "the relations fall to the default tier")


# ---- what the two surfaces must say, to the figure --------------------------

def _number_before(text: str, unit: str, near: str) -> float | None:
    """The number given `unit` in the clause containing `near`."""
    for sentence in re.split(r"(?<=[.;:]) ", text):
        if near in sentence:
            m = re.search(rf"([\d.]+)\s*{unit}", sentence)
            if m:
                return float(m.group(1))
    return None


def test_both_files_price_the_shinkansen_at_the_default_tier():
    """The speed the prose prints beside "the default" is `[rail.tiers.default]`.

    Mutation: change index.html's "82 km/h" to "75 km/h", the pre-tier speed
    -> red, naming both figures.
    """
    want = round(CAL.tiers["default"].speed_kmh)
    for name, text in SURFACES.items():
        got = _number_before(text, "km/h", "the default")
        assert got is not None, (
            f"web/{name} no longer prints the speed the Shinkansen relations are "
            "priced at, so a retune of [rail.tiers.default] would go unnoticed")
        assert round(got) == want, (
            f"web/{name} says the Shinkansen relations are priced at {got:g} km/h; "
            f"calibration.toml's [rail.tiers.default] is "
            f"{CAL.tiers['default'].speed_kmh} km/h")


def test_the_two_shares_are_the_arithmetic_s():
    """The two shares the paragraph gives are the ones the model's own formula
    produces from calibration.toml's constants.

    Mutation: index.html "70% of the error" -> "40%" -> red; llms.txt
    "9% of the error" -> "30%" -> red. The files are checked separately.
    """
    for name, text in SURFACES.items():
        shares = [float(s) for s in re.findall(r"(\d+)% of the error", text)]
        assert len(shares) == 2, (
            f"web/{name} gives {len(shares)} shares of the Tohoku error, not the "
            "two this paragraph is required to give (the tier correction and the "
            "stop-count correction)")
        tier, stop = shares
        lo, hi = TIER_SHARE
        assert lo - 1.0 <= tier <= hi + 1.0, (
            f"web/{name} prints {tier:g}% as the share of the error the tier "
            f"correction removes; calibration.toml's own figures give "
            f"{lo:.1f}-{hi:.1f}%")
        lo, hi = STOP_SHARE
        assert lo - 1.0 <= stop <= hi + 1.0, (
            f"web/{name} prints {stop:g}% as the share of the error the stop-count "
            f"correction removes; calibration.toml's own figures give "
            f"{lo:.1f}-{hi:.1f}%")
        assert tier > stop, (
            f"web/{name} prints the stop-count share at least as large as the tier "
            "share, which reverses the finding this paragraph exists to state")


def test_the_per_stop_allowance_is_the_minutes_the_calibration_gives():
    """"37 minutes" is `stop_overhead_min` times the calls the express skips."""
    extra_calls = STOPS - FAST_CALLS
    want = extra_calls * CAL.tiers["default"].stop_overhead_min
    for name, text in SURFACES.items():
        got = _number_before(text, "min(?:ute)?s?", "the other")
        assert got is not None, (
            f"web/{name} no longer prints the per-stop allowance in minutes")
        assert abs(got - want) <= 1.0, (
            f"web/{name} prints {got:g} minutes of per-stop allowance for the "
            f"{extra_calls} skipped calls; {extra_calls} x "
            f"{CAL.tiers['default'].stop_overhead_min} min is {want:.1f}")


def test_the_journey_hours_the_prose_prints_are_the_computed_ones():
    """Three durations appear in the paragraph -- the journey as priced, the
    saving the tier correction makes, and where both corrections land. Each is
    recomputed, and the first two are cross-checked against the hours
    calibration.toml prints for the same journey.

    Mutation: change "about 10 hours" to "about 8 hours" -> red.
    """
    assert abs(PRICED / 60.0 - AS_PRICED_H) < 0.1, (
        f"the formula gives {PRICED / 60:.2f} h for the Tohoku journey as priced "
        f"and calibration.toml's own table prints {AS_PRICED_H} h; the two have "
        "drifted apart and the page cannot agree with both")
    assert abs(TIER_FIXED / 60.0 - IF_TIERED_H) < 0.1, (
        f"the formula gives {TIER_FIXED / 60:.2f} h for the journey tiered "
        f"high_speed and calibration.toml prints {IF_TIERED_H} h")
    for name, text in SURFACES.items():
        for near, want, what in (
            ("largest", PRICED / 60.0, "the journey as priced"),
            ("take about", (PRICED - TIER_FIXED) / 60.0,
             "the saving the tier correction makes"),
            ("Corrected both ways", BOTH_FIXED / 60.0,
             "where both corrections land"),
        ):
            got = _number_before(text, "h(?:ours?)?\\b", near)
            assert got is not None, (
                f"web/{name} no longer prints {what} in hours")
            assert abs(got - want) <= 0.5, (
                f"web/{name} prints {got:g} h for {what}; the formula over "
                f"calibration.toml's constants gives {want:.2f} h")


def test_both_files_quote_the_relation_s_own_call_count():
    """21 calls, about six on the express, fifteen skipped -- as measured."""
    assert STOPS - FAST_CALLS == 15, (
        f"calibration.toml now records {STOPS} calls against {FAST_CALLS} on the "
        "express; the page's 'the other fifteen' is stale")
    for name, text in SURFACES.items():
        assert re.search(rf"\b{STOPS} station calls\b", text), (
            f"web/{name} no longer says the relation lists {STOPS} station calls")
        assert re.search(r"about six\b", text), (
            f"web/{name} no longer says the fastest train makes about six calls")
        assert re.search(r"the other fifteen\b", text), (
            f"web/{name} no longer names the fifteen calls the express skips")
