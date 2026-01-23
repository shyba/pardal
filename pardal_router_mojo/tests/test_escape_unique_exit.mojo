from collections import List

from python import Python, PythonObject
from testing import assert_equal
from testing.suite import TestSuite

from pardal_router_mojo.router import _pick_escape_exit

comptime py = Python
fn _py_set() raises -> PythonObject:
    var builtins = py.import_module("builtins")
    return builtins.set()


def test_pick_escape_exit_unique_skips_used():
    var candidates = List[Int]()
    candidates.append(10)
    candidates.append(11)
    candidates.append(12)

    var used = _py_set()
    used.add(PythonObject(Int(10)))
    assert_equal(_pick_escape_exit(candidates, 0, used, True), 11)


def test_pick_escape_exit_unique_respects_start_index():
    var candidates = List[Int]()
    candidates.append(10)
    candidates.append(11)
    candidates.append(12)

    var used = _py_set()
    used.add(PythonObject(Int(11)))
    assert_equal(_pick_escape_exit(candidates, 1, used, True), 12)


def test_pick_escape_exit_non_unique_returns_first_from_start():
    var candidates = List[Int]()
    candidates.append(10)
    candidates.append(11)
    candidates.append(12)

    var used = _py_set()
    used.add(PythonObject(Int(10)))
    assert_equal(_pick_escape_exit(candidates, 0, used, False), 10)
    assert_equal(_pick_escape_exit(candidates, 2, used, False), 12)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
