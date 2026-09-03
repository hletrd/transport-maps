"""Nothing derived from FR24 or FlightAware may reach the published artifact."""

import json
import tomllib
from pathlib import Path

import pytest

from transport_maps import config

FORBIDDEN = ("fr24", "flightradar", "flightaware", "aeroapi", "fa_flight_id")


def _dist_files() -> list[Path]:
    return [p for p in config.DIST.rglob("*") if p.is_file()]


@pytest.mark.skipif(not config.DIST.exists(), reason="nothing built yet")
def test_no_provider_fingerprints_in_shipped_text():
    for path in _dist_files():
        if path.suffix not in {".json", ".geojson", ".toml"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in FORBIDDEN:
            assert token not in text, f"{path} contains '{token}'"


def test_calibration_contains_only_numbers():
    raw = tomllib.loads((config.ROOT / "calibration.toml").read_text())

    def assert_scalar(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                assert_scalar(v, f"{path}.{k}")
        elif isinstance(node, list):
            raise AssertionError(f"calibration.toml{path} is a list; records are forbidden")
        else:
            assert isinstance(node, (int, float, bool, str)), f"{path} is {type(node)}"

    assert_scalar(raw)
    # A record dump would be far larger than a coefficient table.
    assert len(json.dumps(raw)) < 4_000
