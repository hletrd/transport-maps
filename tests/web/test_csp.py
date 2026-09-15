"""The CSP hash and the inline gtag bootstrap are a hand-synchronised pair.

A CSP-blocked inline script fails with a console message only, and the conf is
installed by the owner out of band, so nothing in the repo would notice the
two drifting apart. This test does.
"""

import base64
import hashlib
import re

from transport_maps import config


def _inline_scripts(html: str) -> list[tuple[str, str]]:
    """(attributes, body) of every <script> without a src."""
    return re.findall(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", html, flags=re.S)


def test_the_csp_snippet_carries_the_hash_of_every_inline_script():
    html = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    snippet = (config.ROOT / "deploy" / "worldmap-security-headers.conf").read_text(encoding="utf-8")
    scripts = [(attrs, body) for attrs, body in _inline_scripts(html)
               if body.strip() and "ld+json" not in attrs]   # JSON-LD is data, never executed
    assert scripts, "no inline script found in index.html; the hash rule no longer applies"
    for _attrs, body in scripts:
        digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        assert f"'sha256-{digest}'" in snippet, \
            f"inline script hash sha256-{digest} is not in the CSP snippet"


def test_no_inline_script_uses_unsafe_inline():
    snippet = (config.ROOT / "deploy" / "worldmap-security-headers.conf").read_text(encoding="utf-8")
    script_src = re.search(r"script-src ([^;]*);", snippet).group(1)
    assert "'unsafe-inline'" not in script_src


#: The Privacy Sandbox advertising APIs. CSP cannot reach any of them: they are
#: browser capabilities, not network fetches, so `connect-src` and `img-src`
#: say nothing about whether a script may read a browsing topic or join an ad
#: interest group. Each defaults to an allowlist of `*`.
AD_FEATURES = ("browsing-topics", "attribution-reporting",
               "join-ad-interest-group", "run-ad-auction")


def test_the_advertising_apis_are_denied_by_the_header_not_only_by_the_prose():
    """The page states "This site has no accounts, no sign-in and no
    advertising" (index.html). That was prose with nothing enforcing it.

    The CSP above deliberately withholds the hosts Google signals / ads
    linking would need, and its own comment says so -- but the Privacy Sandbox
    APIs are the advertising surface CSP structurally cannot reach. An
    analytics tag that started using them, or any future script on this
    origin, would be inside the CSP and outside the promise.

    Mutation performed and reverted: drop `browsing-topics=()` from the header
    -> red, naming it.
    """
    snippet = (config.ROOT / "deploy" / "worldmap-security-headers.conf").read_text(
        encoding="utf-8")
    line = [ln for ln in snippet.splitlines()
            if ln.lstrip().startswith("add_header Permissions-Policy")]
    assert len(line) == 1, f"expected one Permissions-Policy header, found {len(line)}"
    policy = line[0]
    missing = [f for f in AD_FEATURES if f"{f}=()" not in policy]
    assert not missing, (
        f"Permissions-Policy does not deny {missing}; each defaults to an "
        "allowlist of `*`, and CSP cannot reach any of them. The page claims "
        "it has no advertising -- the header should be what makes that true.")


def test_the_page_still_makes_the_claim_the_header_enforces():
    """The pair. If the "no advertising" sentence is ever removed, the test
    above is enforcing a promise nobody is making any more, and whoever reads
    it next should be told where the promise lives.
    """
    html = (config.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "no advertising" in html, (
        "index.html no longer claims the site has no advertising; "
        "test_the_advertising_apis_are_denied_by_the_header_not_only_by_the_"
        "prose exists to enforce that sentence")


def test_geolocation_is_still_allowed_for_this_document():
    """The positive control. A Permissions-Policy of "deny everything" would
    satisfy the test above and break the "use my location" button, which is a
    feature the page offers and the header comment explains.
    """
    snippet = (config.ROOT / "deploy" / "worldmap-security-headers.conf").read_text(
        encoding="utf-8")
    assert "geolocation=(self)" in snippet, (
        "geolocation is no longer allowed for this document; the nearest-city "
        "button cannot work")
