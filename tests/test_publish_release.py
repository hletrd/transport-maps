"""Exercise publication using actual files and atomic replacements."""

import json
import re
import struct

import pytest

from scripts.publish_release import atomic_write, prepare_reading_ranges, publish


@pytest.fixture
def site(tmp_path):
    (tmp_path / ".release-index.html").write_text(
        '<html><head><link rel="canonical" href="https://worldmap.atik.kr/">'
        '<link rel="preload" href="./index.json" as="fetch">'
        '<link rel="stylesheet" href="./vendor/fonts.css"></head><body>'
        '<a href="#privacy">Privacy</a><script src="./boot.js"></script>'
        '<script type="module" src="./app.js"></script></body></html>')
    (tmp_path / "index.html").write_text("previous page")
    (tmp_path / "index.json").write_text(json.dumps({"buildId": "build-1", "origins": [{"slug": "seoul"}]}))
    for name, data in {"hover_cells.bin": b"cells", "water.pmtiles": b"water",
                       "app.js": b'import "./vendor/lib.js";', "boot.js": b"boot"}.items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor/fonts.css").write_text("font")
    (tmp_path / "vendor/lib.js").write_text("lib")
    (tmp_path / "origins").mkdir()
    (tmp_path / "origins/seoul.bin").write_bytes(b"original times")
    return tmp_path


def test_page_selects_complete_asset_and_data_snapshots(site):
    release = publish(site)
    for directory, identity in (("assets", release["assets"]), ("data", release["data"])):
        assert (site / directory / identity).stat().st_mode & 0o005 == 0o005, "nginx must traverse the snapshot"
    html = (site / "index.html").read_text()
    assert f'/assets/{release["assets"]}/app.js' in html
    assert f'/data/{release["data"]}/index.json' in html
    assert f'<meta name="worldmap-data-root" content="/data/{release["data"]}/">' in html
    assert 'href="#privacy"' in html
    assert 'href="https://worldmap.atik.kr/"' in html
    for path in re.findall(r'(?:href|src)="(/(?:assets|data)/[^\"]+)"', html):
        assert (site / path.lstrip("/")).is_file()
    assert (site / "assets" / release["assets"] / "vendor/lib.js").read_text() == "lib"


@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_first_paint_css_is_embedded_with_versioned_font_urls(site, quote):
    (site / "vendor/font.woff2").write_bytes(b"font")
    (site / "vendor/fonts.css").write_text(
        f"@font-face{{src:url({quote}./font.woff2{quote})}}"
        ".icon{background:url(data:image/svg+xml;base64,AAAA)}")
    release = publish(site)
    html = (site / "index.html").read_text()
    assert 'data-source="vendor/fonts.css"' in html
    assert f'url("/assets/{release["assets"]}/vendor/font.woff2")' in html
    assert "url(data:image/svg+xml;base64,AAAA)" in html
    assert 'rel="stylesheet"' not in html


def test_a_missing_critical_style_keeps_the_previous_page(site):
    (site / "vendor/fonts.css").unlink()
    with pytest.raises(ValueError, match="first-paint stylesheet"):
        publish(site)
    assert (site / "index.html").read_text() == "previous page"


def test_map_layout_is_immediate_and_control_icons_are_deferred(site):
    template = site / ".release-index.html"
    template.write_text(template.read_text().replace("</head>",
        '<link href="./vendor/maplibre-gl.css" rel="stylesheet"></head>'))
    css = ('.maplibregl-canvas{position:absolute;background-image:url("data:canvas");}'
           '.maplibregl-ctrl-icon{width:20px;background-image:url("data:icon");}')
    (site / "vendor/maplibre-gl.css").write_text(css)
    release = publish(site)
    html = (site / "index.html").read_text()
    core = re.search(r'<style data-source="vendor/maplibre-gl.css">(.*?)</style>', html, re.S)[1]
    assert "position:absolute" in core and "width:20px" in core
    assert "data:canvas" in core and "data:icon" not in core
    assert 'media="print" data-after-paint' in html
    assert (site / "assets" / release["assets"] / "vendor/maplibre-gl.css").read_text() == css


def test_comment_removal_preserves_script_hashes_and_css_strings(site):
    template = site / ".release-index.html"
    script = '<script>const x="<!--keep-->"; /* keep CSP bytes */</script>'
    template.write_text(template.read_text().replace("</head>",
        '<!-- remove HTML note --><style>/* remove CSS note */.x{content:"/* keep */"}'
        '/*! keep licence */</style>' + script + '</head>'))
    publish(site)
    html = (site / "index.html").read_text()
    assert script in html
    assert 'content:"/* keep */"' in html and "/*! keep licence */" in html
    assert "remove HTML note" not in html and "remove CSS note" not in html


def test_new_publication_preserves_old_urls_and_reuses_unchanged_snapshots(site):
    old = publish(site)
    assert publish(site) == old
    old_data = site / "data" / old["data"] / "origins/seoul.bin"
    assert old_data.stat().st_ino == (site / "origins/seoul.bin").stat().st_ino
    # This is how rsync --delay-updates publishes: replace, never edit in place.
    atomic_write(site / "origins/seoul.bin", b"new times")
    atomic_write(site / "app.js", b"new application")
    new = publish(site)
    assert new["assets"] != old["assets"] and new["data"] != old["data"]
    assert old_data.read_bytes() == b"original times"
    assert (site / "assets" / old["assets"] / "app.js").read_bytes().startswith(b"import")
    assert (site / "data" / new["data"] / "origins/seoul.bin").read_bytes() == b"new times"


@pytest.mark.parametrize("path", ["index.json", "origins/seoul.bin", "vendor/lib.js", "data", "assets"])
def test_symlinks_cannot_escape_the_publish_root(site, tmp_path_factory, path):
    outside = tmp_path_factory.mktemp("outside") / "private"
    outside.write_text("not public")
    link = site / path
    link.unlink(missing_ok=True)
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        publish(site)
    assert (site / "index.html").read_text() == "previous page"


def test_missing_required_asset_does_not_replace_the_live_page(site):
    (site / "boot.js").unlink()
    with pytest.raises(ValueError, match="boot.js"):
        publish(site)
    assert (site / "index.html").read_text() == "previous page"


def test_a_traversal_build_id_is_refused(site):
    (site / "index.json").write_text(json.dumps({"buildId": "../../escape", "origins": [1]}))
    with pytest.raises(ValueError, match="safe buildId"):
        publish(site)


def test_incomplete_existing_snapshot_does_not_replace_live_page(site):
    release = publish(site)
    before = (site / "index.html").read_bytes()
    (site / "assets" / release["assets"] / "vendor/lib.js").unlink()
    with pytest.raises(ValueError, match="incomplete"):
        publish(site)
    assert (site / "index.html").read_bytes() == before


def regional_files(site, selected=(0, 3, 5, 10)):
    index = json.loads((site / "index.json").read_text())
    index.update(readingRes=6, readingParentCount=3, readingSlots=4,
                 modeChannels=["rail", "ferry"], readingUrlSuffix=".r6.bin", overrideUrlSuffix=".over.bin")
    (site / "index.json").write_text(json.dumps(index))
    (site / "origins/seoul.r6.bin").write_bytes(struct.pack("<12H", *range(12)))
    n = len(selected)
    (site / "origins/seoul.over.bin").write_bytes(struct.pack(f"<{n}I", *selected) + bytes(n * 6))
    return index


def test_regional_index_boundaries_and_repeated_publication(site):
    index = regional_files(site)
    original = (site / "origins/seoul.over.bin").read_bytes()
    prepare_reading_ranges(site, index)
    directory = site / "origins/seoul.over.index.bin"
    assert struct.unpack("<5I", directory.read_bytes()) == (4, 0, 2, 3, 4)
    assert index["readingRanges"] == {"blocks": 32, "overrideIndexSuffix": ".over.index.bin"}
    before = directory.stat().st_mtime_ns
    prepare_reading_ranges(site, index)
    assert directory.stat().st_mtime_ns == before
    assert (site / "origins/seoul.over.bin").read_bytes() == original


@pytest.mark.parametrize("selected", [(3, 0), (1, 1), (12,)])
def test_regional_index_refuses_invalid_route_slots(site, selected):
    index = regional_files(site, selected)
    with pytest.raises(ValueError, match="route slots"):
        prepare_reading_ranges(site, index)
    assert "readingRanges" not in json.loads((site / "index.json").read_text())


def test_regional_index_supports_no_route_overrides(site):
    index = regional_files(site, ())
    prepare_reading_ranges(site, index)
    assert struct.unpack("<5I", (site / "origins/seoul.over.index.bin").read_bytes()) == (0, 0, 0, 0, 0)


def test_regional_index_requires_every_advertised_origin(site):
    index = regional_files(site)
    index["origins"].append({"slug": "missing"})
    with pytest.raises(ValueError, match="missing route overrides"):
        prepare_reading_ranges(site, index)
    assert "readingRanges" not in json.loads((site / "index.json").read_text())
