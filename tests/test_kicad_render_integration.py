from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from pcb_tool.kicad_render import Render3dOptions, render_3d_docker


pytestmark = pytest.mark.slow


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.mark.skipif(
    not _docker_available() or os.environ.get("PARDAL_ENABLE_DOCKER_TESTS") != "1",
    reason="Requires docker + KiCad image; set PARDAL_ENABLE_DOCKER_TESTS=1 to enable",
)
def test_kicad9_render_docker_smoke(tmp_path: Path) -> None:
    pcb = Path("manual_temp_test/injector_6ch_project/injector_6ch_final.kicad_pcb")
    assert pcb.exists(), f"missing fixture: {pcb}"

    out = tmp_path / "render.jpg"
    render_3d_docker(
        pcb,
        out,
        options=Render3dOptions(width=800, height=500, quality="basic", side="top"),
        timeout_s=300.0,
    )
    assert out.exists()
    assert out.stat().st_size > 10_000

