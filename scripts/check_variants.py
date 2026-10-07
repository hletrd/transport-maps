#!/usr/bin/env python3
"""No avoid-a-mode map may be faster than the full map, anywhere.

    uv run python scripts/check_variants.py [--dist dist]

Removing a mode from the network can only lengthen a journey, so for every
origin index.json lists and every variant it offers, each cell's minutes in
the variant must be at least the full map's -- in the reading tier
(`<slug>.r6.bin`) and the hover tier (`<slug>.bin`), uint16 minutes with 65535
for unreachable. A cell that got faster means the variant was built on another
graph or another model than the full map beside it. Run at every release,
after `transport-maps reindex` (rebuild 28 ran it by hand: 0 cells).

Exits 1 and names the worst cases when any cell is faster; prints, for one
origin, how many cells each variant made slower, so a variant identical to
the full map -- built without its exclusion -- is visible too.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

SUFFIXES = (".r6.bin", ".bin")


def check(dist: Path) -> list[str]:
    """Problems found, as sentences; empty when every variant is monotone."""
    idx = json.loads((dist / "index.json").read_text(encoding="utf-8"))
    slugs = [o["slug"] for o in idx["origins"]]
    variants = [v["exclude"] for v in idx.get("variants") or []]
    problems: list[str] = []
    for ex in variants:
        vdir = dist / "v" / f"no-{ex}" / "origins"
        for suffix in SUFFIXES:
            faster_origins = faster_cells = 0
            worst = (0, "")
            for slug in slugs:
                full = np.fromfile(dist / "origins" / f"{slug}{suffix}", dtype="<u2")
                var = np.fromfile(vdir / f"{slug}{suffix}", dtype="<u2")
                if full.shape != var.shape:
                    problems.append(f"no-{ex} {slug}{suffix}: {var.size} cells against the "
                                    f"full map's {full.size}")
                    continue
                quicker = var < full
                if quicker.any():
                    faster_origins += 1
                    faster_cells += int(quicker.sum())
                    gap = int((full[quicker].astype(np.int64) - var[quicker]).max())
                    if gap > worst[0]:
                        worst = (gap, slug)
            if faster_cells:
                problems.append(f"no-{ex} {suffix}: {faster_cells:,} cells in {faster_origins} "
                                f"origins faster than the full map; worst {worst[0]} min "
                                f"at {worst[1]}")
            print(f"  no-{ex:<6} {suffix:<8} {faster_cells:,} cells faster than the full map")
    if slugs and variants:
        probe = slugs[0]
        full = np.fromfile(dist / "origins" / f"{probe}.r6.bin", dtype="<u2")
        for ex in variants:
            var = np.fromfile(dist / "v" / f"no-{ex}" / "origins" / f"{probe}.r6.bin", dtype="<u2")
            slower = int((var > full).sum()) if var.shape == full.shape else -1
            print(f"  no-{ex:<6} from {probe}: {slower:,} cells slower than the full map")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=Path("dist"))
    problems = check(ap.parse_args().dist)
    for p in problems:
        print(f"  !! {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
