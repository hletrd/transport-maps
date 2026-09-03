"""Project-wide constants and paths. No I/O beyond directory creation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = DATA / "cache"
BUILD = DATA / "build"
DIST = ROOT / "dist"

# H3 resolution for the solver grid: 548,557 land cells at ~253 km^2 each (measured).
SOLVE_RES = 5
# H3 resolution for the shipped hover array: 82,983 cells -> 165,966 bytes as uint16.
HOVER_RES = 4

# Upper edge of each isochrone band, in minutes. The 11th band is open-ended.
BAND_EDGES_MIN: tuple[int, ...] = (120, 240, 360, 540, 720, 1080, 1440, 2160, 2880, 4320)

# uint16 sentinel for "no path exists".
UNREACHABLE = 65535


def ensure_dirs() -> None:
    for d in (CACHE, BUILD, DIST):
        d.mkdir(parents=True, exist_ok=True)
