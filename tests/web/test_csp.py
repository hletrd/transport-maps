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
