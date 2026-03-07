from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.datastructures.signum import Signum

def test_signum_of_and_negate():
    assert_equal(Signum.of(1.0).to_string(), "positive")
    assert_equal(Signum.of(-1.0).to_string(), "negative")
    assert_equal(Signum.of(0.0).to_string(), "zero")
    assert_equal(Signum.of(2.0).negate().to_string(), "negative")
    assert_equal(Signum.of(-2.0).negate().to_string(), "positive")
    assert_equal(Signum.of(0.0).negate().to_string(), "zero")

def test_signum_as_int():
    assert_equal(Signum.as_int(1.0), 1)
    assert_equal(Signum.as_int(-1.0), -1)
    assert_equal(Signum.as_int(0.0), 0)

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

