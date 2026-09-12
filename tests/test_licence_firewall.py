"""Nothing derived from a commercial provider may reach the published artifact.

FR24 and FlightAware were the providers the design once named; Google Routes
is the one calibration actually uses (scripts/calibrate_ground.py), so its
fingerprints are forbidden too. The scan runs on the deploy path
(scripts/deploy_verify.sh) as well as in the suite.
"""

import json
import tomllib
from pathlib import Path

import pytest

from transport_maps import config

FORBIDDEN = ("fr24", "flightradar", "flightaware", "aeroapi", "fa_flight_id",
             "routes.googleapis.com", "x-goog-api-key", "computeroutes", "google_routes")
# The formats this firewall actually inspects. If this set is narrowed later
# such that nothing under dist/ matches it, `_check_no_provider_fingerprints`
# must SKIP visibly -- not silently pass having scanned zero files.
SCANNED_SUFFIXES = {".json", ".geojson", ".toml", ".txt", ".md", ".html", ".js", ".xml"}
# Everything above is text, and text is not where most of the published bytes
# are: measured on the current dist/, .pmtiles is 15.5 GB and .bin is 1.4 GB
# against 399 MB of .json. CLAUDE.md and deploy/README.md both call this
# firewall "the only automated licence gate in the project", and it could not
# see either format.
#
# Reading 17 GB in a unit test is not the answer. The two formats differ in
# what they can even carry:
#
#   .pmtiles holds a JSON metadata blob, which is text, which a visitor can
#     fetch with one unauthenticated `Range: 0-4095` GET. That IS a leak
#     surface, and scripts/check_dist.py already locates and gunzips exactly
#     that blob -- so this test reuses that function rather than writing a
#     second PMTiles parser. It reads a few KB per archive, not 28 MB.
#
#   .bin is a fixed-width numeric array straight out of numpy.tobytes(): it
#     has no string content by construction, and the emitter tests assert its
#     exact byte length. There is nothing for a token to hide in, so it is NOT
#     scanned, and that is a reasoned exclusion rather than an oversight.
#
# The tile bodies inside a .pmtiles are gzipped and are not inspected. What
# could reach one is a feature PROPERTY, and tests/emit/ asserts on the
# properties the emitter writes.
SCANNED_BINARY_SUFFIXES = {".pmtiles"}


def _check_dist():
    """scripts/check_dist.py as a module. It is a script, not a package member;
    tests/web/test_check_dist.py loads it the same way."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "check_dist", config.ROOT / "scripts" / "check_dist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_no_provider_fingerprints(root: Path) -> None:
    """Core firewall check, parameterised on the directory to scan.

    Checking `root.exists()` was not enough: `dist/` can exist but be empty
    (or hold nothing with a scanned suffix), and a `skipif` gated only on
    existence let the scan loop iterate zero times and report PASSED having
    checked nothing. Skip explicitly on "no scannable files" instead, and
    assert the scanned count is positive on the path that does run, so this
    can never again pass vacuously.
    """
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix in SCANNED_SUFFIXES
             and "vendor" not in p.parts]           # third-party bundles are not our output
    if not files:
        pytest.skip(f"no scannable files under {root}; nothing built yet")
    assert len(files) > 0

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for token in FORBIDDEN:
            assert token not in text, f"{path} contains '{token}'"

    # The PMTiles metadata blobs, through check_dist's parser but against THIS
    # module's token list. Not check_dist's `_pmtiles_metadata_leak`, which also
    # refuses a build-host path: that is a privacy question, it belongs to the
    # deploy gate that owns it, and the currently deployed `water.pmtiles`
    # carries one -- so borrowing that check would have made this test fail on
    # a fault it is not about, in an artefact only a rebuild can replace. The
    # licence firewall's subject is commercial-provider fingerprints.
    archives = [p for p in root.rglob("*") if p.is_file()
                and p.suffix in SCANNED_BINARY_SUFFIXES and "vendor" not in p.parts]
    if archives:
        metadata_text = _check_dist().pmtiles_metadata_text
        for path in archives:
            text = metadata_text(path)
            if text is None:
                continue                      # not a readable PMTiles header
            for token in FORBIDDEN:
                assert token not in text, f"{path} metadata contains '{token}'"


def test_no_provider_fingerprints_in_shipped_text():
    _check_no_provider_fingerprints(config.DIST)


def test_no_provider_fingerprints_in_the_page_assets():
    """web/, not only dist/.

    T18 is recorded as running this gate "in both modes"; only the full mode
    was. The vendor and CSP tests read web/ directly, but this scan reads
    config.DIST -- and --page-only publishes web/ without ever merging it into
    dist/, so on that path the firewall inspected whatever copies of app.js and
    index.html the last full deploy happened to leave behind. Demonstrated at
    review time: web/app.js contained `countryName` three times and dist/app.js
    zero, so the gate was reading files a day older than the ones about to
    ship. --page-only is the documented mode for a page fix while a rebuild
    owns dist/, which is exactly when it matters.
    """
    _check_no_provider_fingerprints(config.ROOT / "web")


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
            raise TypeError(f"calibration.toml{path} is a list; records are forbidden")
        else:
            assert isinstance(node, (int, float, bool, str)), f"{path} is {type(node)}"

    assert_scalar(raw)
    # A record dump would be far larger than a coefficient table.
    assert len(json.dumps(raw)) < 4_000
