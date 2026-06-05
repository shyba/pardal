"""
Board Builder - Fluent API for creating PCB boards.

Simplifies board creation by providing a chainable builder pattern
that auto-generates pads from footprint templates.

Example:
    board = (BoardBuilder(layers=4, width=40, height=40)
        .net_class("Power", track_width=0.5, clearance=0.25)
        .net_class("Signal", track_width=0.2, clearance=0.2)
        .component("U1", "TQFP-32", (20, 20))
        .component("C1", "0603", (12, 20))
        .net("VCC", "Power", [("U1", "8"), ("C1", "1")])
        .net("GND", "Power", [("U1", "16"), ("C1", "2")])
        .build())
"""

from typing import List, Tuple, Optional, Union
from pardal.data_model import (
    Board,
    Component,
    Net,
    NetClass,
    Pad,
    STANDARD_LAYER_STACKS,
)
from pardal.footprint_templates import generate_pads, get_template, FOOTPRINT_ALIASES


class BoardBuilder:
    """Fluent builder for creating PCB boards.

    Provides a chainable API that simplifies board creation:
    - Automatic pad generation from footprint templates
    - Shorthand footprint names (e.g., "0603" instead of "R_0603_1608Metric")
    - Type-safe net class assignment
    - Automatic net code generation

    Attributes:
        _board: The board being built
        _net_code_counter: Counter for generating net codes
    """

    def __init__(self, layers: int = 2, width: float = 100.0, height: float = 100.0):
        """Initialize a new board builder.

        Args:
            layers: Number of copper layers (2, 4, 6, or 8)
            width: Board width in mm
            height: Board height in mm

        Raises:
            ValueError: If layer count is not supported
        """
        if layers not in STANDARD_LAYER_STACKS:
            raise ValueError(f"Unsupported layer count: {layers}. Use 2, 4, 6, or 8")

        self._board = Board(layers=STANDARD_LAYER_STACKS[layers])
        self._board.width = width
        self._board.height = height
        self._net_code_counter = 1

    def net_class(
        self,
        name: str,
        track_width: float = 0.25,
        clearance: float = 0.2,
        via_size: float = 0.8,
        via_drill: float = 0.4,
    ) -> "BoardBuilder":
        """Add a net class with routing rules.

        Args:
            name: Class name (e.g., "Power", "Signal", "HighSpeed")
            track_width: Trace width in mm
            clearance: Clearance from other copper in mm
            via_size: Via outer diameter in mm
            via_drill: Via drill diameter in mm

        Returns:
            Self for chaining

        Example:
            >>> builder.net_class("Power", track_width=0.5, clearance=0.3)
        """
        self._board.net_classes[name] = NetClass(
            name=name,
            track_width=track_width,
            clearance=clearance,
            via_size=via_size,
            via_drill=via_drill,
        )
        return self

    def component(
        self,
        ref: str,
        footprint: str,
        position: Tuple[float, float],
        value: str = "",
        rotation: float = 0,
        layer: str = "F.Cu",
        pads: Optional[List[Pad]] = None,
    ) -> "BoardBuilder":
        """Add a component to the board.

        Automatically generates pads from footprint templates if not provided.
        Supports shorthand footprint names like "0603", "TQFP-32".

        Args:
            ref: Reference designator (e.g., "U1", "R1", "C1")
            footprint: Footprint name (full or shorthand)
            position: (x, y) position in mm
            value: Component value (e.g., "10k", "100nF")
            rotation: Rotation in degrees (0-359)
            layer: Component layer ("F.Cu" or "B.Cu")
            pads: Optional list of pads (auto-generated if None)

        Returns:
            Self for chaining

        Example:
            >>> builder.component("U1", "TQFP-32", (20, 20))
            >>> builder.component("R1", "0603", (10, 10), value="10k")
        """
        # Resolve shorthand footprint names
        resolved_footprint = self._resolve_footprint(footprint)

        # Auto-generate pads if not provided
        if pads is None:
            try:
                pads = generate_pads(resolved_footprint)
            except ValueError:
                # Footprint not in templates, create empty pad list
                pads = []

        comp = Component(
            ref=ref,
            value=value or footprint,
            footprint=resolved_footprint,
            position=position,
            rotation=rotation,
            layer=layer,
            pads=pads,
        )
        self._board.add_component(comp)
        return self

    def net(
        self,
        name: str,
        net_class: Optional[str] = None,
        connections: Optional[List[Tuple[str, str]]] = None,
        track_width: Optional[float] = None,
    ) -> "BoardBuilder":
        """Add a net with connections.

        Args:
            name: Net name (e.g., "VCC", "GND", "SIG1")
            net_class: Optional net class name for routing rules
            connections: List of (component_ref, pin) tuples
            track_width: Optional explicit track width (overrides net class)

        Returns:
            Self for chaining

        Example:
            >>> builder.net("VCC", "Power", [("U1", "8"), ("C1", "1")])
            >>> builder.net("GND", "Power", [("U1", "16"), ("C1", "2")])
        """
        # Determine track width
        if track_width is not None:
            width = track_width
        elif net_class and net_class in self._board.net_classes:
            width = self._board.net_classes[net_class].track_width
        else:
            width = 0.25  # Default

        net = Net(
            name=name,
            code=str(self._net_code_counter),
            track_width=width,
            net_class=net_class,
        )
        self._net_code_counter += 1

        # Add connections
        if connections:
            for ref, pin in connections:
                net.add_connection(ref, str(pin))

        self._board.add_net(net)

        # Add net to net class if specified
        if net_class and net_class in self._board.net_classes:
            self._board.net_classes[net_class].nets.append(name)

        return self

    def connect(self, net_name: str, ref: str, pin: Union[str, int]) -> "BoardBuilder":
        """Add a connection to an existing net.

        Args:
            net_name: Name of the net to add connection to
            ref: Component reference
            pin: Pin number or name

        Returns:
            Self for chaining

        Raises:
            ValueError: If net doesn't exist

        Example:
            >>> builder.connect("VCC", "C2", "1")
        """
        if net_name not in self._board.nets:
            raise ValueError(f"Net not found: {net_name}")

        self._board.nets[net_name].add_connection(ref, str(pin))
        return self

    def build(self) -> Board:
        """Build and return the completed board.

        Returns:
            The constructed Board object
        """
        return self._board

    def _resolve_footprint(self, footprint: str) -> str:
        """Resolve shorthand footprint names to full names.

        Supports multiple shorthand formats:
        - "0603" -> "R_0603_1608Metric" or "C_0603_1608Metric"
        - "R_0603" -> "R_0603_1608Metric"
        - "TQFP-32" -> "TQFP-32_7x7mm_P0.8mm"

        Args:
            footprint: Footprint name (full or shorthand)

        Returns:
            Full footprint name
        """
        # Check direct alias match
        if footprint in FOOTPRINT_ALIASES:
            return FOOTPRINT_ALIASES[footprint]

        # Check if it's already a full name
        if get_template(footprint):
            return footprint

        # Try common prefixes for bare size codes
        if footprint in ("0402", "0603", "0805", "1206"):
            # Default to resistor pattern
            return FOOTPRINT_ALIASES.get(f"R_{footprint}", footprint)

        return footprint


# Convenience functions for quick board creation


def quick_board(
    layers: int = 2, width: float = 100.0, height: float = 100.0
) -> BoardBuilder:
    """Create a new board builder with sensible defaults.

    Args:
        layers: Number of copper layers
        width: Board width in mm
        height: Board height in mm

    Returns:
        BoardBuilder instance

    Example:
        >>> board = quick_board(4, 50, 50).component("U1", "TQFP-32", (25, 25)).build()
    """
    return BoardBuilder(layers=layers, width=width, height=height)


def fpga_board(
    layers: int = 4,
    width: float = 40.0,
    height: float = 40.0,
    power_width: float = 0.5,
    signal_width: float = 0.2,
) -> BoardBuilder:
    """Create a board builder pre-configured for FPGA designs.

    Sets up Power and Signal net classes with appropriate widths.

    Args:
        layers: Number of copper layers (default 4)
        width: Board width in mm
        height: Board height in mm
        power_width: Track width for power nets in mm
        signal_width: Track width for signal nets in mm

    Returns:
        BoardBuilder with Power and Signal net classes configured

    Example:
        >>> board = (fpga_board()
        ...     .component("U1", "TQFP-32", (20, 20))
        ...     .component("C1", "0603", (12, 20))
        ...     .net("VCC", "Power", [("U1", "8"), ("C1", "1")])
        ...     .build())
    """
    return (
        BoardBuilder(layers=layers, width=width, height=height)
        .net_class(
            "Power",
            track_width=power_width,
            clearance=0.25,
            via_size=0.8,
            via_drill=0.4,
        )
        .net_class(
            "Signal",
            track_width=signal_width,
            clearance=0.2,
            via_size=0.6,
            via_drill=0.3,
        )
    )


def simple_board(
    layers: int = 2,
    width: float = 50.0,
    height: float = 50.0,
    track_width: float = 0.25,
) -> BoardBuilder:
    """Create a simple board with default net class.

    Args:
        layers: Number of copper layers
        width: Board width in mm
        height: Board height in mm
        track_width: Default track width in mm

    Returns:
        BoardBuilder with Default net class configured

    Example:
        >>> board = simple_board().component("R1", "0603", (10, 10)).build()
    """
    return BoardBuilder(layers=layers, width=width, height=height).net_class(
        "Default", track_width=track_width, clearance=0.2
    )
