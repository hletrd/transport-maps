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

import h3
import pyarrow.parquet as pq

from transport_maps import config
from transport_maps.emit.index import _SLUG_RE
from transport_maps.sources import _fetch, landmask

NEAR_KM = 40.0
GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
# geonameid, name, asciiname, alternatenames, latitude, longitude, feature
# class, feature code, country code, cc2, admin1, admin2, admin3, admin4,
# population, elevation, dem, timezone, modification date
COLS = ("id", "name", "ascii", "alt", "lat", "lon", "fclass", "fcode", "cc", "cc2",
        "a1", "a2", "a3", "a4", "pop", "elev", "dem", "tz", "mod")


def geonames() -> list[dict]:
    # Checked against GeoNames on every run (G2); the same cache file the
    # page's gazetteer (emit/places.py) reads.
    cached = _fetch.fetch(GEONAMES_URL, config.CACHE / "cities15000.zip", timeout=120).path
    with zipfile.ZipFile(cached) as z:
        text = z.read("cities15000.txt").decode("utf-8")
    return [dict(zip(COLS, row)) for row in csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)]


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s


def _land_cells_if_built() -> set[str] | None:
    """The solver's land mask, but only if a build has already produced it.

    Deliberately not built on demand: that is a 1.5 GB download and several
    minutes, and this script is also run on machines that never build. When
    the mask is absent the check is SKIPPED AND SAID SO -- a silent skip here
    would be the same vacuous pass CLAUDE.md's testing rule warns about.
    """
    sources = landmask._known_sources()
    if sources is None:
        print("  land check SKIPPED: the Natural Earth archives have not been fetched")
        return None
    path = landmask._cells_cache_path(config.SOLVE_RES, sources)
    if not path.exists():
        print(f"  land check SKIPPED: {path.name} has not been built")
        return None
    cells = set(pq.read_table(path).column(0).to_pylist())
    print(f"  land check against {path.name} ({len(cells):,} cells)")
    return cells


def _on_or_near_land(lat: float, lon: float, land: set[str]) -> bool:
    """The same two-ring test `origin_node` will apply when it solves this."""
    cell = h3.latlng_to_cell(lat, lon, config.SOLVE_RES)
    if cell in land:
        return True
    return any(n in land for ring in (1, 2) for n in h3.grid_ring(cell, ring))


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
    land = _land_cells_if_built()
    added = []
    rejected: list[tuple[str, str, float, float]] = []
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
        # A city centre is on land by definition; a city centre's GEONAMES
        # COORDINATE is not always on the 1:10m land outline the solver uses.
        # This script appended 911 origins on 2026-09-14 with no check at all,
        # and one of them -- Kota Kinabalu -- landed on a cell the mask does
        # not have. `origin_node` now snaps within two rings, so a near miss is
        # harmless; what is not harmless is a coordinate with no land within
        # about 13 km, which is a typo or a swapped pair and which still aborts
        # the build. Rejecting it here costs one set lookup and turns a
        # multi-day failure into a line of output.
        if land is not None and not _on_or_near_land(lat, lon, land):
            rejected.append((slug, name, lat, lon))
            continue
        slugs.add(slug)
        added.append({"slug": slug, "name": name, "lat": round(lat, 4), "lon": round(lon, 4),
                      "country": country, "pop": pop, "capital": capital})

    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n# Added by scripts/expand_origins.py: population >= {args.min_pop:,},"
                 f" or a national capital >= {args.capital_pop:,} (GeoNames cities15000, CC BY 4.0).\n")
        for o in added:
            # json.dumps is valid TOML basic-string quoting for these names
            # (quotes and backslashes escaped); f-string quoting was not.
            # `country` is read from GeoNames a few lines above and used to
            # disambiguate a slug, and was then thrown away -- so the 553-origin
            # run produced four pairs of origins with the SAME NAME (Hyderabad,
            # Suzhou, Fuzhou, Taizhou), distinguishable only by a slug the
            # visitor never sees. The list sorts by name, so each pair is two
            # adjacent identical rows. Writing it costs nothing and lets the
            # page tell them apart without a gazetteer lookup.
            fh.write(f'\n[[origin]]\nslug = "{o["slug"]}"\nname = {json.dumps(o["name"], ensure_ascii=False)}\n'
                     f'lat = {o["lat"]}\nlon = {o["lon"]}\n'
                     f'country = "{o["country"]}"\n')
    print(f"  {len(existing)} existing, {len(added)} added -> {len(existing) + len(added)} origins")
    if rejected:
        print(f"  {len(rejected)} rejected: no land cell within two rings of the coordinate")
        for slug, name, lat, lon in rejected[:12]:
            print(f"    {name:<22} {slug:<24} {lat:.4f}, {lon:.4f}")
    for o in added[:12]:
        print(f"    {o['name']:<22} {o['country']:<18} {o['pop']:>10,}{'  capital' if o['capital'] else ''}")
    print("    ...")


if __name__ == "__main__":
    main()
