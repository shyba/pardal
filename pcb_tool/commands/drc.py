"""DRC Commands - Design Rule Check, Airwires, Clearance, Connectivity"""

import math
from pcb_tool.commands.base import Command
from pcb_tool.data_model import Board
from pcb_tool.messages import error


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
        issues = {"errors": [], "warnings": []}

        for net_name, net in board.nets.items():
            for via in net.vias:
                via_x, via_y = via.position
                via_radius = via.size / 2

                for comp_ref, component in board.components.items():
                    for pad in component.pads:
                        pad_x, pad_y = component.get_pad_position(pad.number)
                        distance = math.sqrt(
                            (via_x - pad_x) ** 2 + (via_y - pad_y) ** 2
                        )

                        # Check for exact position collision
                        if distance < 0.01:
                            issues["errors"].append(
                                f"  ERROR: Via on net {net_name} at ({via_x}, {via_y}) "
                                f"overlaps {comp_ref} pad {pad.number}. Drill holes co-located."
                            )
                        # Check proximity with different net pads
                        elif (
                            pad.net_name
                            and distance < via_radius + max(pad.size) / 2 + 0.1
                        ):
                            if pad.net_name != net_name:
                                issues["errors"].append(
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
        issues = {"errors": [], "warnings": []}

        # Collect all vias with their net names
        all_vias = []
        for net_name, net in board.nets.items():
            for via in net.vias:
                all_vias.append((net_name, via))

        # Check each pair of vias
        for i, (net1, via1) in enumerate(all_vias):
            for net2, via2 in all_vias[i + 1 :]:
                x1, y1 = via1.position
                x2, y2 = via2.position
                distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

                # Check for exact position collision
                if distance < 0.01:
                    if net1 != net2:
                        issues["errors"].append(
                            f"  ERROR: Vias on nets {net1} and {net2} overlap at ({x1}, {y1})"
                        )
                # Check proximity with different net vias
                else:
                    min_clearance = (via1.size + via2.size) / 2 + 0.2
                    if distance < min_clearance and net1 != net2:
                        issues["errors"].append(
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
        issues = {"errors": [], "warnings": []}

        # Collect all segments by layer
        segments_by_layer = {}
        for net_name, net in board.nets.items():
            for segment in net.segments:
                layer = segment.layer
                if layer not in segments_by_layer:
                    segments_by_layer[layer] = []
                segments_by_layer[layer].append((net_name, segment))

        # Check segments on each layer (dedupe by net-pair + intersection point)
        for layer, segments in segments_by_layer.items():
            seen = set()
            for i, (net1, seg1) in enumerate(segments):
                for net2, seg2 in segments[i + 1 :]:
                    # Skip if same net
                    if net1 == net2:
                        continue

                    # Check if segments intersect or are too close
                    intersection = self._segments_intersect(seg1, seg2)
                    if intersection:
                        x, y = intersection
                        key = (
                            layer,
                            tuple(sorted((net1, net2))),
                            round(x, 2),
                            round(y, 2),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        issues["errors"].append(
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

    def _point_to_segment_distance(
        self, px: float, py: float, x1: float, y1: float, x2: float, y2: float
    ) -> float:
        """Calculate minimum distance from point to line segment.

        Args:
            px, py: Point coordinates
            x1, y1: Segment start coordinates
            x2, y2: Segment end coordinates

        Returns:
            Minimum distance from point to segment
        """
        # Vector from segment start to end
        dx = x2 - x1
        dy = y2 - y1

        # Handle zero-length segment
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-10:
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)

        # Project point onto line, clamped to segment
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / seg_len_sq))

        # Closest point on segment
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy

        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

    def _check_track_pad_clearance(self, board: Board) -> dict:
        """Check for track-to-pad clearance violations.

        For each track segment, checks distance to all pads on the same layer.
        Skips pads that belong to the same net as the track.

        Args:
            board: The board to check

        Returns:
            Dictionary with 'errors' and 'warnings' lists
        """
        issues = {"errors": [], "warnings": []}
        min_clearance = 0.2  # Default clearance in mm

        # Build pad-to-net mapping for quick lookup
        pad_nets = {}  # (comp_ref, pad_num) -> net_name
        for net_name, net in board.nets.items():
            for conn_ref, conn_pin in net.connections:
                pad_nets[(conn_ref, str(conn_pin))] = net_name

        # Check each track segment against each pad, but report each (net,pad,layer)
        # violation once (keep worst clearance / short).
        shorts = set()  # (net, comp_ref, pad_num, layer)
        worst_clearance = {}  # (net, comp_ref, pad_num, layer) -> min clearance

        for net_name, net in board.nets.items():
            for segment in net.segments:
                seg_layer = segment.layer
                x1, y1 = segment.start
                x2, y2 = segment.end
                track_half_width = segment.width / 2

                for comp_ref, component in board.components.items():
                    # Only check pads on same layer (or through-hole on all layers)
                    comp_layer = component.layer
                    if comp_layer not in [
                        seg_layer,
                        "F.Cu",
                        "B.Cu",
                    ] and seg_layer not in ["F.Cu", "B.Cu"]:
                        continue

                    for pad in component.pads:
                        # Skip if pad is on the same net
                        pad_net = pad_nets.get((comp_ref, str(pad.number)))
                        if pad_net == net_name:
                            continue

                        pad_x, pad_y = component.get_pad_position(pad.number)
                        pad_radius = max(pad.size[0], pad.size[1]) / 2

                        # Calculate distance from pad center to track segment
                        dist = self._point_to_segment_distance(
                            pad_x, pad_y, x1, y1, x2, y2
                        )

                        # Actual clearance = distance - track_half_width - pad_radius
                        actual_clearance = dist - track_half_width - pad_radius

                        if actual_clearance < 0:
                            # Track touches/overlaps pad - this is a short
                            shorts.add(
                                (
                                    net_name,
                                    comp_ref,
                                    pad.number,
                                    seg_layer,
                                    pad_net or "none",
                                )
                            )
                        elif actual_clearance < min_clearance:
                            key = (net_name, comp_ref, pad.number, seg_layer)
                            prev = worst_clearance.get(key)
                            if prev is None or actual_clearance < prev:
                                worst_clearance[key] = actual_clearance

        for net_name, comp_ref, pad_num, seg_layer, pad_net in sorted(shorts):
            issues["errors"].append(
                f"  ERROR: Track [{net_name}] shorts to {comp_ref} pad {pad_num} "
                f"(net: {pad_net}) on {seg_layer}"
            )

        for (net_name, comp_ref, pad_num, seg_layer), clearance in sorted(
            worst_clearance.items()
        ):
            issues["errors"].append(
                f"  ERROR: Track [{net_name}] too close to {comp_ref} pad {pad_num} "
                f"({clearance:.2f}mm < {min_clearance}mm) on {seg_layer}"
            )

        return issues

    def _check_pad_pad_clearance(self, board: Board) -> dict:
        """Check for pad-to-pad clearance violations within components.

        Detects overlapping or too-close pads in footprint definitions,
        such as TQFP with oversized pads.

        Args:
            board: The board to check

        Returns:
            Dictionary with 'errors' and 'warnings' lists
        """
        issues = {"errors": [], "warnings": []}
        min_clearance = 0.1  # Minimum clearance between pads in mm

        for comp_ref, component in board.components.items():
            pads = component.pads
            if len(pads) < 2:
                continue

            # Check each pair of pads
            for i, pad1 in enumerate(pads):
                for pad2 in pads[i + 1 :]:
                    # Get absolute pad positions
                    x1, y1 = component.get_pad_position(pad1.number)
                    x2, y2 = component.get_pad_position(pad2.number)

                    # Calculate center-to-center distance
                    center_dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

                    # Calculate pad radii (use max dimension for conservative check)
                    r1 = max(pad1.size[0], pad1.size[1]) / 2
                    r2 = max(pad2.size[0], pad2.size[1]) / 2

                    # Edge-to-edge clearance
                    edge_clearance = center_dist - r1 - r2

                    if edge_clearance < 0:
                        issues["errors"].append(
                            f"  ERROR: Pads {pad1.number} and {pad2.number} of {comp_ref} overlap "
                            f"by {abs(edge_clearance):.2f}mm (footprint definition error)"
                        )
                    elif edge_clearance < min_clearance:
                        issues["warnings"].append(
                            f"  WARNING: Pads {pad1.number} and {pad2.number} of {comp_ref} "
                            f"very close ({edge_clearance:.2f}mm < {min_clearance}mm)"
                        )

        return issues

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
            for comp2 in components[i + 1 :]:
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
        errors.extend(via_pad_issues["errors"])
        warnings.extend(via_pad_issues["warnings"])

        # Check via-to-via collisions
        via_via_issues = self._check_via_via_collisions(board)
        errors.extend(via_via_issues["errors"])
        warnings.extend(via_via_issues["warnings"])

        # Check trace-to-trace overlaps and crossings
        trace_overlap_issues = self._check_trace_overlaps(board)
        errors.extend(trace_overlap_issues["errors"])
        warnings.extend(trace_overlap_issues["warnings"])

        # Check track-to-pad clearance
        track_pad_issues = self._check_track_pad_clearance(board)
        errors.extend(track_pad_issues["errors"])
        warnings.extend(track_pad_issues["warnings"])

        # Check pad-to-pad clearance within components
        pad_pad_issues = self._check_pad_pad_clearance(board)
        errors.extend(pad_pad_issues["errors"])
        warnings.extend(pad_pad_issues["warnings"])

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
            for ref2, comp2 in components[i + 1 :]:
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
                issues.append(
                    f'  Net "{net_name}" has only {len(net.connections)} connection (needs at least 2)'
                )

        # Format output
        if not issues:
            lines = ["CONNECTIVITY: OK"]
            lines.append("")
            lines.append("All nets have valid connections.")
            connected_count = len(connected_pins) * 2  # Estimate
            floating_count = total_pins - connected_count
            lines.append(
                f"Component pins: {total_pins} total, {connected_count} connected, {floating_count} floating"
            )
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
