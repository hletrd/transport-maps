"""The ground legs' dashes flow toward the destination, and only when they should.

An always-on `requestAnimationFrame` loop that repaints a globe is the cost
this feature has to avoid, so what is pinned here is mostly when the loop does
NOT run: with no ground leg on screen, with the tab hidden, and with
`prefers-reduced-motion: reduce`. Reduced motion stops the dashes dead rather
than slowing them, which is what the preference means.

The real `dashAtPhase`, `FLOW_FRAMES`, `setFlowStep`, `flowShouldRun`,
`flowTick`, `flowResume` and `setRouteFlow` are sliced out of `web/app.js` and
RUN under Node against a fake `map`, `document` and `requestAnimationFrame`, so
the frame budget and the pause conditions are measured rather than asserted
about as source text.

Two facts about MapLibre that this leans on were read out of the vendored
bundle (`web/vendor/maplibre-gl.js`), not assumed, and are re-derived
independently here:

  * `LineAtlas.getDash` keys its cache on `dasharray.join(",")`, so the set of
    distinct arrays the loop can produce must be FINITE or the cache grows
    without bound and a dash texture is rebuilt every frame.
  * `getDashRanges` starts an odd-length array at `-last`, wrapping the final
    element around to before the line's start, which is what makes a
    three-element phase shift correct.

Mutations performed and reverted, each confirmed RED:
  * `flowShouldRun`: drop `&& !document.hidden`                  -> 1 failed
  * `flowShouldRun`: drop `&& !REDUCED_MOTION.matches`           -> 2 failed
  * `flowShouldRun`: drop `flowWanted &&`                        -> 2 failed
  * `flowTick`: `return setFlowStep(0)` -> `return`              -> 1 failed
  * `flowResume`: drop the `cancelAnimationFrame` branch         -> 1 failed
  * `setFlowStep`: drop the `k === flowStep` early return        -> 1 failed
  * `FLOW_FRAMES`: `(FLOW_STEPS - k)` -> `k`  (flow reversed)    -> 1 failed
"""

from __future__ import annotations

import json
import shutil
import subprocess
from itertools import pairwise

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _slice(start: str, opener: str = "{") -> str:
    """Source from `start` to the brace that closes the block it opens."""
    i = APP.index(start)
    j = APP.index(opener, i)
    depth = 0
    for k in range(j, len(APP)):
        if APP[k] == opener:
            depth += 1
        elif APP[k] == "}":
            depth -= 1
            if depth == 0:
                return APP[i:k + 1]
    raise AssertionError(f"{start!r} is not brace-balanced")


def _function(name: str) -> str:
    return _slice(f"function {name}(")


def _const_line(name: str) -> str:
    i = APP.index(f"const {name} ")
    return APP[i:APP.index("\n", i)]


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the page functions cannot be run")
    return exe


def _probe(*, wanted: str, hidden: str, reduced: str, frames: int = 60,
           ms_per_frame: int = 16, flip_at: int = -1, flip: str = "") -> str:
    """Drive `frames` animation frames and report what the loop did.

    `flip` is JavaScript run after frame `flip_at`, WITHOUT calling
    flowResume -- it stages the condition changing under a loop that is already
    running, which is the only way to reach flowTick's own guard.
    """
    # FLOW_FRAMES is an Array.from(...) spanning two lines; take both.
    i = APP.index("const FLOW_FRAMES = ")
    flow_frames = APP[i:APP.index(";\n", i) + 1]
    return f"""
let flowRaf = 0, flowStep = -1, flowWanted = false;
const REDUCED_MOTION = {{ matches: {reduced}, addEventListener() {{}} }};
globalThis.document = {{ hidden: {hidden}, addEventListener() {{}} }};

// A fake map that records every dasharray written to the layer.
const writes = [];
const map = {{
  getLayer: () => true,
  setPaintProperty: (layer, prop, value) => writes.push([layer, prop, value]),
}};

// A fake clock and frame queue: one frame every {ms_per_frame} ms.
let now = 0, queued = null, nextId = 1;
function requestAnimationFrame(fn) {{ queued = fn; return nextId++; }}
function cancelAnimationFrame(id) {{ queued = null; }}
let cancels = 0;
const _cancel = cancelAnimationFrame;
cancelAnimationFrame = (id) => {{ cancels++; _cancel(id); }};

{_const_line("FLOW_DASH")}
{_const_line("FLOW_STEPS")}
{_const_line("FLOW_MS")}
{_function("dashAtPhase")}
{flow_frames}
{_function("setFlowStep")}
{_function("flowShouldRun")}
{_function("flowTick")}
{_function("flowResume")}
{_function("setRouteFlow")}

setRouteFlow({wanted});
let framesRun = 0;
for (let i = 0; i < {frames}; i++) {{
  if (i === {flip_at}) {{ {flip} }}
  if (!queued) break;
  const fn = queued; queued = null;
  now += {ms_per_frame};
  fn(now); framesRun++;
}}
console.log(JSON.stringify({{
  framesRun, cancels, pending: queued !== null, flowStep,
  writes: writes.map((w) => w[2]),
  layer: writes.length ? writes[0][0] : null,
  prop: writes.length ? writes[0][1] : null,
  frames: FLOW_FRAMES,
  period: FLOW_DASH + 2.5,
}}));
"""


def _run(node: str, tmp_path, body: str) -> dict:
    script = tmp_path / "flow.mjs"
    script.write_text(body, encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------- it runs ---

def test_a_drawn_ground_leg_animates(node, tmp_path) -> None:
    got = _run(node, tmp_path, _probe(wanted="true", hidden="false", reduced="false"))
    assert got["framesRun"] == 60, "the loop stopped rescheduling itself"
    assert got["pending"] is True, "the loop did not queue its next frame"
    assert got["layer"] == "route-ground" and got["prop"] == "line-dasharray", (
        f"the loop wrote {got['prop']} on {got['layer']}")
    assert len(got["writes"]) > 4, (
        f"60 frames produced only {len(got['writes'])} dash changes; nothing moves")


def test_the_dash_changes_less_often_than_the_frames(node, tmp_path) -> None:
    """The map repaints only when the dasharray is written, so the step must be
    quantised. 60 frames at 16 ms is 960 ms, a little over one 720 ms period,
    and one period is FLOW_STEPS changes."""
    got = _run(node, tmp_path, _probe(wanted="true", hidden="false", reduced="false"))
    n = len(got["writes"])
    assert n < 60, (
        f"{n} writes in 60 frames: every frame repaints the map, which is the "
        "cost this quantisation exists to avoid")
    assert 10 <= n <= 22, (
        f"{n} dash writes in 960 ms; one 720 ms period is 12 steps, so this "
        "should be about 16")


# ----------------------------------------------------- it does NOT run -----

@pytest.mark.parametrize("wanted, hidden, reduced, why", [
    ("false", "false", "false", "no ground leg is drawn"),
    ("true", "true", "false", "the tab is hidden"),
    ("true", "false", "true", "the visitor asked for reduced motion"),
])
def test_the_loop_does_not_run(node, tmp_path, wanted, hidden, reduced, why) -> None:
    got = _run(node, tmp_path, _probe(wanted=wanted, hidden=hidden, reduced=reduced))
    assert got["framesRun"] == 0, f"the loop ran although {why}"
    assert got["pending"] is False, f"a frame is still queued although {why}"


def test_reduced_motion_leaves_the_dashes_static_not_slower(node, tmp_path) -> None:
    """The preference means stop, not decelerate. Frame 0 of the cycle is the
    layer's own resting pattern, so the line looks exactly as it did before
    this feature existed."""
    got = _run(node, tmp_path, _probe(wanted="true", hidden="false", reduced="true"))
    assert got["flowStep"] == 0, (
        f"reduced motion left the dashes at step {got['flowStep']}, not at rest")
    assert got["writes"] == [[2, 2.5]], (
        f"the resting pattern is not the layer's own [2, 2.5]: {got['writes']}")


def test_clearing_the_route_cancels_the_pending_frame(node, tmp_path) -> None:
    """A cleared route must not leave a frame queued: that is one more repaint
    of the globe for a line that is no longer drawn."""
    body = _probe(wanted="true", hidden="false", reduced="false", frames=5)
    body = body.replace(
        'console.log(JSON.stringify({',
        'setRouteFlow(false);\nconsole.log(JSON.stringify({', 1)
    got = _run(node, tmp_path, body)
    assert got["pending"] is False, "a frame is still queued after the route was cleared"
    assert got["cancels"] >= 1, "cancelAnimationFrame was never called"
    assert got["flowStep"] == 0, "the dashes were left mid-cycle"


# --------------------------------------------------- the pattern itself ----

def test_the_frame_set_is_finite_and_distinct(node, tmp_path) -> None:
    """MapLibre's LineAtlas keys its dash cache on `dasharray.join(",")`
    (verified in web/vendor/maplibre-gl.js). A loop that produced continuous
    values would build a dash texture every frame and grow that cache without
    bound, so the set must be small, fixed, and free of duplicates."""
    got = _run(node, tmp_path, _probe(wanted="true", hidden="false", reduced="false"))
    frames = got["frames"]
    assert len(frames) == 12, f"{len(frames)} frames; the cost claim assumes 12"
    keys = [",".join(str(x) for x in f) for f in frames]
    assert len(set(keys)) == len(keys), (
        f"two frames share a cache key, so the cycle stutters: {keys}")
    for f in frames:
        assert all(isinstance(x, (int, float)) and x >= 0 for x in f), (
            f"a negative or non-numeric dash length: {f}")
        assert len(f) in (2, 3, 4), f"unexpected dasharray shape: {f}"


def test_every_frame_keeps_the_pattern_the_same_length(node, tmp_path) -> None:
    """A phase shift must not change the spacing. Each array's total is one
    period for the odd form (MapLibre wraps the last element to the front) and
    two periods for the even form."""
    got = _run(node, tmp_path, _probe(wanted="true", hidden="false", reduced="false"))
    period = got["period"]
    assert period == 4.5, "re-derive: the layer's dash pattern has changed"
    for f in got["frames"]:
        total = sum(f)
        assert abs(total - period) < 1e-6, (
            f"{f} totals {total}, not the {period} of one period, so the dashes "
            "change spacing as they move")


def test_the_dashes_flow_toward_the_destination(node, tmp_path) -> None:
    """renderRoute adds every ground leg departure-first, so the pattern must
    move toward the END of the line as time advances.

    The leading dash's start offset is derived here from each frame, and it has
    to increase: at offset `o` the first dash begins `o` units along the line,
    so a rising `o` is motion away from the departure.
    """
    got = _run(node, tmp_path, _probe(wanted="true", hidden="false", reduced="false"))
    period = got["period"]

    def start_offset(f: list) -> float:
        """How far along the line the first dash begins, in line-widths.

        Three shapes, one meaning. [D, G] is the resting pattern, s = 0.
        [D-s, G, s] is the odd form: MapLibre wraps that trailing dash around
        to before the line's start, so the dash begins at -s. [0, P-s, D, s-D]
        is the even form and its first real dash begins at P-s. All three are
        the same quantity mod P.
        """
        if len(f) == 2:
            return 0.0
        s = f[2] if len(f) == 3 else period - f[1]
        return round((period - s) % period, 6)

    offsets = [start_offset(f) for f in got["frames"]]
    assert offsets[0] == 0, f"the cycle does not start at rest: {offsets}"
    rises = sum(1 for a, b in pairwise(offsets) if b > a)
    assert rises == len(offsets) - 1, (
        f"the dash start does not advance monotonically along the line, so the "
        f"flow is backwards or stutters: {offsets}")
    assert offsets[-1] < period, "the cycle overshoots a full period"


# --------------------------- the loop's own guard, not the listeners' -------

@pytest.mark.parametrize("flip, why", [
    ("document.hidden = true;", "the tab was hidden"),
    ("REDUCED_MOTION.matches = true;", "reduced motion was turned on"),
    ("flowWanted = false;", "the route was cleared"),
])
def test_a_condition_changing_mid_flight_stops_and_rests(node, tmp_path, flip, why) -> None:
    """`flowResume` is wired to `visibilitychange` and to the media query's
    `change`, but `flowTick` re-checks on every frame as well, and that check is
    what catches a condition the listeners miss -- a browser that throttles
    rather than fires, or a future caller that sets the flag directly.

    The flip here deliberately does NOT call flowResume, so only flowTick's own
    guard can act on it.

    Mutation performed and reverted: `flowTick`'s
    `if (!flowShouldRun()) return setFlowStep(0);` -> `return;` -> 3 failed.
    """
    got = _run(node, tmp_path, _probe(
        wanted="true", hidden="false", reduced="false", frames=40,
        flip_at=6, flip=flip))
    assert got["framesRun"] == 7, (
        f"the loop ran {got['framesRun']} frames after {why}; it should stop on "
        "the frame that notices")
    assert got["pending"] is False, f"a frame is still queued after {why}"
    assert got["flowStep"] == 0, (
        f"the dashes were left at step {got['flowStep']} after {why}, not "
        "returned to the layer's resting pattern")
    assert got["writes"][-1] == [2, 2.5], (
        f"the last dasharray written after {why} was {got['writes'][-1]}, not "
        "the resting [2, 2.5]")


# ------------------------------------------ exactly one animator, please ----

def test_only_one_thing_animates_the_dashes() -> None:
    """Two dash loops fighting over one paint property is not hypothetical.

    397ded7 landed a SECOND implementation beside this one -- `DASH_CYCLE` /
    `startDashes` / `stopDashes`, driven from a `sourcedata` handler -- and both
    shipped. Measured on the live page with a route drawn: 26.6 dasharray writes
    a second and **20** distinct patterns, against the 12 this cycle defines.
    The two interleaved, so the dashes jittered between two cadences and the map
    repainted for both.

    The duplicate was also wrong on its own terms, which is why this one
    survived rather than the other: its frames totalled 4.8126 to 7.0001 line
    widths, so the pattern's period swung by 45% and the dashes stretched and
    compressed instead of flowing; and its leading gap DECREASED every step, so
    its first dash started earlier each frame and the flow ran toward the
    departure -- the opposite of what its own comment claimed.

    Mutation performed and reverted: paste a second
    `map.setPaintProperty("route-ground", "line-dasharray", …)` call into
    app.js -> red.
    """
    import re

    code = re.sub(r"//[^\n]*", "", APP)
    writers = re.findall(
        r"setPaintProperty\(\s*[\"']route-ground[\"']\s*,\s*[\"']line-dasharray[\"']", code)
    assert len(writers) == 1, (
        f"{len(writers)} places write route-ground's dasharray; they will "
        "interleave and the dashes will jitter between their cadences")

    # ...and one frame loop driving it.
    loops = re.findall(r"requestAnimationFrame\(\s*(\w+)\s*\)", code)
    dash_loops = [n for n in set(loops) if "flow" in n.lower() or "dash" in n.lower()]
    assert dash_loops == ["flowTick"], (
        f"the dash loop is driven by {dash_loops}; there should be exactly one, "
        "flowTick")
