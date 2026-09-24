"""The route behind the fine reading, wherever it differs from the coarse cell's."""

import numpy as np

from transport_maps.emit import itinerary, modes, override


class Idx:
    n_cells = 4
    airports = ("SPN", "TIQ")          # arrival nodes are 4 + 2 + (0, 1) = 6, 7


class Layout:
    # Four base cells, all in ONE hover parent (0), shown from nodes 0..3 at
    # reading slots 40, 10, 30, 20 -- deliberately out of order.
    source = np.array([0, 1, 2, 3])
    dest = np.array([40, 10, 30, 20])


def _case():
    # The representative (node 0, "Saipan") landed at SPN. Node 1 too; node 2
    # ("Tinian") at TIQ; node 3 flew nowhere.
    last = np.array([6, 6, 7, -1, -1, -1, -1, -1])
    acc = np.zeros((8, len(modes.CHANNELS)))
    acc[2] = [0, 2, 55, 17, 0, 0]
    acc[3] = [0, 0, 70000, 0, 0, 0]                 # beyond uint16: clipped
    rep = np.array([0])                              # hover parent 0 -> node 0
    base_hover = np.array([0, 0, 0, 0])
    return last, acc, rep, base_hover


def test_only_cells_whose_airport_differs_from_the_representatives_are_listed():
    slots, airport, minutes = override.override_entries(Idx(), *_case(), Layout())
    # node 1 matches the representative (SPN): not listed. Nodes 2 and 3 are,
    # sorted by SLOT (20 before 30) so the page can binary-search them.
    assert slots.tolist() == [20, 30]
    assert airport.tolist() == [itinerary.NO_AIRPORT, 1]    # node 3 none, node 2 TIQ
    assert minutes[1].tolist() == [0, 2, 55, 17, 0, 0]
    assert minutes[0][2] == modes.MAX_MINUTES


def test_the_file_is_three_arrays_of_the_stated_widths(tmp_path):
    out = tmp_path / "x.over.bin"
    n = override.write_override(Idx(), *_case(), Layout(), out)
    raw = out.read_bytes()
    assert n == 2 and len(raw) == n * override.ENTRY_BYTES
    slots = np.frombuffer(raw[: 4 * n], "<u4")
    airport = np.frombuffer(raw[4 * n: 6 * n], "<u2")
    mins = np.frombuffer(raw[6 * n:], "<u2").reshape(n, len(modes.CHANNELS))
    assert slots.tolist() == [20, 30] and airport.tolist() == [itinerary.NO_AIRPORT, 1]
    assert mins[1].tolist() == [0, 2, 55, 17, 0, 0]


def test_a_cell_the_reading_does_not_show_is_never_listed():
    last, acc, rep, base_hover = _case()

    class Gap(Layout):
        source = np.array([0, 1, -1, 3])             # slot 30 shows no node
    slots, _, _ = override.override_entries(Idx(), last, acc, rep, base_hover, Gap())
    assert slots.tolist() == [20]
