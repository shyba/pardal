from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from pardal.cli import cmd_route
from pardal.data_model import Board, Component, Net, Pad
from pardal.kicad_writer import KicadWriter


def test_cmd_route_fallback_works_without_pcbnew(tmp_path: Path, monkeypatch):
    # Ensure we exercise the text-loader path.
    monkeypatch.setitem(__import__("sys").modules, "pcbnew", None)

    board = Board()
    board.width = 20.0
    board.height = 20.0

    r1 = Component(
        ref="R1",
        value="R",
        footprint="R_0805",
        position=(5.0, 10.0),
        rotation=0.0,
        layer="F.Cu",
    )
    r1.pads.append(Pad(number="1", position_offset=(0.0, 0.0), size=(1.0, 1.0)))
    board.add_component(r1)

    r2 = Component(
        ref="R2",
        value="R",
        footprint="R_0805",
        position=(15.0, 10.0),
        rotation=0.0,
        layer="F.Cu",
    )
    r2.pads.append(Pad(number="1", position_offset=(0.0, 0.0), size=(1.0, 1.0)))
    board.add_component(r2)

    net = Net(name="NET1", code="1")
    net.connections = [("R1", "1"), ("R2", "1")]
    board.nets[net.name] = net

    inp = tmp_path / "in.kicad_pcb"
    out = tmp_path / "out.kicad_pcb"
    KicadWriter().write(board, inp)

    args = Namespace(pcb=inp, output=out, net="NET1", layers=None)
    rc = cmd_route(args)
    assert rc == 0
    assert out.exists()
    text = out.read_text(encoding="utf-8", errors="replace")
    assert "(segment" in text

