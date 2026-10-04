"""The solver service's wire contract, tested without a graph.

Everything here runs against a stub solver. That is the design: a request that
needs 3.4 GiB resident and ten seconds of one core cannot be exercised in a
test suite, so the half that decides WHETHER to solve is separated from the
half that solves, and only the first half is tested here.

The separation is itself asserted (`test_the_service_package_holds_no_graph`),
because the cheapest way to lose it is an import added for convenience.
"""

from __future__ import annotations

import json

import pytest

from transport_maps.service import wire


class Stub:
    """A solver that records what it was asked and answers instantly."""

    def __init__(self, answer=None, raises: Exception | None = None) -> None:
        self.answer = answer if answer is not None else wire.ok_body(
            minutes=618, snapped_km=0.0, snapped_lat=1.0, snapped_lon=2.0)
        self.raises = raises
        self.calls: list[wire.SolveRequest] = []

    def solve(self, req: wire.SolveRequest):
        self.calls.append(req)
        if self.raises is not None:
            raise self.raises
        return self.answer


OK = "from=37.5665,126.9780&to=35.6762,139.6503"


# ---- validation ----------------------------------------------------------

def test_a_well_formed_request_reaches_the_solver():
    stub = Stub()
    status, _, body = wire.handle(OK, stub)
    assert status == 200 and body["status"] == "ok"
    assert len(stub.calls) == 1
    req = stub.calls[0]
    assert (req.from_lat, req.from_lon) == (37.5665, 126.9780)
    assert (req.to_lat, req.to_lon) == (35.6762, 139.6503)


@pytest.mark.parametrize("query,code", [
    # Missing, empty and malformed.
    ("", "bad_request"),
    ("from=37.5,127.0", "bad_request"),
    ("to=37.5,127.0", "bad_request"),
    ("from=&to=35.0,139.0", "bad_request"),
    ("from=37.5&to=35.0,139.0", "bad_request"),
    ("from=37.5,127.0,9&to=35.0,139.0", "bad_request"),
    ("from=,&to=35.0,139.0", "bad_request"),
    # Not a number at all. `true` matters: in a JSON transport a bool is an
    # int subclass and `float(payload["lat"])` would silently solve from the
    # Gulf of Guinea. A query string cannot smuggle one, and this pins that
    # the parser never grows a path that can.
    ("from=north,127.0&to=35.0,139.0", "bad_request"),
    ("from=true,false&to=35.0,139.0", "bad_request"),
    ("from=0x1f,127.0&to=35.0,139.0", "bad_request"),
    # The three strings `float()` accepts and a coordinate must not.
    ("from=nan,127.0&to=35.0,139.0", "out_of_range"),
    ("from=inf,127.0&to=35.0,139.0", "out_of_range"),
    ("from=-Infinity,127.0&to=35.0,139.0", "out_of_range"),
    ("from=37.5,NaN&to=35.0,139.0", "out_of_range"),
    # Out of range. h3 4.5.0 does not refuse these: it normalises them into a
    # real cell somewhere else on Earth and solves from there.
    ("from=91,127.0&to=35.0,139.0", "out_of_range"),
    ("from=-90.0001,127.0&to=35.0,139.0", "out_of_range"),
    ("from=37.5,180.0001&to=35.0,139.0", "out_of_range"),
    ("from=37.5,-400&to=35.0,139.0", "out_of_range"),
    ("from=1e308,127.0&to=35.0,139.0", "out_of_range"),
    ("from=37.5,127.0&to=1e309,139.0", "out_of_range"),
])
def test_a_bad_coordinate_never_reaches_the_solver(query, code):
    """Each of these costs a string test. Reaching the solver costs ten
    seconds of a core, which is the whole asymmetry this endpoint has to
    defend.

    Mutation performed and reverted: drop the `math.isfinite` test -> the four
    non-finite rows go red. Drop the range test -> the six out-of-range rows
    go red and h3 happily returns a cell for latitude 91.
    """
    stub = Stub()
    status, headers, body = wire.handle(query, stub)
    assert stub.calls == [], "an invalid request reached the solver"
    assert body["code"] == code, body
    assert status == wire.ERRORS[code][0]
    assert headers["Cache-Control"] == "no-store"


def test_the_poles_and_the_antimeridian_are_valid():
    """The bounds are inclusive. A visitor who clicks Svalbard or the dateline
    must not be told their coordinate is off the Earth.

    Mutation performed and reverted: make the comparison exclusive (`lo <
    value < hi`) -> red.
    """
    for query in ("from=90,180&to=-90,-180", "from=-90,0&to=90,0"):
        status, _, body = wire.handle(query, Stub())
        assert status == 200, body


def test_an_enormous_query_is_refused_before_it_is_parsed(monkeypatch):
    """A megabyte of query string must cost a length test, not a parse.

    This docstring used to describe a `parse_qs` spy and there was no such
    spy: the only assertion was `stub.calls == []`, which is the SOLVER stub,
    so the test proved "refused" and said "refused before parsing". Cycle 15
    moved the `MAX_QUERY_CHARS` check below `parse_qs` and the file stayed at
    **39 passed, GREEN** -- the refusal still happened, just after paying for
    the parse the guard exists to avoid.

    The spy is real now. `parse_query` does `from urllib.parse import
    parse_qs` INSIDE the function, so the name resolves at call time and
    patching the module attribute is enough to see it.

    Mutation performed and reverted: move the length check below `parse_qs`
    -> RED, naming the call.
    """
    import urllib.parse

    seen = []
    real = urllib.parse.parse_qs

    def spy(*a, **kw):
        seen.append(a[0] if a else kw.get("qs"))
        return real(*a, **kw)

    monkeypatch.setattr(urllib.parse, "parse_qs", spy)

    huge = "from=37.5,127.0&to=35.0,139.0&" + "x" * wire.MAX_QUERY_CHARS
    assert len(huge) > wire.MAX_QUERY_CHARS
    stub = Stub()
    status, _, body = wire.handle(huge, stub)
    assert body["code"] == "bad_request" and status == 400
    assert stub.calls == [], "an over-long query reached the solver"
    assert seen == [], (
        f"parse_qs was called on a query of {len(huge)} characters, which the "
        f"{wire.MAX_QUERY_CHARS}-character limit exists to avoid paying for")


def test_the_parse_qs_spy_can_see_a_normal_request(monkeypatch):
    """The positive control for the spy above.

    Without it, a spy patched onto the wrong module -- or a `parse_query` that
    stopped using `parse_qs` altogether -- would leave `seen == []` for every
    query and the guard would pass while watching nothing.
    """
    import urllib.parse

    seen = []
    real = urllib.parse.parse_qs
    monkeypatch.setattr(urllib.parse, "parse_qs",
                        lambda *a, **kw: (seen.append(1), real(*a, **kw))[1])

    status, _, body = wire.handle("from=37.5,127.0&to=35.0,139.0", Stub())
    assert status == 200, body
    assert seen, (
        "the spy saw no parse_qs call on a query that must be parsed; it is "
        "patched somewhere parse_query does not look, and the refusal test "
        "above is therefore watching nothing")


def test_a_repeated_parameter_takes_the_first_value_and_not_a_list():
    """`?from=a&from=b` must be one point. A parser that hands the handler a
    list turns one request into an unbounded batch.

    Mutation performed and reverted: return `values` instead of `values[0]`
    -> red (`_point` gets a list and `.split` raises AttributeError, which
    `handle` would turn into a 503, not a 400).
    """
    stub = Stub()
    status, _, body = wire.handle(
        "from=37.5665,126.9780&from=0,0&to=35.6762,139.6503", stub)
    assert status == 200, body
    assert stub.calls[0].from_lat == 37.5665


# ---- the error taxonomy --------------------------------------------------

def test_every_code_has_a_status_a_sentence_and_no_exception_text():
    for code, (status, message) in wire.ERRORS.items():
        assert 400 <= status <= 599, code
        assert message and message[0].isupper() and message.endswith((".", "!")), code
        assert "Traceback" not in message and "/Users" not in message


def test_a_solver_refusal_is_the_code_it_raised():
    """`not_on_land` is `solve/dijkstra.py`'s bare ValueError, translated. It
    must be a 422 the page can branch on, not the 500 an unhandled exception
    would produce.

    Mutation performed and reverted: let `WireError` fall through to the bare
    `except Exception` -> red (503 unavailable, and the page cannot tell "pick
    somewhere else" from "come back later").
    """
    status, headers, body = wire.handle(OK, Stub(raises=wire.WireError("not_on_land")))
    assert status == 422 and body["code"] == "not_on_land"
    assert "Retry-After" not in headers, "a permanent refusal must not invite a retry"


def test_a_deadline_is_a_timeout_and_not_a_crash():
    status, _, body = wire.handle(OK, Stub(raises=TimeoutError()))
    assert status == 504 and body["code"] == "timeout"


def test_an_unexpected_exception_becomes_a_fixed_sentence():
    """Default deny. The service holds a graph built from paths on the owner's
    machine, and `str(exc)` is how those reach a stranger's browser.

    Mutation performed and reverted: add `"detail": str(exc)` to the body ->
    red.
    """
    secret = "/Users/someone/flash-shared/transport-maps/data/secret.parquet"
    status, headers, body = wire.handle(OK, Stub(raises=RuntimeError(secret)))
    assert status == 503 and body["code"] == "unavailable"
    assert secret not in json.dumps(body)
    assert headers["Retry-After"] == "60"


def test_the_busy_code_says_when_to_come_back():
    """One solve is ~10 s and the queue is one deep. A caller told to retry in
    a second simply queues again, which is how a rate limiter becomes a
    thundering herd.
    """
    _, headers, _ = wire.handle(OK, Stub(raises=wire.WireError("busy")))
    assert int(headers["Retry-After"]) >= 10


def test_an_unknown_code_cannot_be_invented():
    with pytest.raises(KeyError):
        wire.WireError("teapot")


# ---- the response shape --------------------------------------------------

def test_the_success_shape_is_exactly_these_fields():
    """Set equality, not membership. A test that only checks a field is
    PRESENT passes when a field is added, and an added field is how a shape
    drifts away from the page that reads it.

    Mutation performed and reverted: rename `minutes` to `min` -> red.
    """
    body = wire.ok_body(minutes=618, snapped_km=4.2, snapped_lat=5.98, snapped_lon=116.1)
    assert set(body) == {"v", "status", "reachable", "minutes",
                         "snappedKm", "snappedLat", "snappedLon"}
    assert body["v"] == wire.WIRE_VERSION and body["status"] == "ok"
    assert body["minutes"] == 618 and body["reachable"] is True
    # `legs` is the one optional field, and it is absent rather than empty.
    with_legs = wire.ok_body(minutes=618, snapped_km=4.2, snapped_lat=5.98,
                             snapped_lon=116.1, legs=LEGS)
    assert set(with_legs) == set(body) | {"legs"}
    assert with_legs["legs"] == LEGS


# Seoul to New York in the wire's own terms: to the airport (part of it by
# train), a flight, a connection, a flight, and the way out.
LEGS = [
    {"kind": "surface", "min": 140, "railMin": 52},
    {"kind": "fly", "from": 812, "to": 1450, "min": 230},
    {"kind": "connect", "at": 1450, "min": 95},
    {"kind": "fly", "from": 1450, "to": 991, "min": 61},
    {"kind": "surface", "min": 92, "railMin": 0},
]


def test_legs_keep_the_wire_version_because_they_are_optional():
    """An additive optional field does not move the version; a page written
    before `legs` reads the same `minutes` it always did. If this fails, the
    shape changed in a way the page's version check exists to catch.
    """
    assert wire.WIRE_VERSION == 1
    assert sum(leg["min"] for leg in LEGS) == 618


@pytest.mark.parametrize("why,legs,minutes", [
    ("short by a minute", [dict(LEGS[0], min=139), *LEGS[1:]], 618),
    ("unreachable", LEGS, None),
    ("empty", [], 0),
    ("ends in the air", LEGS[:-1], 618 - 92),
    ("unknown kind", [{"kind": "swim", "min": 618 - 92}, LEGS[-1]], 618),
    ("missing field", [{"kind": "surface", "min": 618}], 618),
    ("extra field", [dict(LEGS[-1], min=618, road=600)], 618),
    ("a float", [{"kind": "surface", "min": 618.0, "railMin": 0}], 618),
    ("a bool", [{"kind": "surface", "min": 618, "railMin": True}], 618),
    ("negative", [*LEGS[:-1], dict(LEGS[-1], min=-92)], 618 - 184),
    ("more rail than surface", [{"kind": "surface", "min": 618, "railMin": 619}], 618),
])
def test_legs_that_do_not_describe_the_figure_are_refused(why, legs, minutes):
    """The page prints the legs as the breakdown of `minutes`. Ones that do
    not add up, describe no journey, or carry a field the page does not read
    are a bug in the solver, refused before they reach a visitor.

    Mutations performed and reverted, each RED on its row: drop the sum test
    ("short by a minute" and "unreachable"); drop the last-leg test ("ends in the air"); compare fields with `<=`
    instead of `==` ("extra field"); `type(...) is not int` ->
    `not isinstance(..., int)` ("a bool"); drop the railMin bound ("more
    rail than surface").
    """
    with pytest.raises(ValueError):
        wire.ok_body(minutes=minutes, snapped_km=0.0, snapped_lat=0.0, snapped_lon=0.0,
                     legs=legs)


def test_unreachable_is_null_and_not_the_binary_sentinel():
    """65535 is a uint16 artefact of the shipped arrays. In JSON it would read
    as 45 days of travel, which the page formats rather than refusing.

    Mutation performed and reverted: emit `minutes: 65535` for the unreachable
    case -> red.
    """
    body = wire.ok_body(minutes=None, snapped_km=0.0, snapped_lat=0.0, snapped_lon=0.0)
    assert body["minutes"] is None and body["reachable"] is False
    assert 65535 not in body.values() and 65534 not in body.values()


def test_the_snap_distance_is_always_present_even_when_it_is_zero():
    """A field that appears only when it is interesting makes the page's "did
    it move?" test a presence test -- and a presence test reads a renamed
    field as "it did not move", printing a time measured 13 km away with no
    disclosure.

    Mutation performed and reverted: omit `snappedKm` when it is 0.0 -> red.
    """
    body = wire.ok_body(minutes=1, snapped_km=0.0, snapped_lat=0.0, snapped_lon=0.0)
    assert body["snappedKm"] == 0.0 and "snappedKm" in body


def test_every_response_is_json_serialisable_with_no_nan():
    """`json.dumps` writes `NaN` and `Infinity` by default, which every
    browser's `JSON.parse` refuses -- so a non-finite figure would reach the
    page as a parse error with no message, which is this repository's worst
    failure class.

    Mutation performed and reverted: pass `float("inf")` as snapped_km ->
    red.
    """
    for body in (wire.ok_body(minutes=None, snapped_km=0.0, snapped_lat=0.0, snapped_lon=0.0),
                 wire.ok_body(minutes=618, snapped_km=4.2, snapped_lat=1.0, snapped_lon=2.0),
                 wire.ok_body(minutes=618, snapped_km=4.2, snapped_lat=1.0, snapped_lon=2.0,
                              legs=LEGS),
                 wire.error_body("not_on_land")):
        json.dumps(body, allow_nan=False)


def test_the_error_shape_is_exactly_these_fields():
    body = wire.error_body("timeout")
    assert set(body) == {"v", "status", "code", "message"}
    assert body["status"] == "error" and body["code"] == "timeout"


def test_a_successful_response_may_be_cached_and_a_failure_may_not():
    """A solve depends only on the two points and the build, so an identical
    click should be free. A 503 cached for an hour would outlive the outage.
    """
    _, ok_headers, _ = wire.handle(OK, Stub())
    assert "max-age" in ok_headers["Cache-Control"]
    _, err_headers, _ = wire.handle(OK, Stub(raises=wire.WireError("busy")))
    assert err_headers["Cache-Control"] == "no-store"


def test_handle_never_raises():
    """A handler that raises is a 500 with a stack trace in the server log and
    an empty body in the browser. Every exception type must land somewhere.
    """
    for boom in (RuntimeError("x"), KeyError("x"), MemoryError(),
                 ValueError("not on a land cell"), TimeoutError()):
        status, _, body = wire.handle(OK, Stub(raises=boom))
        assert 200 <= status <= 599 and body["v"] == wire.WIRE_VERSION


# ---- the seam ------------------------------------------------------------

def test_the_service_package_holds_no_graph():
    """The seam that makes every test above possible. Importing
    `transport_maps.service` must not pull in the graph, the solver or the
    crawlers -- so the suite stays in milliseconds and a reviewer can read the
    wire contract without reading the pipeline.

    Mutation performed and reverted: add `from transport_maps.graph import
    nodes` to `service/wire.py` -> red.
    """
    import ast
    import pathlib

    from transport_maps import config

    banned = ("transport_maps.graph", "transport_maps.solve",
              "transport_maps.sources", "transport_maps.emit",
              "transport_maps.contour")
    package = pathlib.Path(config.ROOT) / "src" / "transport_maps" / "service"
    files = sorted(package.glob("*.py"))
    assert files, "the service package has no modules"
    for path in files:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not name.startswith(banned), (
                    f"{path.name} imports {name}; the service seam exists so the "
                    "wire format can be tested without a 3.4 GiB graph")


def test_the_page_and_the_service_agree_on_the_error_codes():
    """Both ends branch on the same strings. A code added here and not in the
    page is a visitor staring at a silent failure; a code the page branches on
    that the service cannot emit is dead code that looks like a handled case.

    Mutation performed and reverted: add a `"wrong_planet"` code to ERRORS ->
    red.
    """
    import pathlib
    import re

    from transport_maps import config

    app = (pathlib.Path(config.ROOT) / "web" / "app.js").read_text()
    block = re.search(r"const SOLVER_CODES = \{(.*?)\n\};", app, re.S)
    assert block, "web/app.js has no SOLVER_CODES table to compare against"
    in_page = set(re.findall(r'^\s*(\w+):', block.group(1), re.M))
    assert in_page == set(wire.ERRORS), (
        f"only the service knows {set(wire.ERRORS) - in_page}; "
        f"only the page knows {in_page - set(wire.ERRORS)}")


def test_the_page_reads_the_leg_fields_the_service_writes():
    """Both ends name the kinds of leg and their fields. A kind only the
    service knows is a breakdown the page refuses; a field only the page
    checks is one it waits for and never gets, which also costs the
    breakdown.

    Mutations performed and reverted, each RED: add "ferryMin" to the
    service's surface fields; delete the page's `connect` row.
    """
    import pathlib
    import re

    from transport_maps import config

    app = (pathlib.Path(config.ROOT) / "web" / "app.js").read_text()
    block = re.search(r"const SOLVER_LEG_FIELDS = \{(.*?)\n\};", app, re.S)
    assert block, "web/app.js has no SOLVER_LEG_FIELDS table to compare against"
    in_page = {kind: tuple(re.findall(r'"(\w+)"', fields))
               for kind, fields in re.findall(r"^\s*(\w+): \[(.*?)\]", block.group(1), re.M)}
    assert in_page == wire.LEG_FIELDS


def test_the_bodies_nginx_answers_for_the_solver_are_the_wire_format():
    """nginx answers `busy` (rate limit) and `unavailable` (solver down) itself,
    so the page never sees an HTML error page from /api/solve. Those two
    bodies are typed into deploy/worldmap.atik.kr.conf by hand; they must be
    exactly what the service would have sent, or the page reads them as an
    unknown shape.

    Mutation performed and reverted: change a word of the conf's busy message
    -> red.
    """
    import re

    from transport_maps import config

    conf = (config.ROOT / "deploy" / "worldmap.atik.kr.conf").read_text()
    for code in ("busy", "unavailable"):
        m = re.search(r"location @solver_" + code + r" \{.*?return 503 '(\{.*?\})';", conf, re.S)
        assert m, f"no @solver_{code} location answering in the wire format"
        assert json.loads(m.group(1)) == wire.error_body(code)
        retry = re.search(r"location @solver_" + code + r" \{.*?Retry-After (\d+)", conf, re.S)
        assert retry and int(retry.group(1)) == wire.RETRY_AFTER_S[code]


def test_the_solver_route_keeps_no_access_log():
    """The query string is where a visitor departs from and is going, and the
    privacy text says it reaches this server and no one else. A default access
    log would keep every point.

    Mutation performed and reverted: delete `access_log off;` -> red.
    """
    import re

    from transport_maps import config

    conf = (config.ROOT / "deploy" / "worldmap.atik.kr.conf").read_text()
    block = re.search(r"location = /api/solve \{(.*?)\n    \}", conf, re.S)
    assert block and re.search(r"^\s*access_log off;", block.group(1), re.M)


# ---- /api/map ------------------------------------------------------------

# 12 minutes, 65,535 ("no route") and 7 h 3 min, as `{slug}.bin` would hold them.
MAP_TIMES = bytes([12, 0, 0xFF, 0xFF, 0xA7, 0x01])


class MapStub(Stub):
    """A solver that answers `/api/map` with a three-cell map."""

    def __init__(self, raises: Exception | None = None) -> None:
        super().__init__(raises=raises)
        self.answer = wire.map_body(times=MAP_TIMES, count=3, hover_res=4, build_id="b",
                                    snapped_km=0.0, snapped_lat=1.0, snapped_lon=2.0)

    def map(self, req: wire.MapRequest):
        return self.solve(req)


def test_a_map_request_is_one_point_and_reaches_the_solver():
    stub = MapStub()
    status, headers, body = wire.handle_map("from=37.5665,126.9780", stub)
    assert status == 200 and body["status"] == "ok", body
    assert stub.calls == [wire.MapRequest(37.5665, 126.978)]
    assert "max-age" in headers["Cache-Control"]


@pytest.mark.parametrize("query,code", [
    ("", "bad_request"),
    ("to=37.5,127.0", "bad_request"),
    ("from=37.5", "bad_request"),
    ("from=37.5,127.0,9", "bad_request"),
    ("from=true,false", "bad_request"),
    ("from=nan,127.0", "out_of_range"),
    ("from=37.5,inf", "out_of_range"),
    ("from=91,127.0", "out_of_range"),
    ("from=37.5,-400", "out_of_range"),
    ("from=37.5,127.0&" + "x" * wire.MAX_QUERY_CHARS, "bad_request"),
])
def test_a_bad_map_request_never_reaches_the_solver(query, code):
    """The map is the same full solve a journey is, so it is refused on the
    same terms before the solver is woken.

    Mutations performed and reverted, each RED: drop the length test from
    `_getter` (the long row); read `to=` as the map's point ("to=").
    """
    stub = MapStub()
    status, headers, body = wire.handle_map(query, stub)
    assert stub.calls == [], "an invalid map request reached the solver"
    assert body == wire.error_body(code) and status == wire.ERRORS[code][0]
    assert headers["Cache-Control"] == "no-store"


def test_a_repeated_map_point_takes_the_first():
    stub = MapStub()
    status, _, _ = wire.handle_map("from=37.5,127.0&from=0,0", stub)
    assert status == 200 and stub.calls[0].from_lat == 37.5


def test_the_map_handler_never_raises_and_says_nothing_of_the_error():
    """Mutation performed and reverted: call `solver.map` outside `_answer`'s
    try in handle_map -> RED (the RuntimeError escapes)."""
    secret = "/Users/someone/data/build/solver/cells.npy"
    for boom, code in ((RuntimeError(secret), "unavailable"), (MemoryError(), "unavailable"),
                       (TimeoutError(), "timeout"), (wire.WireError("not_on_land"), "not_on_land"),
                       (wire.WireError("busy"), "busy")):
        status, headers, body = wire.handle_map("from=1,2", MapStub(raises=boom))
        assert body == wire.error_body(code) and status == wire.ERRORS[code][0]
        assert secret not in json.dumps(body) and headers["Cache-Control"] == "no-store"


def test_the_map_shape_is_exactly_these_fields():
    """Set equality, as for a journey: an added field is how a shape drifts
    from the page that reads it. `times` is base64 of the little-endian
    uint16 minutes, and nothing else.

    Mutation performed and reverted: encode `times` as hex -> RED.
    """
    import base64

    body = MapStub().answer
    assert set(body) == {"v", "status", "mapVersion", "hoverRes", "count", "buildId",
                         "snappedKm", "snappedLat", "snappedLon", "times"}
    assert body["v"] == wire.WIRE_VERSION and body["mapVersion"] == wire.MAP_VERSION
    assert base64.b64decode(body["times"], validate=True) == MAP_TIMES
    assert (body["count"], body["hoverRes"], body["snappedKm"]) == (3, 4, 0.0)
    json.dumps(body, allow_nan=False)


@pytest.mark.parametrize("times,count", [(MAP_TIMES, 2), (MAP_TIMES[:-1], 3), (MAP_TIMES, 3.0),
                                         (b"", -1)])
def test_a_map_that_is_not_count_minutes_is_refused(times, count):
    """The page checks the decoded length against hover_cells.bin; the
    service must never send one that fails it.

    Mutation performed and reverted: drop the length test from map_body ->
    RED on the first two rows.
    """
    with pytest.raises(ValueError):
        wire.map_body(times=times, count=count, hover_res=4, build_id="b",
                      snapped_km=0.0, snapped_lat=0.0, snapped_lon=0.0)

def test_the_map_route_is_rate_limited_and_refused_like_the_solve_route():
    """The map costs the same full solve as a journey. Its nginx block must
    share the limit zone -- or the map is a way round the limit -- answer the
    same two wire-format refusals (whose bodies the test above pins), and keep
    no access log of the point.

    Mutations performed and reverted, each RED: give /api/map its own zone;
    map its 429 to a plain error; delete its `access_log off;`; delete the
    /api/map block.
    """
    import re

    from transport_maps import config

    conf = (config.ROOT / "deploy" / "worldmap.atik.kr.conf").read_text()
    for path in ("/api/solve", "/api/map"):
        block = re.search(r"location = " + re.escape(path) + r" \{(.*?)\n    \}", conf, re.S)
        assert block, f"no exact location for {path}"
        b = block.group(1)
        for line in ("access_log off;", "limit_req zone=worldmap_solver burst=3 nodelay;",
                     "error_page 429 = @solver_busy;",
                     "error_page 502 503 504 = @solver_unavailable;",
                     "proxy_pass http://127.0.0.1:8787;",
                     "include snippets/worldmap-security-headers.conf;"):
            assert re.search(r"^\s*" + re.escape(line), b, re.M), f"{path}: {line}"
