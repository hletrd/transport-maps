"""The legend's ticks, RUN rather than re-implemented.

`test_the_legend_tick_rule_lands_on_true_band_edges` ports `paintScale`'s
SELECTION into Python, so it pins which edges are chosen and nothing
`paintScale` does afterwards. Proven by mutation in the cycle-8 review:
changing `((i + 1) / N_BANDS)` to `(i / N_BANDS)` -- which moves every tick one
whole band-width off its true boundary, against CLAUDE.md's standing legend
rule -- left all 153 `tests/web` tests green, and so did
`fmtTick(EDGES[i] * 2)`, which doubles every printed number.

`paintScale` and `paintDetail` touch only a handful of DOM setters and a child
list, so they are sliced out of `app.js` by brace matching and run under Node
against a shim -- the approach `test_boot_behaviour.py` and
`test_route_geometry.py` already established for this file. An earlier draft of
this file re-implemented their positioning arithmetic in the probe and stayed
green on exactly the mutation it was written to catch, which is why they are
now executed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
EDGES = list(config.BAND_EDGES_MIN)
N_BANDS = len(EDGES) + 1


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    prefix = APP.rfind("async ", max(0, start - 6), start)
    if prefix != -1:
        start = prefix
    i = APP.index("{", start)
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError(f"function {name} is not brace-balanced")


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the page functions cannot be run")
    return exe


def _run(node: str, tmp_path, body: str, name="probe.mjs") -> dict:
    script = tmp_path / name
    script.write_text(body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# A minimal DOM: enough to RUN paintScale and paintDetail, which is the whole
# point. An earlier draft of this file re-implemented their positioning
# arithmetic in the probe, and so stayed green when the real call sites were
# mutated -- the exact flaw it was written to fix. Deliberately not jsdom: a
# dependency for six setters and a child list.
_DOM = """
class El {
  constructor(tag){ this.tagName=tag; this.style={}; this.dataset={};
    this.textContent=""; this.title=""; this.hidden=false;
    this.children=[]; this._classes=new Set(); this._in=false; }
  get classList(){ const s=this._classes;
    return { add:(c)=>s.add(c), contains:(c)=>s.has(c) }; }
  replaceChildren(...kids){ for (const c of this.children) c._in=false;
    this.children = kids; for (const c of kids) c._in=true; }
  append(...kids){ this.children.push(...kids); for (const c of kids) c._in=true; }
  // A real flag, not a constant `true`: markSpan re-appends its bracket only
  // when paintLegend has detached it, and a shim that always claims to be
  // connected never exercises that branch.
  get isConnected(){ return this._in; }
}
globalThis.document = { createElement: (t) => new El(t) };
const _els = {};
const $ = (id) => (_els[id] ||= new El("div"));
function prune(){ /* measured in a browser; nothing to measure here */ }
const dump = (el) => el.children.map((c) => ({
  left: c.style.left, width: c.style.width, text: c.textContent,
  min: c.dataset.min, cls: [...c._classes].sort(), bg: c.style.background }));
"""


# ---- the legend ------------------------------------------------------------

def test_every_tick_the_page_builds_sits_on_its_own_true_band_boundary(node, tmp_path):
    """RUN, not ported. `tickEl(i, at)` is the one place a tick's position and
    its label are decided, and both must come from the same edge index.

    CLAUDE.md: "its ticks sit at their true band boundaries -- the bands are
    equal width but the time scale is not, so evenly spaced labels would
    misstate the scale."

    Mutation performed and reverted: `(i + 1) / N_BANDS` -> `i / N_BANDS` at
    the world-scale call site -> red here. Mutation: `fmtTick(EDGES[i])` ->
    `fmtTick(EDGES[i] * 2)` -> red here. Both left the whole of tests/web green
    before this file existed.
    """
    probe = f"""
{_DOM}
const EDGES = {json.dumps(EDGES)};
const N_BANDS = EDGES.length + 1;
const TICK_TARGETS_MIN = {re.search(r"const TICK_TARGETS_MIN = (\[[^\]]+\]);", APP).group(1)};
{_function("fmtTick")}
{_function("tickEl")}
{_function("worldTicks")}
{_function("paintScale")}
paintScale();
console.log(JSON.stringify({{ ticks: dump($("scale")) }}));
"""
    ticks = _run(node, tmp_path, probe)["ticks"]
    assert ticks, "the legend built no ticks at all"
    # Every tick's POSITION must be the boundary the tick's own label names.
    # Derived from `min`, which is the edge the page itself recorded, so this
    # cannot be satisfied by the two happening to move together.
    for t in ticks:
        edge = int(t["min"])
        i = EDGES.index(edge)
        want = ((i + 1) / N_BANDS) * 100
        assert float(t["left"].rstrip("%")) == pytest.approx(want), (
            f"the tick labelled {t['text']!r} (edge {edge}) sits at {t['left']}, "
            f"not at that edge's own boundary {want}%")
        assert str(edge // 60 if edge >= 60 else edge) in t["text"]
        assert ("last" in t["cls"]) == (i == len(EDGES) - 1)
    # The ceiling is always drawn, and it is the only tick that carries "+".
    plus = [t for t in ticks if t["text"].endswith("+")]
    assert len(plus) == 1 and int(plus[0]["min"]) == EDGES[-1], (
        "the '72 h+' ceiling is missing or is not the last edge")


def test_the_detail_row_only_ever_names_edges_inside_the_view(node, tmp_path):
    """The zoom detail expands the bands on screen, and paintDetail is RUN, not
    ported. Every tick it draws must still be a real boundary, and one of the
    boundaries of the bands actually in view -- otherwise the finer legend
    would label times the map is not showing, which is the defect it exists to
    fix.

    Mutation performed and reverted: position a detail tick at `k / m` instead
    of `(k + 1) / m` -> red. A first draft of this test re-implemented the
    selection loop in the probe and stayed green on exactly that mutation,
    which is the flaw this whole file was written to correct.
    """
    cases = [(0, 3), (4, 9), (10, 12), (2, 2), (0, 0), (30, 36), (5, 25)]
    probe = f"""
{_DOM}
const EDGES = {json.dumps(EDGES)};
const N_BANDS = EDGES.length + 1;
const BANDS = Array.from({{ length: N_BANDS }}, (_, i) => "#" + String(i).padStart(6, "0"));
{re.search(r"const DETAIL_TICKS = \d+;", APP).group(0)}
let bandSpan = null;
{_function("fmtTick")}
{_function("tickEl")}
{_function("markSpan")}
{_function("paintDetail")}
const runs = [];
for (const [lo, hi] of {json.dumps(cases)}) {{
  paintDetail({{ lo, hi }});
  runs.push({{ lo, hi, ticks: dump($("detail-scale")),
               swatches: dump($("detail-tints")).map((c) => c.bg),
               cap: $("detail-cap").textContent,
               hidden: $("detail").hidden,
               bracket: dump($("tints"))[0] || null }});
}}
console.log(JSON.stringify({{ runs }}));
"""
    for run in _run(node, tmp_path, probe)["runs"]:
        lo, hi, ticks = run["lo"], run["hi"], run["ticks"]
        m = hi - lo + 1
        # One swatch per band in view, in the SAME colours the globe is painted
        # with -- the detail row is a key, and a key in the wrong colours is
        # worse than none. The probe's BANDS is "#000000", "#000001", ... so
        # the index each swatch took is readable straight off the value.
        assert len(run["swatches"]) == m, f"bands {lo}..{hi}: {len(run['swatches'])} swatches"
        assert run["swatches"] == [f"#{lo + k:06d}" for k in range(m)], (
            f"bands {lo}..{hi} are drawn in the colours of bands "
            f"{[int(c[1:]) for c in run['swatches']]}")
        assert run["hidden"] is False, "paintDetail left the row hidden"
        assert ticks, f"no ticks for bands {lo}..{hi}"
        for t in ticks:
            edge = int(t["min"])
            i = EDGES.index(edge)
            # A REAL edge, and one that bounds a band in view: band lo's lower
            # boundary is EDGES[lo-1], band hi's upper boundary is EDGES[hi].
            assert lo - 1 <= i <= hi, (
                f"bands {lo}..{hi} are in view but a tick names edge index {i}, "
                "outside them")
            # ...drawn at that edge's own position on THIS row, which spans the
            # m bands lo..hi rather than the whole ladder.
            at = 0.0 if i == lo - 1 else (i - lo + 1) / m
            # Compared as a number: JavaScript prints 25 where Python prints
            # 25.0, and the test is about the position, not the formatting.
            assert float(t["left"].rstrip("%")) == pytest.approx(at * 100), (
                f"the tick labelled {t['text']!r} sits at {t['left']}, not at "
                f"its own boundary {at * 100}%")
            assert 0 <= at <= 1
        positions = [float(t["left"].rstrip("%")) for t in ticks]
        assert positions == sorted(positions)
        # Band `lo` has a lower boundary of its own unless it is band 0, and
        # that boundary is the left end of this row. Without it the row's
        # leading edge is unlabelled and a reader cannot tell where it starts.
        leading = [t for t in ticks if float(t["left"].rstrip("%")) == 0.0]
        if lo > 0:
            assert len(leading) == 1 and int(leading[0]["min"]) == EDGES[lo - 1], (
                f"bands {lo}..{hi}: the row's left end is not labelled with its "
                f"own boundary {EDGES[lo - 1]}")
            assert "first" in leading[0]["cls"], (
                "the leading tick is centre-anchored and overhangs the strip")
        else:
            assert not leading, "band 0 has no lower boundary to label"
        assert len(ticks) <= int(re.search(r"const DETAIL_TICKS = (\d+);", APP).group(1)) + 1
        # The caption names both ends of the view in true band-edge values.
        assert "Most of this view:" in run["cap"] and "door to door" in run["cap"]
        # ...and the bracket on the main strip covers exactly those bands.
        b = run["bracket"]
        assert float(b["left"].rstrip("%")) == pytest.approx(100 * lo / N_BANDS)
        assert float(b["width"].rstrip("%")) == pytest.approx(100 * m / N_BANDS)


def test_the_detail_row_is_an_addition_and_never_replaces_the_legend():
    """CLAUDE.md: "The legend is always visible", never folded into a panel,
    and the folded phone sheet keeps its keys and caption. The zoom detail is
    an extra row, so none of that may move."""
    html = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    legend = html[html.index('<div class="legend">'):]
    legend = legend[:legend.index('</div>\n\n  <div class="legs"')]
    for required in ('id="tints"', 'id="scale"', 'id="keys"', 'class="legend-cap"',
                     'class="legend-credit"', 'id="detail"'):
        assert required in legend, f"{required} left the always-visible legend block"
    # The detail row starts hidden: with no readings there is nothing to detail.
    assert re.search(r'<div class="detail" id="detail" hidden>', legend)
    # The folded sheet's allow-list is unchanged, so keys and caption survive.
    fold = next(ln for ln in html.splitlines() if ".rail.folded .legend >" in ln)
    for keep in (":not(.tints)", ":not(.scale)", ":not(.keys)", ":not(.legend-cap)",
                 ":not(.legend-credit)"):
        assert keep in fold, f"the folded sheet stopped keeping {keep}"
    assert ":not(.detail)" not in fold, (
        "the detail row must NOT be in the folded sheet's allow-list: 390 px of "
        "height is for the guaranteed legend")
    # browser_verify.sh counts `.tints span` against the band count, so the
    # detail strip must not be a .tints, and its bracket must not be a span.
    assert 'class="zoomstrip"' in legend
    assert ".tints .span{position:absolute" in html




def test_the_on_screen_range_is_trimmed_so_one_outlier_cannot_claim_the_scale(node, tmp_path):
    """Measured on the live page: at zoom 9.5 over Seoul, 81 sampled points run
    from band 0 in the city to band 22 -- twelve hours -- on a single roadless
    cell in the hills forty kilometres out. Taking the raw minimum and maximum
    let that one cell declare 23 of 37 bands "on screen", which tripped the
    wide-view guard and suppressed the detail row entirely: the opposite of
    what zooming in is supposed to do. This is the fix, and it is the reason
    the caption says "most of this view".

    The sampling loop needs a map, so the TRIM is exercised directly here on
    the same sorted-array arithmetic the function uses. The map-dependent half
    is covered by the deploy's browser check.

    Mutation performed and reverted: set SCALE_TRIM to 0 -> red (the Seoul
    case widens back to 23 bands and the guard hides the row).
    """
    trim = float(re.search(r"const SCALE_TRIM = ([\d.]+);", APP).group(1))
    assert 0 < trim < 0.5, "the trim must remove a tail, not a half"
    probe = f"""
const SCALE_TRIM = {trim};
function trimmed(bands) {{
  const n = bands.length;
  bands.sort((a, b) => a - b);
  const cut = Math.floor(n * SCALE_TRIM);
  return {{ lo: bands[cut], hi: bands[n - 1 - cut] }};
}}
// The real Seoul sample: 80 readings in bands 0-9, one roadless cell at 22.
const seoul = [...Array(80).keys()].map((i) => i % 10).concat([22]);
console.log(JSON.stringify({{
  seoul: trimmed(seoul),
  tight: trimmed([...Array(81)].map(() => 3)),
  world: trimmed([...Array(81).keys()].map((i) => Math.floor(i * 36 / 80))),
}}));
"""
    got = _run(node, tmp_path, probe)
    # The outlier is trimmed away, so the row covers where the view actually is.
    assert got["seoul"] == {"lo": 0, "hi": 9}, got["seoul"]
    assert got["seoul"]["hi"] - got["seoul"]["lo"] + 1 < int(0.6 * N_BANDS), (
        "the Seoul view is still wide enough to suppress the detail row")
    # A view sitting entirely in one band is a legitimate range, not an error.
    assert got["tight"] == {"lo": 3, "hi": 3}
    # ...and a world view stays wide, so the four world ticks stand unchanged.
    assert got["world"]["hi"] - got["world"]["lo"] + 1 >= int(0.6 * N_BANDS)


def test_the_readout_never_prints_the_same_coordinate_twice(node, tmp_path):
    """`describe()` falls back to the coordinate when "name places" is off and
    when nothing is near enough to name, so the readout's two lines were the
    same string. Reproduced in a browser with the setting off, and on the page
    as it stood before this cycle -- a long-standing defect, not a regression.

    Mutation performed and reverted: make placeLine return
    `${lead}<br>${coord}` unconditionally -> red.
    """
    probe = f"""
{_function("placeLine")}
let mode = "name";
function describe(lat, lon) {{ return mode === "name" ? "<b>Guri-si</b>" : fmtCoord(lat, lon); }}
function fmtCoord(lat, lon) {{ return `${{lat}}N ${{lon}}E`; }}
const named = placeLine(37.57, 127.12);
mode = "coord";
const bare = placeLine(37.57, 127.12);
console.log(JSON.stringify({{ named, bare }}));
"""
    got = _run(node, tmp_path, probe)
    # A named place keeps both lines: the name, then the coordinate under it.
    assert got["named"] == "<b>Guri-si</b><br>37.57N 127.12E"
    # With nothing to name, one line, not the same thing twice.
    assert got["bare"] == "37.57N 127.12E"
    assert got["bare"].count("37.57N") == 1
