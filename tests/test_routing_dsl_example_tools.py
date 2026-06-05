from __future__ import annotations

import json
from pathlib import Path

from pardal.routing_dsl.example_tools import (
    assemble_example_workflow,
    default_example_board_source,
    default_example_routes_source,
)
from pardal.routing_dsl.board_ir_producer import produce_board_ir


def test_example_workflow_assembles_manifest(tmp_path: Path) -> None:
    example_dir = tmp_path / "example"
    board_source = default_example_board_source()
    route_plan = {
        "route_plan_id": "route-plan-1",
        "route_plan_hash": "sha256:abc",
        "frozen_board_snapshot_id": "snap-1",
        "route_groups": [{"route_group_id": "rg1"}],
    }
    result = assemble_example_workflow(
        example_dir=example_dir,
        board_source_payload=board_source,
        routes_source_payload=default_example_routes_source(),
        board_ir_payload=produce_board_ir(board_source).payload,
        route_plan_payload=route_plan,
        commands=[{"name": "board-ir", "command": ["pardal", "route-dsl", "board-ir"]}],
    )

    manifest = json.loads(result.artifact_manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "pardal.routing_dsl_example"
    assert manifest["authority"] == {
        "generated_board_authority": False,
        "routing_authority": False,
        "release_authority": False,
        "jlc_upload_authority": False,
        "orderable_claim": False,
    }
    assert manifest["counts"]["route_groups"] == 1
    assert manifest["counts"]["candidates"] == 1
    assert manifest["artifacts"]["backend_manifest"]["sha256"]
    assert manifest["artifacts"]["route_candidates"]["sha256"]
    assert manifest["artifacts"]["apply_report"]["sha256"]
    assert manifest["artifacts"]["diagnostics"]["sha256"]
    assert manifest["artifacts"]["check_report"]["sha256"]
    assert manifest["artifacts"]["board_source"]["sha256"]
    assert manifest["artifacts"]["route_plan"]["path"].endswith("route-plan.ir.json")
    assert result.board_source_path.exists()
    assert result.routes_source_path.exists()


def test_example_tooling_seeds_fresh_directory(tmp_path: Path) -> None:
    from pardal.tools import routing_dsl_example as cli_module

    example_dir = tmp_path / "fresh-example"
    code = cli_module.main(["--example-dir", str(example_dir)])
    assert code == 0
    assert (example_dir / "board_source.json").exists()
    assert (example_dir / "routes.pdl.yaml").exists()
    assert (example_dir / "backend_manifest.json").exists()
    assert (example_dir / "route-candidates.json").exists()
    assert (example_dir / "apply-report.json").exists()
    assert (example_dir / "route-diagnostics.json").exists()
    assert (example_dir / "check-report.json").exists()
