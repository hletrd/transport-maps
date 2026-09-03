"""Nothing derived from FR24 or FlightAware may reach the published artifact."""

import json
import tomllib
from pathlib import Path

import pytest

from transport_maps import config

FORBIDDEN = ("fr24", "flightradar", "flightaware", "aeroapi", "fa_flight_id")
# The formats this firewall actually inspects. If this set is narrowed later
# such that nothing under dist/ matches it, `_check_no_provider_fingerprints`
# must SKIP visibly -- not silently pass having scanned zero files.
SCANNED_SUFFIXES = {".json", ".geojson", ".toml"}


def _check_no_provider_fingerprints(root: Path) -> None:
    """Core firewall check, parameterised on the directory to scan.

    Checking `root.exists()` was not enough: `dist/` can exist but be empty
    (or hold nothing with a scanned suffix), and a `skipif` gated only on
    existence let the scan loop iterate zero times and report PASSED having
    checked nothing. Skip explicitly on "no scannable files" instead, and
    assert the scanned count is positive on the path that does run, so this
    can never again pass vacuously.
    """
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix in SCANNED_SUFFIXES]
    if not files:
        pytest.skip(f"no scannable files under {root}; nothing built yet")
    assert len(files) > 0

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in FORBIDDEN:
            assert token not in text, f"{path} contains '{token}'"


def test_no_provider_fingerprints_in_shipped_text():
    _check_no_provider_fingerprints(config.DIST)


def test_firewall_skips_rather_than_passes_on_an_unbuilt_tree(tmp_path):
    """Proof for the vacuous-pass bug: a directory with nothing scannable
    must SKIP, not report a silent pass.
    """
    with pytest.raises(pytest.skip.Exception):
        _check_no_provider_fingerprints(tmp_path)


def test_firewall_fails_on_a_forbidden_token(tmp_path):
    """Proof the scan loop actually inspects content when it does run."""
    (tmp_path / "routes.json").write_text('{"source": "FlightAware feed"}')
    with pytest.raises(AssertionError, match="flightaware"):
        _check_no_provider_fingerprints(tmp_path)


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
