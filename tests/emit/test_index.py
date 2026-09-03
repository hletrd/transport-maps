import numpy as np

from transport_maps.emit import index


class FakeIndex:
    cells = ["8530e08ffffffff", "8530e087fffffff", "85754e63fffffff"]
    n_cells = 3


def test_hover_cell_ids_are_sorted_ascending(tmp_path):
    out = tmp_path / "hover_cells.bin"
    index.write_hover_cells(FakeIndex(), out)
    ids = np.frombuffer(out.read_bytes(), dtype="<u8")
    assert len(ids) > 0
    assert (np.diff(ids.astype(object)) > 0).all()
