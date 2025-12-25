"""Display Commands - List, Show Board, Show Net, Show Airwires"""

from pcb_tool.commands.base import Command
from pcb_tool.data_model import Board
from pcb_tool.messages import error


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

            # Format: REF: Value @ (x, y) rot° Layer [N pads] [LOCKED]
            pad_count = len(comp.pads)
            pad_info = f"[{pad_count} pads]" if pad_count > 0 else "[NO PADS!]"
            line = f"  {ref}: {comp.value} @ ({x}, {y}) {int(comp.rotation)}° {comp.layer} {pad_info}{locked_tag}"
            lines.append(line)

        return "\n".join(lines)


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
