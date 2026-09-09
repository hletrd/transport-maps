"""Project-wide constants and paths. No I/O beyond directory creation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = DATA / "cache"
BUILD = DATA / "build"
DIST = ROOT / "dist"

# H3 resolution for the solver grid: 548,557 land cells at ~253 km^2 each (measured).
SOLVE_RES = 6
# Dense regions are solved on the next resolution down: 1.2 km cells instead
# of 3.2 km. Which cells count as dense is decided in graph/refine.py.
FINE_RES = 7
# H3 resolution for the shipped hover array: 82,983 cells -> 165,966 bytes as uint16.
HOVER_RES = 4

# Upper edge of each isochrone band, in minutes. The 11th band is open-ended.
# Thirty-six bands on a geometric ladder from 30 minutes to 72 hours, ratio
# about 1.155, so the map reads as a continuous gradient rather than eleven
# lumps that put 12 h and 18 h in the same color. Each band is thin enough that
# with corner smoothing and the seam stroke the steps vanish at any zoom.
BAND_EDGES_MIN: tuple[int, ...] = (30, 35, 40, 45, 55, 60, 70, 80, 95, 110, 125, 145, 170, 195, 225, 260, 300, 350, 400, 465, 535, 620, 715, 825, 955, 1100, 1270, 1470, 1695, 1960, 2260, 2615, 3020, 3485, 4025, 4320)

# uint16 sentinel for "no path exists".
UNREACHABLE = 65535


def ensure_dirs() -> None:
    for d in (CACHE, BUILD, DIST):
        d.mkdir(parents=True, exist_ok=True)
