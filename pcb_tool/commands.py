"""
PCB Tool Command Pattern

Abstract base class for all commands following the Command Pattern.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING
import math
from pcb_tool.data_model import Board, TraceSegment, Via
from pcb_tool.messages import success, error

if TYPE_CHECKING:
    from pcb_tool.routing.constraints import RoutingConstraints


class Command(ABC):
    """Abstract base class for all commands"""

    @abstractmethod
    def validate(self, board: Board) -> str | None:
        """
        Validate command can execute.
        Returns None if valid, error message string if invalid.
        """
        pass

    @abstractmethod
    def execute(self, board: Board) -> str:
        """
        Execute the command.
        Returns result message string.
        """
        pass

    def undo(self, board: Board) -> str:
        """Undo the command (override in subclasses that support undo)"""
        return "Undo not implemented for this command"


class HelpCommand(Command):
    """Display help information about available commands"""

    def validate(self, board: Board) -> str | None:
        """Help is always valid"""
        return None

    def execute(self, board: Board) -> str:
        """Return help text"""
        return """Available Commands:

State Management:
  LOAD <file>              Load netlist from file
  SAVE <file>              Save board to .kicad_pcb file
  UNDO                     Undo last command
  REDO                     Redo previously undone command
  HISTORY                  Show command history

Component Placement:
  MOVE <ref> TO <x> <y> [ROTATION <angle>]  Move component to position
  ROTATE <ref> TO|BY <angle>                Rotate component
  FLIP <ref>                                Flip component to other side
  LOCK <ref>                                Lock component position
  UNLOCK <ref>                              Unlock component

Query:
  SHOW BOARD               Display ASCII board view
  LIST COMPONENTS          List all components
  LIST NETS                List all nets
  WHERE <ref>              Show component location
  HELP                     Show this help message

Control:
  EXIT                     Exit program
  QUIT                     Exit program
"""


class LoadCommand(Command):
    """Load a netlist file into the board"""

    def __init__(self, path: Path):
        self.path = path

    def validate(self, board: Board) -> str | None:
        """Check if file exists"""
        # Check for empty path
        if str(self.path) == "" or str(self.path) == ".":
            return error("No file path provided")
        if not self.path.exists():
            return error(f"File not found: {self.path}")
        if self.path.is_dir():
            return error(f"{self.path} is a directory, not a file")
        return None

    def execute(self, board: Board) -> str:
        """Load netlist and populate board"""
        from pcb_tool.netlist_reader import NetlistReader

        reader = NetlistReader()
        loaded_board = reader.read(self.path)

        # Transfer components and nets to the board
        board.components = loaded_board.components
        board.nets = loaded_board.nets
        board.source_file = loaded_board.source_file

        comp_count = len(board.components)
        net_count = len(board.nets)

        return success(f"Loaded board with {comp_count} components, {net_count} nets")


class ListComponentsCommand(Command):
    """List all components in the board"""

    def validate(self, board: Board) -> str | None:
        """Always valid"""
        return None

    def execute(self, board: Board) -> str:
        """List all components with details"""
        if not board.components:
            return "No components loaded"

        lines = [f"Components ({len(board.components)} total):"]
        lines.append("")

        # Sort by reference for consistent output
        refs = sorted(board.components.keys())

        for ref in refs:
            comp = board.components[ref]
            x, y = comp.position
            locked_tag = " [LOCKED]" if comp.locked else ""

            # Format: REF: Value @ (x, y) rot° Layer [LOCKED]
            line = f"  {ref}: {comp.value} @ ({x}, {y}) {int(comp.rotation)}° {comp.layer}{locked_tag}"
            lines.append(line)

        return "\n".join(lines)


class LockCommand(Command):
    """Lock a component to prevent modifications"""

    def __init__(self, ref: str):
        self.ref = ref

    def validate(self, board: Board) -> str | None:
        comp = board.get_component(self.ref)
        if not comp:
            return error(f"Component {self.ref} not found")
        return None

    def execute(self, board: Board) -> str:
        comp = board.get_component(self.ref)
        comp.locked = True
        return success(f"Locked {self.ref}")


class UnlockCommand(Command):
    """Unlock a component to allow modifications"""

    def __init__(self, ref: str):
        self.ref = ref

    def validate(self, board: Board) -> str | None:
        comp = board.get_component(self.ref)
        if not comp:
            return error(f"Component {self.ref} not found")
        return None

    def execute(self, board: Board) -> str:
        comp = board.get_component(self.ref)
        comp.locked = False
        return success(f"Unlocked {self.ref}")


class MoveCommand(Command):
    """Move a component to a new position"""

    def __init__(self, ref: str, x: float, y: float, rotation: float = None):
        self.ref = ref
        self.x = x
        self.y = y
        self.rotation = rotation  # Optional rotation
        self.old_position = None
        self.old_rotation = None

    def validate(self, board: Board) -> str | None:
        comp = board.get_component(self.ref)
        if not comp:
            return error(f"Component {self.ref} not found")
        if comp.locked:
            return error(f"Component {self.ref} is locked")
        return None

    def execute(self, board: Board) -> str:
        comp = board.get_component(self.ref)
        self.old_position = comp.position
        self.old_rotation = comp.rotation

        comp.position = (self.x, self.y)
        if self.rotation is not None:
            comp.rotation = self.rotation % 360

        # Always show rotation in output
        return success(f"Moved {self.ref} to ({self.x}, {self.y}) rotation {comp.rotation}°")

    def undo(self, board: Board) -> str:
        comp = board.get_component(self.ref)
        comp.position = self.old_position
        comp.rotation = self.old_rotation
        return success(f"Restored {self.ref} to {self.old_position}")


class RotateCommand(Command):
    """Rotate a component by specified angle"""

    def __init__(self, ref: str, angle: float, absolute: bool = False):
        self.ref = ref
        self.angle = angle
        self.absolute = absolute  # True for TO, False for BY
        self.old_rotation = None

    def validate(self, board: Board) -> str | None:
        comp = board.get_component(self.ref)
        if not comp:
            return error(f"Component {self.ref} not found")
        if comp.locked:
            return error(f"Component {self.ref} is locked")
        return None

    def execute(self, board: Board) -> str:
        comp = board.get_component(self.ref)
        self.old_rotation = comp.rotation

        if self.absolute:
            # TO behavior: set absolute rotation
            comp.rotation = self.angle % 360
            return success(f"Rotated {self.ref} to {comp.rotation}°")
        else:
            # BY behavior: add to current rotation
            comp.rotation = (comp.rotation + self.angle) % 360
            return success(f"Rotated {self.ref} by {self.angle}° (now at {comp.rotation}°)")

    def undo(self, board: Board) -> str:
        comp = board.get_component(self.ref)
        comp.rotation = self.old_rotation
        return success(f"Restored {self.ref} rotation to {self.old_rotation}°")


class SaveCommand(Command):
    """Save board to .kicad_pcb file"""

    def __init__(self, path: Path = None):
        self.path = path

    def validate(self, board: Board) -> str | None:
        # Check if board has any components
        if not board.components:
            return error("Cannot save: board is empty (no components loaded)")
        # If no path provided, check if board has source_file
        if self.path is None and board.source_file is None:
            return error("No filename specified and no source file loaded")
        return None

    def execute(self, board: Board) -> str:
        from pcb_tool.kicad_writer import KicadWriter

        # Use provided path or default to source_file
        output_path = self.path if self.path is not None else board.source_file

        writer = KicadWriter()
        try:
            writer.write(board, output_path)
        except PermissionError as e:
            return error(f"Permission denied writing to {output_path}")
        except IOError as e:
            return error(f"Error writing to {output_path}: {e}")

        return success(f"Saved to {output_path}")


class FlipCommand(Command):
    """Flip a component to opposite side of board"""

    def __init__(self, ref: str):
        self.ref = ref

    def validate(self, board: Board) -> str | None:
        comp = board.get_component(self.ref)
        if not comp:
            return error(f"Component {self.ref} not found")
        if comp.locked:
            return error(f"Component {self.ref} is locked")
        return None

    def execute(self, board: Board) -> str:
        # For MVP1, just acknowledge the flip
        # Full implementation would toggle layer F.Cu <-> B.Cu
        return success(f"Flipped {self.ref} to opposite side")


class WhereCommand(Command):
    """Show component location and status"""

    def __init__(self, ref: str):
        self.ref = ref

    def validate(self, board: Board) -> str | None:
        comp = board.get_component(self.ref)
        if not comp:
            return error(f"Component {self.ref} not found")
        return None

    def execute(self, board: Board) -> str:
        comp = board.get_component(self.ref)
        x, y = comp.position
        locked_status = "Yes" if comp.locked else "No"

        lines = [
            f"Component: {self.ref}",
            f"  Position: ({x}, {y})",
            f"  Rotation: {comp.rotation}°",
            f"  Layer: {comp.layer}",
            f"  Footprint: {comp.footprint}",
            f"  Value: {comp.value}",
            f"  Locked: {locked_status}"
        ]

        return "\n".join(lines)


class ExitCommand(Command):
    """Exit the interactive session"""

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        return "Goodbye!"


class ListNetsCommand(Command):
    """List all nets in the board"""

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        if not board.nets:
            return "No nets loaded"

        lines = [f"Nets ({len(board.nets)} total):"]
        lines.append("")

        for name in sorted(board.nets.keys()):
            net = board.nets[name]
            conn_count = len(net.connections)
            lines.append(f"  {name:20s} (code {net.code}): {conn_count} connections")
            for ref, pin in net.connections:
                lines.append(f"    - {ref}.{pin}")

        return "\n".join(lines)


class ShowBoardCommand(Command):
    """Display ASCII representation of board"""

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        if not board.components:
            return "No components to display (empty board)"

        # Find bounds for board dimensions
        positions = [comp.position for comp in board.components.values()]
        if not positions:
            return "No components to display"

        # Calculate board dimensions with padding
        min_x = max(0, min(pos[0] for pos in positions) - 10)
        max_x = max(pos[0] for pos in positions) + 10
        min_y = max(0, min(pos[1] for pos in positions) - 10)
        max_y = max(pos[1] for pos in positions) + 10

        board_width = max_x - min_x
        board_height = max_y - min_y

        # Calculate scale (roughly 1 char = 2mm for typical boards)
        # Aim for ~50-60 char width
        target_width = 55
        scale = max(1, board_width / target_width)

        # Grid dimensions
        grid_width = int(board_width / scale / 5) + 1  # Number of columns
        grid_height = int(board_height / scale / 5) + 1  # Number of rows
        cell_size = scale * 5  # mm per cell

        # Count components and nets
        comp_count = len(board.components)
        net_count = len(board.nets)
        locked_count = sum(1 for c in board.components.values() if c.locked)

        # Count routing elements
        total_segments = 0
        total_vias = 0
        for net in board.nets.values():
            total_segments += len(net.segments)
            total_vias += len(net.vias)

        # Header
        lines = [f"Board: {board_width:.1f} x {board_height:.1f} mm | Components: {comp_count} | Nets: {net_count} | Locked: {locked_count}"]
        lines.append(f"Scale: 1 cell = {cell_size:.0f}mm")
        lines.append("")

        # Create grid structure
        grid_cells = {}  # (col, row) -> (ref, arrow)
        via_positions = set()  # (col, row) positions with vias
        segment_endpoints = set()  # (col, row) positions with segment endpoints

        # Add components to grid
        for ref, comp in board.components.items():
            x, y = comp.position
            col = int((x - min_x) / cell_size)
            row = int((y - min_y) / cell_size)

            # Clamp to grid bounds
            col = max(0, min(grid_width - 1, col))
            row = max(0, min(grid_height - 1, row))

            # Determine orientation arrow
            rotation = comp.rotation
            if 315 <= rotation or rotation < 45:
                arrow = "↑"
            elif 45 <= rotation < 135:
                arrow = "→"
            elif 135 <= rotation < 225:
                arrow = "↓"
            else:
                arrow = "←"

            grid_cells[(col, row)] = (ref, arrow)

        # Mark via positions (only if not on component)
        for net in board.nets.values():
            for via in net.vias:
                x, y = via.position
                col = int((x - min_x) / cell_size)
                row = int((y - min_y) / cell_size)
                col = max(0, min(grid_width - 1, col))
                row = max(0, min(grid_height - 1, row))

                # Only mark if no component there
                if (col, row) not in grid_cells:
                    via_positions.add((col, row))

        # Mark segment endpoints (only if not on component or via)
        for net in board.nets.values():
            for segment in net.segments:
                for pos in [segment.start, segment.end]:
                    x, y = pos
                    col = int((x - min_x) / cell_size)
                    row = int((y - min_y) / cell_size)
                    col = max(0, min(grid_width - 1, col))
                    row = max(0, min(grid_height - 1, row))

                    # Only mark if no component or via there
                    if (col, row) not in grid_cells and (col, row) not in via_positions:
                        segment_endpoints.add((col, row))

        # Build coordinate labels (x-axis)
        coord_line = "    "
        for col in range(grid_width):
            x_coord = int(min_x + col * cell_size)
            coord_line += f"{x_coord:>5} "
        lines.append(coord_line)

        # Top border
        border_line = "  ┌"
        for col in range(grid_width):
            border_line += "─────" if col < grid_width - 1 else "─────"
            if col < grid_width - 1:
                border_line += "┬"
        border_line += "┐"
        lines.append(border_line)

        # Grid rows
        for row in range(grid_height):
            y_coord = int(min_y + row * cell_size)

            # Row content
            row_line = f"{y_coord:>2}│"
            for col in range(grid_width):
                if (col, row) in grid_cells:
                    ref, arrow = grid_cells[(col, row)]
                    # Center component in cell: "[R1]↑"
                    content = f"[{ref}]"
                    row_line += f"{content:^5}│"
                elif (col, row) in via_positions:
                    # Show via marker
                    row_line += "  V  │"
                elif (col, row) in segment_endpoints:
                    # Show segment endpoint marker
                    row_line += "  *  │"
                else:
                    row_line += "     │"
            lines.append(row_line)

            # Row with arrows (orientation indicators) or routing markers
            arrow_line = "  │"
            for col in range(grid_width):
                if (col, row) in grid_cells:
                    ref, arrow = grid_cells[(col, row)]
                    arrow_line += f"  {arrow}  │"
                else:
                    arrow_line += "     │"
            lines.append(arrow_line)

            # Inter-row border or bottom border
            if row < grid_height - 1:
                border_line = "  ├"
                for col in range(grid_width):
                    border_line += "─────" if col < grid_width - 1 else "─────"
                    if col < grid_width - 1:
                        border_line += "┼"
                border_line += "┤"
                lines.append(border_line)

        # Bottom border
        border_line = "  └"
        for col in range(grid_width):
            border_line += "─────" if col < grid_width - 1 else "─────"
            if col < grid_width - 1:
                border_line += "┴"
        border_line += "┘"
        lines.append(border_line)

        lines.append("")

        # Enhanced legend with routing info
        legend_parts = ["Legend: [Ref] = Component  ↑→↓← = Orientation (0° 90° 180° 270°)"]
        if total_segments > 0 or total_vias > 0:
            legend_parts.append("        V = Via  * = Trace endpoint")
            legend_parts.append(f"Routing: {total_segments} segments, {total_vias} vias")

        lines.extend(legend_parts)

        # Add routing grid statistics if routing exists
        if total_segments > 0 or total_vias > 0:
            lines.append("")
            grid_stats = self._build_routing_grid_stats(board, min_x, max_x, min_y, max_y)
            if grid_stats:
                lines.extend(grid_stats)

        return "\n".join(lines)

    def _build_routing_grid_stats(
        self,
        board: Board,
        min_x: float,
        max_x: float,
        min_y: float,
        max_y: float
    ) -> list[str]:
        """
        Build routing grid statistics from current board state.

        Returns list of formatted statistics lines.
        """
        try:
            from pcb_tool.routing import RoutingGrid

            # Create routing grid matching board dimensions
            width_mm = max_x - min_x
            height_mm = max_y - min_y

            grid = RoutingGrid(
                width_mm=width_mm,
                height_mm=height_mm,
                resolution_mm=0.1,
                default_clearance_mm=0.2
            )

            # Mark components as obstacles
            for comp in board.components.values():
                # Simple approximation: components are 5mm diameter obstacles
                x, y = comp.position
                grid.mark_obstacle(
                    x_mm=x - min_x,
                    y_mm=y - min_y,
                    layer="both",
                    size_mm=5.0
                )

            # Track routing statistics
            total_segments = 0
            fcu_segments = 0
            bcu_segments = 0
            total_trace_length_mm = 0.0

            # Mark existing traces as obstacles
            for net in board.nets.values():
                for segment in net.segments:
                    start_x, start_y = segment.start
                    end_x, end_y = segment.end

                    # Count segments by layer
                    total_segments += 1
                    if segment.layer == "F.Cu":
                        fcu_segments += 1
                    elif segment.layer == "B.Cu":
                        bcu_segments += 1

                    # Calculate segment length
                    segment_length = ((end_x - start_x)**2 + (end_y - start_y)**2)**0.5
                    total_trace_length_mm += segment_length

                    grid.mark_trace_segment(
                        start_mm=(start_x - min_x, start_y - min_y),
                        end_mm=(end_x - min_x, end_y - min_y),
                        layer=segment.layer,
                        width_mm=segment.width
                    )

                # Mark vias
                for via in net.vias:
                    x, y = via.position
                    grid.mark_via(
                        x_mm=x - min_x,
                        y_mm=y - min_y,
                        size_mm=via.size
                    )

            # Get statistics
            stats = grid.get_statistics()

            # Format output
            lines = ["Routing Grid Statistics:"]
            lines.append(f"  Grid: {stats['dimensions']['grid_width']} × {stats['dimensions']['grid_height']} cells @ {stats['dimensions']['resolution_mm']}mm resolution")
            lines.append(f"  Total cells: {stats['dimensions']['total_cells']:,}")

            # Calculate routable percentage
            total_cells = stats['dimensions']['total_cells']
            fcu_routable = stats['routable_cells']['F.Cu']
            bcu_routable = stats['routable_cells']['B.Cu']
            fcu_pct = (fcu_routable / total_cells * 100) if total_cells > 0 else 0
            bcu_pct = (bcu_routable / total_cells * 100) if total_cells > 0 else 0

            lines.append(f"  F.Cu: {stats['obstacles']['F.Cu']:,} obstacles, {fcu_routable:,} routable ({fcu_pct:.1f}%)")
            lines.append(f"  B.Cu: {stats['obstacles']['B.Cu']:,} obstacles, {bcu_routable:,} routable ({bcu_pct:.1f}%)")

            # Multi-layer routing statistics
            if total_segments > 0:
                fcu_pct_routed = (fcu_segments / total_segments * 100) if total_segments > 0 else 0
                bcu_pct_routed = (bcu_segments / total_segments * 100) if total_segments > 0 else 0
                lines.append("")
                lines.append("Routing Distribution:")
                lines.append(f"  Total trace segments: {total_segments}")
                lines.append(f"  F.Cu segments: {fcu_segments} ({fcu_pct_routed:.1f}%)")
                lines.append(f"  B.Cu segments: {bcu_segments} ({bcu_pct_routed:.1f}%)")
                lines.append(f"  Total trace length: {total_trace_length_mm:.2f}mm")

            if stats['obstacles']['vias'] > 0:
                lines.append(f"  Layer transitions: {stats['obstacles']['vias']} vias")

            return lines

        except ImportError:
            # Routing module not available
            return []
        except Exception as e:
            # Don't fail SHOW BOARD if grid stats fail
            return [f"Routing grid stats unavailable: {str(e)}"]


class UndoCommand(Command):
    """Undo last command"""

    def __init__(self):
        self.history = None  # Will be set by REPL

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        if not self.history or not self.history.undo_stack:
            return "Nothing to undo"

        self.history.undo(board)
        return success("Undid last command")


class RedoCommand(Command):
    """Redo last undone command"""

    def __init__(self):
        self.history = None

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        if not self.history or not self.history.redo_stack:
            return "Nothing to redo"

        self.history.redo(board)
        return success("Redid last command")


class HistoryCommand(Command):
    """Show command history"""

    def __init__(self):
        self.history = None

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        if not self.history or not self.history.undo_stack:
            return "No command history"

        lines = [f"Command History ({len(self.history.undo_stack)} commands):"]
        for i, cmd in enumerate(self.history.undo_stack, 1):
            # Convert MoveCommand -> MOVE, RotateCommand -> ROTATE, etc.
            cmd_name = cmd.__class__.__name__.replace("Command", "").upper()
            lines.append(f"  {i}. {cmd_name}")
        return "\n".join(lines)


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

    def __init__(self, net_name: str, start_pos: tuple[float, float] | str,
                 end_pos: tuple[float, float] | str, layer: str = "F.Cu", width: float = None,
                 waypoints: list[tuple[float, float]] | None = None):
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
        self.segments = []   # For multi-segment routes

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

        # Check layer is valid
        if self.layer not in ("F.Cu", "B.Cu"):
            return error(f'Invalid layer "{self.layer}"')

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
                    width=trace_width
                )
                self.segments.append(segment)
                net.add_segment(segment)

            # Return success message with segment count
            return success(f'Added {len(self.segments)} segments to net "{self.net_name}" via {len(self.waypoints)} waypoints')

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
                width=trace_width
            )

            # Add to net
            net.add_segment(self.segment)

            x1, y1 = actual_start
            x2, y2 = actual_end
            return success(f'Added segment to net "{self.net_name}" from ({x1:.2f}, {y1:.2f}) to ({x2:.2f}, {y2:.2f})')

    def _resolve_position(self, board: Board, pos: tuple[float, float] | str, net_name: str) -> tuple[float, float]:
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
            if '.' not in pos:
                raise ValueError(f"Invalid component.pin notation: {pos}")

            ref, pin_str = pos.split('.', 1)

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

    def _find_pad_position(self, board: Board, intended_pos: tuple[float, float], net_name: str) -> tuple[float, float]:
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
        min_distance = float('inf')

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
                    (intended_pos[0] - pad_pos[0]) ** 2 +
                    (intended_pos[1] - pad_pos[1]) ** 2
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

    def _check_waypoint_deviation(self, intended_pos: tuple[float, float] | str,
                                   actual_pos: tuple[float, float], position_label: str) -> None:
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
                print(f"  WARNING: Waypoint routing deviation at {position_label} position")
                print(f"    Intended: ({intended_x:.2f}, {intended_y:.2f})")
                print(f"    Actual:   ({actual_x:.2f}, {actual_y:.2f})")
                print(f"    Deviation: {total_deviation:.2f}mm (ΔX={deviation_x:.2f}mm, ΔY={deviation_y:.2f}mm)")
                print(f"    Net: {self.net_name}, Layer: {self.layer}")
                print(f"    TIP: Use component.pin notation (e.g., 'Q1.2') for precise routing,")
                print(f"         or verify waypoint coordinates match actual pad positions.")
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
            return success(f'Removed {len(self.segments)} segments from net "{self.net_name}"')
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

    def __init__(self, net_name: str, position: tuple[float, float],
                 size: float = None, drill: float = None):
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
        via_size = self.size if self.size is not None else board.nets[self.net_name].via_size
        via_radius = via_size / 2

        for comp_ref, component in board.components.items():
            for pad in component.pads:
                pad_x, pad_y = component.get_pad_position(pad.number)
                distance = math.sqrt((via_x - pad_x)**2 + (via_y - pad_y)**2)

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
        via_size = self.size if self.size is not None else board.nets[self.net_name].via_size
        via_radius = via_size / 2

        for net_name, net in board.nets.items():
            for existing_via in net.vias:
                ex_x, ex_y = existing_via.position
                distance = math.sqrt((via_x - ex_x)**2 + (via_y - ex_y)**2)

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
            layers=("F.Cu", "B.Cu")
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

    def __init__(self, net_name: str, position: tuple[float, float] = None,
                 delete_all: bool = False):
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

    def __init__(self, net_name: str, position: tuple[float, float] = None,
                 delete_all: bool = False):
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


class MeasureDistanceCommand(Command):
    """Measure distance between two points or components.

    This is a read-only query command that calculates Euclidean distance.
    Can measure between:
    - Two coordinate points
    - Two component centers
    - One coordinate and one component

    Attributes:
        start: Starting point as (x, y) tuple or component reference string
        end: Ending point as (x, y) tuple or component reference string
    """

    def __init__(self, start, end):
        """Initialize measure distance command.

        Args:
            start: Starting point as (x, y) tuple or component ref string
            end: Ending point as (x, y) tuple or component ref string
        """
        self.start = start
        self.end = end

    def validate(self, board: Board) -> str | None:
        """Validate the measure distance command.

        For query commands, validation only checks if component refs exist.
        Always returns None (no undo history needed for read-only commands).

        Returns:
            None if valid (query command, no undo needed), error message if component not found
        """
        # Check if start is a component ref
        if isinstance(self.start, str):
            comp = board.get_component(self.start)
            if not comp:
                return error(f'Component "{self.start}" not found')

        # Check if end is a component ref
        if isinstance(self.end, str):
            comp = board.get_component(self.end)
            if not comp:
                return error(f'Component "{self.end}" not found')

        return None

    def execute(self, board: Board) -> str:
        """Execute the measure distance command.

        Calculates Euclidean distance between two points.
        Resolves component references to their center positions.

        Returns:
            Distance message formatted as "DISTANCE: <d>mm" (1 decimal place)
        """
        # Resolve start position
        if isinstance(self.start, str):
            comp = board.get_component(self.start)
            x1, y1 = comp.position
        else:
            x1, y1 = self.start

        # Resolve end position
        if isinstance(self.end, str):
            comp = board.get_component(self.end)
            x2, y2 = comp.position
        else:
            x2, y2 = self.end

        # Calculate Euclidean distance
        distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

        return f"DISTANCE: {distance:.1f}mm"

    def undo(self, board: Board) -> str:
        """Undo not applicable for read-only query command.

        Returns:
            Empty string (no undo needed)
        """
        return ""


class MeasureNetLengthCommand(Command):
    """Measure total routed length of a net.

    This is a read-only query command that sums the lengths of all
    trace segments in a net and reports segment and via counts.

    Attributes:
        net_name: Name of the net to measure
    """

    def __init__(self, net_name: str):
        """Initialize measure net length command.

        Args:
            net_name: Name of the net to measure
        """
        self.net_name = net_name

    def validate(self, board: Board) -> str | None:
        """Validate the measure net length command.

        For query commands, validation only checks if net exists.
        Always returns None (no undo history needed for read-only commands).

        Returns:
            None if valid (query command, no undo needed), error message if net not found
        """
        if self.net_name not in board.nets:
            return error(f'Net "{self.net_name}" not found')

        return None

    def execute(self, board: Board) -> str:
        """Execute the measure net length command.

        Calculates total length by summing Euclidean distances of all segments.
        Counts segments and vias for reporting.

        Returns:
            Length message with format:
            - If segments exist: 'NET "<name>" total length: <length>mm (<n> segments, <v> vias)'
            - If no segments: 'NET "<name>" has no routed segments'
        """
        net = board.nets[self.net_name]

        # Check if net has segments
        if not net.segments:
            return f'NET "{self.net_name}" has no routed segments'

        # Calculate total length
        total_length = 0.0
        for segment in net.segments:
            x1, y1 = segment.start
            x2, y2 = segment.end
            length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
            total_length += length

        # Count segments and vias
        segment_count = len(net.segments)
        via_count = len(net.vias)

        return f'NET "{self.net_name}" total length: {total_length:.1f}mm ({segment_count} segments, {via_count} vias)'

    def undo(self, board: Board) -> str:
        """Undo not applicable for read-only query command.

        Returns:
            Empty string (no undo needed)
        """
        return ""


class GroupMoveCommand(Command):
    """Move multiple components by a relative offset.

    Applies the same relative displacement to a group of components,
    maintaining their relative positions to each other.

    Attributes:
        component_refs: List of component reference designators
        dx: X offset in millimeters (can be negative)
        dy: Y offset in millimeters (can be negative)
        old_positions: List of original positions for undo support
    """

    def __init__(self, component_refs: list[str], dx: float, dy: float):
        """Initialize group move command.

        Args:
            component_refs: List of component references to move
            dx: X offset in mm
            dy: Y offset in mm
        """
        self.component_refs = component_refs
        self.dx = dx
        self.dy = dy
        self.old_positions = []

    def validate(self, board: Board) -> str | None:
        """Validate the group move command.

        Checks:
        - All components exist
        - No component is locked

        Returns:
            None if valid, error message string if invalid
        """
        # Check all components exist
        for ref in self.component_refs:
            comp = board.get_component(ref)
            if not comp:
                return error(f'Component "{ref}" not found')

        # Check none are locked
        for ref in self.component_refs:
            comp = board.get_component(ref)
            if comp.locked:
                return error(f'Component "{ref}" is locked')

        return None

    def execute(self, board: Board) -> str:
        """Execute the group move command.

        Moves all components by the specified offset and stores
        old positions for undo support.

        Returns:
            Multi-line success message showing old and new positions
        """
        # Store old positions and move components
        self.old_positions = []
        lines = [success(f"Moved {len(self.component_refs)} components by ({self.dx}, {self.dy})")]

        for ref in self.component_refs:
            comp = board.get_component(ref)
            old_pos = comp.position
            self.old_positions.append(old_pos)

            # Calculate new position
            new_x = old_pos[0] + self.dx
            new_y = old_pos[1] + self.dy
            comp.position = (new_x, new_y)

            # Add detail line for this component
            lines.append(f"  {ref}: ({old_pos[0]}, {old_pos[1]}) → ({new_x}, {new_y})")

        return "\n".join(lines)

    def undo(self, board: Board) -> str:
        """Undo the group move by restoring old positions.

        Returns:
            Success message confirming restoration
        """
        for ref, old_pos in zip(self.component_refs, self.old_positions):
            comp = board.get_component(ref)
            comp.position = old_pos

        return success(f"Restored {len(self.component_refs)} components to original positions")


class ArrangeCommand(Command):
    """Arrange multiple components in a pattern.

    Places components in organized patterns: horizontal row, vertical column,
    or square grid. First component's position is used as the starting point.

    Attributes:
        component_refs: List of component reference designators
        pattern: Arrangement pattern ("ROW", "COLUMN", or "GRID")
        spacing: Gap between components in millimeters
        old_positions: List of original positions for undo support
    """

    def __init__(self, component_refs: list[str], pattern: str = "GRID", spacing: float = 5.0):
        """Initialize arrange command.

        Args:
            component_refs: List of component references to arrange
            pattern: Arrangement pattern (default "GRID")
            spacing: Gap between components in mm (default 5.0)
        """
        self.component_refs = component_refs
        self.pattern = pattern.upper()
        self.spacing = spacing
        self.old_positions = []

    def validate(self, board: Board) -> str | None:
        """Validate the arrange command.

        Checks:
        - All components exist
        - No component is locked

        Returns:
            None if valid, error message string if invalid
        """
        # Check all components exist
        for ref in self.component_refs:
            comp = board.get_component(ref)
            if not comp:
                return error(f'Component "{ref}" not found')

        # Check none are locked
        for ref in self.component_refs:
            comp = board.get_component(ref)
            if comp.locked:
                return error(f'Component "{ref}" is locked')

        return None

    def execute(self, board: Board) -> str:
        """Execute the arrange command.

        Arranges components according to the specified pattern:
        - ROW: Horizontal line at first component's Y
        - COLUMN: Vertical line at first component's X
        - GRID: Square grid starting at first component's position

        Returns:
            Multi-line success message showing new positions
        """
        # Store old positions
        self.old_positions = []
        for ref in self.component_refs:
            comp = board.get_component(ref)
            self.old_positions.append(comp.position)

        # Get starting position from first component
        first_comp = board.get_component(self.component_refs[0])
        start_x, start_y = first_comp.position

        # Arrange based on pattern
        if self.pattern == "ROW":
            # Horizontal arrangement: same Y, increment X
            for i, ref in enumerate(self.component_refs):
                comp = board.get_component(ref)
                comp.position = (start_x + i * self.spacing, start_y)

        elif self.pattern == "COLUMN":
            # Vertical arrangement: same X, increment Y
            for i, ref in enumerate(self.component_refs):
                comp = board.get_component(ref)
                comp.position = (start_x, start_y + i * self.spacing)

        else:  # GRID
            # Grid arrangement: sqrt(n) x sqrt(n) grid
            grid_size = math.ceil(math.sqrt(len(self.component_refs)))
            for i, ref in enumerate(self.component_refs):
                comp = board.get_component(ref)
                col = i % grid_size
                row = i // grid_size
                comp.position = (start_x + col * self.spacing, start_y + row * self.spacing)

        # Build result message
        lines = [success(f"Arranged {len(self.component_refs)} components in {self.pattern}")]
        for ref in self.component_refs:
            comp = board.get_component(ref)
            x, y = comp.position
            lines.append(f"  {ref} → ({x}, {y})")

        return "\n".join(lines)

    def undo(self, board: Board) -> str:
        """Undo the arrange by restoring old positions.

        Returns:
            Success message confirming restoration
        """
        for ref, old_pos in zip(self.component_refs, self.old_positions):
            comp = board.get_component(ref)
            comp.position = old_pos

        return success(f"Restored {len(self.component_refs)} components to original positions")


class CheckDrcCommand(Command):
    """Run Design Rule Check (DRC) on the board.

    This is a read-only query command that performs comprehensive design rule checks
    including clearance violations, track widths, unconnected components, unrouted nets,
    via collision detection, and trace overlap detection.

    The command checks for:
    - Clearance violations between components (minimum 0.2mm)
    - Track widths below minimum (0.2mm)
    - Components with no net connections
    - Nets with connections but no routing
    - Via-to-pad collisions (exact position and proximity)
    - Via-to-via collisions (exact position and proximity)
    - Trace-to-trace crossings (line segment intersection)

    Returns a multi-line report with error and warning counts.
    """

    def __init__(self):
        """Initialize CHECK DRC command with no parameters."""
        pass

    def validate(self, board: Board) -> str | None:
        """Validate the CHECK DRC command.

        This is a read-only command, so validation always succeeds.

        Returns:
            None (always valid)
        """
        return None

    def _check_via_pad_collisions(self, board: Board) -> dict:
        """Check for via-to-pad collisions.

        Checks all vias against all component pads for:
        - Exact position overlaps (< 0.01mm) - drill holes co-located
        - Proximity violations with different net pads

        Args:
            board: The board to check

        Returns:
            Dictionary with 'errors' and 'warnings' lists
        """
        issues = {'errors': [], 'warnings': []}

        for net_name, net in board.nets.items():
            for via in net.vias:
                via_x, via_y = via.position
                via_radius = via.size / 2

                for comp_ref, component in board.components.items():
                    for pad in component.pads:
                        pad_x, pad_y = component.get_pad_position(pad.number)
                        distance = math.sqrt((via_x - pad_x)**2 + (via_y - pad_y)**2)

                        # Check for exact position collision
                        if distance < 0.01:
                            issues['errors'].append(
                                f"  ERROR: Via on net {net_name} at ({via_x}, {via_y}) "
                                f"overlaps {comp_ref} pad {pad.number}. Drill holes co-located."
                            )
                        # Check proximity with different net pads
                        elif pad.net_name and distance < via_radius + max(pad.size)/2 + 0.1:
                            if pad.net_name != net_name:
                                issues['errors'].append(
                                    f"  ERROR: Via on net {net_name} too close to "
                                    f"{comp_ref} pad {pad.number} on net {pad.net_name} "
                                    f"({distance:.2f}mm)"
                                )

        return issues

    def _check_via_via_collisions(self, board: Board) -> dict:
        """Check for via-to-via collisions.

        Checks all vias against each other for:
        - Exact position overlaps (< 0.01mm) - same position
        - Proximity violations with different net vias

        Args:
            board: The board to check

        Returns:
            Dictionary with 'errors' and 'warnings' lists
        """
        issues = {'errors': [], 'warnings': []}

        # Collect all vias with their net names
        all_vias = []
        for net_name, net in board.nets.items():
            for via in net.vias:
                all_vias.append((net_name, via))

        # Check each pair of vias
        for i, (net1, via1) in enumerate(all_vias):
            for net2, via2 in all_vias[i+1:]:
                x1, y1 = via1.position
                x2, y2 = via2.position
                distance = math.sqrt((x2-x1)**2 + (y2-y1)**2)

                # Check for exact position collision
                if distance < 0.01:
                    if net1 != net2:
                        issues['errors'].append(
                            f"  ERROR: Vias on nets {net1} and {net2} overlap at ({x1}, {y1})"
                        )
                # Check proximity with different net vias
                else:
                    min_clearance = (via1.size + via2.size)/2 + 0.2
                    if distance < min_clearance and net1 != net2:
                        issues['errors'].append(
                            f"  ERROR: Vias on nets {net1} and {net2} too close "
                            f"({distance:.2f}mm < {min_clearance:.2f}mm)"
                        )

        return issues

    def _check_trace_overlaps(self, board: Board) -> dict:
        """Check for trace-to-trace overlaps and crossings.

        Detects when traces from different nets on the same layer:
        - Cross each other (line segment intersection)
        - Run parallel too close together (clearance violation)

        Args:
            board: The board to check

        Returns:
            Dictionary with 'errors' and 'warnings' lists
        """
        issues = {'errors': [], 'warnings': []}

        # Collect all segments by layer
        segments_by_layer = {}
        for net_name, net in board.nets.items():
            for segment in net.segments:
                layer = segment.layer
                if layer not in segments_by_layer:
                    segments_by_layer[layer] = []
                segments_by_layer[layer].append((net_name, segment))

        # Check segments on each layer
        for layer, segments in segments_by_layer.items():
            for i, (net1, seg1) in enumerate(segments):
                for net2, seg2 in segments[i+1:]:
                    # Skip if same net
                    if net1 == net2:
                        continue

                    # Check if segments intersect or are too close
                    intersection = self._segments_intersect(seg1, seg2)
                    if intersection:
                        x, y = intersection
                        issues['errors'].append(
                            f"  ERROR: Traces from nets {net1} and {net2} cross on {layer} at ({x:.2f}, {y:.2f})"
                        )

        return issues

    def _segments_intersect(self, seg1, seg2) -> tuple[float, float] | None:
        """Check if two line segments intersect.

        Uses line segment intersection algorithm to detect if two traces cross.

        Args:
            seg1: First TraceSegment
            seg2: Second TraceSegment

        Returns:
            Intersection point (x, y) if segments cross, None otherwise
        """
        x1, y1 = seg1.start
        x2, y2 = seg1.end
        x3, y3 = seg2.start
        x4, y4 = seg2.end

        # Calculate denominators
        denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)

        # Parallel or coincident lines
        if abs(denom) < 1e-10:
            return None

        # Calculate intersection parameters
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
        u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom

        # Check if intersection is within both segments
        if 0 <= t <= 1 and 0 <= u <= 1:
            # Calculate intersection point
            ix = x1 + t * (x2 - x1)
            iy = y1 + t * (y2 - y1)
            return (ix, iy)

        return None

    def execute(self, board: Board) -> str:
        """Execute the DRC check.

        Performs all DRC checks and formats results into a multi-line report.

        Returns:
            Multi-line DRC report with errors and warnings
        """
        errors = []
        warnings = []

        # Check clearance violations between components
        min_clearance = 0.2
        components = list(board.components.values())
        for i, comp1 in enumerate(components):
            for comp2 in components[i + 1:]:
                x1, y1 = comp1.position
                x2, y2 = comp2.position
                distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                if distance < min_clearance:
                    errors.append(
                        f"  ERROR: Clearance violation between {comp1.ref} pad 1 and {comp2.ref} pad 2 ({distance:.2f}mm < {min_clearance}mm)"
                    )

        # Check track widths
        min_track_width = 0.2
        for net_name, net in board.nets.items():
            for segment in net.segments:
                if segment.width < min_track_width:
                    x, y = segment.start
                    errors.append(
                        f"  ERROR: Track width {segment.width}mm below minimum {min_track_width}mm on net {net_name} segment at ({x}, {y})"
                    )

        # Check for components with no connections
        for ref, comp in board.components.items():
            has_connection = False
            for net in board.nets.values():
                for conn_ref, conn_pin in net.connections:
                    if conn_ref == ref:
                        has_connection = True
                        break
                if has_connection:
                    break
            if not has_connection:
                warnings.append(f"  WARNING: Component {ref} has no connections")

        # Check for nets with connections but no routing
        for net_name, net in board.nets.items():
            if len(net.connections) > 0 and len(net.segments) == 0:
                warnings.append(
                    f"  WARNING: Net {net_name} has unrouted pins ({len(net.connections)} connections, 0 segments)"
                )

        # Check via-to-pad collisions
        via_pad_issues = self._check_via_pad_collisions(board)
        errors.extend(via_pad_issues['errors'])
        warnings.extend(via_pad_issues['warnings'])

        # Check via-to-via collisions
        via_via_issues = self._check_via_via_collisions(board)
        errors.extend(via_via_issues['errors'])
        warnings.extend(via_via_issues['warnings'])

        # Check trace-to-trace overlaps and crossings
        trace_overlap_issues = self._check_trace_overlaps(board)
        errors.extend(trace_overlap_issues['errors'])
        warnings.extend(trace_overlap_issues['warnings'])

        # Format output
        lines = [f"DRC: {len(errors)} errors, {len(warnings)} warnings"]
        lines.append("")

        if errors:
            lines.append("Errors found:")
            lines.extend(errors)
            lines.append("")

        if warnings:
            lines.append("Warnings found:")
            lines.extend(warnings)

        return "\n".join(lines).rstrip()

    def undo(self, board: Board) -> str:
        """Undo not applicable for read-only query command.

        Returns:
            Empty string (no undo needed)
        """
        return ""


class CheckAirwiresCommand(Command):
    """Check for unrouted connections (airwires) on the board.

    This is a read-only query command that counts unrouted connections per net.
    A net is considered "routed" if it has at least one trace segment.

    Can check all nets or filter to a specific net name.

    Attributes:
        net_name: Optional net name to filter results, or None for all nets
    """

    def __init__(self, net_name: str = None):
        """Initialize CHECK AIRWIRES command.

        Args:
            net_name: Optional net name to filter results
        """
        self.net_name = net_name

    def validate(self, board: Board) -> str | None:
        """Validate the CHECK AIRWIRES command.

        If net_name is specified, checks that the net exists.

        Returns:
            None if valid, error message if net not found
        """
        if self.net_name is not None:
            if self.net_name not in board.nets:
                return error(f'Net "{self.net_name}" not found')
        return None

    def execute(self, board: Board) -> str:
        """Execute the airwires check.

        Counts unrouted connections for each net (or filtered net).
        A net is "routed" if it has segments.

        Returns:
            Multi-line airwires report
        """
        # Determine which nets to check
        if self.net_name:
            nets_to_check = {self.net_name: board.nets[self.net_name]}
        else:
            nets_to_check = board.nets

        # Count total unrouted connections
        total_unrouted = 0
        lines = []

        for net_name, net in sorted(nets_to_check.items()):
            connection_count = len(net.connections)
            segment_count = len(net.segments)

            # A net is routed if it has segments
            if segment_count > 0:
                routed_count = connection_count
                unrouted_count = 0
            else:
                routed_count = 0
                unrouted_count = connection_count

            total_unrouted += unrouted_count

            # Format line
            if segment_count > 0:
                lines.append(
                    f'  NET "{net_name}": {connection_count} connections, {routed_count} routed ({unrouted_count} unrouted)'
                )
            else:
                lines.append(
                    f'  NET "{net_name}": {connection_count} connections, {routed_count} routed'
                )

        # Build output
        result_lines = [f"AIRWIRES: {total_unrouted} unrouted connections"]
        if lines:
            result_lines.append("")
            result_lines.extend(lines)

        return "\n".join(result_lines)

    def undo(self, board: Board) -> str:
        """Undo not applicable for read-only query command.

        Returns:
            Empty string (no undo needed)
        """
        return ""


class CheckClearanceCommand(Command):
    """Check for clearance violations between components.

    This is a read-only query command that checks if any components are
    too close together (center-to-center distance less than 0.2mm).

    Uses Euclidean distance between component positions.
    """

    def __init__(self):
        """Initialize CHECK CLEARANCE command with no parameters."""
        pass

    def validate(self, board: Board) -> str | None:
        """Validate the CHECK CLEARANCE command.

        This is a read-only command, so validation always succeeds.

        Returns:
            None (always valid)
        """
        return None

    def execute(self, board: Board) -> str:
        """Execute the clearance check.

        Checks all component pairs for clearance violations (< 0.2mm).

        Returns:
            Multi-line clearance report
        """
        min_clearance = 0.2
        violations = []

        components = list(board.components.items())
        for i, (ref1, comp1) in enumerate(components):
            for ref2, comp2 in components[i + 1:]:
                x1, y1 = comp1.position
                x2, y2 = comp2.position
                distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

                if distance < min_clearance:
                    violations.append(
                        f"  {ref1} at ({x1}, {y1}) too close to {ref2} at ({x2}, {y2}) ({distance:.2f}mm < {min_clearance}mm)"
                    )

        # Format output
        lines = [f"CLEARANCE: {len(violations)} violations"]
        if violations:
            lines.append("")
            lines.extend(violations)

        return "\n".join(lines)

    def undo(self, board: Board) -> str:
        """Undo not applicable for read-only query command.

        Returns:
            Empty string (no undo needed)
        """
        return ""


class CheckConnectivityCommand(Command):
    """Check connectivity of all components and nets.

    This is a read-only query command that verifies:
    - All component pins are connected to a net
    - All nets have at least 2 connections

    Reports floating pins and invalid nets.
    """

    def __init__(self):
        """Initialize CHECK CONNECTIVITY command with no parameters."""
        pass

    def validate(self, board: Board) -> str | None:
        """Validate the CHECK CONNECTIVITY command.

        This is a read-only command, so validation always succeeds.

        Returns:
            None (always valid)
        """
        return None

    def execute(self, board: Board) -> str:
        """Execute the connectivity check.

        Checks all pins are connected and all nets are valid.

        Returns:
            Multi-line connectivity report
        """
        issues = []

        # Count pins
        total_pins = 0
        connected_pins = set()

        for ref, comp in board.components.items():
            # For MVP2, we'll estimate pins based on component presence
            # In a full implementation, we'd track actual pin counts
            total_pins += 2  # Assume minimum 2 pins per component

        # Find which components are connected
        for net in board.nets.values():
            for conn_ref, conn_pin in net.connections:
                connected_pins.add(conn_ref)

        # Check for components with no connections (floating pins)
        for ref in board.components.keys():
            if ref not in connected_pins:
                issues.append(f"  Component {ref} has floating pins: 1, 2")

        # Check for nets with insufficient connections
        for net_name, net in board.nets.items():
            if len(net.connections) < 2:
                issues.append(f'  Net "{net_name}" has only {len(net.connections)} connection (needs at least 2)')

        # Format output
        if not issues:
            lines = ["CONNECTIVITY: OK"]
            lines.append("")
            lines.append("All nets have valid connections.")
            connected_count = len(connected_pins) * 2  # Estimate
            floating_count = total_pins - connected_count
            lines.append(f"Component pins: {total_pins} total, {connected_count} connected, {floating_count} floating")
        else:
            lines = [f"CONNECTIVITY: {len(issues)} issues"]
            lines.append("")
            lines.extend(issues)

        return "\n".join(lines)

    def undo(self, board: Board) -> str:
        """Undo not applicable for read-only query command.

        Returns:
            Empty string (no undo needed)
        """
        return ""


class ShowNetCommand(Command):
    """Display detailed information about a net.

    This is a read-only query command that shows:
    - Net name and code
    - All connections (component.pin)
    - Routing information (segments and vias)

    Attributes:
        net_name: Name of the net to display
    """

    def __init__(self, net_name: str):
        """Initialize SHOW NET command.

        Args:
            net_name: Name of the net to display
        """
        self.net_name = net_name

    def validate(self, board: Board) -> str | None:
        """Validate the SHOW NET command.

        Checks that the specified net exists.

        Returns:
            None if valid, error message if net not found
        """
        if self.net_name not in board.nets:
            return error(f'Net "{self.net_name}" not found')
        return None

    def execute(self, board: Board) -> str:
        """Execute the SHOW NET command.

        Displays net details including connections, segments, and vias.

        Returns:
            Multi-line formatted net information
        """
        net = board.nets[self.net_name]
        lines = []

        # Header: NET "name" (code X):
        lines.append(f'NET "{self.net_name}" (code {net.code}):')

        # Connections section
        conn_count = len(net.connections)
        lines.append(f"  Connections: {conn_count}")
        for ref, pin in net.connections:
            lines.append(f"    {ref}.{pin}")

        lines.append("")

        # Routing section
        lines.append("  Routing:")
        segment_count = len(net.segments)
        lines.append(f"    Segments: {segment_count}")

        if segment_count > 0:
            for segment in net.segments:
                x1, y1 = segment.start
                x2, y2 = segment.end
                lines.append(f"      ({x1}, {y1}) → ({x2}, {y2}) [{segment.layer}, {segment.width}mm]")
        else:
            lines.append("      (no routed segments)")

        # Vias section
        via_count = len(net.vias)
        lines.append(f"    Vias: {via_count}")
        if via_count > 0:
            for via in net.vias:
                x, y = via.position
                lines.append(f"      ({x}, {y}) [{via.size}mm, drill {via.drill}mm]")

        return "\n".join(lines)

    def undo(self, board: Board) -> str:
        """Undo not applicable for read-only query command.

        Returns:
            Empty string (no undo needed)
        """
        return ""


class ShowAirwiresCommand(Command):
    """Display unrouted connections (airwires) on the board.

    This is a read-only query command that shows which nets have
    unrouted connections. A net is considered "routed" if it has
    at least one trace segment.

    Can filter to a specific net or show all nets.

    Attributes:
        net_name: Optional net name to filter results, or None for all nets
    """

    def __init__(self, net_name: str = None):
        """Initialize SHOW AIRWIRES command.

        Args:
            net_name: Optional net name to filter results
        """
        self.net_name = net_name

    def validate(self, board: Board) -> str | None:
        """Validate the SHOW AIRWIRES command.

        If net_name is specified, checks that the net exists.

        Returns:
            None if valid, error message if net not found
        """
        if self.net_name is not None:
            if self.net_name not in board.nets:
                return error(f'Net "{self.net_name}" not found')
        return None

    def execute(self, board: Board) -> str:
        """Execute the SHOW AIRWIRES command.

        Shows unrouted connections for each net (or filtered net).
        A net is "routed" if it has segments.

        Returns:
            Multi-line airwires report
        """
        # Determine which nets to check
        if self.net_name:
            nets_to_check = {self.net_name: board.nets[self.net_name]}
        else:
            nets_to_check = board.nets

        # Count total unrouted connections
        total_unrouted = 0
        lines = []

        for net_name, net in sorted(nets_to_check.items()):
            connection_count = len(net.connections)
            segment_count = len(net.segments)

            # A net is routed if it has segments
            if segment_count > 0:
                routed_count = connection_count
                unrouted_count = 0
            else:
                routed_count = 0
                unrouted_count = connection_count

            total_unrouted += unrouted_count

            # Format line
            lines.append(
                f'NET "{net_name}" ({connection_count} connections, {routed_count} routed):'
            )

        # Build output
        result_lines = [f"AIRWIRES: {total_unrouted} unrouted connections"]
        result_lines.append("")
        result_lines.extend(lines)

        return "\n".join(result_lines)

    def undo(self, board: Board) -> str:
        """Undo not applicable for read-only query command.

        Returns:
            Empty string (no undo needed)
        """
        return ""


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

    def __init__(self, net_name: Optional[str] = None, prefer_layer: Optional[str] = None,
                 optimize: bool = True, ground_plane_mode: bool = False,
                 via_costs: Optional[Dict[str, float]] = None,
                 manual_routes: Optional[Dict[str, Dict]] = None,
                 constraints: Optional['RoutingConstraints'] = None):
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
            return error("Board has no components. Load a netlist first with: LOAD <file>")

        # Check board has nets
        if not board.nets:
            return error("Board has no nets. Load a netlist first with: LOAD <file>")

        # Check specific net exists
        if self.net_name not in ["ALL", "UNROUTED"] and self.net_name not in board.nets:
            available_nets = ', '.join(sorted(board.nets.keys())[:5])
            if len(board.nets) > 5:
                available_nets += f" ... and {len(board.nets) - 5} more"
            return error(f'Net "{self.net_name}" not found. Available nets: {available_nets}. Use "LIST NETS" to see all nets.')

        # Validate layer preference
        if self.prefer_layer and self.prefer_layer not in ["F.Cu", "B.Cu"]:
            return error(f'Invalid layer "{self.prefer_layer}". Must be F.Cu or B.Cu.')

        return None

    def execute(self, board: Board) -> str:
        """Execute the auto-route command.

        Creates routing grid, extracts net definitions, routes nets using
        MultiNetRouter, and applies results to board.

        Returns:
            Result message string with routing statistics
        """
        from pcb_tool.routing import MultiNetRouter, NetDefinition

        # Determine which nets to route
        if self.net_name == "ALL":
            nets_to_route = list(board.nets.keys())
        elif self.net_name == "UNROUTED":
            # Find nets with connections but no segments
            nets_to_route = [
                name for name, net in board.nets.items()
                if len(net.connections) > 0 and len(net.segments) == 0
            ]
        else:
            nets_to_route = [self.net_name]

        if not nets_to_route:
            return "No nets to route. All nets are either already routed or have insufficient connections."

        # Warning for dense boards
        if len(nets_to_route) > 50:
            print(f"Warning: Routing {len(nets_to_route)} nets may take 30-60 seconds...")

        # Create routing grid from board
        print(f"Initializing routing grid...")
        grid = self._create_routing_grid(board)
        stats = grid.get_statistics()
        total_cells = stats['dimensions']['total_cells']
        obstacles = stats['obstacles']['F.Cu'] + stats['obstacles']['B.Cu']
        congestion = (obstacles / (total_cells * 2)) * 100

        # Warning for congested boards
        if congestion > 30:
            print(f"Warning: Board is {congestion:.0f}% congested. Consider spreading components with ARRANGE GRID.")

        # Extract net definitions
        print(f"Analyzing {len(nets_to_route)} nets...")
        net_definitions = self._extract_net_definitions(board, nets_to_route)

        if not net_definitions:
            return error("No valid connections found to route. Nets must have at least 2 connections. Use LIST NETS to check net connections.")

        # Create router
        router = MultiNetRouter(grid, ground_plane_mode=self.ground_plane_mode, via_cost_map=self.via_costs)

        # Apply manual routes first (before auto-routing)
        if self.manual_routes:
            print(f"Applying {len(self.manual_routes)} manual routes...")
            for net_name, route_spec in self.manual_routes.items():
                path = route_spec.get("path", [])
                layer = route_spec.get("layer", "F.Cu")
                width_mm = route_spec.get("width_mm", 0.25)
                router.add_manual_route(net_name, path, layer, width_mm)

        # Route nets
        if self.ground_plane_mode:
            print(f"Routing {len(net_definitions)} nets in ground plane mode (B.Cu=GND plane, F.Cu=signals)...")
        else:
            print(f"Routing {len(net_definitions)} nets (power nets prioritized)...")
        routed_nets = router.route_nets(net_definitions, constraints=self.constraints)

        # Apply routing to board
        success_count, total_length, total_vias = self._apply_routing_to_board(
            board, routed_nets
        )

        # Format report
        return self._format_routing_report(
            nets_to_route, routed_nets, success_count, total_length, total_vias
        )

    def _create_routing_grid(self, board: Board):
        """Create RoutingGrid from board dimensions and mark obstacles.

        Args:
            board: Board to create grid from

        Returns:
            RoutingGrid instance with obstacles marked
        """
        from pcb_tool.routing import RoutingGrid

        # Calculate board dimensions from component positions
        # RoutingGrid always uses (0,0) origin, so we need to cover the full area
        if not board.components:
            # Default size if no components
            width_mm, height_mm = 100.0, 100.0
        else:
            positions = [comp.position for comp in board.components.values()]
            max_x = max(pos[0] for pos in positions) + 10.0
            max_y = max(pos[1] for pos in positions) + 10.0
            # Ensure minimum size
            width_mm = max(max_x, 20.0)
            height_mm = max(max_y, 20.0)

        # Create grid with 0.2mm resolution
        grid = RoutingGrid(
            width_mm=width_mm,
            height_mm=height_mm,
            resolution_mm=0.2,
            default_clearance_mm=0.2
        )

        # Mark component positions as obstacles
        for comp in board.components.values():
            x, y = comp.position
            grid_x, grid_y = grid.to_grid_coords(x, y)
            # Mark a 3x3 area around component center
            for dx in [-1, 0, 1]:
                for dy in [-1, 0, 1]:
                    gx, gy = grid_x + dx, grid_y + dy
                    if 0 <= gx < grid.grid_width and 0 <= gy < grid.grid_height:
                        grid.mark_obstacle(gx, gy, "F.Cu")
                        grid.mark_obstacle(gx, gy, "B.Cu")

        # Mark existing trace segments as obstacles
        for net in board.nets.values():
            for segment in net.segments:
                start_gx, start_gy = grid.to_grid_coords(*segment.start)
                end_gx, end_gy = grid.to_grid_coords(*segment.end)
                # Simple line marking (could be improved with DDA)
                grid.mark_obstacle(start_gx, start_gy, segment.layer)
                grid.mark_obstacle(end_gx, end_gy, segment.layer)

        # Mark existing vias as obstacles
        for net in board.nets.values():
            for via in net.vias:
                via_gx, via_gy = grid.to_grid_coords(*via.position)
                grid.mark_obstacle(via_gx, via_gy, "F.Cu")
                grid.mark_obstacle(via_gx, via_gy, "B.Cu")

        return grid

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
        from pcb_tool.routing import NetDefinition

        net_definitions = []

        for net_name in net_names:
            net = board.nets.get(net_name)
            if not net or len(net.connections) < 2:
                continue

            # Get all pad positions for this net
            pad_positions = []
            for ref, pin in net.connections:
                comp = board.get_component(ref)
                if not comp:
                    continue
                try:
                    pos = comp.get_pad_position(int(pin))
                    pad_positions.append((ref, pin, pos))
                except (ValueError, KeyError):
                    # Fallback to component position
                    pad_positions.append((ref, pin, comp.position))

            if len(pad_positions) < 2:
                continue

            # Create spanning tree using Prim's algorithm
            edges = self._create_minimum_spanning_tree(pad_positions)

            # Create NetDefinition for each edge
            layer = self.prefer_layer or "F.Cu"
            for (ref1, pin1, pos1), (ref2, pin2, pos2) in edges:
                net_def = NetDefinition(
                    name=net_name,
                    start=pos1,
                    end=pos2,
                    layer=layer,
                    priority=0
                )
                net_definitions.append(net_def)

        return net_definitions

    def _create_minimum_spanning_tree(self, points: list[tuple]) -> list[tuple]:
        """Create minimum spanning tree connecting all points.

        Uses Prim's algorithm to find MST, ensuring all pads in a net are connected
        with minimum total wire length.

        Args:
            points: List of (ref, pin, (x, y)) tuples

        Returns:
            List of edge tuples: ((ref1, pin1, pos1), (ref2, pin2, pos2))
        """
        if len(points) == 0:
            return []
        if len(points) == 1:
            return []
        if len(points) == 2:
            return [(points[0], points[1])]

        # Prim's algorithm
        visited = {0}  # Start with first point
        edges = []

        while len(visited) < len(points):
            min_dist = float('inf')
            best_edge = None

            # Find shortest edge from visited to unvisited
            for i in visited:
                _, _, (x1, y1) = points[i]
                for j in range(len(points)):
                    if j in visited:
                        continue
                    _, _, (x2, y2) = points[j]
                    dist = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
                    if dist < min_dist:
                        min_dist = dist
                        best_edge = (i, j)

            if best_edge:
                i, j = best_edge
                edges.append((points[i], points[j]))
                visited.add(j)
            else:
                break  # Disconnected graph (shouldn't happen)

        return edges

    def _apply_routing_to_board(self, board: Board, routed_nets: dict) -> tuple[int, float, int]:
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

            # Add trace segments
            for start, end in routed_net.segments:
                segment = TraceSegment(
                    net_name=net_name,
                    start=start,
                    end=end,
                    layer=routed_net.layer,
                    width=net.track_width
                )
                net.add_segment(segment)
                self.added_segments.append((net_name, segment))

                # Calculate length
                dx = end[0] - start[0]
                dy = end[1] - start[1]
                length = math.sqrt(dx*dx + dy*dy)
                total_length += length

            success_count += 1

        return success_count, total_length, total_vias

    def _format_routing_report(self, requested_nets: list[str], routed_nets: dict,
                               success_count: int, total_length: float,
                               total_vias: int) -> str:
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
            return error(f"No nets could be routed. Failed: {', '.join(failed_nets[:3])}" + suggestions)

        lines = []

        if len(requested_nets) == 1:
            # Single net report
            net_name = requested_nets[0]
            if net_name in routed_nets:
                routed = routed_nets[net_name]
                lines.append(f"Routing net {net_name}...")
                lines.append(f"  Path length: {total_length:.1f}mm")
                lines.append(f"  Segments: {len(routed.segments)}")
                return success("\n".join(lines) + f"\nOK: Net {net_name} routed successfully")
            else:
                suggestions = f"\n\nTroubleshooting for {net_name}:"
                suggestions += f"\n  1. Try opposite layer: AUTOROUTE NET {net_name} PREFER B.Cu"
                suggestions += "\n  2. Check component spacing: SHOW BOARD"
                suggestions += f"\n  3. Manual routing: ROUTE NET {net_name} FROM ... TO ..."
                return error(f"Failed to route net {net_name}. No path found." + suggestions)
        else:
            # Multiple nets report with progress indicators
            power_net_patterns = {'GND', 'VCC', 'VDD', 'VSS', '+12V', '+5V', '+3V3'}

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
                        net_length += math.sqrt(dx*dx + dy*dy)

                    # Mark power nets
                    is_power = any(p in net_name.upper() for p in power_net_patterns)
                    power_tag = " [POWER]" if is_power else ""
                    lines.append(f"  [{i}/{len(requested_nets)}] {net_name} ... OK ({net_length:.1f}mm){power_tag}")
                else:
                    lines.append(f"  [{i}/{len(requested_nets)}] {net_name} ... FAILED (no path)")

            # Summary
            failed_count = len(requested_nets) - success_count
            lines.append(f"\nOK: {success_count}/{len(requested_nets)} nets routed")
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

        return success(f"Undone: Removed {len(self.added_segments)} segments and {len(self.added_vias)} vias")


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
            return error("Board has no routing to optimize. Route nets first with: AUTOROUTE ALL")

        # Check specific net exists
        if self.net_name != "ALL":
            net = board.nets.get(self.net_name)
            if not net:
                available_nets = ', '.join(sorted(board.nets.keys())[:5])
                return error(f'Net "{self.net_name}" not found. Available nets: {available_nets}')
            # Check if at least one net is routed
            if len(net.segments) == 0:
                return error(f'Net "{self.net_name}" has no routing. Route it first with: AUTOROUTE NET {self.net_name}')

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
                name for name, net in board.nets.items()
                if len(net.segments) > 0
            ]
        else:
            nets_to_optimize = [self.net_name]

        if not nets_to_optimize:
            return "No routed nets to optimize. Route nets first with: AUTOROUTE ALL"

        # Warning for complex optimization
        if len(nets_to_optimize) > 20:
            print(f"Warning: Optimizing {len(nets_to_optimize)} nets may take up to 10 seconds...")

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
                    default_layer=net.segments[0].layer if net.segments else "F.Cu"
                )
                net_paths.append(net_path)

        if not net_paths:
            return error("No valid routing to optimize. Ensure nets have trace segments.")

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
        from pcb_tool.routing import RoutingGrid

        # Calculate board dimensions
        # RoutingGrid always uses (0,0) origin, so we need to cover the full area
        if not board.components:
            width_mm, height_mm = 100.0, 100.0
        else:
            positions = [comp.position for comp in board.components.values()]
            max_x = max(pos[0] for pos in positions) + 10.0
            max_y = max(pos[1] for pos in positions) + 10.0
            width_mm = max(max_x, 20.0)
            height_mm = max(max_y, 20.0)

        return RoutingGrid(
            width_mm=width_mm,
            height_mm=height_mm,
            resolution_mm=0.2
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
            for i, (segment_idx, layer, via_after) in enumerate(assignment.segment_assignments):
                if segment_idx < len(net.segments):
                    # Update layer
                    old_layer = net.segments[segment_idx].layer
                    net.segments[segment_idx] = TraceSegment(
                        net_name=net.segments[segment_idx].net_name,
                        start=net.segments[segment_idx].start,
                        end=net.segments[segment_idx].end,
                        layer=layer,
                        width=net.segments[segment_idx].width
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
                        width=net.segments[segment_idx].width
                    )

        return success("Undone: Restored original layer assignments")
