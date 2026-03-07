from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.geometry.planar.int_box import IntBox
from pardal_router_mojo.fr.geometry.planar.int_point import IntPoint
from pardal_router_mojo.fr.geometry.planar.tile_shape import TileShapeBox


def test_tile_shape_box_intersection_and_contains():
    a = TileShapeBox(IntBox(IntPoint(0, 0), IntPoint(10, 10)))
    b = TileShapeBox(IntBox(IntPoint(5, 5), IntPoint(15, 15)))
    isect = a.intersection(b)
    assert_true(not isect.is_empty())
    assert_equal(isect.box.ll.x, 5)
    assert_equal(isect.box.ll.y, 5)
    assert_equal(isect.box.ur.x, 10)
    assert_equal(isect.box.ur.y, 10)
    assert_true(a.contains(isect))


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
