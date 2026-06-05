from pardal.data_model import Board, Component, Net, Pad
from pardal.physical.fanout import compile_fanouts, compile_qfp_escape_candidates
from pardal.physical.spec import (
    BoardRules,
    FanoutSpec,
    KeepoutIntent,
    PartPlacement,
    PhysicalSpec,
)


def _board(rotation=0) -> Board:
    board = Board()
    board.width = 40
    board.height = 40
    board.layers = ["F.Cu", "In1.Cu", "B.Cu"]
    board.add_component(
        Component(
            "U1",
            "QFP",
            "Package_QFP:TQFP",
            (20.0, 20.0),
            rotation,
            pads=[
                Pad("1", (-5.0, -1.0), (1.5, 0.3)),
                Pad("2", (-5.0, 0.0), (1.5, 0.3)),
                Pad("17", (1.0, -5.0), (0.3, 1.5)),
            ],
        )
    )
    for code, pin in enumerate(["1", "2", "17"], start=1):
        net = Net(f"N{pin}", str(code), track_width=0.1)
        net.add_connection("U1", pin)
        board.add_net(net)
    return board


def _spec(raw):
    return PhysicalSpec(
        path="dummy",
        source_netlist=None,
        width=40,
        height=40,
        stackup="four_layer",
        copper_layers=["F.Cu", "In1.Cu", "B.Cu"],
        rules=BoardRules(),
        parts={"U1": PartPlacement("U1", "Package_QFP:TQFP", (20, 20))},
        netclass_assignments={},
        fanouts={"U1": FanoutSpec("U1", raw)},
    )


def test_qfp_escape_generates_one_via_per_pin():
    board = _board()
    spec = _spec(
        {
            "kind": "qfp_escape",
            "pins": [1, 2],
            "via_layer": "B.Cu",
            "via": {"diameter": "0.5mm", "drill": "0.3mm"},
        }
    )
    reports, violations = compile_fanouts(board, spec, strict=True)
    assert not violations
    assert len(reports) == 2
    assert all(report.vias == 1 for report in reports)
    assert len(board.nets["N1"].vias) == 1
    assert len(board.nets["N2"].vias) == 1


def test_qfp_escape_points_by_pin_emits_authored_segments_in_order():
    board = _board()
    fanout = FanoutSpec(
        "U1",
        {
            "kind": "qfp_escape",
            "pins": [1],
            "layer": "F.Cu",
            "points_by_pin": {
                "1": [
                    ["14.5mm", "18.5mm"],
                    ["13.0mm", "18.5mm"],
                ]
            },
        },
    )

    candidate = compile_qfp_escape_candidates(board, board.components["U1"], fanout)[0]

    assert [segment.start for segment in candidate.segments] == [
        (15.0, 19.0),
        (14.5, 18.5),
    ]
    assert [segment.end for segment in candidate.segments] == [
        (14.5, 18.5),
        (13.0, 18.5),
    ]
    assert [segment.layer for segment in candidate.segments] == ["F.Cu", "F.Cu"]
    assert candidate.vias == []


def test_qfp_escape_points_by_pin_can_end_with_via_to_handoff_layer():
    board = _board()
    fanout = FanoutSpec(
        "U1",
        {
            "kind": "qfp_escape",
            "pins": [1],
            "layer": "F.Cu",
            "via": {"diameter": "0.5mm", "drill": "0.3mm"},
            "points_by_pin": {
                "1": [
                    ["14.5mm", "18.5mm"],
                    {"via": ["13.0mm", "18.5mm"], "to": "B.Cu", "layers": ["F.Cu", "B.Cu"]},
                ]
            },
        },
    )

    candidate = compile_qfp_escape_candidates(board, board.components["U1"], fanout)[0]

    assert [segment.end for segment in candidate.segments] == [
        (14.5, 18.5),
        (13.0, 18.5),
    ]
    assert len(candidate.vias) == 1
    assert candidate.vias[0].position == (13.0, 18.5)
    assert candidate.vias[0].layers == ("F.Cu", "B.Cu")
    assert candidate.vias[0].via_type == "through"


def test_adjacent_side_pins_receive_distinct_lane_positions():
    board = _board()
    fanout = FanoutSpec(
        "U1",
        {
            "kind": "qfp_escape",
            "pins": [1, 2],
            "via_layer": "B.Cu",
            "lane_pitch": "0.8mm",
            "via": {"diameter": "0.5mm", "drill": "0.3mm"},
        },
    )
    candidates = compile_qfp_escape_candidates(board, board.components["U1"], fanout)
    via_y = [candidate.vias[0].position[1] for candidate in candidates]
    assert abs(via_y[1] - via_y[0]) >= 0.8


def test_rotated_qfp_escape_uses_component_rotation():
    board = _board(rotation=90)
    fanout = FanoutSpec(
        "U1",
        {
            "kind": "qfp_escape",
            "pins": [17],
            "via_layer": "B.Cu",
            "via": {"diameter": "0.5mm", "drill": "0.3mm"},
        },
    )
    candidate = compile_qfp_escape_candidates(board, board.components["U1"], fanout)[0]
    pad_point = board.components["U1"].get_pad_position("17")
    escape_end = candidate.segments[0].end
    assert escape_end[0] < pad_point[0]
    assert abs(escape_end[1] - pad_point[1]) < 0.001


def test_qfp_escape_respects_route_keepout():
    board = _board()
    spec = _spec(
        {
            "kind": "qfp_escape",
            "pins": [1],
            "via_layer": "B.Cu",
            "via": {"diameter": "0.5mm", "drill": "0.3mm"},
        }
    )
    spec = PhysicalSpec(
        path=spec.path,
        source_netlist=spec.source_netlist,
        width=spec.width,
        height=spec.height,
        stackup=spec.stackup,
        copper_layers=spec.copper_layers,
        rules=spec.rules,
        parts=spec.parts,
        netclass_assignments=spec.netclass_assignments,
        fanouts=spec.fanouts,
        keepouts=[
            KeepoutIntent(
                name="u1_left_escape_guard",
                layer="F.Cu",
                kind="route",
                at=(14.4, 19.0),
                size=(2.0, 1.0),
                raw={},
            )
        ],
    )

    reports, violations = compile_fanouts(board, spec, strict=False)

    assert reports[0].committed is False
    assert any(v.code == "route_keepout_violation" for v in violations)
