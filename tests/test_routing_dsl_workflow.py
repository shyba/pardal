from __future__ import annotations

import json
from pathlib import Path

import pytest

from pardal.routing_dsl import diagnostics as diagnostics_module
from pardal.routing_dsl import route_plan as route_plan_module
from pardal.routing_dsl import workflow as workflow_module


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def test_run_route_workflow_writes_route_plan_and_capability_report(tmp_path):
    result = workflow_module.run_route_workflow(
        FIXTURES / "route-plan-source.pdl.yaml",
        FIXTURES / "board.ir.json",
        FIXTURES / "backend_manifest_supported.json",
        tmp_path,
    )

    assert result.artifact_kind == "capability-report"
    assert result.route_plan_path == tmp_path / "route-plan.ir.json"
    assert result.artifact_path == tmp_path / "capability-report.json"
    assert result.route_plan_path.exists()
    assert result.artifact_path.exists()

    route_plan_payload = json.loads(result.route_plan_path.read_text(encoding="utf-8"))
    assert route_plan_payload == result.route_plan
    assert route_plan_module.normalize_route_plan_payload(route_plan_payload) == result.route_plan
    assert route_plan_module.route_plan_hash_payload(route_plan_payload) == route_plan_module.route_plan_hash_payload(
        result.route_plan
    )

    capability_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert capability_payload["supported"] is True
    assert capability_payload["failure_count"] == 0
    assert capability_payload["failures"] == []


def test_run_route_workflow_writes_route_diagnostics_for_capability_failures(tmp_path):
    result = workflow_module.run_route_workflow(
        FIXTURES / "route-plan-source.pdl.yaml",
        FIXTURES / "board.ir.json",
        FIXTURES / "backend_manifest_limited.json",
        tmp_path,
    )

    assert result.artifact_kind == "route-diagnostics"
    assert result.artifact_path == tmp_path / "route-diagnostics.json"

    diagnostics_payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert diagnostics_payload["schema"] == "pardal.route_diagnostics"
    assert diagnostics_payload["route_plan_id"] == result.route_plan["route_plan_id"]
    assert diagnostics_payload["route_plan_hash"] == result.route_plan["route_plan_hash"]
    assert diagnostics_payload["row_count"] == len(diagnostics_payload["rows"])
    assert [row["code"] for row in diagnostics_payload["rows"]] == [
        "unsupported_keepouts",
        "unsupported_layer",
        "unsupported_layer",
    ]
    assert diagnostics_payload["rows"][0]["failed_stage"] == "capability"
    assert diagnostics_payload["generated_board_authority"] is False

    reloaded = diagnostics_module.load_route_diagnostics(result.artifact_path)
    assert reloaded == diagnostics_payload


def test_run_route_workflow_rejects_stale_route_plan_inputs(tmp_path, monkeypatch):
    route_plan = route_plan_module.resolve_route_plan(
        workflow_module.source_module.load_routes_source(FIXTURES / "route-plan-source.pdl.yaml"),
        workflow_module.board_ir_module.load_board_ir(FIXTURES / "board.ir.json"),
    )
    stale_plan = dict(route_plan)
    stale_plan["board_ir_id"] = "other-board"

    def fake_resolve_route_plan(*args, **kwargs):
        del args, kwargs
        return stale_plan

    monkeypatch.setattr(workflow_module.route_plan_module, "resolve_route_plan", fake_resolve_route_plan)

    with pytest.raises(workflow_module.StaleRoutePlanError, match="board_ir_id"):
        workflow_module.run_route_workflow(
            FIXTURES / "route-plan-source.pdl.yaml",
            FIXTURES / "board.ir.json",
            FIXTURES / "backend_manifest_supported.json",
            tmp_path,
        )


def test_load_route_plan_artifact_normalizes_and_rehashes(tmp_path):
    result = workflow_module.run_route_workflow(
        FIXTURES / "route-plan-source.pdl.yaml",
        FIXTURES / "board.ir.json",
        FIXTURES / "backend_manifest_supported.json",
        tmp_path,
    )

    loaded = workflow_module.load_route_plan_artifact(result.route_plan_path)
    assert loaded == result.route_plan
    assert loaded["route_plan_hash"] == result.route_plan["route_plan_hash"]
    assert loaded["route_plan_id"] == result.route_plan["route_plan_id"]
