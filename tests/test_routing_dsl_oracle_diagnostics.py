from pathlib import Path

from pardal.routing_dsl.oracle import (
    load_route_oracle_report,
    normalize_route_oracle_report,
    route_oracle_report_to_route_diagnostics,
    summarize_route_oracle_report,
)


FIXTURE = Path(__file__).parent / "fixtures" / "routing_dsl" / "route-oracle-report.json"


def test_normalize_route_oracle_report_preserves_board_copy_and_command_metadata() -> None:
    report = load_route_oracle_report(FIXTURE)
    normalized = normalize_route_oracle_report(report)

    assert normalized["schema"] == "pardal.route_diagnostics"
    assert normalized["route_plan_id"] == "route-plan-001"
    assert normalized["oracle"]["output_board_copy_path"] == "/tmp/out/routed-copy.kicad_pcb"
    assert normalized["oracle"]["command"]["tool"] == "kicad-cli"
    assert normalized["generated_board_authority"] is False
    assert normalized["routing_authority"] is False
    assert normalized["release_authority"] is False
    assert normalized["jlc_upload_authority"] is False
    assert normalized["orderable_claim"] is False

    rows = normalized["rows"]
    assert [row["failed_stage"] for row in rows] == ["apply", "drc"]
    assert [row["code"] for row in rows] == ["apply_rejected", "drc_violation"]
    assert [row["source"] for row in rows] == ["apply-report.json", "drc-report.json"]
    assert rows[1]["provenance"]["board_copy_path"] == "/tmp/out/routed-copy.kicad_pcb"
    assert rows[1]["provenance"]["command"]["argv"][0] == "kicad-cli"
    assert normalized["summary"]["by_route_group"] == [{"key": "rg_board", "count": 2}]
    assert normalized["summary"]["by_candidate"] == [{"key": "cand-board-0", "count": 2}]
    assert normalized["summary"]["by_stage"] == [
        {"key": "apply", "count": 1},
        {"key": "drc", "count": 1},
    ]
    assert normalized["summary"]["by_net"] == [{"key": "SIG_A", "count": 2}]
    assert normalized["summary"]["by_layer"] == [{"key": "F.Cu", "count": 2}]
    assert normalized["summary"]["by_code"] == [
        {"key": "apply_rejected", "count": 1},
        {"key": "drc_violation", "count": 1},
    ]


def test_route_oracle_report_to_route_diagnostics_is_stable() -> None:
    report = load_route_oracle_report(FIXTURE)
    first = route_oracle_report_to_route_diagnostics(report)
    second = route_oracle_report_to_route_diagnostics(report)

    assert first == second
    assert first["row_count"] == 2
    assert first["rows"][0]["row_hash"]


def test_summarize_route_oracle_report_returns_route_linked_summary() -> None:
    report = load_route_oracle_report(FIXTURE)
    summary = summarize_route_oracle_report(report)

    assert summary["route_plan_id"] == "route-plan-001"
    assert summary["route_plan_hash"] == "hash-001"
    assert summary["row_count"] == 2
    assert summary["summary"]["by_stage"][0] == {"key": "apply", "count": 1}
