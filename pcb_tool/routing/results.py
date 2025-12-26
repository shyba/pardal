"""Shared result types for routing.

These are designed for programmatic use (library consumers) while keeping
backwards-compatible string-based CLI reports intact.
"""

from __future__ import annotations

from dataclasses import dataclass

from pcb_tool.routing.grid import GridCell


@dataclass(frozen=True)
class PathResult:
    success: bool
    waypoints_mm: list[tuple[float, float]]
    backend: str | None
    path_cells: list[GridCell] | None
    via_locations: list[tuple[float, float, str, str]]


@dataclass(frozen=True)
class RouteResult:
    """High-level routing result for a set of nets."""

    success_count: int
    total_length_mm: float
    total_vias: int
    report: str
