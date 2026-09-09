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
import tarfile
import urllib.request
from pathlib import Path

GITHUB_RELEASES = "https://api.github.com/repos/adsblol/globe_history_2026/releases?per_page=30"
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


def newest_asset_urls(instance: str) -> tuple[str, list[str]]:
    with urllib.request.urlopen(GITHUB_RELEASES, timeout=60) as r:
        releases = json.load(r)
    for rel in releases:
        if instance in rel["tag_name"]:
            urls = [a["browser_download_url"] for a in rel.get("assets", [])]
            if urls:
                return rel["tag_name"], sorted(urls)
    raise SystemExit(f"no release found for instance {instance!r}")


def ensure_archive(cache: Path, instance: str) -> Path:
    """Download once, keep forever. Parts are concatenated into one tar."""
    tag, urls = newest_asset_urls(instance)
    target = cache / f"{tag}.tar"
    if target.exists() and target.stat().st_size > 0:
        print(f"  cached: {target.name} ({target.stat().st_size/1e9:.2f} GB)", flush=True)
        return target
    cache.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".partial")
    with tmp.open("wb") as fh:
        for u in urls:                      # .tar.aa, .tar.ab ... in order
            print(f"  downloading {u.rsplit('/', 1)[-1]}", flush=True)
            with urllib.request.urlopen(u, timeout=900) as r:
                while chunk := r.read(1 << 22):
                    fh.write(chunk)
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
