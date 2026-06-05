from __future__ import annotations

from pathlib import Path

import json
import pytest

from pardal.routing_dsl.backend_adapter import InMemoryRouteBackend, adapt_backend_route_output
from pardal.routing_dsl.board_ir import load_board_ir
from pardal.routing_dsl.candidate_schema import validate_route_candidates
from pardal.routing_dsl.diagnostics import normalize_route_diagnostics
from pardal.routing_dsl.route_plan import resolve_route_plan
from pardal.routing_dsl.source import load_routes_source


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _load_source_board() -> tuple[object, object]:
    routes_source = load_routes_source(FIXTURES / "route-plan-source.pdl.yaml")
    board = load_board_ir(FIXTURES / "board.ir.json")
    return routes_source, board


def _manifest(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _forbid_external_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {".kicad_pcb", ".dsn", ".ses", ".gbr", ".zip"}

    from pathlib import Path as _Path

    original_read_text = _Path.read_text

    def _read_text(self, *args, **kwargs):  # pragma: no cover - narrow guard
        path = Path(self)
        if path.suffix in forbidden:
            raise AssertionError(f"unexpected file read in phase-8 smoke: {path}")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(_Path, "read_text", _read_text)


def _default_staged_payload(route_plan: dict[str, object], backend: dict[str, object]) -> dict[str, object]:
    candidates = []
    route_groups = sorted(route_plan["route_groups"], key=lambda item: str(item.get("route_group_id") or ""))
    for index, group in enumerate(route_groups):
        group_id = str(group["route_group_id"])
        candidates.append(
            {
                "candidate_id": f"cand-{group_id}-000{index}",
                "candidate_index": index,
                "route_group_id": group_id,
                "assignment_hash": str(group["assignment_hash"]),
                "assignment": {
                    "route_group_id": group_id,
                    "profile": str(backend.get("id", "")),
                },
                "patch": {
                    "remove_objects": [],
                    "move_components": [],
                    "add_tracks": [
                        {
                            "net": str(group["select"]["nets"][0]["name"]),
                            "layer": str(group["scope"]["allowed_layers"][0]["name"]),
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
                "backend_debug": {"profile": str(backend.get("id", ""))},
            }
        )
    return {
        "schema": "pardal.route_candidates",
        "version": "0.1",
        "route_plan_id": str(route_plan["route_plan_id"]),
        "route_plan_hash": str(route_plan["route_plan_hash"]),
        "frozen_board_snapshot_id": str(route_plan["frozen_board_snapshot_id"]),
        "backend": dict(backend),
        "candidates": candidates,
    }


def test_phase_8_smoke_end_to_end_resolves_plan_and_adapts_in_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_external_outputs(monkeypatch)
    routes_source, board = _load_source_board()
    route_plan = resolve_route_plan(routes_source, board)
    route_plan_repeat = resolve_route_plan(routes_source, board)
    assert route_plan == resolve_route_plan(routes_source, board)
    assert route_plan == route_plan_repeat
    assert route_plan["schema"] == "pardal.route_plan"
    assert route_plan["version"] == "0.1"
    assert route_plan["route_plan_id"].startswith("route-plan-")
    assert str(route_plan["route_plan_hash"]).startswith("sha256:")
    assert len(str(route_plan["route_plan_id"]).removeprefix("route-plan-")) == 8
    assert route_plan["board_ir_id"] == "board-ir-demo-v001"
    assert route_plan["frozen_board_snapshot_id"] == "board-snapshot-demo-v001"
    assert [g["route_group_output_id"] for g in route_plan["route_groups"]] == [
        "board-ir-demo-v001:rg_route_u1_to_j1",
        "board-ir-demo-v001:rg_route_bus",
    ]

    manifest = _manifest("backend_manifest_supported.json")
    backend_payload = _default_staged_payload(route_plan, manifest["backend"])
    backend = InMemoryRouteBackend(staged_payload=backend_payload)
    result = adapt_backend_route_output(route_plan, manifest, backend)
    prevalidated = validate_route_candidates(backend_payload)
    revalidated = validate_route_candidates(result.payload)

    assert result.kind == "route-candidates"
    candidates_payload = result.payload
    assert prevalidated["batch_hash"] == candidates_payload["batch_hash"]
    assert candidates_payload["schema"] == "pardal.route_candidates"
    assert candidates_payload["route_plan_id"] == route_plan["route_plan_id"]
    assert candidates_payload["route_plan_hash"] == route_plan["route_plan_hash"]
    assert candidates_payload["frozen_board_snapshot_id"] == route_plan["frozen_board_snapshot_id"]
    assert candidates_payload["backend"] == manifest["backend"]
    assert revalidated["batch_hash"] == candidates_payload["batch_hash"]
    assert [item["candidate_id"] for item in candidates_payload["candidates"]] == [
        "cand-rg_route_bus-0000",
        "cand-rg_route_u1_to_j1-0001",
    ]
    assert candidates_payload["batch_hash"]
    assert candidates_payload["candidates"][0]["candidate_index"] == 0
    assert candidates_payload["candidates"][1]["candidate_index"] == 1

    for candidate in candidates_payload["candidates"]:
        assert candidate["patch"]["remove_objects"] == []
        assert "committed_copper" not in candidate.get("patch", {})
        assert all(
            field not in candidate
            for field in ("generated_board_authority", "routing_authority", "release_authority", "committed_copper")
        )


def test_phase_8_smoke_negative_manifest_path_emits_normalized_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_external_outputs(monkeypatch)
    routes_source, board = _load_source_board()
    route_plan = resolve_route_plan(routes_source, board)

    manifest = _manifest("backend_manifest_limited.json")
    result = adapt_backend_route_output(route_plan, manifest)

    assert result.kind == "route-diagnostics"
    normalized = (
        result.payload
        if "rows" in result.payload and "diagnostics_hash" in result.payload
        else normalize_route_diagnostics(result.payload)
    )

    assert normalized["schema"] == "pardal.route_diagnostics"
    assert normalized["version"] == "0.1"
    assert normalized["route_plan_id"] == route_plan["route_plan_id"]
    assert normalized["generated_board_authority"] is False
    assert normalized["routing_authority"] is False
    assert normalized["release_authority"] is False
    assert normalized["jlc_upload_authority"] is False
    assert normalized["orderable_claim"] is False
    assert normalized["row_count"] == len(normalized["rows"]) >= 1
    assert {row["failed_stage"] for row in normalized["rows"]} == {"capability"}
    assert all(row["assignment_hash"] == "" for row in normalized["rows"])
    assert "unsupported_layer" in {row["code"] for row in normalized["rows"]}
    assert "unsupported_keepouts" in {row["code"] for row in normalized["rows"]}
    assert any(item["code"] == "unsupported_layer" for item in normalized["rows"])

    output = Path("/tmp") / "route-diagnostics.smoke.json"
    output.write_text(json.dumps(normalized, sort_keys=True) + "\n", encoding="utf-8")
    rendered = json.loads(output.read_text(encoding="utf-8"))
    assert rendered["schema"] == "pardal.route_diagnostics"
    assert rendered["diagnostics_hash"] == normalized["diagnostics_hash"]
    assert rendered["rows"][0]["run_id"] == normalized["run_id"]
    assert rendered["generated_board_authority"] is False
