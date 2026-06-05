import pytest
from dataclasses import replace

from pardal.data_model import Board, Component, Net, Pad, TraceSegment, Via
from pardal.physical.commit_gate import RouteCandidate, commit_route_candidate
from pardal.physical.routes import (
    MAX_ESCAPE_BUNDLE_CANDIDATES,
    MAX_HEADER_BANK_BUNDLE_COMBINATIONS,
    apply_routes,
    resolve_point,
    _build_route_corridor_keepouts,
)
from pardal.physical.routes import RouteCommitFailureError
from pardal.physical.compiler import _check_route_layer_policy, format_route_failures_json
from pardal.physical.spec import (
    PhysicalSpec,
    BoardRules,
    PartPlacement,
    RouteIntent,
    RouteCorridorIntent,
    RouteCorridorLaneIntent,
)


def _board() -> Board:
    board = Board()
    board.width = 30
    board.height = 30
    board.layers = ["F.Cu", "In1.Cu", "B.Cu"]
    board.add_component(
        Component(
            "U1",
            "IC",
            "Test:U1",
            (10.0, 10.0),
            0,
            pads=[Pad("1", (0.0, 0.0), (0.4, 0.4)), Pad("2", (4.0, 0.0), (0.4, 0.4))],
        )
    )
    board.add_component(
        Component(
            "J1",
            "Header",
            "Test:J1",
            (20.0, 10.0),
            0,
            pads=[Pad("1", (0.0, 0.0), (0.4, 0.4)), Pad("2", (0.0, 4.0), (0.4, 0.4))],
        )
    )
    net = Net("N1", "1", track_width=0.1)
    net.add_connection("U1", "1")
    net.add_connection("J1", "1")
    board.add_net(net)
    return board


def _spec(routes, route_corridors: dict[str, RouteCorridorIntent] | None = None):
    route_corridors = route_corridors or {}
    return PhysicalSpec(
        path="dummy",
        source_netlist=None,
        width=30,
        height=30,
        stackup="two_layer",
        copper_layers=None,
        rules=BoardRules(),
        parts={"U1": PartPlacement("U1", "Test:U1", (10, 10))},
        netclass_assignments={},
        routes=[RouteIntent(raw=raw) for raw in routes],
        route_corridors=route_corridors,
    )


def _wide_board() -> Board:
    board = Board()
    board.width = 120
    board.height = 120
    board.layers = ["F.Cu", "In1.Cu", "B.Cu"]
    board.add_component(
        Component(
            "U1",
            "IC",
            "Test:U1",
            (10.0, 10.0),
            0,
            pads=[Pad("1", (0.0, 0.0), (0.4, 0.4)), Pad("2", (4.0, 0.0), (0.4, 0.4))],
        )
    )
    board.add_component(
        Component(
            "J1",
            "Header",
            "Test:J1",
            (20.0, 10.0),
            0,
            pads=[Pad("1", (0.0, 0.0), (0.4, 0.4)), Pad("2", (0.0, 4.0), (0.4, 0.4))],
        )
    )
    net = Net("N1", "1", track_width=0.1)
    net.add_connection("U1", "1")
    net.add_connection("J1", "1")
    net2 = Net("N2", "2", track_width=0.1)
    net2.add_connection("U1", "2")
    net2.add_connection("J1", "2")
    board.add_net(net)
    board.add_net(net2)
    return board


def test_resolve_pad_and_relative_points():
    board = _board()
    assert resolve_point(board, "U1.1") == (10.0, 10.0)
    assert resolve_point(board, "north 2mm from U1.1") == (10.0, 8.0)
    assert resolve_point(board, "east 2mm", previous=(10.0, 8.0)) == (12.0, 8.0)


def test_manual_polyline_route_commits_segments():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "manual_polyline",
                "net": "N1",
                "layer": "F.Cu",
                "points": ["U1.1", "north 2mm from U1.1", "J1.1"],
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].alternative_name == ""
    assert len(board.nets["N1"].segments) == 2


def test_non_header_bank_alternatives_by_net_is_ignored():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "manual_polyline",
                "net": "N1",
                "layer": "F.Cu",
                "points": ["U1.1", ["12mm", "8mm"], ["18mm", "8mm"], "J1.1"],
                "alternatives_by_net": {
                    "N1": [
                        {
                            "name": "ignored_manual_alternative",
                            "points": ["U1.1", "J1.1"],
                        }
                    ]
                },
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].alternative_name == ""
    assert len(board.nets["N1"].segments) == 3


def test_manual_polyline_route_can_switch_layers_with_via():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "manual_polyline",
                "net": "N1",
                "layer": "F.Cu",
                "points": [
                    "U1.1",
                    ["10mm", "5mm"],
                    {"via": ["12mm", "5mm"], "to": "B.Cu", "diameter": "0.5mm", "drill": "0.2mm"},
                    ["20mm", "5mm"],
                    "J1.1",
                ],
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].vias == 1
    assert report[0].route_name == "manual_polyline[0001]"
    assert report[0].route_index == 0
    assert report[0].segment_layers == ("F.Cu", "B.Cu")
    assert report[0].via_layers == (("F.Cu", "In1.Cu", "B.Cu"),)
    assert report[0].used_layers == ("F.Cu", "In1.Cu", "B.Cu")
    assert len(board.nets["N1"].vias) == 1
    assert {segment.layer for segment in board.nets["N1"].segments} == {"F.Cu", "B.Cu"}


def test_route_layer_metadata_deduplicates_segment_layers_in_order():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "manual_polyline",
                "net": "N1",
                "layer": "F.Cu",
                "points": [
                    "U1.1",
                    ["10mm", "5mm"],
                    {"via": ["12mm", "5mm"], "to": "In1.Cu", "diameter": "0.5mm", "drill": "0.2mm", "layers": ["In1.Cu", "B.Cu", "F.Cu"]},
                    ["18mm", "5mm"],
                    {"via": ["20mm", "5mm"], "to": "F.Cu", "diameter": "0.5mm", "drill": "0.2mm", "layers": ["F.Cu", "In1.Cu", "B.Cu"]},
                    "J1.1",
                ],
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].segment_layers == ("F.Cu", "In1.Cu")
    assert report[0].via_layers == (
        ("In1.Cu", "B.Cu", "F.Cu"),
        ("F.Cu", "In1.Cu", "B.Cu"),
    )
    assert report[0].used_layers == ("F.Cu", "In1.Cu", "B.Cu")


def test_manual_polyline_route_can_use_through_via_to_inner_layer():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "manual_polyline",
                "net": "N1",
                "layer": "F.Cu",
                "points": [
                    "U1.1",
                    ["10mm", "5mm"],
                    {
                        "via": ["12mm", "5mm"],
                        "to": "In1.Cu",
                        "layers": ["F.Cu", "In1.Cu", "B.Cu"],
                    },
                    ["20mm", "5mm"],
                    "J1.1",
                ],
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert board.nets["N1"].vias[0].layers == ("F.Cu", "In1.Cu", "B.Cu")
    assert board.nets["N1"].vias[0].via_type == "through"
    assert {segment.layer for segment in board.nets["N1"].segments} == {"F.Cu", "In1.Cu"}


def test_direct_route_non_strict_skips_violations():
    board = _board()
    blocker = Net("BLOCK", "2", track_width=0.1)
    board.add_net(blocker)
    commit_route_candidate(
        board,
        RouteCandidate("BLOCK", [TraceSegment("BLOCK", (15, 5), (15, 20), "F.Cu", 0.1)]),
    )
    spec = _spec([{"kind": "direct", "net": "N1", "layer": "F.Cu"}])
    report, violations = apply_routes(board, spec, strict=False)
    assert violations
    assert report[0].committed is False


def test_direct_route_strict_raises_on_violation():
    board = _board()
    blocker = Net("BLOCK", "2", track_width=0.1)
    board.add_net(blocker)
    commit_route_candidate(
        board,
        RouteCandidate("BLOCK", [TraceSegment("BLOCK", (15, 5), (15, 20), "F.Cu", 0.1)]),
    )
    spec = _spec([{"kind": "direct", "net": "N1", "layer": "F.Cu"}])
    with pytest.raises(RouteCommitFailureError) as exc:
        apply_routes(board, spec, strict=True)
    failure = exc.value.report
    assert failure.net == "N1"
    assert failure.route_name == "direct[0001]"
    assert failure.route_index == 0
    assert failure.strategy == "direct"
    assert failure.candidate.used_layers == ()
    assert any(v.code == "track_to_track_clearance" for v in failure.violations)


def test_header_bank_routes_each_listed_net_between_refs():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert [entry.net for entry in report] == ["N1"]
    assert all(entry.committed for entry in report)
    assert len(board.nets["N1"].segments) == 1


def test_header_bank_raises_when_ref_not_in_net_connections():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J9",
                "nets": ["N1"],
            }
        ]
    )
    with pytest.raises(ValueError, match="has no pad on 'J9'"):
        apply_routes(board, spec, strict=True)


def test_header_bank_supports_shared_waypoints():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "F.Cu",
                "waypoints": [["12mm", "8mm"], ["18mm", "8mm"]],
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    segments = board.nets["N1"].segments
    assert len(segments) == 3
    assert segments[0].end == (12.0, 8.0)
    assert segments[1].end == (18.0, 8.0)


def test_header_bank_supports_per_net_waypoints():
    board = _board()
    net2 = Net("N2", "2", track_width=0.1)
    net2.add_connection("U1", "2")
    net2.add_connection("J1", "2")
    board.add_net(net2)
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1", "N2"],
                "layer": "F.Cu",
                "waypoints_by_net": {
                    "N1": [["12mm", "8mm"]],
                    "N2": [["14mm", "12mm"]],
                },
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=False)
    assert report
    assert [entry.net for entry in report] == ["N1", "N2"]
    assert len(board.nets["N1"].segments) >= 1


def test_header_bank_supports_per_net_start_override():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
                "from_by_net": {"N1": ["8mm", "10mm"]},
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert board.nets["N1"].segments[0].start == (8.0, 10.0)


def test_header_bank_alternative_commits_when_base_candidate_fails():
    board = _board()
    blocker = Net("N2", "2", track_width=0.1)
    blocker.add_connection("U1", "2")
    blocker.add_connection("J1", "2")
    blocker.segments.append(
        TraceSegment("N2", (12.0, 10.0), (18.0, 10.0), "F.Cu", 0.1)
    )
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "F.Cu",
                "alternatives_by_net": {
                    "N1": [
                        {
                            "name": "shifted_fcu_lane",
                            "waypoints": [["12mm", "8mm"], ["18mm", "8mm"]],
                        }
                    ]
                },
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].alternative_name == "shifted_fcu_lane"
    assert [segment.end for segment in board.nets["N1"].segments] == [
        (12.0, 8.0),
        (18.0, 8.0),
        (20.0, 10.0),
    ]


def test_header_bank_selects_alternative_for_valid_bundle():
    board = _wide_board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1", "N2"],
                "layer": "F.Cu",
                "alternatives_by_net": {
                    "N1": [
                        {
                            "name": "shifted_fcu_lane",
                            "waypoints": [["12mm", "8mm"], ["18mm", "8mm"]],
                        }
                    ]
                },
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert [entry.net for entry in report] == ["N1", "N2"]
    assert [entry.committed for entry in report] == [True, True]
    assert report[0].alternative_name == "shifted_fcu_lane"
    assert len(board.nets["N1"].segments) == 3
    assert len(board.nets["N2"].segments) == 1


def test_header_bank_all_alternatives_fail_reports_candidate_names():
    board = _board()
    blocker = Net("N2", "2", track_width=0.1)
    blocker.add_connection("U1", "2")
    blocker.add_connection("J1", "2")
    blocker.segments.extend(
        [
            TraceSegment("N2", (12.0, 10.0), (18.0, 10.0), "F.Cu", 0.1),
            TraceSegment("N2", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1),
        ]
    )
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "F.Cu",
                "alternatives_by_net": {
                    "N1": [
                        {
                            "name": "blocked_shifted_fcu_lane",
                            "waypoints": [["12mm", "8mm"], ["18mm", "8mm"]],
                        }
                    ]
                },
            }
        ]
    )
    with pytest.raises(RouteCommitFailureError) as exc:
        apply_routes(board, spec, strict=True)
    assert [failure.alternative_name for failure in exc.value.reports] == [
        "",
        "blocked_shifted_fcu_lane",
    ]
    diagnostics = format_route_failures_json(exc.value.reports)
    assert '"alternative_name": "blocked_shifted_fcu_lane"' in diagnostics


def test_header_bank_strict_bundle_failure_leaves_real_board_unmodified():
    board = _wide_board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1", "N2"],
                "layer": "F.Cu",
            }
        ]
    )
    with pytest.raises(RouteCommitFailureError):
        apply_routes(board, spec, strict=True)
    assert board.nets["N1"].segments == []
    assert board.nets["N2"].segments == []


def test_header_bank_alternative_combinations_are_bounded():
    board = _board()
    nets = [f"N{index}" for index in range(9)]
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": nets,
                "alternatives_by_net": {
                    net: [{"name": "alternate", "waypoints": [["12mm", "8mm"]]}]
                    for net in nets
                },
            }
        ]
    )
    with pytest.raises(ValueError, match=f"exceed {MAX_HEADER_BANK_BUNDLE_COMBINATIONS}"):
        apply_routes(board, spec, strict=True)


def test_escape_bundle_commits_first_staged_passing_assignment():
    board = _wide_board()
    blocker = Net("BLOCK", "3", track_width=0.1)
    blocker.segments.append(TraceSegment("BLOCK", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "name": "two_net_escape",
                "templates": [
                    {
                        "name": "n1_escape",
                        "net": "N1",
                        "start_layer": "F.Cu",
                        "points": ["U1.1", ["12mm", "y:escape_y"], ["18mm", "y:escape_y"], "J1.1"],
                    },
                    {
                        "name": "n2_escape",
                        "net": "N2",
                        "start_layer": "B.Cu",
                        "points": [
                            "U1.2",
                            ["x:n2_x", "y:n2_y"],
                            {"via": ["x:n2_x", "y:n2_y"], "to": "F.Cu"},
                            "J1.2",
                        ],
                    },
                ],
                "variables": {
                    "escape_y": {"values": ["8mm", "6mm"]},
                    "n2_x": {"values": ["16mm"]},
                    "n2_y": {"values": ["16mm"]},
                },
            }
        ]
    )

    report, violations = apply_routes(board, spec, strict=True)

    assert not violations
    assert [entry.net for entry in report] == ["N1", "N2"]
    assert all(entry.strategy == "escape_bundle" for entry in report)
    assert all(entry.committed for entry in report)
    assert board.nets["N1"].segments[0].end == (12.0, 6.0)
    assert len(board.nets["N2"].vias) == 1


def test_route_group_dispatches_to_escape_bundle_behavior():
    board = _wide_board()
    blocker = Net("BLOCK", "3", track_width=0.1)
    blocker.segments.append(TraceSegment("BLOCK", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "route_group",
                "name": "two_net_public_group",
                "templates": [
                    {
                        "name": "n1_escape",
                        "net": "N1",
                        "start_layer": "F.Cu",
                        "points": ["U1.1", ["12mm", "y:escape_y"], ["18mm", "y:escape_y"], "J1.1"],
                    },
                    {
                        "name": "n2_escape",
                        "net": "N2",
                        "start_layer": "B.Cu",
                        "points": [
                            "U1.2",
                            ["x:n2_x", "y:n2_y"],
                            {"via": ["x:n2_x", "y:n2_y"], "to": "F.Cu"},
                            "J1.2",
                        ],
                    },
                ],
                "variables": {
                    "escape_y": {"values": ["8mm", "6mm"]},
                    "n2_x": {"values": ["16mm"]},
                    "n2_y": {"values": ["16mm"]},
                },
            }
        ]
    )

    report, violations = apply_routes(board, spec, strict=True)

    assert not violations
    assert [entry.net for entry in report] == ["N1", "N2"]
    assert all(entry.strategy == "escape_bundle" for entry in report)
    assert all(entry.route_name == "two_net_public_group" for entry in report)
    assert board.nets["N1"].segments[0].end == (12.0, 6.0)
    assert len(board.nets["N2"].vias) == 1


def test_route_group_accepts_optional_schema_metadata_without_changing_behavior():
    board = _wide_board()
    blocker = Net("BLOCK", "3", track_width=0.1)
    blocker.segments.append(TraceSegment("BLOCK", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "route_group",
                "name": "two_net_public_group",
                "schema_version": 1,
                "group": ["route", "escape"],
                "description": "metadata-only route group",
                "library": {
                    "entry_id": "icsp_corridor_placeholder",
                    "pattern_family": "icsp_corridor",
                    "expanded_by": "physical_libraries.catalog",
                    "catalog_schema_version": 1,
                    "parameters": {"connector_ref": "J1"},
                },
                "templates": [
                    {
                        "name": "n1_escape",
                        "net": "N1",
                        "start_layer": "F.Cu",
                        "points": ["U1.1", ["12mm", "y:escape_y"], ["18mm", "y:escape_y"], "J1.1"],
                    },
                    {
                        "name": "n2_escape",
                        "net": "N2",
                        "start_layer": "B.Cu",
                        "points": [
                            "U1.2",
                            ["x:n2_x", "y:n2_y"],
                            {"via": ["x:n2_x", "y:n2_y"], "to": "F.Cu"},
                            "J1.2",
                        ],
                    },
                ],
                "variables": {
                    "escape_y": {"values": ["8mm", "6mm"]},
                    "n2_x": {"values": ["16mm"]},
                    "n2_y": {"values": ["16mm"]},
                },
            }
        ]
    )

    report, violations = apply_routes(board, spec, strict=True)

    assert not violations
    assert [entry.net for entry in report] == ["N1", "N2"]
    assert all(entry.strategy == "escape_bundle" for entry in report)
    assert all(entry.route_name == "two_net_public_group" for entry in report)
    assert board.nets["N1"].segments[0].end == (12.0, 6.0)
    assert len(board.nets["N2"].vias) == 1


def test_route_group_rejects_invalid_schema_version_before_mutation():
    board = _wide_board()
    original_positions = {ref: comp.position for ref, comp in board.components.items()}
    original_segments = {name: list(net.segments) for name, net in board.nets.items()}
    original_vias = {name: list(net.vias) for name, net in board.nets.items()}
    spec = _spec(
        [
            {
                "kind": "route_group",
                "name": "two_net_public_group",
                "schema_version": 2,
                "templates": [
                    {"name": "n1", "net": "N1", "points": ["U1.1", "J1.1"]},
                    {"name": "n2", "net": "N2", "points": ["U1.2", "J1.2"]},
                ],
            }
        ]
    )

    with pytest.raises(ValueError, match="route_group schema_version must be integer 1"):
        apply_routes(board, spec, strict=True)

    assert {ref: comp.position for ref, comp in board.components.items()} == original_positions
    assert {name: list(net.segments) for name, net in board.nets.items()} == original_segments
    assert {name: list(net.vias) for name, net in board.nets.items()} == original_vias


def test_route_group_rejects_malformed_library_metadata_before_mutation():
    board = _wide_board()
    original_positions = {ref: comp.position for ref, comp in board.components.items()}
    spec = _spec(
        [
            {
                "kind": "route_group",
                "name": "two_net_public_group",
                "library": {
                    "entry_id": "",
                    "pattern_family": "icsp_corridor",
                    "expanded_by": "physical_libraries.catalog",
                    "catalog_schema_version": 1,
                },
                "templates": [
                    {"name": "n1", "net": "N1", "points": ["U1.1", "J1.1"]},
                    {"name": "n2", "net": "N2", "points": ["U1.2", "J1.2"]},
                ],
            }
        ]
    )

    with pytest.raises(ValueError, match="route_group library.entry_id must be a non-empty string"):
        apply_routes(board, spec, strict=True)

    assert {ref: comp.position for ref, comp in board.components.items()} == original_positions
    assert board.nets["N1"].segments == []
    assert board.nets["N2"].segments == []


def test_route_group_requires_non_empty_name():
    board = _wide_board()
    spec = _spec(
        [
            {
                "kind": "route_group",
                "templates": [
                    {"name": "n1", "net": "N1", "points": ["U1.1", "J1.1"]},
                    {"name": "n2", "net": "N2", "points": ["U1.2", "J1.2"]},
                ],
            }
        ]
    )

    with pytest.raises(ValueError, match="route_group requires a non-empty name"):
        apply_routes(board, spec, strict=True)


def test_escape_bundle_placement_move_can_make_route_assignment_pass():
    board = _wide_board()
    board.components["U1"].pads[1].position_offset = (4.0, 4.0)
    board.components["J1"].pads[1].position_offset = (0.0, 8.0)
    blocker = Net("BLOCK", "3", track_width=0.1)
    blocker.segments.append(TraceSegment("BLOCK", (12.0, 10.0), (18.0, 10.0), "F.Cu", 0.1))
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "name": "move_pair_escape",
                "placement_variables": {"shift_y": {"values": ["0mm", "-4mm"]}},
                "placement_moves": [
                    {"name": "move_pair", "refs": ["U1", "J1"], "dx": "0mm", "dy": "y:shift_y"}
                ],
                "templates": [
                    {"name": "n1_direct", "net": "N1", "start_layer": "F.Cu", "points": ["U1.1", "J1.1"]},
                    {"name": "n2_direct", "net": "N2", "start_layer": "B.Cu", "points": ["U1.2", "J1.2"]},
                ],
            }
        ]
    )

    report, violations = apply_routes(board, spec, strict=True)

    assert not violations
    assert [entry.net for entry in report] == ["N1", "N2"]
    assert board.components["U1"].position == (10.0, 6.0)
    assert board.components["J1"].position == (20.0, 6.0)
    assert board.nets["N1"].segments[0].start == (10.0, 6.0)
    assert board.nets["N1"].segments[0].end == (20.0, 6.0)


def test_escape_bundle_strict_failure_leaves_real_board_unmodified_and_reports_assignment():
    board = _wide_board()
    blocker = Net("BLOCK", "3", track_width=0.1)
    blocker.segments.append(TraceSegment("BLOCK", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "templates": [
                    {
                        "name": "blocked_n1",
                        "net": "N1",
                        "start_layer": "F.Cu",
                        "points": ["U1.1", ["x:n1_x", "y:escape_y"], "J1.1"],
                    },
                    {
                        "name": "n2_escape",
                        "net": "N2",
                        "start_layer": "B.Cu",
                        "points": ["U1.2", ["16mm", "16mm"], "J1.2"],
                    },
                ],
                "variables": {
                    "escape_y": {"values": ["8mm"]},
                    "n1_x": {"values": ["15mm"]},
                },
            }
        ]
    )

    with pytest.raises(RouteCommitFailureError) as exc:
        apply_routes(board, spec, strict=True)

    assert board.nets["N1"].segments == []
    assert board.nets["N2"].segments == []
    failure = exc.value.reports[0]
    assert failure.strategy == "escape_bundle"
    assert failure.template_name == "blocked_n1"
    assert failure.assignment == {"escape_y": 8.0, "n1_x": 15.0}
    diagnostics = format_route_failures_json(exc.value.reports)
    assert '"template_name": "blocked_n1"' in diagnostics
    assert '"escape_y": 8.0' in diagnostics


def test_escape_bundle_failed_placement_fanout_assignment_leaves_real_board_unmodified():
    board = _wide_board()
    original_positions = {ref: comp.position for ref, comp in board.components.items()}
    original_segments = {name: list(net.segments) for name, net in board.nets.items()}
    original_vias = {name: list(net.vias) for name, net in board.nets.items()}
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "placement_variables": {"shift_y": {"values": ["-2mm"]}},
                "placement_moves": [
                    {"name": "move_pair", "refs": ["U1", "J1"], "dy": "y:shift_y"}
                ],
                "fanout_templates": [
                    {
                        "name": "n1_fanout",
                        "ref": "U1",
                        "pin": "1",
                        "net": "N1",
                        "points": [["12mm", "8mm"], {"via": ["12mm", "8mm"], "to": "B.Cu"}],
                    }
                ],
                "templates": [
                    {"name": "blocked_n1", "net": "N1", "start_layer": "F.Cu", "points": ["U1.1", ["12mm", "8mm"]]},
                    {"name": "n2_direct", "net": "N2", "start_layer": "F.Cu", "points": ["U1.2", ["12mm", "8mm"]]},
                ],
            }
        ]
    )

    with pytest.raises(RouteCommitFailureError):
        apply_routes(board, spec, strict=True)

    assert {ref: comp.position for ref, comp in board.components.items()} == original_positions
    assert {name: net.segments for name, net in board.nets.items()} == original_segments
    assert {name: net.vias for name, net in board.nets.items()} == original_vias


def test_escape_bundle_fanout_template_is_staged_before_route_templates():
    board = _wide_board()
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "variables": {"n2_y": {"values": ["10mm", "16mm"]}},
                "fanout_templates": [
                    {
                        "name": "n1_local_fanout",
                        "ref": "U1",
                        "pin": "1",
                        "net": "N1",
                        "start_layer": "F.Cu",
                        "points": [["12mm", "10mm"], {"via": ["12mm", "10mm"], "to": "B.Cu"}],
                    }
                ],
                "templates": [
                    {"name": "n1_finish", "net": "N1", "start_layer": "B.Cu", "points": [["12mm", "10mm"], "J1.1"]},
                    {"name": "n2_escape", "net": "N2", "start_layer": "F.Cu", "points": ["U1.2", ["12mm", "y:n2_y"], "J1.2"]},
                ],
            }
        ]
    )

    report, violations = apply_routes(board, spec, strict=True)

    assert not violations
    assert [entry.alternative_name.split(":", 1)[0] for entry in report] == [
        "n1_local_fanout",
        "n1_finish",
        "n2_escape",
    ]
    assert report[0].strategy == "escape_bundle_fanout"
    assert len(board.nets["N1"].vias) == 1
    assert board.nets["N2"].segments[0].end == (12.0, 16.0)


def test_escape_bundle_candidate_assignments_are_bounded():
    board = _wide_board()
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "templates": [
                    {"name": "n1", "net": "N1", "points": ["U1.1", "J1.1"]},
                    {"name": "n2", "net": "N2", "points": ["U1.2", "J1.2"]},
                ],
                "variables": {
                    "x": {"values": [f"{index}mm" for index in range(MAX_ESCAPE_BUNDLE_CANDIDATES + 1)]}
                },
            }
        ]
    )
    with pytest.raises(ValueError, match=f"exceed {MAX_ESCAPE_BUNDLE_CANDIDATES}"):
        apply_routes(board, spec, strict=True)


def test_escape_bundle_combined_candidate_assignments_are_bounded_before_mutation():
    board = _wide_board()
    original_position = board.components["U1"].position
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "placement_variables": {
                    "dy": {"values": [f"{index}mm" for index in range(33)]},
                },
                "fanout_variables": {
                    "via_x": {"values": [f"{index}mm" for index in range(17)]},
                },
                "placement_moves": [{"name": "move_u1", "refs": ["U1"], "dy": "y:dy"}],
                "fanout_templates": [
                    {"name": "n1_fanout", "ref": "U1", "pin": "1", "net": "N1", "points": [["x:via_x", "20mm"]]}
                ],
                "templates": [
                    {"name": "n1", "net": "N1", "points": ["U1.1", "J1.1"]},
                    {"name": "n2", "net": "N2", "points": ["U1.2", "J1.2"]},
                ],
            }
        ]
    )

    with pytest.raises(ValueError, match=f"exceed {MAX_ESCAPE_BUNDLE_CANDIDATES}"):
        apply_routes(board, spec, strict=True)
    assert board.components["U1"].position == original_position
    assert board.nets["N1"].segments == []
    assert board.nets["N1"].vias == []


def test_escape_bundle_placement_diagnostics_include_assignment_stage_and_moved_refs():
    board = _wide_board()
    blocker = Net("BLOCK", "3", track_width=0.1)
    blocker.segments.append(TraceSegment("BLOCK", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "placement_variables": {"shift_y": {"values": ["-2mm"]}},
                "placement_moves": [{"name": "move_u1", "refs": ["U1"], "dy": "y:shift_y"}],
                "templates": [
                    {"name": "blocked_n1", "net": "N1", "start_layer": "F.Cu", "points": ["U1.1", ["15mm", "8mm"], "J1.1"]},
                    {"name": "n2_direct", "net": "N2", "start_layer": "B.Cu", "points": ["U1.2", "J1.2"]},
                ],
            }
        ]
    )

    with pytest.raises(RouteCommitFailureError) as exc:
        apply_routes(board, spec, strict=True)

    failure = exc.value.reports[0]
    assert failure.failed_stage == "route_template"
    assert failure.template_name == "blocked_n1"
    assert failure.assignment == {"shift_y": -2.0}
    assert failure.moved_refs == ("U1",)
    diagnostics = format_route_failures_json(exc.value.reports)
    assert '"failed_stage": "route_template"' in diagnostics
    assert '"moved_refs": [' in diagnostics
    assert '"ref": "U1"' in diagnostics


def test_escape_bundle_replace_existing_net_clears_before_validation():
    board = _wide_board()
    old = Net("OLD", "3", track_width=0.1)
    old.segments.append(TraceSegment("OLD", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    old.vias.append(Via("OLD", (16.0, 8.0), 0.8, 0.4, ("F.Cu", "B.Cu")))
    board.add_net(old)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "name": "replace_old_lane",
                "replace_existing": {
                    "nets": ["OLD"],
                    "refs": [],
                    "include_fanout": True,
                    "require_all_nets": True,
                    "max_removed_segments": 4,
                    "max_removed_vias": 4,
                    "allow_power_nets": False,
                },
                "templates": [
                    {"name": "n1_cross_old", "net": "N1", "start_layer": "F.Cu", "points": ["U1.1", ["15mm", "8mm"], "J1.1"]},
                    {"name": "old_replacement", "net": "OLD", "start_layer": "B.Cu", "points": [["30mm", "30mm"], ["35mm", "30mm"]]},
                ],
            }
        ]
    )

    report, violations = apply_routes(board, spec, strict=True)

    assert not violations
    assert [entry.net for entry in report] == ["N1", "OLD"]
    assert board.nets["OLD"].segments == [
        TraceSegment("OLD", (30.0, 30.0), (35.0, 30.0), "B.Cu", 0.1)
    ]
    assert board.nets["OLD"].vias == []
    assert report[0].replacement_removed_segments == 1
    assert report[0].replacement_removed_vias == 1
    assert report[0].replacement_nets == ("OLD",)


def test_escape_bundle_replace_requires_template_for_each_cleared_net():
    board = _wide_board()
    old = Net("OLD", "3", track_width=0.1)
    old.segments.append(TraceSegment("OLD", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(old)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "replace_existing": {"nets": ["OLD"]},
                "templates": [
                    {"name": "n1", "net": "N1", "points": ["U1.1", "J1.1"]},
                    {"name": "n2", "net": "N2", "points": ["U1.2", "J1.2"]},
                ],
            }
        ]
    )

    with pytest.raises(ValueError, match="lack replacement templates"):
        apply_routes(board, spec, strict=True)

    assert len(board.nets["OLD"].segments) == 1


def test_escape_bundle_replace_failure_leaves_real_board_unmodified():
    board = _wide_board()
    old = Net("OLD", "3", track_width=0.1)
    old.segments.append(TraceSegment("OLD", (40.0, 40.0), (45.0, 40.0), "F.Cu", 0.1))
    old.vias.append(Via("OLD", (42.0, 40.0), 0.8, 0.4, ("F.Cu", "B.Cu")))
    board.add_net(old)
    blocker = Net("BLOCK", "4", track_width=0.1)
    blocker.segments.append(TraceSegment("BLOCK", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(blocker)
    original_old_segments = list(board.nets["OLD"].segments)
    original_old_vias = list(board.nets["OLD"].vias)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "replace_existing": {"nets": ["OLD"]},
                "templates": [
                    {"name": "blocked_n1", "net": "N1", "start_layer": "F.Cu", "points": ["U1.1", ["15mm", "8mm"], "J1.1"]},
                    {"name": "old_replacement", "net": "OLD", "start_layer": "B.Cu", "points": [["30mm", "30mm"], ["35mm", "30mm"]]},
                ],
            }
        ]
    )

    with pytest.raises(RouteCommitFailureError):
        apply_routes(board, spec, strict=True)

    assert board.nets["OLD"].segments == original_old_segments
    assert board.nets["OLD"].vias == original_old_vias
    assert board.nets["N1"].segments == []


def test_escape_bundle_replace_does_not_clear_unnamed_neighbor():
    board = _wide_board()
    old = Net("OLD", "3", track_width=0.1)
    old.segments.append(TraceSegment("OLD", (40.0, 40.0), (45.0, 40.0), "F.Cu", 0.1))
    board.add_net(old)
    neighbor = Net("NEIGHBOR", "4", track_width=0.1)
    neighbor.segments.append(TraceSegment("NEIGHBOR", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(neighbor)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "replace_existing": {"nets": ["OLD"]},
                "templates": [
                    {"name": "blocked_by_neighbor", "net": "N1", "start_layer": "F.Cu", "points": ["U1.1", ["15mm", "8mm"], "J1.1"]},
                    {"name": "old_replacement", "net": "OLD", "start_layer": "B.Cu", "points": [["30mm", "30mm"], ["35mm", "30mm"]]},
                ],
            }
        ]
    )

    with pytest.raises(RouteCommitFailureError) as exc:
        apply_routes(board, spec, strict=True)

    assert board.nets["NEIGHBOR"].segments == [
        TraceSegment("NEIGHBOR", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1)
    ]
    diagnostics = format_route_failures_json(exc.value.reports)
    assert "NEIGHBOR" in diagnostics


def test_escape_bundle_replace_reports_removed_counts():
    board = _wide_board()
    old = Net("OLD", "3", track_width=0.1)
    old.segments.append(TraceSegment("OLD", (40.0, 40.0), (45.0, 40.0), "F.Cu", 0.1))
    old.vias.append(Via("OLD", (42.0, 40.0), 0.8, 0.4, ("F.Cu", "B.Cu")))
    board.add_net(old)
    blocker = Net("BLOCK", "4", track_width=0.1)
    blocker.segments.append(TraceSegment("BLOCK", (12.0, 8.0), (18.0, 8.0), "F.Cu", 0.1))
    board.add_net(blocker)
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "name": "diagnose_replace",
                "replace_existing": {"nets": ["OLD"]},
                "templates": [
                    {"name": "blocked_n1", "net": "N1", "start_layer": "F.Cu", "points": ["U1.1", ["15mm", "8mm"], "J1.1"]},
                    {"name": "old_replacement", "net": "OLD", "start_layer": "B.Cu", "points": [["30mm", "30mm"], ["35mm", "30mm"]]},
                ],
            }
        ]
    )

    with pytest.raises(RouteCommitFailureError) as exc:
        apply_routes(board, spec, strict=True)

    failure = exc.value.reports[0]
    assert failure.replacement_report is not None
    assert failure.replacement_report.removed_segments == 1
    assert failure.replacement_report.removed_vias == 1
    diagnostics = format_route_failures_json(exc.value.reports)
    assert '"replacement": {' in diagnostics
    assert '"removed_segments": 1' in diagnostics
    assert '"removed_vias": 1' in diagnostics


def test_escape_bundle_committed_routes_remain_under_layer_role_policy():
    board = _wide_board()
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "templates": [
                    {"name": "n1_inner", "net": "N1", "start_layer": "In1.Cu", "points": ["U1.1", "J1.1"]},
                    {"name": "n2_front", "net": "N2", "start_layer": "F.Cu", "points": ["U1.2", "J1.2"]},
                ],
            }
        ]
    )
    spec = replace(spec, layer_roles={"F.Cu": "signal", "In1.Cu": "power_plane", "B.Cu": "signal"})

    route_report, violations = apply_routes(board, spec, strict=True)
    checks = []
    _check_route_layer_policy(
        spec,
        route_report,
        lambda severity, code, message, source="": checks.append((severity, code, message, source)),
    )

    assert not violations
    assert "route.layer_role_forbidden" in {code for _severity, code, _message, _source in checks}


def test_escape_bundle_fanout_routes_remain_under_layer_role_policy():
    board = _wide_board()
    spec = _spec(
        [
            {
                "kind": "escape_bundle",
                "fanout_templates": [
                    {
                        "name": "n1_inner_fanout",
                        "ref": "U1",
                        "pin": "1",
                        "net": "N1",
                        "start_layer": "In1.Cu",
                        "points": [["12mm", "16mm"]],
                    }
                ],
                "templates": [
                    {"name": "n1_finish", "net": "N1", "start_layer": "F.Cu", "points": [["12mm", "16mm"], "J1.1"]},
                    {"name": "n2_back", "net": "N2", "start_layer": "B.Cu", "points": ["U1.2", ["30mm", "30mm"], "J1.2"]},
                ],
            }
        ]
    )
    spec = replace(spec, layer_roles={"F.Cu": "signal", "In1.Cu": "power_plane", "B.Cu": "signal"})

    route_report, violations = apply_routes(board, spec, strict=True)
    checks = []
    _check_route_layer_policy(
        spec,
        route_report,
        lambda severity, code, message, source="": checks.append((severity, code, message, source)),
    )

    assert not violations
    assert route_report[0].strategy == "escape_bundle_fanout"
    assert "route.layer_role_forbidden" in {code for _severity, code, _message, _source in checks}


def test_header_bank_corridor_generates_lane_points_and_via():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "F.Cu",
                "corridor": {
                    "axis": "x",
                    "entry_by_net": {"N1": ["10mm", "8mm"]},
                    "via_at": "entry",
                    "via_to": "B.Cu",
                    "via_layers": ["F.Cu", "In1.Cu", "B.Cu"],
                    "run_to_x": "14mm",
                    "run_base": "8mm",
                    "run_lane_pitch": "1mm",
                    "exit_x": "18mm",
                    "exit_base": "8mm",
                    "exit_lane_pitch": "1mm",
                },
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].vias == 1
    assert board.nets["N1"].vias[0].position == (10.0, 8.0)
    assert board.nets["N1"].vias[0].layers == ("F.Cu", "In1.Cu", "B.Cu")
    assert [segment.end for segment in board.nets["N1"].segments[:3]] == [
        (10.0, 8.0),
        (14.0, 8.0),
        (18.0, 8.0),
    ]


def test_header_bank_corridor_ref_uses_named_lane_points():
    board = _wide_board()
    corridor = RouteCorridorIntent(
        name="icsp_gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=51.0,
        run_to_x=63.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=34.0,
        lane_pitch=0.65,
        lane_width=0.35,
        clearance=0.20,
        lanes={
            "rd5": RouteCorridorLaneIntent(
                name="rd5",
                index=0,
                nets=("N1",),
                raw={},
            )
        },
        raw={},
    )
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
                "corridor": {
                    "ref": "icsp_gpio_b_bcu",
                    "lane_by_net": {"N1": 0},
                },
            }
        ],
        route_corridors={"icsp_gpio_b_bcu": corridor},
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert [segment.end for segment in board.nets["N1"].segments] == [
        (51.0, 34.0),
        (63.0, 34.0),
        (20.0, 10.0),
    ]


def test_header_bank_corridor_ref_uses_lane_handoff_points():
    board = _wide_board()
    corridor = RouteCorridorIntent(
        name="icsp_gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=51.0,
        run_to_x=63.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=34.0,
        lane_pitch=0.65,
        lane_width=0.35,
        clearance=0.20,
        lanes={
            "rd5": RouteCorridorLaneIntent(
                name="rd5",
                index=0,
                nets=("N1",),
                entry_points=((50.0, 33.5),),
                exit_points=((64.0, 33.5), (64.0, 35.0)),
                raw={},
            )
        },
        raw={},
    )
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
                "corridor": {
                    "ref": "icsp_gpio_b_bcu",
                    "lane_by_net": {"N1": 0},
                },
            }
        ],
        route_corridors={"icsp_gpio_b_bcu": corridor},
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert [segment.end for segment in board.nets["N1"].segments] == [
        (50.0, 33.5),
        (51.0, 34.0),
        (63.0, 34.0),
        (64.0, 33.5),
        (64.0, 35.0),
        (20.0, 10.0),
    ]


def test_header_bank_corridor_ref_uses_lane_pre_points_before_entry_and_run():
    board = _wide_board()
    corridor = RouteCorridorIntent(
        name="icsp_gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=51.0,
        run_to_x=63.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=34.0,
        lane_pitch=0.65,
        lane_width=0.35,
        clearance=0.20,
        lanes={
            "rd5": RouteCorridorLaneIntent(
                name="rd5",
                index=0,
                nets=("N1",),
                pre_points=((48.0, 33.0), (49.0, 33.0)),
                raw={},
            )
        },
        raw={},
    )
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
                "corridor": {
                    "ref": "icsp_gpio_b_bcu",
                    "entry_by_net": {"N1": ["50mm", "33.5mm"]},
                },
            }
        ],
        route_corridors={"icsp_gpio_b_bcu": corridor},
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert [segment.end for segment in board.nets["N1"].segments] == [
        (48.0, 33.0),
        (49.0, 33.0),
        (50.0, 33.5),
        (51.0, 34.0),
        (63.0, 34.0),
        (20.0, 10.0),
    ]


def test_header_bank_corridor_ref_lane_pre_points_can_via_before_run():
    board = _wide_board()
    corridor = RouteCorridorIntent(
        name="icsp_gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=51.0,
        run_to_x=63.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=34.0,
        lane_pitch=0.65,
        lane_width=0.35,
        clearance=0.20,
        lanes={
            "rd5": RouteCorridorLaneIntent(
                name="rd5",
                index=0,
                nets=("N1",),
                pre_points=(
                    ["48mm", "33mm"],
                    {"via": ["49mm", "33mm"], "to": "B.Cu", "layers": ["F.Cu", "B.Cu"]},
                ),
                raw={},
            )
        },
        raw={},
    )
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "F.Cu",
                "corridor": {
                    "ref": "icsp_gpio_b_bcu",
                    "entry_by_net": {"N1": ["50mm", "33.5mm"]},
                },
            }
        ],
        route_corridors={"icsp_gpio_b_bcu": corridor},
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].vias == 1
    assert board.nets["N1"].vias[0].position == (49.0, 33.0)
    assert [segment.end for segment in board.nets["N1"].segments[:4]] == [
        (48.0, 33.0),
        (49.0, 33.0),
        (50.0, 33.5),
        (51.0, 34.0),
    ]
    assert [segment.layer for segment in board.nets["N1"].segments[:4]] == [
        "F.Cu",
        "F.Cu",
        "B.Cu",
        "B.Cu",
    ]


def test_header_bank_corridor_ref_uses_lane_run_overrides():
    board = _wide_board()
    corridor = RouteCorridorIntent(
        name="icsp_gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=51.0,
        run_to_x=63.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=34.0,
        lane_pitch=0.65,
        lane_width=0.35,
        clearance=0.20,
        lanes={
            "rd5": RouteCorridorLaneIntent(
                name="rd5",
                index=0,
                nets=("N1",),
                run_from_x=52.0,
                run_to_x=61.0,
                raw={},
            )
        },
        raw={},
    )
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
                "corridor": {"ref": "icsp_gpio_b_bcu"},
            }
        ],
        route_corridors={"icsp_gpio_b_bcu": corridor},
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert [segment.end for segment in board.nets["N1"].segments] == [
        (52.0, 34.0),
        (61.0, 34.0),
        (20.0, 10.0),
    ]


def test_header_bank_corridor_lane_handoff_points_can_include_vias():
    board = _wide_board()
    corridor = RouteCorridorIntent(
        name="icsp_gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=51.0,
        run_to_x=63.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=34.0,
        lane_pitch=0.65,
        lane_width=0.35,
        clearance=0.20,
        lanes={
            "rd5": RouteCorridorLaneIntent(
                name="rd5",
                index=0,
                nets=("N1",),
                exit_points=(
                    {"via": ["64mm", "34mm"], "to": "F.Cu", "layers": ["F.Cu", "B.Cu"]},
                    ["64mm", "35mm"],
                ),
                raw={},
            )
        },
        raw={},
    )
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
                "corridor": {"ref": "icsp_gpio_b_bcu"},
            }
        ],
        route_corridors={"icsp_gpio_b_bcu": corridor},
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].vias == 1
    assert board.nets["N1"].vias[0].position == (64.0, 34.0)
    assert board.nets["N1"].segments[-1].layer == "F.Cu"


def test_unassigned_net_hits_reserved_lane_keepout():
    board = _wide_board()
    corridor = RouteCorridorIntent(
        name="icsp_gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=51.0,
        run_to_x=63.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=34.0,
        lane_pitch=0.65,
        lane_width=0.35,
        clearance=0.20,
        lanes={
            "rd5": RouteCorridorLaneIntent(
                name="rd5",
                index=0,
                nets=("N1",),
                raw={},
            )
        },
        raw={},
    )
    spec = _spec(
        [
            {
                "kind": "manual_polyline",
                "net": "N2",
                "layer": "B.Cu",
                "points": ["U1.2", ["51mm", "34mm"], "J1.2"],
            }
        ],
        route_corridors={"icsp_gpio_b_bcu": corridor},
    )
    report, violations = apply_routes(board, spec, strict=False)
    assert report[0].committed is False
    assert any(v.code == "route_keepout_violation" for v in violations)


def test_route_corridor_keepouts_use_lane_run_overrides():
    corridor = RouteCorridorIntent(
        name="gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=60.0,
        run_to_x=82.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=36.4,
        lane_pitch=1.6,
        lane_width=0.12,
        clearance=0.20,
        lanes={
            "rd7": RouteCorridorLaneIntent(
                name="rd7",
                index=0,
                nets=("RD7",),
                run_from_x=60.0,
                run_to_x=64.0,
                raw={},
            ),
            "rd8": RouteCorridorLaneIntent(
                name="rd8",
                index=1,
                nets=("RD8",),
                raw={},
            ),
        },
        raw={},
    )
    keepouts = _build_route_corridor_keepouts({"gpio_b_bcu": corridor})
    rd7_keepout = next(keepout for keepout in keepouts if keepout.name.endswith(".rd7"))
    rd8_keepout = next(keepout for keepout in keepouts if keepout.name.endswith(".rd8"))
    assert rd7_keepout.at == pytest.approx((62.0, 36.4))
    assert rd7_keepout.size == pytest.approx((4.4, 0.52))
    assert rd8_keepout.at == pytest.approx((71.0, 38.0))
    assert rd8_keepout.size == pytest.approx((22.4, 0.52))


def test_shortened_neighbor_lane_keepout_allows_staggered_exit():
    board = _wide_board()
    corridor = RouteCorridorIntent(
        name="gpio_b_bcu",
        layer="B.Cu",
        axis="x",
        run_from_x=60.0,
        run_to_x=82.0,
        run_from_y=None,
        run_to_y=None,
        lane_base=36.4,
        lane_pitch=1.6,
        lane_width=0.12,
        clearance=0.20,
        lanes={
            "rd7": RouteCorridorLaneIntent(
                name="rd7",
                index=0,
                nets=("N1",),
                run_to_x=64.0,
                run_from_x=60.0,
                exit_points=((64.0, 38.0), (84.0, 38.0)),
                raw={},
            ),
            "rd8": RouteCorridorLaneIntent(
                name="rd8",
                index=1,
                nets=("N2",),
                run_from_x=60.0,
                run_to_x=62.0,
                raw={},
            ),
        },
        raw={},
    )
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
                "corridor": {"ref": "gpio_b_bcu"},
            }
        ],
        route_corridors={"gpio_b_bcu": corridor},
    )
    report, violations = apply_routes(board, spec, strict=False)
    assert report[0].committed is True
    assert not violations

    overlapping = RouteCorridorIntent(
        **{
            **corridor.__dict__,
            "lanes": {
                **corridor.lanes,
                "rd8": RouteCorridorLaneIntent(
                    name="rd8",
                    index=1,
                    nets=("N2",),
                    raw={},
                ),
            },
        }
    )
    board = _wide_board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "B.Cu",
                "corridor": {"ref": "gpio_b_bcu"},
            }
        ],
        route_corridors={"gpio_b_bcu": overlapping},
    )
    report, violations = apply_routes(board, spec, strict=False)
    assert report[0].committed is False
    assert any("route_corridor.gpio_b_bcu.lane.rd8" in violation.message for violation in violations)


def test_header_bank_corridor_can_route_direct_after_via():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "F.Cu",
                "corridor": {
                    "axis": "x",
                    "entry_by_net": {"N1": ["10mm", "8mm"]},
                    "via_at": "entry",
                    "via_to_by_net": {"N1": "B.Cu"},
                    "via_layers_by_net": {"N1": ["F.Cu", "In1.Cu", "B.Cu"]},
                    "exit": "direct",
                },
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].segments == 2
    assert board.nets["N1"].vias[0].layers == ("F.Cu", "In1.Cu", "B.Cu")
    assert board.nets["N1"].segments[1].start == (10.0, 8.0)
    assert board.nets["N1"].segments[1].end == (20.0, 10.0)


def test_header_bank_corridor_direct_exit_allows_per_net_post_via_waypoints():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "F.Cu",
                "corridor": {
                    "axis": "x",
                    "entry_by_net": {"N1": ["10mm", "8mm"]},
                    "via_at": "entry",
                    "via_to_by_net": {"N1": "B.Cu"},
                    "via_layers": ["F.Cu", "In1.Cu", "B.Cu"],
                    "exit": "direct",
                },
                "waypoints_by_net": {
                    "N1": [["14mm", "8mm"]],
                },
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].segments == 3
    assert report[0].vias == 1
    assert [segment.end for segment in board.nets["N1"].segments] == [
        (10.0, 8.0),
        (14.0, 8.0),
        (20.0, 10.0),
    ]


def test_header_bank_corridor_direct_exit_allows_multiple_post_via_waypoints():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "header_bank",
                "from_ref": "U1",
                "to_ref": "J1",
                "nets": ["N1"],
                "layer": "F.Cu",
                "corridor": {
                    "axis": "x",
                    "entry_by_net": {"N1": ["10mm", "8mm"]},
                    "via_at": "entry",
                    "via_to": "In1.Cu",
                    "exit": "direct",
                },
                "waypoints_by_net": {
                    "N1": [["14mm", "8mm"], ["14mm", "9mm"]],
                },
            }
        ]
    )
    report, violations = apply_routes(board, spec, strict=True)
    assert not violations
    assert report[0].committed is True
    assert report[0].segments == 4
    assert report[0].vias == 1
    assert board.nets["N1"].vias[0].position == (10.0, 8.0)
    assert [segment.end for segment in board.nets["N1"].segments] == [
        (10.0, 8.0),
        (14.0, 8.0),
        (14.0, 9.0),
        (20.0, 10.0),
    ]


def test_route_group_filter_keeps_ungrouped_and_enabled_routes():
    board = _board()
    board.add_net(Net("N2", "2", track_width=0.1))
    board.nets["N2"].add_connection("U1", "2")
    board.nets["N2"].add_connection("J1", "2")
    spec = _spec(
        [
            {
                "kind": "manual_polyline",
                "net": "N1",
                "layer": "F.Cu",
                "points": ["U1.1", "north 2mm from U1.1", "J1.1"],
            },
            {"kind": "direct", "net": "N2", "layer": "F.Cu", "group": "gpio_b"},
        ]
    )
    report, violations = apply_routes(board, spec, strict=True, enabled_groups={"gpio_a"})
    assert not violations
    assert [entry.net for entry in report] == ["N1"]
    assert len(board.nets["N1"].segments) == 2
    assert not board.nets["N2"].segments


def test_deferred_route_declares_intent_without_emitting_geometry():
    board = _board()
    spec = _spec(
        [
            {
                "name": "future_breakout",
                "kind": "deferred",
                "group": "gpio_b",
                "net": "N1",
                "pads": ["U1.1", "J1.1"],
                "reason": "reserved for a later bank-routing pass",
            }
        ]
    )

    report, violations = apply_routes(board, spec, strict=True)

    assert report == []
    assert violations == []
    assert not board.nets["N1"].segments


def test_deferred_route_validates_net_name():
    board = _board()
    spec = _spec([{"kind": "deferred", "net": "MISSING"}])

    with pytest.raises(ValueError, match="Unknown deferred route net"):
        apply_routes(board, spec, strict=True)
