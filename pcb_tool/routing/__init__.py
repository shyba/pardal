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

from pcb_tool.routing.grid import RoutingGrid, GridCell
from pcb_tool.routing.pathfinder import PathFinder
from pcb_tool.routing.layer_optimizer import LayerOptimizer, NetPath, LayerAssignment
from pcb_tool.routing.multi_net_router import MultiNetRouter, NetDefinition, RoutedNet
from pcb_tool.routing.grid_builder import GridBuildConfig, build_routing_grid_from_board
from pcb_tool.routing.net_definitions import (
    extract_net_definitions,
    build_minimum_spanning_tree,
)
from pcb_tool.routing.results import PathResult, RouteResult

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
