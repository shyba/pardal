from python import Python, PythonObject
from testing import assert_equal, assert_true
from testing.suite import TestSuite

from pardal_router_mojo.dsn import (
    dsn_coord_to_mm,
    parse_dsn_class_rules,
    parse_dsn_class_members,
    parse_dsn_boundary_bbox_mm,
    parse_dsn_boundary_mm,
    parse_dsn_layers,
    parse_dsn_library_pins,
    parse_dsn_pin_positions_mm,
    parse_dsn_net_names,
    parse_dsn_net_pins,
    parse_dsn_padstacks,
    parse_dsn_placement,
    parse_dsn_pcb_name,
    parse_dsn_resolution,
    parse_dsn_summary,
    parse_dsn_structure_rules,
    parse_dsn_via_defs,
    parse_dsn_via_catalog_mm,
    parse_dsn_wiring_summary,
    parse_dsn_wiring,
    parse_dsn_wiring_mm,
    parse_dsn_wiring_vias_mm,
)

comptime py = Python


fn _read_text(rel: String) raises -> String:
    var pathlib = py.import_module("pathlib")
    var p = pathlib.Path(PythonObject(rel))
    var s = p.read_text(encoding=PythonObject(String("utf-8")), errors=PythonObject(String("replace")))
    return String(py=s)

fn _is_none(o: PythonObject) raises -> Bool:
    var operator = py.import_module("operator")
    return Bool(py=operator.is_(o, py.none()))

fn _abs_f64(x: Float64) -> Float64:
    if x < Float64(0.0):
        return -x
    return x


def test_empty_board_layer_count_and_boundary():
    var src = _read_text(String("../../freerouting/tests/empty_board.dsn"))
    var s = parse_dsn_summary(src)
    assert_true(s.pcb_symbol == String("pcb") or s.pcb_symbol == String("PCB"))
    assert_true(s.layer_count >= 2)
    assert_true(s.has_boundary)
    assert_true(Int(py=s.boundary_xs.__len__()) >= 4)
    assert_equal(Int(py=s.boundary_xs.__len__()), Int(py=s.boundary_ys.__len__()))


def test_min_fr_test_has_plane_and_layers():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var s = parse_dsn_summary(src)
    assert_true(s.layer_count >= 2)
    assert_true(s.plane_count >= 1)
    # Fixture has explicit layer names "F.Cu" and "B.Cu".
    var seen_f = False
    var seen_b = False
    for name in s.layer_names:
        if String(py=name) == String("F.Cu"):
            seen_f = True
        if String(py=name) == String("B.Cu"):
            seen_b = True
    assert_true(seen_f)
    assert_true(seen_b)

def test_min_fr_test_boundary_mm_has_bbox():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var pts = parse_dsn_boundary_mm(src)
    assert_true(Int(py=pts.__len__()) >= 4)
    var bb = parse_dsn_boundary_bbox_mm(src)
    assert_true(not _is_none(bb[PythonObject(String("min_x"))]))
    assert_true(Float64(py=bb[PythonObject(String("max_x"))]) > Float64(py=bb[PythonObject(String("min_x"))]))


def test_issue229_has_keepouts():
    var src = _read_text(String("../../freerouting/tests/Issue229-display-8-digit-hc595.dsn"))
    var s = parse_dsn_summary(src)
    assert_true(s.keepout_count >= 1)

def test_issue035_semicolon_atom_not_comment_still_parses():
    var src = _read_text(String("../../freerouting/tests/Issue035-ReadPlaceScope.dsn"))
    var s = parse_dsn_summary(src)
    assert_true(s.layer_count >= 2)

def test_min_fr_test_pcb_name_and_nets():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var pcb = parse_dsn_pcb_name(src)
    assert_true(len(pcb) > 0)
    var nets = parse_dsn_net_names(src)
    # Fixture has 2 nets: GND and Net-(J1-Pin_1)
    assert_true(Int(py=nets.__len__()) >= 2)

def test_min_fr_test_net_pins_and_class_members():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var pins_by_net = parse_dsn_net_pins(src)
    assert_true(Bool(pins_by_net.__contains__(PythonObject(String("GND")))))
    var gnd_pins = pins_by_net[PythonObject(String("GND"))]
    assert_true(Int(py=gnd_pins.__len__()) >= 1)

    var classes = parse_dsn_class_members(src)
    assert_true(Bool(classes.__contains__(PythonObject(String("kicad_default")))))
    var members = classes[PythonObject(String("kicad_default"))]
    assert_true(Int(py=members.__len__()) >= 2)

def test_min_fr_test_class_rules_width_clearance_and_use_via():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var rules = parse_dsn_class_rules(src)
    assert_true(Bool(rules.__contains__(PythonObject(String("kicad_default")))))
    var r = rules[PythonObject(String("kicad_default"))]
    # Fixture explicitly sets width/clearance in DSN units.
    assert_true(not _is_none(r[PythonObject(String("width"))]))
    assert_true(not _is_none(r[PythonObject(String("clearance"))]))
    # And sets a via padstack name.
    assert_true(not _is_none(r[PythonObject(String("use_via"))]))

def test_min_fr_test_padstack_library_contains_use_via():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var rules = parse_dsn_class_rules(src)
    var r = rules[PythonObject(String("kicad_default"))]
    var use_via = r[PythonObject(String("use_via"))]
    assert_true(not _is_none(use_via))

    var pads = parse_dsn_padstacks(src)
    # Padstack names are stored as raw atoms (unquoted). Ensure we match by string.
    var use_via_s = String(py=use_via)
    assert_true(Bool(pads.__contains__(PythonObject(use_via_s))))
    var rec = pads[PythonObject(use_via_s)]
    var shapes = rec[PythonObject(String("shapes"))]
    assert_true(Int(py=shapes.__len__()) >= 2)

def test_min_fr_test_resolution_and_via_def_decode():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var unit_name, div = parse_dsn_resolution(src)
    assert_true(len(unit_name) > 0)
    assert_true(div > Float64(0.0))
    # 100 * 10um == 1mm
    assert_true(_abs_f64(dsn_coord_to_mm(Float64(100.0), unit_name, div) - Float64(1.0)) < Float64(1e-9))

    var vias = parse_dsn_via_defs(src)
    var key = PythonObject(String("Via[0-3]_600:300_um"))
    assert_true(Bool(vias.__contains__(key)))
    var rec = vias[key]
    assert_true(not _is_none(rec[PythonObject(String("layers"))]))
    assert_true(not _is_none(rec[PythonObject(String("diameter"))]))
    assert_true(not _is_none(rec[PythonObject(String("drill"))]))

def test_synthetic_via_catalog_and_wiring_via_annotation():
    # Keep this test fast by using a tiny DSN snippet that still exercises:
    # - resolution -> mm conversion
    # - via-name decoding (span + diam/drill)
    # - wiring via annotation via catalog lookup
    var src = String(
        "(pcb test.dsn\n"
        "  (parser (string_quote \") (space_in_quoted_tokens on))\n"
        "  (resolution um 10)\n"
        "  (unit um)\n"
        "  (structure\n"
        "    (layer F.Cu (type signal) (property (index 0)))\n"
        "    (layer B.Cu (type signal) (property (index 1)))\n"
        "    (boundary (path pcb 0 0 0 100 0 100 100 0 100 0 0))\n"
        "    (via \"Via[0-1]_600:300_um\")\n"
        "  )\n"
        "  (library\n"
        "    (padstack \"Via[0-1]_600:300_um\"\n"
        "      (shape (circle F.Cu 600))\n"
        "      (shape (circle B.Cu 600))\n"
        "      (attach off)\n"
        "    )\n"
        "  )\n"
        "  (network (net N1 (pins J1-1 J2-1)))\n"
        "  (wiring\n"
        "    (via \"Via[0-1]_600:300_um\"  10 20 (net N1)(type route))\n"
        "  )\n"
        ")\n"
    )

    var cat = parse_dsn_via_catalog_mm(src)
    var key = PythonObject(String("Via[0-1]_600:300_um"))
    assert_true(Bool(cat.__contains__(key)))
    var r = cat[key]
    assert_true(not _is_none(r[PythonObject(String("diameter_mm"))]))
    assert_true(not _is_none(r[PythonObject(String("drill_mm"))]))

    var vias = parse_dsn_wiring_vias_mm(src)
    assert_true(Int(py=vias.__len__()) == 1)
    var v0 = vias[PythonObject(Int(0))]
    assert_true(not _is_none(v0[PythonObject(String("diameter_mm"))]))

def test_min_fr_test_layers_have_indices():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var layers = parse_dsn_layers(src)
    assert_true(Int(py=layers.__len__()) >= 2)
    # Ensure at least F.Cu has index 0 (fixture uses KiCad indices).
    var seen = False
    for rec in layers:
        if String(py=rec[PythonObject(String("name"))]) == String("F.Cu"):
            assert_true(not _is_none(rec[PythonObject(String("index"))]))
            assert_true(Int(py=rec[PythonObject(String("index"))]) == 0)
            seen = True
    assert_true(seen)

def test_min_fr_test_structure_clearance_types():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var r = parse_dsn_structure_rules(src)
    assert_true(not _is_none(r[PythonObject(String("width"))]))
    assert_true(not _is_none(r[PythonObject(String("clearance"))]))
    var by_type = r[PythonObject(String("clearance_by_type"))]
    # Fixture has (clearance 50 (type smd_smd))
    assert_true(Bool(by_type.__contains__(PythonObject(String("smd_smd")))))

def test_min_fr_test_placement_and_library_pins_present():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var place = parse_dsn_placement(src)
    assert_true(Int(py=place.__len__()) >= 1)
    # Placement has J1..J8 etc.
    assert_true(Bool(place.__contains__(PythonObject(String("J1")))))
    var j1 = place[PythonObject(String("J1"))]
    assert_true(not _is_none(j1[PythonObject(String("footprint"))]))
    assert_true(not _is_none(j1[PythonObject(String("x"))]))

    var pins = parse_dsn_library_pins(src)
    assert_true(Int(py=pins.__len__()) >= 1)
    # Footprint used by placement should exist in library pins.
    var fp = j1[PythonObject(String("footprint"))]
    assert_true(Bool(pins.__contains__(fp)))
    var fp_pins = pins[fp]
    assert_true(Int(py=fp_pins.__len__()) >= 1)

def test_min_fr_test_pin_positions_mm_for_network_pins():
    var src = _read_text(String("../../freerouting/tests/Issue269-min_fr_test/min_fr_test.dsn"))
    var pos = parse_dsn_pin_positions_mm(src)
    # This fixture has net pins like J8-1 and J1-1.
    assert_true(Bool(pos.__contains__(PythonObject(String("J1-1")))))
    var p = pos[PythonObject(String("J1-1"))]
    # Tuple of floats.
    assert_true(Int(py=p.__len__()) == 2)

def test_issue575_wiring_nonempty():
    var src = _read_text(String("../../freerouting/tests/Issue575-drc_dev-board_4_hole_clearance_violations.dsn"))
    var w = parse_dsn_wiring_summary(src)
    assert_true(Int(py=w[PythonObject(String("wire_count"))]) > 0)

def test_issue575_wiring_extracts_wires_and_vias():
    var src = _read_text(String("../../freerouting/tests/Issue575-drc_dev-board_4_hole_clearance_violations.dsn"))
    var w = parse_dsn_wiring(src)
    var wires = w[PythonObject(String("wires"))]
    var vias = w[PythonObject(String("vias"))]
    assert_true(Int(py=wires.__len__()) > 0)
    assert_true(Int(py=vias.__len__()) > 0)
    # Spot-check first wire has layer/net and at least 2 points.
    var w0 = wires[PythonObject(Int(0))]
    assert_true(not _is_none(w0[PythonObject(String("layer"))]))
    assert_true(not _is_none(w0[PythonObject(String("net"))]))
    var pts = w0[PythonObject(String("points"))]
    assert_true(Int(py=pts.__len__()) >= 2)

def test_issue575_wiring_mm_conversion_smoke():
    var src = _read_text(String("../../freerouting/tests/Issue575-drc_dev-board_4_hole_clearance_violations.dsn"))
    var w = parse_dsn_wiring_mm(src)
    var wires = w[PythonObject(String("wires"))]
    assert_true(Int(py=wires.__len__()) > 0)
    var w0 = wires[PythonObject(Int(0))]
    assert_true(not _is_none(w0[PythonObject(String("width_mm"))]))
    var pts = w0[PythonObject(String("points_mm"))]
    assert_true(Int(py=pts.__len__()) >= 2)


def main():
    TestSuite.discover_tests[__functions_in_module()]().run()
