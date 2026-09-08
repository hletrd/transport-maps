"""Which country each land cell sits in, and which land borders are shut.

The ground graph joins every pair of adjacent land cells, which quietly asserts
that you can walk across any border on Earth. Some you cannot: the inter-Korean
border is sealed, and a route through it made Seoul look like a road journey
from Vladivostok.
"""

from __future__ import annotations

import hashlib
import pathlib

import httpx
import numpy as np
import polars as pl
import pyogrio
import shapely
from shapely import STRtree

from .. import config
from ._utils import _atomic_write, _params_hash

COUNTRIES_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_cultural/ne_10m_admin_0_countries.zip"
)

# Land borders a traveller cannot simply cross. Each is a long-standing, total
# closure to through traffic, not a hard crossing or a visa nuisance -- borders
# that are merely slow belong in a border-time model, not here.
#
# Deliberately NOT included: India-Pakistan (Wagah does open), Russia-Ukraine
# and other borders whose status is contested or changing. A wrong entry here
# silently deletes real routes, so the bar is "obviously and durably shut".
CLOSED_BORDERS: frozenset[frozenset[str]] = frozenset({
    frozenset({"PRK", "KOR"}),   # inter-Korean: sealed since 1953
    frozenset({"ARM", "AZE"}),   # closed since 1991
    frozenset({"ARM", "TUR"}),   # closed since 1993
    frozenset({"DZA", "MAR"}),   # closed since 1994
    frozenset({"ISR", "LBN"}),   # no crossing open to travellers
    frozenset({"ISR", "SYR"}),   # no crossing open to travellers
})

UNKNOWN = ""


def _download() -> pathlib.Path:
    cached = config.CACHE / "ne_10m_admin_0_countries.zip"
    if not cached.exists():
        r = httpx.get(COUNTRIES_URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        _atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    return cached


def _polygons() -> tuple[list, list[str]]:
    path = _download().resolve()
    meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    codes = table.column("ADM0_A3").to_pylist()
    geoms = shapely.from_wkb(table.column(meta["geometry_name"] or "wkb_geometry").to_pylist())
    return list(geoms), [c or UNKNOWN for c in codes]


def cell_country(cells: list[str]) -> np.ndarray:
    """ISO A3 code per cell, by centroid. `UNKNOWN` where no polygon contains it.

    Centroid rather than footprint on purpose: a cell straddling a border has
    to be assigned to ONE side, and the centroid is the defensible choice. The
    consequence is that a closed border is cut with cell-sized granularity,
    which at resolution 5 is about 8 km -- finer than the feature it models.
    """
    # Hash every cell, not just the count and the ends: two different cell
    # universes of the same length would otherwise share a cache entry, which
    # is the exact failure this helper exists to prevent elsewhere.
    key = _params_hash(COUNTRIES_URL, hashlib.sha256("".join(cells).encode()).hexdigest())
    cached = config.CACHE / f"cell_country-{key}.parquet"
    if cached.exists():
        return pl.read_parquet(cached)["country"].to_numpy()

    import h3

    geoms, codes = _polygons()
    tree = STRtree(geoms)
    latlng = [h3.cell_to_latlng(c) for c in cells]
    points = shapely.points([p[1] for p in latlng], [p[0] for p in latlng])

    out = np.array([UNKNOWN] * len(cells), dtype=object)
    hit_geom, hit_point = tree.query(points, predicate="within")
    for gi, pi in zip(hit_geom, hit_point):
        # query returns (input index, tree index) pairs; first match wins, and
        # overlapping claims are rare enough that arbitrating them would be
        # inventing a foreign policy.
        if out[gi] == UNKNOWN:
            out[gi] = codes[pi]

    df = pl.DataFrame({"country": out.astype(str)})
    _atomic_write(cached, lambda tmp: df.write_parquet(tmp))
    return df["country"].to_numpy()


def is_closed(a: str, b: str) -> bool:
    """True when the land border between two countries is shut to travellers."""
    if not a or not b or a == b:
        return False
    return frozenset({a, b}) in CLOSED_BORDERS
