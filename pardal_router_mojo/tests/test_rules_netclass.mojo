from collections import List

from testing import assert_equal
from testing.suite import TestSuite

from pardal_router_mojo.rules import BoardRules, ClearanceMatrix, NetClassRules


def test_board_rules_netclass_lookup():
    var names = List[String]()
    names.append(String("default"))
    var cm = ClearanceMatrix(1, names, 100)
    var rules = BoardRules(cm)

    var a = NetClassRules(String("A"))
    a.track_width = 200
    var b = NetClassRules(String("B"))
    b.track_width = 300

    _ = rules.add_netclass(a)
    _ = rules.add_netclass(b)

    assert_equal(rules.netclass_index(String("A")), 0)
    assert_equal(rules.netclass_index(String("B")), 1)
    assert_equal(rules.netclass_index(String("C")), -1)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()

