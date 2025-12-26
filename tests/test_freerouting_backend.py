import os
import shutil
from pathlib import Path

import pytest

from pcb_tool.data_model import Board, Component, Net, Pad, STANDARD_LAYER_STACKS
from pcb_tool.freerouting_backend import FreeroutingRunConfig, freeroute_kicad_pcb
from pcb_tool.kicad_writer import KicadWriter


pytestmark = pytest.mark.slow


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.mark.skipif(
    not _docker_available() or os.environ.get("PARDAL_ENABLE_DOCKER_TESTS") != "1",
    reason="Requires docker + large images; set PARDAL_ENABLE_DOCKER_TESTS=1 to enable",
)
def test_freerouting_smoke(tmp_path: Path) -> None:
    # Minimal 2-layer board with one easy net to route.
    board = Board(layers=STANDARD_LAYER_STACKS[2])
    board.width = 20.0
    board.height = 20.0

    j1 = Component(
        ref="J1",
        value="A",
        footprint="PinHeader_1x02_P2.54mm_Vertical",
        position=(5.0, 10.0),
        rotation=0,
        layer="F.Cu",
    )
    j1.pads.append(Pad(number=1, position_offset=(0.0, -1.27), size=(1.0, 1.0)))
    j1.pads.append(Pad(number=2, position_offset=(0.0, 1.27), size=(1.0, 1.0)))
    board.add_component(j1)

    j2 = Component(
        ref="J2",
        value="B",
        footprint="PinHeader_1x02_P2.54mm_Vertical",
        position=(15.0, 10.0),
        rotation=0,
        layer="F.Cu",
    )
    j2.pads.append(Pad(number=1, position_offset=(0.0, -1.27), size=(1.0, 1.0)))
    j2.pads.append(Pad(number=2, position_offset=(0.0, 1.27), size=(1.0, 1.0)))
    board.add_component(j2)

    net = Net(name="NET1", code="1", track_width=0.4)
    net.add_connection("J1", "1")
    net.add_connection("J2", "1")
    board.add_net(net)

    inp = tmp_path / "in.kicad_pcb"
    out = tmp_path / "out.kicad_pcb"

    KicadWriter().write(board, inp)

    cfg = FreeroutingRunConfig(
        max_passes=5,
        fanout=False,
        threads=0,
        via_costs=50,
        start_ripup_costs=100,
    )
    freeroute_kicad_pcb(inp, out, config=cfg)

    text = out.read_text(encoding="utf-8", errors="replace")
    assert "(kicad_pcb" in text
    assert ("(segment" in text) or ("(via" in text)
