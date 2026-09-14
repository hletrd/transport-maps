"""The on-demand solver service: everything that does not hold the graph.

The design is `plan/2026-09-14-c13-solver-service.md`. What lives here is the
half that can be built and tested without 3.4 GiB of resident graph: the wire
format, request validation, the error taxonomy and the request handler, all
written against a `Solver` protocol rather than against the real solver.

Nothing in this package imports `transport_maps.graph`, `transport_maps.solve`
or `transport_maps.sources`. That is deliberate and it is enforced by
`tests/service/test_wire.py`: the whole point of the seam is that the 17-minute
test suite can exercise the service without a five-minute graph assembly, and
an import added for convenience would quietly end that.
"""

from transport_maps.service.wire import (
    ERRORS,
    WIRE_VERSION,
    SolveRequest,
    WireError,
    error_body,
    handle,
    ok_body,
    parse_query,
)

__all__ = [
    "ERRORS",
    "WIRE_VERSION",
    "SolveRequest",
    "WireError",
    "error_body",
    "handle",
    "ok_body",
    "parse_query",
]
