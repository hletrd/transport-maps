"""The resting departure list is capped, and it must say so.

`data/origins.toml` went from 553 to 1,464 cities in b21e808. 1,464 rows is
38,357 px of list -- 175 screens on a 390x844 phone, 378 in landscape -- and
`render()` rebuilt every one of them on every keystroke. "a" alone matches
1,097 of the real names, so the first character of most searches paid nearly
full price.

The resting view now shows the current departure plus the quickest cities to
reach from it. A search still reaches all 1,464.

The risk this file exists for is that a cap is a SILENT data loss: a list
showing 60 of 1,464 looks exactly like a list of 60. So `capCities` is run for
real -- against the real names from `data/origins.toml` -- rather than pinned
with a substring assertion, and the footer that names the true total is
checked from the code that writes it.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from transport_maps import config
from transport_maps.emit import index

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    i = APP.index("(", start)
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "(":
            depth += 1
        elif APP[j] == ")":
            depth -= 1
            if depth == 0:
                i = APP.index("{", j)
                break
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError(f"function {name} is not brace-balanced")


def _cap_constant() -> int:
    m = re.search(r"const UNFILTERED_CAP = (\d+);", APP)
    assert m, "UNFILTERED_CAP is gone; the list is unbounded again"
    return int(m.group(1))


CAP = _cap_constant()
ORIGINS = index.load_origins()


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH")
    return exe


@pytest.fixture(scope="module")
def cap(node: str, tmp_path_factory):
    """capCities, run for real. `lookup` is the only thing stubbed, and it is
    stubbed as a table so a test can say what every city's time is."""
    src = (re.search(r"const UNFILTERED_CAP = \d+;", APP).group(0) + "\n"
           + "const MAX_MINUTES = 65534;\n"
           + "let active = null, TIMES = {};\n"
           + "function lookup(lat, lon) { return TIMES[`${lat},${lon}`]; }\n"
           + _function("capCities") + "\n")
    path = tmp_path_factory.mktemp("cap") / "cap.cjs"
    # `sorted` is computed in JS with the SAME comparator the page sorts
    # with. Python's sorted() disagrees with localeCompare on diacritics -- it
    # orders "Hamah" after "Yibin" and localeCompare does not -- so a
    # Python-side reference sort would test the wrong thing.
    path.write_text(
        src + "const inp = JSON.parse(process.argv[2]);\n"
        "active = inp.active; TIMES = inp.times || {};\n"
        "const r = capCities(inp.cities);\n"
        "const names = r.hits.map((c) => c.name);\n"
        "const sorted = names.every((n, i, a) => i === 0"
        "  || a[i - 1].localeCompare(n) <= 0);\n"
        "process.stdout.write(JSON.stringify("
        "{ names, slugs: r.hits.map((c) => c.slug),"
        "  capped: r.capped, sorted }));\n", encoding="utf-8")

    def call(cities, active=None, times=None):
        payload = {"cities": cities, "active": active, "times": times or {}}
        done = subprocess.run([node, str(path), json.dumps(payload)],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


def _real_cities() -> list[dict]:
    return sorted(
        ({"slug": o["slug"], "name": o["name"], "lat": o["lat"], "lon": o["lon"]}
         for o in ORIGINS), key=lambda c: c["name"])


def test_the_real_origins_file_is_big_enough_for_this_to_matter():
    """If origins.toml ever shrinks back under the cap these tests stop
    testing anything, and they must say so rather than pass quietly."""
    assert len(ORIGINS) > CAP, (
        f"origins.toml has {len(ORIGINS)} cities and the cap is {CAP}; the "
        "cap never engages and every test below is vacuous")


def test_a_short_list_is_not_capped_at_all(cap):
    cities = _real_cities()[:CAP]
    got = cap(cities)
    assert got["capped"] is False
    assert len(got["names"]) == len(cities)


def test_the_real_list_is_capped_and_reports_it(cap):
    """Mutation performed and reverted: `return { hits, capped: false }` ->
    red, and the footer disappears from the page with 1,404 cities silently
    gone.
    """
    got = cap(_real_cities())
    assert got["capped"] is True
    assert len(got["names"]) == CAP, (
        f"{len(got['names'])} rows, not {CAP}; the cap does not bind")


def test_the_current_departure_is_always_shown(cap):
    """It is the row aria-current, the roving tabindex and the
    scroll-into-view all look for. Seoul is row 1,133 of 1,464 alphabetically
    and, with no times loaded, would fall outside an alphabetical head.

    Mutation performed and reverted: drop the `c.slug === active?.slug ? -1`
    branch -> red.
    """
    cities = _real_cities()
    seoul = next(c for c in cities if c["slug"] == "seoul")
    assert cities.index(seoul) > CAP, "Seoul is inside the head; pick another"

    # Times loaded, Seoul the origin: it must be present even though every
    # other city has a smaller number than its own -1 sentinel would suggest.
    times = {f"{c['lat']},{c['lon']}": 100 for c in cities}
    got = cap(cities, active={"slug": "seoul"}, times=times)
    assert "seoul" in got["slugs"], (
        "the list does not contain the city it is departing from")


def test_the_cities_kept_are_the_quickest_to_reach(cap):
    """Not the alphabetical head. That is the whole reason a cap is tolerable:
    the 60 shown are useful, rather than 60 cities beginning with A.

    Mutation performed and reverted: sort by `a.t - b.t` -> `b.t - a.t` ->
    red, the SLOWEST are kept.
    """
    cities = _real_cities()
    # Give the last 60 alphabetically the smallest times.
    times = {}
    for i, c in enumerate(cities):
        times[f"{c['lat']},{c['lon']}"] = 10 if i >= len(cities) - CAP else 9000
    got = cap(cities, active={"slug": "__none__"}, times=times)
    expected = {c["slug"] for c in cities[-CAP:]}
    assert set(got["slugs"]) == expected, (
        "the cap kept the alphabetical head instead of the quickest cities")


def test_the_rows_are_still_presented_in_alphabetical_order(cap):
    """Ranking chooses WHICH cities; it must not reorder the reading. A list
    that re-sorts itself on every origin change cannot be scanned.

    Mutation performed and reverted: drop the second `.sort(localeCompare)` ->
    red, the rows come back in time order.
    """
    cities = _real_cities()
    times = {f"{c['lat']},{c['lon']}": len(cities) - i
             for i, c in enumerate(cities)}
    got = cap(cities, active={"slug": "__none__"}, times=times)
    assert got["sorted"], (
        f"rows are not in localeCompare order: {got['names'][:6]}")
    # ...and they really are the time-ranked selection, or this would pass on
    # a list that was never reordered at all.
    # times run len(cities)-i, so the SMALLEST belong to the last rows.
    assert set(got["slugs"]) == {c["slug"] for c in cities[-CAP:]}


def test_before_the_arrays_land_it_falls_back_to_the_alphabet(cap):
    """`lookup` returns undefined until the origin's arrays arrive. Ranking on
    that would be ranking on nothing; an alphabetical head is honest, and the
    list is rebuilt when they land.
    """
    cities = _real_cities()
    got = cap(cities, active=None, times={})
    assert got["capped"] is True
    assert got["names"] == [c["name"] for c in cities[:CAP]]


def test_unreachable_cities_do_not_crowd_out_reachable_ones(cap):
    """MAX_MINUTES means no scheduled route. Those sort to the back, not to
    the front as a raw 65534 would against an undefined.
    """
    cities = _real_cities()
    times = {}
    for i, c in enumerate(cities):
        times[f"{c['lat']},{c['lon']}"] = 65534 if i < CAP else 50
    got = cap(cities, active={"slug": "__none__"}, times=times)
    assert not (set(got["slugs"]) & {c["slug"] for c in cities[:CAP]}), (
        "cities with no scheduled route were shown ahead of reachable ones")


# ------------------------------------------------------------ the footer ---

def _render_slice(start: str, end: str) -> str:
    """A region of `render()` cut at its own boundaries.

    Slicing `render()` rather than a named function is deliberate: the filtered
    branch has no name to import, which is exactly why it went unguarded.
    """
    body = APP[APP.index("function render(filter"):]
    body = body[:body.index("\n}\n") + 2]
    return body[body.index(start):body.index(end)]


@pytest.fixture(scope="module")
def filtered(node: str, tmp_path_factory):
    """The FILTERED branch of the list, run for real.

    `capCities` -- which the seven tests above exercise -- is the branch taken
    when the box is EMPTY. The branch taken while you type is a separate
    expression inside `render()` with its own `.slice(0, UNFILTERED_CAP)`, and
    nothing ran it: deleting that slice left every test in this file green
    while typing "a" built 1,097 rows, about 6,600 DOM nodes, per keystroke --
    the regression this file's docstring says the cap exists to prevent.
    """
    ranking = _render_slice("  const rankCity =", "  const list = document")
    src = (re.search(r"const UNFILTERED_CAP = \d+;", APP).group(0) + "\n"
           + APP[APP.index("const FOLD_DROP ="):APP.index("const cities =")]
           + "const inp = JSON.parse(process.argv[2]);\n"
           + "const cities = inp.cities;\n"
           + "for (const c of cities) c.key = fold(c.name);\n"
           + "const f = fold(inp.query);\n"
           + "const matched = f ? cities.filter((c) => (c.skey ?? c.key).includes(f)) : cities;\n"
           # capCities is the other branch; it must exist for the ternary to
           # parse, and a stub would let the filtered branch quietly fall
           # through to it, so it is the real one.
           + "let active = null;\nconst MAX_MINUTES = 65534;\n"
           + "function lookup() { return undefined; }\n"
           + _function("capCities") + "\n"
           + ranking
           + "process.stdout.write(JSON.stringify({rows: hits.length,"
             " capped, matched: matched.length,"
             " names: hits.slice(0, 5).map((c) => c.name)}));\n")
    path = tmp_path_factory.mktemp("filt") / "filt.cjs"
    path.write_text(src, encoding="utf-8")

    def call(query: str, cities=None):
        payload = {"query": query, "cities": cities if cities is not None else _real_cities()}
        done = subprocess.run([node, str(path), json.dumps(payload)],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    return call


def test_a_search_that_matches_almost_everything_is_capped_too(filtered):
    """"a" matches 1,097 of the real names. Uncapped, that is about 6,600 DOM
    nodes rebuilt on one keystroke.

    Mutation performed and reverted: delete `.slice(0, UNFILTERED_CAP)` from
    the `f ?` branch -> red here, green everywhere else in this file.
    """
    got = filtered("a")
    assert got["matched"] > CAP * 5, (
        f'"a" matches only {got["matched"]} of the real names; this test is no '
        "longer exercising a list long enough to need a cap")
    assert got["rows"] == CAP, (
        f'a search matching {got["matched"]} cities built {got["rows"]} rows')
    assert got["capped"] is True


def test_a_search_narrow_enough_to_fit_is_not_capped(filtered):
    """The cap must not be a floor, and `capped` must not be stuck true: a
    footer reading "showing the first 3 of 3 matches" is its own defect."""
    got = filtered("reykjav")
    assert got["rows"] == got["matched"] <= CAP, got
    assert got["capped"] is False, got


def test_the_filtered_cap_keeps_the_best_matches_not_the_first_ones(filtered):
    """A cap applied before the ranking would keep whatever the alphabet
    reached first. `lon` must still put London at the top of its 60."""
    got = filtered("lon")
    assert got["matched"] > 1, got
    assert got["names"][0] == "London", got


def test_both_branches_read_the_same_cap(filtered, cap):
    """Two literals would drift. The resting list and the searched list have
    to agree on how many rows a phone gets."""
    assert ".slice(0, UNFILTERED_CAP)" in _render_slice(
        "  const rankCity =", "  const list = document"), (
        "the filtered branch no longer reads UNFILTERED_CAP")
    assert filtered("a")["rows"] == len(cap(_real_cities())["names"]) == CAP


def test_the_footer_names_the_true_total_and_is_not_a_literal():
    """A capped list that does not say so has silently lost 1,404 cities.
    The count must come from the data: this page has shipped a hardcoded city
    count twice, and check_dist now refuses one in the copy.

    Mutation performed and reverted: delete the `if (capped)` block -> red.
    """
    body = _function("render")
    assert 'className = "listmore"' in body, (
        "a capped list says nothing about the cities it is not showing")
    block = body[body.index('className = "listmore"'):]
    block = block[:block.index("list.append(li);")]
    assert "matched.length" in block, (
        "the footer does not report the true total from the data")
    assert "fmtCount(" in block, "the total is printed without grouping"
    assert "Type to search" in block, (
        "the footer does not say how to reach the cities it is hiding")
    assert not re.search(r"\b(1464|1,464|553)\b", block), (
        "the footer hardcodes a city count")
    assert re.search(r"\.results \.listmore\{", HTML), (
        ".listmore has no style, so the footer reads as another clickable row")


def test_the_match_count_announced_is_the_true_one_not_the_capped_one():
    """The live region is a screen reader's only channel for "your query
    matched nothing". Announcing the capped count would say "60 matches" for a
    query that matched 1,097.

    Mutation performed and reverted: `matched.length` -> `hits.length` in the
    announce -> red.
    """
    body = _function("render")
    # Sliced rather than matched against one expression's exact shape: C17-5
    # split the single `n` into a city count and an airport count so the
    # announcement could name what it was counting, and the old regex went
    # red for a rename. The invariant is what it always was -- the capped
    # view must not reach the live region -- and it is now asserted over the
    # whole block, which the regex was not.
    at = body.index("  if (f) {\n")
    block = body[at:body.index("\n  }", at)]
    # Comments stripped before asserting. The first version of this check went
    # red against correct code because the comment explaining the invariant
    # said "not hits.length" -- prose satisfying, or here defeating, an
    # assertion about code. The repo has the mirror of this bug too: a guard
    # whose window shrank enough to pass when a comment was deleted with it.
    block = re.sub(r"//[^\n]*", "", block)
    assert "announce(" in block, "the announce block moved"
    assert "matched.length" in block, (
        "the live region no longer counts the cities that actually matched")
    assert "hits.length" not in block, (
        "the live region announces hits.length, which is the capped view, not "
        "the number of cities that actually matched")


def test_the_empty_state_tests_the_true_match_set():
    """`hits` is capped and `matched` is not. Testing `hits` for emptiness is
    right today only because a cap never empties a non-empty list -- but it is
    the wrong variable and would be wrong the moment the cap changes shape."""
    body = _function("render")
    assert "if (f && !matched.length && !apHits.length)" in body


def test_searching_matches_the_country_as_well_as_the_name():
    """At 1,464 rows you cannot scroll to "the Japanese ones"; you have to be
    able to type it.

    Mutation performed and reverted: filter on `c.key` -> red.
    """
    body = _function("render")
    assert "c.skey ?? c.key" in body, (
        "the filter matches the city name only")
    # Anchored on `c.skey`, not on `for (const c of cities) {`: the page has
    # more than one loop over `cities` now (C17-1 added the disambiguation
    # grouping above this one), and the first match was the wrong block.
    # Widened rather than relaxed -- the assertion below is unchanged.
    at = APP.index("c.skey =")
    keys = APP[APP.rindex("for (const c of cities) {", 0, at):]
    keys = keys[:keys.index("\n}") + 2]
    assert "countryName(c.country)" in keys, (
        "the search key carries the ISO-2 code but not the country's name")


def test_the_search_key_is_built_below_countryname():
    """`const countryName` is in its temporal dead zone until its own line.
    Building the keys above it throws ReferenceError at module load, boot.js
    turns that into body.fatal and the whole rail is display:none -- a blank
    page with no console error left to find. CLAUDE.md records three of these.
    `node --check` passes it happily, so this is the only thing that catches it.

    Mutation performed and reverted: move the key loop above the countryName
    IIFE -> red.
    """
    assert APP.index("const countryName = (() => {") < APP.index("c.skey = where"), (
        "the search keys are built before countryName is initialised; this is "
        "a ReferenceError at module load and a blank page")


def test_the_keystroke_handler_is_coalesced_to_one_render_per_frame():
    """Mutation performed and reverted: call render() directly from the input
    handler -> red.
    """
    block = APP[APP.index('$("q").addEventListener("input"'):]
    block = block[:block.index("\n});") + 4]
    assert "requestAnimationFrame" in block, (
        "every keystroke rebuilds the list synchronously")
    assert "cancelAnimationFrame" in block, (
        "queued renders are not cancelled, so a fast typist still pays for "
        "every intermediate list")


def test_the_city_count_in_the_page_is_grouped():
    """It was String(meta.origins.length): "553" reads fine and "1464" reads
    as a year. Every other number on the page is grouped."""
    assert 'fmtCount(meta.origins.length)' in APP
    assert "toLocaleString" in APP


# --------------------------------------- the debounce must not leak staleness ---

def test_enter_and_arrowdown_flush_the_pending_render_first():
    """The debounce introduced a real regression, caught by the deploy gate.

    The keydown handler decides what Enter means by READING THE RENDERED LIST:
    a first row means "depart from that city", no row means "search this as an
    address". With the render deferred to the next frame, typing an address and
    pressing Enter in the same tick found the list built for the PREVIOUS query
    and clicked its first row -- so the page departed from an unrelated city
    instead of searching. `browser_verify.sh` types and presses Enter in one
    tick; so does a fast typist.

    Mutation performed and reverted: delete the `flushRender()` call from the
    keydown handler -> red here, and red on the live address-search check.
    """
    block = APP[APP.index('$("q").addEventListener("keydown"'):]
    block = block[:block.index("\n});") + 4]
    assert "flushRender()" in block, (
        "the keydown handler reads the results list without flushing the "
        "debounced render, so Enter can act on a list built for an earlier "
        "query")
    # ...and it must happen BEFORE the list is read, not after.
    assert block.index("flushRender()") < block.index('querySelector("button[data-slug]'), (
        "flushRender runs after the list is read, which is no flush at all")
    for key in ('"Enter"', '"ArrowDown"'):
        assert key in block[:block.index("flushRender()") + 120], (
            f"{key} does not flush, and it reads the list")


def test_escape_cancels_the_pending_frame_rather_than_racing_it():
    """Escape clears the box and renders. A frame queued by the keystroke
    before it lands a moment later and re-filters for the query Escape has
    just cleared.
    """
    block = APP[APP.index('$("q").addEventListener("keydown"'):]
    block = block[:block.index("\n});") + 4]
    esc = block[block.index('=== "Escape"'):]
    assert "cancelAnimationFrame" in esc, (
        "Escape does not cancel the pending render, so the cleared list is "
        "re-filtered a frame later")


def test_flushrender_is_a_real_flush_not_a_cancel():
    """Cancelling without rendering would leave the list describing an older
    query forever, which is worse than the staleness it was meant to fix.
    """
    body = _function("flushRender")
    assert "cancelAnimationFrame" in body and "render(" in body
    assert "renderFrame = 0" in body, (
        "the frame id is not cleared, so the next flush is a no-op")
