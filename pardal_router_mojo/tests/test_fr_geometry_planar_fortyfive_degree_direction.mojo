from testing.suite import TestSuite
from testing import assert_equal

from pardal_router_mojo.fr.geometry.planar.fortyfive_degree_direction import FortyfiveDegreeDirection
from pardal_router_mojo.fr.geometry.planar.direction import to_string

def test_fortyfive_degree_direction_get_direction():
    assert_equal(to_string(FortyfiveDegreeDirection.RIGHT().get_direction()), "RIGHT")
    assert_equal(to_string(FortyfiveDegreeDirection.UP().get_direction()), "UP")
    assert_equal(to_string(FortyfiveDegreeDirection.LEFT().get_direction()), "LEFT")
    assert_equal(to_string(FortyfiveDegreeDirection.DOWN().get_direction()), "DOWN")
    assert_equal(to_string(FortyfiveDegreeDirection.RIGHT45().get_direction()), "UP-RIGHT")

def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

