"""`originNear()` decides which city a dot claims. Prove the fast one agrees.

`originNear` used to scan all 553 origins on every call, and `dottedCityRows`
makes one call per gazetteer label: 900 x 553 = **497,700 haversines in one
synchronous task** on the load path, and 900 x 1,464 = **1,317,600** once the
running rebuild publishes its origin set.

Cycle 15 replaced the scan with a latitude-band prune. That is a dangerous
kind of change to make on this particular function, and the comments around it
say why: it decides whether a label is a *button that departs from a city* or
an inert place name, and getting it wrong is how "Ota" became a button that
departed from Tokyo and "Johor Bahru" one that departed from Singapore --
a different country. The measured tuning (15 km, 80 km, 14.72 km, 56.6 px at
zoom 8) is all in `app.js`.

So this file does not test that the prune is *fast*. It tests that it is
**exact**: for every one of the 34,135 gazetteer rows the page ships, at both
radii the page uses, the pruned implementation must return the SAME origin as
the linear scan -- not a nearby one, not usually, the same one.

The prune is exact by construction, and the argument is worth writing down
because the test can only check the cases the data happens to contain. On a
sphere the great-circle distance between two points is never less than the
meridional arc between their latitudes. `haversineKm` is spherical with
R = 6371.0088, so a degree of latitude is exactly R * pi/180 km everywhere.
Therefore |dLat| * KM_PER_DEG_LAT > maxKm implies distance > maxKm, and an
origin outside the band cannot be the answer. Nothing is discarded that the
scan could have returned.

The one place the two could still diverge is an exact tie, where the scan's
strict `km < bestKm` keeps the lowest index in `meta.origins` order and a
latitude-ordered walk would keep a different one. The implementation carries
the original index to break ties the same way; `test_a_tie_goes_to_the_same_origin`
constructs the tie that the real data does not contain.

MUTATIONS PERFORMED, and the results as measured. Note the direction: the band
is `maxKm / KM_PER_DEG_LAT`, so a LARGER constant makes a NARROWER band, which
is the dangerous way to be wrong.

  - `KM_PER_DEG_LAT` 111.195 -> **130** (band too narrow): **RED**, and in the
    way that matters -- **128 of 34,135** shipped rows disagree at maxKm=15
    and **340 of 34,135** at maxKm=80, and every single disagreement is of
    the form `scan: <a city>, pruned: null` -- Dubai, Manila, Kuala Lumpur,
    Kolkata, Osaka, Hong Kong, Helsinki, Sao Paulo among them. That is a label
    that should be a departure button silently becoming an inert place name.
  - `KM_PER_DEG_LAT` -> **90** (band too wide): **GREEN, 6 passed** -- as it
    must be. A wider band costs time and cannot change the answer. Recorded
    because it shows what this file does and does not measure: correctness,
    never speed.
  - drop the `e.i < bestI` tie-break: **RED** on
    `test_a_tie_goes_to_the_same_origin` (and on the slice guard, which names
    the token). Green on all 34,135 real rows -- which is exactly why that
    test builds its own tie instead of hoping the gazetteer contains one.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.conftest import skip_without_dist
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")
DIST = config.ROOT / "dist"


def _slice(start_marker: str, end_marker: str) -> str:
    """Source between two anchors, both of which must be present."""
    a = APP.index(start_marker)
    b = APP.index(end_marker, a)
    return APP[a:b]


# haversineKm through the end of originNear: the whole unit under test, taken
# verbatim rather than retyped, so a change to either cannot pass unnoticed.
UNDER_TEST = _slice("function haversineKm(", "//: Which gazetteer row carries") + _slice(
    "// Departure city within reach of a point", "//: Drop the destination")


def test_the_slice_holds_what_it_claims() -> None:
    """The guard on the guard: a truncated slice would fail to define
    `originNear` and every test below would error rather than pass, but a
    slice that silently lost the PRUNE would still run -- as the old linear
    scan -- and agree with itself perfectly.
    """
    for token in ("function haversineKm(", "6371.0088", "KM_PER_DEG_LAT",
                  "originsByLat", "lowerBoundLat", "function originNear(",
                  "e.i < bestI"):
        assert token in UNDER_TEST, f"{token} is not in the slice under test"


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; originNear cannot be run")
    return exe


def _origins() -> list[dict]:
    index = DIST / "index.json"
    if not index.exists():
        skip_without_dist("dist/index.json is not built; no origins to scan")
    return json.loads(index.read_text(encoding="utf-8"))["origins"]


def _places() -> list[list]:
    path = DIST / "places.json"
    if not path.exists():
        skip_without_dist("dist/places.json is not built; no gazetteer to scan")
    return json.loads(path.read_text(encoding="utf-8"))["places"]


def _run(node: str, tmp_path, origins: list[dict], probes: list[tuple[float, float]],
         max_km: float) -> dict:
    """Run both implementations over the same probes and diff them in node.

    The reference is the linear scan exactly as it stood before the change,
    written out here rather than sliced, because the file no longer contains
    it to slice.
    """
    harness = """
// On stdin: the shipped origins and places overrun Linux's 128 KiB limit on
// one command-line argument (the page gate failed on h200, 2026-10-06).
const [origins, probes, maxKm] = JSON.parse(require("fs").readFileSync(0, "utf8"));
const meta = { origins };
""" + UNDER_TEST + """
function originNearReference(lat, lon, maxKm) {
  let best = null, bestKm = maxKm;
  for (const o of meta.origins) {
    const km = haversineKm(lat, lon, o.lat, o.lon);
    if (km < bestKm) { best = o; bestKm = km; }
  }
  return best;
}
let checked = 0, matched = 0;
const diffs = [];
for (const [lat, lon] of probes) {
  const a = originNearReference(lat, lon, maxKm);
  const b = originNear(lat, lon, maxKm);
  checked++;
  if ((a && a.slug) === (b && b.slug)) { matched++; continue; }
  if (diffs.length < 8) {
    diffs.push({ lat, lon, scan: a && a.slug, pruned: b && b.slug });
  }
}
process.stdout.write(JSON.stringify({ checked, matched, diffs }));
"""
    path = tmp_path / "originNear.cjs"
    path.write_text(harness, encoding="utf-8")
    done = subprocess.run(
        [node, str(path)], input=json.dumps([origins, probes, max_km]),
        capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


@pytest.mark.parametrize("max_km", [15, 80])
def test_the_prune_agrees_with_the_scan_on_every_shipped_place(
        node: str, tmp_path, max_km: int) -> None:
    """Both radii the page uses, over the whole shipped gazetteer.

    15 km is `dottedCityRows`' radius, the one that decides whether a label is
    a departure button. 80 km is the default, used for the pinned destination.
    """
    origins = _origins()
    probes = [[r[3], r[4]] for r in _places()]
    out = _run(node, tmp_path, origins, probes, max_km)
    assert out["checked"] == len(probes)
    assert out["matched"] == out["checked"], (
        f"at maxKm={max_km} the pruned originNear disagrees with the linear "
        f"scan on {out['checked'] - out['matched']} of {out['checked']} "
        f"shipped gazetteer rows: {out['diffs']}")


def test_the_prune_agrees_at_the_poles_and_the_antimeridian(
        node: str, tmp_path) -> None:
    """The gazetteer is not a fair sample of the sphere: it has no probe at a
    pole and few near +/-180, and those are where a latitude band behaves least
    like a circle. A band is a band of LATITUDE, so longitude wrap cannot
    affect which origins it admits -- but that is an argument, and this is the
    check.
    """
    origins = _origins()
    probes = [[lat, lon]
              for lat in (-89.9, -66.5, -45, -0.001, 0, 0.001, 45, 66.5, 89.9)
              for lon in (-180, -179.99, -90, -0.001, 0, 0.001, 90, 179.99, 180)]
    for max_km in (15, 80, 500):
        out = _run(node, tmp_path, origins, probes, max_km)
        assert out["matched"] == out["checked"], (
            f"at maxKm={max_km} the prune disagrees at an extreme: {out['diffs']}")


def test_the_prune_agrees_around_every_origin(node: str, tmp_path) -> None:
    """The cases that matter most are the ones just inside and just outside
    the radius, and the gazetteer supplies those only by luck. Ring the probes
    around each origin at 0.5x, 0.99x, 1.0x and 1.01x the radius instead.

    The 1.0x ring is the boundary itself, where the scan's strict `km <
    bestKm` returns null: a prune that admitted it would be a behaviour
    change, not an optimisation.
    """
    origins = _origins()
    deg = 80.0 / (6371.0088 * 3.141592653589793 / 180.0)
    probes = []
    for o in origins:
        for f in (0.5, 0.99, 1.0, 1.01):
            probes.append([o["lat"] + deg * f, o["lon"]])
            probes.append([o["lat"], o["lon"] + deg * f])
    out = _run(node, tmp_path, origins, probes, 80)
    assert out["matched"] == out["checked"], (
        f"the prune disagrees on a ring probe: {out['diffs']}")


def test_a_tie_goes_to_the_same_origin(node: str, tmp_path) -> None:
    """Two origins exactly equidistant from a point.

    The scan's strict `km < bestKm` keeps the FIRST in `meta.origins` order.
    A latitude-ordered walk reaches them in a different order, so without the
    `e.i < bestI` tie-break it would keep the southern one instead. The real
    gazetteer contains no such tie, which is exactly why this test builds one:
    dropping the tie-break leaves every other test in this file green.
    """
    # Symmetric about the equator, so the probe at lat 0 is equidistant from
    # both by construction rather than by floating-point luck. `beta` is first
    # in meta.origins order and NORTH, so latitude order reaches `alpha` first.
    origins = [
        {"slug": "beta", "name": "Beta", "lat": 1.0, "lon": 10.0},
        {"slug": "alpha", "name": "Alpha", "lat": -1.0, "lon": 10.0},
    ]
    out = _run(node, tmp_path, origins, [[0.0, 10.0]], 500)
    assert out["matched"] == out["checked"], (
        f"a tie resolves differently under the prune: {out['diffs']}")
