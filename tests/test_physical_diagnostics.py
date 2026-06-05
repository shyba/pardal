import json

from pardal.physical.diagnostics import (
    build_diagnostics_dashboard,
    compare_diagnostics_dashboards,
    load_route_diagnostics_dashboard,
    normalize_route_diagnostic_violations,
    write_diagnostics_dashboard,
    write_progress_comparison,
)


def _cp180_route_diagnostics():
    return {
        "strict_aborted": True,
        "failed_candidate_count": 1,
        "violation_count": 5,
        "failures": [
            {
                "net": "PGC1_RB4",
                "strategy": "escape_bundle",
                "route_name": "pgc_lane",
                "route_index": 7,
                "alternative_name": "",
                "template_name": "pgc_west_of_corridor",
                "assignment": {"pgc_x": 58.3},
                "failed_stage": "route_commit",
                "moved_refs": ["C5", "C6", "TP1"],
                "replacement": {
                    "nets": ["PGC1_RB4"],
                    "removed_segments": 2,
                    "removed_vias": 1,
                },
                "candidate": {"segments": [{"layer": "F.Cu"}], "vias": []},
                "violations": [
                    {
                        "code": "track_to_pad_clearance",
                        "distance": -0.06,
                        "layer": "F.Cu",
                        "message": (
                            "PGC1_RB4 segment on F.Cu is -0.060mm from "
                            f"{target}; requires 0.200mm"
                        ),
                        "net": "PGC1_RB4",
                        "source": "",
                    }
                    for target in ["C5.1", "C5.2", "C6.1", "C6.2", "TP1.1"]
                ],
            }
        ],
    }


def test_normalizes_counterparty_from_message_before_violation_net():
    rows = normalize_route_diagnostic_violations(_cp180_route_diagnostics())

    assert {row["counterparty"] for row in rows} == {
        "C5.1",
        "C5.2",
        "C6.1",
        "C6.2",
        "TP1.1",
    }
    assert {row["counterparty_ref"] for row in rows} == {"C5", "C6", "TP1"}
    assert all(row["primary_net"] == "PGC1_RB4" for row in rows)
    assert "PGC1_RB4" not in {row["counterparty"] for row in rows}


def test_dashboard_stop_sweep_buckets_use_counterparty_objects():
    dashboard = build_diagnostics_dashboard(route_diagnostics=_cp180_route_diagnostics())

    assert dashboard["summary"]["violation_count"] == 5
    assert dashboard["summary"]["unique_bucket_count"] == 5
    assert dashboard["stop_decision"]["action"] == "stop_sweep"
    bucket_keys = {bucket["bucket_key"] for bucket in dashboard["top_buckets"]}
    assert "route_commit|PGC1_RB4|C5.1|F.Cu|track_to_pad_clearance" in bucket_keys
    assert "route_commit|PGC1_RB4|PGC1_RB4|F.Cu|track_to_pad_clearance" not in bucket_keys


def test_load_and_write_dashboard_from_artifact_root(tmp_path):
    route_diag = tmp_path / "nested" / "route-diagnostics.json"
    route_diag.parent.mkdir()
    route_diag.write_text(json.dumps(_cp180_route_diagnostics()), encoding="utf-8")

    dashboard = load_route_diagnostics_dashboard(tmp_path)
    output = tmp_path / "diagnostics-dashboard.json"
    write_diagnostics_dashboard(output, dashboard)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["inputs"]["route_diagnostics_present"] is True
    assert saved["first_blockers"][0]["counterparty"] in {
        "C5.1",
        "C5.2",
        "C6.1",
        "C6.2",
        "TP1.1",
    }


def test_dashboard_continues_when_no_route_diagnostics_failures():
    dashboard = build_diagnostics_dashboard(
        route_diagnostics={
            "strict_aborted": False,
            "failed_candidate_count": 0,
            "failures": [],
        }
    )

    assert dashboard["summary"]["violation_count"] == 0
    assert dashboard["stop_decision"]["action"] == "continue"
    assert dashboard["run"]["verification_stage_reached"] == "production"


def test_progress_comparison_detects_completion():
    previous = build_diagnostics_dashboard(route_diagnostics=_cp180_route_diagnostics())
    current = build_diagnostics_dashboard(
        route_diagnostics={
            "strict_aborted": False,
            "failed_candidate_count": 0,
            "failures": [],
        }
    )

    comparison = compare_diagnostics_dashboards(
        previous,
        current,
        previous_label="CP180",
        current_label="CP182",
    )

    assert comparison["progress_delta"]["verification_stage_delta"] > 0
    assert comparison["progress_delta"]["violation_count_delta"] == -5
    assert comparison["no_progress"]["detected"] is False
    assert comparison["no_progress"]["state"] == "completed"
    assert comparison["recommendation"]["action"] == "continue"


def test_progress_comparison_detects_repeated_failure_plateau(tmp_path):
    previous = build_diagnostics_dashboard(route_diagnostics=_cp180_route_diagnostics())
    current = build_diagnostics_dashboard(route_diagnostics=_cp180_route_diagnostics())

    comparison = compare_diagnostics_dashboards(previous, current)
    output = tmp_path / "comparison.json"
    write_progress_comparison(output, comparison)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert saved["progress_delta"]["verification_stage_delta"] == 0
    assert saved["progress_delta"]["violation_count_delta"] == 0
    assert saved["progress_delta"]["top_bucket_overlap"] == 1.0
    assert saved["no_progress"]["detected"] is True
    assert saved["no_progress"]["state"] == "plateaued"
    assert saved["recommendation"]["action"] == "stop_sweep"
