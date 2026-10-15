"""airspace.json: where a flight routed round closed airspace actually goes.

Since rebuild 30 a flight whose great circle crosses airspace closed to its
airlines is timed on the taut path round it (graph/airspace.py) -- Haneda to
Paris on 14 h 10 rather than the great circle's 12 h 11. The page drew every
flight on the great circle all the same, a line straight across Russia under
a time that goes round it. This file gives the page the turns of each
detoured path:

    {"version": 1, "pairs": {"HND CDG": [[lat, lon], ...], ...}}

keyed "SRC DST" in IATA, directed (the corridor differs by direction by up to
3%), each list the points between the two airports in flight order. A pair
absent flies the great circle. Written by the full-map build, from the graph
it solves on, and advertised by index.json's `airspaceUrl` only when present.
"""

from __future__ import annotations

import json
from pathlib import Path

from transport_maps._io import atomic_write

VERSION = 1


def write_airspace(paths: dict[tuple[str, str], list[tuple[float, float]]], out: Path) -> int:
    """Write the detour turns of every flight in `paths`; returns the count."""
    payload = {"version": VERSION,
               "pairs": {f"{s} {d}": [list(p) for p in pts]
                         for (s, d), pts in sorted(paths.items()) if pts}}
    atomic_write(Path(out), lambda tmp: tmp.write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"))
    return len(payload["pairs"])
