"""The hover array reports the CENTRE solver child of each hover cell."""

from typing import ClassVar

import h3
import numpy as np

from transport_maps import config
from transport_maps.emit import hover

# One hover cell over Seoul and some of its solver-resolution children: the
# centre child, a sibling that is not the centre, plus a cell under another
# hover parent. Built at config.SOLVE_RES on purpose -- the old res-5 fixture
# never matched the centre child, so the centre rule fell through to the
# fastest-child fallback and a plain minimum over children passed every test.
PARENT = h3.latlng_to_cell(37.5665, 126.9780, config.HOVER_RES)
CENTRE = h3.cell_to_center_child(PARENT, config.SOLVE_RES)
SIBLINGS = [c for c in h3.cell_to_children(PARENT, config.SOLVE_RES) if c != CENTRE]
ELSEWHERE = h3.latlng_to_cell(35.6762, 139.6503, config.SOLVE_RES)   # Tokyo


class FakeIndex:
    cells: ClassVar[list[str]] = [CENTRE, SIBLINGS[0], ELSEWHERE]
    n_cells = 3


def _values(idx, minutes, tmp_path) -> dict[str, int]:
    """Hover value per hover cell, as the page would read it."""
    out = tmp_path / "h.bin"
    hover.write_hover(idx, np.asarray(minutes, dtype=float), out)
    raw = np.frombuffer(out.read_bytes(), dtype="<u2")
    return dict(zip(hover.hover_cells(idx), raw.tolist()))


def test_fixture_reaches_the_centre_child_rule():
    """Guards the fixture itself: the centre child must sit in the index at
    the solver resolution, or the rule under test is never exercised."""
    assert h3.get_resolution(CENTRE) == config.SOLVE_RES
    assert h3.cell_to_parent(SIBLINGS[0], config.HOVER_RES) == PARENT
    assert h3.cell_to_parent(ELSEWHERE, config.HOVER_RES) != PARENT


def test_writes_uint16_little_endian(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([10.0, 20.0, 5000.0]), out)
    raw = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert raw.dtype.itemsize == 2
    assert len(raw) == len(hover.hover_cells(FakeIndex())) == 2


def test_parent_reports_its_centre_child_not_its_fastest(tmp_path):
    """The centre child is slower than its sibling; the readout must say so.

    Taking the minimum made the readout "the best time anywhere within ~22 km",
    which borrowed South Korean times ten kilometres inside North Korea and put
    Johor Bahru at 21 minutes from Singapore.
    """
    values = _values(FakeIndex(), [20.0, 10.0, 5000.0], tmp_path)
    assert values[PARENT] == 20


def test_a_parent_whose_centre_is_water_falls_back_to_its_fastest_child(tmp_path):
    class NoCentre:
        cells: ClassVar[list[str]] = [SIBLINGS[0], SIBLINGS[1], ELSEWHERE]
        n_cells = 3
    values = _values(NoCentre(), [30.0, 10.0, 5000.0], tmp_path)
    assert values[PARENT] == 10


def test_a_split_centre_reports_the_fine_centre_child(tmp_path):
    """Where the centre base cell was refined away, its own centre child at
    FINE_RES is what a pointer at that spot means -- not the fastest of them."""
    fine_centre = h3.cell_to_center_child(PARENT, config.FINE_RES)
    fine_other = next(c for c in h3.cell_to_children(CENTRE, config.FINE_RES) if c != fine_centre)
    assert h3.cell_to_parent(fine_centre, config.SOLVE_RES) == CENTRE

    class Split:
        cells: ClassVar[list[str]] = [fine_centre, fine_other, SIBLINGS[0], ELSEWHERE]
        n_cells = 4
    values = _values(Split(), [40.0, 10.0, 15.0, 5000.0], tmp_path)
    assert values[PARENT] == 40


def test_unreachable_becomes_the_sentinel(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([np.inf, np.inf, np.inf]), out)
    values = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert (values == config.UNREACHABLE).all()


def test_values_are_clamped_below_the_sentinel(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([99_999.0, 99_999.0, 99_999.0]), out)
    values = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert (values < config.UNREACHABLE).all()
