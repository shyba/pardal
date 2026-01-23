from python import Python, PythonObject
from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo.sexpr import parse_sexpr, scan_first_quoted_string

comptime py = Python


fn _read_text(rel: String) raises -> String:
    var pathlib = py.import_module("pathlib")
    var p = pathlib.Path(PythonObject(rel))
    var s = p.read_text(encoding=PythonObject(String("utf-8")), errors=PythonObject(String("replace")))
    return String(py=s)

fn _string_contains(hay: String, needle: String) raises -> Bool:
    return Bool(PythonObject(hay).__contains__(PythonObject(needle)))


fn _is_list(o: PythonObject) raises -> Bool:
    var builtins = py.import_module("builtins")
    return Bool(py=builtins.isinstance(o, builtins.list))


fn _py_len(o: PythonObject) raises -> Int:
    var builtins = py.import_module("builtins")
    return Int(py=builtins.len(o))


fn _head_symbol(x: PythonObject) raises -> String:
    if not _is_list(x):
        return String(py=x)
    if _py_len(x) == 0:
        return String("")
    var h = x[PythonObject(Int(0))]
    if _is_list(h):
        return String("")
    return String(py=h)


fn _contains_atom(root: PythonObject, needle: String) raises -> Bool:
    var stack = List[PythonObject]()
    stack.append(root)
    while len(stack) > 0:
        var n = stack.pop()
        if not _is_list(n):
            if String(py=n) == needle:
                return True
            continue
        for child in n:
            stack.append(child)
    return False


def test_parse_empty_board_dsn():
    var src = _read_text(String("../../freerouting/tests/empty_board.dsn"))
    var xs = parse_sexpr(src)
    assert_equal(_py_len(xs), 1)
    var top = xs[PythonObject(Int(0))]
    assert_equal(_head_symbol(top), String("pcb"))
    assert_true(_contains_atom(top, String("structure")))
    assert_true(_contains_atom(top, String("boundary")))


def test_parse_min_fr_test_dsn():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var xs = parse_sexpr(src)
    assert_equal(_py_len(xs), 1)
    var top = xs[PythonObject(Int(0))]
    assert_equal(_head_symbol(top), String("pcb"))
    assert_true(_contains_atom(top, String("layer")))
    assert_true(_contains_atom(top, String("plane")))
    assert_true(_contains_atom(top, String("boundary")))


def test_parse_min_fr_test_no_quotes_dsn():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test_no_quotes.dsn"))
    var xs = parse_sexpr(src)
    assert_equal(_py_len(xs), 1)
    var top = xs[PythonObject(Int(0))]
    assert_equal(_head_symbol(top), String("pcb"))
    assert_true(_contains_atom(top, String("parser")))
    assert_true(_contains_atom(top, String("space_in_quoted_tokens")))
    # Regression: unquoted atoms may include brackets/colons.
    assert_true(_contains_atom(top, String("Via[0-3]_600:300_um")))


def test_parse_issue035_semicolon_atom_not_comment():
    var src = _read_text(String("../../freerouting/tests/Issue035-ReadPlaceScope.dsn"))
    var xs = parse_sexpr(src)
    assert_equal(_py_len(xs), 1)
    var top = xs[PythonObject(Int(0))]
    assert_equal(_head_symbol(top), String("pcb"))
    # Fixture contains (PN ;) which must not be treated as a comment.
    assert_true(_contains_atom(top, String(";")))


def test_parse_hw48na_rules_and_string_tokens():
    var src = _read_text(String("../../freerouting/tests/Issue029-hw48na_valid.rules"))
    var xs = parse_sexpr(src)
    assert_equal(_py_len(xs), 1)
    var top = xs[PythonObject(Int(0))]
    assert_equal(_head_symbol(top), String("rules"))
    assert_true(_contains_atom(top, String("autoroute_settings")))
    # Regression: quoted strings with spaces must be a single token.
    assert_true(_contains_atom(top, String("1A EXTERNAL 1oz")))


def test_parse_issue229_keepouts_present():
    var src = _read_text(String("../../freerouting/tests/Issue229-display-8-digit-hc595.dsn"))
    var xs = parse_sexpr(src)
    assert_equal(_py_len(xs), 1)
    var top = xs[PythonObject(Int(0))]
    assert_equal(_head_symbol(top), String("pcb"))
    assert_true(_contains_atom(top, String("keepout")))
    # Fixture contains an explicit empty-string keepout name: (keepout "" ...)
    assert_true(_contains_atom(top, String("")))


def test_parse_issue270_uppercase_pcb_and_keepouts():
    var src = _read_text(String("../../freerouting/tests/Issue270-non-ansi_bracket.dsn"))
    var xs = parse_sexpr(src)
    assert_equal(_py_len(xs), 1)
    var top = xs[PythonObject(Int(0))]
    assert_equal(_head_symbol(top), String("PCB"))
    assert_true(_contains_atom(top, String("keepout")))
    assert_true(_contains_atom(top, String("~{WE}")))


def test_scan_windows_path_quoted_string():
    var src = _read_text(String("../../freerouting/tests/Issue555-CNH_Functional_Tester_1.dsn"))
    var first = scan_first_quoted_string(src)
    assert_equal(
        first,
        String("C:\\Work\\freerouting\\tests\\Issue555-CNH_Functional_Tester_1.dsn"),
    )

def test_scan_unicode_path_quoted_string():
    var src = _read_text(String("../../freerouting/tests/Issue110-Паяльная станция.dsn"))
    var first = scan_first_quoted_string(src)
    assert_true(_string_contains(first, String("Паяльная станция.dsn")))


def test_parse_test_ses_has_placement():
    var src = _read_text(
        String(
            "../../freerouting/tests/Issue269-NoViasOnPowerPlanes/Issue269-NoViasOnPowerPlanes.ses"
        )
    )
    var xs = parse_sexpr(src)
    assert_equal(_py_len(xs), 1)
    var top = xs[PythonObject(Int(0))]
    assert_equal(_head_symbol(top), String("session"))
    assert_true(_contains_atom(top, String("placement")))
    assert_true(_contains_atom(top, String("routes")))
    assert_true(_contains_atom(top, String("padstack")))


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
