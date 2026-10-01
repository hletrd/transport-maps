"""The page's one time notation, run for real: `fmtTime`, `fmtDur`, `fmtTick`.

P4 (node half, TE-3). Every figure on the page goes through one of these --
the headline reading, the itinerary, the city list, the legend ticks, the band
ranges -- and until now nothing ran them: the only assertions were substring
checks and the legend test's own use of `fmtTick` as a dependency. Each
expected string below is written out by hand, not computed from the function.

The seams that matter: 59.5 rounds UP into the hour notation, and 119.6 is
"2 h" rather than "1 h 60 min" (the round-once comment in `fmtTime`); under an
hour the tick says "45 min", not "0 h 45"; the unreachable sentinel is "no
scheduled route", never a number of hours.

Mutations performed and reverted, each -> red:
- `fmtTime`: round the minutes separately (`h = Math.floor(min / 60)`,
  `m = Math.round(min % 60)`) -> "60 min" at 59.5, "1 h 60 min" at 119.6.
- `fmtTime`: minutes up to two hours (`if (h < 2)`) -> "60 min" at 59.5.
- `fmtTick`: drop `.padStart(2, "0")` -> "3 h 5" for 185.
- `fmtTick`: drop the `total < 60` branch -> "0 h 45" for 45.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.web import _js
from transport_maps import config


@pytest.fixture(scope="module")
def fmt(tmp_path_factory):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH; the formatters cannot be run")
    src = f"""
const UNREACHABLE = {config.UNREACHABLE};
{_js.statement("const MAX_MINUTES = ")}
{_js.function("fmtTime")}
{_js.statement("const fmtDur = ")}
{_js.function("fmtTick")}
const fns = {{ fmtTime, fmtDur, fmtTick }};
const [name, args] = JSON.parse(process.argv[2]);
process.stdout.write(JSON.stringify(args.map((a) => fns[name](a))));
"""
    path = tmp_path_factory.mktemp("fmt") / "fmt.cjs"
    path.write_text(src, encoding="utf-8")

    def call(name: str, args: list):
        done = subprocess.run([node, str(path), json.dumps([name, args])],
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)
    return call


FMT_TIME = [
    (None, ["—", ""]),
    (0, ["0", "min"]),
    (7.4, ["7", "min"]),
    (59.4, ["59", "min"]),
    (59.5, ["1", "h"]),
    (60, ["1", "h"]),
    (61, ["1", "h 1 min"]),
    (90, ["1", "h 30 min"]),
    (119.4, ["1", "h 59 min"]),
    (119.6, ["2", "h"]),
    (185, ["3", "h 5 min"]),
    (2880, ["48", "h"]),
    (4320, ["72", "h"]),
    (4321, ["72", "h 1 min"]),
    (config.UNREACHABLE - 1, ["∞", "no scheduled route"]),
    (config.UNREACHABLE, ["∞", "no scheduled route"]),
]


def test_fmttime_says_each_value_the_one_way_the_page_uses(fmt) -> None:
    got = fmt("fmtTime", [v for v, _ in FMT_TIME])
    for (value, want), have in zip(FMT_TIME, got, strict=True):
        assert have == want, f"fmtTime({value}) = {have}, want {want}"


def test_fmtdur_joins_the_two_halves_with_one_space(fmt) -> None:
    got = fmt("fmtDur", [None, 45, 119.6, 185, config.UNREACHABLE])
    assert got == ["—", "45 min", "2 h", "3 h 5 min", "∞ no scheduled route"]


FMT_TICK = [
    (30, "30 min"),
    (45, "45 min"),
    (59.4, "59 min"),
    (59.5, "1 h"),
    (60, "1 h"),
    (70, "1 h 10"),
    (95, "1 h 35"),
    (185, "3 h 05"),
    (225, "3 h 45"),
    (955, "15 h 55"),
    (4320, "72 h"),
]


def test_fmttick_is_the_compact_form_with_padded_minutes(fmt) -> None:
    got = fmt("fmtTick", [v for v, _ in FMT_TICK])
    for (value, want), have in zip(FMT_TICK, got, strict=True):
        assert have == want, f"fmtTick({value}) = {have!r}, want {want!r}"


def test_every_band_edge_prints_without_a_zero_hour(fmt) -> None:
    """The legend's own inputs. No edge may print "0 h", and every edge under
    an hour must print in minutes, the notation `#time` uses for it."""
    edges = list(config.BAND_EDGES_MIN)
    got = fmt("fmtTick", edges)
    for edge, text in zip(edges, got, strict=True):
        assert not text.startswith("0 h"), f"edge {edge} printed {text!r}"
        assert text.endswith(" min") == (edge < 60), f"edge {edge} printed {text!r}"
