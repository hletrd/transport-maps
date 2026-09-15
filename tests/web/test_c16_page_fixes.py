"""Four page guards whose absence was measured, not assumed.

Each of these four defects had shipped and each was found by measuring the
LIVE site rather than by reading the source, so each guard here is written to
fail on the observable property rather than on the spelling of the fix.

MUTATIONS PERFORMED, with the results as measured -- not as estimated.
Each was applied by editing the file and reverted by editing it back.

1. Delete `scroll-padding-bottom` from `.legs`:
   **1 failed** -- `test_the_itinerary_reserves_room_for_its_sticky_total`.
2. Change it to `scroll-padding-bottom:0`:
   **1 failed**, same test, naming the value.
3. Drop `aria-selected` from the city row builder only:
   **1 failed** -- `test_every_option_row_carries_aria_selected` names the
   builder that lost it. Dropping it from the airport builder instead fails
   the same test naming that one, so the guard is per-site and not a count.
4. Move `#depart-basis` back below the `<dl>` in `index.html`:
   **1 failed** -- `test_the_basis_precedes_the_figures_it_defines`.
5. Restore the single-sentence `depart-note` (the pre-C16-5 wording, with the
   basis and the footnote in one string below the list), leaving the empty
   `#depart-basis` in the markup:
   **1 failed** -- `test_the_basis_element_is_actually_filled`. The order
   test still passes, which is exactly why that second guard exists: an empty
   element in the right place satisfies the order and changes nothing a
   reader sees.
6. Set `sitemap.xml`'s `lastmod` back to 2026-09-10:
   **1 failed** -- `test_the_published_dates_are_not_older_than_the_page`.
   Setting only the JSON-LD `dateModified` back instead: **1 failed**, same
   test, naming the other file. They are checked independently because cycle
   15 corrected one of a pair and left the other.

No mutation came back green.
"""

from __future__ import annotations

import datetime
import re
import subprocess

from transport_maps import config

ROOT = config.ROOT
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
SITEMAP = (ROOT / "web" / "sitemap.xml").read_text(encoding="utf-8")


# --- C16-5.1 ---------------------------------------------------------------

def test_the_itinerary_reserves_room_for_its_sticky_total() -> None:
    """`.leg.total` is `position:sticky; bottom:0` inside `.legs`, which is a
    scroll box. A sticky element paints over the box's own content and the
    browser's scroll-into-view does not account for it, so Tab put focus
    underneath it -- measured 5 of 5 `elementFromPoint` samples at 1280x800
    and again at 844x390. That is WCAG 2.2 SC 2.4.11, focus not obscured.

    Asserted as a relationship, not as a magic number: the total IS sticky,
    and `.legs` DOES reserve at least the total's own box height.
    """
    total = re.search(r"\.leg\.total\{([^}]*)\}", HTML, re.S)
    assert total, "the .leg.total rule has moved; re-read this guard"
    assert "position:sticky" in total.group(1), (
        "the total is no longer sticky, which is what made the padding "
        "necessary -- if that changed on purpose, retire this guard "
        "deliberately rather than leaving it passing for a new reason")

    legs = re.search(r"\n\.legs\{([^}]*)\}", HTML, re.S)
    assert legs, "the .legs rule has moved; re-read this guard"
    body = legs.group(1)
    assert "overflow-y:auto" in body, ".legs is no longer a scroll box"
    pad = re.search(r"scroll-padding-bottom:\s*(\d+)px", body)
    assert pad, (
        "`.legs` has no scroll-padding-bottom, so a focused row can scroll to "
        "sit underneath the sticky total:\n" + body)
    assert int(pad.group(1)) >= 24, (
        f"scroll-padding-bottom is {pad.group(1)}px, which is less than the "
        f"total's own border+margin+padding+line box; focus can still land "
        f"partly under it")


# --- C16-5.2 ---------------------------------------------------------------

def test_every_option_row_carries_aria_selected() -> None:
    """An element with `role="option"` inside a `role="listbox"` carries its
    selected state in `aria-selected`. All three builders set the role and
    none set the state, so 553 rows announced no selection at all -- it was
    carried by the word "departing" in the row's own text, which is content,
    not state (SC 4.1.2).

    Checked per builder rather than by counting, because a count passes when
    one builder gains two and another gains none.
    """
    assert 'role="listbox"' in HTML, (
        "the results list is no longer a listbox; aria-selected may no longer "
        "be the right property -- re-read this guard rather than deleting it")

    builders = [m.start() for m in
                re.finditer(r'b\.setAttribute\("role", "option"\)', APP)]
    assert len(builders) >= 3, (
        f"expected at least three option-row builders, found {len(builders)}")
    for start in builders:
        # The builder's own block: from the role call to the next blank-ish
        # boundary. 900 characters is comfortably past the longest of the
        # three and well short of the next builder.
        block = APP[start:start + 900]
        assert "aria-selected" in block, (
            "an option-row builder sets role=option and never sets "
            "aria-selected:\n" + APP[max(0, start - 200):start + 400])


def test_the_departure_row_selection_tracks_the_active_city() -> None:
    """`aria-selected="true"` on every row, or on none, is as useless as the
    absent attribute. The city builder must bind it to the active origin.
    """
    m = re.search(r'b\.setAttribute\("aria-selected", String\(([^)]*)\)\)', APP)
    assert m, ("no option row binds aria-selected to an expression; a "
               "hard-coded value cannot follow the departure")
    assert "active" in m.group(1) and "slug" in m.group(1), (
        f"aria-selected is bound to {m.group(1)!r}, which does not mention "
        f"the active origin's slug")


# --- C16-5.3 ---------------------------------------------------------------

def test_the_basis_precedes_the_figures_it_defines() -> None:
    """The card printed three bare percentages and only then the sentence
    saying what they are a share of, so "34.2%" was read with no denominator
    -- it could have been a share of countries, of population, or of the
    globe including sea.
    """
    basis = HTML.index('id="depart-basis"')
    figures = HTML.index('id="depart-reach"')
    assert basis < figures, (
        "the basis sentence is rendered AFTER the percentages it defines; a "
        "number is not information until its denominator is")


def test_the_basis_element_is_actually_filled() -> None:
    """The guard on the guard. Adding an empty `<p>` above the list satisfies
    the order test and changes nothing a reader sees, so this one checks the
    element is written to, that what it says names the denominator, and that
    it is cleared on the failure path -- otherwise a city whose arrays are
    missing keeps the previous city's sentence standing over an empty list.
    """
    assert '$("depart-basis").textContent' in APP, (
        "#depart-basis exists in the markup and nothing ever fills it")
    written = re.findall(r'\$\("depart-basis"\)\.textContent\s*=\s*(.{0,120})',
                         APP, re.S)
    assert len(written) >= 2, (
        f"#depart-basis is written at {len(written)} site(s); it needs both "
        f"the filled case and the cleared one")
    joined = " ".join(written)
    assert "charted land" in joined and "Antarctica" in joined, (
        "the basis sentence no longer names what the percentages are a share "
        f"of: {joined!r}")
    assert '"";' in joined or "'';" in joined, (
        "#depart-basis is never cleared, so a failed origin shows the "
        "previous city's basis over an empty list")
    assert "door to door" in joined, (
        "CLAUDE.md makes the door-to-door composition a standing rule "
        "wherever a figure is presented, and this sentence introduces three")


# --- C16-5.4 ---------------------------------------------------------------

def _last_commit_date(path: str) -> datetime.date:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "log", "-1", "--format=%cd", "--date=short",
         "--", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return datetime.date.fromisoformat(out) if out else datetime.date.min


def test_the_published_dates_are_not_older_than_the_page() -> None:
    """`sitemap.xml` was the one deployed file no test opened, and it and the
    JSON-LD `dateModified` both said 2026-09-10 against a page changed six
    days later.

    Compared against `web/index.html`'s own last commit date rather than
    against today, so the guard does not go red merely because time passed --
    it goes red when the page changes and the dates do not, which is the
    failure. The two files are checked independently: a previous cycle
    corrected one of the pair and left the other.
    """
    page = _last_commit_date("web/index.html")
    if page == datetime.date.min:
        import pytest
        pytest.skip("web/index.html has no commit history here")

    sm = re.search(r"<lastmod>(\d{4}-\d{2}-\d{2})</lastmod>", SITEMAP)
    assert sm, "sitemap.xml has no lastmod"
    assert datetime.date.fromisoformat(sm.group(1)) >= page, (
        f"sitemap.xml lastmod is {sm.group(1)} but web/index.html was last "
        f"changed {page}")

    ld = re.search(r'"dateModified":\s*"(\d{4}-\d{2}-\d{2})"', HTML)
    assert ld, "index.html carries no JSON-LD dateModified"
    assert datetime.date.fromisoformat(ld.group(1)) >= page, (
        f"JSON-LD dateModified is {ld.group(1)} but web/index.html was last "
        f"changed {page}")
