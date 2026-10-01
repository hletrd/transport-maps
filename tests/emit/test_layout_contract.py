"""Every per-origin file the page indexes by hover cell must agree on which
hover cell entry k is, and on which solver cell speaks for it (P3 / F7, TE-2).

The page reads one ordinal out of `hover_cells.bin` (`web/app.js`:
`cellIndex`) and uses it, unchanged, in four files: the time (`.bin`), the
arrival airport (`.air.bin`), the surface modes (`.modes.bin`) and the rail
caption (`.rail.bin` -> `.rail.json`). Four writers in four modules each
produce their own array; nothing but this file checks that they produce them
in the same order and from the same child. A writer that drifted -- its own
ordering, or the fastest child instead of the centre -- would print Seoul's
time over Tokyo's airport, every file still exactly the right length. The
reading tier (`.r6.bin`) and the override (`.over.bin`) are keyed by reading
slot instead, but the override compares each fine cell against its HOVER
representative, so it inherits the same ordering through `base_hover`.

The fixture is three real res-4 hover cells, each holding its res-6 CENTRE
child and one sibling. In every parent the sibling is FASTER than the centre
and reached a different way (another airport, no rail, no surface minutes), so
a writer that picked the fastest child names the sibling's route. The cells
are listed in the index in REVERSE hover order, siblings first, so a writer
that ordered by first appearance is wrong in every entry. In the third parent
the centre is reached THROUGH its sibling: same airport, but a rail leg the
sibling does not have.

Two paths are run. `cli._solve_one`, with only the solver, the band tiles and
their gates stubbed, is the build's own wiring: one `parents`/`rep` computed
once and handed to every writer. The standalone path calls each writer with
its defaults, so each derives `parents` and the representative itself -- the
path a per-writer regression would take.
"""

from __future__ import annotations

import json

import h3
import numpy as np
import pytest

from transport_maps import config
from transport_maps.emit import hover, index, itinerary, modes, override, rail_detail
from transport_maps.graph.nodes import NodeIndex

PLACES = [(37.5665, 126.9780), (35.1796, 129.0756), (35.6762, 139.6503)]
AIRPORTS = ("AP0", "AP1", "AP2", "AP3")
STATIONS = ("st0", "st1", "st2")
STATION_NAMES = {"st0": "Seoul Station", "st1": "Busan Station", "st2": "Tokyo Station"}
# One real rail hop, st0 -> st1, so one row carries a line, operator and ref.
LINE = 7
TABLES = {"lines": {("st0", "st1"): (LINE,)},
          "route_label": {LINE: ("Line Seven", "Korail", "R7")},
          "route_stops": {LINE: 2},
          "stop_names": STATION_NAMES}


def _fixture():
    """(idx, minutes, predecessors, expected), `expected[k]` describing hover
    cell k by hand -- never by calling the code under test."""
    parents = sorted(h3.latlng_to_cell(lat, lon, config.HOVER_RES) for lat, lon in PLACES)
    assert len(set(parents)) == 3
    centre, sibling = [], []
    for p in parents:
        c = h3.cell_to_center_child(p, config.SOLVE_RES)
        s = next(n for n in sorted(h3.grid_ring(c, 1))
                 if h3.cell_to_parent(n, config.HOVER_RES) == p)
        centre.append(c)
        sibling.append(s)

    # Reverse hover order, sibling before centre.
    cells = [x for k in (2, 1, 0) for x in (sibling[k], centre[k])]
    pos = {c: i for i, c in enumerate(cells)}
    idx = NodeIndex(
        cells=cells, airports=list(AIRPORTS),
        _cell_pos=dict(pos),
        _airport_pos={a: 6 + i for i, a in enumerate(AIRPORTS)},
        _airport_cell={a: 0 for a in AIRPORTS},
        stations=STATIONS,
        base_cells=list(cells),
        base_index=np.arange(len(cells), dtype=np.int64),
        fine=np.zeros(len(cells), dtype=bool),
        _station_pos={s: 14 + i for i, s in enumerate(STATIONS)},
        _station_cell={s: 0 for s in STATIONS})
    # nodes: cells 0..5, departures 6..9, arrivals 10..13, stations 14..16
    dep0 = 6
    arr = {a: 10 + i for i, a in enumerate(AIRPORTS)}
    stn = {s: 14 + i for i, s in enumerate(STATIONS)}

    n = idx.n
    minutes = np.full(n, np.inf)
    pred = np.full(n, -9999, dtype=np.int64)

    def reach(node, via, at):
        minutes[node], pred[node] = at, via

    reach(dep0, -9999, 0.0)                                   # the origin
    for i, a in enumerate(AIRPORTS):
        reach(arr[a], dep0, 50.0 + 10 * i)                    # AP0 50 ... AP3 80
    # Siblings: flown straight in, each through its own airport, no surface leg.
    for k in range(3):
        reach(pos[sibling[k]], arr[AIRPORTS[k + 1]], 110.0 + 10 * k)
    # Centres 0 and 1: land at AP0, then rail (st0, and st0 -> st1).
    reach(stn["st0"], arr["AP0"], 200.0)
    reach(stn["st1"], stn["st0"], 210.0)
    reach(pos[centre[0]], stn["st0"], 230.0)
    reach(pos[centre[1]], stn["st1"], 250.0)
    # Centre 2: through its own sibling (AP3), then rail via st2.
    reach(stn["st2"], pos[sibling[2]], 140.0)
    reach(pos[centre[2]], stn["st2"], 170.0)

    expected = [
        {"cell": parents[0], "minutes": 230, "airport": "AP0", "rail_min": 180,
         "station": "Seoul Station", "line": ""},
        {"cell": parents[1], "minutes": 250, "airport": "AP0", "rail_min": 200,
         "station": "Busan Station", "line": "Line Seven"},
        {"cell": parents[2], "minutes": 170, "airport": "AP3", "rail_min": 40,
         "station": "Tokyo Station", "line": ""},
    ]
    return idx, minutes, pred, expected, centre, sibling


CELL_CLASS = np.zeros(6, dtype=np.int64)


def _run_build_path(monkeypatch, tmp_path, idx, minutes, pred):
    """`cli._solve_one` as the build calls it; only the solve, the band
    polygons/tiles and their gates are stubbed."""
    from transport_maps import cli
    from transport_maps.contour import bands
    from transport_maps.emit import tiles
    from transport_maps.solve import dijkstra

    monkeypatch.setattr(dijkstra, "origin_node", lambda idx, lat, lon: 6)
    monkeypatch.setattr(dijkstra, "solve_from",
                        lambda csr, source, with_predecessors=False: (minutes, pred))
    monkeypatch.setattr(cli.validate, "check_coverage", lambda m, i: 1.0)
    monkeypatch.setattr(cli.validate, "check_monotonic_ground", lambda *a, **k: None)
    monkeypatch.setattr(cli.validate, "check_bands_cover", lambda *a, **k: None)
    monkeypatch.setattr(bands, "band_feature_collection", lambda *a, **k: {"features": []})
    monkeypatch.setattr(tiles, "write_pmtiles",
                        lambda fc, out, **k: out.write_bytes(b"\0" * 2048))

    parents = hover.hover_cells(idx)
    shared = {"country": None, "zone": None, "cell_class": CELL_CLASS,
              "grid": None, "native": None, "rail_tables": TABLES,
              "reading": hover.reading_layout(idx), "variant": None,
              "hover_parents": parents,
              "hover_groups": hover.hover_groups(idx, parents),
              "base_hover": hover.base_hover_index(idx, parents),
              "out_root": tmp_path}
    cli._solve_one({"slug": "o", "lat": 0.0, "lon": 0.0}, idx, None, None, shared)
    return tmp_path / "origins"


def _run_standalone(tmp_path, idx, minutes, pred):
    """Each writer with its own defaults: it derives `parents` and the
    representative itself."""
    out = tmp_path / "origins"
    out.mkdir()
    hover.write_hover(idx, minutes[: idx.n_cells], out / "o.bin")
    itinerary.write_itinerary(idx, minutes, pred, out / "o.air.bin")
    modes.write_modes(idx, minutes, pred, out / "o.modes.bin", cell_class=CELL_CLASS)
    rail_detail.write_rail_detail(idx, minutes, pred, TABLES,
                                  out / "o.rail.bin", out / "o.rail.json")
    return out


@pytest.mark.parametrize("path", ["build", "standalone"])
def test_entry_k_of_every_per_origin_file_describes_hover_cell_k(path, monkeypatch, tmp_path):
    """Mutations performed and reverted, each alone -> red:
    the fastest child instead of the centre in `write_itinerary`'s default
    representative (standalone red: entries 0 and 1 name AP1/AP2); the same in
    `write_modes` (standalone red: zero rail minutes); the same in
    `write_rail_detail` (standalone red: NO_RAIL); `write_modes`'s `parents`
    sorted in reverse (standalone red: entry 0 is Tokyo's row);
    `representative_array` returning the fastest child everywhere (build red
    in every file at once, the hover minutes first).
    """
    idx, minutes, pred, expected, _, _ = _fixture()
    if path == "build":
        out = _run_build_path(monkeypatch, tmp_path, idx, minutes, pred)
    else:
        out = _run_standalone(tmp_path, idx, minutes, pred)

    index.write_hover_cells(idx, tmp_path / "hover_cells.bin")
    order = [h3.int_to_str(int(v))
             for v in np.frombuffer((tmp_path / "hover_cells.bin").read_bytes(), "<u8")]
    assert order == [e["cell"] for e in expected], "hover_cells.bin is not the sorted parent list"

    n = len(order)
    times = np.frombuffer((out / "o.bin").read_bytes(), "<u2")
    air = np.frombuffer((out / "o.air.bin").read_bytes(), "<u2")
    mode = np.frombuffer((out / "o.modes.bin").read_bytes(), "<u2").reshape(-1, len(modes.CHANNELS))
    rail = np.frombuffer((out / "o.rail.bin").read_bytes(), "<u2")
    table = json.loads((out / "o.rail.json").read_text())
    assert len(times) == len(air) == len(mode) == len(rail) == n

    for k, e in enumerate(expected):
        where = f"hover cell {k} ({e['cell']})"
        assert times[k] == e["minutes"], f"{where}: .bin read {times[k]}"
        assert AIRPORTS[air[k]] == e["airport"], f"{where}: .air.bin names {AIRPORTS[air[k]]}"
        assert mode[k].tolist() == [e["rail_min"], 0, 0, 0, 0, 0], f"{where}: .modes.bin {mode[k]}"
        assert rail[k] != rail_detail.NO_RAIL, f"{where}: .rail.bin says no rail"
        station, line, op, _ = table["stations"][rail[k]]
        assert (station, line) == (e["station"], e["line"]), f"{where}: .rail.json row {station!r}"
        if line:
            assert table["operators"][op] == "Korail"


def test_the_override_and_reading_tier_share_the_hover_representative(monkeypatch, tmp_path):
    """`.over.bin` lists a fine cell exactly when its own arrival airport
    differs from its hover cell's representative. Siblings 0 and 1 landed
    elsewhere than their centres (AP1, AP2 vs AP0) and must be listed; sibling
    2 shares its centre's AP3 and must not be; no centre is ever listed. A
    `base_hover` in another order than the representative would pair cells
    with the wrong parent's centre and list a centre.

    Mutation performed and reverted: `base_hover_index` built from
    `parents[::-1]` -> red (five entries, centres among them, each compared
    against another parent's representative).
    """
    idx, minutes, pred, _, centre, sibling = _fixture()
    out = _run_build_path(monkeypatch, tmp_path, idx, minutes, pred)

    def slot(cell):
        blocks = sorted({h3.cell_to_parent(c, config.READING_PARENT_RES) for c in idx.base_cells})
        return (blocks.index(h3.cell_to_parent(cell, config.READING_PARENT_RES))
                * config.READING_SLOTS + hover.reading_slot(cell))

    reading = np.frombuffer((out / "o.r6.bin").read_bytes(), "<u2")
    for c in idx.cells:
        assert reading[slot(c)] == minutes[idx.cell_index(c)], f"r6 slot of {c}"

    raw = (out / "o.over.bin").read_bytes()
    m = len(raw) // override.ENTRY_BYTES
    slots = np.frombuffer(raw[: 4 * m], "<u4").tolist()
    airport = np.frombuffer(raw[4 * m: 6 * m], "<u2").tolist()
    want = sorted((slot(sibling[k]), k + 1) for k in (0, 1))
    assert list(zip(slots, airport)) == want
