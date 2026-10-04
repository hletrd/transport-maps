"""The resident solver behind nginx: `GET /api/solve?from=lat,lon&to=lat,lon`
and `GET /api/map?from=lat,lon`.

    python -m transport_maps.service.server --bundle /srv/worldmap-solver/current

Single-threaded on purpose. scipy's dijkstra holds the GIL for the whole solve
(measured: a spinning thread kept 4.6% of its speed during one), so threads
would only queue behind it while each held its own half-gigabyte of working
arrays. One request is served at a time; the rest wait in a short listen
backlog, and nginx (deploy/worldmap.atik.kr.conf) rate-limits per address and
answers `busy` itself when the backlog is full. Bound to loopback only.

The bundle is mapped before the socket opens, so a request that reaches this
process always finds a solver; until then nginx gets a refused connection and
the page says the service is not ready (wire code `unavailable`). So is the
map's hover index (service/hovermap.py, 1.7 s and 2.7 MB measured on the
shipped bundle), and when a hover_cells.bin sits beside the bundle, or is named
with `--hover-cells`, the process refuses to start unless the two list the
same cells in the same order.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from transport_maps.service.bundle import GraphSolver, load_bundle
from transport_maps.service.wire import error_body, handle, handle_map

log = logging.getLogger("transport_maps.service")
PATH = "/api/solve"
MAP_PATH = "/api/map"
#: Each path, its handler, and the word its log line uses.
ROUTES = {PATH: (handle, "solve"), MAP_PATH: (handle_map, "map")}


class _Server(HTTPServer):
    # Read by listen() inside the constructor, so it has to be a class attribute.
    request_queue_size = 4


def make_handler(solver):
    class Handler(BaseHTTPRequestHandler):
        server_version = "worldmap-solver"
        sys_version = ""

        def _send(self, status: int, headers: dict[str, str], body: dict) -> None:
            raw = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:                          # noqa: N802
            url = urlsplit(self.path)
            route = ROUTES.get(url.path)
            if route is None:
                self._send(404, {"Content-Type": "application/json; charset=utf-8",
                                 "Cache-Control": "no-store"}, error_body("bad_request"))
                return
            answer, word = route
            t0, solves = time.monotonic(), getattr(solver, "solves", 0)
            status, headers, body = answer(url.query, solver)
            self._send(status, headers, body)
            # The status, the time and whether a kept tree answered: never the
            # points, which are where a visitor is or is going.
            kept = "" if getattr(solver, "solves", 0) != solves else ", kept tree"
            log.info("%s %d in %.1f s%s", word, status, time.monotonic() - t0, kept)

        def log_message(self, fmt, *args) -> None:        # the default logs the URL
            pass

    return Handler


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--hover-cells", default=None,
                    help="the site's hover_cells.bin, to refuse a map in another order "
                         "(default: BUNDLE/hover_cells.bin when it exists)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    t0 = time.monotonic()
    solver = GraphSolver(load_bundle(args.bundle), hover_cells=args.hover_cells)
    log.info("bundle mapped in %.1f s: %s", time.monotonic() - t0, solver.bundle.meta)
    httpd = _Server(("127.0.0.1", args.port), make_handler(solver))
    log.info("serving on 127.0.0.1:%d", args.port)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
