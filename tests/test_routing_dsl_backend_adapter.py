from __future__ import annotations

import json
from pathlib import Path

import pytest

from pardal.routing_dsl.backend_adapter import (
    BackendAdapterError,
    InMemoryRouteBackend,
    adapt_backend_route_output,
)
from pardal.routing_dsl.board_ir import load_board_ir
from pardal.routing_dsl.candidate_schema import validate_route_candidates
from pardal.routing_dsl.route_plan import resolve_route_plan
from pardal.routing_dsl.source import load_routes_source


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _route_plan() -> dict[str, object]:
    plan = resolve_route_plan(
        load_routes_source(FIXTURES / "route-plan-source.pdl.yaml"),
        load_board_ir(FIXTURES / "board.ir.json"),
    )
    route_plan_id = "route-plan-8dea2d4d"
    return {
        **plan,
        "route_plan_id": route_plan_id,
        "route_plan_hash": "sha256:8dea2d4dfeedfacecafebeef0000000000000000000000000000000000000000",
    }


def _manifest(name: str = "backend_manifest_supported.json") -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_backend_adapter_returns_staged_candidates_from_in_memory_backend(monkeypatch) -> None:
    plan = _route_plan()
    manifest = _manifest()
    candidate = {
        "candidate_id": "cand_rg_route_u1_to_j1_0000",
        "candidate_index": 0,
        "route_group_id": plan["route_groups"][0]["route_group_id"],
        "assignment_hash": plan["route_groups"][0]["assignment_hash"],
        "assignment": {"route_group_id": plan["route_groups"][0]["route_group_id"]},
        "patch": {
            "remove_objects": [],
            "move_components": [],
            "add_tracks": [
                {
                    "net": "SIG_A",
                    "layer": "F.Cu",
                    "width": 0.18,
                    "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}],
                }
            ],
            "add_vias": [],
            "add_arcs": [],
            "add_zones": [],
            "set_net_ties": [],
        },
        "diagnostics": [],
        "backend_debug": {"emitted_by": "fake"},
    }
    backend = InMemoryRouteBackend(
        staged_payload={
            "schema": "pardal.route_candidates",
            "version": "0.1",
            "route_plan_id": plan["route_plan_id"],
            "route_plan_hash": plan["route_plan_hash"],
            "frozen_board_snapshot_id": plan["frozen_board_snapshot_id"],
            "backend": manifest["backend"],
            "candidates": [candidate],
        }
    )

    def _fail_on_kicad_read(self, *args, **kwargs):  # pragma: no cover - guard
        if str(self).endswith(".kicad_pcb"):
            raise AssertionError("adapter must not read .kicad_pcb files")
        return original_read_text(self, *args, **kwargs)

    from pathlib import Path as _Path

    original_read_text = _Path.read_text
    monkeypatch.setattr(_Path, "read_text", _fail_on_kicad_read)

    result = adapt_backend_route_output(plan, manifest, backend)

    assert result.kind == "route-candidates"
    payload = result.payload
    assert payload["route_plan_id"] == plan["route_plan_id"]
    assert payload["route_plan_hash"] == plan["route_plan_hash"]
    assert payload["frozen_board_snapshot_id"] == plan["frozen_board_snapshot_id"]
    assert payload["backend"] == manifest["backend"]
    assert validate_route_candidates(payload)["batch_hash"] == payload["batch_hash"]
    assert [item["route_group_id"] for item in payload["candidates"]] == [plan["route_groups"][0]["route_group_id"]]
    assert payload["candidates"][0]["backend_debug"] == {"emitted_by": "fake"}
    assert all(
        field not in payload["candidates"][0]
        for field in ("generated_board_authority", "routing_authority", "release_authority", "jlc_upload_authority", "orderable_claim")
    )


def test_backend_adapter_returns_diagnostics_for_capability_failure() -> None:
    plan = _route_plan()
    manifest = _manifest("backend_manifest_limited.json")

    result = adapt_backend_route_output(plan, manifest, InMemoryRouteBackend(staged_payload={}))

    assert result.kind == "route-diagnostics"
    payload = result.payload
    assert payload["schema"] == "pardal.route_diagnostics"
    assert payload["version"] == "0.1"
    assert payload["route_plan_id"] == plan["route_plan_id"]
    assert payload["row_count"] >= 1
    assert payload["rows"][0]["failed_stage"] == "capability"
    assert payload["rows"][0]["code"]
    assert payload["generated_board_authority"] is False
    assert payload["routing_authority"] is False
    assert payload["release_authority"] is False
    assert payload["jlc_upload_authority"] is False
    assert payload["orderable_claim"] is False


def test_backend_adapter_rejects_backend_identity_mismatch() -> None:
    plan = _route_plan()
    manifest = _manifest()
    payload = {
        "schema": "pardal.route_candidates",
        "version": "0.1",
        "route_plan_id": plan["route_plan_id"],
        "route_plan_hash": plan["route_plan_hash"],
        "frozen_board_snapshot_id": plan["frozen_board_snapshot_id"],
        "backend": {"id": "other", "version": "9.9"},
        "candidates": [],
    }

    with pytest.raises(BackendAdapterError, match="backend identity mismatch"):
        adapt_backend_route_output(plan, manifest, InMemoryRouteBackend(payload))


def test_backend_adapter_rejects_authority_claims() -> None:
    plan = _route_plan()
    manifest = _manifest()
    group_id = plan["route_groups"][0]["route_group_id"]
    payload = {
        "schema": "pardal.route_candidates",
        "version": "0.1",
        "route_plan_id": plan["route_plan_id"],
        "route_plan_hash": plan["route_plan_hash"],
        "frozen_board_snapshot_id": plan["frozen_board_snapshot_id"],
        "backend": manifest["backend"],
        "candidates": [
            {
                "candidate_id": "cand_rg_route_u1_to_j1_0000",
                "candidate_index": 0,
                "route_group_id": group_id,
                "assignment_hash": plan["route_groups"][0]["assignment_hash"],
                "assignment": {},
                "patch": {"remove_objects": [], "move_components": [], "add_tracks": [], "add_vias": [], "add_arcs": [], "add_zones": [], "set_net_ties": [], "committed_copper": True},
                "diagnostics": [],
            }
        ],
    }

    result = adapt_backend_route_output(plan, manifest, InMemoryRouteBackend(payload))
    assert result.kind == "route-diagnostics"
    assert result.payload["rows"][0]["code"] == "malformed_backend_output"
