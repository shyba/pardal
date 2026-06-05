from __future__ import annotations

import json
from pathlib import Path

from pardal.routing_dsl.capability_gate import evaluate_backend_capabilities, load_backend_manifest


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _route_plan(**overrides):
    plan = {
        "route_plan_id": "plan-v1",
        "route_plan_hash": "hash-v1",
        "backend": {"id": "mojo", "version": "1.0"},
        "route_groups": [
            {
                "id": "rg0",
                "scope": {
                    "allowed_layers": ["F.Cu", "In1.Cu"],
                    "zones": True,
                    "keepouts": True,
                    "differential_pairs": True,
                },
                "constraints": {"trace_width_mm": 0.18, "clearance_mm": 0.16},
                "via": {"type": "through", "count": 1},
                "features": ["zones", "keepouts", "differential_pairs"],
            }
        ],
    }
    plan.update(overrides)
    return plan


def test_load_backend_manifest_from_fixture():
    manifest = load_backend_manifest(FIXTURES / "backend_manifest_supported.json")
    assert manifest["backend"]["id"] == "mojo"
    assert manifest["capabilities"]["supported_layers"] == ["F.Cu", "In1.Cu", "B.Cu"]


def test_backend_capability_gate_accepts_supported_plan():
    manifest = load_backend_manifest(FIXTURES / "backend_manifest_supported.json")
    result = evaluate_backend_capabilities(_route_plan(), manifest)

    assert result["supported"] is True
    assert result["failure_count"] == 0
    assert result["failures"] == []


def test_backend_capability_gate_reports_deterministic_failures():
    manifest = load_backend_manifest(FIXTURES / "backend_manifest_limited.json")
    result = evaluate_backend_capabilities(
        _route_plan(backend={"id": "freerouting", "version": "1.0"}), manifest
    )

    assert result["supported"] is False
    assert result["failure_count"] == 7
    codes = [item["code"] for item in result["failures"]]
    assert codes == [
        "unsupported_layer",
        "unsupported_differential_pair",
        "unsupported_zones",
        "unsupported_keepouts",
        "trace_width_out_of_range",
        "clearance_out_of_range",
        "via_count_exceeded",
    ]
    assert result["failures"][0]["source_field"] == "scope.allowed_layers"
    assert result["failures"][-1]["source_field"] == "via.count"


def test_backend_capability_gate_reports_backend_identity_mismatch():
    manifest = load_backend_manifest(FIXTURES / "backend_manifest_supported.json")
    mismatched = _route_plan(backend={"id": "freerouting", "version": "2.0"})
    result = evaluate_backend_capabilities(mismatched, manifest)

    assert [item["code"] for item in result["failures"]] == [
        "backend_identity_mismatch",
        "backend_version_mismatch",
    ]
    assert result["failures"][0]["expected"] == "mojo"


def test_manifest_fixture_json_is_stable():
    for path in sorted(FIXTURES.glob("backend_manifest_*.json")):
        json.loads(path.read_text(encoding="utf-8"))
