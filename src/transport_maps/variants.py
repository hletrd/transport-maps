"""Exclusion variants: the whole map again, with one transport mode never used.

The owner asked for "avoid flights / ferries / trains". A preference changes
which route wins, so it cannot be computed in the page from the full map; the
decision (2026-09-24) was to precompute one map per excluded mode, built by the
same pipeline (`build-all --exclude <mode>`), and keep the site static.

They are slimmer than the full set, and the page says so. Every origin's 38.6 MB
is 26 MB of band tiles -- three quarters of that at zoom 7-8 -- plus the 10 MB
res-6 reading tier. Three full sets would be ~165 GB against 152 GB free on the
web host, measured 2026-09-25, so a variant has no zoom 7-8 tiles: the page
enlarges the zoom-6 ones.

The first variants (2026-09-27) left out the reading tier and the fine-route
override too, about 14 GB a set. Their times were then the ~20 km area's
representative, and could be LOWER than the full map's at the same point --
Tinian with ferries avoided read Saipan's 7 h 38 against 9 h 32 with every
mode, which no map with fewer modes can do. They keep both now, which adds
about 15 MB an origin: 17 to 23 MB an origin, 25 to 33 GB a set.
"""

from __future__ import annotations

import json
from pathlib import Path

from transport_maps import _io

EXCLUDABLE = ("air", "ferry", "rail")
# Band tiles stop here in a variant; the base level of contour.bands.LODS ends
# at 6, so nothing a variant emits is lost by the cap.
VARIANT_MAX_ZOOM = 6
MARKER = "variant.json"


def variant_dir(dist: Path, exclude: str | None) -> Path:
    """Where a build writes: dist/ itself, or dist/v/no-<mode>/ for a variant."""
    if exclude is None:
        return dist
    if exclude not in EXCLUDABLE:
        raise ValueError(f"cannot exclude {exclude!r}; choose from {EXCLUDABLE}")
    return dist / "v" / f"no-{exclude}"


def write_marker(root: Path, exclude: str, slugs: list[str], identity: dict) -> None:
    """Written LAST, and only by a complete (non-partial) variant build."""
    root.mkdir(parents=True, exist_ok=True)
    payload = {"exclude": exclude, "origins": sorted(slugs), "maxZoom": VARIANT_MAX_ZOOM,
               "identity": identity}
    _io.write_bytes(root / MARKER, json.dumps(payload, indent=1).encode())


# The files a variant origin must have to be offered. A set built before the
# reading tier was kept has no .r6.bin and is not offered: its readings are
# the coarse ones described above.
REQUIRED = ("pmtiles", "bin", "json", "air.bin", "modes.bin", "r6.bin", "over.bin")


def withdraw(root: Path) -> None:
    """Stop offering a variant whose files are about to be rewritten."""
    (root / MARKER).unlink(missing_ok=True)


def complete_variants(dist: Path, slugs: list[str]) -> list[str]:
    """Excluded modes whose variant exists for EVERY origin of the full set.

    A variant built for last month's origins, or cut short, is not offered:
    choosing it would load bands for some cities and 404 for the rest.
    """
    out = []
    for mode in EXCLUDABLE:
        root = variant_dir(dist, mode)
        marker = root / MARKER
        if not marker.exists():
            continue
        built = set(json.loads(marker.read_text())["origins"])
        if not set(slugs) <= built:
            continue
        od = root / "origins"
        if all((od / f"{s}.{ext}").exists() for s in slugs for ext in REQUIRED):
            out.append(mode)
    return out
