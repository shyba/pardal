import json
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

from pardal.cli import cmd_verify_production_summary, main


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


def _write_dir_with_file(path: Path, filename: str = "artifact.txt") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text("ok\n", encoding="utf-8")


def _base_payload(tmp_path: Path) -> dict:
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
        "output_board": str(board),
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
        "lcsc_policy": {
            "mapped": 0,
            "excepted": 0,
            "missing": 0,
            "mapped_refs": [],
            "excepted_refs": [],
            "missing_refs": [],
        },
        "validation_results_template": {
            "status": "template",
            "generated": True,
            "path": str(validation_template),
            "test_count": 0,
            "names": [],
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


def _materialize_summary(
    tmp_path: Path,
    *,
    payload_mutator=None,
    archive_summary_text: str | None = None,
    board_width_mm: float | None = None,
    board_height_mm: float | None = None,
    board_writer=None,
) -> Path:
    payload = _base_payload(tmp_path)
    if payload_mutator is not None:
        payload_mutator(payload)

    for artifact_name, artifact_entry in payload["artifacts"].items():
        generated = artifact_entry.get("generated")
        if generated is None or artifact_name in {"build_summary", "manufacturing_archive"}:
            continue
        artifact_path = Path(generated)
        if artifact_name == "board":
            if board_writer is not None:
                board_writer(artifact_path)
            else:
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
    source_handoff = payload.get("source_handoff")
    if isinstance(source_handoff, dict) and isinstance(source_handoff.get("netlist"), str):
        _write_file(Path(source_handoff["netlist"]))

    summary_path = Path(payload["artifacts"]["build_summary"]["generated"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    raw_summary = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    summary_path.write_text(raw_summary, encoding="utf-8")

    archive_path = Path(payload["artifacts"]["manufacturing_archive"]["generated"])
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "build-summary.json",
            raw_summary if archive_summary_text is None else archive_summary_text,
        )
        archive.writestr("bom.csv", "ok\n")

    return summary_path


def test_verify_production_summary_passes_saved_package(monkeypatch, tmp_path, capsys):
    summary_path = _materialize_summary(tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        ["pardal", "verify-production-summary", str(summary_path)],
    )

    result = main()

    captured = capsys.readouterr()
    assert result == 0
    assert json.loads(summary_path.read_text(encoding="utf-8"))["dfm_report"]["count"] == 0
    assert "PASS: fabrication-ready production summary verified" in captured.out
    assert captured.err == ""


def test_verify_production_summary_rejects_top_level_pass_false(tmp_path, capsys):
    summary_path = _materialize_summary(tmp_path, payload_mutator=lambda payload: payload.__setitem__("pass", False))

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "top-level pass flag is not true" in captured.err


def test_verify_production_summary_rejects_drc_failure_and_unconnected(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["drc"].update(
            {
                "pass": False,
                "returncode": 1,
                "violation_count": 2,
                "unconnected_count": 1,
            }
        )

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "DRC did not pass" in captured.err
    assert "DRC returncode must be 0" in captured.err
    assert "DRC violation_count must be 0" in captured.err
    assert "DRC unconnected_count must be 0" in captured.err


def test_verify_production_summary_rejects_missing_drc_source_coverage(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("drc_source_coverage"),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "drc_source_coverage must be a JSON object" in captured.err


def test_verify_production_summary_rejects_missing_route_source_coverage(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("route_source_coverage"),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "route_source_coverage must be a JSON object" in captured.err


def test_verify_production_summary_rejects_missing_footprint_state(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("footprint_state"),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "footprint_state must be a JSON object" in captured.err


def test_verify_production_summary_rejects_missing_source_handoff(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("source_handoff"),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "source_handoff must be a JSON object" in captured.err


def test_verify_production_summary_rejects_missing_atopile_source_state(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("atopile_source_state"),
    )
    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))
    captured = capsys.readouterr()
    assert result == 1
    assert "atopile_source_state must be a JSON object" in captured.err


def test_verify_production_summary_rejects_atopile_source_state_stale_contradiction(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["atopile_source_state"] = {
            "configured": True,
            "project": str(tmp_path / "atopile"),
            "ato_yaml": str(tmp_path / "atopile" / "ato.yaml"),
            "entry": "main.ato:Board",
            "netlist": str(tmp_path / "source.net"),
            "source_files": [
                {
                    "path": str(tmp_path / "atopile" / "ato.yaml"),
                    "exists": True,
                    "size_bytes": 1,
                    "sha256": "0" * 64,
                    "mtime_epoch": 20.0,
                }
            ],
            "netlist_exists": True,
            "netlist_size_bytes": 1,
            "netlist_sha256": "1" * 64,
            "netlist_mtime_epoch": 10.0,
            "newest_source_mtime_epoch": 20.0,
            "netlist_newer_or_equal": False,
            "missing_source_count": 0,
            "missing_sources": [],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))
    captured = capsys.readouterr()
    assert result == 1
    assert "atopile_source_state.pass contradicts missing source or freshness evidence" in captured.err


def test_verify_production_summary_rejects_missing_mechanical_features(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("mechanical_features"),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "mechanical_features must be a JSON object" in captured.err


def test_verify_production_summary_rejects_stale_mechanical_bbox_summary(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["mechanical_features"]["board_width_mm"] = 100.0
        payload["mechanical_features"]["board_height_mm"] = 80.0

    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=mutate,
        board_width_mm=118.0,
        board_height_mm=98.0,
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "mechanical_features.board_width_mm does not match generated board Edge.Cuts bbox" in captured.err
    assert "mechanical_features.board_height_mm does not match generated board Edge.Cuts bbox" in captured.err


def test_verify_production_summary_reads_multiline_kicad9_edge_cuts(tmp_path, capsys):
    def write_board(path: Path) -> None:
        _write_file(
            path,
            """(kicad_pcb
  (gr_line
    (start 0 0)
    (end 40 0)
    (stroke (width 0.1) (type default))
    (layer "Edge.Cuts")
    (uuid "00000000-0000-0000-0000-000000000001"))
  (gr_line
    (start 40 0)
    (end 40 30)
    (stroke (width 0.1) (type default))
    (layer "Edge.Cuts")
    (uuid "00000000-0000-0000-0000-000000000002"))
  (gr_line
    (start 40 30)
    (end 0 30)
    (stroke (width 0.1) (type default))
    (layer "Edge.Cuts")
    (uuid "00000000-0000-0000-0000-000000000003"))
  (gr_line
    (start 0 30)
    (end 0 0)
    (stroke (width 0.1) (type default))
    (layer "Edge.Cuts")
    (uuid "00000000-0000-0000-0000-000000000004"))
)
""",
        )

    summary_path = _materialize_summary(
        tmp_path,
        board_width_mm=40.0,
        board_height_mm=30.0,
        board_writer=write_board,
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""


def test_verify_production_summary_rejects_malformed_manufacturing_geometry(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["manufacturing_geometry"] = {
            "trace_segment_count": 0,
            "via_count": 0,
            "copper_zone_count": -1,
            "min_trace_width_mm": 0.2,
            "min_via_drill_mm": None,
            "min_via_diameter_mm": None,
            "layers_used": ["B.Cu", "B.Cu", "F.Cu"],
            "thresholds": {"default_clearance_mm": "bad"},
            "violations": ["foo"],
            "violation_count": 1,
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))
    captured = capsys.readouterr()
    assert result == 1
    assert "manufacturing_geometry.copper_zone_count must be >= 0" in captured.err
    assert "manufacturing_geometry.layers_used must not contain duplicates" in captured.err
    assert "manufacturing_geometry.min_trace_width_mm should be null when trace_segment_count is 0" in captured.err
    assert "manufacturing_geometry.thresholds.default_clearance_mm must be a number or null" in captured.err
    assert "manufacturing_geometry.pass is true but violation_count > 0" in captured.err


def test_verify_production_summary_rejects_malformed_mechanical_feature_counts_and_names(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["mechanical_features"] = {
            "board_width_mm": 40,
            "board_height_mm": 30,
            "fiducial_count": 3,
            "fiducial_names": ["fid_b", "fid_a"],
            "fiducials": {
                "fid_a": {
                    "x_mm": 3.0,
                    "y_mm": 3.0,
                    "diameter_mm": 1.0,
                    "edge_margin_mm": 2.5,
                },
                "fid_b": {
                    "x_mm": 37.0,
                    "y_mm": 3.0,
                    "diameter_mm": 1.0,
                    "edge_margin_mm": 2.5,
                },
            },
            "mounting_hole_count": 0,
            "mounting_hole_names": [],
            "mounting_holes": {},
            "min_fiducial_edge_margin_mm": 2.5,
            "min_mounting_hole_edge_margin_mm": None,
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "mechanical_features.fiducial_names must be sorted" in captured.err
    assert "mechanical_features.fiducial_count mismatch: 3 != len(fiducial_names)" in captured.err
    assert "mechanical_features.fiducial_names must match sorted mechanical_features.fiducials keys" in captured.err


def test_verify_production_summary_rejects_mechanical_feature_pass_contradiction(tmp_path, capsys):
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

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "mechanical_features.pass is true but one or more edge margins are negative" in captured.err


def test_verify_production_summary_rejects_source_handoff_component_count_mismatch(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["source_handoff"]["component_count"] = 2

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "source_handoff.component_count does not match" in captured.err


def test_verify_production_summary_rejects_source_handoff_missing_atopile_fields(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["source_handoff"]["kind"] = "atopile"
        payload["source_handoff"]["atopile"] = {
            "project": "",
            "ato_yaml": "atopile/ato.yaml",
            "build": "default",
            "entry": "",
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "source_handoff.atopile.project must be a non-empty string" in captured.err
    assert "source_handoff.atopile.entry must be a non-empty string" in captured.err


def test_verify_production_summary_rejects_source_handoff_contradictory_pass_states(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["physical_residuals"]["component_placement"]["unplaced_count"] = 1
        payload["physical_residuals"]["component_placement"]["unplaced_refs"] = ["R1"]
        payload["source_handoff"]["physical_residual_pass"] = True
        payload["source_handoff"]["pass"] = True

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "source_handoff.physical_residual_pass does not match physical_residuals" in captured.err
    assert "source_handoff.pass contradicts netlist/residual/footprint evidence" in captured.err


def test_verify_production_summary_rejects_footprint_state_mismatch(tmp_path, capsys):
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
            "pass": True,
            "unused_spec_count": 0,
            "unused_spec_refs": [],
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "footprint_state.pass is true but footprint discrepancies remain" in captured.err


def test_verify_production_summary_rejects_footprint_state_bad_arithmetic_and_sorting(
    tmp_path,
    capsys,
):
    def mutate(payload: dict) -> None:
        payload["footprint_state"] = {
            "checked_count": 3,
            "matched_count": 1,
            "mismatch_count": 1,
            "mismatches": [
                {
                    "ref": "R2",
                    "netlist_footprint": "Resistor_SMD:R_0603_1608Metric",
                    "spec_footprint": "Resistor_SMD:R_0805_2012Metric",
                },
                {
                    "ref": "R1",
                    "netlist_footprint": "Resistor_SMD:R_0603_1608Metric",
                    "spec_footprint": "Resistor_SMD:R_0402_1005Metric",
                },
            ],
            "missing_spec_count": 1,
            "missing_spec_refs": ["U2", "J1"],
            "pass": False,
            "unused_spec_count": 1,
            "unused_spec_refs": ["R9", "R3"],
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "footprint_state.mismatches must be sorted by ref" in captured.err
    assert "footprint_state.checked_count mismatch" in captured.err
    assert "footprint_state.missing_spec_count mismatch" in captured.err
    assert "footprint_state.unused_spec_count mismatch" in captured.err


def test_verify_production_summary_rejects_malformed_drc_source_coverage(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["drc_source_coverage"] = {
            "violation_count": 1,
            "unconnected_count": 0,
            "attributed_violation_count": 0,
            "unattributed_violation_count": 1,
            "attributed_unconnected_count": 0,
            "unattributed_unconnected_count": 0,
            "pass": True,
            "violation_source_kinds": [],
            "unconnected_source_kinds": {},
        }
        payload["drc"]["violation_count"] = 1
        payload["drc"]["pass"] = False
        payload["drc"]["returncode"] = 1

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "drc_source_coverage.violation_source_kinds must be a JSON object" in captured.err
    assert "drc_source_coverage.pass is true but unattributed DRC entries remain" in captured.err


def test_verify_production_summary_rejects_route_source_coverage_mismatch_and_sorting(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["route_source_coverage"] = {
            "committed_entry_count": 2,
            "named_entry_count": 2,
            "source_mapped_entry_count": 2,
            "unnamed_entry_count": 0,
            "unmapped_named_entry_count": 1,
            "unmapped_named_entries": [
                {
                    "net": "N2",
                    "strategy": "manual_polyline",
                    "route_name": "route_two",
                    "route_index": 1,
                },
                {
                    "net": "N1",
                    "strategy": "manual_polyline",
                    "route_name": "route_one",
                    "route_index": 0,
                },
                {
                    "net": "N1",
                    "strategy": "manual_polyline",
                    "route_name": "route_one",
                    "route_index": 0,
                },
            ],
            "strategy_counts": {"manual_polyline": 1},
            "pass": True,
        }
        payload["routes"]["committed"] = 50

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "route_source_coverage.committed_entry_count does not match routes.committed" in captured.err
    assert "route_source_coverage.strategy_counts does not sum to committed_entry_count" in captured.err
    assert "route_source_coverage.unmapped_named_entry_count mismatch" in captured.err
    assert "route_source_coverage.unmapped_named_entries must be sorted" in captured.err
    assert "route_source_coverage.unmapped_named_entries must not contain duplicates" in captured.err
    assert "route_source_coverage.pass is true but unmapped named route entries remain" in captured.err


def test_verify_production_summary_rejects_drc_source_coverage_mismatch(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["drc_source_coverage"] = {
            "violation_count": 2,
            "unconnected_count": 1,
            "attributed_violation_count": 1,
            "unattributed_violation_count": 1,
            "attributed_unconnected_count": 1,
            "unattributed_unconnected_count": 0,
            "pass": False,
            "violation_source_kinds": {"route": 1},
            "unconnected_source_kinds": {"power_stitch": 1},
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "drc_source_coverage.violation_count does not match drc.violation_count" in captured.err
    assert "drc_source_coverage.unconnected_count does not match drc.unconnected_count" in captured.err


def test_verify_production_summary_rejects_lcsc_missing_parts(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_policy"]["missing"] = 1

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "LCSC policy missing count must be 0" in captured.err


def test_verify_production_summary_rejects_missing_bom_state_block(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("bom_state"),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "bom_state must be a JSON object" in captured.err


def test_verify_production_summary_rejects_missing_part_alternates_block(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("part_alternates"),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "part_alternates must be a JSON object" in captured.err


def test_verify_production_summary_rejects_assembly_plan_mismatch(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["bom_state"]["part_count"] = 2
        payload["assembly_plan"] = {
            "configured": True,
            "component_count": 2,
            "assigned_count": 1,
            "missing_count": 0,
            "unknown_ref_count": 1,
            "method_counts": {"manual_tht": 1},
            "missing_refs": [],
            "unknown_refs": ["X1"],
            "refs_by_method": {"manual_tht": ["J1"]},
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))
    captured = capsys.readouterr()
    assert result == 1
    assert "assembly_plan.pass is true but unknown refs remain" in captured.err


def test_verify_production_summary_rejects_malformed_bom_state(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["bom_state"] = {
            "part_count": 13,
            "mapped_count": 12,
            "missing_count": 1,
            "excepted_count": 0,
            "mapped_refs": ["U1"],
            "missing_refs": ["R1"],
            "excepted_refs": [],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "bom_state.mapped_count mismatch" in captured.err
    assert "bom_state.pass is true but missing parts remain" in captured.err


def test_verify_production_summary_rejects_bom_state_lcsc_policy_mismatch(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["bom_state"]["mapped_count"] = 12
        payload["bom_state"]["part_count"] = 12

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "bom_state.mapped_count does not match lcsc_policy.mapped" in captured.err


def test_verify_production_summary_rejects_part_alternates_declared_count_mismatch(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["bom_state"] = {
            "part_count": 2,
            "mapped_count": 1,
            "missing_count": 1,
            "excepted_count": 0,
            "mapped_refs": ["R1"],
            "missing_refs": ["R2"],
            "excepted_refs": [],
            "pass": False,
        }
        payload["lcsc_policy"] = {
            "mapped": 1,
            "excepted": 0,
            "missing": 1,
            "mapped_refs": ["R1"],
            "excepted_refs": [],
            "missing_refs": ["R2"],
        }
        payload["part_alternates"] = {
            "declared_count": 3,
            "ref_count": 1,
            "refs": ["R1"],
            "alternates_by_ref": {"R1": ["C111", "C222"]},
            "unused_ref_count": 0,
            "unused_refs": [],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "part_alternates.declared_count mismatch" in captured.err


def test_verify_production_summary_rejects_part_alternates_duplicate_and_unsorted_lists(
    tmp_path, capsys
):
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
            "declared_count": 3,
            "ref_count": 1,
            "refs": ["R1"],
            "alternates_by_ref": {"R1": ["C222", "C111", "C111"]},
            "unused_ref_count": 0,
            "unused_refs": [],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "part_alternates.alternates_by_ref.R1 must be sorted" in captured.err
    assert "part_alternates.alternates_by_ref.R1 must not contain duplicates" in captured.err


def test_verify_production_summary_rejects_part_alternates_pass_true_with_unused_refs(
    tmp_path, capsys
):
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

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "part_alternates.pass is true but unused refs remain" in captured.err


def test_verify_production_summary_rejects_part_alternates_refs_key_mismatch(tmp_path, capsys):
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
            "refs": ["R1"],
            "alternates_by_ref": {"R2": ["C111"]},
            "unused_ref_count": 1,
            "unused_refs": ["R2"],
            "pass": False,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "part_alternates.refs does not match alternates_by_ref keys" in captured.err


def test_verify_production_summary_rejects_lcsc_database_count_mismatch(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_database"] = {
            "configured": True,
            "path": "/tmp/does-not-exist.sqlite3",
            "strict": True,
            "exists": False,
            "checked_codes": ["C21190", "C25804"],
            "checked_code_count": 2,
            "found_code_count": 0,
            "missing_codes": ["C21190"],
            "missing_code_count": 1,
            "codes": {},
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "lcsc_database.found_code_count + missing_code_count does not equal checked_code_count" in captured.err
    assert "lcsc_database.pass is true but missing_code_count is not 0" in captured.err


def test_verify_production_summary_rejects_invalid_lcsc_database_payload(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_database"] = {
            "configured": True,
            "path": "/tmp/local.sqlite3",
            "strict": False,
            "exists": True,
            "checked_codes": ["C-123", "C123", "C123"],
            "checked_code_count": 3,
            "found_code_count": 1,
            "missing_codes": ["X1"],
            "missing_code_count": 1,
            "codes": {
                "C123": {
                    "stock": 1,
                    "basic": 1,
                    "preferred": None,
                    "package": None,
                    "description": "ok",
                },
                "X1": {
                    "stock": 2,
                    "basic": "yes",
                    "preferred": "no",
                    "package": "0603",
                    "description": "bad-key",
                },
            },
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "lcsc_database.checked_codes contains malformed LCSC codes" in captured.err
    assert "lcsc_database.checked_codes must not contain duplicates" in captured.err
    assert "lcsc_database.codes[C123].basic must be a string or null" in captured.err


def test_verify_production_summary_rejects_duplicate_lcsc_missing_codes(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_database"] = {
            "configured": True,
            "path": "/tmp/local.sqlite3",
            "strict": True,
            "exists": True,
            "checked_codes": ["C21190", "C25804"],
            "checked_code_count": 2,
            "found_code_count": 0,
            "missing_codes": ["C21190", "C21190"],
            "missing_code_count": 2,
            "codes": {},
            "pass": False,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))
    captured = capsys.readouterr()

    assert result == 1
    assert "lcsc_database.missing_codes must not contain duplicates" in captured.err


def test_verify_production_summary_rejects_lcsc_database_missing_declared_alternate_codes(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_database"] = {
            "configured": True,
            "path": "/tmp/local.sqlite3",
            "strict": True,
            "exists": True,
            "checked_codes": ["C25804"],
            "checked_code_count": 1,
            "found_code_count": 1,
            "missing_codes": [],
            "missing_code_count": 0,
            "codes": {
                "C25804": {
                    "stock": 22319909,
                    "basic": "Yes",
                    "preferred": "No",
                    "package": "0603",
                    "description": "Resistor",
                },
            },
            "pass": True,
        }
        payload["part_alternates"] = {
            "declared_count": 1,
            "ref_count": 1,
            "refs": ["R1"],
            "alternates_by_ref": {"R1": ["C25804", "C99999"]},
            "unused_ref_count": 0,
            "unused_refs": [],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert (
        "lcsc_database.checked_codes does not include all declared alternate codes: C99999"
        in captured.err
    )


def test_verify_production_summary_rejects_invalid_lcsc_cost(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_cost"] = {
            "configured": True,
            "batch_quantity": 10,
            "line_count": 1,
            "priced_line_count": 1,
            "unpriced_line_count": 1,
            "unpriced_codes": ["C25804"],
            "estimated_batch_components_usd": 0.1,
            "estimated_unit_components_usd": 0.01,
            "pass": True,
            "lines": {"C25804": {"refs": ["R1"], "ref_count": 1, "required_quantity": 10, "unit_price_usd": 0.01, "extended_price_usd": 0.1, "selected_tier": {"qFrom": 10, "qTo": 99}, "below_minimum": False}},
        }
    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))
    captured = capsys.readouterr()
    assert result == 1
    assert "lcsc_cost.unpriced_line_count mismatch" in captured.err
    assert "lcsc_cost.unpriced_codes mismatch" in captured.err


def test_verify_production_summary_rejects_invalid_lcsc_availability_payload(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_availability"] = {
            "configured": True,
            "batch_quantity": 10,
            "line_count": 2,
            "checked_line_count": 1,
            "shortage_line_count": 0,
            "unknown_stock_line_count": 1,
            "shortage_codes": ["C25804", "C25804"],
            "unknown_stock_codes": ["C37780947"],
            "pass": True,
            "lines": {
                "C25804": {
                    "refs": ["R1"],
                    "ref_count": 1,
                    "required_quantity": 20,
                    "stock": 10,
                    "stock_sufficient": False,
                    "shortage_quantity": 10,
                },
                "C-37780947": {
                    "refs": ["C1"],
                    "ref_count": 1,
                    "required_quantity": 10,
                    "stock": None,
                    "stock_sufficient": False,
                    "shortage_quantity": 10,
                },
            },
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "lcsc_availability.checked_line_count mismatch" in captured.err
    assert "lcsc_availability.shortage_codes mismatch" in captured.err
    assert "lcsc_availability.unknown_stock_line_count mismatch" in captured.err
    assert "lcsc_availability.lines contains malformed code C-37780947" in captured.err
    assert "lcsc_availability.lines[C25804].required_quantity mismatch" in captured.err
    assert "lcsc_availability.pass is true but shortage or unknown stock exists" in captured.err


def test_verify_production_summary_rejects_unconfigured_lcsc_availability_incorrect_counts(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["lcsc_availability"] = {
            "configured": False,
            "batch_quantity": 10,
            "line_count": 2,
            "checked_line_count": 0,
            "shortage_line_count": 0,
            "unknown_stock_line_count": 0,
            "shortage_codes": [],
            "unknown_stock_codes": [],
            "pass": False,
            "lines": {
                "C25804": {
                    "refs": ["R1"],
                    "ref_count": 1,
                    "required_quantity": 10,
                    "stock": 10,
                    "stock_sufficient": True,
                    "shortage_quantity": 0,
                }
            },
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "lcsc_availability.batch_quantity must be null when not configured" in captured.err
    assert "lcsc_availability.line_count mismatch" in captured.err


def test_verify_production_summary_rejects_missing_artifact(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["artifacts"]["bom"]["generated"] = str(tmp_path / "missing.bom.csv")

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    (tmp_path / "missing.bom.csv").unlink()

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "artifact bom missing" in captured.err


def test_verify_production_summary_rejects_empty_artifact_directory(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        gerber_dir = Path(payload["artifacts"]["gerbers"]["generated"])
        gerber_dir.mkdir(parents=True, exist_ok=True)

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)
    gerber_dir = tmp_path / "gerbers"
    for child in gerber_dir.iterdir():
        child.unlink()

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "artifact gerbers directory is empty" in captured.err


def test_verify_production_summary_rejects_stale_archive_summary(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        archive_summary_text='{"pass": false}\n',
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "manufacturing archive contains a stale build-summary.json payload" in captured.err


def test_verify_production_summary_rejects_missing_testpoint_coverage_block(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.pop("testpoint_coverage"),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "testpoint_coverage must be a JSON object" in captured.err


def test_verify_production_summary_rejects_missing_declared_net_coverage(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["physical_residuals"]["physical_intent_nets"]["testpoints"] = {
            "missing_count": 1,
            "missing_from_netlist": ["MISSING_TESTPOINT"],
        }
        payload["testpoint_coverage"] = {
            "declared_count": 1,
            "declared_names": ["tp_orphan"],
            "declared_nets": ["MISSING_TESTPOINT"],
            "missing_from_netlist_count": 1,
            "missing_from_netlist": ["MISSING_TESTPOINT"],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "pass is true but missing testpoints remain" in captured.err


def test_verify_production_summary_rejects_testpoint_coverage_residual_mismatch(tmp_path, capsys):
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

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "does not match physical_residuals.physical_intent_nets.testpoints.missing_from_netlist" in captured.err


def test_verify_production_summary_rejects_mismatched_testpoint_coverage_payload(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["testpoint_coverage"] = {
            "declared_count": 2,
            "declared_names": ["tp_present"],
            "declared_nets": ["NET1"],
            "missing_from_netlist_count": 0,
            "missing_from_netlist": [],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "declared_count mismatch" in captured.err


def test_verify_production_summary_accepts_duplicate_testpoints_on_one_declared_net(tmp_path, capsys):
    def mutate(payload: dict) -> None:
        payload["testpoint_coverage"] = {
            "declared_count": 2,
            "declared_names": ["tp_a", "tp_b"],
            "declared_nets": ["3V3"],
            "missing_from_netlist_count": 0,
            "missing_from_netlist": [],
            "pass": True,
        }

    summary_path = _materialize_summary(tmp_path, payload_mutator=mutate)

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 0
    assert "PASS: fabrication-ready production summary verified" in captured.out
    assert captured.err == ""


def test_verify_production_summary_rejects_malformed_testpoint_coverage(tmp_path, capsys):
    summary_path = _materialize_summary(
        tmp_path,
        payload_mutator=lambda payload: payload.__setitem__(
            "testpoint_coverage",
            {
                "declared_count": 1,
                "declared_names": ["tp_3v3"],
                "declared_nets": ["3V3"],
                "missing_from_netlist_count": "0",
                "missing_from_netlist": ["MISSING"],
                "pass": True,
            },
        ),
    )

    result = cmd_verify_production_summary(Namespace(summary_json=summary_path))

    captured = capsys.readouterr()
    assert result == 1
    assert "missing_from_netlist_count must be an integer" in captured.err
