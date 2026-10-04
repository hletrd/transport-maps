"""`/api/map`'s array is `{slug}.bin`'s, cell for cell.

The service restates `emit/hover.py`'s representative rule rather than import
it (the seam test in test_wire.py bans `transport_maps.emit` from the
package). A restatement can drift, so it is held here to the original: the
SAME fixture goes through `emit.hover.write_hover` -- the function that writes
every charted city's `.bin` -- and through `service.hovermap`, and the bytes
must be equal. The test may import emit; the service may not.

The fixture is built to reach every branch of the rule, on real h3 cells:
parents whose res-6 centre is land, whose centre is missing (water), whose
centre was split so it speaks at res 7, whose split centre's own centre is
missing too, whose surviving children tie, and whose children are all
unreachable with no centre (a tie at infinity) -- in a shuffled node order, because a bundle's cells are not
sorted and "the lowest position" is a statement about node order.

The real-bundle check this cannot replace was run once by hand on
2026-10-04: maps from Seoul and from Suva on the shipped `52660de5` bundle
differ from `dist/origins/seoul.bin` and `suva.bin` at 0 of 90,740 cells, and
`build_index` reproduced `dist/hover_cells.bin` exactly (1.7 s).
"""

from __future__ import annotations

from types import SimpleNamespace

import h3
import numpy as np
import pytest

from transport_maps import config
from transport_maps.emit import hover, index
from transport_maps.service import bundle, hovermap

SEOUL = (37.5665, 126.9780)


def _ids(cells) -> np.ndarray:
    return np.array([h3.str_to_int(c) for c in cells], dtype=np.uint64)


def _world(seed: int = 7):
    """Seven res-4 parents around Seoul and their solver cells, shuffled.

    Returns (idx, cases): `idx` has the `.cells` list emit reads, and `cases`
    names the parent each branch of the rule is exercised on.
    """
    rng = np.random.default_rng(seed)
    parents = sorted(h3.grid_disk(h3.latlng_to_cell(*SEOUL, config.HOVER_RES), 1))
    cases = dict(zip(("water_centre", "split_centre", "split_centre_water", "tied",
                      "unreachable", "plain", "split_edge"), parents, strict=True))
    cells: list[str] = []
    for name, p in cases.items():
        kids = sorted(h3.cell_to_children(p, config.SOLVE_RES))
        centre = h3.cell_to_center_child(p, config.SOLVE_RES)
        if name in ("water_centre", "unreachable"):
            # An unreachable parent with no centre is the group whose
            # minimum is inf: every child ties, at infinity.
            kids.remove(centre)
        elif name in ("split_centre", "split_centre_water"):
            kids.remove(centre)
            fine = sorted(h3.cell_to_children(centre, config.FINE_RES))
            if name == "split_centre_water":
                fine.remove(h3.cell_to_center_child(p, config.FINE_RES))
            kids += fine
        elif name == "tied":
            kids = [k for k in kids if k != centre][:5]
        elif name == "split_edge":
            edge = kids[-1]
            kids = kids[:-1] + sorted(h3.cell_to_children(edge, config.FINE_RES))
        cells += kids
    cells = [cells[i] for i in rng.permutation(len(cells))]
    return SimpleNamespace(cells=cells), cases


def _minutes(idx, cases, seed: int = 11) -> np.ndarray:
    """Fractional minutes (the encode truncates, and that is tested), with a
    tie, a run of unreachable cells and a few past the 45-day ceiling."""
    rng = np.random.default_rng(seed)
    m = rng.uniform(0, 3000, len(idx.cells))
    pos = {c: i for i, c in enumerate(idx.cells)}
    for c in idx.cells:
        p = h3.cell_to_parent(c, config.HOVER_RES)
        if p == cases["tied"]:
            m[pos[c]] = 123.75                       # every child ties
        elif p == cases["unreachable"]:
            m[pos[c]] = np.inf
    m[rng.choice(len(m), 6, replace=False)] = 70000.0
    return m


def _index_of(idx) -> hovermap.HoverIndex:
    ids = _ids(idx.cells)
    order = np.argsort(ids, kind="stable")
    return hovermap.build_index(ids, ids[order], order.astype(np.int32))


def _emit_bytes(idx, minutes, tmp_path) -> bytes:
    out = tmp_path / "emit.bin"
    hover.write_hover(idx, minutes, out)
    return out.read_bytes()


# ---- the bit helpers ------------------------------------------------------

def test_the_bit_helpers_are_h3s_own_answers():
    """`to_res` and `centre_child` are h3's cell_to_parent and
    cell_to_center_child, over hexagons and every res-4 pentagon.

    Mutations performed and reverted, each RED: start the digit loop of
    `to_res` at `res` instead of `res + 1`; clear digits from `parent_res`
    instead of `parent_res + 1` in `centre_child`.
    """
    cells = list(h3.grid_disk(h3.latlng_to_cell(*SEOUL, 7), 3)) \
        + [h3.cell_to_center_child(p, 7) for p in h3.get_pentagons(4)]
    got = hovermap.to_res(_ids(cells), 4)
    assert [h3.int_to_str(int(v)) for v in got] == [h3.cell_to_parent(c, 4) for c in cells]
    parents = sorted({h3.cell_to_parent(c, 4) for c in cells}) + list(h3.get_pentagons(4))
    for res in (5, 6, 7):
        got = hovermap.centre_child(_ids(parents), 4, res)
        assert [h3.int_to_str(int(v)) for v in got] == \
            [h3.cell_to_center_child(p, res) for p in parents]


# ---- the representative rule ------------------------------------------------

def test_the_map_is_byte_for_byte_what_emit_writes_for_a_charted_city(tmp_path):
    """The whole rule at once: same cells, same order, same child, same
    truncation, same sentinel, compared as the bytes `{slug}.bin` holds.

    Mutations performed and reverted, each RED: drop the FINE_RES centre
    altogether; round instead of truncating in `encode`. (Preferring the
    FINE_RES centre to the SOLVE_RES one stays green, correctly: a split base
    cell is not a node, so the two are never both present.)
    """
    idx, cases = _world()
    minutes = _minutes(idx, cases)
    got = hovermap.encode(hovermap.map_minutes(_index_of(idx), minutes)).tobytes()
    assert got == _emit_bytes(idx, minutes, tmp_path)


@pytest.mark.parametrize("seed", [7, 1, 2])
def test_the_same_child_speaks_for_every_cell(seed):
    """Not only the same minutes: the same CHILD, which the bytes above cannot
    see when children tie. emit reads its arrival-airport, mode and rail
    arrays through the representative, so a rule that broke ties another way
    would agree on every time and disagree on the itinerary.

    Mutations performed and reverted, each RED: take the LAST minimum of a
    group; order each fallback group by descending node position.
    """
    idx, cases = _world(seed)
    minutes = _minutes(idx, cases, seed)
    parents = hover.hover_cells(idx)
    want = hover.representative_array(hover.hover_groups(idx, parents), minutes)
    got = hovermap.representatives(_index_of(idx), minutes)
    assert got.tolist() == want.tolist()


def test_every_branch_of_the_rule_is_in_the_fixture():
    """The positive control for the test above: a fixture that never reached
    a branch would let that branch drift. Each case must pick the child the
    rule says it picks, read from emit's own representative."""
    idx, cases = _world()
    minutes = _minutes(idx, cases)
    parents = hover.hover_cells(idx)
    rep = hover.representative_array(hover.hover_groups(idx, parents), minutes)
    at = {p: idx.cells[int(rep[parents.index(p)])] for p in parents}
    assert at[cases["plain"]] == h3.cell_to_center_child(cases["plain"], 6)
    assert h3.get_resolution(at[cases["split_centre"]]) == config.FINE_RES
    assert at[cases["split_centre"]] == h3.cell_to_center_child(cases["split_centre"], 7)
    for fallback in ("water_centre", "split_centre_water", "tied", "unreachable"):
        p = cases[fallback]
        kids = [i for i, c in enumerate(idx.cells) if h3.cell_to_parent(c, 4) == p]
        best = min(kids, key=lambda i: (minutes[i], i))
        assert at[p] == idx.cells[best], fallback
    # The tie really is a tie, and among several children.
    tied = [i for i, c in enumerate(idx.cells) if h3.cell_to_parent(c, 4) == cases["tied"]]
    assert len(tied) > 1 and len({minutes[i] for i in tied}) == 1
    # Past the 45-day ceiling, every one: inf, or one of the 70,000s.
    assert (minutes[[i for i, c in enumerate(idx.cells)
                     if h3.cell_to_parent(c, 4) == cases["unreachable"]]] >= hovermap.MAX_MINUTES).all()


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_other_orders_and_values_agree_too(tmp_path, seed):
    """The same comparison over four more shuffles and value draws, so a tie
    rule that happens to agree on one permutation does not pass."""
    idx, cases = _world(seed)
    minutes = _minutes(idx, cases, seed)
    got = hovermap.encode(hovermap.map_minutes(_index_of(idx), minutes)).tobytes()
    assert got == _emit_bytes(idx, minutes, tmp_path)


def test_a_fraction_of_a_minute_is_truncated_as_the_build_truncates():
    """emit/hover._encode casts float minutes to uint16, which truncates.
    A rounding copy would be a minute off a charted city's array in half its
    cells -- and the page compares a point's map with a city's.

    Mutation performed and reverted: `np.round(minutes)` before the cast ->
    RED.
    """
    got = hovermap.encode(np.array([0.0, 10.9, 65533.99, 65534.0, np.inf]))
    assert got.tolist() == [0, 10, 65533, config.UNREACHABLE, config.UNREACHABLE]
    assert got.dtype == np.dtype("<u2")


# ---- the order --------------------------------------------------------------

def test_the_parents_are_hover_cells_bin_in_its_own_order(tmp_path):
    """The index's parents ARE the page's hover_cells.bin, written by the
    build's own writer, and `check_order` accepts that file.

    Mutation performed and reverted: build `parents` with np.unique on the
    UNcoarsened ids -> RED.
    """
    idx, _cases = _world()
    out = tmp_path / "hover_cells.bin"
    index.write_hover_cells(idx, out)
    hm = _index_of(idx)
    assert np.array_equal(hm.parents, np.fromfile(out, dtype="<u8"))
    hovermap.check_order(hm, out)


@pytest.mark.parametrize("damage", ["reversed", "one short", "one swapped"])
def test_a_hover_cells_bin_in_another_order_is_refused(tmp_path, damage):
    """Mutation performed and reverted: compare only the lengths in
    `check_order` -> RED on "reversed" and "one swapped"."""
    idx, _cases = _world()
    hm = _index_of(idx)
    ids = hm.parents.copy()
    if damage == "reversed":
        ids = ids[::-1]
    elif damage == "one short":
        ids = ids[:-1]
    else:
        ids[[0, 1]] = ids[[1, 0]]
    out = tmp_path / "hover_cells.bin"
    ids.astype("<u8").tofile(out)
    with pytest.raises(ValueError):
        hovermap.check_order(hm, out)


def _bundle_of(idx, tmp_path):
    """A bundle whose cells are the fixture's, with a graph that reaches
    each cell from cell 0 in its own position's minutes."""
    import scipy.sparse as sp

    n = len(idx.cells)
    rows = np.zeros(n - 1, dtype=np.int64)
    cols = np.arange(1, n)
    csr = sp.csr_matrix((np.arange(1, n, dtype=float) + 0.5, (rows, cols)), shape=(n, n))
    split = {h3.cell_to_parent(c, config.SOLVE_RES) for c in idx.cells
             if h3.get_resolution(c) == config.FINE_RES}
    return bundle.write_bundle(tmp_path / "solver", idx.cells, split, n, csr, {"buildId": "t"},
                               n_airports=0, n_stations=0)


def test_the_service_refuses_to_start_beside_another_order(tmp_path):
    """A hover_cells.bin beside the bundle is checked when the solver is
    built, which is before the server opens its socket (server.main). In
    another order, nothing is served.

    Mutations performed and reverted, each RED: drop the `check_order` call
    from GraphSolver.__init__; look for the file only when it is named.
    """
    idx, _cases = _world()
    out = _bundle_of(idx, tmp_path)
    index.write_hover_cells(idx, out / "hover_cells.bin")
    bundle.GraphSolver(bundle.load_bundle(out))          # the right order starts
    np.fromfile(out / "hover_cells.bin", dtype="<u8")[::-1].tofile(out / "hover_cells.bin")
    with pytest.raises(ValueError):
        bundle.GraphSolver(bundle.load_bundle(out))
    # ...and a file named on the command line is held to the same.
    good = tmp_path / "good.bin"
    index.write_hover_cells(idx, good)
    (out / "hover_cells.bin").unlink()
    bundle.GraphSolver(bundle.load_bundle(out), hover_cells=good)
    with pytest.raises(FileNotFoundError):
        bundle.GraphSolver(bundle.load_bundle(out), hover_cells=tmp_path / "missing.bin")


def test_a_served_map_is_emits_array_for_the_same_solve(tmp_path):
    """End to end through GraphSolver.map: the bundle's own dijkstra, the
    snap, base64, and the bytes emit would write for that departure.

    Mutation performed and reverted: hand `map_minutes` the whole `dist`
    with the cell slice dropped AND the centre gather offset by one -> RED.
    """
    import base64

    from scipy.sparse.csgraph import dijkstra

    from transport_maps.service import wire

    idx, _cases = _world()
    out = _bundle_of(idx, tmp_path)
    b = bundle.load_bundle(out)
    start = 0
    body = bundle.GraphSolver(b).map(wire.MapRequest(*h3.cell_to_latlng(idx.cells[start])))
    want = _emit_bytes(idx, dijkstra(b.csr, directed=True, indices=start), tmp_path)
    assert base64.b64decode(body["times"]) == want
    assert body["count"] == len(hover.hover_cells(idx)) and body["buildId"] == "t"
