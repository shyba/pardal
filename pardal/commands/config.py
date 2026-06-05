"""
PCB Tool Configuration Commands

Commands for setting board and routing parameters.
"""

from typing import Optional, List, Tuple
from pardal.commands.base import Command
from pardal.data_model import Board, NetClass, Net, Component, Pad
from pardal.footprint_templates import generate_pads, get_template


class SetWidthCommand(Command):
    """Set trace width for a net or net class.

    Syntax:
        SET WIDTH NET <net_name> <width_mm>
        SET WIDTH CLASS <class_name> <width_mm>
        SET WIDTH DEFAULT <width_mm>

    Examples:
        SET WIDTH NET GND 0.5
        SET WIDTH NET +12V 0.8
        SET WIDTH CLASS Power 0.5
        SET WIDTH DEFAULT 0.3
    """

    def __init__(
        self,
        width: float,
        net_name: Optional[str] = None,
        class_name: Optional[str] = None,
        set_default: bool = False,
    ):
        """Initialize SetWidthCommand.

        Args:
            width: Trace width in millimeters
            net_name: Name of net to set width for (mutually exclusive with class_name)
            class_name: Name of net class to set width for
            set_default: If True, set the default width for all nets without explicit width
        """
        self.width = width
        self.net_name = net_name
        self.class_name = class_name
        self.set_default = set_default
        self._previous_width: Optional[float] = None
        self._previous_class_width: Optional[float] = None

    def validate(self, board: Board) -> str | None:
        """Validate command parameters."""
        # Check width is positive
        if self.width <= 0:
            return f"Error: Width must be positive, got {self.width}mm"

        # Check width is reasonable (0.1mm to 10mm)
        if self.width < 0.1:
            return f"Error: Width {self.width}mm is below minimum 0.1mm"
        if self.width > 10.0:
            return f"Error: Width {self.width}mm exceeds maximum 10mm"

        # Check that exactly one target is specified
        targets = sum(
            [self.net_name is not None, self.class_name is not None, self.set_default]
        )
        if targets != 1:
            return "Error: Must specify exactly one of NET, CLASS, or DEFAULT"

        # Check net exists if specified
        if self.net_name is not None:
            if self.net_name not in board.nets:
                return f"Error: Net '{self.net_name}' not found"

        return None

    def execute(self, board: Board) -> str:
        """Execute the command."""
        if self.net_name is not None:
            # Set width for specific net
            net = board.nets[self.net_name]
            self._previous_width = net.track_width
            net.track_width = self.width
            return f"OK: Set trace width for net '{self.net_name}' to {self.width}mm"

        elif self.class_name is not None:
            # Set width for net class (create if doesn't exist)
            if self.class_name not in board.net_classes:
                board.net_classes[self.class_name] = NetClass(name=self.class_name)
            self._previous_class_width = board.net_classes[self.class_name].track_width
            board.net_classes[self.class_name].track_width = self.width
            return (
                f"OK: Set trace width for class '{self.class_name}' to {self.width}mm"
            )

        elif self.set_default:
            # Set default width for all nets without explicit class
            count = 0
            for net in board.nets.values():
                if net.net_class is None:
                    net.track_width = self.width
                    count += 1
            return (
                f"OK: Set default trace width to {self.width}mm ({count} nets updated)"
            )

        return "Error: No target specified"

    def undo(self, board: Board) -> str:
        """Undo the command."""
        if self.net_name is not None and self._previous_width is not None:
            board.nets[self.net_name].track_width = self._previous_width
            return f"OK: Restored trace width for net '{self.net_name}' to {self._previous_width}mm"

        elif self.class_name is not None and self._previous_class_width is not None:
            if self.class_name in board.net_classes:
                board.net_classes[self.class_name].track_width = (
                    self._previous_class_width
                )
            return f"OK: Restored trace width for class '{self.class_name}' to {self._previous_class_width}mm"

        return "Undo not available for this command"


class SetLayersCommand(Command):
    """Set the number of routing layers for the board.

    Syntax:
        SET LAYERS <count>

    Examples:
        SET LAYERS 2
        SET LAYERS 4

    Supported layer counts: 2, 4, 6
    """

    LAYER_CONFIGS = {
        2: ["F.Cu", "B.Cu"],
        4: ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        6: ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"],
    }

    def __init__(self, layer_count: int):
        """Initialize SetLayersCommand.

        Args:
            layer_count: Number of copper layers (2, 4, or 6)
        """
        self.layer_count = layer_count
        self._previous_layers: list[str] = []

    def validate(self, board: Board) -> str | None:
        """Validate command parameters."""
        if self.layer_count not in self.LAYER_CONFIGS:
            return (
                f"Error: Unsupported layer count {self.layer_count}. Supported: 2, 4, 6"
            )
        return None

    def execute(self, board: Board) -> str:
        """Execute the command."""
        self._previous_layers = list(board.layers)
        board.layers = self.LAYER_CONFIGS[self.layer_count].copy()
        return f"OK: Set board to {self.layer_count} layers: {', '.join(board.layers)}"

    def undo(self, board: Board) -> str:
        """Undo the command."""
        if self._previous_layers:
            board.layers = self._previous_layers
            return f"OK: Restored layers to: {', '.join(board.layers)}"
        return "Undo not available"


class SetClearanceCommand(Command):
    """Set clearance for a net class.

    Clearance is defined at the net class level. To set clearance for a specific
    net, first assign it to a net class with the desired clearance.

    Syntax:
        SET CLEARANCE CLASS <class_name> <clearance_mm>

    Examples:
        SET CLEARANCE CLASS Power 0.3
        SET CLEARANCE CLASS HighVoltage 0.5
    """

    def __init__(
        self,
        clearance: float,
        net_name: Optional[str] = None,
        class_name: Optional[str] = None,
    ):
        """Initialize SetClearanceCommand.

        Args:
            clearance: Clearance in millimeters
            net_name: Deprecated - clearance is only supported at class level
            class_name: Name of net class to set clearance for
        """
        self.clearance = clearance
        self.net_name = net_name  # Keep for error message
        self.class_name = class_name
        self._previous_clearance: Optional[float] = None

    def validate(self, board: Board) -> str | None:
        """Validate command parameters."""
        # Clearance is only supported at class level
        if self.net_name is not None:
            return "Error: Clearance can only be set at class level. Use: SET CLEARANCE CLASS <name> <value>"

        if self.clearance <= 0:
            return f"Error: Clearance must be positive, got {self.clearance}mm"

        if self.clearance < 0.1:
            return f"Error: Clearance {self.clearance}mm is below minimum 0.1mm"

        if self.class_name is None:
            return "Error: Must specify CLASS"

        return None

    def execute(self, board: Board) -> str:
        """Execute the command."""
        if self.class_name is not None:
            if self.class_name not in board.net_classes:
                board.net_classes[self.class_name] = NetClass(name=self.class_name)
            self._previous_clearance = board.net_classes[self.class_name].clearance
            board.net_classes[self.class_name].clearance = self.clearance
            return (
                f"OK: Set clearance for class '{self.class_name}' to {self.clearance}mm"
            )

        return "Error: No target specified"

    def undo(self, board: Board) -> str:
        """Undo the command."""
        if self._previous_clearance is not None:
            if self.class_name is not None and self.class_name in board.net_classes:
                board.net_classes[self.class_name].clearance = self._previous_clearance
                return f"OK: Restored clearance for class '{self.class_name}'"
        return "Undo not available"


class SetBoardSizeCommand(Command):
    """Set the board dimensions.

    Syntax:
        SET BOARD SIZE <width_mm> <height_mm>

    Examples:
        SET BOARD SIZE 100 80
        SET BOARD SIZE 40 40
    """

    def __init__(self, width: float, height: float):
        """Initialize SetBoardSizeCommand.

        Args:
            width: Board width in millimeters
            height: Board height in millimeters
        """
        self.width = width
        self.height = height
        self._previous_width: Optional[float] = None
        self._previous_height: Optional[float] = None

    def validate(self, board: Board) -> str | None:
        """Validate command parameters."""
        if self.width <= 0:
            return f"Error: Width must be positive, got {self.width}mm"
        if self.height <= 0:
            return f"Error: Height must be positive, got {self.height}mm"
        if self.width > 1000 or self.height > 1000:
            return "Error: Board dimensions cannot exceed 1000mm"
        return None

    def execute(self, board: Board) -> str:
        """Execute the command."""
        self._previous_width = getattr(board, "width", None)
        self._previous_height = getattr(board, "height", None)
        board.width = self.width
        board.height = self.height
        return f"OK: Set board size to {self.width}mm x {self.height}mm"

    def undo(self, board: Board) -> str:
        """Undo the command."""
        if self._previous_width is not None and self._previous_height is not None:
            board.width = self._previous_width
            board.height = self._previous_height
            return f"OK: Restored board size to {self._previous_width}mm x {self._previous_height}mm"
        return "Undo not available"


class StatsCommand(Command):
    """Display board statistics.

    Syntax:
        STATS
        STATS ROUTING
        STATS NETS
        STATS COMPONENTS

    Shows information about the current board state including
    component count, net count, routing status, and layer usage.
    """

    def __init__(self, category: Optional[str] = None):
        """Initialize StatsCommand.

        Args:
            category: Optional category to show (routing, nets, components, or None for all)
        """
        self.category = category

    def validate(self, board: Board) -> str | None:
        """Validate command parameters."""
        if self.category and self.category.upper() not in (
            "ROUTING",
            "NETS",
            "COMPONENTS",
        ):
            return f"Error: Unknown category '{self.category}'. Use ROUTING, NETS, or COMPONENTS"
        return None

    def execute(self, board: Board) -> str:
        """Execute the command."""
        lines = []

        if self.category is None or self.category.upper() == "COMPONENTS":
            lines.append(self._component_stats(board))

        if self.category is None or self.category.upper() == "NETS":
            lines.append(self._net_stats(board))

        if self.category is None or self.category.upper() == "ROUTING":
            lines.append(self._routing_stats(board))

        return "\n".join(lines)

    def _component_stats(self, board: Board) -> str:
        """Get component statistics."""
        comp_count = len(board.components)
        smd_count = sum(
            1
            for c in board.components.values()
            if c.pads and all(p.drill is None for p in c.pads)
        )
        tht_count = sum(
            1
            for c in board.components.values()
            if c.pads and any(p.drill is not None for p in c.pads)
        )
        total_pads = sum(len(c.pads) for c in board.components.values())

        return f"""Components: {comp_count}
  SMD: {smd_count}
  THT: {tht_count}
  Total pads: {total_pads}"""

    def _net_stats(self, board: Board) -> str:
        """Get net statistics."""
        net_count = len(board.nets)
        routed = sum(1 for n in board.nets.values() if n.segments)
        unrouted = net_count - routed
        total_connections = sum(len(n.connections) for n in board.nets.values())

        # Net class breakdown
        class_counts = {}
        for net in board.nets.values():
            cls = net.net_class or "Default"
            class_counts[cls] = class_counts.get(cls, 0) + 1

        class_str = ", ".join(f"{k}:{v}" for k, v in sorted(class_counts.items()))

        return f"""Nets: {net_count}
  Routed: {routed}
  Unrouted: {unrouted}
  Total connections: {total_connections}
  By class: {class_str}"""

    def _routing_stats(self, board: Board) -> str:
        """Get routing statistics."""
        total_segments = sum(len(n.segments) for n in board.nets.values())
        total_vias = sum(len(n.vias) for n in board.nets.values())

        # Calculate total trace length
        total_length = 0.0
        for net in board.nets.values():
            for seg in net.segments:
                dx = seg.end[0] - seg.start[0]
                dy = seg.end[1] - seg.start[1]
                total_length += (dx**2 + dy**2) ** 0.5

        # Layer usage
        layer_segments = {}
        for net in board.nets.values():
            for seg in net.segments:
                layer_segments[seg.layer] = layer_segments.get(seg.layer, 0) + 1

        layer_str = ", ".join(f"{k}:{v}" for k, v in sorted(layer_segments.items()))

        return f"""Routing:
  Segments: {total_segments}
  Vias: {total_vias}
  Total length: {total_length:.1f}mm
  Layers: {board.layers}
  Layer usage: {layer_str or 'None'}"""

    def undo(self, board: Board) -> str:
        """Stats command has no undo."""
        return "Stats command does not modify board"


class CreateNetCommand(Command):
    """Create a new net with connections.

    Syntax:
        CREATE NET <name> <ref.pin> <ref.pin> [<ref.pin>...]
        CREATE NET <name> CLASS <class_name> <ref.pin> <ref.pin> [<ref.pin>...]

    Examples:
        CREATE NET VCC U1.8 C1.1 C2.1
        CREATE NET GND CLASS Power U1.16 C1.2 C2.2
        CREATE NET SIG1 U1.1 J1.2
    """

    def __init__(
        self,
        name: str,
        connections: List[Tuple[str, str]],
        net_class: Optional[str] = None,
    ):
        """Initialize CreateNetCommand.

        Args:
            name: Net name
            connections: List of (component_ref, pin) tuples
            net_class: Optional net class name
        """
        self.name = name
        self.connections = connections
        self.net_class = net_class

    def validate(self, board: Board) -> str | None:
        """Validate command parameters."""
        if not self.name:
            return "Error: Net name cannot be empty"

        if self.name in board.nets:
            return f"Error: Net '{self.name}' already exists"

        if len(self.connections) < 2:
            return "Error: Net must have at least 2 connections"

        # Validate all connections reference existing components
        for ref, pin in self.connections:
            if ref not in board.components:
                return f"Error: Component '{ref}' not found"
            # Optionally validate pin exists on component
            comp = board.components[ref]
            if comp.pads:
                pin_str = str(pin)
                if not any(str(p.number) == pin_str for p in comp.pads):
                    return f"Error: Pin {pin_str} not found on component '{ref}'"

        return None

    def execute(self, board: Board) -> str:
        """Execute the command."""
        # Determine track width from net class if specified
        track_width = 0.25  # Default
        if self.net_class and self.net_class in board.net_classes:
            track_width = board.net_classes[self.net_class].track_width

        # Create net
        net_code = str(len(board.nets) + 1)
        net = Net(
            name=self.name,
            code=net_code,
            track_width=track_width,
            net_class=self.net_class,
        )

        # Add connections
        for ref, pin in self.connections:
            net.add_connection(ref, str(pin))

        board.add_net(net)

        # Add to net class if specified
        if self.net_class and self.net_class in board.net_classes:
            board.net_classes[self.net_class].nets.append(self.name)

        conn_str = ", ".join(f"{ref}.{pin}" for ref, pin in self.connections)
        return f"OK: Created net '{self.name}' with {len(self.connections)} connections: {conn_str}"

    def undo(self, board: Board) -> str:
        """Undo the command."""
        if self.name in board.nets:
            del board.nets[self.name]
            # Remove from net class
            if self.net_class and self.net_class in board.net_classes:
                nets = board.net_classes[self.net_class].nets
                if self.name in nets:
                    nets.remove(self.name)
            return f"OK: Removed net '{self.name}'"
        return "Undo not available"


class CreateComponentCommand(Command):
    """Create a new component with automatic pad generation.

    Syntax:
        CREATE COMPONENT <ref> <footprint> <x> <y> [ROTATION <degrees>] [VALUE <value>]

    Examples:
        CREATE COMPONENT U1 TQFP-32 20 20
        CREATE COMPONENT R1 0603 10 15 VALUE 10k
        CREATE COMPONENT C1 0805 12 20 ROTATION 90 VALUE 100nF
    """

    def __init__(
        self,
        ref: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float = 0,
        value: str = "",
    ):
        """Initialize CreateComponentCommand.

        Args:
            ref: Reference designator
            footprint: Footprint name (full or shorthand)
            x: X position in mm
            y: Y position in mm
            rotation: Rotation in degrees
            value: Component value
        """
        self.ref = ref
        self.footprint = footprint
        self.x = x
        self.y = y
        self.rotation = rotation
        self.value = value

    def validate(self, board: Board) -> str | None:
        """Validate command parameters."""
        if not self.ref:
            return "Error: Reference designator cannot be empty"

        if self.ref in board.components:
            return f"Error: Component '{self.ref}' already exists"

        if not self.footprint:
            return "Error: Footprint cannot be empty"

        if not (0 <= self.rotation < 360):
            return f"Error: Rotation must be 0-359, got {self.rotation}"

        return None

    def execute(self, board: Board) -> str:
        """Execute the command."""
        # Try to generate pads from template
        pads = []
        try:
            pads = generate_pads(self.footprint)
        except ValueError:
            # Footprint not in templates - component will have no pads
            pass

        comp = Component(
            ref=self.ref,
            value=self.value or self.footprint,
            footprint=self.footprint,
            position=(self.x, self.y),
            rotation=self.rotation,
            layer="F.Cu",
            pads=pads,
        )

        board.add_component(comp)

        pad_info = f" ({len(pads)} pads)" if pads else " (no pads - unknown footprint)"
        return f"OK: Created component '{self.ref}' at ({self.x}, {self.y}){pad_info}"

    def undo(self, board: Board) -> str:
        """Undo the command."""
        if self.ref in board.components:
            del board.components[self.ref]
            return f"OK: Removed component '{self.ref}'"
        return "Undo not available"


class AutoRouteStrategyCommand(Command):
    """Route the board using a pre-configured strategy.

    Syntax:
        AUTOROUTE STRATEGY <strategy_name>
        AUTOROUTE STRATEGY AUTO

    Available strategies:
        - simple / 2layer: Basic 2-layer routing
        - ground_plane / 2layer_ground: 2-layer with GND plane on B.Cu
        - fpga / 4layer_fpga: 4-layer optimized for FPGA/MCU
        - mixed / 4layer: 4-layer balanced
        - auto: Automatically select best strategy

    Examples:
        AUTOROUTE STRATEGY fpga
        AUTOROUTE STRATEGY ground_plane
        AUTOROUTE STRATEGY auto
    """

    def __init__(self, strategy_name: str):
        """Initialize AutoRouteStrategyCommand.

        Args:
            strategy_name: Name of routing strategy or "auto"
        """
        self.strategy_name = strategy_name
        self.added_segments = []
        self.added_vias = []

    def validate(self, board: Board) -> str | None:
        """Validate command parameters."""
        from pardal.routing_strategies import STRATEGIES, auto_select_strategy

        if not self.strategy_name:
            return "Error: Strategy name required"

        if self.strategy_name.lower() != "auto":
            name_lower = self.strategy_name.lower().replace("-", "_").replace(" ", "_")
            if name_lower not in STRATEGIES:
                available = ", ".join(STRATEGIES.keys())
                return f"Error: Unknown strategy '{self.strategy_name}'. Available: {available}"

        if not board.nets:
            return "Error: No nets to route"

        return None

    def execute(self, board: Board) -> str:
        """Execute the command."""
        from pardal.routing_strategies import route_board, auto_select_strategy

        # Auto-select if requested
        strategy = self.strategy_name
        if strategy.lower() == "auto":
            strategy = auto_select_strategy(board)
            print(f"Auto-selected strategy: {strategy}")

        # Route using strategy
        result = route_board(board, strategy)

        # Build result message
        lines = [
            f"Strategy: {strategy}",
            f"Nets routed: {result.nets_routed}/{result.nets_total}",
            f"Total length: {result.total_length_mm:.1f}mm",
            f"Vias: {result.total_vias}",
            f"Layers used: {', '.join(sorted(result.layers_used)) or 'None'}",
        ]

        if result.success:
            lines.insert(0, "OK: Routing complete!")
        else:
            lines.insert(
                0,
                f"Warning: {result.nets_total - result.nets_routed} nets failed to route",
            )

        return "\n".join(lines)

    def undo(self, board: Board) -> str:
        """Undo routing - removes all segments and vias."""
        removed_segments = 0
        removed_vias = 0

        for net in board.nets.values():
            removed_segments += len(net.segments)
            removed_vias += len(net.vias)
            net.segments.clear()
            net.vias.clear()

        return f"OK: Removed {removed_segments} segments and {removed_vias} vias"
