"""Programmatic API for pardal-pcb.

This is a stable-ish surface intended for automation use cases (board generation,
autorouting, DRC checks) without going through the interactive CLI/REPL.
"""

from pcb_tool.api.drc import DrcSummary, check_internal_drc, run_kicad_drc
from pcb_tool.api.io import LoadSummary, load_kicad_pcb, save_kicad_pcb
from pcb_tool.api.render import render_3d
from pcb_tool.api.routing import autoroute
from pcb_tool.routing.results import PathResult, RouteResult

__all__ = [
    "PathResult",
    "RouteResult",
    "autoroute",
    "DrcSummary",
    "check_internal_drc",
    "run_kicad_drc",
    "LoadSummary",
    "load_kicad_pcb",
    "save_kicad_pcb",
    "render_3d",
]
