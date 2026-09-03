"""index.json plus the shared hover-cell ordering."""

import json
import tomllib
from pathlib import Path

import h3
import numpy as np

from transport_maps import config
from transport_maps.emit import hover


def load_origins(path: Path | None = None) -> list[dict]:
    path = path or (config.DATA / "origins.toml")
    with open(path, "rb") as fh:
        origins = tomllib.load(fh)["origin"]
    slugs = [o["slug"] for o in origins]
    if len(set(slugs)) != len(slugs):
        raise ValueError("duplicate origin slug in origins.toml")
    return origins


def write_hover_cells(idx, out: Path) -> None:
    """Sorted res-4 cell ids as little-endian uint64, matching the .bin ordering.

    The frontend computes h3.latLngToCell(lat, lon, 4), converts it to its integer
    form, and binary-searches this array to get the index into each origin's .bin.
    """
    ids = np.array([h3.str_to_int(c) for c in hover.hover_cells(idx)], dtype="<u8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(ids.tobytes())


def write_index(origins: list[dict], out: Path) -> None:
    payload = {
        "bandEdgesMin": list(config.BAND_EDGES_MIN),
        "unreachable": config.UNREACHABLE,
        "hoverRes": config.HOVER_RES,
        "hoverCellsUrl": "hover_cells.bin",
        "origins": [
            {"slug": o["slug"], "name": o["name"], "lat": o["lat"], "lon": o["lon"]}
            for o in origins
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
