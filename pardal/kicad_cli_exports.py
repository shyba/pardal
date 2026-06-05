"""Helpers for KiCad CLI fabrication exports."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile


def export_gerbers(board_path: Path, output_dir: Path) -> None:
    """Export Gerber files for a KiCad board into a clean directory."""
    _run_directory_export(
        board_path,
        output_dir,
        "Gerber",
        [
            "kicad-cli",
            "pcb",
            "export",
            "gerbers",
            "--output",
            "",
            "",
        ],
    )


def export_drill(board_path: Path, output_dir: Path) -> None:
    """Export drill files for a KiCad board into a clean directory."""
    _run_directory_export(
        board_path,
        output_dir,
        "drill",
        [
            "kicad-cli",
            "pcb",
            "export",
            "drill",
            "--output",
            "",
            "--format",
            "excellon",
            "--generate-map",
            "",
        ],
    )


def _run_directory_export(
    board_path: Path,
    output_dir: Path,
    export_kind: str,
    command_template: list[str],
) -> None:
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    if output_dir.exists() and not output_dir.is_dir():
        raise RuntimeError(f"{export_kind} output path is not a directory: {output_dir}")

    temp_output_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output_dir.name}.{export_kind.lower()}-",
            dir=str(output_dir.parent),
        )
    )
    command = list(command_template)
    command[5] = str(temp_output_dir)
    command[-1] = str(board_path)

    try:
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        shutil.rmtree(temp_output_dir, ignore_errors=True)
        raise RuntimeError(
            f"kicad-cli not found while exporting {export_kind.lower()} files"
        ) from exc
    except Exception:
        shutil.rmtree(temp_output_dir, ignore_errors=True)
        raise

    try:
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or (
                f"exit code {completed.returncode}"
            )
            raise RuntimeError(
                f"KiCad {export_kind.lower()} export failed for {board_path}: {detail}"
            )
        if not any(temp_output_dir.iterdir()):
            raise RuntimeError(
                f"KiCad {export_kind.lower()} export produced no files for {board_path}"
            )
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temp_output_dir.replace(output_dir)
    except Exception:
        shutil.rmtree(temp_output_dir, ignore_errors=True)
        raise
