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

import argparse, json, math, os, sys, tarfile, urllib.request
from pathlib import Path

GITHUB_RELEASES = "https://api.github.com/repos/adsblol/globe_history_2026/releases?per_page=30"
# A leg must look like a real scheduled flight, not a circuit, tow or test hop.
MIN_MINUTES, MAX_MINUTES = 25.0, 1000.0
MIN_KM, MAX_KM = 150.0, 15000.0
# Above this the aircraft is unambiguously en route, not taxiing or in a pattern.
CRUISE_FLOOR_FT = 10000.0
# A gap this long means the receiver lost it, not that the flight ended.
MAX_GAP_S = 900.0


def great_circle_km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0088 * 2 * math.asin(math.sqrt(h))


def legs_from_trace(doc) -> list[tuple[float, float]]:
    """Airborne legs as (minutes, km). One trace can hold several flights."""
    rows = doc.get("trace") or []
    out, seg = [], []
    prev_t = None
    for r in rows:
        try:
            t, lat, lon, alt = r[0], r[1], r[2], r[3]
        except (IndexError, TypeError):
            continue
        if lat is None or lon is None:
            continue
        airborne = isinstance(alt, (int, float)) and alt >= CRUISE_FLOOR_FT
        broke = prev_t is not None and (t - prev_t) > MAX_GAP_S
        if airborne and not broke:
            seg.append((t, lat, lon))
        else:
            if len(seg) >= 2:
                out.append(seg)
            seg = [(t, lat, lon)] if airborne else []
        prev_t = t
    if len(seg) >= 2:
        out.append(seg)

    legs = []
    for s in out:
        minutes = (s[-1][0] - s[0][0]) / 60.0
        km = great_circle_km(s[0][1:], s[-1][1:])
        if MIN_MINUTES <= minutes <= MAX_MINUTES and MIN_KM <= km <= MAX_KM:
            legs.append((round(minutes, 2), round(km, 2)))
    return legs


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
    ap.add_argument("--instance", default="prod-0")
    ap.add_argument("--cache", default=str(Path.home() / "adsb-cache"))
    ap.add_argument("--out", default="adsb_legs.json")
    ap.add_argument("--limit", type=int, default=0, help="stop after N traces (0 = all)")
    args = ap.parse_args()

    archive = ensure_archive(Path(args.cache), args.instance)
    legs: list[tuple[float, float]] = []
    seen = 0
    with tarfile.open(archive, "r|") as tar:      # streaming: never unpacks to disk
        for member in tar:
            if not (member.isfile() and "/traces/" in member.name and member.name.endswith(".json")):
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            try:
                legs.extend(legs_from_trace(json.loads(fh.read())))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            seen += 1
            if seen % 20000 == 0:
                print(f"  {seen:,} traces -> {len(legs):,} legs", flush=True)
            if args.limit and seen >= args.limit:
                break

    Path(args.out).write_text(json.dumps({
        "source": "adsb.lol globe_history",
        "licence": "ODbL-1.0",
        "archive": archive.name,
        "traces_read": seen,
        "legs": legs,
    }))
    print(f"  {seen:,} traces -> {len(legs):,} legs -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
