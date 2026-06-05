from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pardal.routing_dsl.candidate_schema import (
    CANDIDATE_SCHEMA,
    CANDIDATE_VERSION,
    RouteCandidateSchemaError,
    load_route_candidates,
    normalize_route_candidates,
    route_candidates_to_json_payload,
    validate_route_candidates,
)


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _fixture(name: str) -> Path:
    return FIXTURES / name


def test_load_route_candidates_fixture_is_deterministic() -> None:
    payload = load_route_candidates(_fixture("route-candidates.json"))
    repeat = validate_route_candidates(json.loads(_fixture("route-candidates.json").read_text(encoding="utf-8")))
    normalized = normalize_route_candidates(payload)
    json_payload = route_candidates_to_json_payload(payload)

    assert payload == repeat
    assert normalized == payload
    assert json_payload["candidates"][0]["patch"]["add_vias"][0]["position"] == [13.0, 14.0]
    assert payload["schema"] == CANDIDATE_SCHEMA
    assert payload["version"] == CANDIDATE_VERSION
    assert payload["route_plan_id"] == "route-plan-2d6b5c1f"
    assert payload["route_plan_hash"] == "sha256:2d6b5c1f4dbd2a0f9d56f9f4a9d7ddc33f0d8da6c9d4c0f9b1b772b0e3f5c1a0"
    assert payload["backend"] == {"id": "mojo", "version": "1.0"}

    candidates = payload["candidates"]
    assert [candidate["candidate_id"] for candidate in candidates] == [
        "cand_rg_fpc_escape_a_0001",
        "cand_rg_fpc_escape_a_0002",
    ]
    assert candidates[0]["candidate_index"] == 0
    assert candidates[0]["patch"]["add_vias"][0]["position"] == (13.0, 14.0)
    assert candidates[0]["patch"]["remove_objects"] == ("trk-old-1",)
    assert candidates[0]["diagnostics"] == ("diag-routing-001",)
    assert candidates[1]["patch"]["move_components"][0]["component_id"] == "comp-j1"
    assert payload["batch_hash"].startswith("sha256:")


def test_validate_route_candidates_is_idempotent_for_raw_and_normalized_payloads() -> None:
    raw_payload = json.loads(_fixture("route-candidates.json").read_text(encoding="utf-8"))
    normalized = validate_route_candidates(raw_payload)
    repeat = validate_route_candidates(normalized)

    assert repeat == normalized
    assert repeat["batch_hash"] == normalized["batch_hash"]
    assert repeat["backend"] == {"id": "mojo", "version": "1.0"}


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.__setitem__("schema", "wrong.schema"), "schema"),
        (lambda payload: payload.__setitem__("version", "0.2"), "version"),
        (lambda payload: payload.__setitem__("route_plan_id", "other"), "route_plan_id"),
        (
            lambda payload: payload["candidates"][0].__setitem__("committed_copper", True),
            "committed_copper",
        ),
        (
            lambda payload: payload["candidates"][0]["patch"].__setitem__("committed_copper", True),
            "unknown patch field",
        ),
        (
            lambda payload: payload["candidates"][0]["patch"]["add_vias"][0]["position"].__setitem__("x", float("inf")),
            "finite",
        ),
        (
            lambda payload: payload["candidates"][0]["patch"]["add_tracks"][0].__setitem__("committed_copper", True),
            "add_tracks field",
        ),
    ],
)
def test_validate_route_candidates_rejects_invalid_payloads(mutator, message: str) -> None:
    payload = copy.deepcopy(json.loads(_fixture("route-candidates.json").read_text(encoding="utf-8")))
    mutator(payload)

    with pytest.raises(RouteCandidateSchemaError, match=message):
        validate_route_candidates(payload)


def test_validate_route_candidates_rejects_duplicate_candidate_ids() -> None:
    payload = copy.deepcopy(json.loads(_fixture("route-candidates.json").read_text(encoding="utf-8")))
    payload["candidates"].append(copy.deepcopy(payload["candidates"][0]))

    with pytest.raises(RouteCandidateSchemaError, match="duplicate candidate_id"):
        validate_route_candidates(payload)


def test_validate_route_candidates_rejects_non_dense_candidate_indices() -> None:
    payload = copy.deepcopy(json.loads(_fixture("route-candidates.json").read_text(encoding="utf-8")))
    payload["candidates"][1]["candidate_index"] = 7

    with pytest.raises(RouteCandidateSchemaError, match="dense"):
        validate_route_candidates(payload)
