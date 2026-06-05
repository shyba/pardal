"""
PCB Routing Module

This module provides automated PCB routing capabilities using a hybrid approach:
- A* pathfinding for fast trace routing on a discretized grid
- Z3 SMT solver for layer assignment optimization
- Multi-net routing with conflict resolution

Main components:
- RoutingGrid: Discretized board representation with obstacle management
- PathFinder: A* pathfinding algorithm for single-net routing
- LayerOptimizer: Z3-based layer assignment optimization
- MultiNetRouter: Orchestrates routing of multiple nets with conflict resolution
"""

from pardal.routing.grid import RoutingGrid, GridCell
from pardal.routing.pathfinder import PathFinder
try:
    from pardal.routing.layer_optimizer import LayerOptimizer, NetPath, LayerAssignment
except Exception:  # pragma: no cover - optional dependency (z3)
    LayerOptimizer = None  # type: ignore[assignment]
    NetPath = None  # type: ignore[assignment]
    LayerAssignment = None  # type: ignore[assignment]
from pardal.routing.multi_net_router import MultiNetRouter, NetDefinition, RoutedNet
from pardal.routing.grid_builder import GridBuildConfig, build_routing_grid_from_board
from pardal.routing.net_definitions import (
    extract_net_definitions,
    build_minimum_spanning_tree,
)
from pardal.routing.results import PathResult, RouteResult

__all__ = [
    "RoutingGrid",
    "GridCell",
    "PathFinder",
    "GridBuildConfig",
    "build_routing_grid_from_board",
    "extract_net_definitions",
    "build_minimum_spanning_tree",
    "PathResult",
    "RouteResult",
    "LayerOptimizer",
    "NetPath",
    "LayerAssignment",
    "MultiNetRouter",
    "NetDefinition",
    "RoutedNet",
]
