from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from pcb_tool.drc import run_drc_docker


pytestmark = pytest.mark.slow


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.mark.skipif(
    not _docker_available() or os.environ.get("PARDAL_ENABLE_DOCKER_TESTS") != "1",
    reason="Requires docker + KiCad image; set PARDAL_ENABLE_DOCKER_TESTS=1 to enable",
)
def test_kicad9_drc_docker_smoke() -> None:
    pcb = Path("manual_temp_test/injector_6ch_project/injector_6ch_final.kicad_pcb")
    assert pcb.exists(), f"missing fixture: {pcb}"

    result = run_drc_docker(pcb)
    assert result.success
    assert result.errors == 0
    assert result.warnings == 0
    assert result.unconnected == 0

