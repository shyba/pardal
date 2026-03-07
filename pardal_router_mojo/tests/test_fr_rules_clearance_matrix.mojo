from collections import List
from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.board.layer import Layer
from pardal_router_mojo.fr.board.layer_structure import LayerStructure
from pardal_router_mojo.fr.rules.clearance_matrix import ClearanceMatrix

def test_clearance_matrix_set_value_rounding_and_max():
    layers: List[Layer] = [Layer("Top", True), Layer("Bottom", True)]
    ls = LayerStructure(layers^)
    names: List[String] = ["default"]
    m = ClearanceMatrix(1, ls, names)

    # odd becomes even
    m.set_value(0, 0, 0, 5)
    assert_equal(m.get_value(0, 0, 0, False), 6)
    assert_equal(m.max_value_for_class(0, 0), 6)
    assert_equal(m.max_value_for_layer(0), 6)

    # negative becomes 0; max remains 6
    m.set_value(0, 0, 0, -10)
    assert_equal(m.get_value(0, 0, 0, False), 0)
    assert_equal(m.max_value_for_class(0, 0), 6)
    assert_equal(m.max_value_for_layer(0), 6)

    # MAX_VALUE becomes MAX_VALUE-1 (even)
    m.set_value(0, 0, 0, 2147483647)
    assert_equal(m.get_value(0, 0, 0, False), 2147483646)
    assert_equal(m.max_value_for_class(0, 0), 2147483646)
    assert_equal(m.max_value_for_layer(0), 2147483646)

def test_clearance_matrix_clearance_compensation_value():
    layers: List[Layer] = [Layer("Top", True)]
    ls = LayerStructure(layers^)
    names: List[String] = ["a", "b"]
    m = ClearanceMatrix(2, ls, names)
    m.set_value(1, 1, 0, 5)
    assert_equal(m.clearance_compensation_value(1, 0), 3)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
