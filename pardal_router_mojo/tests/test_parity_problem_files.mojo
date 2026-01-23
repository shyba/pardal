from python import Python, PythonObject
from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo import route_problem

comptime py = Python


def _run(problem_rel: String, expected_failed: Int):
    var tempfile = py.import_module("tempfile")
    var pathlib = py.import_module("pathlib")
    var json = py.import_module("json")

    var root = pathlib.Path(tempfile.mkdtemp())
    var routes = root / PythonObject(String("out.routes.json"))
    var cfg = root / PythonObject(String("cfg.json"))

    var cfg_payload = py.dict()
    cfg_payload[PythonObject(String("commit_routes"))] = PythonObject(True)
    cfg_payload[PythonObject(String("attempts"))] = PythonObject(Int(1))
    cfg_payload[PythonObject(String("margin_init"))] = PythonObject(Int(256))
    cfg_payload[PythonObject(String("via_penalty"))] = PythonObject(Int(40))
    cfg_payload[PythonObject(String("diagonal"))] = PythonObject(True)
    cfg_payload[PythonObject(String("heuristic_weight_pct"))] = PythonObject(Int(100))
    cfg.write_text(json.dumps(cfg_payload, indent=PythonObject(Int(2))))

    route_problem(problem_rel, String(py=routes), String(py=cfg))

    var out = json.loads(routes.read_text())
    var failed = out[PythonObject(String("failed_nets"))].__len__()
    assert_equal(Int(py=failed), expected_failed)

def _run_smoke(problem_rel: String):
    var tempfile = py.import_module("tempfile")
    var pathlib = py.import_module("pathlib")
    var json = py.import_module("json")

    var root = pathlib.Path(tempfile.mkdtemp())
    var routes = root / PythonObject(String("out.routes.json"))
    var cfg = root / PythonObject(String("cfg.json"))

    var cfg_payload = py.dict()
    cfg_payload[PythonObject(String("commit_routes"))] = PythonObject(True)
    cfg_payload[PythonObject(String("attempts"))] = PythonObject(Int(1))
    cfg_payload[PythonObject(String("margin_init"))] = PythonObject(Int(256))
    cfg_payload[PythonObject(String("via_penalty"))] = PythonObject(Int(40))
    cfg_payload[PythonObject(String("diagonal"))] = PythonObject(True)
    cfg_payload[PythonObject(String("heuristic_weight_pct"))] = PythonObject(Int(100))
    cfg.write_text(json.dumps(cfg_payload, indent=PythonObject(Int(2))))

    route_problem(problem_rel, String(py=routes), String(py=cfg))

    var out = json.loads(routes.read_text())
    var failed = out[PythonObject(String("failed_nets"))].__len__()
    assert_true(Int(py=failed) >= 0)

def test_fpga_large_smoke_runs():
    _run_smoke(String("../fpga_large/fpga_large_csg324_breakout_mojo.problem.json"))


def test_small_fpga_routes_all_nets():
    _run(String("../fpga/fpga_unrouted_mojo_drc23.problem.json"), 0)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
