#!/usr/bin/env python3
"""Measure every colour scheme in web/app.js: OKLab lightness must fall
strictly from the first anchor to the last, and adjacent anchors must be at
least MIN_DELTA_E apart (OKLab distance x100), or two bands read as one.
Each scheme's "no scheduled route" grey must be at least MIN_GREY_DELTA_E
from every one of the 37 painted bands (one shared grey sat 0.9 from a Mono
band), and its sea must lie between space and its darkest band.

    uv run python scripts/check_ramps.py
"""

from __future__ import annotations

import re
import sys
from itertools import pairwise
from pathlib import Path

from transport_maps import _io, config


# The number of painted bands is one more than the number of edges, and it is
# the emitter that decides it. Hard-coded as 37 in three places, this gate
# silently stopped covering the shipped ladder the moment an edge was added or
# removed -- it would keep measuring 37 interpolated colours for a legend that
# no longer had 37.
#
# A FUNCTION, not a module constant. Bound at import, the derivation could not
# be told apart from the literal it replaced: `N_BANDS == len(BAND_EDGES_MIN)
# + 1` reads 37 == 37 either way, and the default argument had frozen too, so
# no test could reach it. Reverting the fix left all seven ramp tests green --
# exactly the vacuity CLAUDE.md says to assume until shown otherwise.
def n_bands() -> int:
    return len(config.BAND_EDGES_MIN) + 1

# Between ANCHORS. Eleven anchors from near-white to near-black span about 70
# OKLab units, so ~7 per step is the ceiling for a single ramp; the shipped
# ramps sit at 6-7 and are then interpolated to 37 bands. Below 6 two
# anchors read as one.
MIN_DELTA_E = 6.0
# Between the grey and ANY painted band: the grey must never read as a band.
MIN_GREY_DELTA_E = 8.0
# Sea lightness: above space by this much, below the darkest band by this much.
SEA_ABOVE_SPACE, SEA_BELOW_BAND = 0.05, 0.04
APP = Path(__file__).resolve().parents[1] / "web" / "app.js"


def srgb_to_oklab(hex_colour: str) -> tuple[float, float, float]:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    l = (0.4122214708 * lin[0] + 0.5363325363 * lin[1] + 0.0514459929 * lin[2]) ** (1 / 3)
    m = (0.2119034982 * lin[0] + 0.6806995451 * lin[1] + 0.1073969566 * lin[2]) ** (1 / 3)
    s = (0.0883024619 * lin[0] + 0.2817188376 * lin[1] + 0.6299787005 * lin[2]) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def ramps(source: str = None) -> dict[str, dict]:
    src = source if source is not None else APP.read_text(encoding="utf-8")
    block = src[src.index("const RAMPS = {"):]
    block = block[: block.index("\n};") + 3]
    out = {}
    for m in re.finditer(r'(\w+):\s*\{\s*name:\s*"([^"]+)",\s*sea:\s*"(#[0-9a-fA-F]{6})",\s*grey:\s*"(#[0-9a-fA-F]{6})",\s*c:\s*\[([^\]]+)\]', block):
        out[m.group(1)] = {"name": m.group(2), "sea": m.group(3), "grey": m.group(4),
                           "c": re.findall(r'"(#[0-9a-fA-F]{6})"', m.group(5))}
    return out


def constant(name: str, source: str = None) -> str:
    """A hex colour constant from app.js, e.g. SPACE or BG."""
    src = source if source is not None else APP.read_text(encoding="utf-8")
    m = re.search(rf'const {name} = "(#[0-9a-fA-F]{{6}})"', src) or re.search(rf'{name} = "(#[0-9a-fA-F]{{6}})"', src)
    if not m:
        raise ValueError(f"{name} not found in app.js")
    return m.group(1)


def expand(control: list[str], n: int | None = None) -> list[tuple[float, float, float]]:
    """The painted bands, interpolated between the anchors in OKLab the
    way app.js's expandRamp does. `n` defaults to the emitter's count."""
    import math
    if n is None:
        n = n_bands()
    lab = [srgb_to_oklab(c) for c in control]
    out = []
    for i in range(n):
        t = (i / (n - 1)) * (len(lab) - 1)
        k = min(math.floor(t), len(lab) - 2)
        f = t - k
        out.append(tuple(v + (lab[k + 1][j] - v) * f for j, v in enumerate(lab[k])))
    return out


def delta_e(p, q) -> float:
    return 100 * sum((a - b) ** 2 for a, b in zip(p, q)) ** 0.5


def scheme_problems(r: dict, space: str, bands: int | None = None) -> list[str]:
    """The grey and the sea, measured against the scheme's own bands."""
    out = []
    bands = expand(r["c"], bands)
    grey = srgb_to_oklab(r["grey"])
    d = min(delta_e(grey, b) for b in bands)
    if d < MIN_GREY_DELTA_E:
        out.append(f"grey {r['grey']} is only {d:.1f} from a band (need {MIN_GREY_DELTA_E:.0f})")
    sea_l = srgb_to_oklab(r["sea"])[0]
    if sea_l <= srgb_to_oklab(space)[0] + SEA_ABOVE_SPACE:
        out.append(f"sea {r['sea']} is not lighter than space")
    if sea_l >= srgb_to_oklab(r["c"][-1])[0] - SEA_BELOW_BAND:
        out.append(f"sea {r['sea']} is not darker than the darkest band")
    return out


def measure(colours: list[str]) -> tuple[list[float], list[float]]:
    lab = [srgb_to_oklab(c) for c in colours]
    lightness = [p[0] for p in lab]
    delta = [100 * sum((a - b) ** 2 for a, b in zip(p, q)) ** 0.5 for p, q in pairwise(lab)]
    return lightness, delta


def problems(colours: list[str]) -> list[str]:
    lightness, delta = measure(colours)
    out = []
    if any(b >= a for a, b in pairwise(lightness)):
        out.append("lightness is not strictly decreasing")
    low = [f"{i}-{i + 1}: {d:.1f}" for i, d in enumerate(delta) if d < MIN_DELTA_E]
    if low:
        out.append("adjacent pairs under " + f"{MIN_DELTA_E:.0f}: " + ", ".join(low))
    return out


def respace(colours: list[str]) -> list[str]:
    """The same colour path, re-sampled so adjacent anchors are equally far
    apart in OKLab -- which is what maximises the smallest step."""
    lab = [srgb_to_oklab(c) for c in colours]
    seg = [sum((a - b) ** 2 for a, b in zip(p, q)) ** 0.5 for p, q in pairwise(lab)]
    total = sum(seg)
    n = len(colours)
    out = []
    for i in range(n):
        target = total * i / (n - 1)
        j, acc = 0, 0.0
        while j < len(seg) - 1 and acc + seg[j] < target:
            acc += seg[j]; j += 1
        t = 0.0 if seg[j] == 0 else min(1.0, (target - acc) / seg[j])
        out.append(oklab_to_srgb(tuple(a + (b - a) * t for a, b in zip(lab[j], lab[j + 1]))))
    return out


def oklab_to_srgb(lab: tuple[float, float, float]) -> str:
    L, a, b = lab
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
           -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
           -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    def enc(c):
        c = min(1.0, max(0.0, c))
        c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(c * 255)
    return "#" + "".join(f"{enc(c):02x}" for c in lin)


if __name__ == "__main__":
    if "--respace" in sys.argv:
        # Rewrite every ramp's anchors in app.js, evenly spaced along its path.
        src = APP.read_text(encoding="utf-8")
        for key, r in ramps(src).items():
            new = respace(r["c"])
            # anchors are written across two lines in the file; match loosely
            pat = re.compile(r'(' + key + r':\s*\{[^}]*?c:\s*\[)([^\]]+)(\])')
            m = pat.search(src)
            assert m, key
            src = src[: m.start(2)] + ",".join(f'"{c}"' for c in new) + src[m.end(2):]
        # atomic_write, not write_text: this is the only writer in the repo
        # that truncates a tracked source file in place. A crash or a full
        # disk part-way through leaves web/app.js truncated -- and on the
        # --page-only deploy path nothing would ever open the result, because
        # that path publishes web/ without a build.
        _io.atomic_write(APP, lambda tmp: tmp.write_text(src, encoding="utf-8"))
        print("respaced every ramp in app.js")
    bad = 0
    space = constant("SPACE")
    for key, r in ramps().items():
        lightness, delta = measure(r["c"])
        sea_l = srgb_to_oklab(r["sea"])[0]
        grey_d = min(delta_e(srgb_to_oklab(r["grey"]), b) for b in expand(r["c"]))
        issues = problems(r["c"]) + scheme_problems(r, space)
        bad += bool(issues)
        print(f"{key:9} {len(r['c'])} anchors  L {lightness[0]:.2f}->{lightness[-1]:.2f}  "
              f"min dE {min(delta):5.1f}  grey dE {grey_d:5.1f}  sea L {sea_l:.2f}  "
              f"{'OK' if not issues else 'FAIL: ' + '; '.join(issues)}")
    sys.exit(1 if bad else 0)
