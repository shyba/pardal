from pathlib import Path
import subprocess

import pytest

from pardal.kicad_cli_exports import export_drill, export_gerbers


def _write_export_artifact(command: list[str], filename: str, content: str) -> None:
    output_dir = Path(command[command.index("--output") + 1])
    (output_dir / filename).write_text(content, encoding="utf-8")


def test_export_gerbers_replaces_existing_directory(monkeypatch, tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    output_dir = tmp_path / "gerbers"
    output_dir.mkdir()
    (output_dir / "stale.txt").write_text("stale", encoding="utf-8")

    commands: list[list[str]] = []

    def fake_run(command, check, text, capture_output):
        commands.append(command)
        _write_export_artifact(command, "board-F_Cu.gbr", "gerber")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("pardal.kicad_cli_exports.subprocess.run", fake_run)

    export_gerbers(board, output_dir)

    assert len(commands) == 1
    command = commands[0]
    assert command[:4] == ["kicad-cli", "pcb", "export", "gerbers"]
    assert command[4] == "--output"
    assert Path(command[5]).parent == output_dir.parent
    assert Path(command[5]).name.startswith(".gerbers.gerber-")
    assert command[6] == str(board)
    assert (output_dir / "board-F_Cu.gbr").read_text(encoding="utf-8") == "gerber"
    assert not (output_dir / "stale.txt").exists()


def test_export_drill_preserves_existing_directory_on_failure(monkeypatch, tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    output_dir = tmp_path / "drill"
    output_dir.mkdir()
    stale = output_dir / "existing.drl"
    stale.write_text("keep", encoding="utf-8")

    def fake_run(command, check, text, capture_output):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="drill export failed")

    monkeypatch.setattr("pardal.kicad_cli_exports.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="KiCad drill export failed"):
        export_drill(board, output_dir)

    assert stale.read_text(encoding="utf-8") == "keep"


def test_export_gerbers_cleans_temp_directory_when_kicad_cli_missing(monkeypatch, tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")
    output_dir = tmp_path / "gerbers"

    def fake_run(command, check, text, capture_output):
        raise FileNotFoundError("kicad-cli")

    monkeypatch.setattr("pardal.kicad_cli_exports.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="kicad-cli not found while exporting gerber files"):
        export_gerbers(board, output_dir)

    leftovers = [path for path in tmp_path.iterdir() if path.name.startswith(".gerbers.gerber-")]
    assert leftovers == []
