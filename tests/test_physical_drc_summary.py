from pathlib import Path
import json

from pardal.physical.compiler import (
    DrcSourceReason,
    DrcViolationEntry,
    _build_drc_source_coverage,
    format_drc_diagnostics_json,
    _parse_drc_unconnected,
    _parse_drc_violations,
    format_drc_violations_json,
    map_drc_violations_to_production_checks,
    summarize_drc_unconnected,
)
from pardal.physical.spec import (
    SOURCE_LOCATION_KEY,
    BoardRules,
    PartPlacement,
    PhysicalSpec,
    PowerStitchIntent,
    RouteIntent,
    SourceLocation,
)


def _spec() -> PhysicalSpec:
    return _spec_with_power_stitch({"refs": {"U1": [10]}, "vias": {"U1.10": ["12mm", "10mm"]}})


def _spec_without_route_reason() -> PhysicalSpec:
    spec = _spec()
    spec.routes[0].raw.pop("reason", None)
    return spec


def _spec_with_power_stitch(raw):
    extra_power_stitches = raw.pop("_extra_power_stitches", [])
    return PhysicalSpec(
        path=Path("board.pdl.yaml"),
        source_netlist=None,
        width=30,
        height=20,
        stackup="four_layer",
        copper_layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        rules=BoardRules(),
        parts={"U1": PartPlacement("U1", "Test:U1", (10, 10))},
        netclass_assignments={},
        routes=[
            RouteIntent(
                raw={
                    "name": "gpio_b_rd8",
                    "group": "gpio_b",
                    "kind": "manual_polyline",
                    "net": "RD8",
                    "reason": "blocked until the GPIO_B bank has a negotiated corridor",
                    SOURCE_LOCATION_KEY: SourceLocation(Path("board.pdl.yaml"), 42),
                }
            )
        ],
        power_stitches=[
            PowerStitchIntent(
                raw={
                    "name": "u1_gnd_stitch",
                    "kind": "pad_vias",
                    "net": "gnd",
                    **raw,
                }
            )
        ]
        + [PowerStitchIntent(raw=item) for item in extra_power_stitches],
    )


def test_parse_drc_unconnected_maps_routes_and_power_stitches(tmp_path):
    report = tmp_path / "drc.rpt"
    report.write_text(
        """** Found 2 unconnected pads **
[unconnected_items]: Missing connection between items
    @(49.2500 mm, 34.3375 mm): Pad 58 [RD8] of U1 on F.Cu
    @(85.0000 mm, 47.6200 mm): PTH pad 4 [RD8] of J2
[unconnected_items]: Missing connection between items
    @(44.3375 mm, 40.7500 mm): Pad 10 [gnd] of U1 on F.Cu
    @(44.3375 mm, 37.7500 mm): Pad 4 [gnd] of U1 on F.Cu
""",
        encoding="utf-8",
    )

    entries = _parse_drc_unconnected(report, _spec())

    assert len(entries) == 2
    assert entries[0].net == "RD8"
    assert entries[0].pads == ["U1.58", "J2.4"]
    assert entries[0].route_intents == ["gpio_b_rd8"]
    assert entries[0].route_groups == ["gpio_b"]
    assert [(reason.kind, reason.name, reason.reason) for reason in entries[0].source_reasons] == [
        ("route", "gpio_b_rd8", "blocked until the GPIO_B bank has a negotiated corridor")
    ]
    assert "route intent exists" in entries[0].message
    assert entries[1].net == "gnd"
    assert entries[1].pads == ["U1.10", "U1.4"]
    assert entries[1].power_stitches == ["u1_gnd_stitch"]
    assert "omits U1.4" in entries[1].message


def test_parse_drc_unconnected_maps_deferred_power_refs(tmp_path):
    report = tmp_path / "drc.rpt"
    report.write_text(
        """** Found 1 unconnected pads **
[unconnected_items]: Missing connection between items
    @(44.3375 mm, 40.7500 mm): Pad 10 [gnd] of U1 on F.Cu
    @(44.3375 mm, 37.7500 mm): Pad 4 [gnd] of U1 on F.Cu
""",
        encoding="utf-8",
    )

    entries = _parse_drc_unconnected(
        report,
        _spec_with_power_stitch(
            {
                "refs": {"U1": [10]},
                "vias": {"U1.10": ["12mm", "10mm"]},
                "_extra_power_stitches": [
                    {
                        "name": "u1_gnd_pad4_deferred",
                        "kind": "deferred",
                        "net": "gnd",
                        "refs": {"U1": [4]},
                        "reason": "blocked until local GND stitch geometry can be negotiated",
                        SOURCE_LOCATION_KEY: SourceLocation(Path("board.pdl.yaml"), 88),
                    }
                ],
            }
        ),
    )

    assert len(entries) == 1
    assert entries[0].power_stitches == ["u1_gnd_stitch", "u1_gnd_pad4_deferred"]
    assert [(reason.kind, reason.name, reason.reason) for reason in entries[0].source_reasons] == [
        (
            "power_stitch",
            "u1_gnd_pad4_deferred",
            "blocked until local GND stitch geometry can be negotiated",
        )
    ]
    assert entries[0].source_reasons[0].source == "board.pdl.yaml:88"
    assert entries[0].message == "power pad intentionally deferred: u1_gnd_pad4_deferred"


def test_summarize_drc_unconnected_counts_groups_and_sources(tmp_path):
    report = tmp_path / "drc.rpt"
    report.write_text(
        """** Found 2 unconnected pads **
[unconnected_items]: Missing connection between items
    @(49.2500 mm, 34.3375 mm): Pad 58 [RD8] of U1 on F.Cu
    @(85.0000 mm, 47.6200 mm): PTH pad 4 [RD8] of J2
[unconnected_items]: Missing connection between items
    @(44.3375 mm, 40.7500 mm): Pad 10 [gnd] of U1 on F.Cu
    @(44.3375 mm, 37.7500 mm): Pad 4 [gnd] of U1 on F.Cu
""",
        encoding="utf-8",
    )
    entries = _parse_drc_unconnected(
        report,
        _spec_with_power_stitch(
            {
                "refs": {"U1": [10]},
                "vias": {"U1.10": ["12mm", "10mm"]},
                "_extra_power_stitches": [
                        {
                            "name": "u1_gnd_pad4_deferred",
                            "kind": "deferred",
                            "net": "gnd",
                            "refs": {"U1": [4]},
                            "reason": "blocked until local GND stitch geometry can be negotiated",
                            SOURCE_LOCATION_KEY: SourceLocation(Path("board.pdl.yaml"), 88),
                        }
                    ],
                }
        ),
    )

    summary = summarize_drc_unconnected(entries)

    assert summary.route_groups == {"gpio_b": 1}
    assert summary.route_intents == {"gpio_b_rd8": 1}
    assert summary.power_stitches == {
        "u1_gnd_stitch": 1,
        "u1_gnd_pad4_deferred": 1,
    }
    assert summary.unattributed_nets == {}
    assert [(bucket.kind, bucket.name, bucket.unconnected, bucket.pads) for bucket in summary.buckets] == [
        ("group", "gpio_b", 1, 2),
        ("source", "power_stitch", 1, 2),
    ]
    assert summary.buckets[0].nets == {"RD8"}
    assert summary.buckets[0].route_intents == {"gpio_b_rd8"}
    assert [(reason.kind, reason.name, reason.reason) for reason in summary.buckets[0].source_reasons] == [
        ("route", "gpio_b_rd8", "blocked until the GPIO_B bank has a negotiated corridor")
    ]
    assert [reason.source for reason in summary.buckets[0].source_reasons] == ["board.pdl.yaml:42"]
    assert summary.buckets[1].nets == {"gnd"}
    assert summary.buckets[1].power_stitches == {
        "u1_gnd_stitch",
        "u1_gnd_pad4_deferred",
    }
    assert [(reason.kind, reason.name, reason.reason) for reason in summary.buckets[1].source_reasons] == [
        (
            "power_stitch",
            "u1_gnd_pad4_deferred",
            "blocked until local GND stitch geometry can be negotiated",
        )
    ]
    assert [reason.source for reason in summary.buckets[1].source_reasons] == ["board.pdl.yaml:88"]


def test_parse_drc_violations_extracts_non_unconnected_blocks_and_sources(tmp_path):
    report = tmp_path / "manual-drc.rpt"
    report.write_text(
        """** Found 3 DRC violations **
[track_dangling]: Track has unconnected end
    Local override; warning
    @(50.7500 mm, 34.3370 mm): Track [RD8] on F.Cu, length 34.4017 mm
[clearance]: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.1400 mm)
    Rule: netclass 'Default'; error
    @(49.2500 mm, 34.3370 mm): Pad 58 [RD8] of U1 on F.Cu
    @(85.0000 mm, 47.6200 mm): PTH pad 4 [RD8] of J2
[unconnected_items]: Missing connection between items
    @(49.2500 mm, 34.3375 mm): Pad 58 [RD8] of U1 on F.Cu
    @(85.0000 mm, 47.6200 mm): PTH pad 4 [RD8] of J2
""",
        encoding="utf-8",
    )

    entries = _parse_drc_violations(report, _spec())
    assert len(entries) == 2

    dangling = entries[0]
    assert dangling.code == "track_dangling"
    assert dangling.severity == "warning"
    assert dangling.nets == ["RD8"]
    assert dangling.coordinates == [(50.75, 34.337)]
    assert dangling.pads == []
    assert dangling.source_reasons[0].kind == "route"
    assert dangling.source_reasons[0].name == "gpio_b_rd8"

    clearance = entries[1]
    assert clearance.code == "clearance"
    assert clearance.severity == "error"
    assert clearance.pads == ["U1.58", "J2.4"]
    assert clearance.nets == ["RD8"]


def test_parse_drc_violations_adds_net_level_route_fallback_when_reason_is_missing(tmp_path):
    report = tmp_path / "manual-drc.rpt"
    report.write_text(
        """** Found 1 DRC violations **
[track_dangling]: Track has unconnected end
    Local override; warning
    @(49.2500 mm, 34.3370 mm): Track [RD8] on F.Cu, length 36.0189 mm
""",
        encoding="utf-8",
    )

    entries = _parse_drc_violations(report, _spec_without_route_reason())

    assert len(entries) == 1
    assert entries[0].source_reasons == [
        DrcSourceReason(
            kind="route",
            name="gpio_b_rd8",
            reason="net-level fallback from route intent on violated net",
            source="board.pdl.yaml:42",
        )
    ]


def test_parse_drc_violations_keeps_pad_specific_power_stitch_match_without_net_fallback(tmp_path):
    report = tmp_path / "manual-drc.rpt"
    report.write_text(
        """** Found 1 DRC violations **
[clearance]: Clearance violation (netclass 'Default' clearance 0.2000 mm; actual 0.1400 mm)
    Rule: netclass 'Default'; error
    @(44.3375 mm, 40.7500 mm): Pad 10 [gnd] of U1 on F.Cu
    @(44.3375 mm, 37.7500 mm): Pad 4 [gnd] of U1 on F.Cu
""",
        encoding="utf-8",
    )

    entries = _parse_drc_violations(
        report,
        _spec_with_power_stitch(
            {
                "refs": {"U1": [10]},
                "vias": {"U1.10": ["12mm", "10mm"]},
                "_extra_power_stitches": [
                    {
                        "name": "u1_gnd_pad4_deferred",
                        "kind": "deferred",
                        "net": "gnd",
                        "refs": {"U1": [4]},
                        SOURCE_LOCATION_KEY: SourceLocation(Path("board.pdl.yaml"), 88),
                    }
                ],
            }
        ),
    )

    assert len(entries) == 1
    assert DrcSourceReason(
        kind="power_stitch",
        name="u1_gnd_pad4_deferred",
        reason="matched violated pad in power stitch intent",
        source="board.pdl.yaml:88",
    ) in entries[0].source_reasons
    assert all(
        reason.reason != "net-level fallback from power stitch intent on violated net"
        for reason in entries[0].source_reasons
    )


def test_format_drc_violations_json_includes_source_reasons(tmp_path):
    report = tmp_path / "manual-drc.rpt"
    report.write_text(
        """** Found 1 DRC violations **
[track_dangling]: Track has unconnected end
    Local override; warning
    @(49.2500 mm, 34.3370 mm): Track [RD8] on F.Cu, length 36.0189 mm
""",
        encoding="utf-8",
    )
    entries = _parse_drc_violations(report, _spec())
    payload = format_drc_violations_json(entries)

    assert '"drc_violations": 1' in payload
    assert '"code": "track_dangling"' in payload


def test_format_drc_violations_json_includes_net_level_fallback_source_reasons(tmp_path):
    report = tmp_path / "manual-drc.rpt"
    report.write_text(
        """** Found 1 DRC violations **
[track_dangling]: Track has unconnected end
    Local override; warning
    @(49.2500 mm, 34.3370 mm): Track [RD8] on F.Cu, length 36.0189 mm
""",
        encoding="utf-8",
    )

    entries = _parse_drc_violations(report, _spec_without_route_reason())
    payload = json.loads(format_drc_violations_json(entries))

    assert payload["findings"] == [
        {
            "code": "track_dangling",
            "coordinates": [[49.25, 34.337]],
            "nets": ["RD8"],
            "pads": [],
            "severity": "warning",
            "source_reasons": [
                {
                    "kind": "route",
                    "name": "gpio_b_rd8",
                    "reason": "net-level fallback from route intent on violated net",
                    "source": "board.pdl.yaml:42",
                }
            ],
            "title": "Track has unconnected end",
        }
    ]


def test_format_drc_diagnostics_json_includes_unconnected_entries_and_summary(tmp_path):
    report = tmp_path / "drc.rpt"
    report.write_text(
        """** Found 2 unconnected pads **
[unconnected_items]: Missing connection between items
    @(49.2500 mm, 34.3375 mm): Pad 58 [RD8] of U1 on F.Cu
    @(85.0000 mm, 47.6200 mm): PTH pad 4 [RD8] of J2
[unconnected_items]: Missing connection between items
    @(44.3375 mm, 40.7500 mm): Pad 10 [gnd] of U1 on F.Cu
    @(44.3375 mm, 37.7500 mm): Pad 4 [gnd] of U1 on F.Cu
""",
        encoding="utf-8",
    )
    entries = _parse_drc_unconnected(
        report,
        _spec_with_power_stitch(
            {
                "refs": {"U1": [10]},
                "vias": {"U1.10": ["12mm", "10mm"]},
                "_extra_power_stitches": [
                    {
                        "name": "u1_gnd_pad4_deferred",
                        "kind": "deferred",
                        "net": "gnd",
                        "refs": {"U1": [4]},
                        "reason": "blocked until local GND stitch geometry can be negotiated",
                        SOURCE_LOCATION_KEY: SourceLocation(Path("board.pdl.yaml"), 88),
                    }
                ],
            }
        ),
    )

    payload = json.loads(format_drc_diagnostics_json([], entries))

    assert payload["drc_violations"] == 0
    assert payload["findings"] == []
    assert payload["drc_unconnected"] == 2
    assert payload["unconnected_items"] == [
        {
            "message": "route intent exists but KiCad still reports this connection open",
            "net": "RD8",
            "pads": ["J2.4", "U1.58"],
            "power_stitches": [],
            "route_groups": ["gpio_b"],
            "route_intents": ["gpio_b_rd8"],
            "source_reasons": [
                {
                    "kind": "route",
                    "name": "gpio_b_rd8",
                    "reason": "blocked until the GPIO_B bank has a negotiated corridor",
                    "source": "board.pdl.yaml:42",
                }
            ],
        },
        {
            "message": "power pad intentionally deferred: u1_gnd_pad4_deferred",
            "net": "gnd",
            "pads": ["U1.10", "U1.4"],
            "power_stitches": ["u1_gnd_pad4_deferred", "u1_gnd_stitch"],
            "route_groups": [],
            "route_intents": [],
            "source_reasons": [
                {
                    "kind": "power_stitch",
                    "name": "u1_gnd_pad4_deferred",
                    "reason": "blocked until local GND stitch geometry can be negotiated",
                    "source": "board.pdl.yaml:88",
                }
            ],
        },
    ]
    assert payload["unconnected_summary"] == {
        "buckets": [
            {
                "kind": "group",
                "name": "gpio_b",
                "nets": ["RD8"],
                "pads": 2,
                "power_stitches": [],
                "route_intents": ["gpio_b_rd8"],
                "source_reasons": [
                    {
                        "kind": "route",
                        "name": "gpio_b_rd8",
                        "reason": "blocked until the GPIO_B bank has a negotiated corridor",
                        "source": "board.pdl.yaml:42",
                    }
                ],
                "unconnected": 1,
            },
            {
                "kind": "source",
                "name": "power_stitch",
                "nets": ["gnd"],
                "pads": 2,
                "power_stitches": ["u1_gnd_pad4_deferred", "u1_gnd_stitch"],
                "route_intents": [],
                "source_reasons": [
                    {
                        "kind": "power_stitch",
                        "name": "u1_gnd_pad4_deferred",
                        "reason": "blocked until local GND stitch geometry can be negotiated",
                        "source": "board.pdl.yaml:88",
                    }
                ],
                "unconnected": 1,
            },
        ],
        "power_stitches": {
            "u1_gnd_pad4_deferred": 1,
            "u1_gnd_stitch": 1,
        },
        "route_groups": {"gpio_b": 1},
        "route_intents": {"gpio_b_rd8": 1},
        "unattributed_nets": {},
    }


def test_format_drc_diagnostics_json_records_clean_zero_unconnected_case():
    payload = json.loads(format_drc_diagnostics_json([], []))

    assert payload == {
        "drc_unconnected": 0,
        "drc_violations": 0,
        "findings": [],
        "unconnected_items": [],
        "unconnected_summary": {
            "buckets": [],
            "power_stitches": {},
            "route_groups": {},
            "route_intents": {},
            "unattributed_nets": {},
        },
    }


def test_map_drc_violations_to_production_checks_jlc_policy_mapping():
    violations = [
        DrcViolationEntry(
            code="hole_clearance",
            title="Hole too close to copper",
            severity="error",
            source_reasons=[
                DrcSourceReason(
                    kind="route",
                    name="critical_hole_escape",
                    reason="clearance narrowed around mechanical keepout",
                    source="board.pdl.yaml:120",
                )
            ],
        ),
        DrcViolationEntry(
            code="silk_over_copper",
            title="Silk screen intersects copper",
            severity="error",
        ),
        DrcViolationEntry(
            code="clearance",
            title="General clearance issue",
            severity="error",
        ),
    ]

    findings = map_drc_violations_to_production_checks(
        profile="jlcpcb_4_layer_smt",
        drc_violations=violations,
    )

    assert [(entry.severity, entry.code) for entry in findings] == [
        ("error", "dfm.drc_hole_clearance"),
        ("warning", "dfm.drc_silk_over_copper"),
    ]
    assert findings[0].message == "KiCad DRC hole_clearance: Hole too close to copper"
    assert findings[0].source == "board.pdl.yaml:120"
    assert findings[1].source == ""


def test_map_drc_violations_to_production_checks_requires_profile_and_policy():
    violations = [
        DrcViolationEntry(
            code="hole_to_hole",
            title="Hole spacing too small",
            severity="error",
        )
    ]

    assert (
        map_drc_violations_to_production_checks(profile=None, drc_violations=violations)
        == []
    )
    assert (
        map_drc_violations_to_production_checks(
            profile="proto_internal",
            drc_violations=violations,
        )
        == []
    )


def test_map_drc_violations_to_production_checks_for_jlc_profile():
    drc_entries = [
        DrcViolationEntry(
            code="hole_clearance",
            title="Hole clearance violation",
            severity="error",
            source_reasons=[],
        ),
        DrcViolationEntry(
            code="silk_edge_clearance",
            title="Silkscreen too close to edge",
            severity="error",
            source_reasons=[],
        ),
        DrcViolationEntry(
            code="clearance",
            title="Generic clearance",
            severity="error",
            source_reasons=[],
        ),
    ]

    findings = map_drc_violations_to_production_checks(
        profile="jlcpcb_4_layer_smt",
        drc_violations=drc_entries,
    )
    assert [(entry.severity, entry.code) for entry in findings] == [
        ("error", "dfm.drc_hole_clearance"),
        ("warning", "dfm.drc_silk_edge_clearance"),
    ]
    assert findings[0].message == "KiCad DRC hole_clearance: Hole clearance violation"


def test_build_drc_source_coverage_counts_attributed_and_unattributed_entries(tmp_path):
    report = tmp_path / "drc.rpt"
    report.write_text(
        """** Found 2 unconnected pads **
[unconnected_items]: Missing connection between items
    @(49.2500 mm, 34.3375 mm): Pad 58 [RD8] of U1 on F.Cu
    @(85.0000 mm, 47.6200 mm): PTH pad 4 [RD8] of J2
[unconnected_items]: Missing connection between items
    @(10.0000 mm, 10.0000 mm): Pad 1 [MISSING] of J1 on F.Cu
    @(12.0000 mm, 10.0000 mm): Pad 2 [MISSING] of J1 on F.Cu
""",
        encoding="utf-8",
    )

    coverage = _build_drc_source_coverage(
        drc_violations=[
            DrcViolationEntry(
                code="clearance",
                title="Clearance violation",
                severity="error",
                source_reasons=[
                    DrcSourceReason(
                        kind="route",
                        name="gpio_b_rd8",
                        reason="authored route reason",
                        source="board.pdl.yaml:42",
                    )
                ],
            ),
            DrcViolationEntry(
                code="track_dangling",
                title="Track has unconnected end",
                severity="warning",
            ),
        ],
        drc_unconnected=_parse_drc_unconnected(report, _spec()),
    )

    assert coverage == {
        "violation_count": 2,
        "unconnected_count": 2,
        "attributed_violation_count": 1,
        "unattributed_violation_count": 1,
        "attributed_unconnected_count": 1,
        "unattributed_unconnected_count": 1,
        "pass": False,
        "violation_source_kinds": {"route": 1},
        "unconnected_source_kinds": {"route": 1},
    }
