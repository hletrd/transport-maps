"""`sources._fetch`: the conditional check every raw input goes through (G2).

No network: `_fetch._stream` is replaced by a scripted upstream that records
what it was asked. Each guard below was mutated and the named test went red;
the mutations are listed beside the test they belong to.
"""

import contextlib
import json
import logging
import os

import httpx
import polars as pl
import pytest

from transport_maps import config
from transport_maps.sources import _fetch, airports

URL = "https://example.invalid/data.zip"


class Resp:
    """httpx's response shape, as far as `_fetch` uses it. No `.content` and no
    `.read()`: a body read whole instead of streamed raises AttributeError."""

    def __init__(self, status, body=b"", headers=None, fail_after=None):
        self.status_code = status
        self.headers = httpx.Headers(headers or {})
        self._body = body
        self._fail_after = fail_after

    def iter_bytes(self, chunk_size=None):
        for i in range(0, len(self._body), 4):
            if self._fail_after is not None and i >= self._fail_after:
                raise httpx.ReadError("connection reset mid-body")
            yield self._body[i:i + 4]

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            request = httpx.Request("GET", URL)
            raise httpx.HTTPStatusError(f"{self.status_code}", request=request,
                                        response=httpx.Response(self.status_code, request=request))


class Upstream:
    """Answers each request with the next scripted response (or raises it)."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def __call__(self, url, headers, timeout):
        self.calls.append(dict(headers))
        resp = self.responses.pop(0)
        if isinstance(resp, BaseException):
            raise resp
        return contextlib.nullcontext(resp)


@pytest.fixture
def online(monkeypatch):
    """The network back on, against whatever Upstream a test installs."""
    _fetch.set_offline(False)

    def install(*responses):
        up = Upstream(*responses)
        monkeypatch.setattr(_fetch, "_stream", up)
        return up
    return install


def _new_build():
    """What a second `build-all` sees: the same disk, a fresh process."""
    _fetch.reset()


V1 = b"version one of the archive"
V2 = b"version two, a different length"
HEADERS_V1 = {"etag": '"v1"', "last-modified": "Wed, 01 Oct 2026 00:00:00 GMT",
              "content-length": str(len(V1))}


def test_a_first_download_records_validators_size_and_hash(tmp_path, online):
    up = online(Resp(200, V1, HEADERS_V1))
    cache = tmp_path / "data.zip"
    fp = _fetch.fetch(URL, cache)
    assert cache.read_bytes() == V1
    assert up.calls == [{}], "nothing on disk, so nothing to be conditional on"
    meta = json.loads(_fetch.meta_path(cache).read_text())
    assert meta["etag"] == '"v1"' and meta["last_modified"] == HEADERS_V1["last-modified"]
    assert meta["size"] == len(V1) and meta["sha256"] == fp.sha256
    assert fp.status == "downloaded"
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".part")]


def test_a_304_keeps_the_cache_untouched(tmp_path, online):
    """Mutation: drop the If-None-Match header -> red (the request is not
    conditional). Treating 304 as a body to download -> red (an empty file)."""
    cache = tmp_path / "data.zip"
    online(Resp(200, V1, HEADERS_V1))
    first = _fetch.fetch(URL, cache)
    mtime = cache.stat().st_mtime_ns

    _new_build()
    up = online(Resp(304, headers={"etag": '"v1"'}))
    fp = _fetch.fetch(URL, cache)
    assert up.calls == [{"If-None-Match": '"v1"',
                         "If-Modified-Since": HEADERS_V1["last-modified"]}]
    assert cache.read_bytes() == V1 and cache.stat().st_mtime_ns == mtime
    assert fp.status == "unchanged" and fp.sha256 == first.sha256


def test_a_200_with_new_bytes_replaces_the_cache_and_moves_the_hash(tmp_path, online):
    cache = tmp_path / "data.zip"
    online(Resp(200, V1, HEADERS_V1))
    first = _fetch.fetch(URL, cache)
    _new_build()
    online(Resp(200, V2, {"etag": '"v2"'}))
    fp = _fetch.fetch(URL, cache)
    assert cache.read_bytes() == V2
    assert fp.status == "updated" and fp.sha256 != first.sha256
    assert json.loads(_fetch.meta_path(cache).read_text())["etag"] == '"v2"'


def test_a_200_with_the_same_bytes_leaves_the_file_alone(tmp_path, online):
    """A server that ignores the validators must not rewrite the file (or move
    anything keyed on it)."""
    cache = tmp_path / "data.zip"
    online(Resp(200, V1, HEADERS_V1))
    first = _fetch.fetch(URL, cache)
    mtime = cache.stat().st_mtime_ns
    _new_build()
    online(Resp(200, V1, {"etag": '"v1-again"'}))
    fp = _fetch.fetch(URL, cache)
    assert fp.status == "unchanged" and fp.sha256 == first.sha256
    assert cache.stat().st_mtime_ns == mtime


@pytest.mark.parametrize("bad", [
    Resp(200, V2, fail_after=8),                                   # reset mid-body
    Resp(200, V2, {"content-length": str(len(V2) + 100)}),          # short body
])
def test_a_broken_200_never_replaces_the_cache(tmp_path, online, bad, caplog):
    """Atomic: the old copy stands, and no temp file is left behind.

    Mutation: write straight to the cache path instead of a temp -> red (the
    reset leaves half of V2). Remove the Content-Length check -> red (the
    short body replaces V1)."""
    cache = tmp_path / "data.zip"
    online(Resp(200, V1, HEADERS_V1))
    _fetch.fetch(URL, cache)
    _new_build()
    online(bad)
    with caplog.at_level(logging.WARNING):
        fp = _fetch.fetch(URL, cache)
    assert cache.read_bytes() == V1 and fp.status == "kept"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["data.zip", "data.zip.meta.json"]


@pytest.mark.parametrize("failure", [
    httpx.ConnectError("mirror down"),
    Resp(503),
    Resp(404),
])
def test_a_failed_check_with_a_cache_warns_and_carries_on(tmp_path, online, failure, caplog):
    """Mutation: re-raise instead of keeping the copy -> red on all three."""
    cache = tmp_path / "data.zip"
    online(Resp(200, V1, HEADERS_V1))
    first = _fetch.fetch(URL, cache)
    _new_build()
    online(failure)
    with caplog.at_level(logging.WARNING):
        fp = _fetch.fetch(URL, cache)
    assert fp.status == "kept" and fp.sha256 == first.sha256
    assert cache.read_bytes() == V1
    assert any("using the cached copy" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("failure", [httpx.ConnectError("mirror down"), Resp(503), Resp(304)])
def test_a_failed_fetch_with_no_cache_fails(tmp_path, online, failure):
    """A 304 to an unconditional request is not a file either.

    Mutation: return a fingerprint of nothing on failure -> red."""
    online(failure)
    with pytest.raises(_fetch.MissingInput):
        _fetch.fetch(URL, tmp_path / "data.zip")
    assert not (tmp_path / "data.zip").exists()


def test_offline_makes_no_request_and_reads_the_cache(tmp_path, online, monkeypatch):
    """Mutation: ignore offline() in fetch -> red (the Upstream is asked)."""
    cache = tmp_path / "data.zip"
    online(Resp(200, V1, HEADERS_V1))
    first = _fetch.fetch(URL, cache)
    _new_build()
    up = online()                       # any request at all would pop an empty list
    _fetch.set_offline(True)
    fp = _fetch.fetch(URL, cache)
    assert up.calls == []
    assert fp.status == "offline" and fp.sha256 == first.sha256
    with pytest.raises(_fetch.MissingInput, match="offline"):
        _fetch.fetch(URL, tmp_path / "absent.zip")
    assert up.calls == []


def test_the_environment_variable_turns_offline_on(monkeypatch):
    _fetch.set_offline(None)
    monkeypatch.setenv(_fetch.OFFLINE_ENV, "1")
    assert _fetch.offline()
    monkeypatch.setenv(_fetch.OFFLINE_ENV, "0")
    assert not _fetch.offline()


def test_one_process_asks_once_per_input(tmp_path, online):
    """One build reads one snapshot. Mutation: drop the memo -> red (a second
    request, and here the second answer would have been a different file)."""
    cache = tmp_path / "data.zip"
    up = online(Resp(200, V1, HEADERS_V1), Resp(200, V2))
    a = _fetch.fetch(URL, cache)
    b = _fetch.fetch(URL, cache)
    assert len(up.calls) == 1 and a == b and cache.read_bytes() == V1
    assert _fetch.used()[URL]["sha256"] == a.sha256


def test_a_cache_from_before_g2_is_adopted_by_its_mtime(tmp_path, online):
    """No sidecar: the file's mtime is when it was downloaded, so it goes out
    as If-Modified-Since and a 304 adopts the file as it is."""
    cache = tmp_path / "data.zip"
    cache.write_bytes(V1)
    os.utime(cache, (1_788_000_000, 1_788_000_000))
    up = online(Resp(304))
    fp = _fetch.fetch(URL, cache)
    assert up.calls == [{"If-Modified-Since": "Sat, 29 Aug 2026 10:40:00 GMT"}]
    assert fp.status == "unchanged" and cache.read_bytes() == V1
    import hashlib
    assert fp.sha256 == hashlib.sha256(V1).hexdigest()
    assert _fetch.peek(cache) == fp.sha256


def test_a_file_replaced_behind_the_sidecar_is_rehashed(tmp_path, online):
    """A sidecar describing other bytes must not lend them its hash."""
    cache = tmp_path / "data.zip"
    online(Resp(200, V1, HEADERS_V1))
    _fetch.fetch(URL, cache)
    cache.write_bytes(V2)
    _new_build()
    _fetch.set_offline(True)
    import hashlib
    assert _fetch.fetch(URL, cache).sha256 == hashlib.sha256(V2).hexdigest()


# --- end to end: a changed input invalidates exactly what depends on it -----

CSV_V1 = ("type,name,latitude_deg,longitude_deg,iso_country,scheduled_service,iata_code\n"
          "large_airport,Alpha,1.0,2.0,KR,yes,AAA\n")
CSV_V2 = CSV_V1 + "large_airport,Beta,3.0,4.0,JP,yes,BBB\n"


def test_a_changed_input_rebuilds_its_dependent_and_an_unchanged_one_does_not(
        hermetic_build, online, monkeypatch):
    """OurAirports through the real `scheduled_airports()`.

    Mutation: drop the input's sha256 from `_table_cache_path` -> red (the
    third build reads back the one-row table built from V1).
    """
    built = []
    real = airports._atomic_write
    monkeypatch.setattr(airports, "_atomic_write",
                        lambda path, fn: (built.append(path.name), real(path, fn)))

    online(Resp(200, CSV_V1.encode(), {"etag": '"a"'}))
    assert airports.scheduled_airports()["iata"].to_list() == ["AAA"]
    _new_build()
    online(Resp(304))
    assert airports.scheduled_airports()["iata"].to_list() == ["AAA"]
    assert len(built) == 1, "an unchanged input rebuilt its dependent"
    _new_build()
    online(Resp(200, CSV_V2.encode(), {"etag": '"b"'}))
    assert airports.scheduled_airports()["iata"].to_list() == ["AAA", "BBB"]
    assert len(built) == 2
    assert pl.read_parquet(config.BUILD / built[-1]).height == 2


# --- derived FILES named by their archive's hash --------------------------------


def _zip(member: str, data: bytes) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, data)
    return buf.getvalue()


def test_a_new_grip4_archive_is_a_new_raster(tmp_path, online, monkeypatch):
    """The extracted raster used to be found by its bare name, so the first
    archive's raster served every later one. Mutation: drop the hash from the
    raster's name -> red (the second extraction returns the first file)."""
    from transport_maps.sources import roads

    monkeypatch.setattr(config, "CACHE", tmp_path)
    online(Resp(200, _zip("grip4_tp1_dens_m_km2.asc", b"first raster")))
    first = roads._ensure_raster(1)
    assert first.read_bytes() == b"first raster"
    _new_build()
    online(Resp(200, _zip("grip4_tp1_dens_m_km2.asc", b"second raster")))
    second = roads._ensure_raster(1)
    assert second.read_bytes() == b"second raster" and second != first
    assert (tmp_path / "grip4" / "GRIP4_density_tp1.zip").exists(), \
        "the archive must be kept, or there is nothing to check next build"


def test_a_new_water_archive_is_a_new_flatgeobuf(tmp_path, online, monkeypatch):
    """`_flatgeobuf` was keyed on `.exists()` of a bare name. Mutation: name the
    .fgb by the stem alone -> red (the second archive is never converted)."""
    import sys
    import types

    from transport_maps.emit import water

    converted: list[bytes] = []

    class _Reader:
        def __init__(self, shp):
            self.shp = shp

        def __enter__(self):
            return {"geometry_name": "g", "geometry_type": "Polygon", "crs": None}, self

        def __exit__(self, *exc):
            return False

    def write_arrow(reader, out, **kw):
        converted.append(reader.shp.read_bytes())
        out.write_bytes(reader.shp.read_bytes())

    monkeypatch.setitem(sys.modules, "pyogrio", types.SimpleNamespace(
        open_arrow=lambda shp, batch_size: _Reader(shp), write_arrow=write_arrow))
    monkeypatch.setattr(config, "CACHE", tmp_path)
    online(Resp(200, _zip("coast/water.shp", b"coast one")))
    a = water._flatgeobuf(URL)
    _new_build()
    online(Resp(200, _zip("coast/water.shp", b"coast two")))
    b = water._flatgeobuf(URL)
    assert converted == [b"coast one", b"coast two"]
    assert a != b and b.read_bytes() == b"coast two"
