"""CLAUDE.md's standing design policy, enforced instead of remembered.

The policy has been in CLAUDE.md since cycle 2 and has held for eleven cycles
on attention alone. Cycle 11's test engineer mutated the page and ran the gate
that actually runs before a deploy -- `page_gate()` in scripts/deploy_verify.sh
-- against each mutation. Every one shipped green:

    letter-spacing:.08em added ................ 265 passed
    text-transform:uppercase added ............ 265 passed
    font-variant-numeric:tabular-nums added ... 265 passed
    --bg flipped to a light sepia ............. 265 passed
    --font swapped to a serif stack, plus a
      Google Fonts <link> ..................... 265 passed
    <link href="./vendor/fonts.css"> deleted .. 265 passed

The sepia flip left --text at 1.06:1 on --surface and still passed the suite's
only contrast assertion, which covers --line-ctl alone. Deleting the font
stylesheet makes Plex fall back silently, which is the exact failure CLAUDE.md
gives as the reason the face is self-hosted.

tests/web/ is run as a whole directory by page_gate(), so this file is on the
deploy path without a script edit.

Every assertion here was mutation-verified red before it was committed; the
mutation that reddens each one is named in its own docstring.
"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"


# ---- reading the page without reading its commentary ----
#
# CLAUDE.md's bans are about what the page DOES, and this repository writes
# long explanatory comments that quote the very declarations they forbid --
# index.html carries "sentence case, no letter-spacing" in a comment, and this
# file's own docstring names all five banned strings. A scanner that matched
# raw text would fail on the prose and, worse, could be satisfied by moving a
# real declaration into a comment. Comments and string literals come out first.

def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


def _strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", " ", html, flags=re.S)


@pytest.fixture(scope="module")
def html() -> str:
    return (WEB / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def markup(html: str) -> str:
    """The page with its comments removed -- what a browser is actually given."""
    return _strip_html_comments(html)


@pytest.fixture(scope="module")
def css(markup: str) -> str:
    """Every <style> block, comments stripped."""
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", markup, flags=re.S | re.I)
    assert blocks, "index.html has no <style> block; this gate would pass vacuously"
    return _strip_css_comments("\n".join(blocks))


@pytest.fixture(scope="module")
def script() -> str:
    """app.js with its comments stripped.

    A banned declaration is as effective written through element.style or a
    template literal as it is in the stylesheet, and app.js is where the page's
    dynamic styling lives.
    """
    src = (WEB / "app.js").read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", " ", src, flags=re.M)
    return src


def _declarations(css: str, prop: str) -> list[str]:
    """Every value the stylesheet gives `prop`, normalised."""
    out = []
    for m in re.finditer(rf"(?<![\w-]){re.escape(prop)}\s*:\s*([^;{{}}]+)", css):
        out.append(" ".join(m.group(1).split()).lower())
    return out


# ---- the four bans ----

def test_letter_spacing_is_never_set(css, script):
    """CLAUDE.md: "letter-spacing stays at its default everywhere. Do not set
    it -- not on headings, not on labels, not on small caps."

    Reddens on: adding `letter-spacing:.08em` to any rule, or a
    `style.letterSpacing =` write in app.js.
    """
    found = _declarations(css, "letter-spacing")
    assert not found, f"letter-spacing is set in index.html: {found}"
    assert "letterspacing" not in script.lower().replace("-", ""), \
        "app.js writes letter-spacing; CLAUDE.md fixes it at its default"


def test_nothing_is_upper_cased(css, script):
    """CLAUDE.md: "No text-transform: uppercase. Small all-caps micro-labels
    ("DEPARTURE", "ROUTE") are the generic-dashboard tell."

    `font-variant: small-caps` reaches the same look by another route and is
    banned by the same sentence, so it is checked here too.

    Reddens on: adding `text-transform:uppercase` to any rule, or a
    `style.textTransform =` write in app.js.
    """
    bad = [v for v in _declarations(css, "text-transform") if v not in ("none", "inherit")]
    assert not bad, f"text-transform is used in index.html: {bad}"
    assert "texttransform" not in script.lower().replace("-", ""), \
        "app.js writes text-transform; CLAUDE.md bans uppercasing"
    caps = [v for v in _declarations(css, "font-variant") if "small-caps" in v]
    assert not caps, f"small-caps reaches the banned look by another route: {caps}"


def test_figures_are_proportional(css, script):
    """CLAUDE.md: "No font-variant-numeric: tabular-nums. Monospaced digits
    read as a terminal, not a chart... if a column needs aligning, set a width."

    The page follows the advice in three places -- `.reach dd`, `.results
    .rowtime` and `.leg .t` all set a width -- and each carries a comment
    saying why. Those comments are why this scanner strips them first.

    Reddens on: adding `font-variant-numeric:tabular-nums` to any rule.
    """
    bad = [v for v in _declarations(css, "font-variant-numeric") if v not in ("normal", "inherit")]
    assert not bad, f"font-variant-numeric is set in index.html: {bad}"
    for v in _declarations(css, "font-variant") + _declarations(css, "font-feature-settings"):
        assert "tabular" not in v and "tnum" not in v, f"tabular figures reached via: {v}"
    assert "tabular" not in script.lower(), "app.js asks for tabular figures"


def test_the_ground_is_near_black(css):
    """CLAUDE.md: "Dark theme. Near-black ground (--bg), not a light or sepia
    palette."

    The test engineer's sepia mutation is the reason this measures luminance
    rather than matching a hex: it flipped --bg to #f4ece0 and shipped green,
    and it left --text at 1.06:1 on --surface -- unreadable -- while the suite's
    only contrast assertion, which covers --line-ctl, stayed satisfied.

    Reddens on: flipping --bg, --surface or --surface-2 to a light value.
    """
    for name in ("--bg", "--surface", "--surface-2"):
        vals = _declarations(css, name)
        assert vals, f"{name} is not defined"
        lum = _luminance(vals[0])
        assert lum < 0.05, f"{name} is {vals[0]} (relative luminance {lum:.3f}); CLAUDE.md fixes a near-black ground"
    # ...and the body text must still be readable on it. This is the assertion
    # the sepia mutation actually needed: a light ground with the dark theme's
    # text is the failure, not the hex value on its own.
    ratio = _contrast(_declarations(css, "--text")[0], _declarations(css, "--surface")[0])
    assert ratio >= 4.5, f"--text on --surface is {ratio:.2f}:1, below WCAG 2.2 AA's 4.5:1"


# ---- the typeface ----

def test_the_page_is_set_in_self_hosted_plex(css, markup):
    """CLAUDE.md: "Typeface: IBM Plex Sans. Sans-serif throughout, self-hosted
    in web/vendor/. No serif faces, no webfont CDN (the CSP blocks external
    font hosts, and a face that silently falls back undoes the choice)."

    Three separate failures are checked, because the test engineer's mutations
    reached the same end by three routes: swapping --font, adding a CDN <link>,
    and deleting the stylesheet that loads the local face.

    Reddens on: any of those three.
    """
    font = _declarations(css, "--font")
    assert font, "--font is not defined"
    assert font[0].startswith('"ibm plex sans"'), \
        f'--font must lead with "IBM Plex Sans"; it is {font[0]}'
    for generic in ("serif", "monospace", "cursive", "fantasy"):
        # `sans-serif` ends in "serif"; match the family as a whole token.
        assert not re.search(rf"(?<![\w-]){generic}(?![\w-])", font[0]), \
            f"--font falls back to {generic}: {font[0]}"

    # The face must actually be loaded, and from this origin. nginx sends a CSP
    # that would block an external font host, so a CDN link is not merely
    # against policy -- it renders nothing and falls back in silence.
    assert re.search(r'<link[^>]+href="\./vendor/fonts\.css"', markup), \
        "the self-hosted face's stylesheet is not linked; Plex would fall back silently"
    assert (WEB / "vendor" / "fonts.css").is_file(), "web/vendor/fonts.css is missing"
    for m in re.finditer(r'<link[^>]+href="([^"]+)"', markup):
        href = m.group(1)
        assert "fonts.googleapis.com" not in href and "fonts.gstatic.com" not in href, \
            f"webfont CDN linked: {href}"
    assert "@import" not in css, "@import can pull a webfont host past the <link> scan"

    # Every face fonts.css names must be on disk. A @font-face pointing at a
    # file that is not shipped falls back exactly as silently as a CDN does.
    face_css = (WEB / "vendor" / "fonts.css").read_text(encoding="utf-8")
    srcs = re.findall(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", face_css)
    assert srcs, "vendor/fonts.css declares no font file"
    for src in srcs:
        assert (WEB / "vendor" / Path(src).name).is_file(), f"fonts.css names a missing file: {src}"


def test_no_element_is_left_to_a_browser_default_face(css, markup):
    """Sans-serif THROUGHOUT: an element the stylesheet never dresses gets the
    user agent's own family, and for <code>, <kbd>, <samp> and <pre> that
    family is monospace. A monospace run on a dark panel reads as a terminal,
    which is the tell the tabular-nums ban exists to prevent.

    index.html:979 shipped `<code>index.json</code>` in the UA default for ten
    cycles. It now carries weight instead of a face.

    Reddens on: adding a <code> or <pre> to the body without a font rule.
    """
    body = markup.split("<body", 1)[-1]
    for tag in ("code", "kbd", "samp", "pre", "tt"):
        if not re.search(rf"<{tag}[\s>]", body):
            continue
        # Some rule must set a face for it. Match a selector mentioning the
        # element and a font declaration inside that rule's block.
        pattern = rf"[^{{}}]*(?<![\w-]){tag}(?![\w-])[^{{}}]*\{{[^}}]*font(?:-family)?\s*:"
        assert re.search(pattern, css), \
            f"<{tag}> is used but no rule sets its font; it falls back to the UA's monospace"


# ---- the legend ----

def test_the_legend_is_never_folded_into_a_panel(markup):
    """CLAUDE.md: "The legend is always visible, never folded into a panel."

    <details> is the page's panel idiom and it is collapsible by definition, so
    the legend being inside one would make it foldable whatever the CSS said.

    Reddens on: moving #tints, #scale or #keys inside a <details>.
    """
    for block in re.findall(r"<details\b.*?</details>", markup, flags=re.S | re.I):
        for ident in ('id="tints"', 'id="scale"', 'id="keys"'):
            assert ident not in block, f"the legend's {ident} sits inside a <details>"


# ---- colour arithmetic, so the assertions above measure rather than eyeball ----

def _rgb(value: str) -> tuple[float, float, float]:
    v = value.strip().lstrip("#")
    assert re.fullmatch(r"[0-9a-f]{6}", v), f"expected a 6-digit hex colour, got {value!r}"
    return tuple(int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _luminance(value: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)
