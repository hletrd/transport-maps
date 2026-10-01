"""The page and the emitter must compute the SAME block slot.

The reading tier ships no per-cell index: the emitter writes a value at a slot
it computes, and the page reads a slot it computes, and nothing in the file
connects the two. If they ever disagree the file is still exactly the right
length, every fetch still succeeds, and every land cell on Earth reports a
plausible travel time from somewhere else nearby. No length check, no schema
check and no browser gate can see that.

So this runs `readingSlot` out of `web/app.js` under Node and compares it,
cell by cell, against `transport_maps.emit.hover.reading_slot` -- including
every child of both res-3 pentagons that hold land, which is the only place
the two plausible orderings differ.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import h3
import pytest

from tests.web import _js
from transport_maps import config
from transport_maps.emit import hover

APP = (config.ROOT / "web" / "app.js").read_text(encoding="utf-8")

# Both res-3 pentagons that hold land. 833000fffffffff contains Dalian, which
# is a departure city, so a disagreement here is visible on the shipped site.
PENTAGONS = ("830800fffffffff", "833000fffffffff")


def _function(name: str) -> str:
    return _js.function(name)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the page's readingSlot cannot be run")
    path = tmp_path_factory.mktemp("reading") / "slot.cjs"
    # The two constants come from index.json on the real page; they are
    # injected here from config so a change to either is exercised rather
    # than hard-coded into the test.
    path.write_text(
        f"const READING_PARENT_RES = {config.READING_PARENT_RES};\n"
        f"const READING_RES = {config.READING_RES};\n"
        + _function("readingSlot")
        + "\nconst cells = JSON.parse(process.argv[2]);\n"
          'process.stdout.write(JSON.stringify('
          'cells.map((c) => readingSlot(BigInt("0x" + c)))));\n',
        encoding="utf-8")

    def call(cells):
        done = subprocess.run([exe, str(path), json.dumps(cells)],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


def test_the_page_agrees_with_the_emitter_over_a_dense_neighbourhood(run):
    cells = h3.grid_disk(h3.latlng_to_cell(37.5665, 126.9780, config.READING_RES), 10)
    assert run(list(cells)) == [hover.reading_slot(c) for c in cells]


@pytest.mark.parametrize("pentagon", PENTAGONS)
def test_the_page_agrees_with_the_emitter_under_a_land_pentagon(run, pentagon):
    """The only cells that can separate the two plausible orderings. For a
    hexagon parent h3's own cellToChildPos gives the same answer as the digit
    form for all 343 children, so a test built only from hexagons would pass
    with either side using either rule."""
    kids = h3.cell_to_children(pentagon, config.READING_RES)
    assert len(kids) == 286
    assert run(list(kids)) == [hover.reading_slot(k) for k in kids]


@pytest.mark.parametrize("pentagon", PENTAGONS)
def test_this_pentagon_still_separates_the_two_orderings(run, pentagon):
    """Guards the guard above: if h3 ever renumbered pentagon children so the
    two rules agreed, the test would keep passing while proving nothing."""
    kids = h3.cell_to_children(pentagon, config.READING_RES)
    differ = sum(1 for k in kids
                 if hover.reading_slot(k) != h3.cell_to_child_pos(k, config.READING_PARENT_RES))
    assert differ == 285


def test_every_slot_is_inside_the_published_stride(run):
    cells = list(h3.cell_to_children(PENTAGONS[0], config.READING_RES))
    cells += list(h3.grid_disk(h3.latlng_to_cell(-33.87, 151.21, config.READING_RES), 6))
    slots = run(cells)
    assert min(slots) >= 0
    assert max(slots) < config.READING_SLOTS


@pytest.fixture(scope="module")
def guards(tmp_path_factory):
    """checkedParents and checkedReading, run rather than grepped for."""
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the page's refusals cannot be run")
    path = tmp_path_factory.mktemp("guards") / "guards.cjs"
    path.write_text(
        f"const READING_SLOTS = {config.READING_SLOTS};\n"
        + _function("checkedParents") + "\n" + _function("checkedReading")
        + "\nconst [fn, args] = JSON.parse(process.argv[2]);\n"
          "try {\n"
          "  const a = fn === 'checkedReading'\n"
          "    ? [new ArrayBuffer(args[0]), args[1], args[2]]\n"
          "    : [{length: args[0]}, args[1], args[2]];\n"
          "  const out = ({checkedParents, checkedReading})[fn](...a);\n"
          "  process.stdout.write(JSON.stringify({ok: out.length}));\n"
          "} catch (e) { process.stdout.write(JSON.stringify({error: e.message})); }\n",
        encoding="utf-8")

    def call(fn, *args):
        done = subprocess.run([exe, str(path), json.dumps([fn, list(args)])],
                              capture_output=True, text=True, check=True)
        return json.loads(done.stdout)
    return call


def test_a_directory_of_the_wrong_length_is_refused(guards):
    assert "ok" in guards("checkedParents", 14598, 14598, "reading_parents.bin")
    bad = guards("checkedParents", 14597, 14598, "reading_parents.bin")
    assert "error" in bad and "14597" in bad["error"], bad


def test_a_directory_with_no_declared_count_is_allowed(guards):
    """An index.json from before the field existed must not break the page."""
    assert "ok" in guards("checkedParents", 14598, None, "reading_parents.bin")


def test_a_reading_array_from_another_build_is_refused(guards):
    want = 3 * config.READING_SLOTS * 2
    assert guards("checkedReading", want, 3, "x.r6.bin")["ok"] == 3 * config.READING_SLOTS
    # One block short: still a whole number of blocks, still parses, and every
    # reading after the missing block would come from the wrong place.
    bad = guards("checkedReading", want - config.READING_SLOTS * 2, 3, "x.r6.bin")
    assert "error" in bad and "different builds" in bad["error"], bad
    # Two bytes short: not even a whole number of slots.
    assert "error" in guards("checkedReading", want - 2, 3, "x.r6.bin")


def test_the_page_reads_the_stride_from_the_index_rather_than_assuming_it():
    """readingSlots has to come from index.json: 342 instead of 343 finds the
    right block and reads the wrong slot inside it, in range, everywhere.
    A source assertion is all that can check a module-level const, so it is
    made over COMMENT-STRIPPED source -- the cycle-6 rule."""
    source = "\n".join(ln for ln in APP.splitlines() if not ln.lstrip().startswith("//"))
    assert "meta.readingSlots" in source
    assert "meta.readingParentCount" in source
