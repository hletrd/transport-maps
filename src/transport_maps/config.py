"""Project-wide constants and paths. No I/O beyond directory creation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = DATA / "cache"
BUILD = DATA / "build"
DIST = ROOT / "dist"

# Base H3 resolution of the solver grid: 4,091,715 land cells at resolution 6
# (measured; about 36 km^2 each), refined to FINE_RES where the grid is dense.
SOLVE_RES = 6
# Dense regions are solved on the next resolution down: cells 2.4 km across
# (5.2 km^2) instead of 6.5 km (36 km^2), h3 v4 averages. Which cells count as
# dense is decided in graph/refine.py.
FINE_RES = 7
# H3 resolution for the shipped hover array: 90,740 cells over the res-6
# universe (measured) -> 181,480 bytes as uint16. This is the grid that
# addresses the arrival-airport, mode-breakdown and rail arrays as well as the
# time array, so it cannot be replaced by a finer one without re-emitting all
# four (90.1 MB per origin, measured). It is joined by READING_RES below, not
# replaced.
HOVER_RES = 4

# H3 resolution of the TIME READING a visitor gets when they point at the
# globe. Equal to SOLVE_RES, so the number read is the value of the cell the
# base band is painted from: at HOVER_RES it was a cell ~45 km across and
# 28.0% of sampled land points read a band the map does not paint under them
# (measured, plan/deferred.md AA6).
#
# Where graph/refine.py split a cell the band is painted at FINE_RES, which is
# still finer than this: the reading then averages over seven sub-cells. The
# page says so rather than claiming an agreement that does not hold.
READING_RES = SOLVE_RES
# The readings ship as fixed-width blocks keyed by their res-3 parent, so the
# slot within a block is arithmetic and NO per-origin cell-id list is needed:
# 14,598 res-3 parents hold land (measured) x 343 slots x uint16 = 10,014,228
# bytes per origin. The ordering of the parents themselves ships once for the
# whole site as reading_parents.bin, shared by every origin.
READING_PARENT_RES = 3
# 7 ** (READING_RES - READING_PARENT_RES). A hexagonal res-3 cell has exactly
# this many res-6 descendants; the two PENTAGONS that hold land
# (830800fffffffff on the Norwegian coast, 833000fffffffff over the Bohai gulf,
# which contains the departure city Dalian) have 286. The stride stays the
# constant below and the 57 missing slots are padded with UNREACHABLE, so a
# block's size never depends on which parent it is.
READING_SLOTS = 7 ** (READING_RES - READING_PARENT_RES)

# Upper edge of each isochrone band, in minutes: thirty-six edges on a
# geometric ladder from 30 minutes to 72 hours, ratio about 1.155, plus a
# 37th, open-ended band beyond the last edge. The ladder reads as a continuous
# gradient rather than the eleven lumps it replaced, which put 12 h and 18 h
# in the same colour; each band is thin enough that the steps between
# neighbours vanish at any zoom.
BAND_EDGES_MIN: tuple[int, ...] = (30, 35, 40, 45, 55, 60, 70, 80, 95, 110, 125, 145, 170, 195, 225, 260, 300, 350, 400, 465, 535, 620, 715, 825, 955, 1100, 1270, 1470, 1695, 1960, 2260, 2615, 3020, 3485, 4025, 4320)

# uint16 sentinel for "no path exists".
UNREACHABLE = 65535


def ensure_dirs() -> None:
    for d in (CACHE, BUILD, DIST):
        d.mkdir(parents=True, exist_ok=True)
