"""`scripts/fit_rail_tiers.py` RUN against a synthetic extract.

The script is the reproduction path `calibration.toml`'s `[rail]` block points
at, which makes it part of the calibration's provenance rather than a
convenience: a fit nobody can re-run is a fit nobody can check, and CLAUDE.md's
modelling rule is explicit that a documented, reproducible error beats a hidden
one.

The extract here is three stops on one line with a `duration` chosen so the
implied speed is a round number, so the assertions are arithmetic rather than
tolerances. The real fit's inputs are 4.2 GB of PBF and are not exercised here;
what IS exercised is every decision the script makes about which observations
to keep and how it turns them into constants.

Mutations performed and reverted, each confirmed RED:
  * drop the `declared` truncation guard   -> the truncated route is kept
  * `MIN_IMPLIED_KMH` 3.0 -> 0.0           -> the 0.7 km/h route is kept
  * `_predict` drops `overhead * legs`     -> the recovered speed is wrong
"""

import importlib.util
import pathlib

import osmium
import pytest

from transport_maps import config

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "fit_rail_tiers.py"


@pytest.fixture(scope="module")
def fit():
    spec = importlib.util.spec_from_file_location("fit_rail_tiers", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path, nodes, relations):
    w = osmium.SimpleWriter(str(path))
    for nid, lat, lon, tags in nodes:
        w.add_node(osmium.osm.mutable.Node(id=nid, location=(lon, lat), tags=tags))
    for rid, members, tags in relations:
        w.add_relation(osmium.osm.mutable.Relation(id=rid, members=members, tags=tags))
    w.close()


TRAIN = {"type": "route", "route": "train"}


@pytest.fixture
def extract(tmp_path, monkeypatch):
    """Four routes: one usable, and one for each reason the script drops one."""
    monkeypatch.setattr(config, "CACHE", tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    nodes = [(10, 48.0, 0.0, {"name": "A"}), (11, 48.0, 1.0, {"name": "B"}),
             (12, 48.0, 2.0, {"name": "C"}), (13, 48.0, 3.0, {"name": "D"})]
    rels = [
        # Usable: three stops, a parseable duration, `service` present.
        (100, [("n", 10, "stop"), ("n", 11, "stop"), ("n", 12, "stop")],
         TRAIN | {"service": "regional", "duration": "02:00", "name": "Keeper"}),
        # No duration at all -- the common case, 14,423 of 16,781 real routes.
        (101, [("n", 10, "stop"), ("n", 11, "stop")],
         TRAIN | {"service": "regional", "name": "No duration"}),
        # A duration that does not parse.
        (102, [("n", 10, "stop"), ("n", 11, "stop")],
         TRAIN | {"service": "regional", "duration": "14:00-16:00", "name": "Range"}),
        # 149 km in 6,000 minutes: 1.8 km/h implied, a tagging error.
        (103, [("n", 10, "stop"), ("n", 13, "stop")],
         TRAIN | {"service": "regional", "duration": "6000", "name": "Implausible"}),
    ]
    _write(tmp_path / "t-rail.osm.pbf", nodes, rels)
    return tmp_path


def test_only_routes_with_a_usable_duration_become_observations(fit, extract):
    rows, dropped = fit.observations(extract)
    assert [r["name"] for r in rows] == ["Keeper", "Implausible"], dropped
    assert dropped["no duration tag"] == 1
    assert dropped["duration unparseable"] == 1


def test_the_implausibility_band_rejects_a_mis_tagged_duration(fit, extract):
    rows, _ = fit.observations(extract)
    detour = 1.2
    clean = [r for r in rows
             if fit.MIN_IMPLIED_KMH
             <= 60.0 * detour * r["km"] / r["obs_min"]
             <= fit.MAX_IMPLIED_KMH]
    assert [r["name"] for r in clean] == ["Keeper"], (
        "a 1.8 km/h route reached the fit")


def test_a_route_the_extract_truncates_is_dropped_not_used(fit, tmp_path, monkeypatch):
    """Its chord sum covers fewer stops than the tagged duration describes, so
    keeping it would bias every tier it lands in DOWNWARD -- the route looks
    slower than it is by whatever share of itself is missing."""
    monkeypatch.setattr(config, "CACHE", tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    # The relation names four stops; the extract holds two of them.
    nodes = [(10, 48.0, 0.0, {"name": "A"}), (11, 48.0, 1.0, {"name": "B"})]
    rels = [(200, [("n", 10, "stop"), ("n", 11, "stop"),
                   ("n", 98, "stop"), ("n", 99, "stop")],
             TRAIN | {"service": "regional", "duration": "02:00", "name": "Cut"})]
    _write(tmp_path / "t-rail.osm.pbf", nodes, rels)
    rows, dropped = fit.observations(tmp_path)
    assert rows == []
    assert dropped["stop sequence truncated by the extract"] == 1


def test_the_fit_recovers_the_constants_that_generated_the_data(fit):
    """Synthesise routes from known constants and fit them back.

    This is the assertion that would notice `_predict` losing its overhead
    term or the loss being minimised in the wrong space: the recovered pair
    must be the pair that made the data.
    """
    overhead, speed, detour = 3.0, 100.0, 1.2
    rows = []
    for i, (km, legs) in enumerate([(5, 1), (20, 2), (60, 4), (200, 8),
                                    (400, 12), (900, 20), (12, 3), (75, 6)]):
        rows.append({"route_id": i, "tier": "regional", "km": float(km),
                     "legs": legs, "name": f"r{i}",
                     "obs_min": fit._predict(overhead, speed, km, legs, detour)})
    got_overhead, got_speed = fit._fit(rows, detour)
    assert got_overhead == pytest.approx(overhead, abs=0.2)
    assert got_speed == pytest.approx(speed, rel=0.02)
    med, sd, within = fit._residuals(rows, got_overhead, got_speed, detour)
    assert med == pytest.approx(1.0, rel=1e-3) and sd < 0.01 and within == 1.0


def test_the_shipped_constants_are_the_ones_the_script_audits(fit):
    """The script reports against `calibration.toml`, so a tier added to
    `RAIL_TIERS` without a calibration entry must not silently print nothing."""
    from transport_maps.graph.rail import load_rail_calibration
    from transport_maps.sources import osm

    cal = load_rail_calibration()
    assert set(cal.tiers) == set(osm.RAIL_TIERS)
