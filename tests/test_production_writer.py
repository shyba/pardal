import json
import sqlite3
from pathlib import Path
import subprocess
import zipfile

import pytest

from pardal.physical.commit_gate import CommitViolation
from pardal.physical.routes import (
    RouteCommitFailureError,
    RouteFailureCandidate,
    RouteFailureReport,
    RouteFailureSegment,
    RouteFailureViolation,
    RouteFailureVia,
)
import pardal.physical.compiler as physical_compiler
from pardal.physical.compiler import compile_physical
from pardal.kicad_text_loader import load_board_kicad_pcb


def _write_lcsc_database(path: Path) -> None:
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
        conn.executemany(
            """
            INSERT INTO v_components (lcsc, stock, basic, preferred, package, description, price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("C37780947", 36, "Yes", "Preferred", "TQFP-64(10x10)", "MCU", 1.23),
                ("C25804", 22319909, "Yes", "No", "0603", "Resistor", 0.02),
            ],
        )


def _write_basic_netlist(path: Path) -> None:
    path.write_text(
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


def test_compile_physical_uses_source_board_dimensions_for_edge_cuts(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
  copper_layers: [F.Cu, B.Cu]
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
""",
        encoding="utf-8",
    )
    output = tmp_path / "out.kicad_pcb"

    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=False,
    )

    loaded = load_board_kicad_pcb(output).board
    assert loaded.width == pytest.approx(40.0)
    assert loaded.height == pytest.approx(30.0)


def _write_netlist_with_extra_component(path: Path) -> None:
    path.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "J1") (value "PWR") (footprint "atopile:PinHeader_1x03_P2.54mm_Vertical"))
    (comp (ref "R1") (value "1k") (footprint "atopile:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "3V3")
      (node (ref "J1") (pin "1"))
      (node (ref "R1") (pin "1"))))
  )
)
""",
        encoding="utf-8",
    )


def _write_route_group_netlist(path: Path) -> None:
    path.write_text(
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
    (net (code 2) (name "N2")
      (node (ref "U1") (pin "2"))
      (node (ref "J1") (pin "2")))
    (net (code 3) (name "N3")
      (node (ref "U1") (pin "3"))
      (node (ref "J1") (pin "3"))))
)
""",
        encoding="utf-8",
    )


def _write_drc_report(path: Path, contents: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def test_production_intent_writes_sdk_footprints(tmp_path):
    pcbnew = pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
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
footprint_aliases:
  atopile:PinHeader_1x03_P2.54mm_Vertical: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  required_artifacts:
    - mfg/bom.csv
    - mfg/pnp.csv
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
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    output = tmp_path / "out.kicad_pcb"
    bom = tmp_path / "mfg" / "bom.csv"
    pnp = tmp_path / "mfg" / "pnp.csv"

    result = compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
        bom_output=bom,
        pnp_output=pnp,
    )

    assert result.production_checks == []
    board = pcbnew.LoadBoard(str(output))
    footprints = {fp.GetReference(): fp for fp in board.GetFootprints()}
    assert {"TP1", "FID1", "FID2", "FID3", "MH1", "MH2"}.issubset(footprints)
    assert footprints["TP1"].FindPadByNumber("1").GetNetname() == "3V3"
    assert footprints["FID1"].FindPadByNumber("1").GetNetname() == ""
    assert [pad.GetNetname() for pad in footprints["MH1"].Pads()] in ([], [""])


def test_compile_physical_strict_route_failure_writes_diagnostics_json(
    tmp_path,
    monkeypatch,
):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
  copper_layers: [F.Cu, B.Cu]
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
""",
        encoding="utf-8",
    )

    report = RouteFailureReport(
        net="RD5",
        strategy="manual_polyline",
        route_name="manual_polyline[0001]",
        route_index=0,
        source="board.pdl.yaml:20",
        candidate=RouteFailureCandidate(
            segments=(RouteFailureSegment((1.0, 1.0), (2.0, 1.0), "F.Cu", 0.2),),
            vias=(),
            segment_layers=("F.Cu",),
            via_layers=(),
            used_layers=("F.Cu",),
        ),
        violations=(
            RouteFailureViolation(
                code="track_to_pad_clearance",
                message="manual_polyline[0001] blocked",
                net="RD5",
                layer="F.Cu",
                source="board.pdl.yaml:20",
                distance=0.12,
            ),
        ),
    )

    def failing_apply_routes(*args, **kwargs):
        raise RouteCommitFailureError(
            report,
            [CommitViolation(v.code, v.message) for v in report.violations],
        )

    monkeypatch.setattr(physical_compiler, "apply_routes", failing_apply_routes)
    route_diag = tmp_path / "route-diagnostics.json"
    build_summary = tmp_path / "build-summary.json"

    with pytest.raises(RouteCommitFailureError):
        compile_physical(
            spec_path,
            output_path=tmp_path / "out.kicad_pcb",
            run_drc=False,
            strict=True,
            route_diagnostics_report=route_diag,
            build_summary_output=build_summary,
            production_check=False,
        )

    payload = json.loads(route_diag.read_text(encoding="utf-8"))
    assert payload["strict_aborted"] is True
    assert payload["failed_candidate_count"] == 1
    assert payload["violation_count"] == 1
    failure = payload["failures"][0]
    assert failure["net"] == "RD5"
    assert failure["route_index"] == 0
    assert failure["strategy"] == "manual_polyline"
    assert failure["source"] == "board.pdl.yaml:20"
    assert failure["candidate"]["segments"][0]["start"] == [1.0, 1.0]
    assert failure["violations"][0]["code"] == "track_to_pad_clearance"
    assert build_summary.exists() is False


def test_compile_physical_build_summary_satisfies_current_run_artifact_contract(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
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
footprint_aliases:
  atopile:PinHeader_1x03_P2.54mm_Vertical: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  required_artifacts:
    - mfg/bom.csv
    - mfg/pnp.csv
    - mfg/production-checks.json
    - mfg/build-summary.json
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
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    output = tmp_path / "out.kicad_pcb"
    bom = tmp_path / "mfg" / "bom.csv"
    pnp = tmp_path / "mfg" / "pnp.csv"
    production_report = tmp_path / "mfg" / "production-checks.json"
    drc_diagnostics = tmp_path / "mfg" / "drc-diagnostics.json"
    build_summary = tmp_path / "mfg" / "build-summary.json"

    result = compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
        bom_output=bom,
        pnp_output=pnp,
        production_report=production_report,
        production_report_format="json",
        drc_diagnostics_report=drc_diagnostics,
        drc_diagnostics_format="json",
        build_summary_output=build_summary,
    )

    assert result.production_checks == []
    production_payload = json.loads(production_report.read_text(encoding="utf-8"))
    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert production_payload["dfm_report"] == {
        "count": 0,
        "error_count": 0,
        "warning_count": 0,
        "by_severity": {},
        "by_code": {},
    }
    assert payload["dfm_report"] == production_payload["dfm_report"]
    assert payload["artifacts"]["production_report"]["generated"] == str(production_report.resolve())
    assert payload["artifacts"]["build_summary"]["generated"] == str(build_summary.resolve())
    assert payload["artifacts"]["route_diagnostics"]["requested"] is None
    assert payload["artifacts"]["route_diagnostics"]["generated"] is None
    assert payload["artifacts"]["drc_diagnostics"]["requested"] == str(drc_diagnostics.resolve())
    assert payload["artifacts"]["drc_diagnostics"]["generated"] is None
    assert payload["drc"]["ran"] is False
    assert payload["drc"]["pass"] is False
    assert payload["drc_source_coverage"] == {
        "violation_count": 0,
        "unconnected_count": 0,
        "attributed_violation_count": 0,
        "unattributed_violation_count": 0,
        "attributed_unconnected_count": 0,
        "unattributed_unconnected_count": 0,
        "pass": True,
        "violation_source_kinds": {},
        "unconnected_source_kinds": {},
    }
    assert payload["layer_roles"] == {
        "count": 4,
        "layers": {
            "B.Cu": "signal",
            "F.Cu": "signal",
            "In1.Cu": "power_plane",
            "In2.Cu": "ground_reference",
        },
        "role_buckets": {
            "ground_reference": ["In2.Cu"],
            "power_plane": ["In1.Cu"],
            "signal": ["B.Cu", "F.Cu"],
        },
    }
    assert payload["validation"] == {
        "count": 1,
        "kinds": ["power_on"],
        "names": ["power_on_3v3"],
    }
    assert payload["bom_state"] == {
        "excepted_count": 0,
        "excepted_refs": [],
        "mapped_count": 0,
        "mapped_refs": [],
        "missing_count": 1,
        "missing_refs": ["J1"],
        "part_count": 1,
        "pass": False,
    }
    assert payload["assembly_plan"] == {
        "configured": False,
        "component_count": 1,
        "assigned_count": 0,
        "missing_count": 1,
        "unknown_ref_count": 0,
        "method_counts": {},
        "missing_refs": ["J1"],
        "unknown_refs": [],
        "refs_by_method": {},
        "pass": True,
    }
    assert payload["physical_residuals"] == {
        "component_placement": {
            "placed_count": 1,
            "placed_refs": ["J1"],
            "total_non_helper_netlist_components": 1,
            "unplaced_count": 0,
            "unplaced_refs": [],
            "unused_placement_count": 0,
            "unused_placement_refs": [],
        },
        "physical_intent_nets": {
            "routes": {"missing_count": 0, "missing_from_netlist": []},
            "testpoints": {"missing_count": 0, "missing_from_netlist": []},
            "validation_tests": {"missing_count": 0, "missing_from_netlist": []},
        },
    }
    assert payload["footprint_state"] == {
        "checked_count": 1,
        "matched_count": 1,
        "mismatch_count": 0,
        "mismatches": [],
        "missing_spec_count": 0,
        "missing_spec_refs": [],
        "pass": True,
        "unused_spec_count": 0,
        "unused_spec_refs": [],
    }
    assert payload["source_handoff"] == {
        "kind": "netlist",
        "format": "kicad_sexpr_netlist",
        "netlist": str(netlist.resolve()),
        "netlist_exists": True,
        "component_count": 1,
        "net_count": 1,
        "physical_residual_pass": True,
        "footprint_state_pass": True,
        "pass": True,
    }
    assert payload["route_groups"] == {
        "active_route_intents": 0,
        "declared_groups": [],
        "enabled_filter": [],
        "filter_includes_ungrouped": True,
        "total_route_intents": 0,
        "route_group_intents": [],
        "ungrouped": {
            "active": True,
            "nets": [],
            "route_intent_count": 0,
            "route_names": [],
        },
    }
    assert payload["atopile_source_state"]["configured"] is False
    mechanical_features = payload["mechanical_features"]
    assert mechanical_features["board_width_mm"] == 40.0
    assert mechanical_features["board_height_mm"] == 30.0
    assert mechanical_features["fiducial_count"] == 3
    assert mechanical_features["fiducial_names"] == ["fid_1", "fid_2", "fid_3"]
    assert mechanical_features["fiducials"]["fid_1"] == {
        "x_mm": 3.0,
        "y_mm": 3.0,
        "diameter_mm": 1.0,
        "clearance_mm": None,
        "edge_margin_mm": 2.5,
        "clearance_edge_margin_mm": None,
    }
    assert mechanical_features["fiducials"]["fid_2"] == {
        "x_mm": 37.0,
        "y_mm": 3.0,
        "diameter_mm": 1.0,
        "clearance_mm": None,
        "edge_margin_mm": 2.5,
        "clearance_edge_margin_mm": None,
    }
    assert mechanical_features["fiducials"]["fid_3"] == {
        "x_mm": 37.0,
        "y_mm": 27.0,
        "diameter_mm": 1.0,
        "clearance_mm": None,
        "edge_margin_mm": 2.5,
        "clearance_edge_margin_mm": None,
    }
    assert mechanical_features["mounting_hole_count"] == 2
    assert mechanical_features["mounting_hole_names"] == ["mh_1", "mh_2"]
    assert mechanical_features["mounting_holes"]["mh_1"] == {
        "x_mm": 3.0,
        "y_mm": 27.0,
        "diameter_mm": 3.2,
        "drill_mm": 3.2,
        "edge_margin_mm": pytest.approx(1.4),
    }
    assert mechanical_features["mounting_holes"]["mh_2"] == {
        "x_mm": 33.0,
        "y_mm": 27.0,
        "diameter_mm": 3.2,
        "drill_mm": 3.2,
        "edge_margin_mm": pytest.approx(1.4),
    }
    assert mechanical_features["min_fiducial_edge_margin_mm"] == 2.5
    assert mechanical_features["min_mounting_hole_edge_margin_mm"] == pytest.approx(1.4)
    assert mechanical_features["pass"] is True
    manufacturing_geometry = payload["manufacturing_geometry"]
    assert manufacturing_geometry["trace_segment_count"] >= 0
    assert manufacturing_geometry["via_count"] >= 0
    assert manufacturing_geometry["copper_zone_count"] >= 0
    assert manufacturing_geometry["layers_used"] == sorted(set(manufacturing_geometry["layers_used"]))
    assert isinstance(manufacturing_geometry["thresholds"], dict)
    assert isinstance(manufacturing_geometry["violations"], list)
    assert manufacturing_geometry["violation_count"] == len(manufacturing_geometry["violations"])
    assert payload["pass"] is False


def test_compile_physical_build_summary_reports_bom_state_snapshot(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "R_0603") (footprint "atopile:R_0603_1608Metric"))
    (comp (ref "R2") (value "R_0603") (footprint "atopile:R_0603_1608Metric"))
    (comp (ref "R3") (value "R_0603") (footprint "atopile:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "net1")
      (node (ref "R1") (pin "1"))
      (node (ref "R2") (pin "1"))
      (node (ref "R3") (pin "1"))))
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
    at: [8mm, 10mm]
  R2:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [15mm, 10mm]
  R3:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [22mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
  lcsc_parts:
    R1: C21190
  lcsc_exceptions:
    R2: pending_sourcing
""",
        encoding="utf-8",
    )
    output = tmp_path / "out.kicad_pcb"
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["bom_state"] == {
        "excepted_count": 1,
        "excepted_refs": ["R2"],
        "mapped_count": 1,
        "mapped_refs": ["R1"],
        "missing_count": 1,
        "missing_refs": ["R3"],
        "part_count": 3,
        "pass": False,
    }
    assert payload["lcsc_policy"] == {
        "excepted": 1,
        "excepted_refs": ["R2"],
        "mapped": 1,
        "mapped_refs": ["R1"],
        "missing": 1,
        "missing_refs": ["R3"],
    }


def test_compile_physical_build_summary_reports_part_alternates(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "R_0603") (footprint "atopile:R_0603_1608Metric"))
    (comp (ref "R2") (value "R_0603") (footprint "atopile:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "net1")
      (node (ref "R1") (pin "1"))
      (node (ref "R2") (pin "1"))))
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
    at: [8mm, 10mm]
  R2:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [15mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  lcsc_alternates:
    R2:
      - C21190
      - C25804
    R9:
      - C12345
""",
        encoding="utf-8",
    )
    output = tmp_path / "out.kicad_pcb"
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["part_alternates"] == {
        "alternates_by_ref": {
            "R2": ["C21190", "C25804"],
            "R9": ["C12345"],
        },
        "declared_count": 3,
        "pass": False,
        "ref_count": 2,
        "refs": ["R2", "R9"],
        "unused_ref_count": 1,
        "unused_refs": ["R9"],
    }


def test_compile_physical_build_summary_reports_lcsc_database_snapshot(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
    (comp (ref "R2") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "net1")
      (node (ref "U1") (pin "1"))
      (node (ref "R1") (pin "1"))
      (node (ref "R2") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "jlc-components.sqlite3"
    _write_lcsc_database(db_path)

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
  R2:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [24mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_database:
    path: jlc-components.sqlite3
  lcsc_parts:
    U1: C37780947
    R1: C25804
  lcsc_alternates:
    R1:
      - C21190
""",
        encoding="utf-8",
  )
    output = tmp_path / "out.kicad_pcb"
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    lcsc_database = payload["lcsc_database"]
    assert lcsc_database["configured"] is True
    assert lcsc_database["exists"] is True
    assert lcsc_database["checked_code_count"] == 3
    assert lcsc_database["found_code_count"] == 2
    assert lcsc_database["missing_code_count"] == 1
    assert lcsc_database["missing_codes"] == ["C21190"]
    assert sorted(lcsc_database["checked_codes"]) == ["C21190", "C25804", "C37780947"]
    assert lcsc_database["codes"]["C25804"]["stock"] == 22319909
    assert lcsc_database["codes"]["C25804"]["package"] == "0603"
    assert lcsc_database["codes"]["C37780947"]["stock"] == 36


def test_compile_physical_build_summary_lcsc_codes_are_unique_and_canonical(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "U1") (value "MCU") (footprint "Package_QFP:TQFP-64_10x10mm_P0.5mm"))
    (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
    (comp (ref "R2") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))
  )
  (nets
    (net (code 1) (name "net1")
      (node (ref "U1") (pin "1"))
      (node (ref "R1") (pin "1"))
      (node (ref "R2") (pin "1"))))
)
""",
        encoding="utf-8",
    )
    db_path = tmp_path / "jlc-components.sqlite3"
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
        conn.execute(
            """
            INSERT INTO v_components (lcsc, stock, basic, preferred, package, description, price)
            VALUES ('25804', 10, 'Yes', 'No', '0603', 'Resistor', 0.01)
            """
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
  R2:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [24mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_database:
    path: jlc-components.sqlite3
  lcsc_parts:
    R1: C25804
    R2: C25804
  lcsc_alternates:
    R1:
      - C21190
""",
        encoding="utf-8",
    )
    output = tmp_path / "out.kicad_pcb"
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    lcsc_database = payload["lcsc_database"]
    assert lcsc_database["checked_codes"] == ["C21190", "C25804"]
    assert lcsc_database["checked_code_count"] == 2
    assert lcsc_database["missing_codes"] == ["C21190"]
    assert lcsc_database["missing_code_count"] == 1
    assert lcsc_database["found_code_count"] == 1
    assert sorted(lcsc_database["codes"]) == ["C25804"]


def test_compile_physical_build_summary_reports_lcsc_cost_primary_aggregation(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    netlist.write_text("""(export (version "E") (components (comp (ref "R1") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric")) (comp (ref "R2") (value "10k") (footprint "Resistor_SMD:R_0603_1608Metric"))) (nets (net (code 1) (name "net1") (node (ref "R1") (pin "1")) (node (ref "R2") (pin "1")))))""", encoding="utf-8")
    db_path = tmp_path / "jlc-components.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE v_components (lcsc TEXT PRIMARY KEY, stock INTEGER, basic TEXT, preferred TEXT, package TEXT, description TEXT, price TEXT)""")
        conn.execute("""INSERT INTO v_components (lcsc, stock, basic, preferred, package, description, price) VALUES ('C25804', 10, 'Yes', 'No', '0603', 'Resistor', '[{"qFrom":10,"qTo":99,"price":0.01}]')""")
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text("""source:\n  netlist: test.net\nboard:\n  width: 30mm\n  height: 20mm\nparts:\n  R1:\n    footprint: Resistor_SMD:R_0603_1608Metric\n    at: [18mm, 10mm]\n  R2:\n    footprint: Resistor_SMD:R_0603_1608Metric\n    at: [24mm, 10mm]\ndfm:\n  profile: jlcpcb_4_layer_smt\n  panelization:\n    mode: single_board\n  lcsc_database:\n    path: jlc-components.sqlite3\n  lcsc_cost:\n    batch_quantity: 10\n  lcsc_parts:\n    R1: C25804\n    R2: C25804\n  lcsc_alternates:\n    R1:\n      - C21190\n""", encoding="utf-8")
    build_summary = tmp_path / "mfg" / "build-summary.json"
    compile_physical(spec_path, output_path=tmp_path / "out.kicad_pcb", run_drc=False, production_check=False, build_summary_output=build_summary)
    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    cost = payload["lcsc_cost"]
    assert cost["batch_quantity"] == 10
    assert cost["line_count"] == 1
    assert cost["priced_line_count"] == 1
    assert cost["unpriced_line_count"] == 0
    assert cost["lines"]["C25804"]["ref_count"] == 2
    assert cost["lines"]["C25804"]["required_quantity"] == 20
    assert cost["lines"]["C25804"]["extended_price_usd"] == 0.2


def test_compile_physical_build_summary_reports_lcsc_availability_primary_aggregation(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export (version \"E\") (components (comp (ref \"R1\") (value \"10k\") (footprint \"Resistor_SMD:R_0603_1608Metric\")) (comp (ref \"R2\") (value \"10k\") (footprint \"Resistor_SMD:R_0603_1608Metric\")) (comp (ref \"C1\") (value \"100n\") (footprint \"Capacitor_SMD:C_0603_1608Metric\"))) (nets (net (code 1) (name \"net1\") (node (ref \"R1\") (pin \"1\")) (node (ref \"R2\") (pin \"1\")) (node (ref \"C1\") (pin \"1\")))))""",
        encoding="utf-8",
    )
    db_path = tmp_path / "jlc-components.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""CREATE TABLE v_components (lcsc TEXT PRIMARY KEY, stock INTEGER, basic TEXT, preferred TEXT, package TEXT, description TEXT, price TEXT)""")
        conn.execute(
            """INSERT INTO v_components (lcsc, stock, basic, preferred, package, description, price)
            VALUES ('25804', 15, 'Yes', 'No', '0603', 'Resistor', '[]'),
                   ('37780947', 10, 'Yes', 'No', '0603', 'Capacitor', '[]')"""
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
    path: jlc-components.sqlite3
  lcsc_cost:
    batch_quantity: 10
  lcsc_availability: {}
  lcsc_parts:
    R1: 25804
    R2: C25804
    C1: C37780947
  lcsc_alternates:
    R1:
      - 25804
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"
    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    availability = payload["lcsc_availability"]
    assert availability["configured"] is True
    assert availability["batch_quantity"] == 10
    assert availability["line_count"] == 2
    assert availability["checked_line_count"] == 2
    assert availability["shortage_line_count"] == 1
    assert availability["unknown_stock_line_count"] == 0
    assert availability["shortage_codes"] == ["C25804"]
    assert availability["lines"]["C25804"]["refs"] == ["R1", "R2"]
    assert availability["lines"]["C25804"]["ref_count"] == 2
    assert availability["lines"]["C25804"]["required_quantity"] == 20
    assert availability["lines"]["C25804"]["stock"] == 15
    assert availability["lines"]["C25804"]["shortage_quantity"] == 5
    assert availability["lines"]["C25804"]["stock_sufficient"] is False
    assert availability["lines"]["C37780947"]["required_quantity"] == 10
    assert availability["lines"]["C37780947"]["shortage_quantity"] == 0
    assert availability["lines"]["C37780947"]["stock_sufficient"] is True
    assert availability["pass"] is False


def test_compile_physical_build_summary_includes_unconfigured_lcsc_database_block(tmp_path):
    _write_basic_netlist(tmp_path / "test.net")
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
""",
        encoding="utf-8",
    )
    output = tmp_path / "out.kicad_pcb"
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["lcsc_database"] == {
        "configured": False,
        "path": None,
        "strict": False,
        "exists": False,
        "checked_codes": [],
        "checked_code_count": 0,
        "found_code_count": 0,
        "missing_codes": [],
        "missing_code_count": 0,
        "codes": {},
        "pass": True,
    }


def test_compile_physical_build_summary_includes_unconfigured_lcsc_availability_block(tmp_path):
    _write_basic_netlist(tmp_path / "test.net")
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
""",
        encoding="utf-8",
    )

    output = tmp_path / "out.kicad_pcb"
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["lcsc_availability"] == {
        "configured": False,
        "batch_quantity": None,
        "line_count": 0,
        "checked_line_count": 0,
        "shortage_line_count": 0,
        "unknown_stock_line_count": 0,
        "shortage_codes": [],
        "unknown_stock_codes": [],
        "pass": True,
        "lines": {},
    }


def test_compile_physical_build_summary_reports_atopile_source_handoff(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "atopile_default.pardal.net"
    _write_basic_netlist(netlist)
    atopile_dir = tmp_path / "atopile"
    atopile_dir.mkdir()
    ato_yaml = atopile_dir / "ato.yaml"
    ato_yaml.write_text(
        "builds:\n  default:\n    entry: main.ato:Dspic33akDevBoard\n",
        encoding="utf-8",
    )
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: atopile_default.pardal.net
  format: kicad_sexpr_netlist
  atopile:
    project: atopile
    ato_yaml: atopile/ato.yaml
    build: default
    entry: main.ato:Dspic33akDevBoard
board:
  width: 40mm
  height: 30mm
footprint_aliases:
  atopile:PinHeader_1x03_P2.54mm_Vertical: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        place_only=True,
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["source_handoff"] == {
        "kind": "atopile",
        "format": "kicad_sexpr_netlist",
        "netlist": str(netlist.resolve()),
        "netlist_exists": True,
        "component_count": 1,
        "net_count": 1,
        "physical_residual_pass": True,
        "footprint_state_pass": True,
        "pass": True,
        "atopile": {
            "project": str(atopile_dir.resolve()),
            "ato_yaml": str(ato_yaml.resolve()),
            "build": "default",
            "entry": "main.ato:Dspic33akDevBoard",
        },
    }


def test_compile_physical_build_summary_reports_unplaced_netlist_components(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_netlist_with_extra_component(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
footprint_aliases:
  atopile:PinHeader_1x03_P2.54mm_Vertical: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
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
    at: [37mm, 3mm]
  - name: fid_3
    at: [37mm, 27mm]
mounting_holes:
  - name: mh_1
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    build_summary = tmp_path / "mfg" / "build-summary.json"

    result = compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        run_drc=False,
        production_check=True,
        build_summary_output=build_summary,
    )

    unplaced_finding = next(
        entry for entry in result.production_checks if entry.code == "physical.component_unplaced"
    )
    assert unplaced_finding.message == "netlist components missing placement intent: R1"
    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["physical_residuals"]["component_placement"] == {
        "placed_count": 1,
        "placed_refs": ["J1"],
        "total_non_helper_netlist_components": 2,
        "unplaced_count": 1,
        "unplaced_refs": ["R1"],
        "unused_placement_count": 0,
        "unused_placement_refs": [],
    }
    assert payload["footprint_state"] == {
        "checked_count": 1,
        "matched_count": 1,
        "mismatch_count": 0,
        "mismatches": [],
        "missing_spec_count": 1,
        "missing_spec_refs": ["R1"],
        "pass": False,
        "unused_spec_count": 0,
        "unused_spec_refs": [],
    }
    assert payload["source_handoff"]["component_count"] == 2
    assert payload["source_handoff"]["physical_residual_pass"] is False
    assert payload["source_handoff"]["footprint_state_pass"] is False
    assert payload["source_handoff"]["pass"] is False


def test_compile_physical_build_summary_reports_footprint_state_mismatch(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    netlist.write_text(
        """(export
  (version "E")
  (components
    (comp (ref "R1") (value "1k") (footprint "atopile:R_0805_2012Metric"))
  )
  (nets
    (net (code 1) (name "NET1")
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
footprint_aliases:
  atopile:R_0805_2012Metric: Resistor_SMD:R_0805_2012Metric
  atopile:R_0603_1608Metric: Resistor_SMD:R_0603_1608Metric
parts:
  R1:
    footprint: atopile:R_0603_1608Metric
    at: [15mm, 10mm]
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["footprint_state"] == {
        "checked_count": 1,
        "matched_count": 0,
        "mismatch_count": 1,
        "mismatches": [
            {
                "ref": "R1",
                "netlist_footprint": "Resistor_SMD:R_0805_2012Metric",
                "spec_footprint": "Resistor_SMD:R_0603_1608Metric",
            }
        ],
        "missing_spec_count": 0,
        "missing_spec_refs": [],
        "pass": False,
        "unused_spec_count": 0,
        "unused_spec_refs": [],
    }


def test_compile_physical_build_summary_reports_missing_physical_intent_nets(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
routes:
  - name: orphan_route
    net: MISSING_ROUTE
testpoints:
  - name: tp_orphan
    net: MISSING_TESTPOINT
    at: [20mm, 10mm]
validation_tests:
  - name: orphan_validation
    kind: power_on
    net: MISSING_VALIDATION
    criteria: "Expect a real net."
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        place_only=True,
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["physical_residuals"]["physical_intent_nets"] == {
        "routes": {
            "missing_count": 1,
            "missing_from_netlist": ["MISSING_ROUTE"],
        },
        "testpoints": {
            "missing_count": 1,
            "missing_from_netlist": ["MISSING_TESTPOINT"],
        },
        "validation_tests": {
            "missing_count": 1,
            "missing_from_netlist": ["MISSING_VALIDATION"],
        },
    }
    assert payload["testpoint_coverage"] == {
        "declared_count": 1,
        "declared_names": ["tp_orphan"],
        "declared_nets": ["MISSING_TESTPOINT"],
        "missing_from_netlist_count": 1,
        "missing_from_netlist": ["MISSING_TESTPOINT"],
        "pass": False,
    }


def test_compile_physical_build_summary_reports_testpoint_coverage(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
testpoints:
  - name: tp_present
    net: 3V3
    at: [20mm, 10mm]
  - name: tp_dup
    net: 3V3
    at: [21mm, 10mm]
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        place_only=True,
        run_drc=False,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["testpoint_coverage"] == {
        "declared_count": 2,
        "declared_names": ["tp_dup", "tp_present"],
        "declared_nets": ["3V3"],
        "missing_from_netlist_count": 0,
        "missing_from_netlist": [],
        "pass": True,
    }


def test_compile_physical_build_summary_reports_drc_source_coverage(tmp_path, monkeypatch):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
routes:
  - name: gpio_b_rd8
    kind: deferred
    group: gpio_b
    net: 3V3
    reason: "saved for later source attribution"
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"
    drc_report = tmp_path / "mfg" / "routed-physical-drc.rpt"

    original_parse_unconnected = physical_compiler._parse_drc_unconnected
    original_parse_violations = physical_compiler._parse_drc_violations

    def fake_parse_unconnected(path, spec):
        return [
            original_parse_unconnected(
                _write_drc_report(
                    tmp_path / "synthetic-unconnected.rpt",
                    """** Found 2 unconnected pads **
[unconnected_items]: Missing connection between items
    @(49.2500 mm, 34.3375 mm): Pad 58 [3V3] of U1 on F.Cu
    @(85.0000 mm, 47.6200 mm): PTH pad 4 [3V3] of J2
[unconnected_items]: Missing connection between items
    @(10.0000 mm, 10.0000 mm): Pad 1 [MISSING] of J1 on F.Cu
    @(12.0000 mm, 10.0000 mm): Pad 2 [MISSING] of J1 on F.Cu
""",
                ),
                spec,
            )[0],
            original_parse_unconnected(
                _write_drc_report(
                    tmp_path / "synthetic-unconnected-only.rpt",
                    """** Found 1 unconnected pads **
[unconnected_items]: Missing connection between items
    @(10.0000 mm, 10.0000 mm): Pad 1 [MISSING] of J1 on F.Cu
    @(12.0000 mm, 10.0000 mm): Pad 2 [MISSING] of J1 on F.Cu
""",
                ),
                spec,
            )[0],
        ]

    def fake_parse_violations(path, spec):
        return [
            physical_compiler.DrcViolationEntry(
                code="clearance",
                title="Clearance violation",
                severity="error",
                source_reasons=[
                    physical_compiler.DrcSourceReason(
                        kind="route",
                        name="gpio_b_rd8",
                        reason="saved for later source attribution",
                        source=f"{spec_path}:9",
                    )
                ],
            ),
            physical_compiler.DrcViolationEntry(
                code="track_dangling",
                title="Track has unconnected end",
                severity="warning",
            ),
        ]

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_text("synthetic drc\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr(physical_compiler, "_parse_drc_unconnected", fake_parse_unconnected)
    monkeypatch.setattr(physical_compiler, "_parse_drc_violations", fake_parse_violations)
    monkeypatch.setattr(physical_compiler.subprocess, "run", fake_run)

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        run_drc=True,
        drc_report=drc_report,
        production_check=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["drc"]["violation_count"] == 2
    assert payload["drc"]["unconnected_count"] == 2
    assert payload["drc_source_coverage"] == {
        "violation_count": 2,
        "unconnected_count": 2,
        "attributed_violation_count": 1,
        "unattributed_violation_count": 1,
        "attributed_unconnected_count": 1,
        "unattributed_unconnected_count": 1,
        "pass": False,
        "violation_source_kinds": {"route": 1},
        "unconnected_source_kinds": {"route": 1},
    }


def test_compile_physical_build_summary_reports_route_groups_without_filter(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "route-groups.net"
    _write_route_group_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: route-groups.net
board:
  width: 40mm
  height: 30mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [25mm, 10mm]
routes:
  - name: always_on
    kind: deferred
    net: N1
    reason: "kept in every bisect slice"
  - name: gpio_a_breakout
    kind: deferred
    group: gpio_a
    net: N2
    reason: "grouped route intent"
  - name: gpio_b_breakout
    kind: deferred
    group: gpio_b
    net: N3
    reason: "grouped route intent"
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        run_drc=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["route_groups"] == {
        "active_route_intents": 3,
        "declared_groups": [
            {
                "active": True,
                "name": "gpio_a",
                "nets": ["N2"],
                "route_intent_count": 1,
                "route_names": ["gpio_a_breakout"],
            },
            {
                "active": True,
                "name": "gpio_b",
                "nets": ["N3"],
                "route_intent_count": 1,
                "route_names": ["gpio_b_breakout"],
            },
        ],
        "enabled_filter": ["gpio_a", "gpio_b"],
        "filter_includes_ungrouped": True,
        "total_route_intents": 3,
        "ungrouped": {
            "active": True,
            "nets": ["N1"],
            "route_intent_count": 1,
            "route_names": ["always_on"],
        },
    }


def test_compile_physical_build_summary_reports_route_groups_with_filter(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "route-groups.net"
    _write_route_group_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: route-groups.net
board:
  width: 40mm
  height: 30mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [25mm, 10mm]
routes:
  - name: always_on
    kind: deferred
    net: N1
    reason: "kept in every bisect slice"
  - name: gpio_a_breakout
    kind: deferred
    group: gpio_a
    net: N2
    reason: "grouped route intent"
  - name: gpio_b_breakout
    kind: deferred
    group: gpio_b
    net: N3
    reason: "grouped route intent"
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        run_drc=False,
        enabled_route_groups={"gpio_b"},
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["route_groups"] == {
        "active_route_intents": 2,
        "declared_groups": [
            {
                "active": False,
                "name": "gpio_a",
                "nets": ["N2"],
                "route_intent_count": 1,
                "route_names": ["gpio_a_breakout"],
            },
            {
                "active": True,
                "name": "gpio_b",
                "nets": ["N3"],
                "route_intent_count": 1,
                "route_names": ["gpio_b_breakout"],
            },
        ],
        "enabled_filter": ["gpio_b"],
        "filter_includes_ungrouped": True,
        "total_route_intents": 3,
        "ungrouped": {
            "active": True,
            "nets": ["N1"],
            "route_intent_count": 1,
            "route_names": ["always_on"],
        },
    }


def test_compile_physical_build_summary_reports_route_group_identity_and_provenance(tmp_path, monkeypatch):
    netlist = tmp_path / "route-group.net"
    _write_route_group_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: route-group.net
board:
  width: 40mm
  height: 30mm
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
routes:
  - name: icsp_corridor_pgcpdg
    kind: route_group
    group: gpio_b
    schema_version: 1
    description: "ICSP corridor route group"
    library:
      entry_id: icsp_corridor_placeholder
      pattern_family: icsp_corridor
      expanded_by: physical_libraries.catalog
      catalog_schema_version: 1
    net: N1
    reason: "metadata-only route group"
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"
    route_report = [
        physical_compiler.RouteReportEntry(
            net="N1",
            strategy="escape_bundle",
            segments=1,
            vias=0,
            length=12.5,
            committed=True,
            route_name="icsp_corridor_pgcpdg",
            route_index=0,
            source="board.pdl.yaml:9",
            used_layers=("F.Cu",),
            segment_layers=("F.Cu",),
            via_layers=(),
        )
    ]

    def fake_apply_routes(*args, **kwargs):
        return route_report, []

    monkeypatch.setattr(physical_compiler, "apply_routes", fake_apply_routes)
    monkeypatch.setattr(
        "pardal.kicad_sdk_writer.KiCadSDKWriter",
        lambda: type("FakeKiCadSDKWriter", (), {"write_board": staticmethod(lambda board, path: True)})(),
    )

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        run_drc=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    route_group_intent = payload["route_groups"]["route_group_intents"][0]
    assert route_group_intent["name"] == "icsp_corridor_pgcpdg"
    assert route_group_intent["route_index"] == 0
    assert route_group_intent["route_group_name"] == "icsp_corridor_pgcpdg"
    assert route_group_intent["route_group_source_kind"] == "route_group"
    assert route_group_intent["schema_version"] == 1
    assert route_group_intent["description"] == "ICSP corridor route group"
    assert route_group_intent["library_entry_id"] == "icsp_corridor_placeholder"
    assert route_group_intent["pattern_family"] == "icsp_corridor"
    assert route_group_intent["library_expanded_by"] == "physical_libraries.catalog"
    assert route_group_intent["library_catalog_schema_version"] == 1
    assert route_group_intent["source"].endswith("board.pdl.yaml:11")

    route_layer_entry = payload["route_layer_usage"]["entries"][0]
    assert route_layer_entry["net"] == "N1"
    assert route_layer_entry["strategy"] == "escape_bundle"
    assert route_layer_entry["route_name"] == "icsp_corridor_pgcpdg"
    assert route_layer_entry["route_index"] == 0
    assert route_layer_entry["route_group_name"] == "icsp_corridor_pgcpdg"
    assert route_layer_entry["route_group_source_kind"] == "route_group"
    assert route_layer_entry["schema_version"] == 1
    assert route_layer_entry["description"] == "ICSP corridor route group"
    assert route_layer_entry["library_entry_id"] == "icsp_corridor_placeholder"
    assert route_layer_entry["pattern_family"] == "icsp_corridor"
    assert route_layer_entry["library_expanded_by"] == "physical_libraries.catalog"
    assert route_layer_entry["library_catalog_schema_version"] == 1
    assert route_layer_entry["source"] == "board.pdl.yaml:9"
    assert route_layer_entry["used_layers"] == ["F.Cu"]
    assert route_layer_entry["segment_layers"] == ["F.Cu"]
    assert route_layer_entry["via_layers"] == []
    assert payload["route_source_coverage"]["unmapped_named_entries"] == []


def test_compile_physical_build_summary_reports_committed_route_layer_usage(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "route-layers.net"
    _write_route_group_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: route-layers.net
board:
  width: 40mm
  height: 30mm
  copper_layers: [F.Cu, In1.Cu, In2.Cu, B.Cu]
parts:
  U1:
    footprint: Package_QFP:TQFP-64_10x10mm_P0.5mm
    at: [10mm, 10mm]
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [25mm, 10mm]
routes:
  - name: n1_inner_route
    kind: manual_polyline
    net: N1
    layer: In1.Cu
    points:
      - [12mm, 12mm]
      - [22mm, 12mm]
""",
        encoding="utf-8",
    )
    build_summary = tmp_path / "mfg" / "build-summary.json"

    compile_physical(
        spec_path,
        output_path=tmp_path / "out.kicad_pcb",
        run_drc=False,
        build_summary_output=build_summary,
    )

    payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert payload["route_layer_usage"] == {
        "committed_entry_count": 1,
        "entries": [
            {
                "net": "N1",
                "route_index": 0,
                "route_name": "n1_inner_route",
                "segment_layers": ["In1.Cu"],
                "source": f"{spec_path}:15",
                "strategy": "manual_polyline",
                "used_layers": ["In1.Cu"],
                "via_layers": [],
            }
        ],
        "segment_nets_by_layer": {"In1.Cu": ["N1"]},
    }
    assert payload["route_source_coverage"] == {
        "committed_entry_count": 1,
        "named_entry_count": 1,
        "source_mapped_entry_count": 1,
        "unnamed_entry_count": 0,
        "unmapped_named_entry_count": 0,
        "unmapped_named_entries": [],
        "strategy_counts": {"manual_polyline": 1},
        "pass": True,
    }


def test_compile_physical_writes_manufacturing_archive_with_current_run_outputs(
    monkeypatch, tmp_path
):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  required_artifacts:
    - mfg/bom.csv
    - mfg/pnp.csv
    - mfg/jlc_bom.csv
    - mfg/jlc_pnp.csv
    - mfg/routed-physical-drc.rpt
    - mfg/drc-diagnostics.json
    - mfg/production-checks.json
    - mfg/build-summary.json
    - mfg/manufacturing-package.zip
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
    at: [37mm, 3mm]
  - name: fid_3
    at: [37mm, 27mm]
mounting_holes:
  - name: mh_1
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    output = tmp_path / "out.kicad_pcb"
    mfg = tmp_path / "mfg"
    bom = mfg / "bom.csv"
    pnp = mfg / "pnp.csv"
    jlc_bom = mfg / "jlc_bom.csv"
    jlc_pnp = mfg / "jlc_pnp.csv"
    drc_report = mfg / "routed-physical-drc.rpt"
    production_report = mfg / "production-checks.json"
    drc_diagnostics = mfg / "drc-diagnostics.json"
    build_summary = mfg / "build-summary.json"
    manufacturing_archive = mfg / "manufacturing-package.zip"
    validation_template = mfg / "validation-results.template.json"
    gerbers = mfg / "gerbers"
    drill = mfg / "drill"

    def fake_export_gerbers(board_path: Path, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "top.gbr").write_text("G04 gerber\n", encoding="utf-8")

    def fake_export_drill(board_path: Path, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "board.drl").write_text("M48\n", encoding="utf-8")

    def fake_run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_text("DRC report\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(physical_compiler, "export_gerbers", fake_export_gerbers)
    monkeypatch.setattr(physical_compiler, "export_drill", fake_export_drill)
    monkeypatch.setattr(physical_compiler.subprocess, "run", fake_run)

    result = compile_physical(
        spec_path,
        output_path=output,
        run_drc=True,
        production_check=True,
        drc_report=drc_report,
        bom_output=bom,
        pnp_output=pnp,
        jlc_bom_output=jlc_bom,
        jlc_pnp_output=jlc_pnp,
        gerber_output_dir=gerbers,
        drill_output_dir=drill,
        production_report=production_report,
        production_report_format="json",
        drc_diagnostics_report=drc_diagnostics,
        drc_diagnostics_format="json",
        build_summary_output=build_summary,
        manufacturing_archive_output=manufacturing_archive,
    )

    assert result.production_checks == []
    archive_payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert archive_payload["pass"] is True
    assert (
        archive_payload["artifacts"]["manufacturing_archive"]["generated"]
        == str(manufacturing_archive.resolve())
    )
    assert (
        archive_payload["artifacts"]["validation_results_template"]["generated"]
        == str(validation_template.resolve())
    )
    assert archive_payload["validation_results_template"] == {
        "generated": True,
        "names": ["power_on_3v3"],
        "pass": True,
        "path": str(validation_template.resolve()),
        "status": "template",
        "test_count": 1,
    }
    template_payload = json.loads(validation_template.read_text(encoding="utf-8"))
    assert template_payload["status"] == "template"
    assert template_payload["results"][0]["status"] == "not_run"
    assert template_payload["results"][0]["name"] == "power_on_3v3"
    assert template_payload["results"][0]["kind"] == "power_on"

    with zipfile.ZipFile(manufacturing_archive) as archive:
        members = set(archive.namelist())
        assert {
            "bom.csv",
            "pnp.csv",
            "jlc_bom.csv",
            "jlc_pnp.csv",
            "drc-report.rpt",
            "drc-diagnostics.json",
            "production-report.json",
            "build-summary.json",
            "validation-results.template.json",
            "gerbers/top.gbr",
            "drill/board.drl",
        }.issubset(members)
        assert archive.read("build-summary.json").decode("utf-8") == build_summary.read_text(
            encoding="utf-8"
        )
        assert archive.read("production-report.json").decode("utf-8") == production_report.read_text(
            encoding="utf-8"
        )


def test_compile_physical_manufacturing_archive_rejects_empty_source_directory(
    monkeypatch, tmp_path
):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  required_artifacts:
    - mfg/bom.csv
    - mfg/gerbers
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
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    output = tmp_path / "out.kicad_pcb"
    bom = tmp_path / "mfg" / "bom.csv"
    gerbers = tmp_path / "mfg" / "gerbers"
    manufacturing_archive = tmp_path / "mfg" / "manufacturing-package.zip"

    def fake_export_gerbers(board_path: Path, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(physical_compiler, "export_gerbers", fake_export_gerbers)

    with pytest.raises(RuntimeError, match="manufacturing archive source directory is empty: gerbers"):
        compile_physical(
            spec_path,
            output_path=output,
            run_drc=False,
            production_check=False,
            bom_output=bom,
            gerber_output_dir=gerbers,
            manufacturing_archive_output=manufacturing_archive,
        )


def test_compile_physical_writes_minimal_bom_and_pnp_csv(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  required_artifacts:
    - mfg/bom.csv
    - mfg/pnp.csv
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
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    output = tmp_path / "out.kicad_pcb"
    bom = tmp_path / "mfg" / "bom.csv"
    pnp = tmp_path / "mfg" / "pnp.csv"

    result = compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
        bom_output=bom,
        pnp_output=pnp,
    )

    assert result.production_checks == []
    assert bom.exists()
    assert pnp.exists()
    bom_lines = bom.read_text(encoding="utf-8").strip().splitlines()
    pnp_lines = pnp.read_text(encoding="utf-8").strip().splitlines()
    assert bom_lines[0] == "ref,value,footprint,layer"
    assert "J1,PWR,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical,F.Cu" in bom_lines
    assert pnp_lines[0] == "ref,x_mm,y_mm,rotation_deg,side,footprint"
    assert "J1,10.0000,10.0000,0.00,top,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical" in pnp_lines


def test_compile_physical_jlc_profile_requires_required_artifacts_contract(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
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
    at: [37mm, 3mm]
  - name: fid_3
    at: [37mm, 27mm]
mounting_holes:
  - name: mh_1
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    output = tmp_path / "out.kicad_pcb"

    result = compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
    )

    codes = {entry.code for entry in result.production_checks}
    assert "dfm.artifact_contract_missing" in codes


def test_compile_physical_writes_normalized_jlc_bom_and_pnp_csv(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
    rotation: 45
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  required_artifacts:
    - mfg/jlc_bom.csv
    - mfg/jlc_pnp.csv
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
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    output = tmp_path / "out.kicad_pcb"
    jlc_bom = tmp_path / "mfg" / "jlc_bom.csv"
    jlc_pnp = tmp_path / "mfg" / "jlc_pnp.csv"

    result = compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
        jlc_bom_output=jlc_bom,
        jlc_pnp_output=jlc_pnp,
    )

    assert result.production_checks == []
    bom_lines = jlc_bom.read_text(encoding="utf-8").strip().splitlines()
    pnp_lines = jlc_pnp.read_text(encoding="utf-8").strip().splitlines()
    assert bom_lines[0] == "Designator,Comment,Footprint,LCSC Part #"
    assert (
        "J1,PWR,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical,"
        in bom_lines
    )
    assert pnp_lines[0] == "Designator,Mid X,Mid Y,Layer,Rotation"
    assert "J1,10.0000mm,10.0000mm,Top,45.00" in pnp_lines


def test_compile_physical_jlc_bom_includes_mapped_lcsc_part_numbers(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_parts:
    J1: C124375
  required_artifacts:
    - mfg/jlc_bom.csv
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
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
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
    output = tmp_path / "out.kicad_pcb"
    jlc_bom = tmp_path / "mfg" / "jlc_bom.csv"

    result = compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
        jlc_bom_output=jlc_bom,
    )

    assert result.production_checks == []
    bom_lines = jlc_bom.read_text(encoding="utf-8").strip().splitlines()
    assert bom_lines[0] == "Designator,Comment,Footprint,LCSC Part #"
    assert (
        "J1,PWR,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical,C124375"
        in bom_lines
    )


def test_compile_physical_export_helper_inclusion_policy_controls_csv_outputs(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  required_artifacts:
    - mfg/bom.csv
    - mfg/pnp.csv
    - mfg/jlc_bom.csv
    - mfg/jlc_pnp.csv
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
    at: [3mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
  - name: mh_2
    at: [33mm, 27mm]
    diameter: 3.2mm
    drill: 3.2mm
""",
        encoding="utf-8",
    )
    output = tmp_path / "out.kicad_pcb"

    bom_with = tmp_path / "mfg" / "with_helpers_bom.csv"
    pnp_with = tmp_path / "mfg" / "with_helpers_pnp.csv"
    jlc_bom_with = tmp_path / "mfg" / "with_helpers_jlc_bom.csv"
    jlc_pnp_with = tmp_path / "mfg" / "with_helpers_jlc_pnp.csv"
    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
        bom_output=bom_with,
        pnp_output=pnp_with,
        jlc_bom_output=jlc_bom_with,
        jlc_pnp_output=jlc_pnp_with,
        include_helpers_in_exports=True,
    )

    bom_without = tmp_path / "mfg" / "without_helpers_bom.csv"
    pnp_without = tmp_path / "mfg" / "without_helpers_pnp.csv"
    jlc_bom_without = tmp_path / "mfg" / "without_helpers_jlc_bom.csv"
    jlc_pnp_without = tmp_path / "mfg" / "without_helpers_jlc_pnp.csv"
    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        production_check=True,
        bom_output=bom_without,
        pnp_output=pnp_without,
        jlc_bom_output=jlc_bom_without,
        jlc_pnp_output=jlc_pnp_without,
        include_helpers_in_exports=False,
    )

    with_helpers = (
        bom_with.read_text(encoding="utf-8")
        + pnp_with.read_text(encoding="utf-8")
        + jlc_bom_with.read_text(encoding="utf-8")
        + jlc_pnp_with.read_text(encoding="utf-8")
    )
    without_helpers = (
        bom_without.read_text(encoding="utf-8")
        + pnp_without.read_text(encoding="utf-8")
        + jlc_bom_without.read_text(encoding="utf-8")
        + jlc_pnp_without.read_text(encoding="utf-8")
    )

    for helper_ref in ("TP1", "FID1", "FID2", "FID3", "MH1", "MH2"):
        assert helper_ref in bom_with.read_text(encoding="utf-8")
        assert helper_ref in pnp_with.read_text(encoding="utf-8")
        assert helper_ref not in bom_without.read_text(encoding="utf-8")
        assert helper_ref not in pnp_without.read_text(encoding="utf-8")
        assert helper_ref not in jlc_bom_with.read_text(encoding="utf-8")
        assert helper_ref not in jlc_pnp_with.read_text(encoding="utf-8")
        assert helper_ref not in jlc_bom_without.read_text(encoding="utf-8")
        assert helper_ref not in jlc_pnp_without.read_text(encoding="utf-8")
        assert helper_ref not in without_helpers
    assert "J1" in with_helpers
    assert "J1" in without_helpers


def test_part_value_override_appears_in_jlc_bom_comment(tmp_path):
    pytest.importorskip("pcbnew")
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
  width: 30mm
  height: 20mm
parts:
  R1:
    footprint: Resistor_SMD:R_0603_1608Metric
    at: [15mm, 10mm]
    value: "1k"
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
  lcsc_policy: require_or_exception
  lcsc_exceptions:
    R1: pending_sourcing
""",
        encoding="utf-8",
    )
    output = tmp_path / "out.kicad_pcb"
    jlc_bom = tmp_path / "jlc_bom.csv"

    compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        jlc_bom_output=jlc_bom,
    )

    content = jlc_bom.read_text(encoding="utf-8")
    assert "Designator,Comment,Footprint,LCSC Part #" in content
    assert "R1,1k," in content


def test_compile_physical_writes_route_diagnostics_on_success(tmp_path):
    pytest.importorskip("pcbnew")
    netlist = tmp_path / "test.net"
    _write_basic_netlist(netlist)
    spec_path = tmp_path / "board.pdl.yaml"
    spec_path.write_text(
        """source:
  netlist: test.net
board:
  width: 40mm
  height: 30mm
  copper_layers: [F.Cu, In1.Cu, In2.Cu, B.Cu]
parts:
  J1:
    footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
    at: [10mm, 10mm]
dfm:
  profile: jlcpcb_4_layer_smt
  panelization:
    mode: single_board
""",
        encoding="utf-8",
    )
    output = tmp_path / "out.kicad_pcb"
    route_diagnostics = tmp_path / "mfg" / "route-diagnostics.json"
    build_summary = tmp_path / "mfg" / "build-summary.json"

    result = compile_physical(
        spec_path,
        output_path=output,
        run_drc=False,
        route_diagnostics_report=route_diagnostics,
        build_summary_output=build_summary,
    )

    assert result.output == output
    assert route_diagnostics.exists()
    route_payload = json.loads(route_diagnostics.read_text(encoding="utf-8"))
    summary_payload = json.loads(build_summary.read_text(encoding="utf-8"))
    assert route_payload == {
        "failed_candidate_count": 0,
        "failures": [],
        "strict_aborted": True,
        "violation_count": 0,
    }
    assert summary_payload["artifacts"]["route_diagnostics"]["requested"] == str(
        route_diagnostics.resolve()
    )
    assert summary_payload["artifacts"]["route_diagnostics"]["generated"] == str(
        route_diagnostics.resolve()
    )
