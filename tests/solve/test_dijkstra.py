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
