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


def label_for(df, hops):
    """The (name, operator, ref) the writer would print for a hop sequence.

    `hops` is nearest-the-destination first, the order `_walk_back_hops`
    produces. Going through `pick_route` rather than reading `_line_between`
    directly is deliberate: the selection is the thing under test, and reading
    the dict would test the storage instead.
    """
    lines = rail_detail._line_between(df, CAL)
    rid = rail_detail.pick_route(hops, lines, rail_detail._route_stop_counts(df))
    return rail_detail._route_labels(df).get(rid, ("", "", ""))


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
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert label_for(df, [(a, b)])[0] == "Line Two"
    assert label_for(df, [(b, a)])[0] == "Line Two"


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
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert label_for(df, [(a, b)])[0] == "KTX: Seoul -> Busan"
    assert label_for(df, [(b, a)])[0] == "KTX: Busan -> Seoul"


def test_a_one_way_relation_still_captions_the_ride_back():
    """Where OSM models only one direction, the graph is still traversable
    both ways (`build._rail_edges` makes rail edges undirected), so saying
    nothing would be worse than saying a line whose arrow points the other
    way. The fallback exists and is only a fallback."""
    from transport_maps.graph.rail import station_key

    df = routes([stop(1, 0, 37.0, 127.0, "A", "regional", "Only Direction"),
                 stop(1, 1, 37.1, 127.1, "B", "regional", "Only Direction")])
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert label_for(df, [(a, b)])[0] == label_for(df, [(b, a)])[0] == "Only Direction"


def test_the_operator_and_ref_travel_with_the_line_they_belong_to():
    """A caption that took the line from one relation and the operator from
    another would read like a timetable and be a fabrication."""
    from transport_maps.graph.rail import station_key

    df = routes([stop(1, 0, 37.0, 127.0, "A", "commuter", "Slow", "Metro Co", "S1"),
                 stop(1, 1, 37.1, 127.1, "B", "commuter", "Slow", "Metro Co", "S1"),
                 stop(2, 0, 37.0, 127.0, "A", "high_speed", "Fast", "Rail Co", "X9"),
                 stop(2, 1, 37.1, 127.1, "B", "high_speed", "Fast", "Rail Co", "X9")])
    a, b = station_key(37.0, 127.0), station_key(37.1, 127.1)
    assert label_for(df, [(a, b)]) == ("Fast", "Rail Co", "X9")


# The owner's report, with the real relation ids, stop sequences and
# coordinates out of `data/cache/osm/asia-rail.osm.pbf`. Three KTX services run
# Seoul -> Busan; all three are `service=high_speed, highspeed=yes` and operated
# by 한국철도공사, so nothing about the SERVICE distinguishes them. The detour
# variants carry a lower relation id than the direct train, which is why the
# lowest-id rule showed "(구포경유)" on a hop the direct train also runs.
SEOUL = (37.5547, 126.9707)
GWANGMYEONG = (37.4160, 126.8846)
YEONGDEUNGPO = (37.5157, 126.9077)
SUWON = (37.2659, 127.0003)
DAEJEON = (36.3320, 127.4344)
DONGDAEGU = (35.8797, 128.6285)
MIRYANG = (35.4939, 128.7481)
GUPO = (35.2114, 128.9906)
BUSAN = (35.1150, 129.0403)

KTX_DIRECT = "경부선 KTX: 서울 → 부산"
KTX_GUPO = "경부선 KTX: 서울 → 부산 (구포경유)"
KTX_SUWON = "경부선 KTX: 서울 → 부산 (수원경유)"


def _ktx():
    """The three real services, each built with its real stop sequence."""
    rows = []
    for rid, name, seq in (
        (10882384, KTX_SUWON, [SEOUL, YEONGDEUNGPO, SUWON, DAEJEON, BUSAN]),
        (11208904, KTX_GUPO,
         [SEOUL, GWANGMYEONG, DAEJEON, DONGDAEGU, MIRYANG, GUPO, BUSAN]),
        (11214334, KTX_DIRECT, [SEOUL, DAEJEON, DONGDAEGU, BUSAN]),
    ):
        for i, (la, lo) in enumerate(seq):
            rows.append(stop(rid, i, la, lo, "", "high_speed", name,
                             "한국철도공사", ""))
    return routes(rows)


def test_the_gupo_detour_no_longer_captions_the_direct_ktx(  # noqa: N802
):
    """The owner's report: "KTX 는 왜 자꾸 구포경유만 뜨지?"

    대전 -> 동대구 is the ONE hop relation 11208904 (seven stops, via 구포) and
    relation 11214334 (four stops, direct) share. Both are `high_speed` over
    the same two stations, so they cost the same minutes to the hundredth and
    neither is "the faster service"; the old rule broke the tie on relation id
    and 11208904 is the lower. A traveller riding 서울 -> 대전 -> 동대구 was
    therefore told they were on the 구포 detour.

    The hop BEFORE it settles it. The direct train runs 서울 -> 대전; the 구포
    variant calls at 광명 in between and so has no such hop at all.
    """
    from transport_maps.graph.rail import station_key

    df = _ktx()
    seoul, daejeon, dongdaegu = (station_key(*SEOUL), station_key(*DAEJEON),
                                 station_key(*DONGDAEGU))

    # Both services really do tie on the shared hop -- if they did not, this
    # test would be passing for the wrong reason.
    lines = rail_detail._line_between(df, CAL)
    assert sorted(lines[(daejeon, dongdaegu)]) == [11208904, 11214334]

    # Riding the direct train: the previous hop names it.
    assert label_for(df, [(daejeon, dongdaegu), (seoul, daejeon)])[0] == KTX_DIRECT
    # Riding the 구포 variant, whose previous hop is 광명 -> 대전.
    gwangmyeong = station_key(*GWANGMYEONG)
    assert label_for(df, [(daejeon, dongdaegu), (gwangmyeong, daejeon)])[0] == KTX_GUPO


def test_a_hop_only_the_detour_runs_is_still_captioned_with_the_detour():
    """The fix must not simply prefer the shortest service. 밀양 -> 구포 is run
    by the 구포 variant and nothing else, and naming anything else there would
    be the same defect pointing the other way."""
    from transport_maps.graph.rail import station_key

    df = _ktx()
    assert label_for(df, [(station_key(*MIRYANG), station_key(*GUPO))])[0] == KTX_GUPO
    assert label_for(df, [(station_key(*YEONGDEUNGPO), station_key(*SUWON))])[0] == KTX_SUWON


def test_a_single_hop_ride_names_the_corridor_not_a_detour_variant():
    """Boarding AT 대전 there is no preceding hop to disambiguate with.

    Both services run exactly that hop at exactly that speed, so either name
    is true; the question is which is USEFUL. `경부선 KTX: 서울 → 부산`
    describes the corridor, `(구포경유)` describes a variant of it, and a
    reader on a 대전 -> 동대구 leg is told something irrelevant by the second.
    Fewest stops wins. Relation id -- which is what decided this before, and
    which put 11208904 ahead of 11214334 -- is only the tie-break under that.
    """
    from transport_maps.graph.rail import station_key

    df = _ktx()
    hop = [(station_key(*DAEJEON), station_key(*DONGDAEGU))]
    assert label_for(df, hop)[0] == KTX_DIRECT
    # 11208904 is the LOWER id, so passing would be impossible if id still won.
    lines = rail_detail._line_between(df, CAL)
    assert min(lines[(hop[0])]) == 11208904


def test_the_last_resort_tie_break_is_deterministic():
    """Otherwise the same journey captions differently between builds, and a
    diff of two `.rail.json` files stops meaning anything."""
    from transport_maps.graph.rail import station_key

    hop = [(station_key(*DAEJEON), station_key(*DONGDAEGU))]
    assert label_for(_ktx(), hop) == label_for(_ktx(), hop)


def test_fewest_stops_never_overrides_the_travellers_own_path():
    """The order of the three rules matters and this pins it.

    The 구포 variant has MORE stops, so if fewest-stops outranked path coverage
    a traveller who actually rode it via 광명 would be told they were on the
    direct train. Path coverage first, stops second, id last.
    """
    from transport_maps.graph.rail import station_key

    df = _ktx()
    hops = [(station_key(*DAEJEON), station_key(*DONGDAEGU)),
            (station_key(*GWANGMYEONG), station_key(*DAEJEON))]
    assert label_for(df, hops)[0] == KTX_GUPO


def test_the_chosen_service_is_never_slower_than_the_one_that_set_the_time():
    """The property AA17 is about, asserted directly rather than implied.

    `pick_route` only ever chooses among routes that TIE for fastest over the
    final hop, so a path-based tie-break can change which name is shown but can
    never name a train slower than the one the traveller was charged for.
    """
    from transport_maps.graph.rail import station_key

    # A genuinely slower service sharing the whole route with a faster one.
    df = routes([stop(1, 0, 37.0, 127.0, "A", "commuter", "Slow stopper"),
                 stop(1, 1, 37.5, 127.5, "B", "commuter", "Slow stopper"),
                 stop(1, 2, 38.0, 128.0, "C", "commuter", "Slow stopper"),
                 stop(2, 0, 37.0, 127.0, "A", "high_speed", "Express"),
                 stop(2, 1, 37.5, 127.5, "B", "high_speed", "Express"),
                 stop(2, 2, 38.0, 128.0, "C", "high_speed", "Express")])
    b, c = station_key(37.5, 127.5), station_key(38.0, 128.0)
    a = station_key(37.0, 127.0)
    lines = rail_detail._line_between(df, CAL)
    assert lines[(b, c)] == (2,), "the slow service must not be a candidate at all"
    # Even with the slow service covering every preceding hop, it cannot win.
    assert label_for(df, [(b, c), (a, b)])[0] == "Express"


def test_walk_back_hops_reads_the_travellers_own_chain():
    """`_walk_back_hops` is what turns a predecessor array into the hop
    sequence `pick_route` scores, and nothing exercised it: every other test
    here hands the hops in directly, so `PATH_LOOKBACK_HOPS` could be set to 1
    with the whole file green. Found by mutation, which is why it is here.
    """
    class Idx:
        n_cells = 2
        airports: ClassVar[list[str]] = ["AAA"]
        stations = ("s0", "s1", "s2", "s3")

    idx = Idx()
    first = idx.n_cells + 2 * len(idx.airports)      # 4
    # cell 0 <- s3 <- s2 <- s1 <- s0, and s0's predecessor is a CELL.
    pred = np.array([-9999, -9999, -9999, -9999, 0, 4, 5, 6])
    hops = rail_detail._walk_back_hops(idx, pred, 7, first)
    assert hops == [("s2", "s3"), ("s1", "s2"), ("s0", "s1")], (
        "hops must run nearest-the-destination first and stop at the cell")


def test_the_walk_back_is_bounded(monkeypatch):
    """A pathological chain must not make the writer walk the whole network:
    this runs once per hover parent, ~90,740 times per origin."""
    class Idx:
        n_cells = 1
        airports: ClassVar[list[str]] = []
        stations = tuple(f"s{i}" for i in range(50))

    idx = Idx()
    first = 1
    pred = np.array([-9999] + [max(i - 1, 0) for i in range(50)])
    monkeypatch.setattr(rail_detail, "PATH_LOOKBACK_HOPS", 3)
    assert len(rail_detail._walk_back_hops(idx, pred, 40, first)) == 3


def test_lookup_tables_are_plain_dicts_a_fork_can_use():
    from transport_maps.graph.rail import station_key
    t = rail_detail.lookup_tables(routes(LINE_ONE), CAL)
    assert set(t) == {"lines", "stop_names", "route_label", "route_stops"}
    assert all(isinstance(v, dict) for v in t.values())
    assert t["stop_names"][station_key(37.0, 127.0)] == "A"
    # The hop table holds route IDS and the labels are held once per route:
    # 16,781 routes against 147,332 directed pairs, so this is also the
    # smaller structure to inherit across a fork.
    assert all(isinstance(v, tuple) and all(isinstance(r, int) for r in v)
               for v in t["lines"].values())
    assert rail_detail.lookup_tables(None) == {"lines": {}, "stop_names": {},
                                               "route_label": {}, "route_stops": {}}


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


# --- the duplicated pricing formula -----------------------------------------
#
# `emit/rail_detail._line_between` and `graph/rail.ride_edges` each compute
#
#     stop_overhead_min + 60 * km * detour_factor / speed_kmh
#
# once in scalar Python and once vectorised in polars. `ride_edges` sets the
# TIME an edge costs; `_line_between` decides which service the caption NAMES,
# by taking the minimum of the same quantity. If the two drift, the page prints
# a service that is not the one the traveller was charged for -- which is AA17,
# and the residual of it this cycle's tracer measured at 24.4% of directed hops.
#
# Nothing saw the drift. Cycle 15 mutated `_line_between` to drop
# `* cal.detour_factor`, and then to drop BOTH `stop_overhead_min` and
# `detour_factor`, and this file stayed at 19 passed, GREEN, both times: every
# other test here compares captions to captions, so a formula wrong the same
# way on every route still agrees with itself.
#
# THE FIRST ATTEMPT AT THIS GUARD WAS ALSO VACUOUS, and it is worth saying how,
# because it is the more seductive mistake. It recomputed the formula in the
# test and compared that to `ride_edges`. But the quantity `_line_between`
# actually computes is thrown away -- it returns only the winning route ids --
# so the comparison was test-arithmetic against graph-arithmetic, and a
# mutation of `rail_detail` changed neither. All three mutations stayed green
# on it.
#
# What `_line_between` DOES expose is which route won. So the fixtures below
# are built as two services over one hop, at a distance chosen so that dropping
# a term FLIPS THE WINNER. That is observable through the real return value,
# and it is the property that matters anyway: the caption must name the service
# the charge came from.
#
# MUTATIONS PERFORMED on `emit/rail_detail.py`'s pricing line, each run, with
# the count this FILE returns:
#
#   drop `* cal.detour_factor`          -> RED, 2 failed   (was GREEN, 19 passed)
#   drop `t.stop_overhead_min +`        -> RED, 2 failed
#   drop BOTH                           -> RED, 2 failed   (was GREEN, 19 passed)
#   `/ t.speed_kmh` -> `/ 100.0`        -> RED, 5 failed
#   `60.0` -> `60`                      -> GREEN, 22 passed
#
# The last line is deliberate and is the reason this guard does not assert on
# literals: `60` and `60.0` are identical in float arithmetic, and a check that
# reddened for a semantically empty edit would teach the next reader to ignore
# it. The first draft of the source-term test did exactly that.


#: Two services over one station pair, at distances solved from the shipped
#: calibration (high_speed 214.7 km/h + 5.11 min; commuter 73.8 km/h + 1.32 min;
#: detour_factor 1.2). The crossover sits at 5.92 km with the real formula and
#: 7.10 km without the detour factor, so:
#:
#:   3.0 km  correct -> commuter    ; no stop_overhead -> high_speed
#:   6.5 km  correct -> high_speed  ; no detour_factor -> commuter
#:
#: Both distances are needed. One alone leaves the other term free.
FLIP_DLAT_3KM = 0.026980      # 3.0000 km by graph.rail._haversine_km
FLIP_DLAT_6_5KM = 0.058456    # 6.5000 km


def _two_services(dlat):
    """The same hop, run by a high-speed service and a commuter service."""
    return routes([
        stop(20, 0, 37.0, 127.0, "A", tier="high_speed", route_name="Express"),
        stop(20, 1, 37.0 + dlat, 127.0, "B", tier="high_speed", route_name="Express"),
        stop(21, 0, 37.0, 127.0, "A", tier="commuter", route_name="Stopper"),
        stop(21, 1, 37.0 + dlat, 127.0, "B", tier="commuter", route_name="Stopper"),
    ])


def _winner(df, dlat):
    """Which route id `_line_between` captions the hop with."""
    key = (rail.station_key(37.0, 127.0), rail.station_key(37.0 + dlat, 127.0))
    lines = rail_detail._line_between(df, CAL)
    ids = lines[key]
    assert len(ids) == 1, f"expected one winning service, got {ids}"
    return ids[0]


@pytest.mark.parametrize("dlat,expected,why", [
    (FLIP_DLAT_3KM, 21,
     "over 3 km the commuter's 1.32 min stop overhead beats the express's "
     "5.11 min; without stop_overhead_min the express would win"),
    (FLIP_DLAT_6_5KM, 20,
     "over 6.5 km the express is ahead only because detour_factor 1.2 "
     "inflates both distance terms; at factor 1.0 the commuter would win"),
])
def test_the_caption_names_the_service_the_graph_charges_least_for(dlat, expected, why):
    """`_line_between`'s winner must be `ride_edges`' cheapest service.

    Checked against `ride_edges` rather than against a number written here, so
    the two implementations are compared with each other and not with the test.
    """
    df = _two_services(dlat)
    assert _winner(df, dlat) == expected, why

    # ...and the graph agrees that this is the cheaper one. ride_edges keeps
    # the minimum over both services, so the winner's own price must equal it.
    edges = rail.ride_edges(df, CAL)
    assert len(edges) == 1
    charged = float(edges["minutes"][0])
    alone = rail.ride_edges(
        df.filter(pl.col("route_id") == expected), CAL)
    assert float(alone["minutes"][0]) == pytest.approx(charged, abs=1e-9), (
        f"the captioned service ({expected}) is not the one the graph charged "
        f"for: it costs {float(alone['minutes'][0])!r} against the edge's "
        f"{charged!r}")


def test_the_two_pricings_name_the_same_calibration_terms():
    """The formula itself, side by side.

    The flip tests above would still pass if BOTH implementations lost the
    same term, because they would agree with each other. This reads the two
    expressions and requires each to name every calibration term.

    Deliberately NOT asserting on `60.0` or any other literal: changing it to
    `60` is identical in float arithmetic, and a guard that reddens for a
    semantically empty edit trains people to ignore it. The first draft did
    exactly that.
    """
    import inspect
    graph_src = inspect.getsource(rail.ride_edges)
    emit_src = inspect.getsource(rail_detail._line_between)
    for term in ("stop_overhead_min", "detour_factor", "speed_kmh"):
        assert term in graph_src, f"graph/rail.ride_edges no longer uses {term}"
        assert term in emit_src, (
            f"emit/rail_detail._line_between no longer uses {term}; the caption "
            "would be chosen by a different rule from the charge")


# ---- a "via X" qualifier the traveller never passed ---------------------------

@pytest.mark.parametrize("line,passed,complete,want", [
    # The owner's case, from a real Seoul solve: 서울역 -> 대전 -> 부산.
    ("경부선 KTX: 서울 → 부산 (수원경유)", {"서울역", "대전", "부산"}, True, "경부선 KTX: 서울 → 부산"),
    # The path DID pass 구포: the qualifier is true and stays.
    ("경부선 KTX: 서울 → 부산 (구포경유)", {"대전", "밀양", "구포", "부산"}, True,
     "경부선 KTX: 서울 → 부산 (구포경유)"),
    # Traced only in part: 수원 may be on the untraced part, so nothing is dropped.
    ("경부선 KTX: 서울 → 부산 (수원경유)", {"대전", "부산"}, False, "경부선 KTX: 서울 → 부산 (수원경유)"),
    ("Express (via Reading)", {"London", "Bristol"}, True, "Express"),
    ("Express (via Reading)", {"London", "Reading", "Bristol"}, True, "Express (via Reading)"),
    ("경부선 KTX: 서울 → 부산", {"대전"}, True, "경부선 KTX: 서울 → 부산"),
])
def test_a_via_qualifier_is_kept_only_when_the_path_passed_it(line, passed, complete, want):
    assert rail_detail.drop_false_via(line, passed, complete) == want


class _Stations:
    """Mirrors NodeIndex: station_index is the station's NODE id, stations
    being laid out after the cells and airports (first station = `first`)."""

    def __init__(self, names, first=100):
        self.stations = names
        self.first = first

    def station_index(self, name):
        return self.first + self.stations.index(name)


def test_a_path_is_complete_only_when_traced_back_to_where_the_traveller_boarded():
    first = 100
    idx = _Stations(["s0", "s1", "s2"])
    pred = np.full(first + 3, -9999)
    pred[first + 0] = 5          # s0 was entered from a cell: boarding
    short = [("s1", "s2"), ("s0", "s1")]
    assert rail_detail.boarded_within(idx, pred, short, first)
    long_ = [("a", "b")] * rail_detail.PATH_LOOKBACK_HOPS
    idx2 = _Stations(["a", "b"])
    pred2 = np.full(first + 2, -9999)
    pred2[first + 0] = first + 1  # "a" was reached by rail: the ride goes on
    assert not rail_detail.boarded_within(idx2, pred2, long_, first)
    pred2[first + 0] = 7          # ...unless "a" is where it began
    assert rail_detail.boarded_within(idx2, pred2, long_, first)
    assert not rail_detail.boarded_within(idx, pred, [], first)


def test_the_written_caption_drops_a_via_the_ride_never_passed(tmp_path):
    """The rule is worth nothing if the writer does not apply it. Found by
    mutation: removing the call left every other test in this file green."""
    doc, _ = _one_cell_reached_by_rail([
        stop(1, 0, 37.50, 127.00, "Seoul Station", "high_speed",
             "KTX: Seoul -> Busan (via Suwon)", "Korail", "101"),
        stop(1, 1, 37.55, 127.05, "Gupo", "high_speed",
             "KTX: Seoul -> Busan (via Suwon)", "Korail", "101"),
    ], tmp_path, "via")
    assert doc["stations"][0][1] == "KTX: Seoul -> Busan"
