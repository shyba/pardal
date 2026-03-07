from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.geometry.planar.int_direction import IntDirection

def test_int_direction_turns():
    d = IntDirection(1, 0)  # RIGHT
    d90 = d.turn_45_degree(2)
    assert_equal(d90.x, 0)
    assert_equal(d90.y, 1)  # UP
    d180 = d.turn_45_degree(4)
    assert_equal(d180.x, -1)
    assert_equal(d180.y, 0)  # LEFT

def test_int_direction_compare_basic():
    # Basic antisymmetry smoke: compare_to flips sign.
    a = IntDirection(1, 0)
    b = IntDirection(0, 1)
    ab = a.compare_to_int_direction(b)
    ba = b.compare_to_int_direction(a)
    assert_equal(ab, -ba)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

