from python import Python, PythonObject
from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo import route_problem

comptime py = Python


def test_route_problem_emits_schema():
    var tempfile = py.import_module("tempfile")
    var pathlib = py.import_module("pathlib")
    var json = py.import_module("json")

    var root = pathlib.Path(tempfile.mkdtemp())
    var problem = root / PythonObject(String("p.problem.json"))
    var routes = root / PythonObject(String("p.routes.json"))

    var payload = py.dict()
    payload[PythonObject(String("resolution_mm"))] = PythonObject(Float64(0.1))
    payload[PythonObject(String("layers"))] = py.list(PythonObject(String("F.Cu")), PythonObject(String("B.Cu")))
    payload[PythonObject(String("width"))] = PythonObject(Int(20))
    payload[PythonObject(String("height"))] = PythonObject(Int(10))
    payload[PythonObject(String("circles"))] = py.list()

    var net = py.dict()
    net[PythonObject(String("net"))] = PythonObject(String("N1"))
    net[PythonObject(String("net_id"))] = PythonObject(Int(1))
    var start = py.dict()
    start[PythonObject(String("layer"))] = PythonObject(Int(0))
    start[PythonObject(String("x"))] = PythonObject(Int(1))
    start[PythonObject(String("y"))] = PythonObject(Int(1))
    net[PythonObject(String("start"))] = start

    var goal = py.dict()
    goal[PythonObject(String("layer"))] = PythonObject(Int(0))
    goal[PythonObject(String("x"))] = PythonObject(Int(15))
    goal[PythonObject(String("y"))] = PythonObject(Int(8))
    net[PythonObject(String("goal"))] = goal
    net[PythonObject(String("track_width_mm"))] = PythonObject(Float64(0.2))
    net[PythonObject(String("via_diameter_mm"))] = PythonObject(Float64(0.6))
    net[PythonObject(String("via_drill_mm"))] = PythonObject(Float64(0.3))
    net[PythonObject(String("uvia_diameter_mm"))] = PythonObject(Float64(0.4))
    net[PythonObject(String("uvia_drill_mm"))] = PythonObject(Float64(0.2))
    payload[PythonObject(String("nets"))] = py.list(net)

    problem.write_text(json.dumps(payload, indent=PythonObject(Int(2))))

    try:
        route_problem(String(py=problem), String(py=routes), "")
    except e:
        assert_true(False)

    var out = json.loads(routes.read_text())
    assert_equal(String(py=out[PythonObject(String("backend"))]), "pardal_router_mojo")
    assert_true(out[PythonObject(String("tracks"))].__len__() > 0)
    assert_true(out[PythonObject(String("failed_nets"))].__len__() == 0)

def test_route_problem_routes_outer_layers_with_internal_mask_gap():
    var tempfile = py.import_module("tempfile")
    var pathlib = py.import_module("pathlib")
    var json = py.import_module("json")

    var root = pathlib.Path(tempfile.mkdtemp())
    var problem = root / PythonObject(String("p.problem.json"))
    var routes = root / PythonObject(String("p.routes.json"))

    var payload = py.dict()
    payload[PythonObject(String("resolution_mm"))] = PythonObject(Float64(0.1))
    payload[PythonObject(String("layers"))] = py.list(
        PythonObject(String("F.Cu")),
        PythonObject(String("GND")),
        PythonObject(String("PWR")),
        PythonObject(String("B.Cu")),
    )
    var roles = py.dict()
    roles[PythonObject(String("F.Cu"))] = PythonObject(String("signal"))
    roles[PythonObject(String("GND"))] = PythonObject(String("plane"))
    roles[PythonObject(String("PWR"))] = PythonObject(String("plane"))
    roles[PythonObject(String("B.Cu"))] = PythonObject(String("signal"))
    payload[PythonObject(String("layer_roles"))] = roles
    payload[PythonObject(String("width"))] = PythonObject(Int(24))
    payload[PythonObject(String("height"))] = PythonObject(Int(24))
    payload[PythonObject(String("circles"))] = py.list()

    var net = py.dict()
    net[PythonObject(String("net"))] = PythonObject(String("N_OUTER"))
    net[PythonObject(String("net_id"))] = PythonObject(Int(1))
    var start = py.dict()
    start[PythonObject(String("layer"))] = PythonObject(Int(0))
    start[PythonObject(String("x"))] = PythonObject(Int(5))
    start[PythonObject(String("y"))] = PythonObject(Int(5))
    net[PythonObject(String("start"))] = start
    var goal = py.dict()
    goal[PythonObject(String("layer"))] = PythonObject(Int(3))
    goal[PythonObject(String("x"))] = PythonObject(Int(5))
    goal[PythonObject(String("y"))] = PythonObject(Int(5))
    net[PythonObject(String("goal"))] = goal
    net[PythonObject(String("track_width_mm"))] = PythonObject(Float64(0.2))
    net[PythonObject(String("via_diameter_mm"))] = PythonObject(Float64(0.6))
    net[PythonObject(String("via_drill_mm"))] = PythonObject(Float64(0.3))
    net[PythonObject(String("uvia_diameter_mm"))] = PythonObject(Float64(0.4))
    net[PythonObject(String("uvia_drill_mm"))] = PythonObject(Float64(0.2))
    payload[PythonObject(String("nets"))] = py.list(net)

    problem.write_text(json.dumps(payload, indent=PythonObject(Int(2))))

    try:
        route_problem(String(py=problem), String(py=routes), "")
    except e:
        assert_true(False)

    var out = json.loads(routes.read_text())
    assert_true(out[PythonObject(String("failed_nets"))].__len__() == 0)
    assert_true(out[PythonObject(String("vias"))].__len__() > 0)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
