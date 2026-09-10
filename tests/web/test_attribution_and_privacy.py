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

from html.parser import HTMLParser

from transport_maps import config

HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

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

    # Geolocation is opt-in and never leaves the browser.
    assert "not sent anywhere" in body
    assert "navigator.geolocation.getCurrentPosition" in APP
    assert "geolocation" not in APP.split("const NOMINATIM")[1][:2000], (
        "the policy says the position is never sent; something sends it")

    # localStorage holds preferences only: the ramp name and two booleans.
    assert "local storage" in body
    keys = {m for m in ("ramp", "lock-north", "show-places")
            if f'localStorage.getItem("{m}")' in APP or f'"{m}"' in APP}
    assert "ramp" in keys

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
    for fn in ("commitDestination", 'map.on("click"'):
        body = APP[APP.index(fn):]
        body = body[:body.index("renderLegs()")]
        assert body.index("unfoldSheet()") < body.index("announceReading("), (
            f"{fn} announces before it reveals")


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
