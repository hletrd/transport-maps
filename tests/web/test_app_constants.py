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


def test_the_legend_tick_rule_lands_on_true_band_edges():
    """A Python port of paintScale's selection: each target snaps to the
    nearest edge by log distance, an exact hour winning when nearly as close,
    so every tick is a real band boundary (the CLAUDE.md legend rule); the
    on-screen gap rule is measured in the browser (browser_verify.sh)."""
    import math

    m = re.search(r"const TICK_TARGETS_MIN = \[([^\]]+)\];", APP)
    targets = [int(x) for x in m.group(1).split(",")]
    edges = list(config.BAND_EDGES_MIN)
    picked = []
    for t in targets:
        best, best_err = -1, math.inf
        for i, e in enumerate(edges):
            err = abs(math.log(e / t)) * (0.6 if e % 60 == 0 else 1.0)
            if err < best_err:
                best, best_err = i, err
        picked.append(edges[best])
    assert picked == [60, 300, 1470, 4320]
    assert all(v in edges for v in picked)
