import json
import sqlite3
from pathlib import Path

import pytest

from pardal.physical.compiler import (
    ProductionCheckEntry,
    build_physical_board,
    check_production_readiness,
    compile_physical,
    format_production_checks,
    format_production_checks_json,
    summarize_lcsc_database,
    summarize_lcsc_availability,
    summarize_lcsc_policy,
    summarize_part_alternates,
)
from pardal.physical.routes import apply_routes
from pardal.physical.spec import load_physical_spec, parse_current, parse_mm, parse_voltage


def test_parse_mm_rejects_unitless_values():
    with pytest.raises(ValueError, match="explicit unit"):
        parse_mm(10, field_name="board.width")
    with pytest.raises(ValueError, match="mm units"):
        parse_mm("10", field_name="board.width")


def test_parse_voltage_and_current_require_units():
    assert parse_voltage("3.3V", field_name="rails.3v3.nominal") == pytest.approx(3.3)
    assert parse_voltage("3300mV", field_name="rails.3v3.nominal") == pytest.approx(3.3)
    assert parse_current("250mA", field_name="rails.3v3.max_current") == pytest.approx(0.25)
    assert parse_current("1.5A", field_name="rails.input.max_current") == pytest.approx(1.5)

    with pytest.raises(ValueError, match="V or mV"):
        parse_voltage("3.3", field_name="rails.3v3.nominal")
    with pytest.raises(ValueError, match="A or mA"):
        parse_current("250", field_name="rails.3v3.max_current")


def test_load_physical_spec_rejects_duplicate_route_corridor_lane_indexes(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
route_corridors:
  test_corridor:
    layer: B.Cu
    axis: x
    run_from_x: 1mm
    run_to_x: 2mm
    lane_base: 5mm
    lane_pitch: 0.65mm
    lane_width: 0.35mm
    clearance: 0.20mm
    lanes:
      lane_a:
        index: 0
        nets: [RD5]
      lane_b:
        index: 0
        nets: [RD6]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate lane index 0"):
        load_physical_spec(spec_path)


def test_load_physical_spec_rejects_bad_route_corridor_axis(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
route_corridors:
  bad_axis:
    layer: B.Cu
    axis: diagonal
    run_from_x: 1mm
    run_to_x: 2mm
    lane_base: 5mm
    lane_pitch: 0.65mm
    lane_width: 0.35mm
    clearance: 0.20mm
    lanes:
      lane_a:
        index: 0
        nets: [RD5]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="axis must be x or y"):
        load_physical_spec(spec_path)


def test_load_physical_spec_parses_route_corridor_lane_handoff_points(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
route_corridors:
  test_corridor:
    layer: B.Cu
    axis: x
    run_from_x: 1mm
    run_to_x: 2mm
    lane_base: 5mm
    lane_pitch: 0.65mm
    lane_width: 0.35mm
    clearance: 0.20mm
    lanes:
      lane_a:
        index: 0
        nets: [RD5]
        entry_points:
          - [0.5mm, 4.5mm]
        exit_points:
          - [2.5mm, 5.5mm]
          - [2.5mm, 6.0mm]
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    lane = spec.route_corridors["test_corridor"].lanes["lane_a"]
    assert lane.entry_points == (["0.5mm", "4.5mm"],)
    assert lane.exit_points == (["2.5mm", "5.5mm"], ["2.5mm", "6.0mm"])


def test_load_physical_spec_parses_route_corridor_lane_pre_points_with_via(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
route_corridors:
  test_corridor:
    layer: B.Cu
    axis: x
    run_from_x: 1mm
    run_to_x: 2mm
    lane_base: 5mm
    lane_pitch: 0.65mm
    lane_width: 0.35mm
    clearance: 0.20mm
    lanes:
      lane_a:
        index: 0
        nets: [RD5]
        pre_points:
          - [0.5mm, 4.5mm]
          - via: [0.75mm, 4.75mm]
            to: B.Cu
            layers: [F.Cu, B.Cu]
""",
        encoding="utf-8",
    )
    lane = load_physical_spec(spec_path).route_corridors["test_corridor"].lanes["lane_a"]
    assert lane.pre_points == (
        ["0.5mm", "4.5mm"],
        {"via": ["0.75mm", "4.75mm"], "to": "B.Cu", "layers": ["F.Cu", "B.Cu"]},
    )


def test_load_physical_spec_rejects_malformed_route_corridor_lane_pre_points(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
route_corridors:
  test_corridor:
    layer: B.Cu
    axis: x
    run_from_x: 1mm
    run_to_x: 2mm
    lane_base: 5mm
    lane_pitch: 0.65mm
    lane_width: 0.35mm
    clearance: 0.20mm
    lanes:
      lane_a:
        index: 0
        nets: [RD5]
        pre_points:
          - via: [0.75mm, 4.75mm]
            layers: [F.Cu, B.Cu]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"pre_points\[0\]\.to"):
        load_physical_spec(spec_path)


def test_load_physical_spec_parses_source_atopile_metadata(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
  format: kicad_sexpr_netlist
  atopile:
    project: atopile
    ato_yaml: atopile/ato.yaml
    build: default
    entry: main.ato:Dspic33akDevBoard
board:
  width: 20mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)

    assert spec.source_format == "kicad_sexpr_netlist"
    assert spec.source_atopile is not None
    assert spec.source_atopile.project == Path("atopile")
    assert spec.source_atopile.ato_yaml == Path("atopile/ato.yaml")
    assert spec.source_atopile.build == "default"
    assert spec.source_atopile.entry == "main.ato:Dspic33akDevBoard"


def test_load_physical_spec_rejects_non_mapping_source_atopile(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
  atopile: default
board:
  width: 20mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source.atopile must be a mapping"):
        load_physical_spec(spec_path)


def test_load_physical_spec_parses_route_corridor_lane_run_overrides(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
route_corridors:
  test_corridor:
    layer: B.Cu
    axis: x
    run_from_x: 1mm
    run_to_x: 10mm
    lane_base: 5mm
    lane_pitch: 0.65mm
    lane_width: 0.35mm
    clearance: 0.20mm
    lanes:
      lane_a:
        index: 0
        nets: [RD5]
        run_from_x: 2mm
        run_to_x: 8mm
""",
        encoding="utf-8",
    )
    lane = load_physical_spec(spec_path).route_corridors["test_corridor"].lanes["lane_a"]
    assert lane.run_from_x == pytest.approx(2.0)
    assert lane.run_to_x == pytest.approx(8.0)


def test_load_physical_spec_rejects_cross_axis_lane_run_overrides(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP"))
  )
  (nets)
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  U1:
    footprint: Package_QFP:TQFP
    at: [10mm, 10mm]
route_corridors:
  test_corridor:
    layer: B.Cu
    axis: x
    run_from_x: 1mm
    run_to_x: 10mm
    lane_base: 5mm
    lane_pitch: 0.65mm
    lane_width: 0.35mm
    clearance: 0.20mm
    lanes:
      lane_a:
        index: 0
        nets: [RD5]
        run_from_y: 2mm
        run_to_y: 8mm
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="only valid for axis y"):
        load_physical_spec(spec_path)


def test_part_value_override_parsed_and_applied(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "R_0603") (footprint "atopile:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "net1")
      (node (ref "R1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
    value: "1k"
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    assert spec.parts["R1"].value == "1k"

    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    assert board.components["R1"].value == "1k"


def test_part_value_empty_string_rejected(tmp_path):
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
    value: ""
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-empty string"):
        load_physical_spec(spec_path)


def test_part_value_absent_preserves_netlist_value(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "original_val") (footprint "atopile:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "net1")
      (node (ref "R1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 20mm
  height: 20mm
rules:
  default_clearance: 0.20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    assert spec.parts["R1"].value is None

    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    assert board.components["R1"].value == "original_val"


def test_load_physical_spec_and_apply_placement(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP-64_10x10mm_P0.5mm"))
    (comp (ref "J1") (value "GPIO") (footprint "atopile:PinHeader_1x08_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "gnd")
      (node (ref "U1") (pin "4"))
      (node (ref "J1") (pin "8")))
    (net (code 2) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
  stackup: four_layer
  copper_layers: [F.Cu, In1.Cu, In2.Cu, B.Cu]
layer_roles:
  F.Cu: signal
  In1.Cu: power_plane
  In2.Cu: ground_reference
  B.Cu: signal
rules:
  default_clearance: 0.20mm
  netclasses:
    Power:
      width: 0.25mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [15mm, 10mm]
    rotation: 90
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical
    at: [5mm, 10mm]
netclasses:
  Power: [gnd]
power_stitch:
  - name: test_gnd_stitch
    kind: pad_vias
    net: gnd
    refs:
      U1: [4]
    vias:
      U1.4: [12mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: top
rails:
  3v3:
    nominal: 3.3V
    min: 3.0V
    max: 3.6V
    max_current: 250mA
    source: U2
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [25mm, 5mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
    diameter: 1mm
    clearance: 2mm
  - name: fid_2
    at: [27mm, 3mm]
    diameter: 1mm
    clearance: 2mm
  - name: fid_3
    at: [27mm, 13mm]
    diameter: 1mm
    clearance: 2mm
mounting_holes:
  - name: mh_1
    at: [4mm, 16mm]
    diameter: 3.4mm
    drill: 3.2mm
  - name: mh_2
    at: [26mm, 16mm]
    diameter: 3.4mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3v3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, report = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    assert board.layers == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert board.components["U1"].position == (15.0, 10.0)
    assert board.components["U1"].rotation == 90
    assert board.components["U1"].footprint == "Package_QFP:TQFP-64_10x10mm_P0.5mm"
    assert board.nets["gnd"].net_class == "Power"
    assert [entry.ref for entry in report] == ["U1", "J1"]
    assert board.components["TP1"].footprint == "TestPoint:TestPoint_Pad_1.0mm"
    assert board.components["TP1"].position == (25.0, 5.0)
    assert board.components["TP1"].pads[0].net_name == "3V3"
    assert ("TP1", "1") in board.nets["3V3"].connections
    assert board.components["FID1"].footprint == "Fiducial:Fiducial_1mm_Mask2mm"
    assert board.components["FID1"].position == (3.0, 3.0)
    assert board.components["MH1"].footprint == "MountingHole:MountingHole_3.2mm_M3"
    assert board.components["MH1"].pads[0].drill == 3.2
    assert spec.layer_roles == {
        "F.Cu": "signal",
        "In1.Cu": "power_plane",
        "In2.Cu": "ground_reference",
        "B.Cu": "signal",
    }
    assert spec.layer_role_sources["F.Cu"].display() == f"{spec_path}:9"
    assert spec.layer_role_sources["In2.Cu"].display() == f"{spec_path}:11"
    assert len(spec.power_stitches) == 1
    assert spec.power_stitches[0].raw["vias"]["U1.4"] == ["12mm", "10mm"]
    assert spec.power_stitches[0].raw["__pdl_source__"].display() == f"{spec_path}:29"
    assert spec.dfm is not None
    assert spec.dfm.profile == "jlcpcb_4_layer_smt"
    assert spec.dfm.assembly == "top"
    assert spec.rails["3v3"].nominal_voltage == pytest.approx(3.3)
    assert spec.rails["3v3"].max_current == pytest.approx(0.25)
    assert spec.rails["3v3"].raw["__pdl_source__"].display() == f"{spec_path}:42"
    assert spec.testpoints[0].name == "tp_3v3"
    assert spec.testpoints[0].at == (25.0, 5.0)
    assert spec.testpoints[0].raw["__pdl_source__"].display() == f"{spec_path}:49"
    assert spec.fiducials[0].diameter == 1.0
    assert spec.fiducials[0].clearance == 2.0
    assert spec.fiducials[0].raw["__pdl_source__"].display() == f"{spec_path}:53"
    assert spec.mounting_holes[0].drill == 3.2
    assert spec.mounting_holes[0].raw["__pdl_source__"].display() == f"{spec_path}:66"

    checks = check_production_readiness(spec, board)
    assert checks == []


def test_production_readiness_reports_source_mapped_findings(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "atopile:TQFP-64_10x10mm_P0.5mm"))
  )
  (nets
    (net (code 1) (name "gnd")
      (node (ref "U1") (pin "4"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [15mm, 10mm]
rails:
  3v3:
    nominal: 3.3V
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, _report = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    checks = check_production_readiness(spec, board)
    by_code = {check.code: check for check in checks}
    assert by_code["dfm.missing"].message == "production spec requires dfm.profile"
    assert by_code["rail.current_missing"].source == f"{spec_path}:11"
    assert by_code["rail.testpoint_missing"].source == f"{spec_path}:11"


def test_production_readiness_reports_layer_role_findings_with_sources(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
  copper_layers: [F.Cu, In1.Cu, In2.Cu, B.Cu]
layer_roles:
  F.Cu: signal
  In1.Cu: quiet_analog
  Extra.Cu: restricted
  B.Cu: ground_reference
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    findings = {entry.code: entry for entry in check_production_readiness(spec, board)}
    assert findings["layer.role_missing"].source == f"{spec_path}:6"
    assert findings["layer.role_invalid"].source == f"{spec_path}:9"
    assert findings["layer.role_unknown"].source == f"{spec_path}:10"


def _write_route_layer_policy_fixture(tmp_path, route_extra: str = "") -> Path:
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
    (comp (ref "J1") (value "HDR") (footprint "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "N1")
      (node (ref "U1") (pin "1"))
      (node (ref "J1") (pin "1")))
    (net (code 2) (name "3V3")
      (node (ref "J1") (pin "2"))))
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        f"""source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
  copper_layers: [F.Cu, In1.Cu, In2.Cu, B.Cu]
layer_roles:
  F.Cu: signal
  In1.Cu: power_plane
  In2.Cu: ground_reference
  B.Cu: signal
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [25mm, 10mm]
routes:
  - name: n1_inner_dogleg
    kind: manual_polyline
    net: N1
    layer: In1.Cu
    points:
      - [12mm, 12mm]
      - [22mm, 12mm]
{route_extra}dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [37mm, 3mm]
  - name: fid_3
    at: [37mm, 27mm]
mounting_holes:
  - name: mh_1
    at: [4mm, 26mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [34mm, 26mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    return spec_path


def _route_layer_policy_codes(spec_path: Path) -> set[str]:
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    route_report, violations = apply_routes(board, spec, strict=True)
    assert violations == []
    return {
        entry.code
        for entry in check_production_readiness(spec, board, route_report=route_report)
    }


def test_production_readiness_rejects_signal_route_on_forbidden_layer_without_exception(tmp_path):
    spec_path = _write_route_layer_policy_fixture(tmp_path)

    codes = _route_layer_policy_codes(spec_path)

    assert "route.layer_role_forbidden" in codes


def test_production_readiness_accepts_exact_route_layer_exception(tmp_path):
    spec_path = _write_route_layer_policy_fixture(
        tmp_path,
        """    route_layer_exceptions:
      - layer: In1.Cu
        role: power_plane
        nets: [N1]
        reason: "temporary escape on inner power plane"
""",
    )

    codes = _route_layer_policy_codes(spec_path)

    assert "route.layer_role_forbidden" not in codes
    assert "route_layer_exception.reason_missing" not in codes


@pytest.mark.parametrize(
    "route_extra",
    [
        """    route_layer_exceptions:
      - layer: In1.Cu
        role: power_plane
        nets: [N1]
""",
        """    route_layer_exceptions:
      - layer: In1.Cu
        role: power_plane
        nets: [N1]
        reason: "   "
""",
    ],
)
def test_production_readiness_rejects_route_layer_exception_without_reason(
    tmp_path,
    route_extra,
):
    spec_path = _write_route_layer_policy_fixture(tmp_path, route_extra)

    codes = _route_layer_policy_codes(spec_path)

    assert "route_layer_exception.reason_missing" in codes
    assert "route.layer_role_forbidden" in codes


def test_dfm_panelization_policy_parses_from_source(tmp_path):
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: customer_panel
    breakaway: mouse_bites
    rail_width: 6mm
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)

    assert spec.dfm is not None
    assert spec.dfm.raw["__pdl_source__"].display() == f"{spec_path}:11"
    assert spec.dfm.panelization is not None
    assert spec.dfm.panelization.mode == "customer_panel"
    assert spec.dfm.panelization.breakaway == "mouse_bites"
    assert spec.dfm.panelization.rail_width == pytest.approx(6.0)
    assert spec.dfm.panelization.raw["__pdl_source__"].display() == f"{spec_path}:13"


def test_production_readiness_requires_panelization_policy_for_jlc_profiles(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    findings = {entry.code: entry for entry in check_production_readiness(spec, board)}
    assert findings["dfm.panelization_missing"].source == f"{spec_path}:11"


def test_production_readiness_rejects_invalid_panelization_mode(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: coupon_sheet
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    findings = {entry.code: entry for entry in check_production_readiness(spec, board)}
    assert findings["dfm.panelization_invalid"].source == f"{spec_path}:13"


def test_production_readiness_requires_customer_panel_breakaway_and_rail_width(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: customer_panel
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    codes = {entry.code for entry in check_production_readiness(spec, board)}
    assert "dfm.panelization_breakaway_missing" in codes
    assert "dfm.panelization_rail_width_missing" in codes


def test_production_readiness_requires_customer_panel_minimum_rail_width_and_accepts_valid_policy(
    tmp_path,
):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    low_width_spec_path = tmp_path / "low-width-board.pdl.yaml"
    low_width_spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: customer_panel
    breakaway: v_cut
    rail_width: 4mm
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    valid_spec_path = tmp_path / "valid-board.pdl.yaml"
    valid_spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: customer_panel
    breakaway: mouse_bites
    rail_width: 6mm
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    low_width_spec = load_physical_spec(low_width_spec_path)
    low_width_board, _ = build_physical_board(
        low_width_spec, low_width_spec_path.parent / low_width_spec.source_netlist
    )
    low_width_codes = {
        entry.code for entry in check_production_readiness(low_width_spec, low_width_board)
    }
    assert "dfm.panelization_rail_width_below_min" in low_width_codes

    valid_spec = load_physical_spec(valid_spec_path)
    valid_board, _ = build_physical_board(
        valid_spec, valid_spec_path.parent / valid_spec.source_netlist
    )
    assert check_production_readiness(valid_spec, valid_board) == []


def test_production_readiness_reports_missing_lcsc_part_mapping(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _report = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    checks = check_production_readiness(spec, board)
    codes = {entry.code for entry in checks}
    assert "dfm.lcsc_part_missing" in codes


def test_production_readiness_allows_lcsc_exception(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_exceptions:
    R1: DNI on this build
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _report = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    checks = check_production_readiness(spec, board)
    codes = {entry.code for entry in checks}
    assert "dfm.lcsc_part_missing" not in codes


def test_lcsc_exception_threshold_passes_when_within_limit(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
  max_lcsc_exceptions: 1
  lcsc_exceptions:
    R1: generic_placeholder
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    codes = {entry.code for entry in check_production_readiness(spec, board)}
    assert "dfm.lcsc_exceptions_exceed_limit" not in codes


def test_lcsc_exception_threshold_fails_when_exceeded(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
    (comp (ref "R2") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))
      (node (ref "R2") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
  R2:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [15mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
  max_lcsc_exceptions: 1
  lcsc_exceptions:
    R1: generic_placeholder
    R2: generic_placeholder
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    checks = check_production_readiness(spec, board)
    hit = [entry for entry in checks if entry.code == "dfm.lcsc_exceptions_exceed_limit"]
    assert len(hit) == 1


def test_lcsc_exception_threshold_has_no_effect_when_absent(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
    (comp (ref "R2") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))
      (node (ref "R2") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
  R2:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [15mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
  lcsc_exceptions:
    R1: generic_placeholder
    R2: generic_placeholder
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    codes = {entry.code for entry in check_production_readiness(spec, board)}
    assert "dfm.lcsc_exceptions_exceed_limit" not in codes


def test_load_physical_spec_parses_lcsc_alternates(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))
      (node (ref "U1") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [20mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  lcsc_alternates:
    R1:
      - C25804
      - C21190
    U1:
      - C37780947
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)

    assert spec.dfm is not None
    assert spec.dfm.lcsc_alternates == {
        "R1": ("C25804", "C21190"),
        "U1": ("C37780947",),
    }


def test_load_physical_spec_parses_assembly_methods(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        "(export (version \"E\") (components (comp (ref \"R1\") (value \"10k\") (footprint \"Resistor_SMD:R_0603_1608Metric\"))) (nets (net (code 1) (name \"3V3\") (node (ref \"R1\") (pin \"1\")))))",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  assembly_methods:
    R1: jlc_smt
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    assert spec.dfm is not None
    assert spec.dfm.assembly_methods == {"R1": "jlc_smt"}


def test_load_physical_spec_parses_lcsc_database(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_database:
    path: components.sqlite3
    strict: false
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    assert spec.dfm is not None
    assert spec.dfm.lcsc_database["path"] == Path("components.sqlite3")
    assert spec.dfm.lcsc_database["strict"] is False


def test_load_physical_spec_parses_lcsc_cost(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text("(export (version \"E\") (components (comp (ref \"R1\") (value \"10k\") (footprint \"Resistor_SMD:R_0603_1608Metric\"))) (nets (net (code 1) (name \"3V3\") (node (ref \"R1\") (pin \"1\")))))", encoding="utf-8")
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text("""source:\n  netlist: test.net\nboard:\n  width: 30mm\n  height: 20mm\nparts:\n  R1:\n    footprint: Resistor_SMD:R_0603_1608Metric\n    at: [10mm, 10mm]\ndfm:\n  profile: jlcpcb_4_layer_smt\n  panelization:\n    mode: single_board\n  lcsc_cost:\n    batch_quantity: 10\n""", encoding="utf-8")
    spec = load_physical_spec(spec_path)
    assert spec.dfm is not None
    assert spec.dfm.lcsc_cost["batch_quantity"] == 10


def test_load_physical_spec_parses_lcsc_availability(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        "(export (version \"E\") (components (comp (ref \"R1\") (value \"10k\") (footprint \"Resistor_SMD:R_0603_1608Metric\"))) (nets (net (code 1) (name \"3V3\") (node (ref \"R1\") (pin \"1\"))))",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_cost:
    batch_quantity: 10
  lcsc_availability:
    strict: false
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    assert spec.dfm is not None
    assert spec.dfm.lcsc_availability["strict"] is False


def test_load_physical_spec_rejects_invalid_lcsc_availability_strict_flag(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        "(export\n  (version \"E\")\n  (components\n    (comp (ref \"R1\") (value \"10k\") (footprint \"Resistor_SMD:R_0603_1608Metric\"))\n  )\n  (nets\n    (net (code 1) (name \"3V3\")\n      (node (ref \"R1\") (pin \"1\")))))",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_availability:
    strict: "yes"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="dfm.lcsc_availability.strict must be a boolean"):
        load_physical_spec(spec_path)


@pytest.mark.parametrize(
    ("database_yaml", "message"),
    [
        ("path:\n      - C37780947\n", "dfm.lcsc_database.path must be a non-empty string"),
        ("path: 123\n", "dfm.lcsc_database.path must be a non-empty string"),
        ("path: \"\"\n", "dfm.lcsc_database.path must be a non-empty string"),
    ],
)
def test_load_physical_spec_rejects_invalid_lcsc_database(tmp_path, database_yaml, message):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        f"""source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_database:
    {database_yaml}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_physical_spec(spec_path)


def test_load_physical_spec_rejects_invalid_lcsc_database_strict_flag(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))))
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_database:
    path: components.sqlite3
    strict: "yes"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="dfm.lcsc_database.strict must be a boolean"):
        load_physical_spec(spec_path)


def _write_lcsc_component_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE v_components (
              lcsc TEXT PRIMARY KEY,
              stock INTEGER,
              basic TEXT,
              preferred TEXT,
              package TEXT,
              description TEXT,
              price REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO v_components (lcsc, stock, basic, preferred, package, description, price)
            VALUES (:lcsc, :stock, :basic, :preferred, :package, :description, :price)
            """
        , {
            "lcsc": "C37780947",
            "stock": 36,
            "basic": "Yes",
            "preferred": "No",
            "package": "TQFP-64(10x10)",
            "description": "MCU",
            "price": 0.34,
        })


def test_summarize_lcsc_database_reports_stock_snapshot(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "U1") (pin "1"))
      (node (ref "R1") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "components.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE v_components (
              lcsc TEXT PRIMARY KEY,
              stock INTEGER,
              basic TEXT,
              preferred TEXT,
              package TEXT,
              description TEXT,
              price REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO v_components (lcsc, stock, basic, preferred, package, description, price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ("C37780947", 36, "Yes", "Yes", "TQFP-64(10x10)", "MCU", 0.45),
                ("C25804", 22319909, "Yes", "No", "0603", "Resistor", 0.08),
            ),
        )

    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [18mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_database:
    path: components.sqlite3
    strict: true
  lcsc_parts:
    U1: C37780947
  lcsc_alternates:
    U1:
      - C25804
      - C21190
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    summary = summarize_lcsc_database(spec, board)

    assert summary.configured is True
    assert summary.exists is True
    assert summary.strict is True
    assert summary.checked_code_count == 3
    assert summary.found_code_count == 2
    assert summary.missing_code_count == 1
    assert summary.missing_codes == ("C21190",)
    assert "C25804" in summary.codes
    assert summary.codes["C25804"].stock == 22319909
    assert summary.codes["C25804"].package == "0603"


def test_summarize_lcsc_database_dedupes_codes_and_normalizes_c_prefix_lookup(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
    (comp (ref "C1") (value "100n") (footprint "Capacitor_SMD:C_0603_1608Metric"))
    (comp (ref "C2") (value "100n") (footprint "Capacitor_SMD:C_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "U1") (pin "1"))
      (node (ref "C1") (pin "1"))
      (node (ref "C2") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "components.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE v_components (
              lcsc TEXT PRIMARY KEY,
              stock INTEGER,
              basic TEXT,
              preferred TEXT,
              package TEXT,
              description TEXT,
              price REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO v_components (lcsc, stock, basic, preferred, package, description, price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ("37780947", 36, "Yes", "Yes", "TQFP-64(10x10)", "MCU", 0.45),
                ("25804", 22319909, "Yes", "No", "0603", "Resistor", 0.08),
            ),
        )

    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
  C1:
    footprint: Capacitor_SMD:C_0603_1608Metric
    at: [18mm, 10mm]
  C2:
    footprint: Capacitor_SMD:C_0603_1608Metric
    at: [24mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_database:
    path: components.sqlite3
    strict: true
  lcsc_parts:
    U1: C37780947
    C1: C25804
    C2: C25804
  lcsc_alternates:
    U1:
      - C25804
      - C21190
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    summary = summarize_lcsc_database(spec, board)

    assert summary.checked_codes == ("C21190", "C25804", "C37780947")
    assert summary.checked_code_count == 3
    assert summary.found_code_count == 2
    assert summary.missing_codes == ("C21190",)
    assert summary.missing_code_count == 1
    assert set(summary.codes) == {"C25804", "C37780947"}


def test_summarize_lcsc_availability_primary_aggregation_and_shortage(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version \"E\")
  (components
    (comp (ref \"R1\") (value \"10k\") (footprint \"Resistor_SMD:R_0603_1608Metric\"))
    (comp (ref \"R2\") (value \"10k\") (footprint \"Resistor_SMD:R_0603_1608Metric\"))
    (comp (ref \"C1\") (value \"100n\") (footprint \"Capacitor_SMD:C_0603_1608Metric\"))
  )
  (nets
    (net (code 1) (name \"3V3\")
      (node (ref \"R1\") (pin \"1\"))
      (node (ref \"R2\") (pin \"1\"))
      (node (ref \"C1\") (pin \"1\"))))
)""",
        encoding="utf-8",
    )
    db_path = tmp_path / "components.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE v_components (
              lcsc TEXT PRIMARY KEY,
              stock INTEGER,
              basic TEXT,
              preferred TEXT,
              package TEXT,
              description TEXT,
              price REAL
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO v_components (lcsc, stock, basic, preferred, package, description, price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ("37780947", 2, "Yes", "No", "TQFP", "MCU", 0.45),
                ("25804", 1, "Yes", "No", "0603", "Resistor", 0.01),
            ),
        )

    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [18mm, 10mm]
  R2:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [24mm, 10mm]
  C1:
    footprint: Capacitor_SMD:C_0603_1608Metric
    at: [30mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_database:
    path: components.sqlite3
  lcsc_cost:
    batch_quantity: 3
  lcsc_availability: {}
  lcsc_parts:
    R1: C37780947
    R2: 37780947
    C1: C25804
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    summary = summarize_lcsc_availability(spec, board)

    assert summary.configured is True
    assert summary.batch_quantity == 3
    assert summary.line_count == 2
    assert summary.checked_line_count == 2
    assert summary.shortage_line_count == 2
    assert summary.unknown_stock_line_count == 0
    assert summary.shortage_codes == ("C25804", "C37780947")
    assert summary.lines[0].code == "C25804"
    assert summary.lines[0].ref_count == 1
    assert summary.lines[0].required_quantity == 3
    assert summary.lines[0].stock == 1
    assert summary.lines[0].shortage_quantity == 2
    assert summary.lines[1].code == "C37780947"
    assert summary.lines[1].ref_count == 2
    assert summary.lines[1].required_quantity == 6
    assert summary.lines[1].stock == 2
    assert summary.lines[1].shortage_quantity == 4
    assert summary.passed is False


@pytest.mark.parametrize(
    ("alternates_yaml", "message"),
    [
        ("    - C21190\n", "dfm.lcsc_alternates must be a mapping"),
        ("    \"\":\n      - C21190\n", "dfm.lcsc_alternates contains empty reference key"),
        ("    R1: []\n", "dfm.lcsc_alternates.R1 must be a non-empty list"),
        ("    R1:\n      - \"\"\n", r"dfm\.lcsc_alternates\.R1\[0\] must be a non-empty string"),
        ("    R1:\n      - C21190\n      - C21190\n", "dfm.lcsc_alternates.R1 contains duplicate alternate C21190"),
    ],
)
def test_load_physical_spec_rejects_invalid_lcsc_alternates(tmp_path, alternates_yaml, message):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        f"""source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  lcsc_alternates:
{alternates_yaml}""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_physical_spec(spec_path)


def test_summarize_part_alternates_reports_unused_refs(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "R1") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  lcsc_alternates:
    R1:
      - C21190
    R9:
      - C25804
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)

    summary = summarize_part_alternates(spec, board)

    assert summary.declared_count == 2
    assert summary.ref_count == 2
    assert summary.refs == ("R1", "R9")
    assert summary.alternates_by_ref == {
        "R1": ("C21190",),
        "R9": ("C25804",),
    }
    assert summary.unused_ref_count == 1
    assert summary.unused_refs == ("R9",)
    assert summary.passed is False


def test_production_mechanical_checks_report_overlap_and_edge_clearance(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [4mm, 18mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [1.7mm, 1.7mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    checks = check_production_readiness(spec, board)
    codes = {entry.code for entry in checks}
    assert "mech.fiducial_hole_overlap" in codes
    assert "mech.hole_edge_clearance" in codes
    report_text = format_production_checks(checks)
    assert "mech.fiducial_hole_overlap" in report_text
    assert "mech.hole_edge_clearance" in report_text
    report_json = format_production_checks_json(checks)
    assert '"production_checks"' in report_json
    assert '"findings"' in report_json
    assert '"code": "mech.fiducial_hole_overlap"' in report_json


def test_production_dfm_profile_checks_flag_rule_and_hole_limits(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
rules:
  default_clearance: 0.08mm
  netclasses:
    Signal:
      width: 0.09mm
      clearance: 0.08mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [27mm, 3mm]
  - name: fid_3
    at: [27mm, 17mm]
mounting_holes:
  - name: mh_1
    at: [4mm, 16mm]
    diameter: 0.16mm
    drill: 0.18mm
  - name: mh_2
    at: [26mm, 16mm]
    diameter: 0.16mm
    drill: 0.18mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    checks = check_production_readiness(spec, board)
    codes = {entry.code for entry in checks}
    assert "dfm.clearance_below_profile" in codes
    assert "dfm.track_width_below_profile" in codes
    assert "dfm.netclass_clearance_below_profile" in codes
    assert "dfm.mounting_hole_drill_below_profile" in codes
    assert "dfm.mounting_hole_geometry_invalid" in codes


def test_jlcpcb_profile_reports_min_drill_violation(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
rules:
  default_clearance: 0.20mm
  netclasses:
    Default:
      width: 0.25mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 0.45mm
    drill: 0.15mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    checks = check_production_readiness(spec, board)
    assert any(entry.code == "dfm.mounting_hole_drill_below_profile" for entry in checks)


def test_jlcpcb_profile_reports_mounting_hole_annular_ring_violation(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
rules:
  default_clearance: 0.20mm
  netclasses:
    Default:
      width: 0.25mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.1mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    checks = check_production_readiness(spec, board)
    assert any(entry.code == "dfm.mounting_hole_geometry_invalid" for entry in checks)


def test_jlcpcb_profile_reports_minimum_declared_routing_rules(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
rules:
  default_clearance: 0.05mm
  netclasses:
    Default:
      width: 0.05mm
      clearance: 0.05mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    checks = check_production_readiness(spec, board)
    codes = {entry.code for entry in checks}
    assert "dfm.track_width_below_profile" in codes
    assert "dfm.clearance_below_profile" in codes
    assert "dfm.netclass_clearance_below_profile" in codes


def test_jlcpcb_profile_reports_missing_required_artifacts(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
rules:
  default_clearance: 0.20mm
  netclasses:
    Default:
      width: 0.25mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: top
  required_artifacts:
    - mfg/bom.csv
    - mfg/pnp.csv
    - mfg/gerbers
    - mfg/drill
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    result = compile_physical(
        spec_path,
        output_path=tmp_path / "board.kicad_pcb",
        run_drc=False,
        production_check=True,
    )
    misses = [entry for entry in result.production_checks if entry.code == "dfm.artifact_missing"]
    assert len(misses) == 4
    messages = {entry.message for entry in misses}
    assert "required manufacturing artifact missing: mfg/bom.csv" in messages
    assert "required manufacturing artifact missing: mfg/pnp.csv" in messages
    assert "required manufacturing artifact missing: mfg/gerbers" in messages
    assert "required manufacturing artifact missing: mfg/drill" in messages


@pytest.mark.parametrize(
    ("artifact_path", "is_dir", "expected_message"),
    [
        ("mfg/bom.csv", False, "required manufacturing artifact file is empty: mfg/bom.csv"),
        ("mfg/gerbers", True, "required manufacturing artifact directory is empty: mfg/gerbers"),
    ],
)
def test_jlcpcb_profile_reports_empty_required_artifacts(
    tmp_path, artifact_path, is_dir, expected_message
):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    (tmp_path / "mfg").mkdir()
    if is_dir:
        (tmp_path / artifact_path).mkdir()
        (tmp_path / "mfg" / "bom.csv").write_text("ref,mpn\n", encoding="utf-8")
    else:
        (tmp_path / artifact_path).write_text("", encoding="utf-8")
        (tmp_path / "mfg" / "gerbers").mkdir()
        (tmp_path / "mfg" / "gerbers" / "top.gbr").write_text("G04\n", encoding="utf-8")
    (tmp_path / "mfg" / "pnp.csv").write_text("ref,x,y\n", encoding="utf-8")
    (tmp_path / "mfg" / "drill").mkdir()
    (tmp_path / "mfg" / "drill" / "board.drl").write_text("M48\n", encoding="utf-8")
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
rules:
  default_clearance: 0.20mm
  netclasses:
    Default:
      width: 0.25mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: top
  required_artifacts:
    - mfg/bom.csv
    - mfg/pnp.csv
    - mfg/gerbers
    - mfg/drill
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    empties = [
        entry
        for entry in check_production_readiness(spec, board, artifact_root=tmp_path)
        if entry.code == "dfm.artifact_empty"
    ]
    assert [entry.message for entry in empties] == [expected_message]


def test_jlcpcb_profile_required_artifacts_pass_when_present(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    (tmp_path / "mfg").mkdir()
    (tmp_path / "mfg" / "bom.csv").write_text("ref,mpn\n", encoding="utf-8")
    (tmp_path / "mfg" / "pnp.csv").write_text("ref,x,y\n", encoding="utf-8")
    (tmp_path / "mfg" / "gerbers").mkdir()
    (tmp_path / "mfg" / "gerbers" / "top.gbr").write_text("G04 gerber\n", encoding="utf-8")
    (tmp_path / "mfg" / "drill").mkdir()
    (tmp_path / "mfg" / "drill" / "board.drl").write_text("M48\n", encoding="utf-8")
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
rules:
  default_clearance: 0.20mm
  netclasses:
    Default:
      width: 0.25mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: top
  required_artifacts:
    - mfg/bom.csv
    - mfg/pnp.csv
    - mfg/gerbers
    - mfg/drill
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    checks = check_production_readiness(spec, board, artifact_root=tmp_path)
    assert not any(entry.code == "dfm.artifact_missing" for entry in checks)
    assert not any(entry.code == "dfm.artifact_empty" for entry in checks)


def test_jlcpcb_profile_reports_invalid_assembly_value(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
rules:
  default_clearance: 0.20mm
  netclasses:
    Default:
      width: 0.25mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: both_sides
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.4mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    checks = check_production_readiness(spec, board)
    assert any(entry.code == "dfm.assembly_invalid" for entry in checks)


def test_compile_physical_emits_bom_and_pnp_csv(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: top
  required_artifacts:
    - board.bom.csv
    - board.pnp.csv
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    pcb = tmp_path / "board.kicad_pcb"
    bom = tmp_path / "board.bom.csv"
    pnp = tmp_path / "board.pnp.csv"
    result = compile_physical(
        spec_path,
        output_path=pcb,
        run_drc=False,
        production_check=True,
        bom_output=bom,
        pnp_output=pnp,
    )
    assert result.production_checks == []
    assert bom.exists()
    assert pnp.exists()
    bom_text = bom.read_text(encoding="utf-8")
    pnp_text = pnp.read_text(encoding="utf-8")
    assert "ref,value,footprint,layer" in bom_text
    assert "J1,PWR,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical,F.Cu" in bom_text
    assert "ref,x_mm,y_mm,rotation_deg,side,footprint" in pnp_text
    assert "J1,10.0000,10.0000,0.00,top,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical" in pnp_text


def test_compile_physical_jlc_requires_artifact_contract(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: top
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    pcb = tmp_path / "board.kicad_pcb"
    result = compile_physical(
        spec_path,
        output_path=pcb,
        run_drc=False,
        production_check=True,
    )
    assert any(entry.code == "dfm.artifact_contract_missing" for entry in result.production_checks)


def test_lcsc_policy_summary_reports_mapped_excepted_missing(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "U1") (pin "1"))
      (node (ref "R1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [15mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
  lcsc_parts:
    U1: C37780947
  lcsc_exceptions:
    R1: generic_placeholder
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / spec.source_netlist)
    summary = summarize_lcsc_policy(spec, board)
    assert summary is not None
    assert summary.mapped == 1
    assert summary.excepted == 1
    assert summary.missing == 0
    assert summary.mapped_refs == ("U1",)
    assert summary.excepted_refs == ("R1",)


def test_production_json_report_includes_lcsc_policy_summary_when_available(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "U1") (pin "1"))
      (node (ref "R1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [15mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
  lcsc_parts:
    U1: C37780947
  lcsc_exceptions:
    R1: generic_placeholder
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    pcb = tmp_path / "board.kicad_pcb"
    result = compile_physical(spec_path, output_path=pcb, run_drc=False, production_check=True)

    payload = json.loads(
        format_production_checks_json(result.production_checks, result.lcsc_policy_summary)
    )
    assert "lcsc_policy_summary" in payload
    assert payload["lcsc_policy_summary"] == {
        "mapped": 1,
        "excepted": 1,
        "missing": 0,
        "mapped_refs": ["U1"],
        "excepted_refs": ["R1"],
        "missing_refs": [],
    }


def test_production_json_report_omits_lcsc_policy_summary_when_unavailable(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    pcb = tmp_path / "board.kicad_pcb"
    result = compile_physical(spec_path, output_path=pcb, run_drc=False, production_check=True)

    payload = json.loads(
        format_production_checks_json(result.production_checks, result.lcsc_policy_summary)
    )
    assert payload["production_checks"] == len(result.production_checks)
    assert isinstance(payload["findings"], list)
    assert "lcsc_policy_summary" not in payload


def test_format_production_checks_json_includes_grouped_dfm_report():
    payload = json.loads(
        format_production_checks_json(
            [
                ProductionCheckEntry(
                    severity="warning",
                    code="mech.edge_clearance",
                    message="Hole too close to board edge",
                    source="board.pdl.yaml:11",
                ),
                ProductionCheckEntry(
                    severity="error",
                    code="dfm.clearance_below_profile",
                    message="Trace spacing below profile minimum",
                    source="board.pdl.yaml:22",
                ),
                ProductionCheckEntry(
                    severity="warning",
                    code="mech.edge_clearance",
                    message="Hole too close to board edge",
                    source="board.pdl.yaml:15",
                ),
                ProductionCheckEntry(
                    severity="error",
                    code="mech.edge_clearance",
                    message="Mounting hole violates edge keepout",
                    source="board.pdl.yaml:18",
                ),
            ]
        )
    )

    assert payload["production_checks"] == 4
    assert isinstance(payload["findings"], list)
    assert payload["dfm_report"] == {
        "count": 4,
        "error_count": 2,
        "warning_count": 2,
        "by_severity": {
            "error": 2,
            "warning": 2,
        },
        "by_code": {
            "dfm.clearance_below_profile": {
                "count": 1,
                "severities": ["error"],
                "sources": ["board.pdl.yaml:22"],
                "messages": ["Trace spacing below profile minimum"],
            },
            "mech.edge_clearance": {
                "count": 3,
                "severities": ["error", "warning"],
                "sources": [
                    "board.pdl.yaml:11",
                    "board.pdl.yaml:15",
                    "board.pdl.yaml:18",
                ],
                "messages": [
                    "Hole too close to board edge",
                    "Mounting hole violates edge keepout",
                ],
            },
        },
    }


def test_format_production_checks_json_includes_package_finding_metadata():
    payload = json.loads(
        format_production_checks_json(
            [
                ProductionCheckEntry(
                    severity="error",
                    code="fixture.metadata_check",
                    message="metadata finding",
                    source="contracts/board.contract.yaml:adc_frontends.ADC0",
                    stage="source_contract",
                    package="acme/gd32f310-support",
                    evidence={"channel": "ADC0"},
                    source_details={
                        "path": "contracts/board.contract.yaml",
                        "field": "adc_frontends.ADC0",
                    },
                    waived=True,
                    waiver_reason="covered by board review",
                )
            ]
        )
    )

    assert payload["findings"] == [
        {
            "severity": "error",
            "code": "fixture.metadata_check",
            "message": "metadata finding",
            "source": "contracts/board.contract.yaml:adc_frontends.ADC0",
            "stage": "source_contract",
            "package": "acme/gd32f310-support",
            "evidence": {"channel": "ADC0"},
            "source_details": {
                "path": "contracts/board.contract.yaml",
                "field": "adc_frontends.ADC0",
            },
            "waived": True,
            "waiver_reason": "covered by board review",
        }
    ]


def test_format_production_checks_json_includes_lcsc_summary_when_present(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "U1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
  lcsc_parts:
    U1: C37780947
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    result = compile_physical(
        spec_path,
        output_path=tmp_path / "board.kicad_pcb",
        run_drc=False,
        production_check=True,
    )
    payload = format_production_checks_json(result.production_checks, result.lcsc_policy_summary)
    assert '"production_checks"' in payload
    assert '"findings"' in payload
    assert '"lcsc_policy_summary"' in payload
    assert '"mapped": 1' in payload
    assert '"excepted": 0' in payload
    assert '"missing": 0' in payload


def test_compile_physical_emits_jlc_bom_and_pnp_csv(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: top
  required_artifacts:
    - board.jlc.bom.csv
    - board.jlc.pnp.csv
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    pcb = tmp_path / "board.kicad_pcb"
    jlc_bom = tmp_path / "board.jlc.bom.csv"
    jlc_pnp = tmp_path / "board.jlc.pnp.csv"
    result = compile_physical(
        spec_path,
        output_path=pcb,
        run_drc=False,
        production_check=True,
        jlc_bom_output=jlc_bom,
        jlc_pnp_output=jlc_pnp,
    )
    assert result.production_checks == []
    bom_text = jlc_bom.read_text(encoding="utf-8")
    pnp_text = jlc_pnp.read_text(encoding="utf-8")
    assert "Designator,Comment,Footprint,LCSC Part #" in bom_text
    assert "J1,PWR,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical," in bom_text
    assert "Designator,Mid X,Mid Y,Layer,Rotation" in pnp_text
    assert "J1,10.0000mm,10.0000mm,Top,0.00" in pnp_text


def test_compile_physical_excludes_helpers_from_exports_when_disabled(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  assembly: top
  required_artifacts:
    - board.bom.csv
    - board.pnp.csv
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [4mm, 18mm]
  - name: fid_3
    at: [28mm, 3mm]
mounting_holes:
  - name: mh_1
    at: [6mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [24mm, 15mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )
    pcb = tmp_path / "board.kicad_pcb"
    bom = tmp_path / "board.bom.csv"
    pnp = tmp_path / "board.pnp.csv"
    result = compile_physical(
        spec_path,
        output_path=pcb,
        run_drc=False,
        production_check=True,
        bom_output=bom,
        pnp_output=pnp,
        include_helpers_in_exports=False,
    )
    assert result.production_checks == []
    bom_text = bom.read_text(encoding="utf-8")
    pnp_text = pnp.read_text(encoding="utf-8")
    assert "J1,PWR,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical,F.Cu" in bom_text
    assert "TP1" not in bom_text
    assert "FID1" not in bom_text
    assert "MH1" not in bom_text
    assert "J1,10.0000,10.0000,0.00,top,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical" in pnp_text
    assert "TP1" not in pnp_text


def test_load_physical_spec_parses_keepouts_with_source_mapping(tmp_path):
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """board:
  width: 20mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
keepouts:
  - name: gpio_corridor_guard
    layer: F.Cu
    kind: route
    at: [10mm, 10mm]
    size: [4mm, 2mm]
""",
        encoding="utf-8",
    )
    spec = load_physical_spec(spec_path)
    assert len(spec.keepouts) == 1
    keepout = spec.keepouts[0]
    assert keepout.name == "gpio_corridor_guard"
    assert keepout.layer == "F.Cu"
    assert keepout.kind == "route"
    assert keepout.at == (10.0, 10.0)
    assert keepout.size == (4.0, 2.0)
    assert keepout.raw["__pdl_source__"].display() == f"{spec_path}:9"


def test_load_physical_spec_parses_validation_tests_with_source_mapping(tmp_path):
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """board:
  width: 20mm
  height: 20mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)

    assert len(spec.validation_tests) == 1
    validation_test = spec.validation_tests[0]
    assert validation_test.name == "power_on_3v3"
    assert validation_test.kind == "power_on"
    assert validation_test.rail == "3V3"
    assert validation_test.criteria == "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
    assert validation_test.raw["__pdl_source__"].display() == f"{spec_path}:9"


def test_check_production_readiness_validates_source_owned_validation_tests(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "GPIO") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1")))
    (net (code 2) (name "gnd")
      (node (ref "J1") (pin "2")))
    (net (code 3) (name "mclr")
      (node (ref "J1") (pin "3"))))
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
  gnd:
    nominal: 0V
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
  - name: tp_gnd
    net: gnd
    at: [20mm, 12mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [27mm, 3mm]
  - name: fid_3
    at: [27mm, 17mm]
mounting_holes:
  - name: mh_1
    at: [3mm, 17mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [27mm, 17mm]
    diameter: 3.2mm
    drill: 3.2mm
validation_tests:
  - name: power_on_3v3
    kind: power_on
    rail: 3V3
    net: 3V3
    criteria: "Measure 3V3 at TP1: pass 3.20V to 3.40V after 100ms."
  - name: bad_kind
    kind: unsupported
    criteria: "Should be rejected."
  - name: missing_criteria
    kind: debug_interface
    interface: ICSP
  - name: missing_refs
    kind: fault_state
    rail: VBAT
    net: missing_net
    criteria: "Hold reset low and confirm the net stays below 0.20V."
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / "test.net")
    findings = check_production_readiness(spec, board, artifact_root=tmp_path)
    assert not any(entry.code == "validation.tests_missing" for entry in findings)
    invalid_kind = next(entry for entry in findings if entry.code == "validation.kind_invalid")
    assert invalid_kind.source == f"{spec_path}:49"
    criteria_missing = next(entry for entry in findings if entry.code == "validation.criteria_missing")
    assert criteria_missing.source == f"{spec_path}:52"
    rail_missing = next(entry for entry in findings if entry.code == "validation.rail_missing")
    assert rail_missing.source == f"{spec_path}:55"
    net_missing = next(entry for entry in findings if entry.code == "validation.net_missing")
    assert net_missing.source == f"{spec_path}:55"


def test_check_production_readiness_requires_validation_tests_for_jlc_profile(tmp_path):
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x02_P2.54mm_Vertical"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1")))
    (net (code 2) (name "gnd")
      (node (ref "J1") (pin "2"))))
)
""",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 30mm
  height: 20mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
rails:
  3V3:
    nominal: 3.3V
    max_current: 100mA
  gnd:
    nominal: 0V
testpoints:
  - name: tp_3v3
    net: 3V3
    at: [20mm, 10mm]
  - name: tp_gnd
    net: gnd
    at: [20mm, 12mm]
fiducials:
  - name: fid_1
    at: [3mm, 3mm]
  - name: fid_2
    at: [27mm, 3mm]
  - name: fid_3
    at: [27mm, 17mm]
mounting_holes:
  - name: mh_1
    at: [3mm, 17mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [27mm, 17mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )

    spec = load_physical_spec(spec_path)
    board, _ = build_physical_board(spec, spec_path.parent / "test.net")
    checks = check_production_readiness(spec, board)

    entry = next(entry for entry in checks if entry.code == "validation.tests_missing")
    assert entry.source == f"{spec_path}:11"
