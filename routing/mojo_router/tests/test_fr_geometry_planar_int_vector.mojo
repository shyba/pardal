from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.geometry.planar.int_vector import IntVector

def test_int_vector_basics():
    v = IntVector(3, 4)
    assert_true(not v.is_zero())
    assert_true(v.is_orthogonal() == False)
    assert_true(v.is_diagonal() == False)
    assert_equal(v.negate().x, -3)
    assert_equal(v.negate().y, -4)
    assert_equal(v.determinant(IntVector(5, 6)), Int64(3) * Int64(6) - Int64(4) * Int64(5))

def test_int_vector_turns_and_mirror():
    v = IntVector(2, 1)
    v0 = v.turn_90_degree(0)
    assert_equal(v0.x, 2)
    assert_equal(v0.y, 1)
    v1 = v.turn_90_degree(1)
    assert_equal(v1.x, -1)
    assert_equal(v1.y, 2)
    v2 = v.turn_90_degree(2)
    assert_equal(v2.x, -2)
    assert_equal(v2.y, -1)
    v3 = v.turn_90_degree(3)
    assert_equal(v3.x, 1)
    assert_equal(v3.y, -2)
    my = v.mirror_at_y_axis()
    assert_equal(my.x, -2)
    assert_equal(my.y, 1)
    mx = v.mirror_at_x_axis()
    assert_equal(mx.x, 2)
    assert_equal(mx.y, -1)

def test_int_vector_normalized_direction():
    v = IntVector(6, 9)
    vd = v.to_normalized_direction()
    assert_equal(vd.x, 2)
    assert_equal(vd.y, 3)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
