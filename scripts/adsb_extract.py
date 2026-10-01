#!/usr/bin/env python3
"""Extract airborne-leg samples from an adsb.lol daily archive.

Runs on the server that has the bandwidth and the cache, not on a laptop. One
archive is downloaded per day-instance and kept forever; re-running costs no
network at all. adsb.lol data is ODbL 1.0 — attribution and share-alike, not
the no-redistribution terms the commercial providers impose.

Output is a compact JSON of (airborne_minutes, great_circle_km) pairs, which is
all `calibrate.fit.fit_airborne` needs to recover the climb/descent penalty and
effective cruise speed. Raw traces never leave the server.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "adsblol/globe_history_2026"
GITHUB_RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
# Everything below this point trusts nothing the releases API returns. The tag
# becomes a file name under the cache and each asset URL is fetched and written
# into it, so a tag of `../../.ssh/authorized_keys`, a URL that points at some
# other host, or an http:// hop that a man in the middle can answer, would each
# turn a calibration download into a write or a fetch the operator never asked
# for (SEC-23).
#
# A tag or asset name is one path component from a deliberately small alphabet:
# what adsb.lol actually publishes is `v2026.09.30-planes-readsb-prod-0` and
# `v2026.09.30-planes-readsb-prod-0.tar.aa`. No slash, no backslash, no NUL,
# and it may not start with a dot, which rules out `.`, `..` and hidden files
# in one rule rather than a list of special cases.
SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
# Where a release asset may come from. GitHub answers the browser download URL
# with a 302 to its asset CDN, so the redirect target is allowed too -- but
# only these hosts, only over https, and the first URL must be this repo's own
# download path.
DOWNLOAD_HOST = "github.com"
REDIRECT_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})
# A day's archive is two parts of at most 2.0 GB each (measured 2026-10-02:
# 2,000,000,000 + 1,978,338,304 bytes for prod-0). A part is refused above 4 GB
# and a day above 16 GB: generous enough for a busier day, small enough that a
# hostile or broken release cannot fill the cache disk.
MAX_PART_BYTES = 4 * 10**9
MAX_ARCHIVE_BYTES = 16 * 10**9
# A leg must look like a real scheduled flight, not a circuit, tow or test hop.
MIN_MINUTES, MAX_MINUTES = 25.0, 1000.0
MIN_KM, MAX_KM = 150.0, 15000.0
# A segment must reach this at some point to count as a real en-route flight
# rather than a circuit, tow or test hop. It gates the leg; it does not clip it.
CRUISE_FLOOR_FT = 10000.0
# Above this the aircraft is off the runway. The leg is measured from here so it
# spans wheels-off to wheels-on: clipping at the cruise floor instead would drop
# climb-out and descent from BOTH the time and the distance, which biases the
# fitted intercept toward zero and makes it unusable against a full
# airport-to-airport distance.
AIRBORNE_FLOOR_FT = 500.0
# A gap this long means the receiver lost it, not that the flight ended.
MAX_GAP_S = 900.0


def great_circle_km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def legs_from_trace(doc) -> tuple[list, list]:
    """Return (airborne_legs, cruise_legs) as (minutes, km) pairs.

    `airborne` spans the whole flight and is what the model wants. `cruise` is
    the above-10,000 ft window, kept only so the two fits can be compared.
    One trace can hold several flights; ground contact separates them.
    """
    rows = doc.get("trace") or []
    out, seg, peak = [], [], 0.0
    prev_t = None

    def flush():
        if len(seg) >= 2 and peak >= CRUISE_FLOOR_FT:
            out.append(list(seg))

    for r in rows:
        try:
            t, lat, lon, alt = r[0], r[1], r[2], r[3]
        except (IndexError, TypeError):
            continue
        if lat is None or lon is None:
            continue
        numeric = isinstance(alt, (int, float))
        aloft = numeric and alt >= AIRBORNE_FLOOR_FT
        broke = prev_t is not None and (t - prev_t) > MAX_GAP_S
        if aloft and not broke:
            seg.append((t, lat, lon, alt))
            peak = max(peak, alt)
        else:
            flush()
            seg = [(t, lat, lon, alt)] if aloft else []
            peak = alt if aloft else 0.0
        prev_t = t
    flush()

    airborne_legs, cruise_legs = [], []
    for s in out:
        for points, sink in ((s, airborne_legs),
                             ([q for q in s if q[3] >= CRUISE_FLOOR_FT], cruise_legs)):
            if len(points) < 2:
                continue
            minutes = (points[-1][0] - points[0][0]) / 60.0
            km = great_circle_km(points[0][1:3], points[-1][1:3])
            if MIN_MINUTES <= minutes <= MAX_MINUTES and MIN_KM <= km <= MAX_KM:
                sink.append((round(minutes, 2), round(km, 2)))
    return airborne_legs, cruise_legs


def safe_name(name, what: str) -> str:
    """`name` if it is one safe path component, else stop the run."""
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
        raise SystemExit(f"refusing unsafe {what} from the releases API: {name!r}")
    return name


def check_asset_url(url, tag: str, name: str) -> str:
    """`url` if it is this repo's https download path for `tag`/`name`."""
    parts = urllib.parse.urlsplit(url if isinstance(url, str) else "")
    expected = f"/{REPO}/releases/download/{tag}/{name}"
    if (parts.scheme != "https" or parts.hostname != DOWNLOAD_HOST
            or parts.port is not None or parts.path != expected
            or parts.query or parts.fragment or parts.username or parts.password):
        raise SystemExit(f"refusing asset URL {url!r}: expected https://{DOWNLOAD_HOST}{expected}")
    return url


class _AllowListRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to an https URL on an allow-listed host.

    urllib's default handler follows a 302 to any http, https or ftp URL, so
    checking the first URL alone would let the response send the download
    anywhere.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlsplit(newurl)
        if parts.scheme != "https" or parts.hostname not in REDIRECT_HOSTS:
            raise urllib.error.HTTPError(
                newurl, code, f"refusing redirect to {newurl!r}", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_AllowListRedirects)


def newest_assets(instance: str) -> tuple[str, list[tuple[str, int]]]:
    """(tag, [(url, declared size), ...]) of the newest release for `instance`.

    Every name, URL and size is checked before it is returned; nothing the API
    says reaches the file system or the network unvalidated.
    """
    with _opener.open(GITHUB_RELEASES, timeout=60) as r:
        releases = json.load(r)
    for rel in releases:
        tag = rel.get("tag_name")
        if not isinstance(tag, str) or instance not in tag:
            continue
        tag = safe_name(tag, "release tag")
        assets = []
        for a in rel.get("assets", []):
            name = safe_name(a.get("name"), "asset name")
            url = check_asset_url(a.get("browser_download_url"), tag, name)
            size = a.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_PART_BYTES:
                raise SystemExit(f"refusing asset {name}: declared size {size!r} is "
                                 f"outside 1..{MAX_PART_BYTES:,} bytes")
            assets.append((url, size))
        if assets:
            total = sum(size for _, size in assets)
            if total > MAX_ARCHIVE_BYTES:
                raise SystemExit(f"refusing release {tag}: {total:,} bytes declared, "
                                 f"cap is {MAX_ARCHIVE_BYTES:,}")
            return tag, sorted(assets)
    raise SystemExit(f"no release found for instance {instance!r}")


def ensure_archive(cache: Path, instance: str) -> Path:
    """Download once, keep forever. Parts are concatenated into one tar."""
    tag, assets = newest_assets(instance)
    target = cache / f"{tag}.tar"
    # Belt and braces: `safe_name` already forbids a separator, but the
    # property that matters is that the file lands directly in `cache`.
    if target.parent != cache:
        raise SystemExit(f"refusing archive path outside the cache: {target}")
    if target.exists() and target.stat().st_size > 0:
        print(f"  cached: {target.name} ({target.stat().st_size/1e9:.2f} GB)", flush=True)
        return target
    cache.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".partial")
    try:
        with tmp.open("wb") as fh:
            for u, declared in assets:          # .tar.aa, .tar.ab ... in order
                print(f"  downloading {u.rsplit('/', 1)[-1]}", flush=True)
                got = 0
                with _opener.open(u, timeout=900) as r:
                    while chunk := r.read(1 << 22):
                        got += len(chunk)
                        # The declared size is the cap, enforced on the bytes
                        # actually received: a server that keeps sending is
                        # stopped here, not when the disk fills.
                        if got > declared:
                            raise SystemExit(f"{u} sent more than its declared "
                                             f"{declared:,} bytes; refusing")
                        fh.write(chunk)
                if got != declared:
                    raise SystemExit(f"{u} sent {got:,} of its declared {declared:,} bytes")
    except BaseException:
        # A refused or broken download must not leave a partial behind that a
        # later reader could mistake for a part of the archive.
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, target)
    print(f"  stored {target.name} ({target.stat().st_size/1e9:.2f} GB)", flush=True)
    return target


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", default="",
                    help="use this already-downloaded archive and make no "
                         "network request at all")
    ap.add_argument("--instance", default="prod-0")
    ap.add_argument("--cache", default=str(Path.home() / "adsb-cache"))
    ap.add_argument("--out", default="adsb_legs.json")
    ap.add_argument("--limit", type=int, default=0, help="stop after N traces (0 = all)")
    args = ap.parse_args()

    if args.archive:
        archive = Path(args.archive)
        if not archive.exists():
            raise SystemExit(f"no such archive: {archive}")
        print(f"  reusing cached {archive.name} (no network)", flush=True)
    else:
        archive = ensure_archive(Path(args.cache), args.instance)
    legs: list[tuple[float, float]] = []
    cruise_legs: list[tuple[float, float]] = []
    seen = 0
    unreadable = 0
    with tarfile.open(archive, "r|") as tar:      # streaming: never unpacks to disk
        for member in tar:
            if not (member.isfile() and "/traces/" in member.name and member.name.endswith(".json")):
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            seen += 1
            raw = fh.read()
            # Trace files are gzip-compressed despite the .json extension.
            # Reading them as text raises UnicodeDecodeError on every single
            # one -- which an over-broad `except: continue` will happily
            # swallow, reporting a clean run over zero traces.
            if raw[:2] == b"\x1f\x8b":
                try:
                    raw = gzip.decompress(raw)
                except OSError:
                    unreadable += 1
                    continue
            try:
                a, c = legs_from_trace(json.loads(raw))
                legs.extend(a)
                cruise_legs.extend(c)
            except (json.JSONDecodeError, UnicodeDecodeError):
                unreadable += 1
                continue
            if seen % 20000 == 0:
                print(f"  {seen:,} traces -> {len(legs):,} legs", flush=True)
            if args.limit and seen >= args.limit:
                break

    # A run that could not read most of what it opened is a failed run, not an
    # empty day. Say so instead of writing a confident, empty result.
    if seen and unreadable > 0.5 * seen:
        raise SystemExit(
            f"{unreadable} of {seen} traces were unreadable; refusing to write a "
            "result derived from almost nothing"
        )

    Path(args.out).write_text(json.dumps({
        "source": "adsb.lol globe_history",
        "licence": "ODbL-1.0",
        "archive": archive.name,
        "traces_read": seen,
        "unreadable": unreadable,
        "legs": legs,
        "cruise_legs": cruise_legs,
    }))
    print(f"  {seen:,} traces ({unreadable:,} unreadable) -> {len(legs):,} legs -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
