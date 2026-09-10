"""The page re-types a handful of the pipeline's constants; keep them equal.

The channel order of .modes.bin, the two uint16 sentinels, the unreachable
band id, the tile layer name and the airports.json column order are read by
app.js as literals (or as fallbacks when index.json predates the field). A
change on one side that the other does not follow is a wrong route panel with
no error, so the literals are pinned to the emitters here.
"""

import re

from transport_maps import config
from transport_maps.contour import bands
from transport_maps.emit import (
    airports_json,
    index,
    itinerary,
    modes,
    rail_detail,
    tiles,
)

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _js_list(name: str) -> list[str]:
    m = re.search(rf'{name}\s*=\s*meta\.\w+\s*\?\?\s*\[([^\]]*)\]', APP) or re.search(rf'const {name}\s*=\s*\[([^\]]*)\]', APP)
    assert m, f"{name} not found in app.js"
    return re.findall(r'"([^"]+)"', m.group(1))


def _js_const(name: str) -> str:
    m = re.search(rf'const {name}\s*=\s*([^;]+);', APP)
    assert m, f"{name} not found in app.js"
    return m.group(1).strip()


def test_mode_channel_fallback_matches_the_emitter():
    assert _js_list("MODE_NAMES") == list(modes.CHANNELS)


def test_sentinels_match_the_emitters():
    assert int(_js_const("NO_AIRPORT"), 16) == itinerary.NO_AIRPORT
    assert int(_js_const("NO_RAIL"), 16) == rail_detail.NO_RAIL
    assert int(_js_const("UNREACHABLE_BAND")) == bands.UNREACHABLE_BAND


def test_the_page_reads_the_tile_layer_the_emitter_writes():
    assert f'"source-layer": "{tiles.LAYER}"' in APP


def test_airports_json_column_order_matches_the_reads():
    """app.js reads a[0]=code, a[1]=name, a[2]=country, a[3]=lat, a[4]=lon."""
    fields = airports_json.FIELDS
    assert fields[:5] == ("iata", "name", "country", "lat", "lon"), fields


def test_every_index_json_key_the_page_reads_is_written(tmp_path):
    import json

    out = tmp_path / "index.json"
    index.write_index([{"slug": "s", "name": "S", "lat": 0.0, "lon": 0.0}], out,
                      hover_cell_count=1, graph={"rail": True, "ferry": True}, identity=index.build_identity())
    written = set(json.loads(out.read_text()))
    read = set(re.findall(r"meta\.(\w+)", APP))
    assert read <= written, f"app.js reads {sorted(read - written)} which write_index never writes"


def _tick_rule(targets, edges, hour_bonus=0.6):
    """paintScale's selection, ported: snap each target to the nearest edge by
    log distance, an exact hour winning when it is nearly as close."""
    import math

    picked = []
    for t in targets:
        best, best_err = -1, math.inf
        for i, e in enumerate(edges):
            err = abs(math.log(e / t)) * (hour_bonus if e % 60 == 0 else 1.0)
            if err < best_err:
                best, best_err = i, err
        picked.append(edges[best])
    return picked


def test_the_legend_tick_rule_lands_on_true_band_edges():
    """Every tick is a real band boundary -- the CLAUDE.md legend rule. The
    on-screen gap rule is measured in the browser (browser_verify.sh)."""
    m = re.search(r"const TICK_TARGETS_MIN = \[([^\]]+)\];", APP)
    targets = [int(x) for x in m.group(1).split(",")]
    edges = list(config.BAND_EDGES_MIN)
    picked = _tick_rule(targets, edges)
    assert picked == [60, 300, 1470, 4320]
    assert picked == sorted(set(picked)), "ticks must be distinct and ascending"
    assert picked[0] == min(e for e in edges if e >= targets[0])


def test_the_hour_bonus_is_a_rule_the_port_implements_not_a_constant_it_ignores():
    """The shipped ladder is blind to the hour bonus.

    On config.BAND_EDGES_MIN every target either IS an edge or has one so much
    closer than any hour edge that the factor never decides: 0.6, 1.0, 0.2 and
    0.9 all yield [60, 300, 1470, 4320], so a port that dropped `* 0.6`
    entirely would keep this file green while the page changed. Exercise the
    branch on a ladder where it decides, so the port is pinned to the rule and
    not to one outcome.
    """
    edges, targets = [114, 120], [100]
    assert _tick_rule(targets, edges, hour_bonus=0.6) == [120], "the hour edge wins with the bonus"
    assert _tick_rule(targets, edges, hour_bonus=1.0) == [114], "and loses without it"
    # And the factor the page actually ships is the one tested above.
    assert re.search(r"err \*= 0\.6;", APP), "app.js no longer applies the hour bonus"
