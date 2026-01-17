from __future__ import annotations

from pathlib import Path

from pcb_tool.data_model import Component, Pad
from pcb_tool.kicad_text_loader import load_board_kicad_pcb


def test_pad_numbers_are_stringly_typed():
    comp = Component(
        ref="U1",
        value="X",
        footprint="X",
        position=(0.0, 0.0),
        rotation=0.0,
    )
    comp.pads.append(Pad(number=1, position_offset=(1.0, 2.0), size=(1.0, 1.0)))

    assert comp.get_pad_by_number("1") is not None
    assert comp.get_pad_by_number(1) is not None
    assert comp.get_pad_position("1") == (1.0, 2.0)
    assert comp.get_pad_position(1) == (1.0, 2.0)


def test_kicad_text_loader_parses_fpga_large_fixture():
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "fpga_large" / "fpga_large_csg324_breakout.kicad_pcb"
    result = load_board_kicad_pcb(fixture)
    board = result.board

    assert board.layers[:2] == ["F.Cu", "In1.Cu"]
    assert board.layers[-1] == "B.Cu"
    assert getattr(board, "width") == 260.0
    assert getattr(board, "height") == 260.0

    u1 = board.components["U1"]
    assert any(p.number == "A1" for p in u1.pads)
    assert "U1_A1" in board.nets
    assert ("U1", "A1") in board.nets["U1_A1"].connections


def test_kicad_text_loader_parses_segments_and_vias():
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "fpga" / "fpga_routed_with_widths.kicad_pcb"
    result = load_board_kicad_pcb(fixture)
    board = result.board

    assert board.nets["VCC"].segments
    assert board.nets["TDO"].vias
