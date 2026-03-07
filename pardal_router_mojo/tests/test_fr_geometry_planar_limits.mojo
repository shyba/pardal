from testing.suite import TestSuite
from testing import assert_equal, assert_true

from pardal_router_mojo.fr.geometry.planar.limits import crit_int, crit_double, sqrt2

def test_limits_constants():
    assert_equal(crit_int(), 33554432)
    assert_equal(crit_double(), 9007199254740992.0)
    assert_true(sqrt2() > 1.414)
    assert_true(sqrt2() < 1.415)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

