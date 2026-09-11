"""The notice that explains a blank globe must be reachable by real failures.

CLAUDE.md's deploy rule records that this site has gone out blank twice, and
that `curl` returning 200 proves nothing. The page carries a notice for exactly
that case -- and for the whole of its life the notice could not fire, because
the handler tested pmtiles.js's message text for the words "pmtiles", "tile" or
"source" and pmtiles.js emits none of them. The guard passed review because its
recorded verification fired a synthetic error containing the literal string
"pmtiles".

The end-to-end check (fire the two real messages at the live map, require the
notice) is in `scripts/browser_verify.sh`. What is pinned here is why the
message test alone cannot be trusted: the real strings are asserted NOT to
match it, so a regression to message-only matching is caught by a test that
cannot be satisfied by rewording a comment.
"""

import re

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

#: The messages pmtiles.js and MapLibre actually produce when an archive is
#: missing, truncated, or served by something that will not do Range requests.
#: Taken from the library sources, and reproduced against the real dist/ with
#: the archives withheld.
REAL_FAILURES = (
    "Bad response code: 404",
    "Bad response code: 403",
    "archive does not appear to support HTTP Byte Serving",
    "Unexpected end of JSON input",
)


def _handler() -> str:
    m = re.search(r'map\.on\("error", \(e\) => \{(.*?)\n\}\);', APP, re.S)
    assert m, "the map error handler has moved; re-derive this test"
    return re.sub(r"^\s*//.*$", "", m.group(1), flags=re.M)


def test_the_notice_is_triggered_by_the_source_not_by_the_wording():
    """`e.sourceId` is MapLibre's own answer to "which source failed?".

    Mutation performed and reverted: drop `e?.sourceId ||` from the condition
    -> red here, and the browser gate's two real messages stop showing the
    notice at all.
    """
    assert re.search(r"e\?\.sourceId", _handler()), (
        "the map error handler no longer discriminates on the failing source")
    assert re.search(r"noteTileTrouble\(msg,\s*e\?\.sourceId\)", _handler()), (
        "noteTileTrouble is no longer told which source failed")


def test_the_message_test_alone_would_miss_every_real_failure():
    """This is the evidence for the test above, not a restatement of it.

    If the fallback regex is ever made the only condition again, these four
    strings are the reason it will be silent.
    """
    m = re.search(r"/([^/]+)/i\.test\(msg\)", _handler())
    assert m, "the fallback message test has moved; re-derive this test"
    pattern = re.compile(m.group(1), re.I)
    missed = [s for s in REAL_FAILURES if not pattern.search(s)]
    assert missed == list(REAL_FAILURES), (
        "a real pmtiles failure message now matches the fallback regex; if the "
        "regex has been widened on purpose, re-derive REAL_FAILURES from the "
        "library rather than relaxing this assertion")


def test_the_notice_names_the_layer_from_the_source_id():
    """"The globe is blank" is wrong when it is only the coastline missing.

    Mutation performed and reverted: make `water` unconditionally
    `/water\\.pmtiles/i.test(msg)` again -> the browser gate's water case names
    the bands.
    """
    m = re.search(r"function noteTileTrouble\(([^)]*)\)", APP)
    assert m and "sourceId" in m.group(1), (
        "noteTileTrouble no longer takes the failing source id")
    assert re.search(r"sourceId === WATER_SOURCE", APP), (
        "the notice no longer decides which layer failed from the source id")
    # The constant and the addSource call must stay the same string, or the
    # notice names the wrong layer for every coastline failure.
    assert re.search(r'const WATER_SOURCE = "water"', APP)
    assert re.search(r"map\.addSource\(WATER_SOURCE,", APP)
