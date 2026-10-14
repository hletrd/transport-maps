"""The rail paragraph, pinned to the calibration it describes.

Both `web/index.html` and `web/llms.txt` tell a visitor how a train is priced.
Every figure they print is read from `calibration.toml` here, so the next
refit that moves a constant turns this red rather than leaving the copy stale.
Until rebuild 30 this file pinned a paragraph about the Tohoku Shinkansen
priced at the default tier's 82 km/h; the track now promotes it, and that
paragraph's claims are retracted below so they cannot drift back.

Mutations performed and reverted, each RED: `221 km/h` -> `215 km/h` in
index.html; `88%` -> `90%` in llms.txt; `track_speed_factor` 0.881 -> 0.85 in
calibration.toml.
"""

import re

import pytest

from transport_maps import config
from transport_maps.graph.rail import load_rail_calibration

CAL = load_rail_calibration(config.ROOT / "calibration.toml")
HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
LLMS = (config.ROOT / "web" / "llms.txt").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text)).replace("&rsquo;", "'")


def _rail(text: str) -> str:
    flat = _flat(text)
    i = flat.index("Running time comes from one of six service tiers")
    return flat[i:i + 2000]


SURFACES = {"index.html": _rail(HTML), "llms.txt": _rail(LLMS)}


@pytest.mark.parametrize("name", SURFACES)
def test_the_tier_speeds_printed_are_the_fitted_ones(name):
    text = SURFACES[name]
    for tier, phrase in (("commuter", "for a commuter service"),
                         ("high_speed", "for a high-speed one"),
                         ("tourism", "tier for heritage")):
        want = round(CAL.tiers[tier].speed_kmh)
        m = re.search(r"(\d+) km/h " + re.escape(phrase), text)
        assert m, f"{name}: no speed before '{phrase}'"
        assert int(m.group(1)) == want, (
            f"{name} prints {m.group(1)} km/h {phrase}; calibration.toml says {want}")


@pytest.mark.parametrize("name", SURFACES)
def test_the_line_speed_shares_printed_are_the_fitted_ones(name):
    text = SURFACES[name]
    m = re.search(r"about (\d+) to (\d+)% of it", text)
    assert m, f"{name}: the line-speed share is not stated"
    factors = [t.line_speed_factor for t in CAL.tiers.values() if t.line_speed_factor]
    assert (int(m.group(1)), int(m.group(2))) == (round(100 * min(factors)),
                                                  round(100 * max(factors)))
    m = re.search(r"and (\d+)% of its speed limit", text)
    assert m and int(m.group(1)) == round(100 * CAL.track_speed_factor), (
        f"{name}: the track network's share is not calibration.toml's "
        f"{CAL.track_speed_factor:.3f}")


@pytest.mark.parametrize("name", SURFACES)
def test_the_retracted_shinkansen_claims_stay_retracted(name):
    text = SURFACES[name]
    for claim in ("priced at the default, 82 km/h", "about 10 hours against", "70% of the error"):
        assert claim not in text, f"{name} still says '{claim}'"
