import json
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

from pardal.cli import cmd_verify_release_package, main


def _write_file(path: Path, contents: str = "ok\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def _write_board(path: Path, *, width_mm: float, height_mm: float) -> None:
    _write_file(
        path,
        "\n".join(
            [
                "(kicad_pcb",
                '  (layer "Edge.Cuts")',
                f'  (gr_line (start 0 0) (end {width_mm} 0) (layer "Edge.Cuts") (width 0.1))',
                f'  (gr_line (start {width_mm} 0) (end {width_mm} {height_mm}) (layer "Edge.Cuts") (width 0.1))',
                f'  (gr_line (start {width_mm} {height_mm}) (end 0 {height_mm}) (layer "Edge.Cuts") (width 0.1))',
                f'  (gr_line (start 0 {height_mm}) (end 0 0) (layer "Edge.Cuts") (width 0.1))',
                ")",
                "",
            ]
        ),
    )


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_dir_with_file(path: Path, filename: str = "artifact.txt") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text("ok\n", encoding="utf-8")


def _base_summary_payload(tmp_path: Path) -> dict:
    board = tmp_path / "board.kicad_pcb"
    bom = tmp_path / "board.bom.csv"
    pnp = tmp_path / "board.pnp.csv"
    jlc_bom = tmp_path / "board.jlc.bom.csv"
    jlc_pnp = tmp_path / "board.jlc.pnp.csv"
    drc_report = tmp_path / "routed-physical-drc.rpt"
    drc_diagnostics = tmp_path / "drc-diagnostics.json"
    production_report = tmp_path / "production-checks.json"
    gerbers = tmp_path / "gerbers"
    drill = tmp_path / "drill"
    build_summary = tmp_path / "build-summary.json"
    archive = tmp_path / "manufacturing-package.zip"
    validation_template = tmp_path / "validation-results.template.json"

    return {
        "pass": True,
        "strict": {
            "requested": True,
            "route_gate_pass": True,
            "commit_violations": 0,
        },
        "routes": {
            "committed": 50,
            "total": 50,
            "probe_count": 0,
        },
        "route_source_coverage": {
            "committed_entry_count": 50,
            "named_entry_count": 50,
            "source_mapped_entry_count": 50,
            "unnamed_entry_count": 0,
            "unmapped_named_entry_count": 0,
            "unmapped_named_entries": [],
            "strategy_counts": {"manual_polyline": 50},
            "pass": True,
        },
        "drc": {
            "requested": True,
            "ran": True,
            "returncode": 0,
            "violation_count": 0,
            "unconnected_count": 0,
            "pass": True,
        },
        "drc_source_coverage": {
            "violation_count": 0,
            "unconnected_count": 0,
            "attributed_violation_count": 0,
            "unattributed_violation_count": 0,
            "attributed_unconnected_count": 0,
            "unattributed_unconnected_count": 0,
            "pass": True,
            "violation_source_kinds": {},
            "unconnected_source_kinds": {},
        },
        "production_checks": {
            "enabled": True,
            "count": 0,
            "error_count": 0,
        },
        "bom_state": {
            "part_count": 0,
            "mapped_count": 0,
            "missing_count": 0,
            "excepted_count": 0,
            "mapped_refs": [],
            "missing_refs": [],
            "excepted_refs": [],
            "pass": True,
        },
        "part_alternates": {
            "declared_count": 0,
            "ref_count": 0,
            "refs": [],
            "alternates_by_ref": {},
            "unused_ref_count": 0,
            "unused_refs": [],
            "pass": True,
        },
        "assembly_plan": {
            "configured": True,
            "component_count": 0,
            "assigned_count": 0,
            "missing_count": 0,
            "unknown_ref_count": 0,
            "method_counts": {},
            "missing_refs": [],
            "unknown_refs": [],
            "refs_by_method": {},
            "pass": True,
        },
        "dfm_report": {
            "count": 0,
            "error_count": 0,
            "warning_count": 0,
            "by_severity": {},
            "by_code": {},
        },
        "physical_residuals": {
            "component_placement": {
                "total_non_helper_netlist_components": 0,
                "placed_count": 0,
                "placed_refs": [],
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
        },
        "footprint_state": {
            "checked_count": 1,
            "matched_count": 1,
            "mismatch_count": 0,
            "mismatches": [],
            "missing_spec_count": 0,
            "missing_spec_refs": [],
            "pass": True,
            "unused_spec_count": 0,
            "unused_spec_refs": [],
        },
        "source_handoff": {
            "kind": "netlist",
            "format": "kicad_sexpr_netlist",
            "netlist": str(tmp_path / "source.net"),
            "netlist_exists": True,
            "component_count": 0,
            "net_count": 0,
            "physical_residual_pass": True,
            "footprint_state_pass": True,
            "pass": True,
        },
        "atopile_source_state": {
            "configured": False,
            "project": None,
            "ato_yaml": None,
            "entry": None,
            "netlist": str(tmp_path / "source.net"),
            "source_files": [],
            "netlist_exists": True,
            "netlist_size_bytes": 3,
            "netlist_sha256": None,
            "netlist_mtime_epoch": 1.0,
            "newest_source_mtime_epoch": None,
            "netlist_newer_or_equal": True,
            "missing_source_count": 0,
            "missing_sources": [],
            "pass": True,
        },
        "testpoint_coverage": {
            "declared_count": 1,
            "declared_names": ["tp_3v3"],
            "declared_nets": ["3V3"],
            "missing_from_netlist_count": 0,
            "missing_from_netlist": [],
            "pass": True,
        },
        "validation": {
            "count": 2,
            "kinds": ["power", "io"],
            "names": ["power_on_3v3", "gpio_sanity"],
        },
        "validation_results_template": {
            "status": "template",
            "generated": True,
            "path": str(validation_template),
            "test_count": 2,
            "names": ["gpio_sanity", "power_on_3v3"],
            "pass": True,
        },
        "lcsc_policy": {
            "mapped": 0,
            "excepted": 0,
            "missing": 0,
            "mapped_refs": [],
            "excepted_refs": [],
            "missing_refs": [],
        },
        "lcsc_database": {
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
        },
        "lcsc_availability": {
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
        },
        "mechanical_features": {
            "board_width_mm": 40.0,
            "board_height_mm": 30.0,
            "fiducial_count": 0,
            "fiducial_names": [],
            "fiducials": {},
            "mounting_hole_count": 0,
            "mounting_hole_names": [],
            "mounting_holes": {},
            "min_fiducial_edge_margin_mm": None,
            "min_mounting_hole_edge_margin_mm": None,
            "pass": True,
        },
        "manufacturing_geometry": {
            "trace_segment_count": 0,
            "via_count": 0,
            "copper_zone_count": 0,
            "min_trace_width_mm": None,
            "min_via_drill_mm": None,
            "min_via_diameter_mm": None,
            "layers_used": [],
            "thresholds": {
                "default_trace_width_mm": None,
                "default_clearance_mm": 0.2,
                "default_via_drill_mm": None,
                "default_via_diameter_mm": None,
            },
            "violations": [],
            "violation_count": 0,
            "pass": True,
        },
        "artifacts": {
            "board": {"requested": str(board), "generated": str(board)},
            "bom": {"requested": str(bom), "generated": str(bom)},
            "pnp": {"requested": str(pnp), "generated": str(pnp)},
            "jlc_bom": {"requested": str(jlc_bom), "generated": str(jlc_bom)},
            "jlc_pnp": {"requested": str(jlc_pnp), "generated": str(jlc_pnp)},
            "drc_report": {"requested": str(drc_report), "generated": str(drc_report)},
            "drc_diagnostics": {
                "requested": str(drc_diagnostics),
                "generated": str(drc_diagnostics),
            },
            "production_report": {
                "requested": str(production_report),
                "generated": str(production_report),
            },
            "gerbers": {"requested": str(gerbers), "generated": str(gerbers)},
            "drill": {"requested": str(drill), "generated": str(drill)},
            "build_summary": {
                "requested": str(build_summary),
                "generated": str(build_summary),
            },
            "manufacturing_archive": {
                "requested": str(archive),
                "generated": str(archive),
            },
            "validation_results_template": {
                "requested": str(validation_template),
                "generated": str(validation_template),
            },
        },
    }


def _manufacturing_archive_entries(summary_text: str) -> dict[str, str]:
    return {
        "build-summary.json": summary_text,
        "bom.csv": "ok\n",
        "pnp.csv": "ok\n",
        "jlc_bom.csv": "ok\n",
        "jlc_pnp.csv": "ok\n",
        "drc-report.rpt": "ok\n",
        "drc-diagnostics.json": "{}\n",
        "production-report.json": "{}\n",
        "validation-results.template.json": "{}\n",
        "gerbers/outline.gbr": "ok\n",
        "drill/drill.plated.drl": "ok\n",
    }


def _materialize_summary(
    tmp_path: Path,
    *,
    payload_mutator=None,
    archive_members: dict[str, str] | None = None,
    board_width_mm: float | None = None,
    board_height_mm: float | None = None,
) -> Path:
    payload = _base_summary_payload(tmp_path)
    if payload_mutator is not None:
        payload_mutator(payload)

    for artifact_name, artifact_entry in payload["artifacts"].items():
        generated = artifact_entry.get("generated")
        if generated is None or artifact_name in {"build_summary", "manufacturing_archive"}:
            continue
        artifact_path = Path(generated)
        if artifact_name == "board":
            _write_board(
                artifact_path,
                width_mm=board_width_mm if board_width_mm is not None else 40.0,
                height_mm=board_height_mm if board_height_mm is not None else 30.0,
            )
            continue
        if artifact_name in {"gerbers", "drill"}:
            _write_dir_with_file(artifact_path)
        else:
            _write_file(artifact_path)
    _write_file(Path(payload["source_handoff"]["netlist"]))

    summary_path = Path(payload["artifacts"]["build_summary"]["generated"])
    raw_summary = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(raw_summary, encoding="utf-8")

    archive_entry = payload["artifacts"].get("manufacturing_archive")
    if isinstance(archive_entry, dict) and archive_entry.get("generated"):
        archive_path = Path(archive_entry["generated"])
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "w") as archive:
            members = archive_members or _manufacturing_archive_entries(raw_summary)
            members = members.copy()
            if "build-summary.json" not in members:
                members["build-summary.json"] = raw_summary
            else:
                members["build-summary.json"] = raw_summary
            for name, contents in members.items():
                archive.writestr(name, contents)

    return summary_path


def _write_validation_results(tmp_path: Path, entries: list[dict[str, str]]) -> Path:
    results_path = tmp_path / "validation-results.json"
    _write_json(results_path, {"results": entries})
    return results_path


def test_verify_release_package_passes_production_only(tmp_path, capsys):
    summary_path = _materialize_summary(tmp_path)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert "PASS: release package verified" in captured.out


def test_verify_release_package_accepts_json_drc_report_member(tmp_path, capsys):
    archive_members = _manufacturing_archive_entries("placeholder\n")
    archive_members["drc-report.json"] = archive_members.pop("drc-report.rpt")
    summary_path = _materialize_summary(
        tmp_path,
        archive_members=archive_members,
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert "PASS: release package verified" in captured.out


def test_verify_release_package_rejects_missing_manufacturing_archive(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload["artifacts"].pop("manufacturing_archive", None),
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "release artifact manufacturing_archive is required" in captured.err


def test_verify_release_package_rejects_archive_missing_required_member(tmp_path, capsys):
    archive_members = _manufacturing_archive_entries("placeholder\n")
    archive_members.pop("jlc_pnp.csv")
    summary_path = _materialize_summary(
        tmp_path,
        archive_members=archive_members,
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "release manufacturing archive is missing expected member: jlc_pnp.csv" in captured.err


def test_verify_release_package_rejects_archive_missing_gerber_and_drill_prefixes(tmp_path, capsys):
    archive_members = _manufacturing_archive_entries("placeholder\n")
    archive_members.pop("gerbers/outline.gbr")
    archive_members.pop("drill/drill.plated.drl")
    summary_path = _materialize_summary(
        tmp_path,
        archive_members=archive_members,
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "release manufacturing archive is missing expected prefix member: gerbers/" in captured.err
    assert "release manufacturing archive is missing expected prefix member: drill/" in captured.err


def test_verify_release_package_rejects_jlc_bom_helper_rows(tmp_path, capsys):
    archive_members = _manufacturing_archive_entries("placeholder\n")
    archive_members["jlc_bom.csv"] = "\n".join(
        [
            "Designator,Comment,Footprint,LCSC Part #",
            "TP1,TP,TestPoint:TestPoint_Pad_1.0mm,",
            "R1,1k,Resistor_SMD:R_0603_1608Metric,C25804",
        ]
    ) + "\n"
    summary_path = _materialize_summary(
        tmp_path,
        archive_members=archive_members,
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "release jlc_bom.csv includes helper designator: TP1" in captured.err
    assert "release jlc_bom.csv includes helper footprint: TestPoint:TestPoint_Pad_1.0mm" in captured.err


def test_verify_release_package_rejects_testpoint_coverage_mismatch(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["testpoint_coverage"] = {
            "declared_count": 1,
            "declared_names": ["tp_3v3"],
            "declared_nets": ["3V3"],
            "missing_from_netlist_count": 1,
            "missing_from_netlist": ["MISSING_TESTPOINT"],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "testpoint_coverage" in captured.err


def test_verify_release_package_rejects_testpoint_residual_mismatch(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["physical_residuals"]["physical_intent_nets"]["testpoints"] = {
            "missing_count": 1,
            "missing_from_netlist": ["3V3_MISSING"],
        }
        payload["testpoint_coverage"] = {
            "declared_count": 1,
            "declared_names": ["tp_3v3"],
            "declared_nets": ["3V3_MISSING"],
            "missing_from_netlist_count": 1,
            "missing_from_netlist": ["OTHER_MISSING"],
            "pass": False,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "physical_residuals.physical_intent_nets.testpoints.missing_from_netlist" in captured.err


def test_verify_release_package_inherits_footprint_state_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["footprint_state"] = {
            "checked_count": 1,
            "matched_count": 0,
            "mismatch_count": 1,
            "mismatches": [
                {
                    "ref": "J1",
                    "netlist_footprint": "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Horizontal",
                    "spec_footprint": "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
                }
            ],
            "missing_spec_count": 0,
            "missing_spec_refs": [],
            "pass": False,
            "unused_spec_count": 0,
            "unused_spec_refs": [],
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "footprint_state" in captured.err


def test_verify_release_package_inherits_source_handoff_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["source_handoff"]["kind"] = "atopile"
        payload["source_handoff"]["atopile"] = {
            "project": "atopile",
            "ato_yaml": "",
            "build": "default",
            "entry": "main.ato:Board",
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "source_handoff.atopile.ato_yaml must be a non-empty string" in captured.err


def test_verify_release_package_inherits_atopile_source_state_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["atopile_source_state"] = {
            "configured": True,
            "project": str(tmp_path / "atopile"),
            "ato_yaml": str(tmp_path / "atopile" / "ato.yaml"),
            "entry": "main.ato:Board",
            "netlist": str(tmp_path / "source.net"),
            "source_files": [],
            "netlist_exists": True,
            "netlist_size_bytes": 1,
            "netlist_sha256": "1" * 64,
            "netlist_mtime_epoch": 10.0,
            "newest_source_mtime_epoch": None,
            "netlist_newer_or_equal": False,
            "missing_source_count": 0,
            "missing_sources": [],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )
    captured = capsys.readouterr()
    assert result == 1
    assert "atopile_source_state.pass contradicts missing source or freshness evidence" in captured.err


def test_verify_release_package_inherits_bom_state_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["bom_state"]["missing_count"] = 1
        payload["bom_state"]["missing_refs"] = ["R1"]
        payload["bom_state"]["part_count"] = 14
        payload["bom_state"]["pass"] = True

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "bom_state.pass is true but missing parts remain" in captured.err


def test_verify_release_package_inherits_part_alternates_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["bom_state"] = {
            "part_count": 1,
            "mapped_count": 1,
            "missing_count": 0,
            "excepted_count": 0,
            "mapped_refs": ["R1"],
            "missing_refs": [],
            "excepted_refs": [],
            "pass": True,
        }
        payload["lcsc_policy"] = {
            "mapped": 1,
            "excepted": 0,
            "missing": 0,
            "mapped_refs": ["R1"],
            "excepted_refs": [],
            "missing_refs": [],
        }
        payload["part_alternates"] = {
            "declared_count": 1,
            "ref_count": 1,
            "refs": ["R9"],
            "alternates_by_ref": {"R9": ["C111"]},
            "unused_ref_count": 1,
            "unused_refs": ["R9"],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "part_alternates.pass is true but unused refs remain" in captured.err


def test_verify_release_package_inherits_lcsc_database_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_database"] = {
            "configured": True,
            "path": "/tmp/local.sqlite3",
            "strict": True,
            "exists": True,
            "checked_codes": ["C25804", "C99999"],
            "checked_code_count": 2,
            "found_code_count": 1,
            "missing_codes": ["C99999"],
            "missing_code_count": 1,
            "codes": {
                "C25804": {
                    "stock": 22319909,
                    "basic": "Yes",
                    "preferred": "No",
                    "package": "0603",
                    "description": "Resistor",
                }
            },
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "lcsc_database.pass is true but missing_code_count is not 0" in captured.err


def test_verify_release_package_inherits_lcsc_cost_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_cost"] = {
            "configured": True,
            "batch_quantity": 10,
            "line_count": 1,
            "priced_line_count": 0,
            "unpriced_line_count": 0,
            "unpriced_codes": [],
            "estimated_batch_components_usd": 0.0,
            "estimated_unit_components_usd": 0.0,
            "pass": True,
            "lines": {"C25804": {"refs": ["R1"], "ref_count": 1, "required_quantity": 10, "unit_price_usd": None, "extended_price_usd": None, "selected_tier": {"qFrom": 10, "qTo": 99}, "below_minimum": False}},
        }
    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    result = cmd_verify_release_package(Namespace(summary_json=summary_path, validation_results=None))
    captured = capsys.readouterr()
    assert result == 1
    assert "lcsc_cost.unpriced_line_count mismatch" in captured.err
    assert "lcsc_cost.pass is true but unpriced_line_count is not 0" in captured.err


def test_verify_release_package_inherits_lcsc_availability_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_availability"] = {
            "configured": True,
            "batch_quantity": 10,
            "line_count": 1,
            "checked_line_count": 1,
            "shortage_line_count": 1,
            "unknown_stock_line_count": 1,
            "shortage_codes": ["C25804"],
            "unknown_stock_codes": ["C37780947"],
            "pass": True,
            "lines": {
                "C25804": {
                    "refs": ["R1"],
                    "ref_count": 1,
                    "required_quantity": 10,
                    "stock": 5,
                    "stock_sufficient": False,
                    "shortage_quantity": 5,
                },
            },
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "lcsc_availability.pass is true but shortage or unknown stock exists" in captured.err


def test_verify_release_package_inherits_drc_source_coverage_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["drc_source_coverage"] = {
            "violation_count": 1,
            "unconnected_count": 0,
            "attributed_violation_count": 0,
            "unattributed_violation_count": 1,
            "attributed_unconnected_count": 0,
            "unattributed_unconnected_count": 0,
            "pass": True,
            "violation_source_kinds": {},
            "unconnected_source_kinds": {},
        }
        payload["drc"]["violation_count"] = 1
        payload["drc"]["pass"] = False
        payload["drc"]["returncode"] = 1

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "drc_source_coverage.pass is true but unattributed DRC entries remain" in captured.err


def test_verify_release_package_inherits_route_source_coverage_gate(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["route_source_coverage"] = {
            "committed_entry_count": 1,
            "named_entry_count": 1,
            "source_mapped_entry_count": 0,
            "unnamed_entry_count": 0,
            "unmapped_named_entry_count": 1,
            "unmapped_named_entries": [
                {
                    "net": "3V3",
                    "strategy": "manual_polyline",
                    "route_name": "gpio_b_rd8",
                    "route_index": 0,
                }
            ],
            "strategy_counts": {"manual_polyline": 1},
            "pass": True,
        }
        payload["routes"]["committed"] = 1

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "route_source_coverage.pass is true but unmapped named route entries remain" in captured.err


def test_verify_release_package_propagates_production_summary_failure(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.__setitem__("pass", False),
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "ERROR: top-level pass flag is not true" in captured.err


def test_verify_release_package_rejects_mechanical_features_pass_contradiction(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["mechanical_features"] = {
            "board_width_mm": 40,
            "board_height_mm": 30,
            "fiducial_count": 1,
            "fiducial_names": ["fid_a"],
            "fiducials": {
                "fid_a": {
                    "x_mm": 0.0,
                    "y_mm": 3.0,
                    "diameter_mm": 1.0,
                    "edge_margin_mm": -0.5,
                },
            },
            "mounting_hole_count": 0,
            "mounting_hole_names": [],
            "mounting_holes": {},
            "min_fiducial_edge_margin_mm": -0.5,
            "min_mounting_hole_edge_margin_mm": None,
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "mechanical_features.pass is true but one or more edge margins are negative" in captured.err


def test_verify_release_package_rejects_stale_mechanical_bbox_summary(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["mechanical_features"]["board_width_mm"] = 100.0
        payload["mechanical_features"]["board_height_mm"] = 80.0

    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=mutate,
        board_width_mm=118.0,
        board_height_mm=98.0,
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=None)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "mechanical_features.board_width_mm does not match generated board Edge.Cuts bbox" in captured.err
    assert "mechanical_features.board_height_mm does not match generated board Edge.Cuts bbox" in captured.err


def test_verify_release_package_rejects_manufacturing_geometry_pass_contradiction(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["manufacturing_geometry"]["violations"] = ["min_trace_width_below_rules_default"]
        payload["manufacturing_geometry"]["violation_count"] = 1
        payload["manufacturing_geometry"]["pass"] = True

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    result = cmd_verify_release_package(Namespace(summary_json=summary_path, validation_results=None))
    captured = capsys.readouterr()
    assert result == 1
    assert "manufacturing_geometry.pass is true but violation_count > 0" in captured.err


def test_verify_release_package_passes_with_validation_results(tmp_path, capsys):
    summary_path = _materialize_summary(tmp_path)
    results_path = _write_validation_results(
        tmp_path,
        [
            {"name": "power_on_3v3", "status": "pass", "measured": "3.31V"},
            {"name": "gpio_sanity", "status": "pass", "measured": "1,1,0,1"},
        ],
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=results_path)
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert "PASS: release package verified" in captured.out


def test_verify_release_package_propagates_validation_failure(tmp_path, capsys):
    summary_path = _materialize_summary(tmp_path)
    results_path = _write_validation_results(
        tmp_path,
        [
            {"name": "power_on_3v3", "status": "pass"},
            {"name": "gpio_sanity", "status": "skip"},
        ],
    )

    result = cmd_verify_release_package(
        Namespace(summary_json=summary_path, validation_results=results_path)
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "ERROR: validation result did not pass: gpio_sanity -> skip" in captured.err


def test_verify_release_package_dispatches_from_main(monkeypatch, tmp_path, capsys):
    summary_path = _materialize_summary(tmp_path)
    results_path = _write_validation_results(
        tmp_path,
        [
            {"name": "power_on_3v3", "status": "pass"},
            {"name": "gpio_sanity", "status": "pass"},
        ],
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pardal",
            "verify-release-package",
            str(summary_path),
            "--validation-results",
            str(results_path),
        ],
    )

    result = main()

    captured = capsys.readouterr()
    assert result == 0
    assert "PASS: release package verified" in captured.out
    assert captured.err == ""
