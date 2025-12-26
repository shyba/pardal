from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pcb_tool.data_model import Board
from pcb_tool.drc import DrcResult, run_drc, run_sdk_drc
from pcb_tool.drc_engine import InternalDrcEngine


@dataclass(frozen=True)
class DrcSummary:
    errors: int
    warnings: int
    report: str


def check_internal_drc(board: Board) -> DrcSummary:
    """Run the internal (fast, simplified) DRC used by the test suite."""
    result = InternalDrcEngine().check_board(board)
    return DrcSummary(
        errors=result.errors,
        warnings=result.warnings,
        report=result.raw_report or "",
    )


def run_kicad_drc(pcb_path: str | Path, *, use_sdk: bool = False) -> DrcResult:
    """Run KiCad DRC via `kicad-cli` (default) or `pcbnew` SDK if requested."""
    if use_sdk:
        return run_sdk_drc(Path(pcb_path))
    return run_drc(Path(pcb_path))
