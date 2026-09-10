import numpy as np
import scipy.sparse as sp

from transport_maps.solve import dijkstra


def test_solves_a_tiny_hand_built_graph():
    #  0 --5--> 1 --2--> 2 ,  0 --20--> 2
    m = sp.csr_matrix(np.array([
        [0.0, 5.0, 20.0],
        [0.0, 0.0, 2.0],
        [0.0, 0.0, 0.0],
    ]))
    d = dijkstra.solve_from(m, 0)
    assert d[0] == 0.0
    assert d[1] == 5.0
    assert d[2] == 7.0  # via node 1, not the direct 20


def test_unreachable_nodes_are_infinite():
    m = sp.csr_matrix(np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]))
    d = dijkstra.solve_from(m, 0)
    assert np.isinf(d[2])


# ---- the two things the fixtures above cannot decide -------------------
#
# Both matrices are upper-triangular, so every edge already points "forwards"
# and `directed=False` gives byte-identical output on both -- the flag that
# decides whether a one-way ferry can be sailed backwards is undecidable by
# every test this module had. And `with_predecessors=True`, which cli.py is the
# only production caller of and always passes, was entered by nothing at all.

def _one_way():
    """0 -> 1 costs 1. There is no edge back, and 2 stands alone.

    Read undirected, node 0 becomes reachable FROM node 1, which is the
    property that matters: a one-way ferry crossing, a one-way road, and an
    airport departure edge are all directed, and treating them otherwise
    invents journeys that cannot be made.
    """
    return sp.csr_matrix(np.array([
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0],
        [0.0, 0.0, 0.0],
    ]))


def test_edges_are_one_way():
    """Mutation: `directed=True` -> `directed=False` in solve_from.

    Solving FROM node 1, the only edge in the graph points away from it, so
    node 0 must stay unreachable. Read undirected it becomes 1.0.
    """
    d = dijkstra.solve_from(_one_way(), 1)
    assert d[1] == 0.0
    assert np.isinf(d[0]), (
        "a one-way edge was traversed backwards: solve_from is not directed")
    assert np.isinf(d[2])


def test_predecessors_reconstruct_the_path_the_route_panel_walks():
    """cli.py is the only production caller and always passes
    with_predecessors=True, so this branch ran in no test.

    Mutations: drop the `if with_predecessors` branch, or pass
    return_predecessors=False inside it -- both make this raise or mismatch.
    """
    #  0 --5--> 1 --2--> 2 , and a direct 0 --20--> 2 that must NOT be chosen
    m = sp.csr_matrix(np.array([
        [0.0, 5.0, 20.0],
        [0.0, 0.0, 2.0],
        [0.0, 0.0, 0.0],
    ]))
    result = dijkstra.solve_from(m, 0, with_predecessors=True)
    assert isinstance(result, tuple) and len(result) == 2, (
        "with_predecessors must return (dist, pred); the route panel unpacks two")
    dist, pred = result
    assert dist[2] == 7.0
    # Walk it back the way the itinerary emitter does.
    hops, node = [], 2
    while node != 0:
        hops.append(node)
        node = int(pred[node])
        assert node >= 0, "the predecessor chain does not reach the source"
    hops.append(0)
    assert hops[::-1] == [0, 1, 2], (
        f"the cheap path is 0->1->2; predecessors say {hops[::-1]}")


def test_without_predecessors_only_distances_come_back():
    """The other half of the same branch: the default must NOT be a tuple, or
    every caller that indexes the result reads a row of the wrong array.
    """
    m = sp.csr_matrix(np.array([[0.0, 1.0], [0.0, 0.0]]))
    d = dijkstra.solve_from(m, 0)
    assert not isinstance(d, tuple)
    assert d.shape == (2,)
