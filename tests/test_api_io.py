from __future__ import annotations

from pathlib import Path

import pytest

from pardal.api.io import load_kicad_pcb, save_kicad_pcb


def test_api_load_kicad_pcb_uses_text_loader_for_kicad9_fixture():
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "examples" / "fpga_large" / "fpga_large_csg324_breakout.kicad_pcb"
    summary = load_kicad_pcb(fixture, prefer_pcbnew=True)
    assert summary.backend in {"pcbnew", "text"}
    assert "U1" in summary.board.components
    # Net settings should be loaded from the sibling `.kicad_pro`.
    assert summary.board.net_classes["Default"].track_width == pytest.approx(0.1)
    one_net = summary.board.nets["U1_A1"]
    assert one_net.track_width == pytest.approx(0.1)
    assert one_net.via_size == pytest.approx(0.4)
    assert one_net.via_drill == pytest.approx(0.2)
    # In the test venv we normally lack pcbnew, so this should be text.
    # If a developer runs tests inside KiCad's Python env, pcbnew may be used.


def test_api_save_kicad_pcb_roundtrip(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    fixture = repo_root / "examples" / "fpga_large" / "fpga_large_csg324_breakout.kicad_pcb"
    summary = load_kicad_pcb(fixture, prefer_pcbnew=False)
    out = tmp_path / "out.kicad_pcb"
    save_kicad_pcb(summary.board, out)
    assert out.exists()
    assert "(kicad_pcb" in out.read_text(encoding="utf-8", errors="replace")
