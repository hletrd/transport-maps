"""Two obligations the page owes whoever opens it, checked in the markup.

Both were found by the cycle-4 document-specialist against the primary sources,
and both are contract terms rather than matters of taste, so they get a gate.

1. OpenStreetMap. The OSMF Attribution Guideline says, verbatim: "The
   attribution format should not require individuals to interact with the map
   or produced work to see the attribution." The page set
   `attributionControl: false` and put its only credit inside
   `<details id="key">`, which has no `open` attribute and which app.js closes
   outright on a phone. The three collapse behaviours the guideline does permit
   (dismiss, on map interaction, after five seconds) all presuppose the credit
   was shown first.
   https://osmfoundation.org/wiki/Licence/Attribution_Guidelines

2. Google Analytics. Its terms, section 7: "You must post a Privacy Policy ...
   You must disclose the use of Google Analytics, and how it collects and
   processes data", which a prominent link to the partner-sites page satisfies.
   `grep -rni privacy web/` returned nothing at all.
   https://marketingplatform.google.com/about/analytics/terms/us/
"""

import re
from html.parser import HTMLParser

from transport_maps import config

HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


def _function(name: str) -> str:
    """The verbatim source of a top-level function, by brace matching."""
    start = APP.index(f"function {name}(")
    i, depth = APP.index("(", start), 0
    while True:
        if APP[i] == "(":
            depth += 1
        elif APP[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    i = APP.index("{", i)
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError(f"function {name} is not brace-balanced")

OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright"
GA_PARTNERS = "https://www.google.com/policies/privacy/partners/"


class _Finder(HTMLParser):
    """Records, for each element carrying one of `wanted`, the open <details>
    ancestors it sits inside. A `<details>` without `open` hides its body until
    someone clicks it, which is the interaction the guideline forbids."""

    def __init__(self, wanted: set[str]):
        super().__init__(convert_charrefs=True)
        self.wanted = wanted
        self.stack: list[tuple[str, bool]] = []
        self.found: dict[str, list[str]] = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "details":
            self.stack.append((a.get("id") or "details", "open" in a))
        cls = set((a.get("class") or "").split())
        for w in self.wanted & cls:
            self.found[w] = [name for name, is_open in self.stack if not is_open]

    def handle_endtag(self, tag):
        if tag == "details" and self.stack:
            self.stack.pop()


def _closed_ancestors(class_name: str) -> list[str]:
    f = _Finder({class_name})
    f.feed(HTML)
    assert class_name in f.found, f"no element with class {class_name!r} in index.html"
    return f.found[class_name]


def test_the_openstreetmap_credit_needs_no_interaction_to_see():
    assert _closed_ancestors("legend-credit") == [], (
        "the credit sits inside a <details> that is not open, so it cannot be seen "
        "without interacting with the page -- which the OSMF guideline forbids")


def test_the_credit_says_openstreetmap_and_links_to_the_copyright_page():
    i = HTML.index('class="legend-credit"')
    line = HTML[i:i + 400]
    assert "OpenStreetMap" in line and "contributors" in line
    assert OSM_COPYRIGHT in line


def test_the_credit_lives_in_the_block_the_design_policy_keeps_visible():
    """CLAUDE.md: "The legend is always visible." That is the only block on the
    page with that guarantee, so it is the only safe home for the credit."""
    legend = HTML[HTML.index('<div class="legend">'):]
    legend = legend[:legend.index("</div>\n\n  <div class=\"legs\"")]
    assert 'class="legend-credit"' in legend

    # ...and the folded phone sheet must not hide it. The rule is a chain of
    # :not()s; the credit has to be in that chain.
    fold = next(ln for ln in HTML.splitlines() if ".rail.folded .legend >" in ln)
    assert ":not(.legend-credit)" in fold, (
        "the folded sheet hides everything in .legend but the listed classes")


def test_the_page_posts_a_privacy_policy():
    assert 'id="privacy"' in HTML, "no privacy section"
    assert _closed_ancestors("legend-credit") == []
    assert 'href="#privacy"' in HTML, "nothing visible links to it"


def test_the_privacy_policy_discloses_analytics_and_links_googles_own_page():
    body = HTML[HTML.index('id="privacy"'):]
    body = body[:body.index("</details>")]
    assert "Google Analytics" in body
    assert GA_PARTNERS in body, (
        "GA's terms are satisfied by a prominent link to the partner-sites page")
    # The other recipient of visitor data, named in the same place.
    assert "Nominatim" in body


def test_the_privacy_policy_describes_what_the_page_actually_does():
    """A policy that overstates or understates is worse than none.

    Each claim below is pinned to the code that makes it true, so a change on
    one side cannot leave the other lying.
    """
    body = HTML[HTML.index('id="privacy"'):]
    body = body[:body.index("</details>")]

    # Geolocation is opt-in and the POSITION never leaves the browser.
    assert "never sent to this site or to anyone else" in body
    assert "navigator.geolocation.getCurrentPosition" in APP
    assert "geolocation" not in APP.split("const NOMINATIM")[1][:2000], (
        "the policy says the position is never sent; something sends it")
    # ...but what it DERIVES does leave, and the policy said otherwise.
    # "Show my location" picks the nearest departure city and calls
    # paintOrigin, which calls syncPermalink, which writes ?from=<slug> into
    # the address bar -- and the address bar is what GA4 records as
    # page_location. The old wording, "it is not sent anywhere", was true of
    # the coordinates and false of the answer. Both halves have to be said.
    assert "address bar" in body and "page location" in body, (
        "the locate paragraph no longer says the chosen city reaches the "
        "address bar, and therefore the analytics page path")
    assert 'syncPermalink' in APP

    # The setting called "Name the place under the cursor" has to stop the
    # thing the policy says it stops. namePlaces gated only the LOCAL
    # places.json lookups, so a visitor who had switched naming off still sent
    # every clicked coordinate to Nominatim while the page promised in writing
    # that unticking the box "stops the second kind entirely".
    assert "stops the" in body and "entirely" in body
    assert re.search(r"if \(namePlaces\) reverseGeocode\(", APP), (
        "the privacy policy promises the setting stops the click "
        "reverse-geocode; reverseGeocode is called without consulting it")
    # Nothing else may call it unconditionally either.
    for m in re.finditer(r"^[^\n/]*\breverseGeocode\(", APP, re.M):
        line = APP[APP.rfind("\n", 0, m.start()) + 1:APP.find("\n", m.start())]
        assert "async function" in line or "namePlaces" in line, (
            f"reverseGeocode is called without the setting: {line.strip()!r}")

    # localStorage holds preferences only: the ramp name and two booleans.
    #
    # This clause used to name "lock-north" and "show-places", which are the
    # CHECKBOX ELEMENT IDS, not storage keys -- the real keys are "ramp",
    # "lockNorth" and "namePlaces" -- and it then asserted only that "ramp"
    # was among whichever of the three happened to appear anywhere in app.js.
    # It bounded nothing: adding localStorage.setItem("visitor-id", ...) made
    # the posted privacy policy false and left all 460 tests green.
    #
    # Derive the set the page actually writes and require the policy to be
    # true of exactly that set. Mutation: add a setItem with a fourth key.
    assert "local storage" in body
    written = set(re.findall(r'localStorage\.setItem\(\s*"([^"]+)"', APP))
    written |= set(re.findall(r'store\.set\(\s*"([^"]+)"', APP))
    # ...and the PROSE has to keep up with the set, not just the set with the
    # code. Removing "your ocean colour" from the policy left this test green
    # until this assertion existed: the key check alone cannot tell whether the
    # sentence still describes what is stored.
    for key, phrase in (("ramp", "colour scheme"), ("ocean", "ocean colour"),
                        ("lockNorth", "Settings switches"),
                        ("namePlaces", "Settings switches"),
                        ("carryOn", "carry-on choice")):
        if key in re.findall(r'localStorage\.setItem\(\s*"([^"]+)"', APP) + \
                   re.findall(r'store\.set\(\s*"([^"]+)"', APP):
            assert phrase in body, (
                f"the page stores {key!r} and the privacy policy does not say so "
                f"(expected to find {phrase!r})")

    assert written == {"ramp", "ocean", "lockNorth", "namePlaces", "carryOn"}, (
        "the page writes a localStorage key the privacy policy does not "
        f"account for: {sorted(written)}. Update both, or neither.")
    # ...and every key it writes it also reads back, so none is write-only
    # state a visitor cannot see the effect of.
    read = set(re.findall(r'localStorage\.getItem\(\s*"([^"]+)"', APP))
    read |= set(re.findall(r'store\.get\(\s*"([^"]+)"', APP))
    assert written <= read, f"written but never read: {sorted(written - read)}"

    # Nominatim is never called per keystroke.
    assert "never sent as you type" in body or "never as you type" in body


# --- U16: one live region, and it must be displayed when it is written ------

def test_only_one_live_region_exists():
    """T4 moved the page's live region into #status and left #pins as one.

    With two, an origin switch announced the whole route block up to six times
    and every click announced twice -- which is the same as announcing nothing.
    """
    import re
    live = re.findall(r'<[^>]*\baria-live="[^"]*"[^>]*>', HTML)
    assert live == [], f"aria-live outside the single role=status region: {live}"
    assert 'id="status" role="status"' in HTML, "the one live region is gone"


def test_the_live_region_is_not_hidden_by_the_folded_sheet():
    """#status is a direct child of .reading and is not .legend, so the folded
    rule matched it: the region was display:none exactly when a phone user had
    folded the sheet to see the globe and then tapped it. ARIA does not present
    changes to a hidden region, and the click handler wrote it BEFORE the
    reveal, so the reveal produced no mutation either."""
    fold = [ln for ln in HTML.splitlines() if ".rail.folded .reading >" in ln]
    assert any("#status{display:block}" in ln for ln in fold), (
        "nothing keeps #status displayed while the sheet is folded")
    assert any(":not(#status)" in ln for ln in fold), (
        "the blanket folded rule still matches #status")


def test_the_announcement_follows_the_reveal():
    """Writing a hidden region and then revealing it announces nothing: the
    reveal is not a mutation of the region's content."""
    # `map.on("click"` used to be one of these. It is not a separate path any
    # more: the click body became setDestination(), which the click handler and
    # the new Enter-key handler both call, so the ordering is enforced in one
    # place instead of two that could drift. Both entry points are asserted to
    # go through it, so widening the list back out cannot be forgotten.
    # Bounded by brace matching, not by slicing to the first `renderLegs()`.
    # That marker stopped at whichever call came first, so when
    # setDestination grew an early-return branch that calls renderLegs() to
    # tear down the previous destination, the window ended before
    # unfoldSheet() and the search raised ValueError on a page whose ordering
    # was still correct.
    for fn in ("commitDestination", "setDestination"):
        body = _function(fn)
        assert "unfoldSheet()" in body and "announceReading(" in body, (
            f"{fn} no longer both reveals and announces")
        assert body.index("unfoldSheet()") < body.index("announceReading("), (
            f"{fn} announces before it reveals")
    assert "setDestination(e.lngLat.lat, e.lngLat.lng, e.point)" in APP, (
        "the click handler no longer goes through setDestination")
    assert "setDestination(c.lat, c.lng, point)" in APP, (
        "the keyboard handler no longer goes through setDestination")


# --- U27: WCAG 2.2 SC 1.4.11, the boundary that identifies a control --------

def _luminance(hex_colour: str) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _token(name: str) -> str:
    import re
    m = re.search(rf"{name}:\s*(#[0-9a-fA-F]{{6}})", HTML)
    assert m, f"{name} not found in index.html"
    return m.group(1)


def test_the_control_boundary_token_clears_three_to_one_on_every_ground():
    """--line measures 1.30:1 on --surface, 1.21:1 on --surface-2 and 1.40:1
    over space, so the zoom buttons, the compass, the search box and the
    buttons had boundaries that are, measurably, not there. SC 1.4.11 wants
    3:1 for the visual information required to identify a control.

    --line itself is unchanged: it draws dividers and panel edges, which the
    criterion does not cover.
    """
    ctl = _token("--line-ctl")
    for ground in ("--surface", "--surface-2", "--bg"):
        assert _contrast(ctl, _token(ground)) >= 3.0, (
            f"--line-ctl {ctl} is {_contrast(ctl, _token(ground)):.2f}:1 on {ground}")


def test_every_interactive_control_uses_it():
    """A control that keeps --line has a boundary nobody can see."""
    import re
    # ^ anchored: ".qrow .btn{flex:none}" is a layout tweak, not the base rule.
    for selector in (r"#q\{", r"\.mapbtn\{", r"\.compass\{", r"\.btn\{"):
        m = re.search(r"^" + selector + r"[^}]*\}", HTML, re.S | re.M)
        assert m, selector
        block = m.group(0)
        assert "border:1px solid var(--line-ctl)" in block, (
            f"{selector} still draws its boundary with --line: {block[:120]}")


# --- U10 / T26: hierarchy, the empty state, and something to navigate by ----

def test_the_page_has_landmarks_with_accessible_names():
    """One heading and two landmarks left nothing to navigate the page by."""
    import re
    assert re.search(r'<main aria-label="[^"]+"', HTML), "no named main landmark"
    assert re.search(r'<aside class="rail" aria-labelledby="[^"]+"', HTML), "the rail is not a landmark"
    assert re.search(r'<section class="reading" aria-labelledby="[^"]+"', HTML), (
        "the readout is not a landmark")
    assert "<header class=\"mast\">" in HTML


def test_the_heading_outline_is_one_h1_and_named_sections():
    import re
    heads = re.findall(r"<h([123])[^>]*>(.*?)</h\1>", HTML, re.S)
    levels = [int(lv) for lv, _ in heads]
    assert levels.count(1) >= 1, heads
    # Every landmark that names itself by id must have a heading with that id.
    for m in re.finditer(r'aria-labelledby="([\w-]+)"', HTML):
        assert f'id="{m.group(1)}"' in HTML, f"aria-labelledby={m.group(1)} names nothing"


def test_the_idle_readout_is_not_a_fifty_pixel_em_dash():
    """At rest the largest element on the page was an em dash: 50px of
    punctuation, the first thing a first-time visitor saw.

    Asserted on the ELEMENT's content, not on one exact spelling of the tag:
    the previous form pinned `<p class="v" id="time"></p>` byte for byte, so
    it failed when a loading placeholder was added -- which serves the same
    purpose better -- while still passing for any dash written any other way.
    """
    m = re.search(r'<p class="v" id="time">(.*?)</p>', HTML, re.S)
    assert m, "#time is not where the readout expects it"
    inner = m.group(1)
    assert "\u2014" not in inner and "&mdash;" not in inner, (
        f"the dash is back in the markup: {inner!r}")
    # Empty, or a placeholder that says something. Never punctuation alone.
    assert not inner.strip("\u2014-\u2013 \t") or "waiting" in inner, inner
    assert "IDLE_TIME" in APP and 'class="idle"' in APP
    # ...and the height is reserved, so the first reading does not shift the page.
    assert "min-height:50px" in HTML


def test_one_quantity_is_not_split_across_two_colours():
    """50px in --text beside 16px in --text-2 read as a number and a separate
    piece of metadata. CLAUDE.md: carry hierarchy with weight and colour --
    within one figure that means one colour."""
    import re
    m = re.search(r"\.reading \.v small\{([^}]*)\}", HTML)
    assert m, "the unit rule is gone"
    assert "color:inherit" in m.group(1), m.group(1)
    assert "font-size:0.42em" in m.group(1), "the unit must scale with the figure, not stand apart"


def test_the_route_panel_puts_the_answer_above_the_instructions():
    body = HTML[HTML.index('<details class="panel" id="route">'):]
    body = body[:body.index("</details>")]
    assert body.index('id="pins"') < body.index('id="route-hint"'), (
        "eighty words of instructions still outrank the answer")


def test_a_reverse_geocoded_address_never_reaches_the_address_bar() -> None:
    """`?label=` is part of the page location the analytics tag reports.

    A label from this site's own gazetteer is a place name ("near Xanthi"), and
    the privacy text has always covered that. A label from Nominatim's reverse
    geocoder, for a click inside a city, is a street address -- and it was
    written into the address bar exactly the same way, so it reached Google as
    `page_location` while the privacy text disclosed only the coordinate.

    Two guards, because there are two paths: app.js must not write one, and the
    gtag bootstrap must strip one that arrives in the incoming URL (an older
    client's link, or a hand-written one).

    Mutations performed and reverted: drop `!pinB.geocoded` from syncPermalink
    -> red; drop the searchParams.delete('label') from the bootstrap -> red.
    """
    sync = APP[APP.index("function syncPermalink()"):]
    sync = sync[:sync.index("\n}\n")]
    sync = re.sub(r"//[^\n]*", "", sync)          # comments cannot satisfy this
    put = re.search(r'put\("label",(.*?)\);', sync, flags=re.S)
    assert put, "syncPermalink no longer serialises a label"
    assert "geocoded" in put.group(1), (
        "syncPermalink writes a reverse-geocoded label into the address bar, "
        "which is what the analytics tag reports as the page location")

    boot = re.search(r"<script>(?![^<]*ld\+json)(.*?)</script>", HTML, flags=re.S)
    assert boot and "gtag(" in boot.group(1), "the gtag bootstrap moved"
    src = boot.group(1)
    assert "page_location" in src, (
        "gtag reports location.href verbatim, so a label in the incoming URL "
        "goes to Google unchanged")
    assert re.search(r"delete\(\s*['\"]label['\"]\s*\)", src), (
        "the gtag bootstrap sets page_location without removing ?label= from it")


def test_the_privacy_text_says_the_address_is_kept_out() -> None:
    """A fix nobody is told about is half a fix: the section that describes the
    address bar must say what is deliberately absent from it."""
    start = HTML.index('<h3 id="privacy">')
    # To the next <h3>, or to the end of the document if it is the last.
    nxt = HTML.find("<h3", start + 1)
    section = HTML[start: nxt if nxt != -1 else len(HTML)]
    assert "reverse geocoding" in section.lower() or "reverse-geocod" in section.lower()
    assert "gazetteer" in section.lower(), (
        "the privacy section does not distinguish a gazetteer place name, which "
        "does go into the address bar, from a geocoded street address, which "
        "does not")


# --- C16-6: the compliance page's pointer at the data credits ---------------
#
# The licence page under web/vendor/licences/ is the one document a visitor
# reaches when they want to know who the data belongs to, and it ends by
# pointing back at the map's own source list. Cycle 15 aimed that pointer at
# `../../#key` and verified only that the id exists. It does -- and following
# the link still shows no credits, because `#key` IS the folded panel.
#
# HTML's ancestor revealing algorithm, which scrolling to a fragment runs on
# the target, walks the target and its ancestors and appends a <details> to
# the reveal list only when the node it is looking at "is slotted into the
# second slot of a details element which does not have an open attribute" --
# and what it appends is that node's PARENT. A target that IS the <details> is
# slotted into nothing, so the algorithm reveals nothing. Nor is there a
# fallback: `<details id="key">` has no `open` attribute, `grep -n hash
# web/app.js` returns nothing at all, and app.js's one anchor handler is a
# click listener, which a cross-document arrival never fires.
#
# Measured in Chromium against this page's own markup, not inferred:
# `...#key`     -> document.getElementById("key").open === false
# `...#credits` -> .open === true, and #credits has a layout box.
# (A prose summary of the spec asserted the opposite -- that running the
# algorithm on a closed <details> opens it. The quoted steps and the browser
# both say otherwise. Hence the measurement.)
#
# https://html.spec.whatwg.org/multipage/interaction.html#ancestor-revealing-algorithm

LICENCES = config.ROOT / "web" / "vendor" / "licences"

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "source", "track", "wbr"}


def _hidden_state(a: dict[str, str | None]) -> str | None:
    """The `hidden` attribute's state, or None when the attribute is absent.

    Of the two states only Hidden Until Found is revealed by the algorithm.
    The presence test is on the KEY and never on the value: HTMLParser hands a
    bare boolean `hidden` back as `("hidden", None)`, so an `is not None` test
    on the value silently passes every plainly hidden element -- which is what
    the first draft of this class did, and a synthetic `<div hidden>` case
    caught it.
    """
    if "hidden" not in a:
        return None
    return "until-found" if (a["hidden"] or "").strip().lower() == "until-found" else "hidden"


class _Reachability(HTMLParser):
    """For every id in a document, whether a fragment aimed at it is shown.

    Models the two clauses of the ancestor revealing algorithm rather than
    guessing at them:

    * a closed `<details>` STRICTLY ABOVE the target, reached through its body
      slot, is opened -- so being inside one is fine;
    * the target's own `hidden` attribute, or an ancestor's, is undone only in
      the `until-found` state;
    * and the case this section exists for: when the target itself is the
      closed `<details>`, it is slotted into nothing, so nothing opens.

    An id inside a `<summary>` sits in the first slot and so triggers no
    reveal, but a summary renders while its panel is folded, so it is shown
    either way and needs no special case here.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        # id -> (tag, list of reasons it would still not be shown)
        self.ids: dict[str, tuple[str, list[str]]] = {}

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id") and a["id"] not in self.ids:
            hidden = [
                f"<{t} hidden> is not in the Hidden Until Found state, so the "
                f"algorithm does not reveal it"
                for t, x in [(tag, a), *self.stack]
                if _hidden_state(x) == "hidden"
            ]
            if tag == "details" and "open" not in a:
                hidden.append(
                    "the target IS a <details> with no open attribute, and the "
                    "ancestor revealing algorithm opens only a details the "
                    "target is slotted INTO, never the target itself")
            self.ids[a["id"]] = (tag, hidden)
        if tag not in _VOID:
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return


class _Links(HTMLParser):
    """Every `href` in a document, in source order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.hrefs.append(a["href"])


def _cross_document_fragments() -> list[tuple[str, str, str]]:
    """(licence file, href, fragment) for every href in web/vendor/licences/
    that carries a fragment and resolves to a DIFFERENT document."""
    out: list[tuple[str, str, str]] = []
    for path in sorted(LICENCES.rglob("*.html")):
        p = _Links()
        p.feed(path.read_text(encoding="utf-8"))
        for href in p.hrefs:
            if "#" not in href or href.startswith(("http:", "https:", "mailto:")):
                continue
            target, _, frag = href.partition("#")
            if not frag or not target:      # same-document fragment
                continue
            dest = (path.parent / target).resolve()
            if dest.is_dir():
                dest = dest / "index.html"
            out.append((path.name, href, frag))
            assert dest.is_file(), f"{path.name}: {href!r} resolves to nothing at {dest}"
            assert dest == (config.ROOT / "web" / "index.html").resolve(), (
                f"{path.name}: {href!r} aims at {dest}, which this gate does not model")
    return out


def test_the_licence_page_points_at_a_fragment_the_browser_will_reveal():
    """A pointer at the data credits that lands on a folded panel is no pointer.

    MUTATION PERFORMED, with the result as measured -- not as estimated.

    1. Restore cycle 15's target, `<a href="../../#key">`, in
       web/vendor/licences/index.html -- the id exists, which is all the
       cycle-15 ledger checked, so the old gate stayed green on it:
       **1 failed, 19 passed.** The failure names the href and the reason:
       "lands on <details id='key'> and the visitor still sees nothing".

    The mutation did not come back green.
    """
    links = _cross_document_fragments()
    assert links, (
        "no cross-document fragment link found under web/vendor/licences/ -- "
        "this gate would pass vacuously; check the parse, not the page")

    r = _Reachability()
    r.feed(HTML)
    for name, href, frag in links:
        assert frag in r.ids, (
            f"{name}: {href!r} names #{frag}, which is not an id in web/index.html")
        tag, blockers = r.ids[frag]
        assert not blockers, (
            f"{name}: {href!r} lands on <{tag} id={frag!r}> and the visitor "
            f"still sees nothing -- {'; '.join(blockers)}")


def test_the_credited_fragment_is_the_source_list_and_not_merely_reachable():
    """Reachable is not the same as right: #credits has to be the element the
    page fills with the data sources, inside the panel the link names.

    MUTATIONS PERFORMED, with the results as measured.

    1. Drop the id from `<p class="src" id="credits">`: **red** -- and the
       gate above goes red with it, since the fragment then names nothing.
    2. Move #credits out of the panel, onto a <p> in .keys: **red** here,
       GREEN above. That is the point of having two: the fragment stays
       reachable while the link text, "Sources and method", starts lying.
    3. Rename the `$("credits")` lookup in app.js: **red**. The paragraph is
       empty in the markup, so without this the gate would accept an id on a
       <p> that nothing ever fills.

    No mutation came back green.
    """
    assert 'id="credits"' in HTML, "the credits paragraph is gone from index.html"
    panel = HTML[HTML.index('<details class="panel" id="key">'):]
    panel = panel[:panel.index("</details>")]
    assert 'id="credits"' in panel, (
        "#credits left the Sources and method panel; the licence page's link "
        "text names that panel")
    assert re.search(r'\$\(\s*"credits"\s*\)', APP), (
        "nothing in app.js writes the credits paragraph any more")
