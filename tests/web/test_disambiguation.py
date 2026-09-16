"""Two cities called Suzhou must not render two identical rows.

`cityCountry` resolved an ambiguous name to a COUNTRY, so it worked only for
pairs that straddle a border. Measured against the shipped 1,464-origin index,
six of the thirteen shared names are China against China -- Changsha, Changzhi,
Fuzhou, Puyang, Suzhou, Taizhou -- and each rendered two byte-identical rows.
Three of those six (Suzhou, Fuzhou, Taizhou) are among the four pairs the
feature was written for, so the feature did not work for the cases that
prompted it.

`tests/web/test_city_country.py` could not see it: it stubs `nearestPlace` to
a constant, which is the right shape for the question that file asks (do the
two country sources agree on one spelling) and the wrong shape for this one.
This file runs the real resolver over the real gazetteer and asserts the thing
a visitor actually needs -- that the two rows differ.

A seventh case the old code missed entirely: `San José` and `San Jose` are two
display names and one folded search key. Grouping by name called them
unambiguous and labelled neither.

Mutations performed and reverted, both RED:
  * drop the `region &&` escalation in `disambigMap` -> 6 identical pairs.
  * group by `c.name` instead of `c.key` -> San Jose loses its label. This
    mutation stayed GREEN on the first version of this file, which asserted
    only that the two rows' text differs -- and "San Jose" already differs
    from "San José". The test now asserts the label, which is the thing the
    grouping produces. Recorded because CLAUDE.md asks for it: a guard that
    cannot fail is worse than none, and this one could not until it was
    rewritten.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.conftest import skip_without_dist
from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

#: The pairs that country alone cannot separate, and which therefore prove the
#: escalation ran. Both members are in China in every one.
SAME_COUNTRY_PAIRS = ("changsha", "fuzhou", "puyang", "suzhou", "taizhou")

#: Known residue, tracked as DEF17-1 in plan/2026-09-17-c17-review-findings.md:
#: the gazetteer holds two settlements both named Changzhi in Shanxi, 145 km
#: apart, so no admin-1 region separates them and the next distinct place is
#: 55-81 km away. Naming that would be a false label, so the row stays
#: ambiguous until `origins.toml` carries a discriminator.
UNRESOLVED = ("changzhi",)


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    i = APP.index("{", start)
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError(f"function {name} is not brace-balanced")


def _fold_line() -> str:
    """The page's own `fold`, lifted verbatim rather than reimplemented.

    A reimplementation here would test this file's idea of folding, not the
    page's, and the two have diverged before (`FOLD_DROP` grew five apostrophe
    variants in cycle 15).
    """
    start = APP.index("const FOLD_DROP =")
    end = APP.index("const cities =", start)
    return APP[start:end]


@pytest.fixture(scope="module")
def rendered() -> dict[str, list[list[str]]]:
    """Per shared folded name, each member's `[rendered row, label]`."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the disambiguator cannot be run")
    index = config.DIST / "index.json"
    places = config.DIST / "places.json"
    for path in (index, places):
        if not path.exists():
            skip_without_dist(f"{path.name} is not built")

    src = f"""
const fs = require("node:fs");
const meta = JSON.parse(fs.readFileSync({json.dumps(str(index))}, "utf8"));
const p = JSON.parse(fs.readFileSync({json.dumps(str(places))}, "utf8"));
let places = {{
  lat: Float32Array.from(p.places, (x) => x[3]),
  lon: Float32Array.from(p.places, (x) => x[4]),
  rows: p.places,
}};
{_fold_line()}
const cities = meta.origins.slice().sort((a, b) => a.name.localeCompare(b.name));
for (const c of cities) c.key = fold(c.name);
const dn = new Intl.DisplayNames(["en"], {{ type: "region" }});
const countryName = (code) => (code ? (dn.of(code) || code) : "");
let _disambig = null;
{_function("nearestPlace")}
{_function("cityCountry")}
{_function("disambigMap")}
const label = (c) => disambigMap().get(c.slug) ?? "";
const groups = new Map();
for (const c of cities) {{
  let g = groups.get(c.key);
  if (!g) groups.set(c.key, (g = []));
  g.push(c);
}}
const out = {{}};
for (const [k, g] of groups) {{
  if (g.length < 2) continue;
  // Exactly the string the row builds: the name span plus the .disambig <i>,
  // and the label on its own, so a test can tell "these two rows differ" from
  // "the disambiguator ran".
  out[k] = g.map((c) => [label(c) ? `${{c.name}} ${{label(c)}}` : c.name, label(c)]);
}}
process.stdout.write(JSON.stringify(out));
"""
    done = subprocess.run([node, "-e", src], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_shipped_roster_still_has_names_two_cities_share(rendered):
    """Guards the rest of this file against passing vacuously.

    If the roster ever stops sharing a name, every assertion below becomes a
    loop over nothing. That is a legitimate state of the world, but it must be
    noticed rather than read as a pass.
    """
    assert len(rendered) >= 10, (
        f"only {len(rendered)} shared names in the shipped index; this file's "
        "other tests would be checking almost nothing")


def test_no_two_departure_rows_render_the_same_text(rendered):
    """The defect, as a visitor met it: two adjacent rows, nothing to choose by."""
    identical = {
        key: [r for r, _ in pair] for key, pair in rendered.items()
        if len({r for r, _ in pair}) != len(pair) and key not in UNRESOLVED
    }
    assert not identical, (
        "these shared names render two identical rows: "
        + "; ".join(f"{k}: {rows}" for k, rows in sorted(identical.items())))


@pytest.mark.parametrize("key", SAME_COUNTRY_PAIRS)
def test_a_pair_inside_one_country_is_separated_by_its_region(rendered, key):
    """The escalation is what is being asserted, not just distinctness.

    Both members are in China, so a country-only label cannot tell them apart:
    if these differ, the gazetteer's admin-1 region reached the row.
    """
    pair = rendered.get(key)
    assert pair, f"{key} is no longer a shared name in the shipped index"
    rows = [r for r, _ in pair]
    assert len(set(rows)) == len(rows), f"{key} renders identical rows: {rows}"
    assert all("China" in r for r in rows), rows
    assert all(r.count(",") >= 1 for r in rows), (
        f"{key} was separated without a region, so it is not the escalation "
        f"that fixed it: {rows}")


def test_a_pair_that_only_a_country_needs_does_not_gain_a_region(rendered):
    """Escalation is per group, deliberately.

    Country separates seven of the pairs, and those rows should keep reading
    "Barcelona Spain". Escalating globally would rewrite them all to
    "Barcelona Catalonia, Spain" -- more words for no added meaning, in a
    26.2 px row.
    """
    for key in ("barcelona", "london", "hyderabad", "newcastle"):
        pair = rendered.get(key)
        assert pair, f"{key} is no longer a shared name"
        rows = [r for r, _ in pair]
        assert len(set(rows)) == len(rows), f"{key} renders identical rows: {rows}"
        assert all("," not in r for r in rows), (
            f"{key} gained a region it does not need: {rows}")


def test_names_that_differ_only_by_an_accent_are_still_one_group(rendered):
    """`San José` and `San Jose` are two names and one search key.

    They fold together, rank identically, and land at adjacent rows, so a
    visitor sees two rows and gets one answer from Enter. Grouping by display
    name called them unambiguous and labelled neither.
    """
    pair = rendered.get("san jose")
    assert pair, "San Jose/San José are no longer in the shipped roster"
    # Distinctness is NOT the assertion here, and asserting it was this test's
    # first mistake: "San Jose" and "San José" already differ as text, so the
    # check passed while `disambigMap` grouped by display name and labelled
    # neither row. What a visitor needs is the LABEL -- the two rank
    # identically, so without one, Enter picks a city and does not say which.
    labels = [label for _, label in pair]
    assert all(labels), (
        "San Jose/San José carry no disambiguator, so disambigMap is keying on "
        f"the display name again rather than the folded key: {pair}")
    assert len(set(labels)) == len(labels), f"both rows say the same thing: {pair}"


def test_the_unresolved_pair_is_the_one_the_plan_records(rendered):
    """DEF17-1 names exactly one residue. If a second appears, or if this one
    resolves, the deferral row is wrong and must be updated.
    """
    still = {k for k, pair in rendered.items()
             if len({r for r, _ in pair}) != len(pair)}
    assert still == set(UNRESOLVED), (
        f"unresolved pairs are {sorted(still)}, but DEF17-1 records "
        f"{sorted(UNRESOLVED)}")


def test_the_accessible_name_carries_the_disambiguator():
    """Seven of thirteen pairs were distinguishable by eye and none by ear:
    the row's aria-label was built from `c.name` and dropped the label the row
    had just been given.
    """
    start = APP.index('b.setAttribute("aria-label"')
    window = APP[start - 400:start + 400]
    assert "${said}" in window, (
        "the aria-label no longer interpolates the disambiguated name")
    assert "`${c.name}. " not in window, (
        "the aria-label is built from the bare name again")
