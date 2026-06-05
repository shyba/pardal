from pathlib import Path

from pardal.data_model import Board, Net
from pardal.kicad_sdk_writer import KiCadSDKWriter
from pardal.data_model import Component, Pad
from pardal.physical.power import apply_planes, apply_power_stitches
from pardal.physical.spec import (
    BoardRules,
    KeepoutIntent,
    PartPlacement,
    PhysicalSpec,
    PlaneIntent,
    PowerStitchIntent,
)


def _board() -> Board:
    board = Board()
    board.width = 30
    board.height = 20
    board.layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    board.add_net(Net("gnd", "1"))
    board.add_component(
        Component(
            "U1",
            "IC",
            "Test:U1",
            (10.0, 10.0),
            0,
            pads=[Pad("1", (0.0, 0.0), (0.4, 0.4))],
        )
    )
    board.nets["gnd"].add_connection("U1", "1")
    return board


def _spec(planes):
    return PhysicalSpec(
        path=Path("dummy"),
        source_netlist=None,
        width=30,
        height=20,
        stackup="four_layer",
        copper_layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        rules=BoardRules(),
        parts={"J1": PartPlacement("J1", "Test:J1", (10, 10))},
        netclass_assignments={},
        planes=[PlaneIntent(net=str(raw["net"]), layer=str(raw["layer"]), raw=raw) for raw in planes],
    )


def _stitch_spec(stitches, keepouts=None):
    spec = _spec([])
    return PhysicalSpec(
        path=spec.path,
        source_netlist=spec.source_netlist,
        width=spec.width,
        height=spec.height,
        stackup=spec.stackup,
        copper_layers=spec.copper_layers,
        rules=spec.rules,
        parts=spec.parts,
        netclass_assignments=spec.netclass_assignments,
        power_stitches=[PowerStitchIntent(raw=raw) for raw in stitches],
        keepouts=list(keepouts or []),
    )


def test_apply_board_outline_plane_creates_zone_inside_board():
    board = _board()
    spec = _spec(
        [
            {
                "kind": "zone",
                "net": "gnd",
                "layer": "In2.Cu",
                "outline": "board",
                "margin": "1.5mm",
            }
        ]
    )
    zones = apply_planes(board, spec)
    assert len(zones) == 1
    assert zones[0].outline == [(1.5, 1.5), (28.5, 1.5), (28.5, 18.5), (1.5, 18.5)]
    assert board.zones == zones


def test_apply_plane_rejects_unknown_net():
    board = _board()
    spec = _spec([{"kind": "zone", "net": "missing", "layer": "In2.Cu"}])
    try:
        apply_planes(board, spec)
    except ValueError as exc:
        assert "unknown net" in str(exc)
    else:
        raise AssertionError("expected unknown net failure")


def test_sdk_writer_emits_zone_record(tmp_path):
    board = _board()
    spec = _spec([{"kind": "zone", "net": "gnd", "layer": "In2.Cu", "margin": "1mm"}])
    apply_planes(board, spec)
    output = tmp_path / "zone_board.kicad_pcb"
    assert KiCadSDKWriter().write_board(board, str(output))
    text = output.read_text(encoding="utf-8")
    assert '(zone' in text
    assert '(net_name "gnd")' in text
    assert '(layer "In2.Cu")' in text


def test_power_stitch_commits_pad_trace_and_via():
    board = _board()
    spec = _stitch_spec(
        [
            {
                "kind": "pad_vias",
                "net": "gnd",
                "refs": {"U1": [1]},
                "vias": {"U1.1": ["12mm", "10mm"]},
                "via": {"diameter": "0.5mm", "drill": "0.3mm"},
            }
        ]
    )
    reports, violations = apply_power_stitches(board, spec, strict=True)
    assert not violations
    assert reports[0].committed is True
    assert reports[0].vias == 1
    assert len(board.nets["gnd"].segments) == 1
    assert len(board.nets["gnd"].vias) == 1


def test_power_stitch_auto_selects_missing_via_coordinate():
    board = _board()
    spec = _stitch_spec(
        [
            {
                "kind": "pad_vias",
                "net": "gnd",
                "refs": {"U1": [1]},
                "auto": {
                    "directions": ["east"],
                    "offsets": ["1.0mm"],
                    "laterals": ["0mm"],
                },
                "via": {"diameter": "0.5mm", "drill": "0.3mm"},
            }
        ]
    )

    reports, violations = apply_power_stitches(board, spec, strict=True)

    assert not violations
    assert reports[0].committed is True
    assert reports[0].message == "auto-selected via"
    assert board.nets["gnd"].vias[0].position == (11.0, 10.0)


def test_deferred_power_stitch_validates_pad_without_geometry():
    board = _board()
    spec = _stitch_spec(
        [
            {
                "name": "u1_gnd_pad1_deferred",
                "kind": "deferred",
                "net": "gnd",
                "refs": {"U1": [1]},
            }
        ]
    )

    reports, violations = apply_power_stitches(board, spec, strict=True)

    assert reports == []
    assert violations == []
    assert not board.nets["gnd"].segments
    assert not board.nets["gnd"].vias


def test_deferred_power_stitch_probe_reports_legal_candidate_without_geometry():
    board = _board()
    spec = _stitch_spec(
        [
            {
                "name": "u1_gnd_pad1_deferred",
                "kind": "deferred",
                "net": "gnd",
                "refs": {"U1": [1]},
                "auto": {
                    "directions": ["east"],
                    "offsets": ["1.0mm"],
                    "laterals": ["0mm"],
                },
                "via": {"diameter": "0.5mm", "drill": "0.3mm"},
            }
        ]
    )

    reports, violations = apply_power_stitches(board, spec, strict=True, probe_deferred=True)

    assert violations == []
    assert reports[0].strategy == "power_probe"
    assert reports[0].committed is False
    assert reports[0].message == (
        "probe u1_gnd_pad1_deferred U1.1 found legal via at (11.000, 10.000); not committed"
    )
    assert not board.nets["gnd"].segments
    assert not board.nets["gnd"].vias


def test_deferred_power_stitch_probe_reports_candidate_failures():
    board = _board()
    spec = _stitch_spec(
        [
            {
                "name": "u1_gnd_pad1_deferred",
                "kind": "deferred",
                "net": "gnd",
                "refs": {"U1": [1]},
                "auto": {
                    "directions": ["west"],
                    "offsets": ["20.0mm"],
                    "laterals": ["0mm"],
                },
                "via": {"diameter": "0.5mm", "drill": "0.3mm"},
            }
        ]
    )

    reports, violations = apply_power_stitches(board, spec, strict=True, probe_deferred=True)

    assert violations == []
    assert reports[0].strategy == "power_probe"
    assert reports[0].committed is False
    assert (
        "probe u1_gnd_pad1_deferred U1.1 found no legal auto stitch candidate after 1 candidate(s)"
        in reports[0].message
    )
    assert "outside board outline" in reports[0].message
    assert not board.nets["gnd"].segments
    assert not board.nets["gnd"].vias


def test_power_stitch_requires_explicit_via_coordinate():
    board = _board()
    spec = _stitch_spec(
        [
            {
                "kind": "pad_vias",
                "net": "gnd",
                "refs": {"U1": [1]},
                "vias": {},
            }
        ]
    )
    try:
        apply_power_stitches(board, spec, strict=True)
    except ValueError as exc:
        assert "missing via coordinate" in str(exc)
    else:
        raise AssertionError("expected missing via coordinate failure")


def test_power_stitch_rejects_via_inside_via_keepout():
    board = _board()
    spec = _stitch_spec(
        [
            {
                "kind": "pad_vias",
                "net": "gnd",
                "refs": {"U1": [1]},
                "vias": {"U1.1": ["12mm", "10mm"]},
                "via": {"diameter": "0.5mm", "drill": "0.3mm"},
            }
        ],
        keepouts=[
            KeepoutIntent(
                name="u1_stitch_forbidden",
                layer="F.Cu",
                kind="via",
                at=(12.0, 10.0),
                size=(1.0, 1.0),
                raw={},
            )
        ],
    )

    reports, violations = apply_power_stitches(board, spec, strict=False)

    assert reports[0].committed is False
    assert any(v.code == "via_keepout_violation" for v in violations)


def test_deferred_power_stitch_probe_respects_keepout():
    board = _board()
    spec = _stitch_spec(
        [
            {
                "name": "u1_gnd_pad1_deferred",
                "kind": "deferred",
                "net": "gnd",
                "refs": {"U1": [1]},
                "auto": {
                    "directions": ["east"],
                    "offsets": ["1.0mm"],
                    "laterals": ["0mm"],
                },
                "via": {"diameter": "0.5mm", "drill": "0.3mm"},
            }
        ],
        keepouts=[
            KeepoutIntent(
                name="u1_probe_forbidden",
                layer="F.Cu",
                kind="via",
                at=(11.0, 10.0),
                size=(1.0, 1.0),
                raw={},
            )
        ],
    )

    reports, violations = apply_power_stitches(board, spec, strict=True, probe_deferred=True)

    assert violations == []
    assert reports[0].strategy == "power_probe"
    assert reports[0].committed is False
    assert "found no legal auto stitch candidate after 1 candidate(s)" in reports[0].message
