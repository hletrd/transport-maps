"""The URL's state: written, read back, and validated.

The writer (`syncPermalink`) and the reader sit 1,800 lines apart and agreed
only by coincidence of two string literals. Proven by mutation in the cycle-8
review: renaming the reader's `q.get("to")` to `q.get("dest")` left all 153
`tests/web` tests green, as did renaming `from`, and as did deleting the
destination's latitude and longitude bounds check -- so a pasted link could
silently lose half its state, or carry an out-of-range coordinate into
`lookup()`, with nothing to say so.

`parseCamera`, `cleanLabel` and the destination-parsing block are pure string
maths, so they are sliced out of `app.js` by brace matching and RUN under Node
rather than grepped for. The key-set test is necessary and not sufficient on
its own: renaming only the line that parses a value leaves the key's other
mention in place.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from tests.web import _js
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
EDGES = list(config.BAND_EDGES_MIN)
N_BANDS = len(EDGES) + 1


def _function(name: str) -> str:
    return _js.function(name, with_async=True)


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


# ---- the URL ---------------------------------------------------------------

#: Every parameter the writer emits must be read back. The pair is the test:
#: the two halves live 1,800 lines apart and a rename in either was invisible.
URL_KEYS = ("from", "to", "label", "scheme", "sea", "north", "places", "at", "avoid", "carryon")


def test_every_parameter_the_writer_emits_is_read_back_on_load():
    """Mutation performed and reverted: rename the reader's `q.get("to")` to
    `q.get("dest")` -> red. Same for `from`. Before this test both left all
    153 tests/web tests green while a pasted link silently lost half its
    state."""
    writer = _function("syncPermalink")
    written = set(re.findall(r'put\("(\w+)"', writer))
    assert written == set(URL_KEYS), f"syncPermalink writes {sorted(written)}"

    # The reader is spread over the early urlChoice/urlFlag calls and the late
    # block, so search the whole file for each key being READ.
    for key in URL_KEYS:
        read = (f'q.get("{key}")' in APP or f'URL_PARAMS.get("{key}")' in APP
                or f'urlChoice("{key}"' in APP or f'urlFlag("{key}"' in APP)
        assert read, f"?{key}= is written into the address and never read back"


def test_the_destination_block_actually_reads_the_key_the_writer_wrote(node, tmp_path):
    """The reader's destination block, RUN against a real URLSearchParams.

    The key-set test above is necessary and not sufficient: renaming only the
    line that parses the value leaves the key's other mention in place, and the
    substring check stays green while a pasted `?to=` produces no pin at all.
    That is mutation 3 of the cycle-8 review, which left all 153 tests/web
    tests green.

    Mutation performed and reverted: `q.get("to")` -> `q.get("dest")` on the
    parsing line -> red here (no pin). Mutation: rename the writer's key
    instead -> red on the key-set test above.
    """
    block = APP[APP.index('  const to = (q.get('):APP.index('  // ?at= -- the camera.')]
    probe = f"""
const LABEL_MAX = {re.search(r"const LABEL_MAX = (\d+);", APP).group(1)};
{_function("cleanLabel")}
function parse(search) {{
  const q = new URLSearchParams(search);
  const URL_REJECTED = [];
  let requestedPin = null;
{block}
  return {{ requestedPin, URL_REJECTED }};
}}
console.log(JSON.stringify({{
  good: parse("to=59.44,24.75&label=Tallinn"),
  bare: parse("to=59.44,24.75"),
  bad:  parse("to=91,0"),
  junk: parse("to=nonsense"),
  none: parse(""),
}}));
"""
    got = _run(node, tmp_path, probe)
    assert got["good"]["requestedPin"] == {"lat": 59.44, "lon": 24.75, "label": "Tallinn"}
    assert got["bare"]["requestedPin"] == {"lat": 59.44, "lon": 24.75, "label": None}
    # Out of range and unparseable are both dropped AND reported -- never
    # swallowed, and never trusted into lookup() or the DOM.
    assert got["bad"]["requestedPin"] is None and got["bad"]["URL_REJECTED"] == ["to"]
    assert got["junk"]["requestedPin"] is None and got["junk"]["URL_REJECTED"] == ["to"]
    # An absent parameter is not a rejection.
    assert got["none"]["requestedPin"] is None and got["none"]["URL_REJECTED"] == []


def test_the_copy_button_copies_the_address_it_has_just_refreshed():
    """The camera write is debounced, so a click within 350 ms of letting go of
    a drag would copy the view before the one on screen.

    Mutation: remove the `syncPermalink()` call from the handler -> red."""
    handler = APP[APP.index('$("copy-link").addEventListener'):]
    handler = handler[:handler.index("\n});")]
    assert "syncPermalink();" in handler
    assert handler.index("syncPermalink();") < handler.index("clipboard.writeText"), (
        "the address is flushed AFTER being copied, which copies the stale one")
    assert "location.href" in handler


def test_the_camera_is_written_on_rest_and_never_pushes_history():
    """A drag must not leave forty entries in the back button."""
    assert "history.pushState" not in APP, "the page must only ever replaceState"
    assert APP.count("history.replaceState") == 1
    sync = _function("scheduleCameraSync")
    assert "clearTimeout" in sync and "setTimeout" in sync
    for event in ('map.on("moveend", scheduleCameraSync)',
                  'map.on("rotateend", scheduleCameraSync)',
                  'map.on("pitchend", scheduleCameraSync)'):
        assert event in APP, f"missing {event}"
    assert 'map.on("move", scheduleCameraSync)' not in APP, (
        "the camera must be written at rest, not on every frame of a drag")


@pytest.mark.parametrize("raw,ok", [
    ("37.56650,126.97800,4.20", True),
    ("0,0,0", True),
    ("-33.9,18.4,11,45", True),
    ("-33.9,18.4,11,45,30", True),
    ("91,0,4", False),                  # latitude out of range
    ("0,181,4", False),                 # longitude out of range
    ("0,0,-1", False),                  # zoom out of range
    ("0,0,25", False),
    ("0,0,4,0,86", False),              # pitch beyond MapLibre's limit
    ("0,0", False),                     # too few
    ("0,0,4,0,0,0", False),             # too many
    ("a,b,c", False),
    ("", False),
    ("NaN,0,4", False),
    ("0,0,Infinity", False),
])
def test_a_camera_in_the_address_is_validated_before_it_is_flown_to(node, tmp_path, raw, ok):
    """Held to the same standard `?from=` and `?to=` already are: a partially
    valid camera is not valid, because a good centre with a nonsense zoom would
    fly somewhere nobody asked for.

    Mutation: delete the `Math.abs(lat) > 90` bound -> the 91-degree case goes
    red. Deleting the equivalent bound on `?to=` left all 153 tests green
    before this file existed."""
    probe = f"""
{_function("parseCamera")}
console.log(JSON.stringify({{ got: parseCamera({json.dumps(raw)}) }}));
"""
    got = _run(node, tmp_path, probe)["got"]
    assert (got is not None) == ok, f"parseCamera({raw!r}) -> {got!r}"


@pytest.mark.parametrize("raw,ok", [
    ("37.56650,126.97800", True),
    ("0,0", True),
    ("-90,-180", True),
    ("91,0", False),
    ("-91,0", False),
    ("0,181", False),
    ("0,-181", False),
    ("abc,0", False),
    ("0", False),
    ("0,0,0", False),
])
def test_a_destination_in_the_address_is_bounds_checked(raw, ok):
    """The reader's own bounds, exercised through the same arithmetic it uses.
    Deleting these bounds was mutation 5 of the cycle-8 review and left all 153
    tests/web tests green."""
    parts = raw.split(",")
    accepted = False
    if len(parts) == 2:
        try:
            la, lo = float(parts[0]), float(parts[1])
            accepted = abs(la) <= 90 and abs(lo) <= 180
        except ValueError:
            accepted = False
    assert accepted == ok
    # ...and the page still applies exactly that rule.
    assert "Math.abs(la) <= 90 && Math.abs(lo) <= 180" in APP, (
        "the destination's coordinate bounds have been removed from app.js")


@pytest.mark.parametrize("raw,want", [
    ("Tromso Airport", "Tromso Airport"),
    ("  spaced   out  ", "spaced out"),
    ("line\nbreak", "line break"),
    ("", None),
    ("   ", None),
    (None, None),
    ("x" * 400, "x" * 120),
])
def test_a_pasted_label_is_bounded_and_stripped(node, tmp_path, raw, want):
    """The label travels in the address, so it is a string from whoever wrote
    the link. Every sink that shows it uses textContent, so this is not the
    only defence -- but a hostile link must not be able to put a megabyte of
    newlines in the pin list."""
    probe = f"""
const LABEL_MAX = {re.search(r"const LABEL_MAX = (\d+);", APP).group(1)};
{_function("cleanLabel")}
console.log(JSON.stringify({{ got: cleanLabel({json.dumps(raw)}) }}));
"""
    assert _run(node, tmp_path, probe)["got"] == want


def test_a_setting_at_its_default_is_left_out_of_the_address():
    """Rule 1 of the writer: the common link stays `?from=seoul&to=...`, and a
    parameter's presence means someone chose it."""
    writer = _function("syncPermalink")
    assert "rampName === RAMP_DEFAULT ? null : rampName" in writer
    assert "oceanName === OCEAN_DEFAULT ? null : oceanName" in writer
    assert 'lockNorth ? "1" : null' in writer
    assert 'namePlaces ? null : "0"' in writer
    # `put` deletes on null, so "omitted" really means removed from the URL.
    assert "q.delete(k)" in writer


def test_an_unusable_parameter_is_reported_rather_than_swallowed():
    """`?from=` has said so since it was added, because a mistyped link that
    silently works is indistinguishable from one that does not. Every
    parameter added this cycle is held to the same rule."""
    assert "URL_REJECTED" in APP
    assert "Ignored unusable link setting" in APP
    for key in ("to", "at"):
        assert f'URL_REJECTED.push("{key}")' in APP
    # scheme/sea/north/places report through the two shared helpers.
    for helper in ("urlChoice", "urlFlag"):
        assert "URL_REJECTED.push(key)" in _function(helper)
    # The unknown-city message is unchanged.
    assert 'No departure city called' in APP
