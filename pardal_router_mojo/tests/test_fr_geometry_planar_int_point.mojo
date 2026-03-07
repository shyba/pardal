from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint


def test_int_point_equals():
    assert_true(IntPoint(1, 2).equals(IntPoint(1, 2)))
    assert_true(not IntPoint(1, 2).equals(IntPoint(2, 1)))


def test_int_point_determinant():
    var a = IntPoint(2, 3)
    var b = IntPoint(7, 11)
    assert_equal(a.determinant(b), Int64(2 * 11 - 3 * 7))


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

