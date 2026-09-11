"""The departure list has to show the rows it says it is showing.

Both defects here were invisible to every existing test and to the eye: the
list rendered the right rows, announced the right count, and scrolled to a
position that put them off screen. Nothing errored. They were found by
measuring `getBoundingClientRect()` against the list box on the live site.

The two assertions below are structural rather than behavioural -- app.js is a
2,600-line ES module that needs MapLibre and a real layout engine, so there is
no harness that can run it the way `test_boot_behaviour.py` runs boot.js. The
measured checks live in `scripts/browser_verify.sh`, which drives the deployed
page. What these pin is the pairing: the scroll arithmetic in app.js is only
correct while the CSS makes `#results` the offsetParent, and the two live in
different files, so a change to one will not show the other.

Mutations performed and reverted before committing:
  - delete `position:relative` from the `.results` rule -> red
  - delete the `else if (f)` branch from app.js -> red
"""

import re

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")

#: The `.results` rule body, with CSS comments removed so a comment that merely
#: mentions a declaration cannot satisfy the assertion.
_CSS = re.sub(r"/\*.*?\*/", "", HTML, flags=re.S)


def _rule(selector: str) -> str:
    m = re.search(rf"(?:^|\}}|>)\s*{re.escape(selector)}\s*\{{([^}}]*)\}}", _CSS, re.M)
    assert m, f"no CSS rule for {selector}"
    return m.group(1)


def test_the_results_box_is_the_offset_parent_its_scroll_maths_assumes():
    """`here.offsetTop` is measured against the nearest positioned ancestor.

    Without `position:relative` on `.results` that ancestor was `.rail`, so the
    offset carried the search box and the caption above the list. Measured at
    `?from=seoul`: the active row rendered at y 166.95-193.14 against a box at
    y 298.14-618.14 -- 131 px above the top of the visible list -- and the list
    opened on "Shaoguan ... Srinagar" with no sign a departure was selected.
    `inView()` repeats the same measurement, so it reported the row visible and
    never corrected.
    """
    assert "position:relative" in _rule(".results").replace(" ", "")
    # The pairing this rule exists for: if app.js stops measuring offsetTop
    # against the box, this test is pinning a rule nothing needs.
    assert "here.offsetTop" in APP


def test_a_filtered_list_starts_at_its_own_top():
    """`replaceChildren` does not reset `scrollTop`; the browser clamps it.

    Typing "lond" on a fresh load left `.results.scrollTop` at 152 -- the new
    maximum for a nine-row list -- so London itself rendered at y 146-172
    against a box at y 298-618 and the visible list began at "STN London
    Stansted Airport", while the live region announced "9 matches". The answer
    was in the DOM and off the screen.
    """
    m = re.search(
        r"if \(!f && active\) \{.*?\n  \} else if \(f\) \{(.*?)\n  \}",
        APP, re.S)
    assert m, "the filtered-list branch is gone from the results builder"
    body = re.sub(r"//.*", "", m.group(1))
    assert re.search(r"box\.scrollTop\s*=\s*0", body), (
        "a filtered list no longer resets its scroll position")
