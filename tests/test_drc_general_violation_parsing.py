from __future__ import annotations

import json

from pardal.drc import _parse_drc_json


def test_parse_drc_json_parses_general_violations_and_preserves_items(tmp_path):
    report = tmp_path / "kicad_drc.json"
    payload = {
        "violations": [
            {
                "type": "clearance",
                "severity": "error",
                "description": "Clearance violation between items",
                "items": [
                    {
                        "uuid": "11111111-1111-1111-1111-111111111111",
                        "description": "Track [RD8] on F.Cu",
                        "pos": {"x": 49.25, "y": 34.3375},
                        "source": {"ref": "U1", "pad": "58"},
                    },
                    {
                        "uuid": "22222222-2222-2222-2222-222222222222",
                        "description": "Pad 4 [RD8] of J2",
                        "pos": {"x": 85.0, "y": 47.62},
                        "source": {"ref": "J2", "pad": "4"},
                    },
                ],
            },
            {
                "type": "shorting_items",
                "severity": "warning",
                "description": "Potential short between nets GND and 3V3",
                "items": [
                    {
                        "uuid": "33333333-3333-3333-3333-333333333333",
                        "description": "Via [GND] on B.Cu",
                        "pos": {"x": 12.0, "y": 8.0},
                        "source": {"ref": "U3", "pad": "10"},
                    }
                ],
            },
        ],
        "unconnected_items": [],
    }
    report.write_text(json.dumps(payload), encoding="utf-8")

    errors, warnings, violations, unconnected = _parse_drc_json(report)

    assert errors == 1
    assert warnings == 1
    assert unconnected == 0
    assert len(violations) == 2

    clearance = violations[0]
    assert clearance.type == "clearance"
    assert clearance.severity == "error"
    assert clearance.description == "Clearance violation between items"
    assert clearance.items[0]["uuid"] == "11111111-1111-1111-1111-111111111111"
    assert clearance.items[0]["pos"] == {"x": 49.25, "y": 34.3375}
    assert clearance.items[0]["source"] == {"ref": "U1", "pad": "58"}

    shorting = violations[1]
    assert shorting.type == "shorting_items"
    assert shorting.severity == "warning"
    assert shorting.items[0]["source"] == {"ref": "U3", "pad": "10"}


def test_parse_drc_json_defaults_missing_severity_for_general_violations(tmp_path):
    report = tmp_path / "kicad_drc.json"
    payload = {
        "violations": [
            {
                "type": "hole_clearance",
                "description": "Hole too close to copper",
                "items": [{"description": "Via [GND]"}],
            }
        ],
        "unconnected_items": [],
    }
    report.write_text(json.dumps(payload), encoding="utf-8")

    errors, warnings, violations, unconnected = _parse_drc_json(report)

    assert errors == 0
    assert warnings == 1
    assert unconnected == 0
    assert len(violations) == 1
    assert violations[0].type == "hole_clearance"
    assert violations[0].severity == "warning"
    assert violations[0].description == "Hole too close to copper"
