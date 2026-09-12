"""The res-6 reading tier: the block layout, and the arithmetic that addresses it.

The format's most likely failure is not a crash. It is that the emitter and the
page each compute a slot index and the two quietly disagree, so every land cell
reports a plausible time from somewhere else. These tests pin the arithmetic to
h3's OWN answers rather than to a second copy of the same reasoning, and cover
both res-3 pentagons by name -- the case where h3's `cell_to_child_pos` and
digit order genuinely differ.
"""

import inspect
import re
from typing import ClassVar

import h3
import numpy as np
import pytest

from transport_maps import config
from transport_maps.emit import hover

# The two res-3 pentagons that hold land. One of them contains Dalian, a
# departure city, so getting them wrong is visible on the shipped site.
PENTAGONS = ("830800fffffffff", "833000fffffffff")

SEOUL = h3.latlng_to_cell(37.5665, 126.9780, config.READING_RES)
TOKYO = h3.latlng_to_cell(35.6762, 139.6503, config.READING_RES)


class FakeIndex:
    """Two res-6 cells under different res-3 parents, neither of them split."""

    base_cells: ClassVar[list[str]] = sorted([SEOUL, TOKYO])
    cells: ClassVar[list[str]] = sorted([SEOUL, TOKYO])
    base_index: ClassVar[np.ndarray] = np.array([0, 1], dtype=np.int64)
    fine: ClassVar[np.ndarray] = np.zeros(2, dtype=bool)
    n_cells = 2

    def try_cell_index(self, cell):
        return self.cells.index(cell) if cell in self.cells else None


# --- the arithmetic, pinned to h3 --------------------------------------------
def test_to_res_agrees_with_h3_cell_to_parent():
    """_to_res is cell_to_parent vectorised. If it drifts, the page searches
    the right directory for cells it does not contain and every land reading
    reports open water."""
    cells = [SEOUL, TOKYO, *h3.cell_to_children(PENTAGONS[0], config.READING_RES)[:20]]
    ids = np.array([h3.str_to_int(c) for c in cells], dtype=np.uint64)
    for res in (config.READING_PARENT_RES, config.HOVER_RES, 5):
        mine = hover._to_res(ids, res)
        theirs = np.array([h3.str_to_int(h3.cell_to_parent(c, res)) for c in cells],
                          dtype=np.uint64)
        assert (mine == theirs).all(), f"_to_res disagrees with h3 at resolution {res}"


def _slot_by_hand(cell: str) -> int:
    """A second, independent implementation of the slot.

    Written longhand against the h3 bit layout -- digit r occupies bits
    (45-3r)..(47-3r) -- so it shares no code with hover._slots. It exists
    because the first version of this file tested reading_slot against itself:
    replacing it wholesale with h3.cell_to_child_pos kept all fourteen tests
    green, even though the two disagree for 285 of the 286 children of each
    land pentagon, which is the exact case the format is padded for.
    """
    v = h3.str_to_int(cell)
    return ((v >> 33) & 7) * 49 + ((v >> 30) & 7) * 7 + ((v >> 27) & 7)


@pytest.mark.parametrize("pentagon", PENTAGONS)
def test_the_slot_is_the_h3_digits_not_the_child_position(pentagon):
    """For a hexagon parent the two agree on all 343 children, so only a
    pentagon can tell them apart. If the emitter ever switches to
    cell_to_child_pos, this is what goes red."""
    assert (config.READING_RES, config.READING_PARENT_RES) == (6, 3), (
        "the longhand above is written for res 3 -> 6; update it with the constants")
    kids = h3.cell_to_children(pentagon, config.READING_RES)
    assert [hover.reading_slot(k) for k in kids] == [_slot_by_hand(k) for k in kids]
    disagree = sum(1 for k in kids
                   if hover.reading_slot(k) != h3.cell_to_child_pos(k, config.READING_PARENT_RES))
    assert disagree == 285, (
        "digit order and cell_to_child_pos no longer differ here, so this guard "
        "would pass with either -- find a case that still separates them")


def test_the_emitted_file_places_a_pentagon_child_at_its_digit_slot(tmp_path):
    """The end-to-end version: the byte the page will read must sit where the
    independent derivation says, not merely where hover.reading_slot says."""
    parent = PENTAGONS[1]
    kid = h3.cell_to_children(parent, config.READING_RES)[-1]

    class PentIndex(FakeIndex):
        base_cells: ClassVar[list[str]] = [kid]
        cells: ClassVar[list[str]] = [kid]
        base_index: ClassVar[np.ndarray] = np.array([0], dtype=np.int64)
        fine: ClassVar[np.ndarray] = np.zeros(1, dtype=bool)
        n_cells = 1

    idx = PentIndex()
    out = tmp_path / "p.r6.bin"
    hover.write_reading(idx, np.array([42.0]), out)
    raw = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert raw[_slot_by_hand(kid)] == 42
    assert _slot_by_hand(kid) != h3.cell_to_child_pos(kid, config.READING_PARENT_RES)


@pytest.mark.parametrize("pentagon", PENTAGONS)
def test_every_child_of_a_land_pentagon_gets_a_distinct_slot(pentagon):
    """A res-3 pentagon has 286 res-6 descendants, not 343. The stride stays
    343 and the 57 holes are padding; what must hold is that no two children
    collide, because a collision silently overwrites one cell with another."""
    kids = h3.cell_to_children(pentagon, config.READING_RES)
    assert len(kids) == 286, "the pentagon premise this format is padded for has changed"
    slots = [hover.reading_slot(k) for k in kids]
    assert len(set(slots)) == len(kids)
    assert 0 <= min(slots) and max(slots) < config.READING_SLOTS


def test_a_hexagon_parent_has_exactly_the_stride_many_children():
    parent = h3.cell_to_parent(SEOUL, config.READING_PARENT_RES)
    assert not h3.is_pentagon(parent)
    kids = h3.cell_to_children(parent, config.READING_RES)
    assert len(kids) == config.READING_SLOTS
    assert sorted(hover.reading_slot(k) for k in kids) == list(range(config.READING_SLOTS))


def test_slots_do_not_collide_across_a_real_neighbourhood():
    """A collision inside one block is the failure a length check cannot see:
    the file is exactly the right size and two cells share a value."""
    cells = h3.grid_disk(SEOUL, 12)
    keys = {(h3.cell_to_parent(c, config.READING_PARENT_RES), hover.reading_slot(c))
            for c in cells}
    assert len(keys) == len(cells)


# --- the emitted file --------------------------------------------------------
def _read(tmp_path, minutes):
    idx = FakeIndex()
    out = tmp_path / "o.r6.bin"
    hover.write_reading(idx, np.asarray(minutes, dtype=float), out)
    return idx, np.frombuffer(out.read_bytes(), dtype="<u2")


def test_the_array_is_exactly_one_block_per_parent(tmp_path):
    idx, raw = _read(tmp_path, [10, 20])
    parents = hover.reading_parents(idx)
    assert len(raw) == len(parents) * config.READING_SLOTS
    assert raw.nbytes == len(parents) * config.READING_SLOTS * 2


def test_a_cell_reads_back_at_its_own_block_and_slot(tmp_path):
    """The round trip the page performs: parent -> block, digits -> slot."""
    idx, raw = _read(tmp_path, [10, 20])
    parents = hover.reading_parents(idx)
    for cell, want in zip(idx.cells, [10, 20]):
        block = parents.index(h3.cell_to_parent(cell, config.READING_PARENT_RES))
        assert raw[block * config.READING_SLOTS + hover.reading_slot(cell)] == want


def test_padding_reads_as_unreachable_not_as_a_time(tmp_path):
    """18.3% of the shipped array is padding. Zero would read as "you are
    already there" for a fifth of every block; the sentinel reads as no route."""
    idx, raw = _read(tmp_path, [10, 20])
    written = {
        hover.reading_parents(idx).index(h3.cell_to_parent(c, config.READING_PARENT_RES))
        * config.READING_SLOTS + hover.reading_slot(c)
        for c in idx.cells
    }
    padding = [v for i, v in enumerate(raw.tolist()) if i not in written]
    assert padding, "the fixture has no padding, so this guard proves nothing"
    assert set(padding) == {config.UNREACHABLE}


def test_an_unreachable_cell_keeps_the_sentinel(tmp_path):
    _, raw = _read(tmp_path, [np.inf, 20])
    assert config.UNREACHABLE in raw.tolist()


def test_a_journey_past_the_ceiling_becomes_the_sentinel(tmp_path):
    """65,534 minutes is 45 days. The page must say "no route", not print it."""
    idx, raw = _read(tmp_path, [hover.MAX_MINUTES, 20])
    parents = hover.reading_parents(idx)
    cell = idx.cells[0]
    block = parents.index(h3.cell_to_parent(cell, config.READING_PARENT_RES))
    assert raw[block * config.READING_SLOTS + hover.reading_slot(cell)] == config.UNREACHABLE


def test_the_directory_is_sorted_uint64_at_the_parent_resolution(tmp_path):
    """The page binary-searches this file. Unsorted, the search misses and
    every land cell reads open water."""
    idx = FakeIndex()
    out = tmp_path / "reading_parents.bin"
    hover.write_reading_parents(idx, out)
    ids = np.frombuffer(out.read_bytes(), dtype="<u8")
    assert len(ids) == len(hover.reading_parents(idx))
    assert (np.diff(ids.astype(object)) > 0).all(), "reading_parents.bin is not sorted"
    for v in ids.tolist():
        assert h3.get_resolution(h3.int_to_str(int(v))) == config.READING_PARENT_RES


def test_the_two_tiers_describe_the_same_universe(tmp_path):
    """The res-4 parents of the reading grid must be exactly hover_cells.bin's
    set. If either tier covered ground the other did not, the page could paint
    a band with no reading under it, or read a time off the edge of the map."""
    idx = FakeIndex()
    from_reading = {h3.cell_to_parent(c, config.HOVER_RES) for c in idx.base_cells}
    assert sorted(from_reading) == hover.hover_cells(idx)


def test_the_layout_is_reusable_across_origins(tmp_path):
    """The layout is built once and carried into the fork pool. A layout that
    depended on the values would give every origin after the first the first
    origin's geometry."""
    idx = FakeIndex()
    layout = hover.reading_layout(idx)
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    hover.write_reading(idx, np.array([10.0, 20.0]), a, layout=layout)
    hover.write_reading(idx, np.array([30.0, 40.0]), b, layout=layout)
    ra = np.frombuffer(a.read_bytes(), dtype="<u2")
    rb = np.frombuffer(b.read_bytes(), dtype="<u2")
    assert sorted(set(ra.tolist()) - {config.UNREACHABLE}) == [10, 20]
    assert sorted(set(rb.tolist()) - {config.UNREACHABLE}) == [30, 40]
    assert hover.reading_layout(idx).dest.tolist() == layout.dest.tolist()


def test_the_stride_is_the_child_count_of_a_hexagon():
    """READING_SLOTS is a derived constant. Pinning it to h3's own child count
    means a change to READING_RES cannot leave the stride behind."""
    assert config.READING_SLOTS == 7 ** (config.READING_RES - config.READING_PARENT_RES)
    parent = h3.cell_to_parent(TOKYO, config.READING_PARENT_RES)
    assert len(h3.cell_to_children(parent, config.READING_RES)) == config.READING_SLOTS


# --- the refusal that has no safe fallback -----------------------------------
def test_an_index_with_no_base_grid_is_refused():
    """There is no safe fallback to `idx.cells`.

    The digits this format reads are the same for a res-7 cell and its res-6
    parent, so seven split siblings would land in one slot, six values would
    be lost, and the file would still be exactly the right length -- the
    failure mode this format has instead of a crash. `cli.py` DOES fall back
    to `idx.cells` for the render grid, which is why the refusal has to be
    explicit here rather than left to the caller's habits.

    Mutation performed and reverted: replace the raise with
    `base = base or idx.cells` -> red.
    """

    class NoBase:
        cells: ClassVar[list[str]] = [SEOUL]
        base_cells: ClassVar[list[str]] = []

    with pytest.raises(ValueError, match="base_cells"):
        hover.reading_layout(NoBase())
    with pytest.raises(ValueError, match="base_cells"):
        hover.reading_parents(NoBase())


def test_a_base_grid_at_the_wrong_resolution_is_refused():
    """A res-7 cell's slot digits are its res-6 parent's, so a grid one level
    too fine collides seven-to-one and passes every length check."""
    finer = h3.cell_to_children(SEOUL, config.READING_RES + 1)

    class Finer:
        cells: ClassVar[list[str]] = list(finer)
        base_cells: ClassVar[list[str]] = list(finer)

    with pytest.raises(ValueError, match=f"resolution {config.READING_RES}"):
        hover.reading_layout(Finer())


def test_the_refusal_would_have_caught_the_collision_it_exists_for():
    """Shows the harm concretely: seven res-7 siblings share one slot.

    Not a test of the code -- a test of the PREMISE, so the refusal above
    cannot later be relaxed on the belief that the fallback was harmless.
    """
    kids = h3.cell_to_children(SEOUL, config.READING_RES + 1)
    assert len(kids) == 7
    assert len({hover.reading_slot(k) for k in kids}) == 1
    assert hover.reading_slot(kids[0]) == hover.reading_slot(SEOUL)


def test_nothing_the_site_ships_claims_the_reading_averages_its_sub_cells():
    """`reading_layout` takes the CENTRE child, and three documents said average.

    `emit/hover.py` resolves a split base cell to
    `h3.cell_to_center_child(...)` -- one value, not a mean of seven. The page,
    `llms.txt` and `config.py` all described it as an average, which is a
    different number and a different claim: an average over a 2.4 km cell that
    straddles a motorway and a hillside is a figure the map paints nowhere.

    The expectation comes from the SOURCE OF THE VALUE, not from the prose:
    whichever h3 call `reading_layout` uses decides what the documents may say.

    Mutation performed and reverted: restore "the reading averages over them" to
    `web/llms.txt` -> red, naming the file and the line.
    """
    layout_src = inspect.getsource(hover.reading_layout)
    assert "cell_to_center_child" in layout_src, (
        "reading_layout no longer resolves a split cell to its centre child; "
        "re-read this guard before changing the documents back")
    assert "mean(" not in layout_src and "average" not in layout_src.lower(), (
        "reading_layout now averages; the documents below may say so again")

    shipped = {
        "web/index.html": None, "web/llms.txt": None,
        "src/transport_maps/config.py": None,
    }
    bad = []
    for rel in shipped:
        text = (config.ROOT / rel).read_text(encoding="utf-8")
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if "averag" not in low:
                continue
            # "not an average", "rather than an average" are the corrections.
            if re.search(r"(not|rather than|never)\s+an?\s+averag", low):
                continue
            if "h3 v4 averages" in low:          # cell-size figures, not readings
                continue
            if "reading" in low or "sub-cell" in low or "children" in low:
                bad.append(f"{rel}:{n}: {line.strip()}")
    assert not bad, (
        "the reading is the centre child's value, and these lines say it is an "
        "average over the seven:\n  " + "\n  ".join(bad))
