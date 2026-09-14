"""An ETOPS setting was asked for, and there is no honest switch to build.

Every flight on this map is a scheduled service, already operating under its
airline's extended-range approval. An ETOPS rule is therefore upstream of the
data rather than something the page could apply on top of it, and a toggle
would change no figure.

It is worse than useless, too. Searched rather than assumed, on 2026-09-14:

  dist/airports.json        fields are exactly iata, name, country, lat, lon, size
  sources/routes.py:267-322 builds ["src","dst"] IATA pairs; the airline
                            column of the source table is discarded
  scripts/adsb_extract.py   keeps (t, lat, lon, alt); the type code the
                            traces carry is discarded
  graph/air.py:52-59        taxi + climb/descent + 60*d/cruise_kmh + taxi,
                            affine in great-circle distance and unbounded
  grep -rE 'etops|overwater|diversion|range_km|twin|oceanic' src/  -> nothing

So there is no aircraft type, no engine count and no flown track anywhere in
this repository. A control would be a placebo, and CLAUDE.md's standing rule
is that the page must not claim a number changed when it did not.

This file is the guard on that decision. It fails if a control appears under
the ETOPS label WITHOUT the model having gained something for it to act on --
so the day the data really does carry aircraft types, the test says so and
gets deleted rather than standing in the way.
"""

from __future__ import annotations

import re
import subprocess

import pytest

from transport_maps import config

HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

#: What a real ETOPS implementation would have to read, as IDENTIFIERS. Prose
#: is excluded deliberately: build.py:21 uses the word "equipment" in a comment
#: about aircraft size, which is not a lever, and a test that fires on English
#: rather than on code is a test that gets muted.
LEVERS = (r"\betops\b|\bdiversion_|_diversion\b|engine_count|\bn_engines\b"
          r"|aircraft_type|\bequipment\s*[=:\[]")


def _settings_panel() -> str:
    start = HTML.index('<details class="panel" id="settings">')
    return HTML[start:HTML.index("</details>", start)]


def test_the_model_still_has_nothing_for_an_etops_rule_to_act_on():
    """The premise, re-checked on every run rather than trusted from a comment.

    Mutation performed and reverted: add `engine_count` to graph/air.py -> red,
    which is the correct outcome: the decision below would need revisiting.
    """
    found = subprocess.run(
        ["grep", "-rniE", LEVERS, str(config.ROOT / "src")],
        capture_output=True, text=True).stdout.splitlines()
    # Comment lines are prose, not a lever.
    hits = "\n".join(ln for ln in found
                     if not ln.split(":", 2)[-1].lstrip().startswith("#"))
    assert not hits, (
        "the model has gained something an ETOPS rule could act on:\n" + hits
        + "\n\nThe reasoning behind shipping a statement instead of a control "
          "no longer holds. Revisit it, then delete this test.")


def test_the_air_model_is_still_a_function_of_distance_alone():
    """`graph/air.py` prices every flight from the great-circle distance. A
    diversion constraint costs a LONGER TRACK, which this cannot express.
    """
    air = (config.ROOT / "src" / "transport_maps" / "graph" / "air.py").read_text()
    build = (config.ROOT / "src" / "transport_maps" / "graph" / "build.py").read_text()
    # air.py takes `distance_km`; build.py is where that distance is measured,
    # and it measures a great circle.
    assert "def block_time_min(distance_km" in air, (
        "the flight cost no longer takes a scalar distance; if it now takes a "
        "track, an ETOPS option may have become possible")
    call = build[build.index("air.block_time_min(") - 400:
                 build.index("air.block_time_min(")]
    assert "h3.great_circle_distance(" in call, (
        "the distance passed to the flight model is no longer a great circle")


def test_the_airports_table_carries_no_equipment():
    """`sources/airports.py` keeps scheduled_service airports and six fields.
    Inferring an 'adequate alternate' from `size` was measured and rejected:
    Lajes, Cold Bay, Goose Bay, Iqaluit, Kangerlussuaq, Kodiak, Wake and
    Ascension are all `medium`, and Midway and Shemya are absent entirely --
    structurally so, since the source keeps only scheduled service.
    """
    src = (config.ROOT / "src" / "transport_maps" / "sources" / "airports.py").read_text()
    assert "scheduled_service" in src
    assert not re.search(r"engine|aircraft|equipment", src, re.I)


def test_settings_answers_the_question_without_offering_a_switch():
    """The owner asked for this in Settings, so Settings says why there is
    nothing to set -- in the panel's existing label-plus-hint idiom, with the
    control deliberately absent.

    Mutation performed and reverted: add `<input type="checkbox" id="etops">`
    inside that group -> red.
    """
    panel = _settings_panel()
    assert "Long over-water flights" in panel, (
        "Settings does not answer the ETOPS question at all; the owner asked "
        "for it there")

    start = panel.index("Long over-water flights")
    group = panel[panel.rindex("<div", 0, start):]
    group = group[:group.index("</div>", group.index("</p>"))]

    assert "ETOPS" in group, "the group does not name what it is about"
    for control in ("<input", "<select", "<button", 'role="radiogroup"',
                    'role="switch"', 'type="checkbox"'):
        assert control not in group, (
            f"an ETOPS {control} appeared in Settings. It cannot change any "
            "figure this page computes -- see this file's docstring for the "
            "search that establishes it -- so it would be a placebo. If the "
            "model has genuinely gained a lever, the test above will have "
            "failed first and this one should be deleted with it.")


def test_no_javascript_is_wired_to_an_etops_setting():
    """A control could also be created from app.js. Nothing reads or writes
    such a setting, and nothing should until there is a model behind it.
    """
    for token in ("etops", "ETOPS"):
        for pattern in (f'$("{token}")', f'id="{token}"', f"'{token}'"):
            assert pattern not in APP, (
                f"app.js wires up {pattern}, which has nothing to act on")


def test_the_page_says_why_rather_than_only_that_it_makes_no_difference():
    """Cycle 10 had already established that scheduled routes comply. The
    useful half is the second admission -- that the model could not represent
    a difference if there were one -- and that is what must not be dropped in
    a later edit.
    """
    start = HTML.index('id="limits"')
    limits = HTML[start:HTML.index('id="credits"', start)]
    assert "Long over-water flights" in limits, (
        "the limits section no longer explains the ETOPS position")
    block = limits[limits.index("Long over-water flights"):]
    block = block[:block.index("</p>")]
    # The source is wrapped, so "scheduled\n service" is one phrase to a
    # reader and two tokens to a substring check.
    block = " ".join(block.split())
    assert "scheduled service" in block, "it does not say the routes comply"
    assert "no aircraft type" in block or "carries no aircraft type" in block, (
        "it does not admit the data has no aircraft type, which is the reason "
        "no rule could be applied even in principle")
    assert "great circle" in block or "great-circle" in block, (
        "it does not explain that the drawn track is a great circle, which is "
        "precisely what an ETOPS-limited flight does not fly")


@pytest.mark.parametrize("forbidden", [
    "text-transform:uppercase", "letter-spacing", "tabular-nums",
])
def test_the_new_copy_obeys_the_design_policy(forbidden):
    """CLAUDE.md's standing design rules, applied to the block just added."""
    panel = _settings_panel()
    assert forbidden not in panel.replace(" ", "")
