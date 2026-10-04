"""Request validation, the error taxonomy and the response shape.

No graph, no solver, no network. Every function here is pure, so the whole
wire contract is testable in milliseconds against a stub -- which is what
makes it possible to write this half of the service while a 39-hour build owns
the machine.

THE TRANSPORT IS `GET`, and that is a decision rather than an accident:

- There is no request body, so "reject an oversized payload before parsing it"
  has no attack surface to defend. nginx bounds the request line itself.
- `json.loads` never sees attacker bytes. Python's JSON parser accepts the
  literals `NaN`, `Infinity` and `-Infinity` by default, which is a foot-gun
  the service simply does not have to disarm.
- A same-origin `GET` is cacheable, by nginx and by the browser, on the URL.
  A solve costs seconds of one core; making the identical click free is worth
  more here than REST tidiness.

`float()` still accepts "nan", "inf" and "infinity" from a STRING, so the
non-finite check below is not redundant with the transport choice. It is the
only thing standing between a query string and `h3.latlng_to_cell(nan, nan)`.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from typing import Any, Protocol

# Bumped when a response field changes meaning or disappears. The page reads
# it and refuses a version it does not know, rather than parsing a shape it
# was not written for -- which is the failure that leaves a visitor with a
# number and no idea what it measures.
WIRE_VERSION = 1

# The layout of `/api/map`'s body, versioned on its own. The map is additive
# to wire 1 -- a page that never asks for it is unaffected, and index.json's
# `solver.wire` arms both endpoints -- so it does not move WIRE_VERSION; but its
# `times` field is a binary array with an order and a width, and a change to
# either is exactly the silent kind (a plausible time in the wrong place), so
# the page checks this number too and refuses any other.
MAP_VERSION = 1

# The whole error taxonomy, in one place, because both ends need to agree on
# it: the page branches on `code`, and `tests/service/test_wire.py` asserts the
# two sets are equal. `message` is a fixed sentence per code. A response NEVER
# carries exception text, the offending input, or anything about the queue --
# the first leaks build-host paths, the second is an echo primitive, and the
# third is a timing oracle for the rate limiter.
ERRORS: dict[str, tuple[int, str]] = {
    "bad_request": (
        400, "The request did not name a departure and a destination."),
    "out_of_range": (
        400, "A coordinate was outside the range of the Earth."),
    "not_on_land": (
        422, "There is no land within about 13 km of that point, so there is "
             "nothing to depart from."),
    "busy": (
        503, "Too many points are being computed at once. Try again shortly."),
    "timeout": (
        504, "That point took too long to compute."),
    "unavailable": (
        503, "The service that computes an uncharted departure is not ready."),
}

# Retry-After, in seconds, for the two codes that mean "later, not never". A
# solve is ~10 s and the queue is one deep, so a caller told to come back in
# one second would simply queue again.
RETRY_AFTER_S: dict[str, int] = {"busy": 15, "unavailable": 60}


class WireError(Exception):
    """A request that will not be solved, carrying its enumerated code."""

    def __init__(self, code: str) -> None:
        if code not in ERRORS:
            raise KeyError(f"{code} is not in the error taxonomy")
        super().__init__(code)
        self.code = code

    @property
    def status(self) -> int:
        return ERRORS[self.code][0]


@dataclass(frozen=True)
class SolveRequest:
    """A validated request. Constructing one is the only way past validation."""

    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float


@dataclass(frozen=True)
class MapRequest:
    """A validated `/api/map` request: one point, and nothing else."""

    from_lat: float
    from_lon: float


class Solver(Protocol):
    """What the handler needs from the half that does hold the graph.

    Deliberately one method taking four floats and returning plain data. The
    handler never sees a `NodeIndex`, a CSR matrix or an h3 cell, so it can be
    built, tested and reviewed without any of them existing -- and the real
    solver can be written against this signature in a later cycle without
    touching a line of the wire format.

    Raises `WireError` for anything the caller did wrong (`not_on_land`) and
    `TimeoutError` when the deadline passes.
    """

    def solve(self, req: SolveRequest) -> dict[str, Any]:
        ...

    def map(self, req: MapRequest) -> dict[str, Any]:
        """The whole map from one point, as `map_body` shapes it."""
        ...


def _coord(raw: str | None, lo: float, hi: float) -> float:
    """One coordinate, or `WireError`. Rejects everything that is not a finite
    number in range -- including the three strings `float()` accepts and h3
    does not refuse.

    h3 4.5.0 raises on NaN and the infinities, but SILENTLY NORMALISES a
    latitude of 91 or a longitude of -400 into a real cell somewhere else on
    Earth. So the range test is not politeness: without it a caller can spend
    a full solve on a point they did not ask for, which is the amplification
    this endpoint has to be careful about.
    """
    if raw is None or raw == "":
        raise WireError("bad_request")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise WireError("bad_request") from exc
    if not math.isfinite(value):
        raise WireError("out_of_range")
    if not lo <= value <= hi:
        raise WireError("out_of_range")
    return value


def _point(raw: str | None) -> tuple[float, float]:
    """`"<lat>,<lon>"` as a pair. One point per parameter, never a list: a
    batch parameter would turn one request into N solves, which is the
    amplification the whole design is built to avoid.
    """
    if raw is None:
        raise WireError("bad_request")
    parts = raw.split(",")
    if len(parts) != 2:
        raise WireError("bad_request")
    return _coord(parts[0].strip(), -90.0, 90.0), _coord(parts[1].strip(), -180.0, 180.0)


# A query string longer than this is not a coordinate pair. Two points at full
# double precision plus their separators is under 100 characters; 256 leaves
# room for a future parameter and still refuses a payload. Checked BEFORE
# parsing, so a megabyte of query string costs a length test.
MAX_QUERY_CHARS = 256


def _getter(query: str, getter):
    """The parameter reader both endpoints use, after the length test.

    `getter` is for callers that already hold a parsed mapping (a framework's
    request object, say). It must return the FIRST value for a repeated
    parameter, or None -- never a list, so a repeated `from=` cannot smuggle a
    second point past the single-point rule.
    """
    if len(query) > MAX_QUERY_CHARS:
        raise WireError("bad_request")
    if getter is None:
        from urllib.parse import parse_qs

        parsed = parse_qs(query, keep_blank_values=True, strict_parsing=False)

        def getter(name: str) -> str | None:      # noqa: E306
            values = parsed.get(name)
            return values[0] if values else None

    return getter


def parse_query(query: str, getter=None) -> SolveRequest:
    """Validate a query string into a `SolveRequest`, or raise `WireError`."""
    getter = _getter(query, getter)
    from_lat, from_lon = _point(getter("from"))
    to_lat, to_lon = _point(getter("to"))
    return SolveRequest(from_lat, from_lon, to_lat, to_lon)


def parse_map_query(query: str, getter=None) -> MapRequest:
    """Validate `/api/map`'s query string into a `MapRequest`, or raise
    `WireError`. The same length bound, the same first-value rule and the same
    coordinate checks as `parse_query`: one point is the whole request, and a
    map costs exactly the full solve a journey does."""
    getter = _getter(query, getter)
    return MapRequest(*_point(getter("from")))


# The three kinds of leg and the integer fields each carries, all of them
# required. `min` is whole minutes; `from`, `to` and `at` are airport ordinals,
# the positions `.air.bin` uses (docs/contract.md). `legs` is optional and
# additive -- a page written before it ignores it, and a server that cannot
# read its bundle's node layout leaves it out -- so it did not move
# WIRE_VERSION.
LEG_FIELDS: dict[str, tuple[str, ...]] = {
    "surface": ("min", "railMin"),
    "fly": ("from", "to", "min"),
    "connect": ("at", "min"),
}


def _check_legs(legs: list[dict[str, Any]], minutes: int | None) -> None:
    """The legs describe the journey the figure measures, or ValueError.

    They must sum to `minutes` exactly: the page prints them under that figure
    as its breakdown, and a breakdown that does not add up is the one thing a
    reader cannot be asked to reconcile -- and an unreachable destination,
    `minutes` None, has nothing for them to sum to. They end on the surface,
    because the destination is a cell and every way into a cell is a surface
    edge.
    """
    if not legs or legs[-1].get("kind") != "surface":
        raise ValueError("a journey ends with a surface leg")
    for leg in legs:
        fields = LEG_FIELDS.get(leg.get("kind"))
        if fields is None or set(leg) != {"kind", *fields}:
            raise ValueError(f"not a leg: {leg!r}")
        if any(type(leg[f]) is not int or leg[f] < 0 for f in fields):
            raise ValueError(f"a leg's fields are non-negative integers: {leg!r}")
        if leg["kind"] == "surface" and leg["railMin"] > leg["min"]:
            raise ValueError(f"more rail than surface: {leg!r}")
    if sum(leg["min"] for leg in legs) != minutes:
        raise ValueError(f"the legs come to {sum(leg['min'] for leg in legs)}, not {minutes}")


def ok_body(*, minutes: int | None, snapped_km: float, snapped_lat: float,
            snapped_lon: float, legs: list[dict[str, Any]] | None = None,
            ) -> dict[str, Any]:
    """The success shape.

    `minutes` is MINUTES, integer, and the field is named so -- the page's
    binary arrays are minutes and its own copy says "door to door", so a
    seconds field here would be a unit mismatch nobody would notice until a
    figure was 60x wrong.

    Unreachable is `minutes: null` with `reachable: false`, NOT the 65535 the
    binary arrays use. That sentinel is an artefact of a uint16 array and has
    no business in JSON, where `null` means exactly what it says and cannot be
    mistaken for 45 days of travel.

    `snappedKm` is ALWAYS present, including when it is 0.0. A field that
    appears only when it is interesting makes the page's "did it move?" test a
    presence test, and a presence test silently reads a renamed field as "it
    did not move" -- which would print a time measured somewhere else with no
    disclosure at all.

    `legs`, when given, is the journey as `LEG_FIELDS` describes it, checked
    by `_check_legs`. It is absent, not empty, when there is none to give.
    """
    if legs is not None:
        _check_legs(legs, minutes)
    body: dict[str, Any] = {
        "v": WIRE_VERSION,
        "status": "ok",
        "reachable": minutes is not None,
        "minutes": minutes,
        "snappedKm": round(float(snapped_km), 2),
        "snappedLat": round(float(snapped_lat), 5),
        "snappedLon": round(float(snapped_lon), 5),
    }
    if legs is not None:
        body["legs"] = legs
    return body


def map_body(*, times: bytes, count: int, hover_res: int, build_id: str | None,
             snapped_km: float, snapped_lat: float, snapped_lon: float) -> dict[str, Any]:
    """The success shape of `/api/map`.

    `times` is the map itself: `count` little-endian uint16 minutes, one per
    hover_cells.bin cell in that file's order -- `{slug}.bin`'s layout exactly,
    65,535 for "no route" included (docs/contract.md). It travels as base64
    inside the same JSON envelope every other answer uses, so the page has ONE
    parse path for a map, a journey and every failure, and a body that is not
    this service's -- a captive portal's HTML, a truncated transfer -- fails
    `JSON.parse` and reads as `unavailable` rather than as an array of
    garbage. The 33% that base64 adds is mostly given back by nginx's gzip.

    `count`, `hoverRes` and `buildId` are there to be checked, not read: the
    page refuses a map whose cell count is not its hover_cells.bin's length,
    whose grid is not its own, or whose build is not its index.json's. Any of
    the three would otherwise paint every time in the wrong place.

    `snappedKm` is always present, for the reason ok_body gives.
    """
    if type(count) is not int or count < 0 or len(times) != 2 * count:
        raise ValueError(f"{len(times)} bytes is not {count} uint16 minutes")
    return {
        "v": WIRE_VERSION,
        "status": "ok",
        "mapVersion": MAP_VERSION,
        "hoverRes": int(hover_res),
        "count": count,
        "buildId": build_id,
        "snappedKm": round(float(snapped_km), 2),
        "snappedLat": round(float(snapped_lat), 5),
        "snappedLon": round(float(snapped_lon), 5),
        "times": base64.b64encode(bytes(times)).decode("ascii"),
    }


def error_body(code: str) -> dict[str, Any]:
    """The failure shape. Same envelope, enumerated code, fixed sentence."""
    status, message = ERRORS[code]
    return {"v": WIRE_VERSION, "status": "error", "code": code, "message": message}


def handle(query: str, solver: Solver) -> tuple[int, dict[str, str], dict[str, Any]]:
    """One `/api/solve` request. Returns `(http status, headers, body)`; never
    raises.

    The default-deny shape is the point: every exception that is not a
    `WireError` or a `TimeoutError` becomes `unavailable` with a fixed
    sentence. A handler that lets `str(exc)` reach the response turns any
    internal error into an information leak, and this one solves with a graph
    built from paths on the owner's machine.
    """
    return _answer(lambda: solver.solve(parse_query(query)))


def handle_map(query: str, solver: Solver) -> tuple[int, dict[str, str], dict[str, Any]]:
    """One `/api/map` request, under exactly `handle`'s rules: validation
    before the solver is reached, the same codes, the same caching, and no
    exception that gets out."""
    return _answer(lambda: solver.map(parse_map_query(query)))


def _answer(call) -> tuple[int, dict[str, str], dict[str, Any]]:
    try:
        body = call()
        headers = {"Content-Type": "application/json; charset=utf-8",
                   # A solve or a map depends only on its points, and the
                   # graph changes once per build. Let nginx and the browser
                   # make an identical click free; 3,600 s is far below a build.
                   "Cache-Control": "public, max-age=3600"}
        return 200, headers, body
    except WireError as err:
        code = err.code
    except TimeoutError:
        code = "timeout"
    except Exception:                                  # noqa: BLE001
        code = "unavailable"
    status, _ = ERRORS[code]
    headers = {"Content-Type": "application/json; charset=utf-8",
               "Cache-Control": "no-store"}
    if code in RETRY_AFTER_S:
        headers["Retry-After"] = str(RETRY_AFTER_S[code])
    return status, headers, error_body(code)
