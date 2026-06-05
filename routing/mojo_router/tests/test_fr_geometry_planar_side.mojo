from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.geometry.planar.side import Side

def test_side_of_and_negate():
    assert_equal(Side.of(1.0).to_string(), "on_the_left")
    assert_equal(Side.of(-1.0).to_string(), "on_the_right")
    assert_equal(Side.of(0.0).to_string(), "collinear")
    assert_equal(Side.of(2.0).negate().to_string(), "on_the_right")
    assert_equal(Side.of(-2.0).negate().to_string(), "on_the_left")
    assert_equal(Side.of(0.0).negate().to_string(), "collinear")

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

