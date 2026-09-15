"""A failure the page survives must still be a failure somebody can SEE.

Three defects, one theme. CLAUDE.md's deploy rule records two live incidents
where the site went out blank "with no console error visible after the fact",
and each of these is another way for that to happen.

1. Nine fetches were written `(r) => (r.ok ? r.json() : null)`. An HTTP error
   status became a silent `null`, the next `.then` returned early, and nothing
   was logged anywhere. The `.catch` beside some of them only fires on a
   NETWORK error, never on a 404 or a 500 -- so a server answering 404 for
   every per-origin extra produced a page with no itinerary, no arrival
   airports and no mode breakdown, and an empty console.

2. `#tiletrouble` is a visible `<p>` in no live region. A screen-reader user
   heard announce()'s "Travel times from Seoul are ready" from the same load
   while the globe was blank, and never heard why. WCAG 2.2 SC 4.1.3.

3. That notice said "The travel times BELOW are still correct", and "below"
   pointed at the colour key at all four viewports.

`okOr` is RUN here rather than read: it is the whole of (1) and it is a pure
function of a Response-shaped object, so there is no excuse for asserting on
its source text.

MUTATIONS PERFORMED:
  - `okOr` returns `r` unconditionally: **RED** on
    `test_a_failed_response_is_turned_into_null` and
    `test_a_failed_response_is_logged_with_its_status`.
  - `okOr` drops the `console.warn`: **RED** on the logging test, green on the
    other -- which is the point of having both.
  - delete `announce(say)` from `noteTileTrouble`: **RED** on
    `test_the_tile_notice_reaches_the_live_region` -- but only after that
    assertion was fixed. On the first attempt it came back **GREEN**, because
    `"announce(" in note` was matching the COMMENT inside the function, which
    quotes "announce()'s own words". The comment strip is load-bearing.
  - put "times below are still correct" back: **RED** on
    `test_the_tile_notice_does_not_point_anywhere`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _uncommented(src: str) -> str:
    """Source with `//` and `//:` lines removed.

    The prose that explains a ban is allowed to quote the banned thing -- the
    comment above `noteTileTrouble` says what "below" used to point at, and a
    check that could not tell the two apart would forbid explaining the fix.
    """
    return "\n".join(ln for ln in src.splitlines()
                      if not ln.lstrip().startswith(("//", "//:")))


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
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
        pytest.skip("node is not on PATH; okOr cannot be run")
    return exe


@pytest.fixture(scope="module")
def ok_or(node: str, tmp_path_factory):
    """Run the real `okOr` against a Response-shaped object.

    Returns (result_is_null, warnings) so both halves -- what it RETURNS and
    what it SAYS -- can be asserted separately. A helper that returned null
    silently would be the defect all over again.
    """
    path = tmp_path_factory.mktemp("okor") / "okor.cjs"
    path.write_text(
        "const warnings = [];\n"
        "console.warn = (...a) => warnings.push(a.map(String).join(' '));\n"
        + _function("okOr") +
        "\nconst r = JSON.parse(process.argv[2]);\n"
        "const out = okOr(r, process.argv[3]);\n"
        "process.stdout.write(JSON.stringify("
        "{ nulled: out === null, same: out === r, warnings }));\n",
        encoding="utf-8")

    def call(response: dict, what: str) -> dict:
        done = subprocess.run([node, str(path), json.dumps(response), what],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


def test_a_successful_response_passes_straight_through(ok_or) -> None:
    """The positive control. Without it, `okOr` returning null for everything
    would satisfy every other test in this file while breaking every fetch on
    the page.
    """
    out = ok_or({"ok": True, "status": 200, "statusText": "OK",
                 "url": "https://example/places.json"}, "places.json")
    assert out["same"], "a 200 response did not pass through okOr unchanged"
    assert not out["nulled"]
    assert out["warnings"] == [], f"a successful fetch logged: {out['warnings']}"


@pytest.mark.parametrize("status,text", [(404, "Not Found"), (500, "Internal Server Error"),
                                         (403, "Forbidden"), (502, "Bad Gateway")])
def test_a_failed_response_is_turned_into_null(ok_or, status: int, text: str) -> None:
    """Behaviour is deliberately unchanged: these files are progressive extras
    and an origin built before they existed is EXPECTED to 404, so a bad
    response must still degrade to null rather than become a user-facing error.
    """
    out = ok_or({"ok": False, "status": status, "statusText": text,
                 "url": "https://example/origins/seoul.modes.bin"}, "seoul.modes.bin")
    assert out["nulled"], f"HTTP {status} did not degrade to null"


@pytest.mark.parametrize("status,text", [(404, "Not Found"), (500, "Internal Server Error")])
def test_a_failed_response_is_logged_with_its_status(ok_or, status: int, text: str) -> None:
    """...and the half that was missing. The log has to name WHICH file and
    WHAT went wrong, or an operator reading the console still cannot tell a
    404 for an optional extra from a server that has fallen over.
    """
    out = ok_or({"ok": False, "status": status, "statusText": text,
                 "url": "https://example/origins/seoul.modes.bin"}, "seoul.modes.bin")
    assert out["warnings"], f"HTTP {status} was swallowed in silence"
    joined = " ".join(out["warnings"])
    assert "seoul.modes.bin" in joined, f"the log does not name the file: {joined}"
    assert str(status) in joined, f"the log does not carry the status: {joined}"


def test_no_fetch_still_swallows_its_status_silently() -> None:
    """The nine sites, as a class rather than one at a time.

    `r.ok ? r.<something>() : null` is the exact shape that discards the
    status. Any new one is a new silent failure, so the pattern is banned
    outright in code -- the prose that explains the ban may quote it.
    """
    code = _uncommented(APP)
    silent = re.findall(r"r\.ok \? r\.\w+\(\) : null", code)
    assert not silent, (
        f"{len(silent)} fetch(es) still turn an HTTP error into a silent null; "
        "route them through okOr() so the status reaches the console")
    # ...and the positive control: okOr must actually be in use, or the
    # assertion above is satisfied by a page that fetches nothing.
    assert code.count("okOr(") >= 9, (
        f"okOr is used {code.count('okOr(')} times; nine fetches need it")


def test_the_tile_notice_reaches_the_live_region() -> None:
    """`#tiletrouble` is a plain `<p>`; `#status` is the `role="status"` region.

    A screen reader was told "Travel times from Seoul are ready" while the
    globe was blank and never told why. SC 4.1.3.
    """
    # _uncommented, and this is not fussiness: the comment inside
    # noteTileTrouble quotes "announce()'s own words", so the first draft of
    # this assertion matched the COMMENT. Deleting the real `announce(say)`
    # call left it green -- caught by mutating, exactly as CLAUDE.md requires,
    # and recorded here because it is the cheapest way to make the same
    # mistake twice.
    note = _uncommented(_function("noteTileTrouble"))
    assert "announce(" in note, (
        "noteTileTrouble writes only to #tiletrouble, which is in no live "
        "region: a screen-reader user is never told the globe is blank")
    # The element it writes visibly is still not a live region, and must not
    # quietly become one -- two announcements of the same failure is worse
    # than one. This pins WHICH channel carries it.
    trouble = re.search(r'id="tiletrouble"[^>]*>', HTML)
    assert trouble, "#tiletrouble is gone from index.html"
    assert "aria-live" not in trouble.group(0), (
        "#tiletrouble became a live region as well as being announce()d; the "
        "failure would now be read out twice")
    status = re.search(r'id="status"[^>]*>', HTML)
    assert status and 'role="status"' in status.group(0), (
        "#status is no longer the live region announce() writes into")


def test_the_tile_notice_does_not_point_anywhere() -> None:
    """"The travel times BELOW are still correct" pointed at the colour key at
    every one of the four viewports. A positional word in a message that moves
    with the layout is a promise the layout does not keep.
    """
    note = _uncommented(_function("noteTileTrouble")).lower()
    for word in ("below", "above", "on the right", "on the left", "to the right"):
        assert word not in note, (
            f"the tile-trouble notice says {word!r}; #tiletrouble moves between "
            "the four viewports and cannot promise where anything is")


def test_the_globe_has_a_focus_ring_of_its_own() -> None:
    """`#map` is `position:fixed; inset:0` and focusable, so with no rule of
    its own it wore the user agent's 1 px ring on the VIEWPORT EDGE -- 440 px
    of it behind the bottom sheet at 390x844, indicating nothing.
    SC 2.4.11 and 2.4.13.
    """
    assert "#map:focus-visible" in HTML, (
        "the globe has no focus-visible rule, so it falls back to the UA ring "
        "drawn on the viewport edge")
    rule = re.search(r"#map:focus-visible[^{]*\{([^}]*)\}", HTML)
    assert rule, "the #map:focus-visible rule has no body"
    body = rule.group(1)
    assert "outline" in body and "none" not in body, (
        f"the globe's focus rule does not draw an outline: {body}")
    # Inset, or it is drawn outside a full-viewport element and clipped away.
    assert "outline-offset:-" in body.replace(" ", ""), (
        f"the globe's focus ring is not inset and would be clipped: {body}")


def test_the_sheet_is_unfolded_before_the_panel_is_opened() -> None:
    """`.rail.folded > :not(.sheet-toggle):not(.reading)` puts `#route` at
    `display:none`, so `openRoutePanel()` before `unfoldSheet()` set `open` on
    a hidden element and left focus on `<body>`.

    Both call sites, because fixing one and not the other is how cycle 14's
    D15 came back half-fixed.
    """
    code = _uncommented(APP)
    assert "openRoutePanel();\n  unfoldSheet();" not in code, (
        "a call site still opens #route while the folded sheet has it at "
        "display:none")
    pairs = code.count("unfoldSheet();\n  openRoutePanel();")
    assert pairs == 2, (
        f"expected both call sites to unfold first, found {pairs}")
