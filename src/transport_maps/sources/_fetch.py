"""Raw inputs: one conditional request per input per build (G2).

Every raw input the pipeline reads -- Natural Earth, OurAirports, GRIP4,
GeoNames, the water polygons -- used to be fetched once into data/cache and
never again. The cache was keyed on `.exists()`, so a build read whatever the
upstream held on the day of the first download, forever, and nothing recorded
which day that was. The owner's policy (2026-10-02): every build asks each
upstream whether its file changed, and re-downloads what did.

`fetch(url, cache)` asks. Beside each cache file sits `<name>.meta.json`: the
validators the server sent (ETag, Last-Modified), the size and sha256 of the
bytes on disk, and when they were fetched. The request is conditional on those
validators, and the answer decides what happens to the cache:

* 304: the cache stands, untouched.
* 200: the body streams to a same-directory temp file, hashed as it arrives,
  and replaces the cache by rename -- unless it hashes to what is already
  there (a server that ignores the validators), in which case the cache is
  left as it was.
* a network or HTTP failure: with a copy on disk the build carries on with it
  and logs a warning -- a mirror down for an hour must not kill a three-day
  build that already holds the file -- and with none it fails.
* offline (`build-all --offline`, or TRANSPORT_MAPS_OFFLINE=1): no request at
  all. The cache is read as it is, and a missing one is an error. This is how
  a past build is reproduced, or a dead one resumed on the inputs it read.

Derived caches key on the returned `Fingerprint.sha256` -- the content, not
the path or the mtime -- so a changed input invalidates exactly what was
computed from it, and an unchanged re-download invalidates nothing.

Checked once per process: the first call for a cache path asks the upstream,
and every later call in the same run gets the same answer, so one build reads
one snapshot even if the upstream moves while it runs. `used()` lists what was
read, for index.json (emit/index.build_identity).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import pathlib
import tempfile
from datetime import UTC, datetime
from email.utils import format_datetime

import httpx

from transport_maps import _io

logger = logging.getLogger(__name__)

OFFLINE_ENV = "TRANSPORT_MAPS_OFFLINE"
CHUNK = 1 << 20

# None: follow OFFLINE_ENV. Set by `build-all --offline` through set_offline().
_offline: bool | None = None
# Cache path -> what this process settled for it. See the module docstring.
_checked: dict[str, Fingerprint] = {}
# Inputs that are not one file (the Wikipedia crawl, the OSM extracts), keyed
# by a name of their own; see record().
_records: dict[str, dict] = {}


class MissingInput(Exception):
    """An input with no usable cached copy that could not be fetched.

    Not a RuntimeError: the crawl and the graph catch RuntimeError for their
    own recoverable failures, and the absence of an input is never one."""


class TruncatedDownload(OSError):
    """A body shorter or longer than the Content-Length the server announced."""


@dataclasses.dataclass(frozen=True)
class Fingerprint:
    """What one raw input was, as read by this build."""

    url: str
    path: pathlib.Path
    sha256: str
    size: int
    etag: str | None
    last_modified: str | None
    fetched_at: str
    # How this run settled it: "downloaded" (no copy before), "updated" (a new
    # one replaced it), "unchanged" (304, or a 200 with the same bytes),
    # "kept" (the check failed and the cached copy was used), "offline".
    status: str

    def record(self) -> dict:
        """The entry index.json carries for this input."""
        out = {"sha256": self.sha256, "size": self.size, "fetchedAt": self.fetched_at}
        if self.etag:
            out["etag"] = self.etag
        if self.last_modified:
            out["lastModified"] = self.last_modified
        return out


def set_offline(flag: bool | None) -> None:
    """Make every later check skip the network (True), or not (False); None
    defers to the environment again."""
    global _offline
    _offline = flag


def offline() -> bool:
    if _offline is not None:
        return _offline
    return os.environ.get(OFFLINE_ENV, "").strip() not in ("", "0")


def reset() -> None:
    """Forget what this process has checked. For tests, and nothing else: a
    build that re-asked mid-run could read two snapshots of one input."""
    _checked.clear()
    _records.clear()


def record(name: str, info: dict) -> None:
    """Register an input that is not a single downloaded file, so `used()`
    reports it beside the files."""
    _records[name] = dict(info)


def checked() -> list[Fingerprint]:
    """Every file input settled in this process, in the order first asked."""
    return list(_checked.values())


def used() -> dict[str, dict]:
    """Every input this process has read, by URL (files) or by name."""
    out = {fp.url: fp.record() for fp in _checked.values()}
    out.update(_records)
    return dict(sorted(out.items()))


def meta_path(cache: pathlib.Path) -> pathlib.Path:
    return cache.with_name(cache.name + ".meta.json")


def _stream(url: str, headers: dict[str, str], timeout: float):
    """The one place this module touches the network; tests replace it.

    Returns a context manager yielding a response with `status_code`,
    `headers`, `iter_bytes()` and `raise_for_status()` -- httpx's shape.
    """
    return httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=timeout)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _sha256_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _read_meta(cache: pathlib.Path) -> dict | None:
    """The sidecar, if it still describes the file on disk; else one rebuilt
    from the file itself, with no validators; None if there is no file.

    A sidecar whose size or mtime no longer matches the file means the file
    was replaced behind this module's back, so its hash and validators are for
    other bytes and are dropped rather than trusted.
    """
    if not cache.exists():
        return None
    st = cache.stat()
    try:
        meta = json.loads(meta_path(cache).read_text(encoding="utf-8"))
        if meta.get("size") == st.st_size and meta.get("mtime_ns") == st.st_mtime_ns \
                and meta.get("sha256"):
            return meta
    except (OSError, ValueError):
        pass
    # A cache from before this helper (or one edited by hand). Every download
    # went through atomic_write, so its mtime is when it arrived; `fetch`
    # sends that as If-Modified-Since, and an upstream that has not changed
    # since answers 304 and the file is adopted as it is.
    return {"url": None, "etag": None, "last_modified": None, "size": st.st_size,
            "mtime_ns": st.st_mtime_ns, "sha256": _sha256_file(cache),
            "fetched_at": datetime.fromtimestamp(st.st_mtime, UTC).replace(microsecond=0)
            .isoformat(), "adopted": True}


def _write_meta(cache: pathlib.Path, meta: dict) -> None:
    st = cache.stat()
    meta = {**meta, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    _io.write_text(meta_path(cache), json.dumps(meta, indent=1, sort_keys=True))


def _conditional_headers(cache: pathlib.Path, meta: dict | None, url: str) -> dict[str, str]:
    if meta is None or meta.get("url") not in (None, url):
        # Nothing on disk, or a copy of ANOTHER URL at this path: neither its
        # validators nor its mtime say anything about this one.
        return {}
    headers = {}
    if meta.get("etag"):
        headers["If-None-Match"] = meta["etag"]
    if meta.get("last_modified"):
        headers["If-Modified-Since"] = meta["last_modified"]
    elif not meta.get("etag"):
        mtime = datetime.fromtimestamp(cache.stat().st_mtime, UTC)
        headers["If-Modified-Since"] = format_datetime(mtime, usegmt=True)
    return headers


def _download(response, cache: pathlib.Path) -> tuple[pathlib.Path, str]:
    """Stream the body to a same-directory temp file. Returns (temp, sha256);
    the caller renames or removes the temp."""
    fd, name = tempfile.mkstemp(dir=cache.parent, prefix=f".{cache.name}.", suffix=".part")
    tmp = pathlib.Path(name)
    h = hashlib.sha256()
    n = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            for chunk in response.iter_bytes(CHUNK):
                fh.write(chunk)
                h.update(chunk)
                n += len(chunk)
        # Content-Length counts the bytes on the wire, which are not the bytes
        # iter_bytes yields when the server compressed them; only an
        # uncompressed body can be checked against it.
        want = response.headers.get("content-length")
        encoding = (response.headers.get("content-encoding") or "identity").lower()
        if want is not None and encoding == "identity" and int(want) != n:
            raise TruncatedDownload(f"received {n:,} bytes of the {int(want):,} announced")
        os.chmod(tmp, _io.ARTIFACT_MODE)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp, h.hexdigest()


def fetch(url: str, cache: pathlib.Path, *, timeout: float = 180) -> Fingerprint:
    """`cache`, checked against `url` once in this process. See the module
    docstring for what each answer does."""
    cache = pathlib.Path(cache)
    key = str(cache)
    if key in _checked:
        return _checked[key]
    cache.parent.mkdir(parents=True, exist_ok=True)
    meta = _read_meta(cache)

    if offline():
        if meta is None:
            raise MissingInput(f"offline, and {url} has no cached copy at {cache}")
        if meta.get("adopted"):
            _write_meta(cache, {k: v for k, v in meta.items() if k != "adopted"})
        status = "offline"
    else:
        status = _check(url, cache, meta, timeout)
        meta = json.loads(meta_path(cache).read_text(encoding="utf-8"))

    fp = Fingerprint(url=url, path=cache, sha256=meta["sha256"], size=meta["size"],
                     etag=meta.get("etag"), last_modified=meta.get("last_modified"),
                     fetched_at=meta["fetched_at"], status=status)
    _checked[key] = fp
    logger.info("input %s: %s (sha256 %s, fetched %s)", cache.name, status,
                fp.sha256[:12], fp.fetched_at)
    return fp


def _check(url: str, cache: pathlib.Path, meta: dict | None, timeout: float) -> str:
    """Ask the upstream and settle the cache and its sidecar. Returns the status."""
    try:
        with _stream(url, _conditional_headers(cache, meta, url), timeout) as r:
            if r.status_code == 304 and meta is not None:
                # A 304 may repeat the validators or omit them; keep what we had
                # for whichever it omits.
                _write_meta(cache, {
                    **{k: v for k, v in meta.items() if k != "adopted"}, "url": url,
                    "etag": r.headers.get("etag") or meta.get("etag"),
                    "last_modified": r.headers.get("last-modified") or meta.get("last_modified"),
                })
                return "unchanged"
            r.raise_for_status()
            if r.status_code != 200:
                raise httpx.HTTPStatusError(f"unexpected {r.status_code} for {url}",
                                            request=getattr(r, "request", None), response=r)
            tmp, sha = _download(r, cache)
            fresh = {"url": url, "etag": r.headers.get("etag"),
                     "last_modified": r.headers.get("last-modified"), "sha256": sha}
    except (httpx.HTTPError, OSError) as exc:
        if meta is None:
            raise MissingInput(f"cannot fetch {url} ({exc}) and there is no cached copy "
                               f"at {cache}") from exc
        logger.warning("could not check %s for changes (%s); using the cached copy of %s",
                       url, exc, meta.get("fetched_at"))
        if meta.get("adopted"):
            _write_meta(cache, {k: v for k, v in meta.items() if k != "adopted"})
        return "kept"

    if meta is not None and meta["sha256"] == sha:
        tmp.unlink(missing_ok=True)
        _write_meta(cache, {**{k: v for k, v in meta.items() if k != "adopted"}, **fresh})
        return "unchanged"
    os.replace(tmp, cache)
    _write_meta(cache, {**fresh, "fetched_at": _now()})
    return "downloaded" if meta is None else "updated"


def peek(cache: pathlib.Path) -> str | None:
    """The sha256 the sidecar records for `cache`, with no request and no
    hashing; None when there is no sidecar that matches the file. For tools
    that must name a derived cache without building it (scripts/expand_origins)."""
    cache = pathlib.Path(cache)
    if not cache.exists():
        return None
    try:
        meta = json.loads(meta_path(cache).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    st = cache.stat()
    if meta.get("size") == st.st_size and meta.get("mtime_ns") == st.st_mtime_ns:
        return meta.get("sha256")
    return None


def get_text(url: str, *, timeout: float = 60) -> str:
    """A small document (Geofabrik's state.txt) fetched unconditionally and not
    cached. Raises on any failure, or when offline; the caller decides what a
    failure means."""
    if offline():
        raise MissingInput(f"offline: not fetching {url}")
    with _stream(url, {}, timeout) as r:
        r.raise_for_status()
        return b"".join(r.iter_bytes(CHUNK)).decode("utf-8")
