"""Unified DRC interface for programmatic use.

This wraps:
- Internal simplified DRC (`pcb_tool.commands.drc.CheckDrcCommand`) for fast feedback.
- KiCad DRC via `kicad-cli` (`pcb_tool.drc.run_drc`) for production validation.
- KiCad DRC via `pcbnew` SDK (`pcb_tool.drc.run_sdk_drc`) when available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pcb_tool.commands.drc import CheckDrcCommand
from pcb_tool.data_model import Board
from pcb_tool.drc import DrcResult, run_drc, run_sdk_drc


@dataclass(frozen=True)
class DrcEngineResult:
    errors: int
    warnings: int
    unconnected: int = 0
    raw_report: str | None = None
    kicad: DrcResult | None = None

    @property
    def success(self) -> bool:
        return self.errors == 0


class DrcEngine(Protocol):
    def check_board(self, board: Board) -> DrcEngineResult:
        raise NotImplementedError

    def check_pcb(self, pcb_path: str | Path) -> DrcEngineResult:
        raise NotImplementedError


_INTERNAL_HEADER_RE = re.compile(
    r"DRC:\s*(\d+)\s+errors?,\s*(\d+)\s+warnings?", re.I
)


class InternalDrcEngine:
    """Internal (fast, simplified) DRC used by the test suite."""

    def check_board(self, board: Board) -> DrcEngineResult:
        report = CheckDrcCommand().execute(board)
        first = report.splitlines()[0] if report else ""
        m = _INTERNAL_HEADER_RE.search(first)
        if not m:
            return DrcEngineResult(errors=0, warnings=0, raw_report=report)
        return DrcEngineResult(
            errors=int(m.group(1)),
            warnings=int(m.group(2)),
            raw_report=report,
        )

    def check_pcb(self, pcb_path: str | Path) -> DrcEngineResult:
        raise TypeError("Internal DRC requires an in-memory Board, not a PCB path.")


class KicadCliDrcEngine:
    """DRC via `kicad-cli pcb drc`."""

    def check_board(self, board: Board) -> DrcEngineResult:
        raise TypeError("KiCad DRC requires a .kicad_pcb path.")

    def check_pcb(self, pcb_path: str | Path) -> DrcEngineResult:
        result = run_drc(Path(pcb_path))
        return DrcEngineResult(
            errors=result.errors,
            warnings=result.warnings,
            unconnected=result.unconnected,
            raw_report=str(result.report_path) if result.report_path else None,
            kicad=result,
        )


class PcbnewDrcEngine:
    """DRC via `pcbnew` Python SDK (falls back to `kicad-cli` if unavailable)."""

    def check_board(self, board: Board) -> DrcEngineResult:
        raise TypeError("KiCad DRC requires a .kicad_pcb path.")

    def check_pcb(self, pcb_path: str | Path) -> DrcEngineResult:
        result = run_sdk_drc(Path(pcb_path))
        return DrcEngineResult(
            errors=result.errors,
            warnings=result.warnings,
            unconnected=result.unconnected,
            raw_report=str(result.report_path) if result.report_path else None,
            kicad=result,
        )
