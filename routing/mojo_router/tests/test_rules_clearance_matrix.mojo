from collections import List

from testing import assert_equal
from testing.suite import TestSuite

from pardal_router_mojo.rules import ClearanceMatrix


def test_clearance_matrix_symmetry_and_layers():
    var names = List[String]()
    names.append(String("default"))
    names.append(String("smd"))
    names.append(String("via"))
    var m = ClearanceMatrix(2, names, 100)

    assert_equal(m.class_count(), 3)
    # Default fill.
    assert_equal(m.get(0, 1, 0), 100)
    assert_equal(m.get(1, 0, 0), 100)
    assert_equal(m.get(0, 1, 1), 100)

    # Set is symmetric and layer-scoped.
    m.set(0, 1, 0, 250)
    assert_equal(m.get(0, 1, 0), 250)
    assert_equal(m.get(1, 0, 0), 250)
    assert_equal(m.get(0, 1, 1), 100)

    m.set(2, 2, 1, 333)
    assert_equal(m.get(2, 2, 1), 333)
    assert_equal(m.get(2, 2, 0), 100)


def test_clearance_matrix_class_index():
    var names = List[String]()
    names.append(String("a"))
    names.append(String("b"))
    var m = ClearanceMatrix(1, names, 1)
    assert_equal(m.class_index(String("a")), 0)
    assert_equal(m.class_index(String("b")), 1)
    assert_equal(m.class_index(String("c")), -1)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

