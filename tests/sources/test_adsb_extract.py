"""`scripts/adsb_extract.py` trusts nothing the GitHub releases API returns.

The release tag becomes a file name under the cache and each asset URL is
fetched and written into it (A18 / Q4, SEC-23). These tests drive
`ensure_archive` against a fake opener, so no request leaves the machine, and
assert both halves of every refusal: the run stops, and nothing is written
outside -- or left behind inside -- the cache.

Mutations performed and reverted, each confirmed RED:
  * `safe_name` returns `name` unchecked          -> 9 of the tag and asset
                                                     name cases go red
  * `check_asset_url` drops the scheme test       -> the http:// test goes red
  * `check_asset_url` drops the host test         -> the other-host test goes red
  * `check_asset_url` drops the path test         -> the other-repo test goes red
  * `MAX_PART_BYTES` check removed                -> the oversized-part test
                                                     goes red
  * `MAX_ARCHIVE_BYTES` check removed             -> the oversized-release test
                                                     goes red
  * the `got > declared` stream cap removed       -> the over-sending server
                                                     test goes red
  * the `.partial` unlink on failure removed      -> the over-sending and short
                                                     download tests go red
  * `_AllowListRedirects.redirect_request` passes
    everything to `super()`                       -> all three refused-redirect
                                                     cases go red
"""

import importlib.util
import io
import json
import pathlib
import urllib.error
import urllib.request

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "adsb_extract.py"
TAG = "v2026.09.30-planes-readsb-prod-0"
BASE = f"https://github.com/adsblol/globe_history_2026/releases/download/{TAG}"


@pytest.fixture(scope="module")
def adsb():
    spec = importlib.util.spec_from_file_location("adsb_extract", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _asset(name, size, url=None, tag=TAG):
    base = f"https://github.com/adsblol/globe_history_2026/releases/download/{tag}"
    return {"name": name, "size": size, "browser_download_url": url or f"{base}/{name}"}


class FakeOpener:
    """Answers the releases API with `releases` and each URL from `bodies`."""

    def __init__(self, adsb, releases, bodies=None):
        self.adsb = adsb
        self.releases = releases
        self.bodies = bodies or {}
        self.fetched = []

    def open(self, url, timeout=None):
        self.fetched.append(url)
        if url == self.adsb.GITHUB_RELEASES:
            return io.BytesIO(json.dumps(self.releases).encode())
        return io.BytesIO(self.bodies[url])


def _run(adsb, monkeypatch, tmp_path, releases, bodies=None):
    fake = FakeOpener(adsb, releases, bodies)
    monkeypatch.setattr(adsb, "_opener", fake)
    cache = tmp_path / "cache"
    return fake, cache


def _files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_a_well_formed_release_downloads_and_concatenates(adsb, monkeypatch, tmp_path):
    """The positive control: without it every refusal below could be a script
    that refuses everything."""
    releases = [{"tag_name": TAG, "assets": [_asset(f"{TAG}.tar.ab", 3),
                                             _asset(f"{TAG}.tar.aa", 4)]}]
    bodies = {f"{BASE}/{TAG}.tar.aa": b"AAAA", f"{BASE}/{TAG}.tar.ab": b"BBB"}
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases, bodies)
    target = adsb.ensure_archive(cache, "prod-0")
    assert target == cache / f"{TAG}.tar"
    assert target.read_bytes() == b"AAAABBB"          # .aa before .ab
    assert _files(tmp_path) == [f"cache/{TAG}.tar"]


@pytest.mark.parametrize("tag", [
    "../../prod-0-escape",          # climbs out of the cache
    "prod-0/../../escape",          # separator inside
    ".prod-0",                      # hidden file, and the `..` family
    "prod-0\\..\\escape",           # Windows separator
    "prod-0\x00",                   # NUL
])
def test_an_unsafe_release_tag_is_refused(adsb, monkeypatch, tmp_path, tag):
    releases = [{"tag_name": tag, "assets": [_asset("x.tar.aa", 4, tag=tag)]}]
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases)
    with pytest.raises(SystemExit, match="unsafe release tag"):
        adsb.ensure_archive(cache, "prod-0")
    assert _files(tmp_path) == []
    assert fake.fetched == [adsb.GITHUB_RELEASES]    # no asset was requested


@pytest.mark.parametrize("name", ["../evil.tar.aa", "a/b.tar.aa", "..", ""])
def test_an_unsafe_asset_name_is_refused(adsb, monkeypatch, tmp_path, name):
    releases = [{"tag_name": TAG, "assets": [_asset(name, 4)]}]
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases)
    with pytest.raises(SystemExit, match="unsafe asset name"):
        adsb.ensure_archive(cache, "prod-0")
    assert _files(tmp_path) == []


@pytest.mark.parametrize(("url", "why"), [
    (f"http://github.com/adsblol/globe_history_2026/releases/download/{TAG}/{TAG}.tar.aa",
     "plain http"),
    (f"https://evil.example/adsblol/globe_history_2026/releases/download/{TAG}/{TAG}.tar.aa",
     "other host"),
    (f"https://github.com.evil.example/adsblol/globe_history_2026/releases/download/{TAG}/{TAG}.tar.aa",
     "suffix host"),
    (f"https://github.com/someone/else/releases/download/{TAG}/{TAG}.tar.aa",
     "other repo"),
    (f"https://github.com/adsblol/globe_history_2026/releases/download/{TAG}/other.tar.aa",
     "URL names a different asset"),
    (f"https://github.com:8443/adsblol/globe_history_2026/releases/download/{TAG}/{TAG}.tar.aa",
     "non-default port"),
])
def test_an_unexpected_asset_url_is_refused(adsb, monkeypatch, tmp_path, url, why):
    releases = [{"tag_name": TAG, "assets": [_asset(f"{TAG}.tar.aa", 4, url=url)]}]
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases)
    with pytest.raises(SystemExit, match="refusing asset URL"):
        adsb.ensure_archive(cache, "prod-0")
    assert fake.fetched == [adsb.GITHUB_RELEASES], why
    assert _files(tmp_path) == []


@pytest.mark.parametrize("size", [0, -1, None, "4", True])
def test_a_missing_or_nonsense_size_is_refused(adsb, monkeypatch, tmp_path, size):
    releases = [{"tag_name": TAG, "assets": [_asset(f"{TAG}.tar.aa", size)]}]
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases)
    with pytest.raises(SystemExit, match="declared size"):
        adsb.ensure_archive(cache, "prod-0")


def test_an_oversized_part_is_refused_before_any_download(adsb, monkeypatch, tmp_path):
    releases = [{"tag_name": TAG,
                 "assets": [_asset(f"{TAG}.tar.aa", adsb.MAX_PART_BYTES + 1)]}]
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases)
    with pytest.raises(SystemExit, match="declared size"):
        adsb.ensure_archive(cache, "prod-0")
    assert fake.fetched == [adsb.GITHUB_RELEASES]


def test_an_oversized_release_is_refused_before_any_download(adsb, monkeypatch, tmp_path):
    n = adsb.MAX_ARCHIVE_BYTES // adsb.MAX_PART_BYTES + 1
    parts = [_asset(f"{TAG}.tar.a{chr(97 + i)}", adsb.MAX_PART_BYTES) for i in range(n)]
    releases = [{"tag_name": TAG, "assets": parts}]
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases)
    with pytest.raises(SystemExit, match="bytes declared"):
        adsb.ensure_archive(cache, "prod-0")
    assert fake.fetched == [adsb.GITHUB_RELEASES]


def test_a_server_that_sends_more_than_declared_is_stopped(adsb, monkeypatch, tmp_path):
    """The declared size is a cap on bytes received, and the partial goes."""
    releases = [{"tag_name": TAG, "assets": [_asset(f"{TAG}.tar.aa", 4)]}]
    bodies = {f"{BASE}/{TAG}.tar.aa": b"A" * (1 << 23)}
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases, bodies)
    with pytest.raises(SystemExit, match="more than its declared"):
        adsb.ensure_archive(cache, "prod-0")
    assert _files(tmp_path) == []


def test_a_short_download_is_refused_and_leaves_nothing(adsb, monkeypatch, tmp_path):
    releases = [{"tag_name": TAG, "assets": [_asset(f"{TAG}.tar.aa", 4)]}]
    bodies = {f"{BASE}/{TAG}.tar.aa": b"AA"}
    fake, cache = _run(adsb, monkeypatch, tmp_path, releases, bodies)
    with pytest.raises(SystemExit, match="sent 2 of its declared 4"):
        adsb.ensure_archive(cache, "prod-0")
    assert _files(tmp_path) == []


def _redirect(adsb, newurl):
    handler = adsb._AllowListRedirects()
    req = urllib.request.Request(f"{BASE}/{TAG}.tar.aa")
    return handler.redirect_request(req, io.BytesIO(), 302, "Found", {}, newurl)


@pytest.mark.parametrize("newurl", [
    "http://release-assets.githubusercontent.com/x",       # downgraded to http
    "https://evil.example/x",                              # other host
    "ftp://release-assets.githubusercontent.com/x",
])
def test_a_redirect_off_the_allow_list_is_refused(adsb, newurl):
    with pytest.raises(urllib.error.HTTPError, match="refusing redirect"):
        _redirect(adsb, newurl)


def test_the_github_asset_cdn_redirect_is_followed(adsb):
    """GitHub answers the download URL with a 302 to its CDN (measured
    2026-10-02: release-assets.githubusercontent.com). Refusing that would make
    the script unable to download anything."""
    req = _redirect(adsb, "https://release-assets.githubusercontent.com/github-production-release-asset/1")
    assert req.full_url.startswith("https://release-assets.githubusercontent.com/")
