import pytest

from pardal.data_model import Board, Component, CopperZone, Net, Pad, TraceSegment, Via
from pardal.physical.commit_gate import (
    RouteCandidate,
    RouteCommitError,
    KeepoutConstraint,
    commit_route_candidate,
    validate_route_candidate,
)


def _board() -> Board:
    board = Board()
    board.width = 20.0
    board.height = 20.0
    board.add_component(
        Component(
            "U1",
            "IC",
            "Test:U1",
            (10.0, 10.0),
            0,
            pads=[Pad("1", (0.0, 0.0), (1.0, 1.0)), Pad("2", (2.0, 0.0), (1.0, 1.0))],
        )
    )
    a = Net("A", "1", track_width=0.2)
    a.add_connection("U1", "1")
    b = Net("B", "2", track_width=0.2)
    b.add_connection("U1", "2")
    board.add_net(a)
    board.add_net(b)
    return board


def test_rejects_unknown_net():
    board = _board()
    candidate = RouteCandidate("NOPE", [])
    violations = validate_route_candidate(board, candidate)
    assert violations[0].code == "unknown_net"


def test_rejects_invalid_layer():
    board = _board()
    candidate = RouteCandidate("A", [TraceSegment("A", (1, 1), (2, 2), "In1.Cu", 0.2)])
    violations = validate_route_candidate(board, candidate)
    assert any(v.code == "invalid_layer" for v in violations)


def test_rejects_outside_board_outline():
    board = _board()
    candidate = RouteCandidate("A", [TraceSegment("A", (-1, 1), (2, 2), "F.Cu", 0.2)])
    violations = validate_route_candidate(board, candidate)
    assert any(v.code == "outside_board" for v in violations)


def test_allows_simple_segment_to_same_net_pad():
    board = _board()
    candidate = RouteCandidate("A", [TraceSegment("A", (1, 1), (8, 8), "F.Cu", 0.2)])
    commit_route_candidate(board, candidate)
    assert len(board.nets["A"].segments) == 1


def test_rejects_track_crossing_existing_different_net():
    board = _board()
    board.nets["B"].segments.append(TraceSegment("B", (2, 2), (18, 18), "F.Cu", 0.2))
    candidate = RouteCandidate("A", [TraceSegment("A", (2, 18), (18, 2), "F.Cu", 0.2)])
    with pytest.raises(RouteCommitError):
        commit_route_candidate(board, candidate)


def test_rejects_track_too_close_to_different_net_pad():
    board = _board()
    candidate = RouteCandidate("A", [TraceSegment("A", (12, 9.9), (18, 9.9), "F.Cu", 0.2)])
    violations = validate_route_candidate(board, candidate)
    violation = next(v for v in violations if v.code == "track_to_pad_clearance")
    assert violation.distance is not None
    assert violation.distance < 0


def test_commits_valid_via_atomically():
    board = _board()
    candidate = RouteCandidate(
        "A",
        [TraceSegment("A", (1, 1), (5, 5), "F.Cu", 0.2)],
        [Via("A", (5, 5), 0.5, 0.2, ("F.Cu", "B.Cu"))],
    )
    commit_route_candidate(board, candidate)
    assert len(board.nets["A"].segments) == 1
    assert len(board.nets["A"].vias) == 1


def test_rejects_via_too_close_to_different_net_pad():
    board = _board()
    candidate = RouteCandidate("A", [], [Via("A", (12, 10), 0.5, 0.2, ("F.Cu", "B.Cu"))])
    violations = validate_route_candidate(board, candidate)
    violation = next(v for v in violations if v.code == "via_to_pad_clearance")
    assert violation.distance is not None
    assert violation.distance < 0


def test_rejects_track_too_close_to_existing_different_net_via():
    board = _board()
    board.nets["B"].vias.append(Via("B", (10, 10), 0.5, 0.2, ("F.Cu", "B.Cu")))
    candidate = RouteCandidate("A", [TraceSegment("A", (9, 10), (11, 10), "F.Cu", 0.2)])
    violations = validate_route_candidate(board, candidate)
    assert any(v.code == "track_to_via_clearance" for v in violations)


def test_rejects_via_too_close_to_existing_different_net_track():
    board = _board()
    board.nets["B"].segments.append(TraceSegment("B", (9, 10), (11, 10), "F.Cu", 0.2))
    candidate = RouteCandidate("A", [], [Via("A", (10, 10), 0.5, 0.2, ("F.Cu", "B.Cu"))])
    violations = validate_route_candidate(board, candidate)
    assert any(v.code == "via_to_track_clearance" for v in violations)


def test_rejects_track_crossing_route_keepout():
    board = _board()
    keepouts = [
        KeepoutConstraint(
            name="gpio_corridor_guard",
            layer="F.Cu",
            kind="route",
            at=(10.0, 10.0),
            size=(2.0, 2.0),
            source="board.pdl.yaml:42",
        )
    ]
    candidate = RouteCandidate("A", [TraceSegment("A", (8, 10), (12, 10), "F.Cu", 0.2)])
    violations = validate_route_candidate(board, candidate, keepouts=keepouts)
    assert any(v.code == "route_keepout_violation" for v in violations)
    assert any(v.source == "board.pdl.yaml:42" for v in violations)


def test_allows_route_keepout_when_net_is_allowed():
    board = _board()
    keepouts = [
        KeepoutConstraint(
            name="gpio_corridor_guard",
            layer="F.Cu",
            kind="route",
            at=(10.0, 10.0),
            size=(2.0, 2.0),
            allowed_nets=("A",),
            source="board.pdl.yaml:42",
        )
    ]
    candidate = RouteCandidate("A", [TraceSegment("A", (1, 1), (3, 1), "F.Cu", 0.2)])
    commit_route_candidate(board, candidate, keepouts=keepouts)
    assert len(board.nets["A"].segments) == 1


def test_rejects_unlisted_route_keepout_net():
    board = _board()
    keepouts = [
        KeepoutConstraint(
            name="gpio_corridor_guard",
            layer="F.Cu",
            kind="route",
            at=(10.0, 10.0),
            size=(2.0, 2.0),
            allowed_nets=("A",),
            source="board.pdl.yaml:42",
        )
    ]
    candidate = RouteCandidate("B", [TraceSegment("B", (8, 10), (12, 10), "F.Cu", 0.2)])
    violations = validate_route_candidate(board, candidate, keepouts=keepouts)
    assert any(v.code == "route_keepout_violation" for v in violations)


def test_allows_route_outside_keepout():
    board = _board()
    keepouts = [
        KeepoutConstraint(
            name="gpio_corridor_guard",
            layer="F.Cu",
            kind="route",
            at=(10.0, 10.0),
            size=(2.0, 2.0),
            source="board.pdl.yaml:42",
        )
    ]
    candidate = RouteCandidate("A", [TraceSegment("A", (1, 1), (4, 1), "F.Cu", 0.2)])
    commit_route_candidate(board, candidate, keepouts=keepouts)
    assert len(board.nets["A"].segments) == 1


def test_rejects_track_crossing_foreign_zone():
    board = _board()
    board.zones.append(
        CopperZone(
            net_name="B",
            net_code="2",
            layer="F.Cu",
            outline=[(6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)],
            clearance=0.3,
        )
    )
    candidate = RouteCandidate("A", [TraceSegment("A", (2.0, 10.0), (18.0, 10.0), "F.Cu", 0.2)])

    violations = validate_route_candidate(board, candidate)

    violation = next(v for v in violations if v.code == "track_to_zone_clearance")
    assert violation.net == "A"
    assert violation.layer == "F.Cu"
    assert violation.source == "B"
    assert violation.distance is not None
    assert violation.distance < 0


def test_strict_commit_rejects_track_crossing_foreign_zone():
    board = _board()
    board.zones.append(
        CopperZone(
            net_name="B",
            net_code="2",
            layer="F.Cu",
            outline=[(6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)],
        )
    )
    candidate = RouteCandidate("A", [TraceSegment("A", (2.0, 10.0), (18.0, 10.0), "F.Cu", 0.2)])

    with pytest.raises(RouteCommitError) as exc:
        commit_route_candidate(board, candidate)

    assert any(v.code == "track_to_zone_clearance" for v in exc.value.violations)
    assert not board.nets["A"].segments


def test_allows_same_net_track_crossing_zone():
    board = _board()
    board.zones.append(
        CopperZone(
            net_name="A",
            net_code="1",
            layer="F.Cu",
            outline=[(6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)],
        )
    )
    candidate = RouteCandidate("A", [TraceSegment("A", (2.0, 10.0), (18.0, 10.0), "F.Cu", 0.2)])

    violations = validate_route_candidate(board, candidate)

    assert not any(v.code == "track_to_zone_clearance" for v in violations)


def test_allows_foreign_track_inside_zone_away_from_boundary():
    board = _board()
    board.zones.append(
        CopperZone(
            net_name="B",
            net_code="2",
            layer="F.Cu",
            outline=[(6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)],
            clearance=0.3,
        )
    )
    candidate = RouteCandidate("A", [TraceSegment("A", (8.0, 13.0), (12.0, 13.0), "F.Cu", 0.2)])

    violations = validate_route_candidate(board, candidate)

    assert not any(v.code == "track_to_zone_clearance" for v in violations)


def test_rejects_track_too_close_to_non_rectilinear_foreign_zone():
    board = _board()
    board.zones.append(
        CopperZone(
            net_name="B",
            net_code="2",
            layer="F.Cu",
            outline=[(8.0, 8.0), (12.0, 10.0), (8.0, 12.0)],
            clearance=0.3,
        )
    )
    candidate = RouteCandidate("A", [TraceSegment("A", (7.8, 10.0), (7.8, 14.0), "F.Cu", 0.2)])

    violations = validate_route_candidate(board, candidate)

    violation = next(v for v in violations if v.code == "track_to_zone_clearance")
    assert violation.distance is not None
    assert 0 < violation.distance < 0.3


def test_allows_via_inside_foreign_zone_away_from_boundary():
    board = _board()
    board.layers = ["F.Cu", "In1.Cu", "B.Cu"]
    board.zones.append(
        CopperZone(
            net_name="B",
            net_code="2",
            layer="In1.Cu",
            outline=[(6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)],
        )
    )
    candidate = RouteCandidate("A", [], [Via("A", (10.0, 10.0), 0.5, 0.2, ("F.Cu", "B.Cu"))])

    violations = validate_route_candidate(board, candidate)

    assert not any(v.code == "via_to_zone_clearance" for v in violations)


def test_rejects_via_too_close_to_foreign_zone_boundary():
    board = _board()
    board.layers = ["F.Cu", "In1.Cu", "B.Cu"]
    board.zones.append(
        CopperZone(
            net_name="B",
            net_code="2",
            layer="In1.Cu",
            outline=[(6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)],
        )
    )
    candidate = RouteCandidate("A", [], [Via("A", (6.15, 10.0), 0.5, 0.2, ("F.Cu", "B.Cu"))])

    violations = validate_route_candidate(board, candidate)

    violation = next(v for v in violations if v.code == "via_to_zone_clearance")
    assert violation.net == "A"
    assert violation.layer == "In1.Cu"
    assert violation.source == "B"
    assert violation.distance is not None
    assert violation.distance < 0


def test_allows_via_when_span_excludes_foreign_zone_layer():
    board = _board()
    board.layers = ["F.Cu", "In1.Cu", "B.Cu"]
    board.zones.append(
        CopperZone(
            net_name="B",
            net_code="2",
            layer="B.Cu",
            outline=[(6.0, 6.0), (14.0, 6.0), (14.0, 14.0), (6.0, 14.0)],
        )
    )
    candidate = RouteCandidate("A", [], [Via("A", (10.0, 10.0), 0.5, 0.2, ("F.Cu", "In1.Cu"))])

    violations = validate_route_candidate(board, candidate)

    assert not any(v.code == "via_to_zone_clearance" for v in violations)
