import json
from pathlib import Path

import pytest

from pardal.routing_dsl.diagnostics import (
    load_route_diagnostics,
    normalize_route_diagnostics,
    write_route_diagnostics,
)


FIXTURE = Path(__file__).parent / "fixtures" / "routing_dsl" / "route-diagnostics.json"


def test_normalizes_diagnostic_rows_and_summaries():
    payload = load_route_diagnostics(FIXTURE)
    normalized = normalize_route_diagnostics(payload)

    assert normalized["schema"] == "pardal.route_diagnostics"
    assert normalized["version"] == "0.1"
    assert normalized["run_id"] == "run-001"
    assert normalized["route_plan_id"] == "route-plan-001"
    assert normalized["diagnostics_hash"]
    assert normalized["generated_board_authority"] is False
    assert normalized["routing_authority"] is False
    assert normalized["release_authority"] is False
    assert normalized["jlc_upload_authority"] is False
    assert normalized["orderable_claim"] is False

    rows = normalized["rows"]
    assert [row["route_group_id"] for row in rows] == [
        "rg_backend",
        "rg_board",
        "rg_cap",
        "rg_source",
    ]
    assert rows[0]["failed_stage"] == "backend"
    assert rows[0]["candidate_index"] == 1
    assert rows[0]["strategy.kind"] == "lane_allocator"
    assert rows[0]["strategy.profile_id"] == "profile-b"
    assert rows[0]["replacement"] == {"removed_objects": ["U1.A1"]}
    assert rows[0]["movement"] == {"moved_components": [{"ref": "U1", "dx": 1.0, "dy": 0.0}]}
    assert rows[1]["failed_stage"] == "board_ir"
    assert rows[2]["failed_stage"] == "capability"
    assert rows[3]["failed_stage"] == "source"
    assert rows[3]["source"] == "routes.pdl.yaml"
    assert rows[3]["distance_mm"] == 0.12
    assert rows[3]["source_span"] == {"path": "routes.pdl.yaml", "line": 1, "column": 1}

    assert normalized["summary"]["by_stage"] == [
        {"key": "backend", "count": 1},
        {"key": "board_ir", "count": 1},
        {"key": "capability", "count": 1},
        {"key": "source", "count": 1},
    ]
    assert normalized["summary"]["by_code"][-1] == {"key": "yaml_parse_error", "count": 1}


def test_write_route_diagnostics_is_stable(tmp_path):
    payload = load_route_diagnostics(FIXTURE)
    output = tmp_path / "route-diagnostics.normalized.json"
    write_route_diagnostics(output, payload)
    first = output.read_text(encoding="utf-8")
    write_route_diagnostics(output, payload)
    second = output.read_text(encoding="utf-8")

    assert first == second
    saved = json.loads(first)
    assert saved["row_count"] == 4
    assert saved["rows"][0]["row_hash"]
    assert saved["generated_board_authority"] is False


@pytest.mark.parametrize(
    ("failed_stage", "code"),
    [
        ("apply", "apply_rejected"),
        ("drc", "drc_violation"),
        ("oracle", "oracle_mismatch"),
    ],
)
def test_future_failure_stages_are_preserved_stably(failed_stage: str, code: str) -> None:
    payload = normalize_route_diagnostics(
        {
            "run_id": "run-future",
            "route_plan_id": "route-plan-future",
            "route_plan_hash": "hash-future",
            "failures": [
                {
                    "route_group_id": "rg_future",
                    "candidate_id": "cand_future",
                    "candidate_index": 0,
                    "failed_stage": failed_stage,
                    "code": code,
                    "message": "future-stage failure",
                    "assignment": {"profile": "future"},
                }
            ],
        }
    )

    assert payload["rows"][0]["failed_stage"] == failed_stage
    assert payload["rows"][0]["code"] == code
    assert payload["summary"]["by_stage"] == [{"key": failed_stage, "count": 1}]
    assert payload["summary"]["by_code"] == [{"key": code, "count": 1}]


def test_missing_required_fields_are_rejected():
    with pytest.raises(ValueError, match="failed_stage must be present"):
        normalize_route_diagnostics(
            {
                "failures": [
                    {
                        "route_group_id": "rg1",
                        "candidate_id": "cand1",
                        "source_owned": False,
                        "code": "x",
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="source_span must be present for source-owned errors"):
        normalize_route_diagnostics(
            {
                "failures": [
                    {
                        "route_group_id": "rg1",
                        "candidate_id": "cand1",
                        "failed_stage": "source",
                        "code": "yaml_parse_error",
                        "source_owned": True,
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="route_group_id must be present"):
        normalize_route_diagnostics(
            {
                "failures": [
                    {
                        "candidate_id": "cand1",
                        "failed_stage": "backend",
                        "code": "staging_rejected",
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="candidate_id must be present when candidate exists"):
        normalize_route_diagnostics(
            {
                "failures": [
                    {
                        "route_group_id": "rg1",
                        "candidate": {"kind": "patch"},
                        "failed_stage": "backend",
                        "code": "staging_rejected",
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="numeric blocker must be present for clearance/length diagnostics"):
        normalize_route_diagnostics(
            {
                "failures": [
                    {
                        "route_group_id": "rg1",
                        "candidate_id": "cand1",
                        "failed_stage": "backend",
                        "code": "clearance",
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="authority fields must remain false"):
        normalize_route_diagnostics(
            {
                "failures": [
                    {
                        "route_group_id": "rg1",
                        "candidate_id": "cand1",
                        "failed_stage": "backend",
                        "code": "staging_rejected",
                        "generated_board_authority": True,
                    }
                ]
            }
        )
