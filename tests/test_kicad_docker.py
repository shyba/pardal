from __future__ import annotations

from pathlib import Path

import pytest


def test_build_kicad_cli_docker_cmd(tmp_path: Path):
    from pcb_tool.kicad_docker import build_kicad_cli_docker_cmd

    cmd = build_kicad_cli_docker_cmd(
        image="kicad/kicad:9.0.6-full",
        workdir_host=tmp_path,
        args=["version"],
    )

    assert cmd[0:4] == ["docker", "run", "--rm", "--user"]
    assert "-v" in cmd
    assert f"{tmp_path.resolve()}:/work" in cmd
    assert cmd[-2:] == ["kicad-cli", "version"]


def test_run_drc_when_cli_unsupported_returns_helpful_error(tmp_path: Path, monkeypatch):
    from pcb_tool import drc as drc_mod

    pcb_file = tmp_path / "test.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018) (generator test) (net 0 \"\"))\n")

    monkeypatch.setattr(drc_mod, "_kicad_cli_supports_pcb_drc", lambda: False)
    monkeypatch.delenv("PARDAL_KICAD_DOCKER", raising=False)

    result = drc_mod.run_drc(pcb_file)
    assert result.success is False
    assert result.errors == 1
    assert result.violations
    assert "does not support" in result.violations[0].description


def test_run_drc_uses_docker_when_env_set(tmp_path: Path, monkeypatch):
    from pcb_tool import drc as drc_mod
    from pcb_tool.drc import DrcResult

    pcb_file = tmp_path / "test.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018) (generator test) (net 0 \"\"))\n")

    monkeypatch.setattr(drc_mod, "_kicad_cli_supports_pcb_drc", lambda: False)
    monkeypatch.setenv("PARDAL_KICAD_DOCKER", "1")

    sentinel = DrcResult(
        errors=0,
        warnings=0,
        violations=[],
        unconnected=0,
        report_path=None,
        success=True,
    )
    monkeypatch.setattr(drc_mod, "run_drc_docker", lambda *a, **k: sentinel)

    assert drc_mod.run_drc(pcb_file) is sentinel

