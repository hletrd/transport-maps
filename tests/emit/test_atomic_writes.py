"""Every per-origin artifact is published by rename, never written in place.

A worker stopped by Pool.terminate (the abort path), a signal or an OOM kill
used to leave a truncated .bin/.json in dist/origins that the deploy gate
(existence and length only) could ship.
"""

import json
import os
import stat
from typing import ClassVar

import h3
import numpy as np
import pytest

from transport_maps import _io, config
from transport_maps.emit import hover, index, itinerary, modes, rail_detail, routes_json


def test_a_failed_write_leaves_neither_target_nor_temp_file(tmp_path):
    out = tmp_path / "artifact.bin"

    def half_then_die(p):
        p.write_bytes(b"half")
        raise RuntimeError("killed mid-write")

    with pytest.raises(RuntimeError):
        _io.atomic_write(out, half_then_die)
    assert not out.exists()
    assert list(tmp_path.iterdir()) == [], "a temp file was left behind"


def test_a_successful_write_is_world_readable(tmp_path):
    out = tmp_path / "sub" / "artifact.bin"
    _io.write_bytes(out, b"ok")
    assert out.read_bytes() == b"ok"
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o644


class Idx:
    a = h3.latlng_to_cell(37.5, 127.0, config.SOLVE_RES)
    cells: ClassVar[list[str]] = [a, h3.grid_ring(a, 1)[0]]
    n_cells = 2
    airports: ClassVar[list[str]] = ["AAA"]
    stations = ("s1", "s2")

    def airport_index(self, iata):
        return 2

    def airport_arr_index(self, iata):
        return 3


MINUTES = np.array([0.0, 30.0, 10.0, 20.0, 5.0, 25.0])
PRED = np.array([-9999, 0, 0, 2, 0, 4])


def _writers(tmp_path):
    idx = Idx()
    return {
        "hover": (tmp_path / "x.bin", lambda: hover.write_hover(idx, MINUTES[:2], tmp_path / "x.bin")),
        "itinerary": (tmp_path / "x.air.bin", lambda: itinerary.write_itinerary(idx, MINUTES, PRED, tmp_path / "x.air.bin")),
        "modes": (tmp_path / "x.modes.bin", lambda: modes.write_modes(idx, MINUTES, PRED, tmp_path / "x.modes.bin", cell_class=np.array([1, 1]))),
        "routes": (tmp_path / "x.json", lambda: routes_json.write_routes(idx, MINUTES, PRED, tmp_path / "x.json")),
        "rail": (tmp_path / "x.rail.bin", lambda: rail_detail.write_rail_detail(idx, MINUTES, PRED, None, tmp_path / "x.rail.bin", tmp_path / "x.rail.json")),
        "hover_cells": (tmp_path / "hover_cells.bin", lambda: index.write_hover_cells(idx, tmp_path / "hover_cells.bin")),
        "index": (tmp_path / "index.json", lambda: index.write_index([{"slug": "s", "name": "S", "lat": 0.0, "lon": 0.0}], tmp_path / "index.json")),
    }


@pytest.mark.parametrize("name", ["hover", "itinerary", "modes", "routes", "rail", "hover_cells", "index"])
def test_every_emitter_publishes_through_the_atomic_writer(monkeypatch, tmp_path, name):
    out, write = _writers(tmp_path)[name]
    write()
    assert out.exists()
    out.unlink()

    def refuse(path, write_fn, mode=_io.ARTIFACT_MODE):
        raise RuntimeError("atomic writer refused")
    monkeypatch.setattr(_io, "atomic_write", refuse)
    with pytest.raises(RuntimeError, match="refused"):
        write()
    assert not out.exists(), f"{name} wrote {out.name} in place, bypassing the atomic writer"


def test_routes_json_is_valid_after_the_atomic_write(tmp_path):
    out, write = _writers(tmp_path)["routes"]
    write()
    assert "offsets" in json.loads(out.read_text())
