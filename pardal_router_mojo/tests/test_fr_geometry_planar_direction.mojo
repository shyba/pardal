from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.geometry.planar.direction import (
    right,
    up,
    left,
    down,
    right45,
    to_string,
    get_instance_from_vector,
    get_instance_approx,
    equals_dir,
)
from pardal_router_mojo.fr.geometry.planar.int_vector import IntVector

def test_direction_constants_to_string():
    assert_equal(to_string(right()), "RIGHT")
    assert_equal(to_string(up()), "UP")
    assert_equal(to_string(left()), "LEFT")
    assert_equal(to_string(down()), "DOWN")
    assert_equal(to_string(right45()), "UP-RIGHT")

def test_direction_get_instance_normalizes():
    d = get_instance_from_vector(IntVector(6, 9))
    assert_equal(d.x, 2)
    assert_equal(d.y, 3)

def test_direction_equals_semantics():
    assert_true(equals_dir(right(), right()))
    assert_true(not equals_dir(right(), left()))

def test_direction_instance_approx_smoke():
    d = get_instance_approx(0.0)
    assert_equal(to_string(d), "RIGHT")

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

