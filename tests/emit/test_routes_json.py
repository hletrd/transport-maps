import json
from typing import ClassVar

import numpy as np

from transport_maps.emit import routes_json


class FakeIndex:
    """Mirrors the real layout: cells [0,3), departures [3,5), arrivals [5,7)."""

    n_cells = 3
    airports: ClassVar[list[str]] = ["ICN", "GMP"]

    def airport_index(self, iata: str) -> int:
        return {"ICN": 3, "GMP": 4}[iata]

    def airport_arr_index(self, iata: str) -> int:
        return self.airport_index(iata) + len(self.airports)


def test_offsets_and_reachable_airport_nodes(tmp_path):
    out = tmp_path / "routes.json"
    #                cells        dep ICN/GMP   arr ICN/GMP
    minutes = np.array([0.0, 10.0, 20.0, 30.0, np.inf, np.inf, 95.0])
    predecessors = np.array([-9999, 0, 0, 0, -9999, -9999, 3])

    routes_json.write_routes(FakeIndex(), minutes, predecessors, out)
    payload = json.loads(out.read_text())

    assert payload["offsets"] == {"cells": 0, "airports": 3, "stations": 7}
    # Unreachable nodes are omitted, not emitted as a huge number.
    assert {(n["code"], n["kind"]) for n in payload["nodes"]} == {
        ("ICN", "dep"), ("GMP", "arr")}


def test_scipy_sentinel_becomes_null_not_the_literal_number(tmp_path):
    out = tmp_path / "routes.json"
    # ICN departure (node 3) is reachable but has scipy's sentinel.
    minutes = np.array([0.0, 10.0, 20.0, 30.0, np.inf, np.inf, np.inf])
    predecessors = np.array([-9999, 0, 0, -9999, -9999, -9999, -9999])

    routes_json.write_routes(FakeIndex(), minutes, predecessors, out)
    payload = json.loads(out.read_text())

    icn = next(n for n in payload["nodes"]
               if n["code"] == "ICN" and n["kind"] == "dep")
    assert icn["prev"] is None  # scipy's -9999 sentinel must become null, not -9999
    assert icn["min"] == 30
