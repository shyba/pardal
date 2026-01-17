"""Build `NetDefinition` objects from a `Board`.

This is used by autorouting to convert net connectivity (pads) into one or more
point-to-point routing tasks.

For multi-point nets (3+ pads), we build a minimum spanning tree (MST) so the
router can connect all pads with minimal total wire length.
"""

from __future__ import annotations

import math
from typing import Iterable

from pcb_tool.data_model import Board
from pcb_tool.routing.multi_net_router import NetDefinition


def build_minimum_spanning_tree(points: list[tuple]) -> list[tuple]:
    """Create minimum spanning tree connecting all points using Prim's algorithm.

    Args:
        points: List of (ref, pin, (x, y)) tuples

    Returns:
        List of edge tuples: ((ref1, pin1, pos1), (ref2, pin2, pos2))
    """
    if len(points) <= 1:
        return []
    if len(points) == 2:
        return [(points[0], points[1])]

    visited = {0}
    edges = []

    while len(visited) < len(points):
        min_dist = float("inf")
        best_edge = None

        for i in visited:
            _, _, (x1, y1) = points[i]
            for j in range(len(points)):
                if j in visited:
                    continue
                _, _, (x2, y2) = points[j]
                dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                if dist < min_dist:
                    min_dist = dist
                    best_edge = (i, j)

        if best_edge is None:
            break

        i, j = best_edge
        edges.append((points[i], points[j]))
        visited.add(j)

    return edges


def extract_net_definitions(
    board: Board,
    net_names: Iterable[str],
    *,
    default_layer: str = "F.Cu",
) -> list[NetDefinition]:
    """Extract `NetDefinition` objects for requested nets.

    Args:
        board: Board to extract from
        net_names: Net names to extract
        default_layer: Routing layer assigned to each definition unless the caller
            overrides later

    Returns:
        List of `NetDefinition` objects (one per MST edge)
    """
    net_definitions: list[NetDefinition] = []

    for net_name in net_names:
        net = board.nets.get(net_name)
        if not net or len(net.connections) < 2:
            continue

        width_mm = board.get_net_width(net_name)
        clearance_mm = board.get_net_clearance(net_name)

        pad_positions = []
        for ref, pin in net.connections:
            comp = board.get_component(ref)
            if not comp:
                continue
            try:
                pos = comp.get_pad_position(pin)
                pad_positions.append((ref, pin, pos))
            except (ValueError, KeyError):
                pad_positions.append((ref, pin, comp.position))

        if len(pad_positions) < 2:
            continue

        edges = build_minimum_spanning_tree(pad_positions)
        for (_ref1, _pin1, pos1), (_ref2, _pin2, pos2) in edges:
            net_definitions.append(
                NetDefinition(
                    name=net_name,
                    start=pos1,
                    end=pos2,
                    layer=default_layer,
                    priority=0,
                    width_mm=width_mm,
                    clearance_mm=clearance_mm,
                )
            )

    return net_definitions
