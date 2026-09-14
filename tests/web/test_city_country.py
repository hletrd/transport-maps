"""One departure list, two ways of naming a country.

`emit/index.py` writes `country` into index.json only for origins whose row in
`data/origins.toml` carries one. The 911 added on 2026-09-14 do; the 553 before
them do not. The field is an ISO-2 code.

`cityCountry` returned that code verbatim and fell back to places.json -- which
resolves a country NAME -- for everything else. So the same alphabetical list
printed "London United Kingdom" directly above "London CA". Ambiguous names
went from 4 to 13 with that tranche, and 8 of the 13 pairs are mixed-source, so
this was most of them.

The airport rows hit the identical problem and already had the fix:
`countryName()` wraps `Intl.DisplayNames`, needs no data and no network. The
city rows just were not using it.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from transport_maps import config

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")


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


def _const_iife(name: str) -> str:
    """`const NAME = (() => { ... })();` -- countryName's shape."""
    start = APP.index(f"const {name} = (() => {{")
    i = APP.index("{", start)
    depth = 0
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:APP.index(";", j) + 1]
    raise AssertionError(f"const {name} is not brace-balanced")


@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; cityCountry cannot be run")
    return exe


@pytest.fixture(scope="module")
def run(node: str, tmp_path_factory):
    src = (_const_iife("countryName") + "\n" + _function("cityCountry") + "\n"
           # places.json's resolver, stubbed: it is a different data path and
           # its own tests cover it. What matters here is that the two paths
           # agree on what a country looks like.
           "let places = true;\n"
           "function nearestPlace() { return { country: 'South Korea' }; }\n")
    path = tmp_path_factory.mktemp("cc") / "cc.cjs"
    path.write_text(
        src + "process.stdout.write(JSON.stringify("
        "cityCountry(JSON.parse(process.argv[2]))));\n", encoding="utf-8")

    def call(city: dict):
        done = subprocess.run([node, str(path), json.dumps(city)],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


@pytest.mark.parametrize("code,expected", [
    ("MY", "Malaysia"),
    ("GB", "United Kingdom"),
    ("CA", "Canada"),
    ("KR", "South Korea"),
    ("US", "United States"),
])
def test_an_iso2_code_is_resolved_to_the_country_name(run, code, expected):
    """Mutation performed and reverted: `return c.country` instead of
    `return countryName(c.country)` -> red, the raw code comes back.
    """
    assert run({"name": "X", "country": code, "lat": 0, "lon": 0}) == expected


def test_the_two_sources_agree_on_one_london(run):
    """The defect, stated as the visitor saw it: two rows, same name, one
    country spelled out and one abbreviated."""
    coded = run({"name": "London", "country": "GB", "lat": 51.5, "lon": -0.1})
    # No `country` field: the places.json path, which yields a name.
    fallback = run({"name": "London", "lat": 42.98, "lon": -81.24})
    assert coded == "United Kingdom"
    assert " " in fallback or len(fallback) > 2, (
        "the fallback path returned something code-shaped")
    assert len(coded) > 2, "an ISO-2 code reached the list"


def test_a_code_the_platform_cannot_name_never_blanks_the_row(run):
    """A blank country is worse than an odd one: it is the disambiguation two
    same-named cities depend on.

    `Intl.DisplayNames` has three behaviours and the wrapper must survive all
    of them -- verified against node, not assumed: "XX" comes back unchanged,
    "ZZ" comes back as "Unknown Region", and "1A" throws a RangeError. Only
    the third needs the try/catch, which is why it is easy to write a wrapper
    that looks right and blanks the row.
    """
    for code in ("XX", "ZZ", "1A", "QQ"):
        got = run({"name": "X", "country": code, "lat": 0, "lon": 0})
        assert got, f"country {code!r} resolved to an empty string"

    # An absent code is the 553 legacy origins: fall through to places.json.
    assert run({"name": "X", "country": "", "lat": 0, "lon": 0}) == "South Korea"


def test_the_departure_rows_and_the_airport_rows_use_the_same_resolver():
    """The airport list fixed this first. If the two ever diverge again, the
    same list shows both spellings.
    """
    assert "countryName(c.country)" in APP, (
        "cityCountry no longer routes through countryName")
    assert APP.count("countryName(") >= 2, (
        "only one caller left; the airport rows or the city rows lost it")
