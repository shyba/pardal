"""Measure Commands - Distance and Net Length"""

import math
from pcb_tool.commands.base import Command
from pcb_tool.data_model import Board
from pcb_tool.messages import error


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
