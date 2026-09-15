from typing import ClassVar

import h3
import numpy as np
import polars as pl
import pytest

from transport_maps import config
from transport_maps.emit import rail_detail
from transport_maps.graph import rail
from transport_maps.sources.osm import SCHEMA

CAL = rail.load_rail_calibration()


def routes(rows):
    """Schema-complete route rows.

    Every fixture in this file used to spell out a dict literal missing
    whichever columns it did not care about, so polars nulled them in silence.
    `schema=SCHEMA` here means a new column reddens this file rather than
    slipping through as nulls.
    """
    return pl.DataFrame(rows, schema=SCHEMA)


def stop(route_id, seq, lat, lon, name, tier="regional", route_name="",
         operator="", ref=""):
    return {"route_id": route_id, "seq": seq, "stop_id": route_id * 100 + seq,
            "lat": lat, "lon": lon, "name": name, "tier": tier,
            "route_name": route_name, "operator": operator, "ref": ref}


LINE_ONE = [stop(1, 0, 37.0, 127.0, "A", route_name="Line One",
                 operator="Korail", ref="101"),
            stop(1, 1, 37.1, 127.1, "B", route_name="Line One",
                 operator="Korail", ref="101")]


class Idx:
    """Two cells, one airport (dep+arr), two stations: cells 0,1; air 2,3; stations 4,5."""
    cells: ClassVar[list[str]] = ["8630e08ffffffff", "8630e087fffffff"]
    n_cells = 2
    airports: ClassVar[list[str]] = ["AAA"]
    stations = ("s1", "s2")


def test_last_station_follows_the_shortest_path_tree():
    idx = Idx()
    # cell0 -> station4 -> station5 -> cell1 ; airport nodes unreachable
    minutes = np.array([0.0, 30.0, np.inf, np.inf, 5.0, 20.0])
    pred = np.array([-9999, 5, -9999, -9999, 0, 4])
    last = rail_detail.last_station_per_node(idx, minutes, pred)
    assert last.tolist() == [-1, 5, -1, -1, 4, 5]


def test_the_caption_names_the_service_the_edge_was_PRICED_from():
    """Not the lowest OSM relation id, which is what `setdefault` kept.

    Route 1 is a stopping service and route 2 a high-speed one over the same
    two stops. `ride_edges` prices the segment at route 2's time, so the
    caption must say route 2. Resolving by relation id gave "Line One" -- the
    tracer lane measured 20.9% of directed pairs captioned with a line other
    than the one timed, 370 of them a different speed class.
    """
    from transport_maps.graph.rail import station_key

    df = routes([stop(1, 0, 37.0, 127.0, "A", "commuter", "Line One"),
                 stop(1, 1, 37.1, 127.1, "B", "commuter", "Line One"),
                 stop(2, 0, 37.0, 127.0, "A", "high_speed", "Line Two"),
                 stop(2, 1, 37.1, 127.1, "B", "high_speed", "Line Two")])
    lines = rail_detail._line_between(df, CAL)
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert lines[(a, b)][0] == "Line Two"
    assert lines[(b, a)][0] == "Line Two"


def test_the_reverse_direction_is_not_captioned_with_the_forward_service():
    """OSM route names are directional -- `경부선 KTX: 서울 → 부산`.

    `setdefault((b, a), name)` filled the reverse pair with the forward name,
    so 50.0% of arrow-named station pairs named the service running the other
    way and 3,834 shipped rows named the line's own ORIGIN as the destination.
    Where both directions exist as relations, each must get its own.
    """
    from transport_maps.graph.rail import station_key

    df = routes([stop(1, 0, 37.0, 127.0, "Seoul", "high_speed", "KTX: Seoul -> Busan"),
                 stop(1, 1, 37.1, 127.1, "Busan", "high_speed", "KTX: Seoul -> Busan"),
                 stop(2, 0, 37.1, 127.1, "Busan", "high_speed", "KTX: Busan -> Seoul"),
                 stop(2, 1, 37.0, 127.0, "Seoul", "high_speed", "KTX: Busan -> Seoul")])
    lines = rail_detail._line_between(df, CAL)
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert lines[(a, b)][0] == "KTX: Seoul -> Busan"
    assert lines[(b, a)][0] == "KTX: Busan -> Seoul"


def test_a_one_way_relation_still_captions_the_ride_back():
    """Where OSM models only one direction, the graph is still traversable
    both ways (`build._rail_edges` makes rail edges undirected), so saying
    nothing would be worse than saying a line whose arrow points the other
    way. The fallback exists and is only a fallback."""
    from transport_maps.graph.rail import station_key

    df = routes([stop(1, 0, 37.0, 127.0, "A", "regional", "Only Direction"),
                 stop(1, 1, 37.1, 127.1, "B", "regional", "Only Direction")])
    lines = rail_detail._line_between(df, CAL)
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert lines[(a, b)][0] == lines[(b, a)][0] == "Only Direction"


def test_the_operator_and_ref_travel_with_the_line_they_belong_to():
    """A caption that took the line from one relation and the operator from
    another would read like a timetable and be a fabrication."""
    from transport_maps.graph.rail import station_key

    df = routes([stop(1, 0, 37.0, 127.0, "A", "commuter", "Slow", "Metro Co", "S1"),
                 stop(1, 1, 37.1, 127.1, "B", "commuter", "Slow", "Metro Co", "S1"),
                 stop(2, 0, 37.0, 127.0, "A", "high_speed", "Fast", "Rail Co", "X9"),
                 stop(2, 1, 37.1, 127.1, "B", "high_speed", "Fast", "Rail Co", "X9")])
    lines = rail_detail._line_between(df, CAL)
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert lines[(a, b)] == ("Fast", "Rail Co", "X9")


def test_lookup_tables_are_plain_dicts_a_fork_can_use():
    from transport_maps.graph.rail import station_key
    t = rail_detail.lookup_tables(routes(LINE_ONE), CAL)
    assert set(t) == {"lines", "stop_names"}
    assert isinstance(t["lines"], dict) and isinstance(t["stop_names"], dict)
    assert t["stop_names"][station_key(37.0, 127.0)] == "A"
    assert rail_detail.lookup_tables(None) == {"lines": {}, "stop_names": {}}


def test_write_rail_detail_never_touches_polars(monkeypatch, tmp_path):
    """The writer runs inside forked workers, where a polars call deadlocks
    (its thread pool does not survive fork). The lookup tables are built in
    the parent; with the module's `pl` removed the writer must still run."""
    tables = rail_detail.lookup_tables(routes(LINE_ONE), CAL)
    monkeypatch.setattr(rail_detail, "pl", None)        # any pl.* in the writer -> AttributeError

    class RealIdx(Idx):
        # real cells: the writer groups them into hover parents
        a = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
        cells: ClassVar[list[str]] = [a, h3.grid_ring(a, 1)[0]]
    idx = RealIdx()
    minutes = np.array([0.0, 30.0, np.inf, np.inf, 5.0, 20.0])
    pred = np.array([-9999, 5, -9999, -9999, 0, 4])
    rail_detail.write_rail_detail(idx, minutes, pred, tables,
                                  tmp_path / "x.rail.bin", tmp_path / "x.rail.json")
    assert (tmp_path / "x.rail.bin").stat().st_size == 2 * len({h3.cell_to_parent(c, config.HOVER_RES) for c in idx.cells})


def _one_cell_reached_by_rail(rows, tmp_path, name):
    """One solve cell, reached by riding station A -> station B.

    Node layout matches `OneCell` below: cell 0; airport dep 1 / arr 2;
    stations 3 and 4. A single cell means `_representative_children` cannot
    pick the origin instead of the destination, which is what made a
    two-cell fixture yield an empty table.
    """
    import json

    cell = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    tables = rail_detail.lookup_tables(routes(rows), CAL)
    keys = [rail.station_key(r["lat"], r["lon"]) for r in rows]

    class OneCell:
        cells: ClassVar[list[str]] = [cell]
        n_cells = 1
        airports: ClassVar[list[str]] = ["AAA"]
        stations = tuple(keys)

    minutes = np.array([30.0, np.inf, np.inf, 5.0, 20.0])
    pred = np.array([4, -9999, -9999, -9999, 3])
    rail_detail.write_rail_detail(OneCell(), minutes, pred, tables,
                                  tmp_path / f"{name}.rail.bin",
                                  tmp_path / f"{name}.rail.json")
    return (json.loads((tmp_path / f"{name}.rail.json").read_text()),
            (tmp_path / f"{name}.rail.bin").read_bytes())


def test_the_rail_json_carries_the_station_line_operator_and_ref(tmp_path):
    """The only test that OPENS `.rail.json`.

    Every assertion on this emitter used to be `st_size == n * 2` on the
    companion `.bin`, which passes for a wrong-endian, wrong-order or entirely
    empty table -- and the JSON, which is the half a reader actually sees, was
    written and never read back by anything.
    """
    doc, raw = _one_cell_reached_by_rail([
        stop(1, 0, 37.50, 127.00, "Seoul Station", "high_speed",
             "KTX: Seoul -> Busan", "Korail", "101"),
        stop(1, 1, 37.55, 127.05, "Gupo", "high_speed",
             "KTX: Seoul -> Busan", "Korail", "101"),
    ], tmp_path, "x")

    assert doc["fields"] == ["station", "line", "operator", "ref"]
    assert doc["operators"] == ["Korail"], "the operator must be interned once"
    assert doc["stations"], "no station row was written at all"
    station, line, op, ref = doc["stations"][0]
    assert station == "Gupo", "the station alighted at, not the one boarded"
    assert line == "KTX: Seoul -> Busan"
    assert op == 0 and doc["operators"][op] == "Korail"
    assert ref == "101"

    # The .bin must INDEX that row, little-endian uint16 -- not merely be the
    # right length.
    idx = np.frombuffer(raw, dtype="<u2")
    assert len(idx) == 1
    assert int(idx[0]) == 0


def test_a_missing_operator_is_a_sentinel_not_an_empty_string(tmp_path):
    """8% of route relations carry no `operator` and 20% in Africa, so the
    page must be able to tell absence from a blank name and print nothing."""
    doc, _ = _one_cell_reached_by_rail([
        stop(1, 0, 37.50, 127.00, "A", "regional", "Unbranded Line"),
        stop(1, 1, 37.55, 127.05, "B", "regional", "Unbranded Line"),
    ], tmp_path, "y")
    assert doc["operators"] == []
    assert doc["stations"][0][2] == rail_detail.NO_OPERATOR
    assert doc["stations"][0][3] == ""


def test_an_unnamed_stop_publishes_an_empty_station_not_the_line_name(tmp_path):
    """The station column must degrade to "" so `railVia` can print "a
    station"; publishing the route name there produced rows that read
    `via S1: Rostock Hbf -> Warnemünde (S1: Rostock Hbf -> Warnemünde)`."""
    doc, _ = _one_cell_reached_by_rail([
        stop(1, 0, 37.50, 127.00, "Rostock Hbf", "commuter",
             "S1: Rostock Hbf -> Warnemünde"),
        stop(1, 1, 37.55, 127.05, "", "commuter",
             "S1: Rostock Hbf -> Warnemünde"),
    ], tmp_path, "z")
    station, line, _, _ = doc["stations"][0]
    assert station == ""
    assert line == "S1: Rostock Hbf -> Warnemünde"
    assert station != line


def test_a_rail_table_that_reaches_the_sentinel_is_refused(monkeypatch, tmp_path):
    """np.minimum used to fold table indexes past 65,535 into NO_RAIL silently."""
    tables = rail_detail.lookup_tables(routes(LINE_ONE), CAL)

    class OneCell:
        """cell 0; airport dep 1 / arr 2; stations 3, 4 -- the cell is reached by rail."""
        cells: ClassVar[list[str]] = [h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)]
        n_cells = 1
        airports: ClassVar[list[str]] = ["AAA"]
        stations = ("s1", "s2")
    minutes = np.array([30.0, np.inf, np.inf, 5.0, 20.0])
    pred = np.array([4, -9999, -9999, -9999, 3])
    monkeypatch.setattr(rail_detail, "NO_RAIL", 1)     # a one-row table now "reaches" it
    with pytest.raises(ValueError, match="uint16 holds"):
        rail_detail.write_rail_detail(OneCell(), minutes, pred, tables,
                                      tmp_path / "x.rail.bin", tmp_path / "x.rail.json")
