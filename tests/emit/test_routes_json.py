import json
from typing import ClassVar

import numpy as np

from transport_maps.emit import routes_json


class FakeIndex:
    # No `.stations` / `.station_index` on purpose: Task 9 (rail) has not
    # landed yet, so NodeIndex only has cells then airports.
    n_cells = 3
    airports: ClassVar[list[str]] = ["ICN", "GMP"]

    def airport_index(self, iata: str) -> int:
        return {"ICN": 3, "GMP": 4}[iata]


def test_offsets_and_reachable_airport_nodes(tmp_path):
    out = tmp_path / "routes.json"
    minutes = np.array([0.0, 10.0, 20.0, 30.0, np.inf])
    predecessors = np.array([-9999, 0, 0, 0, -9999])

    routes_json.write_routes(FakeIndex(), minutes, predecessors, out)
    payload = json.loads(out.read_text())

    assert payload["offsets"] == {"cells": 0, "airports": 3, "stations": 5}
    # GMP (index 4) is unreachable and must be omitted, not emitted as a huge number.
    codes = {n["code"] for n in payload["nodes"]}
    assert codes == {"ICN"}


def test_scipy_sentinel_becomes_null_not_the_literal_number(tmp_path):
    out = tmp_path / "routes.json"
    # ICN (node 3) is reachable but has scipy's "no predecessor" sentinel.
    minutes = np.array([0.0, 10.0, 20.0, 30.0, np.inf])
    predecessors = np.array([-9999, 0, 0, -9999, -9999])

    routes_json.write_routes(FakeIndex(), minutes, predecessors, out)
    payload = json.loads(out.read_text())

    icn = next(n for n in payload["nodes"] if n["code"] == "ICN")
    assert icn["prev"] is None  # scipy's -9999 sentinel must become null, not -9999
    assert icn["min"] == 30
