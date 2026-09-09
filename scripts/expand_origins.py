#!/usr/bin/env python3
"""Add every major city to data/origins.toml from GeoNames cities15000.

    uv run python scripts/expand_origins.py [--min-pop 1000000] [--capital-pop 250000]

A city qualifies by population, or as a national capital (PPLC) above a lower
bar. Anything within 40 km of an origin already listed is skipped, so the
hand-picked entries and their coordinates stay as they are. Appends; never
edits.

GeoNames rather than Natural Earth populated places: the first run on Natural
Earth produced "Shenyeng" and gave Amaravati 5.8 million people. GeoNames
(CC BY 4.0) carries proper names, ASCII names and current populations.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import tomllib
import unicodedata
import zipfile

import httpx

from transport_maps import _io, config
from transport_maps.emit.index import _SLUG_RE

NEAR_KM = 40.0
GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
# geonameid, name, asciiname, alternatenames, latitude, longitude, feature
# class, feature code, country code, cc2, admin1, admin2, admin3, admin4,
# population, elevation, dem, timezone, modification date
COLS = ("id", "name", "ascii", "alt", "lat", "lon", "fclass", "fcode", "cc", "cc2",
        "a1", "a2", "a3", "a4", "pop", "elev", "dem", "tz", "mod")


def geonames() -> list[dict]:
    cached = config.CACHE / "cities15000.zip"
    if not cached.exists():
        r = httpx.get(GEONAMES_URL, follow_redirects=True, timeout=120)
        r.raise_for_status()
        _io.write_bytes(cached, r.content)
    with zipfile.ZipFile(cached) as z:
        text = z.read("cities15000.txt").decode("utf-8")
    return [dict(zip(COLS, row)) for row in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)]


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s


def km(a, b, c, d):
    r = math.pi / 180
    x = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(x))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pop", type=int, default=1_000_000)
    ap.add_argument("--capital-pop", type=int, default=250_000)
    args = ap.parse_args()

    path = config.ROOT / "data" / "origins.toml"
    existing = tomllib.loads(path.read_text(encoding="utf-8"))["origin"]
    slugs = {o["slug"] for o in existing}

    rows = geonames()
    added = []
    for r in sorted(rows, key=lambda r: -int(r["pop"] or 0)):
        name, country = r["name"], r["cc"]
        pop = int(r["pop"] or 0)
        capital = r["fcode"] == "PPLC"
        if not (pop >= args.min_pop or (capital and pop >= args.capital_pop)):
            continue
        lat, lon = float(r["lat"]), float(r["lon"])
        if any(km(lat, lon, o["lat"], o["lon"]) < NEAR_KM for o in existing + added):
            continue
        # A name with no ASCII form slugifies to nothing, and the old fallback
        # collapsed it to the bare country code, so the second such city was
        # silently skipped. The GeoNames id is always unique.
        slug = slugify(r["ascii"] or name) or f"city-{r['id']}"
        if slug in slugs:
            slug = f"{slug}-{country.lower()}"
        if slug in slugs:
            slug = f"{slug}-{r['id']}"
        assert _SLUG_RE.fullmatch(slug), slug
        slugs.add(slug)
        added.append({"slug": slug, "name": name, "lat": round(lat, 4), "lon": round(lon, 4),
                      "country": country, "pop": pop, "capital": capital})

    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n# Added by scripts/expand_origins.py: population >= {args.min_pop:,},"
                 f" or a national capital >= {args.capital_pop:,} (GeoNames cities15000, CC BY 4.0).\n")
        for o in added:
            # json.dumps is valid TOML basic-string quoting for these names
            # (quotes and backslashes escaped); f-string quoting was not.
            fh.write(f'\n[[origin]]\nslug = "{o["slug"]}"\nname = {json.dumps(o["name"], ensure_ascii=False)}\n'
                     f'lat = {o["lat"]}\nlon = {o["lon"]}\n')
    print(f"  {len(existing)} existing, {len(added)} added -> {len(existing) + len(added)} origins")
    for o in added[:12]:
        print(f"    {o['name']:<22} {o['country']:<18} {o['pop']:>10,}{'  capital' if o['capital'] else ''}")
    print("    ...")


if __name__ == "__main__":
    main()
