from __future__ import annotations

from typing import Optional, Dict

from pcb_tool.commands.routing import AutoRouteCommand
from pcb_tool.data_model import Board
from pcb_tool.routing.constraints import RoutingConstraints
from pcb_tool.routing.results import RouteResult


def autoroute(
    board: Board,
    *,
    net_name: str = "ALL",
    prefer_layer: Optional[str] = None,
    ground_plane_mode: bool = False,
    via_costs: Optional[Dict[str, float]] = None,
    manual_routes: Optional[Dict[str, Dict]] = None,
    constraints: Optional[RoutingConstraints] = None,
    verbose: bool = False,
) -> RouteResult:
    """Autoroute nets on the given board (mutates `board`).

    This is a thin wrapper around the existing routing command implementation,
    but returns a structured `RouteResult` for programmatic use.
    """
    cmd = AutoRouteCommand(
        net_name=net_name,
        prefer_layer=prefer_layer,
        ground_plane_mode=ground_plane_mode,
        via_costs=via_costs,
        manual_routes=manual_routes,
        constraints=constraints,
        verbose=verbose,
    )

    validation_error = cmd.validate(board)
    if validation_error:
        raise ValueError(validation_error)

    return cmd.execute_result(board)
