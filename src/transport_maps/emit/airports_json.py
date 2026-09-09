"""The airport list, so the search box can find JFK as readily as New York.

Compact columnar JSON: 4,008 rows (scheduled-service airports; the graph drops
a few) of code, name, country, lat, lon. The IATA
code is what people type; the name is what they need to recognise the answer.
"""

import json
from pathlib import Path

from ..sources import airports
from ..sources._utils import _atomic_write

# Column order of every row in airports.json; web/app.js reads them by position
# (a[0] code, a[1] name, a[2] country, a[3] lat, a[4] lon).
FIELDS = ("iata", "name", "country", "lat", "lon", "size")


def build(out: Path) -> int:
    a = airports.scheduled_airports()
    rows = [[c, n, k, round(float(la), 3), round(float(lo), 3), s]
            for c, n, k, la, lo, s in zip(a["iata"], a["name"], a["country"],
                                          a["lat"], a["lon"], a["size"])]
    payload = {"fields": list(FIELDS), "airports": rows}
    _atomic_write(out, lambda tmp: tmp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"))
    return len(rows)
