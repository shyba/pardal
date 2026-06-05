from __future__ import annotations

import json
from pathlib import Path

import pytest

from pardal.routing_dsl.backend_adapter import adapt_backend_route_output
from pardal.routing_dsl.candidate_schema import validate_route_candidates
from pardal.routing_dsl.mojo_bridge import (
    MojoBridgeError,
    build_mojo_problem_payload,
    convert_mojo_routes_to_route_candidates,
    load_mojo_problem_payload,
    load_mojo_routes_payload,
    validate_mojo_problem_payload,
    validate_mojo_routes_payload,
)
from pardal.routing_dsl.route_plan import resolve_route_plan
from pardal.routing_dsl.source import load_routes_source
from pardal.routing_dsl.board_ir import load_board_ir


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _route_plan() -> dict[str, object]:
    return resolve_route_plan(
        load_routes_source(FIXTURES / "route-plan-source.pdl.yaml"),
        load_board_ir(FIXTURES / "board.ir.json"),
    )


def _manifest() -> dict[str, object]:
    return json.loads((FIXTURES / "backend_manifest_supported.json").read_text(encoding="utf-8"))


def test_build_mojo_problem_payload_is_deterministic_and_pure() -> None:
    plan = _route_plan()
    board = load_board_ir(FIXTURES / "board.ir.json")
    manifest = _manifest()

    payload = build_mojo_problem_payload(board, plan, manifest)
    repeat = validate_mojo_problem_payload(payload)

    assert payload["schema"] == "mojo.problem"
    assert payload["backend"] == {"id": "mojo", "version": "1.0"}
    assert payload["board"]["board_ir_id"] == board.board_ir_id
    assert payload["route_plan"]["route_plan_id"] == plan["route_plan_id"]
    assert payload["problem_hash"].startswith("sha256:")
    assert repeat["problem_hash"] == payload["problem_hash"]
    assert "backend_native" not in payload["route_plan"]["route_groups"][0]


def test_convert_mojo_routes_payload_to_route_candidates_preserves_backend_debug_only() -> None:
    plan = _route_plan()
    manifest = _manifest()
    routes_payload = load_mojo_routes_payload(FIXTURES / "routes.json")
    routes_payload["route_plan_id"] = plan["route_plan_id"]
    routes_payload["route_plan_hash"] = plan["route_plan_hash"]

    payload = convert_mojo_routes_to_route_candidates(routes_payload, plan, manifest)

    assert payload["backend"] == {"id": "mojo", "version": "1.0"}
    assert validate_route_candidates(payload)["batch_hash"] == payload["batch_hash"]
    assert payload["candidates"][0]["backend_debug"]["native"]["route_id"] == "mojo-route-0001"
    assert "backend_native" not in payload["candidates"][0]
    assert all(
        field not in payload["candidates"][0]
        for field in ("generated_board_authority", "routing_authority", "release_authority", "jlc_upload_authority", "orderable_claim")
    )


def test_backend_adapter_can_stage_candidates_from_mojo_bridge_payload(monkeypatch) -> None:
    plan = _route_plan()
    manifest = _manifest()
    routes_payload = load_mojo_routes_payload(FIXTURES / "routes.json")
    routes_payload["route_plan_id"] = plan["route_plan_id"]
    routes_payload["route_plan_hash"] = plan["route_plan_hash"]
    staged = convert_mojo_routes_to_route_candidates(routes_payload, plan, manifest)

    class _Backend:
        def stage_candidates(self, route_plan, backend_manifest):
            del route_plan, backend_manifest
            return staged

    result = adapt_backend_route_output(plan, manifest, _Backend())
    assert result.kind == "route-candidates"
    assert result.payload["candidates"][0]["backend_debug"]["native"]["route_id"] == "mojo-route-0001"


def test_mojo_bridge_rejects_non_mojo_manifest() -> None:
    plan = _route_plan()
    board = load_board_ir(FIXTURES / "board.ir.json")
    manifest = {"backend": {"id": "freerouting", "version": "1.0"}, "capabilities": {}}

    with pytest.raises(MojoBridgeError, match="only supports mojo"):
        build_mojo_problem_payload(board, plan, manifest)


def test_load_mojo_payloads_round_trip_fixture_files() -> None:
    problem = load_mojo_problem_payload(FIXTURES / "problem.json")
    routes = load_mojo_routes_payload(FIXTURES / "routes.json")

    assert problem["schema"] == "mojo.problem"
    assert routes["schema"] == "mojo.routes"
