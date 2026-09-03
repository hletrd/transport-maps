import numpy as np

from transport_maps import config
from transport_maps.emit import hover


class FakeIndex:
    # Two res-5 cells that share a res-4 parent, plus one that does not.
    cells = ["8530e08ffffffff", "8530e087fffffff", "85754e63fffffff"]
    n_cells = 3


def test_writes_uint16_little_endian(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([10.0, 20.0, 5000.0]), out)
    raw = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert raw.dtype.itemsize == 2
    assert len(raw) == len(hover.hover_cells(FakeIndex()))


def test_parent_cell_takes_the_minimum_of_its_children(tmp_path):
    out = tmp_path / "h.bin"
    hover.write_hover(FakeIndex(), np.array([10.0, 20.0, 5000.0]), out)
    values = np.frombuffer(out.read_bytes(), dtype="<u2")
    assert 10 in values  # the faster of the two siblings wins


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
