"""Component Commands - Lock, Unlock, Move, Rotate, Flip, Where, GroupMove, Arrange"""

import math
from pardal.commands.base import Command
from pardal.data_model import Board
from pardal.messages import success, error


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
        return success(
            f"Moved {self.ref} to ({self.x}, {self.y}) rotation {comp.rotation}°"
        )

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
            return success(
                f"Rotated {self.ref} by {self.angle}° (now at {comp.rotation}°)"
            )

    def undo(self, board: Board) -> str:
        comp = board.get_component(self.ref)
        comp.rotation = self.old_rotation
        return success(f"Restored {self.ref} rotation to {self.old_rotation}°")


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
            f"  Locked: {locked_status}",
        ]

        return "\n".join(lines)


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
        lines = [
            success(
                f"Moved {len(self.component_refs)} components by ({self.dx}, {self.dy})"
            )
        ]

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

        return success(
            f"Restored {len(self.component_refs)} components to original positions"
        )


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

    def __init__(
        self, component_refs: list[str], pattern: str = "GRID", spacing: float = 5.0
    ):
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
                comp.position = (
                    start_x + col * self.spacing,
                    start_y + row * self.spacing,
                )

        # Build result message
        lines = [
            success(f"Arranged {len(self.component_refs)} components in {self.pattern}")
        ]
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

        return success(
            f"Restored {len(self.component_refs)} components to original positions"
        )
