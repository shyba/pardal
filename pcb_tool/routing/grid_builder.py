"""Routing grid construction from a board.

This module centralizes the policy for turning a `pcb_tool.data_model.Board` into a
`pcb_tool.routing.grid.RoutingGrid` for pathfinding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pcb_tool.data_model import Board
from pcb_tool.routing.grid import RoutingGrid


@dataclass(frozen=True)
class GridBuildConfig:
    resolution_mm: float = 0.1
    default_clearance_mm: float = 0.2
    margin_mm: float = 10.0
    min_width_mm: float = 20.0
    min_height_mm: float = 20.0


def build_routing_grid_from_board(
    board: Board,
    *,
    config: GridBuildConfig | None = None,
) -> RoutingGrid:
    """Create a `RoutingGrid` from board contents and stamp obstacles.

    Stamps:
    - All pad copper as obstacles (SMD on component layer; THT on all layers).
    - A `pad_net_map` on the grid for all pad cells (including unconnected pads).
    - A `pad_centers` set for via-in-pad avoidance logic.
    - Existing trace segments as obstacles (clearance zones).
    - Existing vias as obstacles on all layers.
    """
    cfg = config or GridBuildConfig()

    # Prefer explicit board dimensions when provided; fall back to component extents.
    if getattr(board, "width", 0.0) and getattr(board, "height", 0.0):
        width_mm = max(float(board.width), cfg.min_width_mm)
        height_mm = max(float(board.height), cfg.min_height_mm)
    elif not board.components:
        width_mm = 100.0
        height_mm = 100.0
    else:
        positions = [comp.position for comp in board.components.values()]
        max_x = max(pos[0] for pos in positions) + cfg.margin_mm
        max_y = max(pos[1] for pos in positions) + cfg.margin_mm
        width_mm = max(max_x, cfg.min_width_mm)
        height_mm = max(max_y, cfg.min_height_mm)

    grid = RoutingGrid(
        width_mm=width_mm,
        height_mm=height_mm,
        resolution_mm=cfg.resolution_mm,
        default_clearance_mm=cfg.default_clearance_mm,
        layers=board.layers,
    )

    # Mark all pad positions as obstacles and track per-cell pad ownership.
    grid.pad_net_map = {}  # (grid_x, grid_y, layer) -> net_name | None
    grid.pad_centers = set()  # {(grid_x, grid_y)}

    for comp in board.components.values():
        for pad in comp.pads:
            pad_pos = comp.get_pad_position(pad.number)
            pad_size = max(pad.size[0], pad.size[1])

            # Find which net this pad belongs to (if any).
            pad_net = None
            for net_name, net in board.nets.items():
                for conn_ref, conn_pin in net.connections:
                    if conn_ref == comp.ref and int(conn_pin) == pad.number:
                        pad_net = net_name
                        break
                if pad_net:
                    break

            pad_grid_x, pad_grid_y = grid.to_grid_coords(*pad_pos)
            grid.pad_centers.add((pad_grid_x, pad_grid_y))

            # Calculate obstacle radius (same as mark_obstacle).
            obstacle_radius = int(math.ceil(pad_size / (2 * grid.resolution_mm)))

            if pad.drill is not None:
                # Through-hole pad: mark on all layers.
                for layer in grid.layers:
                    grid.mark_obstacle(pad_pos[0], pad_pos[1], layer, size_mm=pad_size)
                    for dx in range(-obstacle_radius, obstacle_radius + 1):
                        for dy in range(-obstacle_radius, obstacle_radius + 1):
                            gx, gy = pad_grid_x + dx, pad_grid_y + dy
                            if grid.is_within_bounds(gx, gy):
                                dist = math.sqrt(dx * dx + dy * dy) * grid.resolution_mm
                                if dist <= pad_size / 2:
                                    grid.pad_net_map[(gx, gy, layer)] = pad_net
            else:
                # SMD pad: mark only on component layer.
                grid.mark_obstacle(pad_pos[0], pad_pos[1], comp.layer, size_mm=pad_size)
                for dx in range(-obstacle_radius, obstacle_radius + 1):
                    for dy in range(-obstacle_radius, obstacle_radius + 1):
                        gx, gy = pad_grid_x + dx, pad_grid_y + dy
                        if grid.is_within_bounds(gx, gy):
                            dist = math.sqrt(dx * dx + dy * dy) * grid.resolution_mm
                            if dist <= pad_size / 2:
                                grid.pad_net_map[(gx, gy, comp.layer)] = pad_net

    # Mark existing trace segments as obstacles.
    for net in board.nets.values():
        for segment in net.segments:
            grid.mark_trace_segment(
                start_mm=segment.start,
                end_mm=segment.end,
                layer=segment.layer,
                width_mm=segment.width,
                clearance_mm=grid.default_clearance_mm,
            )

    # Mark existing vias as obstacles on all layers.
    for net in board.nets.values():
        for via in net.vias:
            for layer in grid.layers:
                grid.mark_obstacle(via.position[0], via.position[1], layer)

    return grid
