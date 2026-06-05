from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pardal import cli as cli_module
from pardal.routing_dsl import backend_adapter as backend_adapter_module
from pardal.routing_dsl import mojo_bridge as mojo_bridge_module
from pardal.routing_dsl import route_plan as route_plan_module
from pardal.routing_dsl.board_ir import load_board_ir
from pardal.routing_dsl.board_ir_producer import produce_board_ir
from pardal.routing_dsl.candidate_schema import load_route_candidates
from pardal.routing_dsl import diagnostics as diagnostics_module
from pardal.routing_dsl.oracle import route_oracle_report_to_route_diagnostics
from pardal.routing_dsl.source import load_routes_source


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _run_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["pardal", *args])
    code = cli_module.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_route_dsl_help_exposes_group_and_subcommands(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["pardal", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        cli_module.main()
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "route-dsl" in out

    monkeypatch.setattr(sys, "argv", ["pardal", "route-dsl", "--help"])
    with pytest.raises(SystemExit) as excinfo:
        cli_module.main()
    assert excinfo.value.code == 0
    nested = capsys.readouterr().out
    assert "board-ir" in nested
    assert "plan" in nested
    assert "candidates" in nested
    assert "apply" in nested
    assert "diagnostics" in nested
    assert "check" in nested


def test_route_dsl_board_ir_writes_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    output = tmp_path / "board.ir.json"
    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "board-ir",
        str(FIXTURES / "board_ir_source.json"),
        "-o",
        str(output),
    )

    assert code == 0
    assert err == ""
    assert "Wrote" in out
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8")) == produce_board_ir(FIXTURES / "board_ir_source.json").payload


def test_route_dsl_plan_writes_route_plan_and_artifact(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    board_output = FIXTURES / "board.ir.json"
    route_plan_output = tmp_path / "route-plan.ir.json"
    artifact_output = tmp_path / "capability-report.json"

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "plan",
        str(FIXTURES / "route-plan-source.pdl.yaml"),
        str(board_output),
        str(FIXTURES / "backend_manifest_supported.json"),
        "--route-plan-output",
        str(route_plan_output),
        "--artifact-output",
        str(artifact_output),
    )

    assert code == 0
    assert err == ""
    assert "Wrote" in out
    plan = route_plan_module.resolve_route_plan(
        load_routes_source(FIXTURES / "route-plan-source.pdl.yaml"),
        load_board_ir(board_output),
    )
    assert route_plan_module.normalize_route_plan_payload(route_plan_output) == route_plan_module.normalize_route_plan_payload(plan)
    capability = json.loads(artifact_output.read_text(encoding="utf-8"))
    assert capability["supported"] is True
    assert capability["failure_count"] == 0


def test_route_dsl_plan_creates_nested_output_dirs(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    board_output = FIXTURES / "board.ir.json"
    route_plan_output = tmp_path / "nested" / "plan" / "route-plan.ir.json"
    artifact_output = tmp_path / "nested" / "artifact" / "capability-report.json"

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "plan",
        str(FIXTURES / "route-plan-source.pdl.yaml"),
        str(board_output),
        str(FIXTURES / "backend_manifest_supported.json"),
        "--route-plan-output",
        str(route_plan_output),
        "--artifact-output",
        str(artifact_output),
    )

    assert code == 0
    assert err == ""
    assert route_plan_output.exists()
    assert artifact_output.exists()
    assert "Wrote" in out


def test_route_dsl_candidates_writes_validated_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    board_output = FIXTURES / "board.ir.json"
    plan = route_plan_module.resolve_route_plan(
        load_routes_source(FIXTURES / "route-plan-source.pdl.yaml"),
        load_board_ir(board_output),
    )
    route_plan_output = tmp_path / "route-plan.ir.json"
    route_plan_output.write_text(json.dumps(plan, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")

    routes_payload = json.loads((FIXTURES / "routes.json").read_text(encoding="utf-8"))
    routes_payload["route_plan_id"] = plan["route_plan_id"]
    routes_payload["route_plan_hash"] = plan["route_plan_hash"]
    routes_payload["frozen_board_snapshot_id"] = plan["frozen_board_snapshot_id"]
    routes_path = tmp_path / "routes.json"
    routes_path.write_text(json.dumps(routes_payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    output = tmp_path / "route-candidates.json"
    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "candidates",
        str(board_output),
        str(route_plan_output),
        str(FIXTURES / "backend_manifest_supported.json"),
        "--routes",
        str(routes_path),
        "-o",
        str(output),
    )

    assert code == 0
    assert err == ""
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    expected = mojo_bridge_module.convert_mojo_routes_to_route_candidates(
        mojo_bridge_module.load_mojo_routes_payload(routes_path),
        plan,
        json.loads((FIXTURES / "backend_manifest_supported.json").read_text(encoding="utf-8")),
    )
    assert load_route_candidates(payload) == load_route_candidates(expected)
    assert "Wrote" in out


def test_route_dsl_apply_writes_accepted_report(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    board_output = FIXTURES / "board.ir.json"
    plan = route_plan_module.resolve_route_plan(
        load_routes_source(FIXTURES / "route-plan-source.pdl.yaml"),
        load_board_ir(board_output),
    )
    manifest = json.loads((FIXTURES / "backend_manifest_supported.json").read_text(encoding="utf-8"))
    staged = backend_adapter_module.adapt_backend_route_output(plan, manifest)
    assert staged.kind == "route-candidates"
    candidates_path = tmp_path / "route-candidates.json"
    candidates_path.write_text(json.dumps(staged.payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    route_plan_path = tmp_path / "route-plan.ir.json"
    route_plan_path.write_text(json.dumps(plan, sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    output = tmp_path / "apply-report.json"
    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "apply",
        str(board_output),
        str(route_plan_path),
        str(candidates_path),
        "-o",
        str(output),
        "--selected-candidate-id",
        staged.payload["candidates"][0]["candidate_id"],
    )

    assert code == 0
    assert err == ""
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema"] == "pardal.route_apply_report"
    assert payload["accepted"] is True
    assert payload["generated_board_authority"] is False
    assert payload["routing_authority"] is False
    assert payload["release_authority"] is False
    assert payload["jlc_upload_authority"] is False
    assert payload["orderable_claim"] is False
    assert payload["candidate_id"] == staged.payload["candidates"][0]["candidate_id"]
    assert "Wrote" in out


def test_route_dsl_apply_can_copy_input_board_to_output_board(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    board_output = FIXTURES / "board.ir.json"
    plan = route_plan_module.resolve_route_plan(
        load_routes_source(FIXTURES / "route-plan-source.pdl.yaml"),
        load_board_ir(board_output),
    )
    manifest = json.loads((FIXTURES / "backend_manifest_supported.json").read_text(encoding="utf-8"))
    staged = backend_adapter_module.adapt_backend_route_output(plan, manifest)
    candidates_path = tmp_path / "route-candidates.json"
    candidates_path.write_text(json.dumps(staged.payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    route_plan_path = tmp_path / "route-plan.ir.json"
    route_plan_path.write_text(json.dumps(plan, sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    input_board = tmp_path / "input-board.txt"
    input_board.write_text("input-board-bytes\n", encoding="utf-8")
    output_board = tmp_path / "nested" / "output-board.txt"
    output_report = tmp_path / "apply-report.json"

    before = input_board.read_bytes()
    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "apply",
        str(board_output),
        str(route_plan_path),
        str(candidates_path),
        "-o",
        str(output_report),
        "--selected-candidate-id",
        staged.payload["candidates"][0]["candidate_id"],
        "--input-board",
        str(input_board),
        "--output-board",
        str(output_board),
    )

    assert code == 0
    assert err == ""
    assert input_board.read_bytes() == before
    assert output_board.read_bytes() == before
    payload = json.loads(output_report.read_text(encoding="utf-8"))
    assert payload["accepted"] is True
    assert payload["schema"] == "pardal.route_apply_report"
    assert payload["generated_board_authority"] is False
    assert payload["routing_authority"] is False
    assert payload["release_authority"] is False
    assert payload["jlc_upload_authority"] is False
    assert payload["orderable_claim"] is False
    assert payload["candidate_id"] == staged.payload["candidates"][0]["candidate_id"]
    assert "Wrote" in out


def test_route_dsl_example_init_and_run(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    example_dir = tmp_path / "example"

    init_code, init_out, init_err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "example",
        "init",
        "--example-dir",
        str(example_dir),
    )
    assert init_code == 0
    assert init_err == ""
    assert init_out.strip() == str(example_dir)
    assert (example_dir / "board_source.json").exists()
    assert (example_dir / "routes.pdl.yaml").exists()
    assert (example_dir / "backend_manifest.json").exists()

    run_code, run_out, run_err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "example",
        "run",
        "--example-dir",
        str(example_dir),
    )
    assert run_code == 0
    assert run_err == ""
    manifest_path = Path(run_out.strip().splitlines()[-1])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "pardal.routing_dsl_example"
    assert manifest["authority"] == {
        "generated_board_authority": False,
        "routing_authority": False,
        "release_authority": False,
        "jlc_upload_authority": False,
        "orderable_claim": False,
    }
    assert manifest["artifacts"]["apply_report"]["path"].endswith("apply-report.json")


def test_route_dsl_diagnostics_normalizes_oracle_and_preserves_false_authority_fields(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    output = tmp_path / "route-diagnostics.json"
    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "diagnostics",
        str(FIXTURES / "route-oracle-report.json"),
        "-o",
        str(output),
    )

    assert code == 0
    assert err == ""
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    expected = route_oracle_report_to_route_diagnostics(json.loads((FIXTURES / "route-oracle-report.json").read_text(encoding="utf-8")))
    assert payload == expected
    assert payload["generated_board_authority"] is False
    assert payload["routing_authority"] is False
    assert payload["release_authority"] is False
    assert payload["jlc_upload_authority"] is False
    assert payload["orderable_claim"] is False
    assert "Wrote" in out


def test_route_dsl_diagnostics_preserves_normalized_rows(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    raw_input = FIXTURES / "route-diagnostics.json"
    first_output = tmp_path / "first" / "route-diagnostics.json"
    second_output = tmp_path / "second" / "route-diagnostics.json"

    first_code, _, first_err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "diagnostics",
        str(raw_input),
        "-o",
        str(first_output),
    )
    assert first_code == 0
    assert first_err == ""
    normalized_input = json.loads(first_output.read_text(encoding="utf-8"))

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "diagnostics",
        str(first_output),
        "-o",
        str(second_output),
    )

    assert code == 0
    assert err == ""
    payload = json.loads(second_output.read_text(encoding="utf-8"))
    assert payload["rows"]
    assert payload["row_count"] == len(payload["rows"])
    assert payload["rows"] == normalized_input["rows"]
    assert "Wrote" in out


def test_route_dsl_check_rejects_invalid_artifact(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.route-plan.json"
    invalid.write_text(json.dumps({"schema": "wrong"}, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "check",
        "route-plan",
        str(invalid),
    )

    assert code == 1
    assert out == ""
    assert "Error:" in err


def test_route_dsl_check_rejects_invalid_diagnostics(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.route-diagnostics.json"
    invalid.write_text(json.dumps({"schema": "pardal.route_diagnostics", "version": "0.1", "rows": []}, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "check",
        "diagnostics",
        str(invalid),
    )

    assert code == 1
    assert out == ""
    assert "Error:" in err
