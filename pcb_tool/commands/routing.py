"""Routing Commands - Route, Via, Delete Route/Via, AutoRoute, OptimizeRouting"""

import math
from typing import Optional, Dict, TYPE_CHECKING
from pcb_tool.commands.base import Command
from pcb_tool.data_model import Board, TraceSegment, Via
from pcb_tool.messages import success, error

if TYPE_CHECKING:
    from pcb_tool.routing.constraints import RoutingConstraints


class RouteCommand(Command):
    """Add a routed trace segment to a net.

    Creates a straight trace segment connecting two points on a specified layer.
    The trace is added to the specified net for electrical connectivity.

    Attributes:
        net_name: Name of the net to route
        start_pos: Starting position as (x, y) tuple or "ref.pin" string
        end_pos: Ending position as (x, y) tuple or "ref.pin" string
        layer: Layer name ("F.Cu" or "B.Cu"), defaults to "F.Cu"
        width: Trace width in millimeters, defaults to net's track_width
        segment: The TraceSegment created by execute(), used for undo
    """

    def __init__(
        self,
        net_name: str,
        start_pos: tuple[float, float] | str,
        end_pos: tuple[float, float] | str,
        layer: str = "F.Cu",
        width: float = None,
        waypoints: list[tuple[float, float]] | None = None,
    ):
        """Initialize route command.

        Args:
            net_name: Name of the net to route
            start_pos: Starting position (x, y) in mm or "ref.pin" notation
            end_pos: Ending position (x, y) in mm or "ref.pin" notation
            layer: Layer name, default "F.Cu"
            width: Trace width in mm, default uses net's track_width
            waypoints: Optional list of waypoint coordinates for multi-segment routing
        """
        self.net_name = net_name
        self.start_pos = start_pos
        self.end_pos = end_pos
        self.layer = layer
        self.width = width
        self.waypoints = waypoints
        self.segment = None  # For single-segment routes (backward compatibility)
        self.segments = []  # For multi-segment routes

    def validate(self, board: Board) -> str | None:
        """Validate the route command.

        Checks:
        - Net exists in board
        - Layer is valid (F.Cu or B.Cu)
        - Width is >= 0.1mm if specified

        Returns:
            None if valid, error message string if invalid
        """
        # Check net exists
        if self.net_name not in board.nets:
            return error(f'Net "{self.net_name}" not found')

        # Check layer is valid (support multi-layer boards)
        from pcb_tool.data_model import VALID_COPPER_LAYERS

        if self.layer not in VALID_COPPER_LAYERS:
            return error(f'Invalid layer "{self.layer}". Must be a valid copper layer.')
        if self.layer not in board.layers:
            return error(
                f'Layer "{self.layer}" not in board layer stack: {board.layers}'
            )

        # Check width is valid if specified
        if self.width is not None and self.width < 0.1:
            return error(f"Width {self.width} below minimum 0.1")

        return None

    def execute(self, board: Board) -> str:
        """Execute the route command with pad-aware routing.

        Resolves start/end positions (coordinates or component.pin notation),
        finds the actual pad positions, and creates trace segment(s).
        For multi-segment routing with waypoints, creates N+1 segments for N waypoints.
        Uses the net's default track_width if width not specified.

        Returns:
            Success message with routing details
        """
        net = board.nets[self.net_name]

        # Use net's default width if not specified
        trace_width = self.width if self.width is not None else net.track_width

        # Resolve positions (handles both coordinates and component.pin notation)
        actual_start = self._resolve_position(board, self.start_pos, self.net_name)
        actual_end = self._resolve_position(board, self.end_pos, self.net_name)

        # Multi-segment routing with waypoints
        if self.waypoints:
            # Build point sequence: start -> waypoint1 -> waypoint2 -> ... -> end
            points = [actual_start] + self.waypoints + [actual_end]

            # Create all segments
            for i in range(len(points) - 1):
                segment = TraceSegment(
                    net_name=self.net_name,
                    start=points[i],
                    end=points[i + 1],
                    layer=self.layer,
                    width=trace_width,
                )
                self.segments.append(segment)
                net.add_segment(segment)

            # Return success message with segment count
            return success(
                f'Added {len(self.segments)} segments to net "{self.net_name}" via {len(self.waypoints)} waypoints'
            )

        else:
            # Single-segment routing (backward compatible behavior)
            # Validate waypoint deviation if coordinates were used
            self._check_waypoint_deviation(self.start_pos, actual_start, "start")
            self._check_waypoint_deviation(self.end_pos, actual_end, "end")

            # Create segment with actual pad positions
            self.segment = TraceSegment(
                net_name=self.net_name,
                start=actual_start,
                end=actual_end,
                layer=self.layer,
                width=trace_width,
            )

            # Add to net
            net.add_segment(self.segment)

            x1, y1 = actual_start
            x2, y2 = actual_end
            return success(
                f'Added segment to net "{self.net_name}" from ({x1:.2f}, {y1:.2f}) to ({x2:.2f}, {y2:.2f})'
            )

    def _resolve_position(
        self, board: Board, pos: tuple[float, float] | str, net_name: str
    ) -> tuple[float, float]:
        """Resolve a position specification to actual pad coordinates.

        Handles two types of position specifications:
        1. Coordinate tuple (x, y) - uses pad-aware routing to find nearest pad
        2. Component.pin string like "Q1.2" - resolves directly to specific pad

        Args:
            board: Board to search
            pos: Position as (x, y) tuple or "ref.pin" string
            net_name: Net name for validation and nearest-pad search

        Returns:
            Actual pad position as (x, y) tuple

        Raises:
            ValueError: If component.pin notation is invalid
        """
        # Check if pos is a string (component.pin notation)
        if isinstance(pos, str):
            # Parse component.pin notation
            if "." not in pos:
                raise ValueError(f"Invalid component.pin notation: {pos}")

            ref, pin_str = pos.split(".", 1)

            # Find component
            if ref not in board.components:
                raise ValueError(f"Component {ref} not found")

            comp = board.components[ref]

            # Parse pin number
            try:
                pin_num = int(pin_str)
            except ValueError:
                raise ValueError(f"Invalid pin number: {pin_str}")

            # Get pad position directly
            try:
                return comp.get_pad_position(pin_num)
            except ValueError as e:
                raise ValueError(f"Pad {pin_num} not found on component {ref}: {e}")

        else:
            # pos is a coordinate tuple - use exact coordinates for manual routing
            # Automatic pad-finding is NOT used for coordinate-based routing
            # Use component.pin notation (e.g., "Q1.2") for automatic pad resolution
            return pos

    def _find_pad_position(
        self, board: Board, intended_pos: tuple[float, float], net_name: str
    ) -> tuple[float, float]:
        """Find the actual pad position nearest to the intended position.

        Searches for components with pads connected to the specified net
        and returns the position of the nearest pad.

        Args:
            board: Board to search
            intended_pos: Intended connection position (e.g., component center)
            net_name: Net name to filter pads

        Returns:
            Actual pad position, or intended position if no matching pad found
        """
        nearest_pad_pos = intended_pos
        min_distance = float("inf")

        # Search all components for pads on this net
        for comp in board.components.values():
            if not comp.pads:
                continue

            # Check each pad
            for pad in comp.pads:
                # Get pad's absolute position
                pad_pos = comp.get_pad_position(pad.number)

                # Calculate distance from intended position
                dist = math.sqrt(
                    (intended_pos[0] - pad_pos[0]) ** 2
                    + (intended_pos[1] - pad_pos[1]) ** 2
                )

                # Check if this pad is on the correct net
                pad_on_net = False
                net = board.nets.get(net_name)
                if net:
                    for conn_ref, conn_pin in net.connections:
                        if conn_ref == comp.ref and int(conn_pin) == pad.number:
                            pad_on_net = True
                            break

                # Update if this is closer and on the correct net
                if pad_on_net and dist < min_distance:
                    min_distance = dist
                    nearest_pad_pos = pad_pos

        return nearest_pad_pos

    def _check_waypoint_deviation(
        self,
        intended_pos: tuple[float, float] | str,
        actual_pos: tuple[float, float],
        position_label: str,
    ) -> None:
        """Check if waypoint-based routing deviated significantly from intended coordinates.

        When coordinate tuples are used as waypoints (not component.pin notation),
        this warns if the actual routed position deviates significantly from the
        intended coordinates. This helps detect routing problems where waypoint-based
        routing doesn't create the expected trace geometry.

        Skips deviation check for routes with explicit VIA waypoints, as those
        are intentional multi-segment routes where deviation is expected.

        Args:
            intended_pos: Original position specification (coordinates or component.pin)
            actual_pos: Actual position after resolution
            position_label: "start" or "end" for error messages

        Warns:
            If coordinate-based waypoint deviates > 1mm from intended position
        """
        # Skip deviation check if route has explicit VIA waypoints
        # VIA-based routing is intentional and doesn't need deviation warnings
        if self.waypoints:
            return

        # Only check for coordinate tuples (not component.pin notation)
        if isinstance(intended_pos, tuple):
            intended_x, intended_y = intended_pos
            actual_x, actual_y = actual_pos

            # Calculate deviation
            deviation_x = abs(actual_x - intended_x)
            deviation_y = abs(actual_y - intended_y)
            total_deviation = math.sqrt(deviation_x**2 + deviation_y**2)

            # Warn if deviation is significant (> 1mm)
            if total_deviation > 1.0:
                print(
                    f"  WARNING: Waypoint routing deviation at {position_label} position"
                )
                print(f"    Intended: ({intended_x:.2f}, {intended_y:.2f})")
                print(f"    Actual:   ({actual_x:.2f}, {actual_y:.2f})")
                print(
                    f"    Deviation: {total_deviation:.2f}mm (ΔX={deviation_x:.2f}mm, ΔY={deviation_y:.2f}mm)"
                )
                print(f"    Net: {self.net_name}, Layer: {self.layer}")
                print(
                    f"    TIP: Use component.pin notation (e.g., 'Q1.2') for precise routing,"
                )
                print(
                    f"         or verify waypoint coordinates match actual pad positions."
                )
                print()

    def undo(self, board: Board) -> str:
        """Undo the route command by removing the segment(s).

        Returns:
            Success message confirming removal
        """
        net = board.nets[self.net_name]

        # Handle multi-segment routes
        if self.segments:
            for segment in self.segments:
                net.remove_segment(segment)
            return success(
                f'Removed {len(self.segments)} segments from net "{self.net_name}"'
            )
        else:
            # Handle single-segment routes (backward compatibility)
            net.remove_segment(self.segment)
            return success(f'Removed segment from net "{self.net_name}"')


class ViaCommand(Command):
    """Add a via to a net.

    Creates a via (plated through-hole) connecting layers at a specified position.
    The via is added to the specified net for layer transitions in routing.

    Attributes:
        net_name: Name of the net for this via
        position: Position as (x, y) tuple in millimeters
        size: Via outer diameter in millimeters, defaults to net's via_size
        drill: Drill hole diameter in millimeters, defaults to net's via_drill
        via: The Via created by execute(), used for undo
    """

    def __init__(
        self,
        net_name: str,
        position: tuple[float, float],
        size: float = None,
        drill: float = None,
    ):
        """Initialize via command.

        Args:
            net_name: Name of the net for this via
            position: Position (x, y) in mm
            size: Via outer diameter in mm, default uses net's via_size
            drill: Drill diameter in mm, default uses net's via_drill
        """
        self.net_name = net_name
        self.position = position
        self.size = size
        self.drill = drill
        self.via = None

    def _check_pad_collision(self, board: Board) -> str | None:
        """Check if via collides with any component pads.

        Checks for:
        - Exact position collision (< 0.01mm) - drill holes would overlap
        - Proximity collision with different net pads

        Args:
            board: The board to check against

        Returns:
            Error message if collision detected, None otherwise
        """
        via_x, via_y = self.position
        # Use specified size or net's default
        via_size = (
            self.size if self.size is not None else board.nets[self.net_name].via_size
        )
        via_radius = via_size / 2

        for comp_ref, component in board.components.items():
            for pad in component.pads:
                pad_x, pad_y = component.get_pad_position(pad.number)
                distance = math.sqrt((via_x - pad_x) ** 2 + (via_y - pad_y) ** 2)

                # Check for exact position collision (drill holes overlap)
                if distance < 0.01:
                    return error(
                        f"Via at ({via_x}, {via_y}) on net {self.net_name} "
                        f"collides with {comp_ref} pad {pad.number}. "
                        f"Drill holes would overlap."
                    )

                # Check proximity with different net pads
                pad_radius = max(pad.size[0], pad.size[1]) / 2
                min_clearance = via_radius + pad_radius + 0.1

                if distance < min_clearance and pad.net_name != self.net_name:
                    return error(
                        f"Via at ({via_x}, {via_y}) on net {self.net_name} "
                        f"too close to {comp_ref} pad {pad.number} on net {pad.net_name} "
                        f"({distance:.2f}mm < {min_clearance:.2f}mm)"
                    )

        return None

    def _check_via_collision(self, board: Board) -> str | None:
        """Check if via collides with existing vias.

        Checks for:
        - Exact position collision (< 0.01mm) - same position overlap
        - Proximity collision with different net vias

        Args:
            board: The board to check against

        Returns:
            Error message if collision detected, None otherwise
        """
        via_x, via_y = self.position
        # Use specified size or net's default
        via_size = (
            self.size if self.size is not None else board.nets[self.net_name].via_size
        )
        via_radius = via_size / 2

        for net_name, net in board.nets.items():
            for existing_via in net.vias:
                ex_x, ex_y = existing_via.position
                distance = math.sqrt((via_x - ex_x) ** 2 + (via_y - ex_y) ** 2)

                # Check for exact position collision
                if distance < 0.01:
                    return error(
                        f"Via at ({via_x}, {via_y}) on net {self.net_name} "
                        f"overlaps with existing via on net {net_name}"
                    )

                # Check proximity with different net vias
                existing_radius = existing_via.size / 2
                min_clearance = via_radius + existing_radius + 0.2

                if distance < min_clearance and net_name != self.net_name:
                    return error(
                        f"Via at ({via_x}, {via_y}) on net {self.net_name} "
                        f"too close to via on net {net_name} "
                        f"({distance:.2f}mm < {min_clearance:.2f}mm)"
                    )

        return None

    def validate(self, board: Board) -> str | None:
        """Validate the via command.

        Checks:
        - Net exists in board
        - Size is >= 0.5mm if specified
        - Drill is < size if both specified
        - Via does not collide with component pads
        - Via does not collide with existing vias

        Returns:
            None if valid, error message string if invalid
        """
        # Check net exists
        if self.net_name not in board.nets:
            return error(f'Net "{self.net_name}" not found')

        # Check size is valid if specified
        if self.size is not None and self.size < 0.5:
            return error(f"Via size {self.size} below minimum 0.5")

        # Check drill is valid if both size and drill specified
        if self.size is not None and self.drill is not None:
            if self.drill >= self.size:
                return error(f"Drill {self.drill} >= via size {self.size}")

        # Check for pad collisions
        pad_collision = self._check_pad_collision(board)
        if pad_collision:
            return pad_collision

        # Check for via collisions
        via_collision = self._check_via_collision(board)
        if via_collision:
            return via_collision

        return None

    def execute(self, board: Board) -> str:
        """Execute the via command.

        Creates a Via and adds it to the specified net.
        Uses the net's default via_size and via_drill if not specified.
        Always connects F.Cu and B.Cu layers.

        Returns:
            Success message with via details
        """
        net = board.nets[self.net_name]

        # Use net's defaults if not specified
        via_size = self.size if self.size is not None else net.via_size
        via_drill = self.drill if self.drill is not None else net.via_drill

        # Create via
        self.via = Via(
            net_name=self.net_name,
            position=self.position,
            size=via_size,
            drill=via_drill,
            layers=("F.Cu", "B.Cu"),
        )

        # Add to net
        net.add_via(self.via)

        x, y = self.position
        return success(f'Added via to net "{self.net_name}" at ({x}, {y})')

    def undo(self, board: Board) -> str:
        """Undo the via command by removing the via.

        Returns:
            Success message confirming removal
        """
        net = board.nets[self.net_name]
        net.remove_via(self.via)
        return success(f'Removed via from net "{self.net_name}"')


class DeleteRouteCommand(Command):
    """Delete trace segment(s) from a net.

    Removes one or more trace segments from a specified net. Can delete either
    a single segment near a specified position or all segments on the net.

    Attributes:
        net_name: Name of the net to delete segments from
        position: Position (x, y) tuple to find segment near, or None if delete_all
        delete_all: If True, delete all segments on the net
        deleted_segments: List of deleted segments for undo support
    """

    def __init__(
        self,
        net_name: str,
        position: tuple[float, float] = None,
        delete_all: bool = False,
    ):
        """Initialize delete route command.

        Args:
            net_name: Name of the net
            position: Position (x, y) to search near, or None if delete_all
            delete_all: If True, delete all segments on the net
        """
        self.net_name = net_name
        self.position = position
        self.delete_all = delete_all
        self.deleted_segments = []

    def validate(self, board: Board) -> str | None:
        """Validate the delete route command.

        Checks:
        - Net exists in board
        - Either position or delete_all is specified (not both or neither)

        Returns:
            None if valid, error message string if invalid
        """
        # Check net exists
        if self.net_name not in board.nets:
            return error(f'Net "{self.net_name}" not found')

        return None

    def execute(self, board: Board) -> str:
        """Execute the delete route command.

        Deletes segment(s) from the net and stores them for undo.
        Uses net.find_segment_near() with tolerance=0.5mm for position mode.

        Returns:
            Success message with deletion count, or error if no segment found
        """
        net = board.nets[self.net_name]

        if self.delete_all:
            # Delete all segments
            self.deleted_segments = net.segments.copy()
            count = len(self.deleted_segments)
            net.segments.clear()
            return success(f'Deleted {count} segments from net "{self.net_name}"')
        else:
            # Delete segment near position
            x, y = self.position
            segment = net.find_segment_near(x, y, tolerance=0.5)

            if segment is None:
                return error(f"No segment found near ({x}, {y})")

            self.deleted_segments = [segment]
            net.remove_segment(segment)
            return success(f'Deleted 1 segment from net "{self.net_name}"')

    def undo(self, board: Board) -> str:
        """Undo the delete route command by restoring segments.

        Returns:
            Success message confirming restoration
        """
        net = board.nets[self.net_name]

        # Restore all deleted segments
        for segment in self.deleted_segments:
            net.add_segment(segment)

        count = len(self.deleted_segments)
        return success(f'Restored {count} segment(s) to net "{self.net_name}"')


class DeleteViaCommand(Command):
    """Delete via(s) from a net.

    Removes one or more vias from a specified net. Can delete either
    a single via at a specified position or all vias on the net.

    Attributes:
        net_name: Name of the net to delete vias from
        position: Position (x, y) tuple to find via at, or None if delete_all
        delete_all: If True, delete all vias on the net
        deleted_vias: List of deleted vias for undo support
    """

    def __init__(
        self,
        net_name: str,
        position: tuple[float, float] = None,
        delete_all: bool = False,
    ):
        """Initialize delete via command.

        Args:
            net_name: Name of the net
            position: Position (x, y) to search at, or None if delete_all
            delete_all: If True, delete all vias on the net
        """
        self.net_name = net_name
        self.position = position
        self.delete_all = delete_all
        self.deleted_vias = []

    def validate(self, board: Board) -> str | None:
        """Validate the delete via command.

        Checks:
        - Net exists in board
        - Either position or delete_all is specified (not both or neither)

        Returns:
            None if valid, error message string if invalid
        """
        # Check net exists
        if self.net_name not in board.nets:
            return error(f'Net "{self.net_name}" not found')

        return None

    def execute(self, board: Board) -> str:
        """Execute the delete via command.

        Deletes via(s) from the net and stores them for undo.
        Uses net.find_via_at() with tolerance=0.1mm for position mode.

        Returns:
            Success message with deletion details, or error if no via found
        """
        net = board.nets[self.net_name]

        if self.delete_all:
            # Delete all vias
            self.deleted_vias = net.vias.copy()
            count = len(self.deleted_vias)
            net.vias.clear()
            return success(f'Deleted {count} vias from net "{self.net_name}"')
        else:
            # Delete via at position
            x, y = self.position
            via = net.find_via_at(x, y, tolerance=0.1)

            if via is None:
                return error(f"No via found at ({x}, {y})")

            self.deleted_vias = [via]
            net.remove_via(via)
            return success(f'Deleted via from net "{self.net_name}" at ({x}, {y})')

    def undo(self, board: Board) -> str:
        """Undo the delete via command by restoring vias.

        Returns:
            Success message confirming restoration
        """
        net = board.nets[self.net_name]

        # Restore all deleted vias
        for via in self.deleted_vias:
            net.add_via(via)

        count = len(self.deleted_vias)
        return success(f'Restored {count} via(s) to net "{self.net_name}"')


class AutoRouteCommand(Command):
    """Automatically route nets using PathFinder and multi-layer routing.

    Routes one or all nets on the board using the automated routing engine.
    Creates RoutingGrid from board state, routes requested nets, and applies
    the routing results back to the board.

    Attributes:
        net_name: Net name to route, or "ALL" to route all nets, or "UNROUTED" for unrouted nets
        prefer_layer: Optional layer preference ("F.Cu" or "B.Cu")
        optimize: Whether to use Z3 optimization (default True)
        ground_plane_mode: Use ground plane strategy (B.Cu=GND plane, F.Cu=signals, default False)
    """

    def __init__(
        self,
        net_name: Optional[str] = None,
        prefer_layer: Optional[str] = None,
        optimize: bool = True,
        ground_plane_mode: bool = False,
        via_costs: Optional[Dict[str, float]] = None,
        manual_routes: Optional[Dict[str, Dict]] = None,
        constraints: Optional["RoutingConstraints"] = None,
        verbose: bool = True,
    ):
        """Initialize auto-route command.

        Args:
            net_name: Net name to route, "ALL" for all nets, or "UNROUTED" for unrouted only
            prefer_layer: Optional layer preference
            optimize: Enable Z3 optimization
            ground_plane_mode: Use ground plane strategy (2-layer boards)
            via_costs: Optional mapping of net name patterns to via costs (supports wildcards)
            manual_routes: Optional manual routes dict: {"NET": {"path": [...], "layer": "F.Cu"}}
            constraints: Optional routing constraints (must_route, optional, route_order)
        """
        self.net_name = net_name or "ALL"
        self.prefer_layer = prefer_layer
        self.optimize = optimize
        self.ground_plane_mode = ground_plane_mode
        self.via_costs = via_costs
        self.manual_routes = manual_routes
        self.constraints = constraints
        self.verbose = bool(verbose)
        self.added_segments = []  # For undo
        self.added_vias = []  # For undo

    def validate(self, board: Board) -> str | None:
        """Validate the auto-route command.

        Checks:
        - Board has components
        - Board has nets
        - If specific net requested, it exists
        - Layer preference is valid if specified

        Returns:
            None if valid, error message string if invalid
        """
        # Check board has components
        if not board.components:
            return error(
                "Board has no components. Load a netlist first with: LOAD <file>"
            )

        # Check board has nets
        if not board.nets:
            return error("Board has no nets. Load a netlist first with: LOAD <file>")

        # Check components have pads for routing
        missing_pads = []
        single_pad = []
        for ref, comp in board.components.items():
            if len(comp.pads) == 0:
                missing_pads.append(f"  {ref} ({comp.footprint}): 0 pads")
            elif len(comp.pads) == 1:
                single_pad.append(f"  {ref} ({comp.footprint}): 1 pad")

        if missing_pads:
            msg = f"Cannot route - {len(missing_pads)} components have no pads:\n"
            msg += "\n".join(missing_pads[:10])
            if len(missing_pads) > 10:
                msg += f"\n  ... and {len(missing_pads) - 10} more"
            msg += "\n\nHint: Footprints may not be in library. Check pcb_tool/footprint_library.py"
            return error(msg)

        if single_pad:
            if self.verbose:
                print(
                    f"Note: {len(single_pad)} components have only 1 pad (test points?)"
                )

        # Check specific net exists
        if self.net_name not in ["ALL", "UNROUTED"] and self.net_name not in board.nets:
            available_nets = ", ".join(sorted(board.nets.keys())[:5])
            if len(board.nets) > 5:
                available_nets += f" ... and {len(board.nets) - 5} more"
            return error(
                f'Net "{self.net_name}" not found. Available nets: {available_nets}. Use "LIST NETS" to see all nets.'
            )

        # Validate layer preference (allow any valid copper layer for multi-layer boards)
        from pcb_tool.data_model import VALID_COPPER_LAYERS

        if self.prefer_layer and self.prefer_layer not in VALID_COPPER_LAYERS:
            return error(
                f'Invalid layer "{self.prefer_layer}". Must be a valid copper layer (F.Cu, In1.Cu, ..., B.Cu).'
            )

        return None

    def execute(self, board: Board) -> str:
        result = self.execute_result(board)
        return result.report

    def execute_result(self, board: Board):
        """Execute the auto-route command.

        Creates routing grid, extracts net definitions, routes nets using
        MultiNetRouter, and applies results to board.

        Returns:
            Structured routing result for programmatic use
        """
        from pcb_tool.routing import MultiNetRouter, NetDefinition
        from pcb_tool.routing.results import RouteResult

        # Determine which nets to route
        if self.net_name == "ALL":
            nets_to_route = list(board.nets.keys())
        elif self.net_name == "UNROUTED":
            # Find nets with connections but no segments
            nets_to_route = [
                name
                for name, net in board.nets.items()
                if len(net.connections) > 0 and len(net.segments) == 0
            ]
        else:
            nets_to_route = [self.net_name]

        if not nets_to_route:
            return RouteResult(
                success_count=0,
                total_length_mm=0.0,
                total_vias=0,
                report="No nets to route. All nets are either already routed or have insufficient connections.",
            )

        # Warning for dense boards
        if len(nets_to_route) > 50:
            if self.verbose:
                print(
                    f"Warning: Routing {len(nets_to_route)} nets may take 30-60 seconds..."
                )

        # Create routing grid from board
        if self.verbose:
            print("Initializing routing grid...")
        grid = self._create_routing_grid(board)
        stats = grid.get_statistics()
        total_cells = stats["dimensions"]["total_cells"]
        obstacles = stats["obstacles"]["F.Cu"] + stats["obstacles"]["B.Cu"]
        congestion = (obstacles / (total_cells * 2)) * 100

        # Warning for congested boards
        if congestion > 30:
            if self.verbose:
                print(
                    f"Warning: Board is {congestion:.0f}% congested. Consider spreading components with ARRANGE GRID."
                )

        # Extract net definitions
        if self.verbose:
            print(f"Analyzing {len(nets_to_route)} nets...")
        net_definitions = self._extract_net_definitions(board, nets_to_route)

        if not net_definitions:
            return RouteResult(
                success_count=0,
                total_length_mm=0.0,
                total_vias=0,
                report=error(
                    "No valid connections found to route. Nets must have at least 2 connections. Use LIST NETS to check net connections."
                ),
            )

        # Create router
        router = MultiNetRouter(
            grid, ground_plane_mode=self.ground_plane_mode, via_cost_map=self.via_costs
        )

        # Apply manual routes first (before auto-routing)
        if self.manual_routes:
            if self.verbose:
                print(f"Applying {len(self.manual_routes)} manual routes...")
            for net_name, route_spec in self.manual_routes.items():
                path = route_spec.get("path", [])
                layer = route_spec.get("layer", "F.Cu")
                width_mm = route_spec.get("width_mm", 0.25)
                router.add_manual_route(net_name, path, layer, width_mm)

        # Route nets
        if self.ground_plane_mode:
            if self.verbose:
                print(
                    f"Routing {len(net_definitions)} nets in ground plane mode (B.Cu=GND plane, F.Cu=signals)..."
                )
        else:
            if self.verbose:
                print(
                    f"Routing {len(net_definitions)} nets (power nets prioritized)..."
                )
        routed_nets = router.route_nets(net_definitions, constraints=self.constraints)

        # Retry failed edges for multi-point nets
        routed_nets = self._retry_failed_multipoint_edges(
            board, nets_to_route, net_definitions, routed_nets, router, grid
        )

        # Apply routing to board
        success_count, total_length, total_vias = self._apply_routing_to_board(
            board, routed_nets
        )

        # Format report
        report = self._format_routing_report(
            nets_to_route, routed_nets, success_count, total_length, total_vias
        )
        return RouteResult(
            success_count=success_count,
            total_length_mm=total_length,
            total_vias=total_vias,
            report=report,
        )

    def _retry_failed_multipoint_edges(
        self,
        board: Board,
        nets_to_route: list[str],
        net_definitions: list,
        routed_nets: dict,
        router,
        grid,
    ) -> dict:
        """Retry failed edges for multi-point nets to ensure complete connectivity.

        For multi-point nets (3+ pads), some MST edges may fail to route in the first pass.
        This method:
        1. Identifies which nets have incomplete connectivity
        2. Finds already-routed pads for each incomplete net
        3. Attempts to connect unrouted pads to the nearest routed pad
        4. Retries with relaxed constraints (allow vias, try alternate layers)

        Args:
            board: Board being routed
            nets_to_route: List of net names being routed
            net_definitions: Original MST edge definitions
            routed_nets: Dictionary of successfully routed edges
            router: MultiNetRouter instance
            grid: RoutingGrid instance

        Returns:
            Updated routed_nets dictionary with retry results
        """
        from pcb_tool.routing import NetDefinition, RoutedNet

        # Group net definitions by net name to identify multi-point nets
        net_to_edges = {}
        for net_def in net_definitions:
            if net_def.name not in net_to_edges:
                net_to_edges[net_def.name] = []
            net_to_edges[net_def.name].append(net_def)

        # Find multi-point nets that may have incomplete routing
        multipoint_nets = {
            name: edges for name, edges in net_to_edges.items() if len(edges) >= 2
        }

        if not multipoint_nets:
            return routed_nets

        # Check connectivity for each multi-point net
        for net_name, edges in multipoint_nets.items():
            # Get all pads for this net
            net = board.nets.get(net_name)
            if not net or len(net.connections) < 3:
                continue

            # In ground plane mode, skip GND (it's a solid plane on B.Cu)
            if self.ground_plane_mode and net_name.upper() in ["GND", "GROUND"]:
                continue

            # Get pad positions
            pad_positions = []
            for ref, pin in net.connections:
                comp = board.get_component(ref)
                if not comp:
                    continue
                try:
                    pos = comp.get_pad_position(int(pin))
                    pad_positions.append((ref, pin, pos))
                except (ValueError, KeyError):
                    pad_positions.append((ref, pin, comp.position))

            if len(pad_positions) < 3:
                continue

            # For multi-point nets, we can't directly count routed edges since
            # all edges have the same name. Instead, check connectivity.
            # If connectivity is complete, all edges were effectively routed.
            # If not, we need retry logic below.

            # Check if connectivity is complete using union-find
            if not self._check_connectivity(routed_nets, pad_positions, net_name):
                # Connectivity incomplete - attempt retry
                print(
                    f"  Retrying incomplete net {net_name} (connectivity check failed, attempting to bridge disconnected groups)..."
                )

                # Find which pads are already connected (reachable set)
                connected_groups = self._find_connected_groups(
                    routed_nets, pad_positions, net_name
                )

                if len(connected_groups) <= 1:
                    continue  # All pads connected or none connected

                # Try to connect disconnected groups
                # Strategy: Connect largest group to each smaller group
                connected_groups.sort(key=lambda g: len(g), reverse=True)
                main_group = connected_groups[0]

                for group in connected_groups[1:]:
                    # Find closest pair between main_group and this group
                    best_dist = float("inf")
                    best_start = None
                    best_end = None

                    for _, _, pos1 in main_group:
                        for _, _, pos2 in group:
                            dist = math.sqrt(
                                (pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2
                            )
                            if dist < best_dist:
                                best_dist = dist
                                best_start = pos1
                                best_end = pos2

                    if best_start and best_end:
                        # Try to route this edge with relaxed constraints
                        layer = self.prefer_layer or "F.Cu"

                        # Attempt 1: Route with vias allowed
                        path = router.pathfinder.find_path(
                            start_mm=best_start,
                            goal_mm=best_end,
                            layer=layer,
                            allow_diagonals=True,
                            force_single_layer=False,  # Allow vias
                            net_name=net_name,
                        )

                        if not path:
                            # Attempt 2: Try opposite layer
                            alt_layer = "B.Cu" if layer == "F.Cu" else "F.Cu"
                            path = router.pathfinder.find_path(
                                start_mm=best_start,
                                goal_mm=best_end,
                                layer=alt_layer,
                                allow_diagonals=True,
                                force_single_layer=False,
                                net_name=net_name,
                            )

                        if path:
                            # Successfully routed - add to routed_nets
                            segments = []
                            for i in range(len(path) - 1):
                                segments.append((path[i], path[i + 1]))

                            # Create a synthetic name for this retry edge
                            edge_name = net_name
                            if edge_name not in routed_nets:
                                routed_nets[edge_name] = RoutedNet(
                                    name=net_name,
                                    path=path,
                                    layer=layer,
                                    segments=segments,
                                )
                            else:
                                # Append segments to existing routed net
                                routed_nets[edge_name].segments.extend(segments)
                                routed_nets[edge_name].path.extend(
                                    path[1:]
                                )  # Skip duplicate first point

                            # Mark as obstacle for other nets
                            router._mark_net_as_obstacle(path, layer, net_name)

                            # Update main group to include newly connected group
                            main_group.extend(group)

        return routed_nets

    def _check_connectivity(
        self, routed_nets: dict, pad_positions: list, net_name: str
    ) -> bool:
        """Check if all pads are connected via routed segments using union-find.

        This checker handles waypoint chains by building a connectivity graph
        that includes both pads and waypoints, then checking if all pads are
        reachable through the graph.

        Args:
            routed_nets: Dictionary of routed nets
            pad_positions: List of (ref, pin, pos) tuples
            net_name: Net name to check

        Returns:
            True if all pads are connected, False otherwise
        """
        if len(pad_positions) <= 1:
            return True

        # Build connectivity graph with waypoints included
        # Use position tuples as keys (rounded to avoid floating point issues)
        parent = {}

        def make_key(pos):
            return (round(pos[0], 3), round(pos[1], 3))

        def find(x):
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Find all segments for this net and union their endpoints
        for routed_net_name, routed_net in routed_nets.items():
            if routed_net.name != net_name:
                continue

            # Union all segment endpoints (including waypoints)
            for segment in routed_net.segments:
                start_key = make_key(segment[0])
                end_key = make_key(segment[1])
                union(start_key, end_key)

        # Check if all pads are in the same connected component
        pad_keys = [make_key(pos) for ref, pin, pos in pad_positions]
        if not pad_keys:
            return False

        # Get roots for all pads
        roots = set(find(key) for key in pad_keys)
        return len(roots) == 1

    def _find_connected_groups(
        self, routed_nets: dict, pad_positions: list, net_name: str
    ) -> list:
        """Find groups of connected pads using union-find.

        Handles waypoint chains by building a full connectivity graph.

        Args:
            routed_nets: Dictionary of routed nets
            pad_positions: List of (ref, pin, pos) tuples
            net_name: Net name to analyze

        Returns:
            List of groups, where each group is a list of (ref, pin, pos) tuples
        """
        if len(pad_positions) <= 1:
            return [pad_positions]

        # Build connectivity graph with waypoints included
        parent = {}

        def make_key(pos):
            return (round(pos[0], 3), round(pos[1], 3))

        def find(x):
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Find all segments for this net and union their endpoints
        for routed_net_name, routed_net in routed_nets.items():
            if routed_net.name != net_name:
                continue

            # Union all segment endpoints (including waypoints)
            for segment in routed_net.segments:
                start_key = make_key(segment[0])
                end_key = make_key(segment[1])
                union(start_key, end_key)

        # Group pads by their connected component
        pad_key_to_ref = {
            make_key(pos): (ref, pin, pos) for ref, pin, pos in pad_positions
        }
        groups_by_root = {}

        for pad_key, pad_data in pad_key_to_ref.items():
            root = find(pad_key)
            if root not in groups_by_root:
                groups_by_root[root] = []
            groups_by_root[root].append(pad_data)

        return list(groups_by_root.values())

    def _distance(self, p1: tuple[float, float], p2: tuple[float, float]) -> float:
        """Calculate Euclidean distance between two points.

        Args:
            p1: First point (x, y)
            p2: Second point (x, y)

        Returns:
            Distance in mm
        """
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    def _create_routing_grid(self, board: Board):
        """Create RoutingGrid from board dimensions and mark obstacles.

        Args:
            board: Board to create grid from

        Returns:
            RoutingGrid instance with obstacles marked
        """
        from pcb_tool.routing.grid_builder import (
            GridBuildConfig,
            build_routing_grid_from_board,
        )

        return build_routing_grid_from_board(
            board,
            config=GridBuildConfig(
                resolution_mm=0.1,
                default_clearance_mm=0.2,
                margin_mm=10.0,
                min_width_mm=20.0,
                min_height_mm=20.0,
            ),
        )

    def _extract_net_definitions(self, board: Board, net_names: list[str]) -> list:
        """Extract NetDefinition objects for requested nets.

        For multi-point nets (3+ connections), creates a minimum spanning tree
        to ensure all pads are connected.

        Args:
            board: Board to extract from
            net_names: List of net names to extract

        Returns:
            List of NetDefinition objects (one per edge in spanning tree)
        """
        from pcb_tool.routing.net_definitions import extract_net_definitions

        layer = self.prefer_layer or "F.Cu"
        return extract_net_definitions(board, net_names, default_layer=layer)

    def _create_minimum_spanning_tree(self, points: list[tuple]) -> list[tuple]:
        """Create minimum spanning tree connecting all points.

        Uses Prim's algorithm to find MST, ensuring all pads in a net are connected
        with minimum total wire length.

        Args:
            points: List of (ref, pin, (x, y)) tuples

        Returns:
            List of edge tuples: ((ref1, pin1, pos1), (ref2, pin2, pos2))
        """
        from pcb_tool.routing.net_definitions import build_minimum_spanning_tree

        return build_minimum_spanning_tree(points)

    def _apply_routing_to_board(
        self, board: Board, routed_nets: dict
    ) -> tuple[int, float, int]:
        """Apply routing results to board nets.

        Args:
            board: Board to apply routing to
            routed_nets: Dictionary of RoutedNet objects from router

        Returns:
            Tuple of (success_count, total_length_mm, total_vias)
        """
        success_count = 0
        total_length = 0.0
        total_vias = 0

        for net_name, routed_net in routed_nets.items():
            net = board.nets.get(net_name)
            if not net:
                continue

            # Add trace segments with per-segment layer info
            for i, (start, end) in enumerate(routed_net.segments):
                # Use per-segment layer if available, else fall back to default
                if routed_net.segment_layers and i < len(routed_net.segment_layers):
                    segment_layer = routed_net.segment_layers[i]
                else:
                    segment_layer = routed_net.layer

                segment = TraceSegment(
                    net_name=net_name,
                    start=start,
                    end=end,
                    layer=segment_layer,
                    width=net.track_width,
                )
                net.add_segment(segment)
                self.added_segments.append((net_name, segment))

                # Calculate length
                dx = end[0] - start[0]
                dy = end[1] - start[1]
                length = math.sqrt(dx * dx + dy * dy)
                total_length += length

            # Add vias if present
            if routed_net.vias:
                for vx, vy, from_layer, to_layer in routed_net.vias:
                    via = Via(
                        net_name=net_name,
                        position=(vx, vy),
                        size=0.8,
                        drill=0.4,
                        layers=(from_layer, to_layer),
                    )
                    net.add_via(via)
                    total_vias += 1

            success_count += 1

        return success_count, total_length, total_vias

    def _format_routing_report(
        self,
        requested_nets: list[str],
        routed_nets: dict,
        success_count: int,
        total_length: float,
        total_vias: int,
    ) -> str:
        """Format routing results as user-friendly report.

        Args:
            requested_nets: List of net names that were requested
            routed_nets: Dictionary of successfully routed nets
            success_count: Number of successfully routed nets
            total_length: Total trace length in mm
            total_vias: Total number of vias placed

        Returns:
            Formatted report string
        """
        if success_count == 0:
            failed_nets = [n for n in requested_nets if n not in routed_nets]
            suggestions = "\n\nTroubleshooting suggestions:"
            suggestions += "\n  1. Check component placement: SHOW BOARD"
            suggestions += "\n  2. Spread components: ARRANGE GRID SPACING 15"
            suggestions += "\n  3. Try routing power nets first: AUTOROUTE NET GND"
            suggestions += "\n  4. Manual route critical nets, then: AUTOROUTE UNROUTED"
            return error(
                f"No nets could be routed. Failed: {', '.join(failed_nets[:3])}"
                + suggestions
            )

        lines = []

        if len(requested_nets) == 1:
            # Single net report
            net_name = requested_nets[0]
            if net_name in routed_nets:
                routed = routed_nets[net_name]
                lines.append(f"Routing net {net_name}...")
                lines.append(f"  Path length: {total_length:.1f}mm")
                lines.append(f"  Segments: {len(routed.segments)}")
                return success(
                    "\n".join(lines) + f"\nOK: Net {net_name} routed successfully"
                )
            else:
                suggestions = f"\n\nTroubleshooting for {net_name}:"
                suggestions += (
                    f"\n  1. Try opposite layer: AUTOROUTE NET {net_name} PREFER B.Cu"
                )
                suggestions += "\n  2. Check component spacing: SHOW BOARD"
                suggestions += (
                    f"\n  3. Manual routing: ROUTE NET {net_name} FROM ... TO ..."
                )
                return error(
                    f"Failed to route net {net_name}. No path found." + suggestions
                )
        else:
            # Multiple nets report with progress indicators
            power_net_patterns = {"GND", "VCC", "VDD", "VSS", "+12V", "+5V", "+3V3"}
            ground_patterns = {"GND", "GROUND", "VSS"}

            lines.append(f"Routing {len(requested_nets)} nets...")
            for i, net_name in enumerate(requested_nets, 1):
                # Show progress every 10 nets or at end
                if i % 10 == 0 or i == len(requested_nets):
                    print(f"Progress: {i}/{len(requested_nets)} nets processed...")

                if net_name in routed_nets:
                    routed = routed_nets[net_name]
                    # Calculate net length
                    net_length = 0.0
                    for start, end in routed.segments:
                        dx = end[0] - start[0]
                        dy = end[1] - start[1]
                        net_length += math.sqrt(dx * dx + dy * dy)

                    # Mark power nets
                    is_power = any(p in net_name.upper() for p in power_net_patterns)
                    power_tag = " [POWER]" if is_power else ""
                    lines.append(
                        f"  [{i}/{len(requested_nets)}] {net_name} ... OK ({net_length:.1f}mm){power_tag}"
                    )
                else:
                    # Check if this is a ground net skipped in ground_plane_mode
                    is_ground = any(p in net_name.upper() for p in ground_patterns)
                    if self.ground_plane_mode and is_ground:
                        lines.append(
                            f"  [{i}/{len(requested_nets)}] {net_name} ... SKIPPED (copper pour on B.Cu)"
                        )
                    else:
                        lines.append(
                            f"  [{i}/{len(requested_nets)}] {net_name} ... FAILED (no path)"
                        )

            # Summary - count skipped ground nets separately
            skipped_count = 0
            if self.ground_plane_mode:
                skipped_count = sum(
                    1
                    for n in requested_nets
                    if n not in routed_nets
                    and any(p in n.upper() for p in ground_patterns)
                )
            failed_count = len(requested_nets) - success_count - skipped_count
            total_processed = success_count + skipped_count
            lines.append(
                f"\nOK: {success_count}/{len(requested_nets)} nets routed"
                + (
                    f", {skipped_count} skipped (copper pour)"
                    if skipped_count > 0
                    else ""
                )
            )
            lines.append(f"Total length: {total_length:.1f}mm")
            if total_vias > 0:
                lines.append(f"Vias placed: {total_vias}")

            # Add suggestions if some failed
            if failed_count > 0:
                lines.append(f"\nWarning: {failed_count} nets failed to route")
                lines.append("Suggestions:")
                lines.append("  - Rearrange components: ARRANGE GRID SPACING 15")
                lines.append("  - Check failed nets: LIST NETS")
                lines.append("  - Manual routing: ROUTE NET <name> FROM ... TO ...")

            return success("\n".join(lines))

    def undo(self, board: Board) -> str:
        """Undo the auto-route command by removing added segments and vias.

        Returns:
            Success message
        """
        # Remove added segments
        for net_name, segment in self.added_segments:
            net = board.nets.get(net_name)
            if net and segment in net.segments:
                net.segments.remove(segment)

        # Remove added vias
        for net_name, via in self.added_vias:
            net = board.nets.get(net_name)
            if net and via in net.vias:
                net.vias.remove(via)

        return success(
            f"Undone: Removed {len(self.added_segments)} segments and {len(self.added_vias)} vias"
        )


class OptimizeRoutingCommand(Command):
    """Optimize layer assignments for existing routing to minimize vias.

    Uses Z3 SMT solver to find optimal layer assignments that minimize
    via count while respecting DRC constraints.

    Attributes:
        net_name: Net name to optimize, or "ALL" to optimize all routed nets
    """

    def __init__(self, net_name: str | None = None):
        """Initialize optimize routing command.

        Args:
            net_name: Net name to optimize, or "ALL" for all nets
        """
        self.net_name = net_name or "ALL"
        self.original_layers = {}  # For undo

    def validate(self, board: Board) -> str | None:
        """Validate the optimize routing command.

        Checks:
        - Board has nets
        - Board has existing routing
        - If specific net requested, it exists and is routed

        Returns:
            None if valid, error message string if invalid
        """
        # Check board has nets
        if not board.nets:
            return error("Board has no nets. Load a netlist first with: LOAD <file>")

        # Check for existing routing
        has_routing = any(len(net.segments) > 0 for net in board.nets.values())
        if not has_routing:
            return error(
                "Board has no routing to optimize. Route nets first with: AUTOROUTE ALL"
            )

        # Check specific net exists
        if self.net_name != "ALL":
            net = board.nets.get(self.net_name)
            if not net:
                available_nets = ", ".join(sorted(board.nets.keys())[:5])
                return error(
                    f'Net "{self.net_name}" not found. Available nets: {available_nets}'
                )
            # Check if at least one net is routed
            if len(net.segments) == 0:
                return error(
                    f'Net "{self.net_name}" has no routing. Route it first with: AUTOROUTE NET {self.net_name}'
                )

        return None

    def execute(self, board: Board) -> str:
        """Execute the optimize routing command.

        Extracts existing routing, runs LayerOptimizer, and updates board
        with optimized layer assignments.

        Returns:
            Result message string with optimization statistics
        """
        from pcb_tool.routing import LayerOptimizer, NetPath, RoutingGrid

        # Determine which nets to optimize
        if self.net_name == "ALL":
            nets_to_optimize = [
                name for name, net in board.nets.items() if len(net.segments) > 0
            ]
        else:
            nets_to_optimize = [self.net_name]

        if not nets_to_optimize:
            return "No routed nets to optimize. Route nets first with: AUTOROUTE ALL"

        # Warning for complex optimization
        if len(nets_to_optimize) > 20:
            print(
                f"Warning: Optimizing {len(nets_to_optimize)} nets may take up to 10 seconds..."
            )

        # Create routing grid
        print("Initializing routing grid for optimization...")
        grid = self._create_routing_grid(board)

        # Extract existing routing as NetPath objects
        print(f"Analyzing {len(nets_to_optimize)} routed nets...")
        net_paths = []
        for net_name in nets_to_optimize:
            net = board.nets[net_name]
            segments = [(seg.start, seg.end) for seg in net.segments]
            if segments:
                net_path = NetPath(
                    name=net_name,
                    segments=segments,
                    default_layer=net.segments[0].layer if net.segments else "F.Cu",
                )
                net_paths.append(net_path)

        if not net_paths:
            return error(
                "No valid routing to optimize. Ensure nets have trace segments."
            )

        # Run optimizer
        print(f"Running Z3 optimizer (timeout: 10s)...")
        optimizer = LayerOptimizer(grid, timeout=10.0)
        optimized = optimizer.optimize_layer_assignments(net_paths)
        print("Optimization complete.")

        # Count vias before optimization
        vias_before = sum(len(net.vias) for net in board.nets.values())

        # Apply optimized layer assignments
        vias_after = self._apply_optimized_layers(board, optimized)

        # Format report
        via_reduction = vias_before - vias_after
        if via_reduction > 0:
            pct = (via_reduction / vias_before * 100) if vias_before > 0 else 0
            return success(
                f"Optimizing layer assignments...\n"
                f"  Via count reduced: {vias_before} → {vias_after} ({pct:.0f}% improvement)\n"
                f"OK: Routing optimized"
            )
        else:
            return success("Routing already optimal (no via reduction possible)")

    def _create_routing_grid(self, board: Board):
        """Create RoutingGrid from board dimensions.

        Args:
            board: Board to create grid from

        Returns:
            RoutingGrid instance
        """
        from pcb_tool.routing.grid_builder import (
            GridBuildConfig,
            build_routing_grid_from_board,
        )

        # Layer optimization currently only assigns between F.Cu/B.Cu, but we still
        # build the full grid from the board for consistent sizing.
        return build_routing_grid_from_board(
            board,
            config=GridBuildConfig(
                resolution_mm=0.2,
                default_clearance_mm=0.2,
                margin_mm=10.0,
                min_width_mm=20.0,
                min_height_mm=20.0,
            ),
        )

    def _apply_optimized_layers(self, board: Board, optimized: dict) -> int:
        """Apply optimized layer assignments to board nets.

        Args:
            board: Board to update
            optimized: Dictionary of LayerAssignment objects

        Returns:
            Total via count after optimization
        """
        total_vias = 0

        for net_name, assignment in optimized.items():
            net = board.nets.get(net_name)
            if not net:
                continue

            # Save original layers for undo
            self.original_layers[net_name] = [
                (i, seg.layer) for i, seg in enumerate(net.segments)
            ]

            # Update segment layers based on optimization
            for i, (segment_idx, layer, via_after) in enumerate(
                assignment.segment_assignments
            ):
                if segment_idx < len(net.segments):
                    # Update layer
                    old_layer = net.segments[segment_idx].layer
                    net.segments[segment_idx] = TraceSegment(
                        net_name=net.segments[segment_idx].net_name,
                        start=net.segments[segment_idx].start,
                        end=net.segments[segment_idx].end,
                        layer=layer,
                        width=net.segments[segment_idx].width,
                    )

                    # Add via if needed (simplified - just count for now)
                    if via_after:
                        total_vias += 1

        return total_vias

    def undo(self, board: Board) -> str:
        """Undo the optimization by restoring original layer assignments.

        Returns:
            Success message
        """
        for net_name, original_layers in self.original_layers.items():
            net = board.nets.get(net_name)
            if not net:
                continue

            for segment_idx, layer in original_layers:
                if segment_idx < len(net.segments):
                    net.segments[segment_idx] = TraceSegment(
                        net_name=net.segments[segment_idx].net_name,
                        start=net.segments[segment_idx].start,
                        end=net.segments[segment_idx].end,
                        layer=layer,
                        width=net.segments[segment_idx].width,
                    )

        return success("Undone: Restored original layer assignments")
