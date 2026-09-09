"""The vendored bundles are pinned by content, and the one local patch and the
mitigation that make CVE-2026-85061 unreachable are guarded.

MapLibre 5.24.0 is the last 5.x release and its DOM.sanitize is vulnerable
(fixed upstream only in 6.4.1). The page never hands MapLibre untrusted HTML
because the attribution control is off; the bundle also carries a one-token
patch so the sanitizer no longer mutates the NamedNodeMap it iterates.
"""

import hashlib
import re

from transport_maps import config

WEB = config.ROOT / "web"


def _readme_hashes() -> dict[str, str]:
    text = (WEB / "README.md").read_text(encoding="utf-8")
    found = {}
    for line in text.splitlines():
        m = re.match(r"\| ([\w.-]+) \| `([0-9a-f]{64})`", line)
        if m:
            found[m.group(1)] = m.group(2)
    return found


def test_every_vendored_file_matches_the_hash_the_readme_records():
    recorded = _readme_hashes()
    expected = {"maplibre-gl.js", "pmtiles.js", "h3.js", "fflate.js", "maplibre-gl.css", "fonts.css"}
    assert expected <= set(recorded), f"README records hashes for {sorted(recorded)}"
    for name in expected:
        actual = hashlib.sha256((WEB / "vendor" / name).read_bytes()).hexdigest()
        assert actual == recorded[name], f"{name}: on disk {actual[:12]}…, README {recorded[name][:12]}…"


def test_the_sanitizer_patch_is_in_the_vendored_maplibre():
    bundle = (WEB / "vendor" / "maplibre-gl.js").read_text(encoding="utf-8")
    assert "of Array.from(t.attributes))" in bundle, "the CVE-2026-85061 patch is missing"
    assert "of t.attributes)pe.isPossiblyDangerous" not in bundle, "the vulnerable loop is back"


def test_the_page_never_hands_maplibre_an_attribution_string():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert re.search(r"attributionControl:\s*false", app), "attributionControl must stay off"
    assert "AttributionControl(" not in app
    assert "Popup(" not in app and "setHTML(" not in app, "a popup would reach DOM.sanitize with page HTML"
