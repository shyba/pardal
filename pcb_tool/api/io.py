from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pcb_tool.data_model import Board
from pcb_tool.kicad_text_loader import KicadTextLoadResult, load_board_kicad_pcb
from pcb_tool.kicad_writer import KicadWriter
from pcb_tool.kicad_project_loader import apply_project_net_settings


@dataclass(frozen=True)
class LoadSummary:
    board: Board
    warnings: list[str]
    backend: str  # "pcbnew" | "text"


def load_kicad_pcb(path: str | Path, *, prefer_pcbnew: bool = True) -> LoadSummary:
    """Load a `.kicad_pcb` into the internal `Board` model.

    - If `pcbnew` is available and the file is supported, use the KiCad SDK.
    - Otherwise, fall back to a text/S-expression loader.
    """
    pcb_path = Path(path)
    if prefer_pcbnew:
        try:
            import pcbnew  # type: ignore

            from pcb_tool.kicad_loader import load_board_from_kicad

            kicad_board = pcbnew.LoadBoard(str(pcb_path))
            board = load_board_from_kicad(kicad_board)
            board.source_file = pcb_path
            warnings = apply_project_net_settings(board, pcb_path)
            return LoadSummary(board=board, warnings=warnings, backend="pcbnew")
        except Exception:
            pass

    result: KicadTextLoadResult = load_board_kicad_pcb(pcb_path)
    warnings = list(result.warnings)
    warnings.extend(apply_project_net_settings(result.board, pcb_path))
    return LoadSummary(board=result.board, warnings=warnings, backend="text")


def save_kicad_pcb(board: Board, path: str | Path) -> Path:
    """Write a minimal `.kicad_pcb` (router-focused) from an in-memory `Board`."""
    out = Path(path)
    KicadWriter().write(board, out)
    return out
