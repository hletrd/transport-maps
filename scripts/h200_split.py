#!/usr/bin/env python3
"""Records arithmetic for splitting one map's build across two checkouts.

Used by scripts/h200_rebuild.sh `split`. A main build runs in one checkout and
a tail build, on the last part of the roster, in another; both are the same
code on the same inputs, so their records carry the same inputsHash and
graphHash. Only records with THIS build's hashes count: the previous build's
complete records stay on disk until each origin is redone.

    h200_split.py todo  <map> <main> <inputs> <graph>             # not done in main, roster order
    h200_split.py lack  <map> <main> <tail> <n> <inputs> <graph>  # main's missing before the last n
    h200_split.py left  <map> <main> <tail> <n> <inputs> <graph>  # last n neither has, comma-separated
    h200_split.py merge <map> <main> <tail> <inputs> <graph>      # copy the tail's finished origins in

<map> is full, air, ferry or rail; <main> and <tail> are checkout directories.
Run with the checkout's own python, so the roster is that checkout's.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def map_dir(tree: Path, which: str) -> Path:
    return tree / "dist" if which == "full" else tree / "dist" / "v" / f"no-{which}"


def complete(tree: Path, which: str, inputs: str, graph: str) -> dict[str, dict]:
    out = {}
    for p in (map_dir(tree, which) / ".progress").glob("*.json"):
        try:
            rec = json.loads(p.read_text())
        except ValueError:
            continue
        if (rec.get("state") == "complete" and rec.get("inputsHash") == inputs
                and rec.get("graphHash") == graph):
            out[p.stem] = rec
    return out


def merge(which: str, main: Path, tail: Path, inputs: str, graph: str) -> int:
    """Copy each origin the tail finished and main has not: the files its
    record lists, then the record, so a record never names a missing file."""
    have = complete(main, which, inputs, graph)
    src, dst = map_dir(tail, which), map_dir(main, which)
    n = 0
    for slug, rec in sorted(complete(tail, which, inputs, graph).items()):
        if slug in have:
            continue
        for f in rec["files"]:
            shutil.copy2(src / "origins" / f, dst / "origins" / f)
        shutil.copy2(src / ".progress" / f"{slug}.json", dst / ".progress" / f"{slug}.json")
        n += 1
    return n


def main(argv: list[str], slugs: list[str]) -> str:
    cmd, which = argv[0], argv[1]
    if which not in ("full", "air", "ferry", "rail"):
        raise SystemExit(f"map must be full, air, ferry or rail, not {which!r}")
    if cmd == "todo":
        m = complete(Path(argv[2]), which, argv[3], argv[4])
        return ",".join(s for s in slugs if s not in m)
    if cmd in ("lack", "left"):
        main_, tail, n, inputs, graph = Path(argv[2]), Path(argv[3]), int(argv[4]), argv[5], argv[6]
        m, t = complete(main_, which, inputs, graph), complete(tail, which, inputs, graph)
        if cmd == "lack":
            head = slugs[:-n] if n else slugs
            return str(sum(s not in m for s in head))
        return ",".join(s for s in slugs[-n:] if s not in m and s not in t)
    if cmd == "merge":
        n = merge(which, Path(argv[2]), Path(argv[3]), argv[4], argv[5])
        return f"{which}: merged {n} origin(s) from {argv[3]} into {argv[2]}"
    raise SystemExit(f"unknown command {cmd!r}")


if __name__ == "__main__":
    from transport_maps.emit import index

    print(main(sys.argv[1:], [o["slug"] for o in index.load_origins()]))
