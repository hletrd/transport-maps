#!/usr/bin/env python3
"""The dist/ consistency gate, as a module the deploy script calls and the
suite tests.

    uv run python scripts/check_dist.py [--dist dist] [--web web] [--copy-only]

Refuses a build whose artifacts disagree with each other: a hover array of
one length under a cell ordering of another renders plausible, silently
wrong times for every cell (it shipped once, and dist/ is exactly that
mixture during every in-place rebuild). Everything it knows about the file
layout comes from the emitters, not from a second copy of the widths.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

from transport_maps.emit.modes import CHANNELS

REQUIRED_EXTRAS = ("places.json", "airports.json", "borders.json", "water.pmtiles")
# Evidence of an aborted writer; a deploy that merely excluded them would ship
# the partial file next to them.
STRAY = re.compile(r"^(\..*|.*-journal|.*\.tmp|.*\.part|.*\.partial|tmp.*)$")
PMTILES_MAGIC = b"PMTiles"
# "N cities" / "N departures" with a three-digit literal, or "hundreds": the
# count must come from index.json at runtime (it said 553 over a 157-origin
# build once, and "hundreds" over 157 after that).
COUNT_CLAIM = re.compile(r"\b[0-9]{3} (cities|departure|origin)|\bhundreds of (cities|departure)", re.I)


def _pmtiles_ok(path: Path) -> str | None:
    """None when the archive's header is sane, else the problem."""
    size = path.stat().st_size
    if size < 127:
        return f"{path.name} is {size} bytes, not a PMTiles archive"
    with open(path, "rb") as fh:
        head = fh.read(127)
    if head[:7] != PMTILES_MAGIC:
        return f"{path.name} does not start with the PMTiles magic"
    # root dir, metadata, leaf dirs, tile data: offset/length pairs at 8..71
    for name, off in (("root directory", 8), ("metadata", 24), ("leaf directories", 40), ("tile data", 56)):
        start, length = struct.unpack_from("<QQ", head, off)
        if start + length > size:
            return f"{path.name} {name} runs past the end of the file (truncated copy?)"
    return None


def check_dist(dist: Path, origins: list[dict] | None = None,
               n_channels: int = len(CHANNELS)) -> list[str]:
    """Every problem found under `dist`, or an empty list.

    `origins` is the expected origin list (data/origins.toml); when given,
    index.json must list exactly those slugs -- a partial build never
    rewrites index.json, so a mismatch means a stale one.
    """
    dist = Path(dist)
    bad: list[str] = []
    if (dist / ".build.lock").exists():
        bad.append(".build.lock present: a build is running, or died holding it")
    for p in dist.rglob("*"):
        if p.is_file() and STRAY.match(p.name) and p.name != ".build.lock":
            bad.append(f"stray file {p.relative_to(dist)} (an aborted writer's leftover)")

    index_path = dist / "index.json"
    if not index_path.exists():
        return [*bad, "index.json missing"]
    try:
        idx = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [*bad, f"index.json unreadable: {exc}"]
    listed = idx.get("origins") or []
    if not listed:
        bad.append("index.json lists no origins")
    if origins is not None:
        want = {o["slug"] for o in origins}
        have = {o["slug"] for o in listed}
        if want != have:
            bad.append(f"index.json lists {len(have)} origins, origins.toml has {len(want)} "
                       f"(missing {sorted(want - have)[:5]}, extra {sorted(have - want)[:5]})")
    if "modeChannels" in idx and len(idx["modeChannels"]) != n_channels:
        bad.append(f"index.json modeChannels has {len(idx['modeChannels'])} entries, emitter has {n_channels}")

    cells_path = dist / "hover_cells.bin"
    if not cells_path.exists():
        return [*bad, "hover_cells.bin missing"]
    if cells_path.stat().st_size % 8:
        bad.append("hover_cells.bin is not a whole number of uint64 ids")
    n_cells = cells_path.stat().st_size // 8
    if "hoverCellCount" in idx and idx["hoverCellCount"] != n_cells:
        bad.append(f"index.json hoverCellCount {idx['hoverCellCount']} != hover_cells.bin {n_cells}")

    widths = {".bin": 2, ".air.bin": 2, ".modes.bin": 2 * n_channels}
    rail_advertised = bool(idx.get("railDetail"))
    for o in listed:
        s = o["slug"]
        base = dist / "origins" / s
        for suffix, width in widths.items():
            p = base.with_name(s + suffix)
            if not p.exists():
                bad.append(f"{s}{suffix} missing")
            elif p.stat().st_size != n_cells * width:
                bad.append(f"{s}{suffix} has {p.stat().st_size // width} entries, expected {n_cells}")
        rail_bin, rail_json = base.with_name(s + ".rail.bin"), base.with_name(s + ".rail.json")
        if rail_bin.exists() != rail_json.exists():
            bad.append(f"{s}: .rail.bin and .rail.json must ship together")
        if rail_advertised and not rail_bin.exists():
            bad.append(f"{s}.rail.bin missing although index.json advertises railDetail")
        if rail_bin.exists() and rail_bin.stat().st_size != n_cells * 2:
            bad.append(f"{s}.rail.bin has {rail_bin.stat().st_size // 2} entries, expected {n_cells}")
        routes = base.with_name(s + ".json")
        if not routes.exists():
            bad.append(f"{s}.json missing (the route panel walks it)")
        else:
            try:
                payload = json.loads(routes.read_text(encoding="utf-8"))
                if "offsets" not in payload or "nodes" not in payload:
                    bad.append(f"{s}.json lacks offsets/nodes")
            except (OSError, ValueError):
                bad.append(f"{s}.json is not valid JSON (truncated write?)")
        tiles = base.with_name(s + ".pmtiles")
        if not tiles.exists():
            bad.append(f"{s}.pmtiles missing")
        else:
            problem = _pmtiles_ok(tiles)
            if problem:
                bad.append(problem)

    for extra in REQUIRED_EXTRAS:
        p = dist / extra
        if not p.exists():
            bad.append(f"{extra} missing")
        elif extra.endswith(".pmtiles"):
            problem = _pmtiles_ok(p)
            if problem:
                bad.append(problem)
    return bad


def check_copy(web: Path) -> list[str]:
    """The page copy must not state a city count the data can contradict."""
    bad = []
    for name in ("index.html", "llms.txt"):
        p = Path(web) / name
        if not p.exists():
            continue
        for m in COUNT_CLAIM.finditer(p.read_text(encoding="utf-8")):
            bad.append(f"web/{name} states a city count ({m.group(0)!r}); derive it from index.json")
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", type=Path, default=Path("dist"))
    ap.add_argument("--web", type=Path, default=Path("web"))
    ap.add_argument("--copy-only", action="store_true", help="check the page copy only (page-only deploy)")
    ap.add_argument("--no-origins", action="store_true", help="do not compare index.json with data/origins.toml")
    args = ap.parse_args()

    problems = check_copy(args.web)
    if not args.copy_only:
        origins = None
        if not args.no_origins:
            from transport_maps.emit.index import load_origins
            origins = load_origins()
        problems += check_dist(args.dist, origins)
        if not problems:
            idx = json.loads((args.dist / "index.json").read_text())
            n = (args.dist / "hover_cells.bin").stat().st_size // 8
            print(f"  hover cells {n:,} | origins {len(idx['origins'])} | bands {len(idx['bandEdgesMin']) + 1} "
                  f"| solveRes {idx.get('solveRes')} | build {idx.get('buildId', 'unstamped')}")
            print(f"  attribution {[a['name'] for a in idx['attribution']]}")
    if problems:
        print("  PROBLEMS:", *problems[:15], sep="\n    ")
        if len(problems) > 15:
            print(f"    ... and {len(problems) - 15} more")
        sys.exit(1)
    print("  dist/ is consistent: every origin has pmtiles + bin + air.bin + modes.bin + json, "
          "rail files paired, no strays; page copy states no count")


if __name__ == "__main__":
    main()
