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
        m = re.match(r"\| ([\w./-]+) \| `([0-9a-f]{64})`", line)
        if m:
            found[m.group(1)] = m.group(2)
    return found


def test_every_vendored_file_matches_the_hash_the_readme_records():
    """Enumerate vendor/, not a hard-coded list.

    A hard-coded set pinned six of the ten files: the three IBM Plex faces --
    served `immutable, max-age=31536000`, so a swap is cached for a year -- and
    OFL.txt were unpinned, and a newly vendored file would have been unpinned
    too, silently. Deriving the set from the directory makes that impossible.
    """
    recorded = _readme_hashes()
    # rglob, not iterdir: the seven files under vendor/licences/ -- the
    # licence TEXTS this page's compliance rests on -- were invisible to a
    # non-recursive walk, while web/README.md claimed "every file in
    # vendor/ appears above". Recorded by path relative to vendor/.
    expected = {p.relative_to(WEB / "vendor").as_posix()
                for p in (WEB / "vendor").rglob("*") if p.is_file()}
    # BOTH directions. `expected <= recorded` alone cannot see the test
    # NARROWING: reverting this walk from rglob to iterdir drops the seven
    # licence texts from `expected` and a subset check stays green, which is
    # exactly how web/README.md came to claim "every file in vendor/ appears
    # above" while seven of them were unpinned. Equality also catches a row
    # left behind for a file that has been deleted.
    assert expected == set(recorded), (
        "web/README.md and web/vendor/ disagree.\n"
        f"  vendored but not pinned: {sorted(expected - set(recorded))}\n"
        f"  pinned but not vendored: {sorted(set(recorded) - expected)}")
    assert any("/" in name for name in expected), (
        "no file under a vendor/ SUBDIRECTORY is in the walk, so it is not "
        "recursive -- vendor/licences/ holds the licence texts this page's "
        "compliance rests on")
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


# --- C6-12 / C6-15: the notices we redistribute, and the statistic we quote --

LICENCES = config.ROOT / "web" / "vendor" / "licences"

#: Every vendored file that reaches a visitor, and the licence text that must
#: travel with it. Derived from web/README.md's own version table; BSD-3-Clause,
#: Apache-2.0 and MIT all require the notice to be reproduced on redistribution,
#: and jsDelivr's repack had stripped every source banner -- `grep -ciE
#: "BSD|Apache License|MIT License|Copyright"` returned 0 on all four bundles.
NOTICE_FOR = {
    "maplibre-gl.js": "maplibre-gl.LICENSE.txt",
    "maplibre-gl.css": "maplibre-gl.LICENSE.txt",
    "pmtiles.js": "pmtiles.LICENSE.txt",
    "h3.js": "h3-js.LICENSE.txt",
    "fflate.js": "fflate.LICENSE.txt",
    "ibm-plex-sans-latin-400-normal.woff2": "../OFL.txt",
    "ibm-plex-sans-latin-500-normal.woff2": "../OFL.txt",
    "ibm-plex-sans-latin-600-normal.woff2": "../OFL.txt",
    "fonts.css": "../OFL.txt",
}


def test_every_redistributed_bundle_carries_its_licence_text():
    """The notice requirement is a licence term, not a courtesy.

    Enumerate vendor/ rather than a list, exactly as the hash test does: a newly
    vendored file must fail this until someone decides which notice goes with
    it.

    Mutation performed and reverted: delete any one file under
    `vendor/licences/` -> red.
    """
    shipped = {p.name for p in (WEB / "vendor").iterdir() if p.is_file()}
    shipped -= {"OFL.txt"}                      # it IS a notice, not a bundle
    assert shipped == set(NOTICE_FOR), (
        "a vendored file has no recorded licence text: "
        f"{sorted(shipped ^ set(NOTICE_FOR))}")
    for name, notice in NOTICE_FOR.items():
        path = (LICENCES / notice).resolve()
        assert path.is_file(), f"{name} is served with no licence text ({notice})"
        assert path.stat().st_size > 500, f"{notice} is too short to be a licence"


def test_the_apache_notice_travels_with_the_apache_licence():
    """Apache-2.0 section 4(d): the NOTICE file's attribution text must be
    carried with any derivative distribution, separately from the licence."""
    notice = LICENCES / "h3-js.NOTICE.txt"
    assert notice.is_file(), "h3-js ships Apache-2.0 with no NOTICE"
    assert "Uber Technologies" in notice.read_text(encoding="utf-8")
    assert "Apache License" in (LICENCES / "h3-js.LICENSE.txt").read_text(encoding="utf-8")


def test_the_licence_texts_are_the_upstream_ones_not_a_summary():
    """Each must carry the operative clause its licence is identified by."""
    must = {
        "maplibre-gl.LICENSE.txt": "Redistributions of source code must retain",
        "pmtiles.LICENSE.txt": "Redistributions of source code must retain",
        "h3-js.LICENSE.txt": "Licensed under the Apache License",
        "fflate.LICENSE.txt": "Permission is hereby granted, free of charge",
    }
    for name, clause in must.items():
        text = (LICENCES / name).read_text(encoding="utf-8")
        assert clause in text, f"{name} is not the upstream licence text"
        assert "Copyright" in text, f"{name} carries no copyright notice"


def test_the_page_points_a_visitor_at_them():
    """A notice nobody can find is not served with the work.

    Mutation performed and reverted: delete the vendor/licences link from
    index.html -> red.
    """
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'href="./vendor/licences/"' in html, (
        "the page does not link to the third-party notices it redistributes")
    # Collapse the markup's own wrapping before looking for a phrase: the
    # paragraph is indented prose and "Open Font License" spans a line break.
    flat = " ".join(html.split())
    for word in ("BSD-3-Clause", "Apache-2.0", "MIT", "Open Font License"):
        assert word in flat, f"the notices paragraph does not name {word}"


def test_the_directory_the_page_links_actually_serves_something():
    """The link above was satisfied by a URL that returned 403.

    nginx serves this directory with `index index.html` and no autoindex, and
    for as long as the link existed there was no index.html in it -- so the
    page's only route to the notices was a 403 while the five .txt files
    beside it returned 200. BSD-3-Clause section 2 and Apache-2.0 section 4
    were unmet in practice, and the test above passed throughout, because a
    link to a 403 contains exactly the same href string as a link that works.

    This is the static half; scripts/deploy_verify.sh probes the live URL,
    which is the half that can see a server-side regression.

    Mutation performed and reverted: delete vendor/licences/index.html -> red;
    remove any one licence link from it -> red.
    """
    index = LICENCES / "index.html"
    assert index.exists(), (
        "vendor/licences/ has no index.html, so the link in the page is a 403")
    page = index.read_text(encoding="utf-8")
    for name in ("maplibre-gl.LICENSE.txt", "pmtiles.LICENSE.txt", "h3-js.LICENSE.txt",
                 "h3-js.NOTICE.txt", "fflate.LICENSE.txt"):
        assert (LICENCES / name).exists(), f"{name} is missing from vendor/licences/"
        # The HREF, not the name anywhere on the page: the first version of
        # this assertion was `name in page`, which stayed green when the href
        # was replaced by "#", because the file name survived as the link's
        # own visible text.
        assert f'href="./{name}"' in page, (
            f"vendor/licences/index.html does not LINK {name} (it may only name it)")
    # The font's text lives one directory up and is linked from here, since
    # nothing else on the site links it at all.
    assert 'href="../OFL.txt"' in page, "the licence index does not link the font's OFL text"
    assert (WEB / "vendor" / "OFL.txt").exists()


def test_the_licence_index_is_not_excluded_from_the_deploy():
    """README.md is excluded from both rsyncs, which is why the directory's
    previous index -- a README -- 404ed. An index.html must not be.

    Mutation performed and reverted: add `index.html` to
    deploy/rsync-excludes.txt -> red.
    """
    excludes = [ln.strip() for ln in
                (config.ROOT / "deploy" / "rsync-excludes.txt").read_text().splitlines()
                if ln.strip() and not ln.startswith("#")]
    assert "index.html" not in excludes, (
        "the deploy excludes index.html, so vendor/licences/ would 403 again")
    assert "README.md" in excludes, (
        "this test's premise has changed: README.md is no longer excluded, so the "
        "directory could be indexed by its README after all")


def test_the_held_out_error_is_called_what_it_is():
    """`calibrate/fit.py` takes `.mean()`. Both public surfaces said median.

    Mutation performed and reverted: put "median of about 9 minutes" back in
    index.html -> red.
    """
    import tomllib

    from transport_maps.calibrate import fit

    src = (config.ROOT / "src" / "transport_maps" / "calibrate" / "fit.py").read_text(
        encoding="utf-8")
    body = src[src.index("def fit_airborne_with_holdout"):]
    body = body[:body.index("\ndef ")]
    assert ".mean()" in body and ".median()" not in body, (
        "fit_airborne_with_holdout no longer reports a mean; re-derive this test")
    assert fit is not None

    with (config.ROOT / "calibration.toml").open("rb") as fh:
        mae = tomllib.load(fh)["meta"]["holdout_mae_min"]
    rounded = f"{round(mae)} minutes"

    for path in (WEB / "index.html", WEB / "llms.txt"):
        text = path.read_text(encoding="utf-8")
        i = text.index(rounded)
        window = text[max(0, i - 260):i]
        assert "median" not in window.lower(), (
            f"{path.name} calls the mean absolute error a median")
        assert "mean" in window.lower(), (
            f"{path.name} does not say the held-out error is a mean")
