"""Exercise publication using actual files and atomic replacements."""

import json
import re

import pytest

from scripts.publish_release import atomic_write, publish


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
