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
    # North Korea's other borders admit no independent traveller either --
    # entry is by escorted tour, by air or by the Beijing train, never by a
    # visitor driving up to the crossing. Leaving these open made Pyongyang
    # reachable overland from Seoul via a loop through China.
    frozenset({"PRK", "CHN"}),
    frozenset({"PRK", "RUS"}),
    frozenset({"ARM", "AZE"}),   # closed since 1991
    frozenset({"ARM", "TUR"}),   # closed since 1993
    frozenset({"DZA", "MAR"}),   # closed since 1994
    frozenset({"ISR", "LBN"}),   # no crossing open to travellers
    frozenset({"ISR", "SYR"}),   # no crossing open to travellers
    frozenset({"IND", "PAK"}),   # Wagah admits a trickle by permit; shut to through traffic
    frozenset({"RUS", "UKR"}),   # war
    frozenset({"ERI", "ETH"}),   # reopened 2018, shut again
    frozenset({"BGD", "MMR"}),   # no crossing open to foreigners
    frozenset({"AFG", "PAK"}),   # Torkham closed to third-country nationals
})

UNKNOWN = ""


def _download() -> pathlib.Path:
    cached = config.CACHE / "ne_10m_admin_0_countries.zip"
    if not cached.exists():
        r = httpx.get(COUNTRIES_URL, follow_redirects=True, timeout=180)
        r.raise_for_status()
        _atomic_write(cached, lambda tmp: tmp.write_bytes(r.content))
    return cached


# Natural Earth's ISO_A2 is -99 for a handful of territories; ADM0_A3 never is,
# so it stays the cell key and this is only for the immigration-zone lookup.
A3_TO_A2: dict[str, str] = {}


def _polygons() -> tuple[list, list[str]]:
    path = _download().resolve()
    meta, table = pyogrio.read_arrow(f"/vsizip/{path}")
    codes = table.column("ADM0_A3").to_pylist()
    a2 = table.column("ISO_A2_EH").to_pylist() if "ISO_A2_EH" in table.schema.names \
         else table.column("ISO_A2").to_pylist()
    for c3, c2 in zip(codes, a2):
        if c3 and c2 and c2 != "-99":
            A3_TO_A2[c3] = c2
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
    key = _params_hash(COUNTRIES_URL, "filled-blanks-nearest", hashlib.sha256("".join(cells).encode()).hexdigest())
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

    out = _fill_blanks(cells, out)
    df = pl.DataFrame({"country": out.astype(str)})
    _atomic_write(cached, lambda tmp: df.write_parquet(tmp))
    return df["country"].to_numpy()


def _fill_blanks(cells: list[str], out: np.ndarray, passes: int = 3) -> np.ndarray:
    """Give a country to every cell whose centroid fell in the sea.

    31,022 coastal cells -- 5.2% of land -- had no country, and a cell with
    none is a bridge across every closed border: the inter-Korean cut held on
    the DMZ itself yet Kaesong was reachable from Seoul in 2.5 h by stepping
    onto a blank Han-estuary cell and off it into the North. Each blank takes
    the commonest country among its assigned neighbours; a few passes reach
    the blanks that only touch other blanks. Whichever side a blank inherits,
    one of its edges then crosses the closed pair and is cut.
    """
    from collections import Counter

    import h3

    pos = {c: i for i, c in enumerate(cells)}
    out = out.copy()
    for _ in range(passes):
        blanks = np.where(out == UNKNOWN)[0]
        if len(blanks) == 0:
            break
        fill = {}
        for i in blanks:
            votes = Counter(out[pos[n]] for n in h3.grid_disk(cells[i], 1)
                            if n in pos and out[pos[n]] != UNKNOWN)
            if votes:
                fill[i] = votes.most_common(1)[0][0]
        if not fill:
            break
        for i, c in fill.items():
            out[i] = c
    # Whatever is left has no assigned neighbour at all -- isolated atolls and
    # islets whose every neighbour is water. Take the nearest assigned cell.
    blanks = np.where(out == UNKNOWN)[0]
    if len(blanks) and len(blanks) < len(out):      # nothing to copy from if all blank
        from scipy.spatial import cKDTree

        latlng = np.array([h3.cell_to_latlng(c) for c in cells])
        assigned = np.where(out != UNKNOWN)[0]
        xyz = lambda ll: np.column_stack([
            np.cos(np.radians(ll[:, 0])) * np.cos(np.radians(ll[:, 1])),
            np.cos(np.radians(ll[:, 0])) * np.sin(np.radians(ll[:, 1])),
            np.sin(np.radians(ll[:, 0]))])
        _, nearest = cKDTree(xyz(latlng[assigned])).query(xyz(latlng[blanks]))
        out[blanks] = out[assigned[nearest]]
    return out


def iso2(a3: str) -> str:
    """ISO-2 for an ADM0_A3, loading the table on first use."""
    if not A3_TO_A2:
        _polygons()
    return A3_TO_A2.get(a3, a3)


def is_closed(a: str, b: str) -> bool:
    """True when the land border between two countries is shut to travellers."""
    if not a or not b or a == b:
        return False
    return frozenset({a, b}) in CLOSED_BORDERS
