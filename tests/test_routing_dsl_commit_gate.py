from __future__ import annotations

import json
from pathlib import Path

import pytest

from pardal.routing_dsl.apply_candidate import apply_candidate_report
from pardal.routing_dsl.commit_gate import APPLY_REPORT_SCHEMA, validate_candidate_commit
from pardal.routing_dsl.candidate_schema import RouteCandidateSchemaError, load_route_candidates
from pardal.routing_dsl.route_plan import load_route_plan


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _fixture(name: str) -> Path:
    return FIXTURES / name


def _loaded_plan() -> dict[str, object]:
    return load_route_plan(_fixture("route-plan-source.pdl.yaml"), _fixture("board.ir.json"))


def _aligned_bridge_batch() -> dict[str, object]:
    payload = json.loads(_fixture("route-candidates.json").read_text(encoding="utf-8"))
    plan = _loaded_plan()
    payload["route_plan_id"] = plan["route_plan_id"]
    payload["route_plan_hash"] = plan["route_plan_hash"]
    payload["candidates"][0]["route_group_id"] = plan["route_groups"][0]["route_group_id"]
    payload["candidates"][1]["route_group_id"] = plan["route_groups"][0]["route_group_id"]
    for candidate in payload["candidates"]:
        candidate["patch"]["add_tracks"][0]["net"] = "SIG_A"
        candidate["patch"]["add_vias"][0]["net"] = "SIG_A"
    return payload


def test_validate_candidate_commit_accepts_bridge_emitted_candidate() -> None:
    board = _fixture("board.ir.json")
    plan = _loaded_plan()
    candidates = load_route_candidates(_aligned_bridge_batch())

    result = validate_candidate_commit(board, plan, candidates, selected_candidate_id="cand_rg_fpc_escape_a_0001")

    assert result.accepted is True
    assert result.payload["schema"] == APPLY_REPORT_SCHEMA
    assert result.payload["candidate_id"] == "cand_rg_fpc_escape_a_0001"
    assert result.payload["violations"] == []


def test_validate_candidate_commit_rejects_authority_claims() -> None:
    payload = _aligned_bridge_batch()
    payload["candidates"][1]["generated_board_authority"] = True

    with pytest.raises(RouteCandidateSchemaError, match="unknown candidate field"):
        validate_candidate_commit(_fixture("board.ir.json"), _loaded_plan(), payload, selected_candidate_id="cand_rg_fpc_escape_a_0001")


def test_validate_candidate_commit_rejects_unknown_layer_and_input_path_claim() -> None:
    payload = _aligned_bridge_batch()
    payload["candidates"][1]["patch"]["add_tracks"][0]["layer"] = "In1.Cu"

    result = validate_candidate_commit(_fixture("board.ir.json"), _loaded_plan(), payload, selected_candidate_id="cand_rg_fpc_escape_a_0001")

    assert result.accepted is False
    assert {item["code"] for item in result.payload["violations"]} >= {"forbidden_layer"}


def test_apply_candidate_report_writes_copy_only_report(tmp_path: Path) -> None:
    board = _fixture("board.ir.json")
    plan = _loaded_plan()
    candidates = load_route_candidates(_aligned_bridge_batch())
    output = tmp_path / "apply-report.json"

    payload = apply_candidate_report(board, plan, candidates, output, selected_candidate_id="cand_rg_fpc_escape_a_0001")

    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert payload["schema"] == APPLY_REPORT_SCHEMA
    assert payload["accepted"] is True
    assert payload["generated_board_authority"] is False
    assert payload["routing_authority"] is False
    assert payload["release_authority"] is False
    assert payload["jlc_upload_authority"] is False
    assert payload["orderable_claim"] is False
    assert payload["board_ir"]["frozen_board_snapshot_id"] == "board-snapshot-demo-v001"


def test_validate_candidate_commit_rejects_mismatched_route_plan_linkage() -> None:
    board = _fixture("board.ir.json")
    plan = json.loads(_fixture("route-plan.ir.json").read_text(encoding="utf-8"))
    plan["route_plan_hash"] = "sha256:deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    candidates = load_route_candidates(_fixture("route-candidates.json"))

    result = validate_candidate_commit(board, plan, candidates, selected_candidate_id="cand_rg_fpc_escape_a_0001")

    assert result.accepted is False
    assert any(item["code"] == "route_plan_hash_mismatch" for item in result.payload["violations"])
