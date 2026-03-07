from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.datastructures.big_int_aux import binary_gcd

def test_binary_gcd_basic():
    assert_equal(binary_gcd(0, 10), 10)
    assert_equal(binary_gcd(10, 0), 10)
    assert_equal(binary_gcd(12, 18), 6)
    assert_equal(binary_gcd(7, 13), 1)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

