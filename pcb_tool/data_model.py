"""
PCB Tool Data Model

Core data structures for representing PCB boards, components, and nets.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import math


# Standard layer stacks for common board configurations
STANDARD_LAYER_STACKS = {
    2: ["F.Cu", "B.Cu"],
    4: ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
    6: ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "B.Cu"],
    8: ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu", "In5.Cu", "In6.Cu", "B.Cu"],
}

# All valid copper layer names
VALID_COPPER_LAYERS = {
    "F.Cu", "B.Cu",
    "In1.Cu", "In2.Cu", "In3.Cu", "In4.Cu",
    "In5.Cu", "In6.Cu", "In7.Cu", "In8.Cu",
    "In9.Cu", "In10.Cu", "In11.Cu", "In12.Cu",
    "In13.Cu", "In14.Cu", "In15.Cu", "In16.Cu",
    "In17.Cu", "In18.Cu", "In19.Cu", "In20.Cu",
    "In21.Cu", "In22.Cu", "In23.Cu", "In24.Cu",
    "In25.Cu", "In26.Cu", "In27.Cu", "In28.Cu",
    "In29.Cu", "In30.Cu",
}


@dataclass
class LayerConfig:
    """Configuration for a single board layer.

    Attributes:
        name: Layer name (e.g., "F.Cu", "In1.Cu", "B.Cu")
        layer_type: Type of layer - "signal" or "power"
        index: Layer index in the stack (0 = top, higher = deeper)
    """
    name: str
    layer_type: str = "signal"  # "signal" or "power"
    index: int = 0

    def __post_init__(self):
        if self.name not in VALID_COPPER_LAYERS:
            raise ValueError(f"Invalid layer name: {self.name}")
        if self.layer_type not in ("signal", "power"):
            raise ValueError(f"Layer type must be 'signal' or 'power', got {self.layer_type}")


@dataclass
class NetClass:
    """Routing rules for a group of nets.

    Net classes define default routing parameters (trace width, clearance, via size)
    that apply to all nets assigned to the class.

    Attributes:
        name: Class name (e.g., "Default", "Power", "Signal")
        track_width: Default trace width in millimeters
        clearance: Minimum clearance from other copper in millimeters
        via_size: Via outer diameter in millimeters
        via_drill: Via drill hole diameter in millimeters
        nets: List of net names belonging to this class
    """
    name: str
    track_width: float = 0.25
    clearance: float = 0.2
    via_size: float = 0.8
    via_drill: float = 0.4
    nets: list[str] = field(default_factory=list)

    def __post_init__(self):
        if self.track_width <= 0:
            raise ValueError(f"track_width must be positive, got {self.track_width}")
        if self.clearance < 0:
            raise ValueError(f"clearance must be non-negative, got {self.clearance}")
        if self.via_size <= 0:
            raise ValueError(f"via_size must be positive, got {self.via_size}")
        if self.via_drill <= 0:
            raise ValueError(f"via_drill must be positive, got {self.via_drill}")
        if self.via_drill >= self.via_size:
            raise ValueError(f"via_drill must be smaller than via_size")


@dataclass
class Pad:
    """Represents a component pad with position and properties."""

    number: int  # Pin/pad number
    position_offset: tuple[float, float]  # Offset from component center (x, y) in mm
    size: tuple[float, float]  # Pad size (width, height) in mm
    drill: Optional[float] = None  # Drill diameter in mm (None for SMD)
    shape: str = "circle"  # "circle", "rect", "oval"
    net_name: str = ""  # Net this pad connects to

    @property
    def is_tht(self) -> bool:
        """Check if this is a through-hole pad."""
        return self.drill is not None

    @property
    def is_smd(self) -> bool:
        """Check if this is an SMD pad."""
        return self.drill is None


@dataclass
class Component:
    """Represents a PCB component with position and properties."""

    ref: str
    value: str
    footprint: str
    position: tuple[float, float]
    rotation: float
    locked: bool = False
    layer: str = "F.Cu"
    pins: list[str] = field(default_factory=list)
    pads: list[Pad] = field(default_factory=list)

    def __post_init__(self):
        """Validate component data after initialization.

        Raises:
            ValueError: If any field contains invalid data
        """
        # Validate ref
        if not self.ref or not isinstance(self.ref, str):
            raise ValueError("Component ref must be non-empty string")

        # Validate rotation
        if not isinstance(self.rotation, (int, float)):
            raise ValueError(f"Rotation must be numeric, got {type(self.rotation).__name__}")
        if not (0 <= self.rotation < 360):
            raise ValueError(f"Rotation must be in [0, 360), got {self.rotation}")

        # Validate position
        if not isinstance(self.position, tuple) or len(self.position) != 2:
            raise ValueError(f"Position must be tuple of 2 elements, got {self.position}")
        try:
            float(self.position[0])
            float(self.position[1])
        except (TypeError, ValueError):
            raise ValueError(f"Position coordinates must be numeric, got {self.position}")

        # Validate footprint
        if not self.footprint or not isinstance(self.footprint, str):
            raise ValueError("Component footprint must be non-empty string")

    def get_pad_position(self, pad_num: int) -> tuple[float, float]:
        """Get absolute position of a pad in board coordinates.

        Applies component rotation to pad offset before adding to component position.

        Args:
            pad_num: Pad number to get position for

        Returns:
            Tuple of (x, y) coordinates in mm

        Raises:
            ValueError: If pad number not found
        """
        pad = next((p for p in self.pads if p.number == pad_num), None)
        if not pad:
            raise ValueError(f"Pad {pad_num} not found on component {self.ref}")

        # Rotate pad offset by component rotation (KiCad uses clockwise rotation)
        # Negate angle for counter-clockwise math convention
        angle_rad = math.radians(-self.rotation)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        rotated_x = pad.position_offset[0] * cos_a - pad.position_offset[1] * sin_a
        rotated_y = pad.position_offset[0] * sin_a + pad.position_offset[1] * cos_a

        # Calculate absolute position from component position + rotated pad offset
        return (
            self.position[0] + rotated_x,
            self.position[1] + rotated_y
        )

    def get_pad_by_number(self, pad_num: int) -> Optional[Pad]:
        """Get pad by number.

        Args:
            pad_num: Pad number to find

        Returns:
            Pad object or None if not found
        """
        return next((p for p in self.pads if p.number == pad_num), None)

    def find_nearest_pad(self, target_pos: tuple[float, float]) -> Optional[tuple[Pad, float]]:
        """Find the nearest pad to a target position.

        Args:
            target_pos: Target (x, y) position in board coordinates

        Returns:
            Tuple of (Pad, distance) for nearest pad, or None if no pads
        """
        if not self.pads:
            return None

        nearest = None
        min_dist = float('inf')

        for pad in self.pads:
            pad_pos = self.get_pad_position(pad.number)
            dist = math.sqrt(
                (target_pos[0] - pad_pos[0]) ** 2 +
                (target_pos[1] - pad_pos[1]) ** 2
            )
            if dist < min_dist:
                min_dist = dist
                nearest = pad

        return (nearest, min_dist) if nearest else None


@dataclass
class TraceSegment:
    """Represents a routed trace segment on a PCB layer.

    A trace segment is a straight line connecting two points on a single layer,
    typically used to electrically connect component pins or other trace segments.

    Attributes:
        net_name: Name of the net this segment belongs to (e.g., "GND", "VCC")
        start: Starting position as (x, y) tuple in millimeters
        end: Ending position as (x, y) tuple in millimeters
        layer: Layer name, must be "F.Cu" (front copper) or "B.Cu" (back copper)
        width: Trace width in millimeters, must be positive

    Example:
        >>> segment = TraceSegment(
        ...     net_name="GND",
        ...     start=(10.0, 20.0),
        ...     end=(30.0, 40.0),
        ...     layer="F.Cu",
        ...     width=0.25
        ... )
    """

    net_name: str
    start: tuple[float, float]
    end: tuple[float, float]
    layer: str
    width: float

    def __post_init__(self):
        """Validate trace segment data after initialization.

        Raises:
            ValueError: If width is not positive or layer is invalid
        """
        if self.width <= 0:
            raise ValueError(f"TraceSegment width must be positive, got {self.width}")

        if self.layer not in VALID_COPPER_LAYERS:
            raise ValueError(f"TraceSegment layer must be a valid copper layer, got {self.layer}")


@dataclass
class Via:
    """Represents a via connecting copper layers on a PCB.

    A via is a plated through-hole that electrically connects traces on different layers.
    It consists of a drilled hole with plated walls and pads on the connected layers.

    Via types:
        - "through": Connects all layers (F.Cu through B.Cu)
        - "blind": Connects an outer layer to an inner layer (doesn't go through entire board)
        - "buried": Connects only inner layers (not visible on outer layers)

    Attributes:
        net_name: Name of the net this via belongs to (e.g., "GND", "VCC")
        position: Position as (x, y) tuple in millimeters
        size: Outer diameter of the via pad in millimeters, must be positive
        drill: Drill hole diameter in millimeters, must be positive and smaller than size
        layers: Tuple of layer names this via connects (variable length)
        via_type: Type of via - "through", "blind", or "buried"

    Example:
        >>> # Through-hole via (2-layer board)
        >>> via = Via(
        ...     net_name="GND",
        ...     position=(50.0, 60.0),
        ...     size=0.8,
        ...     drill=0.4,
        ...     layers=("F.Cu", "B.Cu")
        ... )
        >>> # Blind via (4-layer board, top to first inner)
        >>> blind_via = Via(
        ...     net_name="VCC",
        ...     position=(30.0, 40.0),
        ...     size=0.6,
        ...     drill=0.3,
        ...     layers=("F.Cu", "In1.Cu"),
        ...     via_type="blind"
        ... )
    """

    net_name: str
    position: tuple[float, float]
    size: float
    drill: float
    layers: tuple[str, ...]  # Variable-length tuple of layer names
    via_type: str = "through"  # "through", "blind", or "buried"

    def __post_init__(self):
        """Validate via data after initialization.

        Raises:
            ValueError: If size or drill are not positive, or if drill >= size
        """
        if self.size <= 0:
            raise ValueError(f"Via size must be positive, got {self.size}")

        if self.drill <= 0:
            raise ValueError(f"Via drill must be positive, got {self.drill}")

        if self.drill >= self.size:
            raise ValueError(
                f"Via drill must be smaller than size, got drill={self.drill}, size={self.size}"
            )

        if len(self.layers) < 2:
            raise ValueError(f"Via must connect at least 2 layers, got {len(self.layers)}")

        for layer in self.layers:
            if layer not in VALID_COPPER_LAYERS:
                raise ValueError(f"Invalid via layer: {layer}")

        if self.via_type not in ("through", "blind", "buried"):
            raise ValueError(f"via_type must be 'through', 'blind', or 'buried', got {self.via_type}")

    @property
    def is_through_hole(self) -> bool:
        """Check if this is a through-hole via (connects F.Cu to B.Cu)."""
        return "F.Cu" in self.layers and "B.Cu" in self.layers

    @property
    def is_blind(self) -> bool:
        """Check if this is a blind via (connects outer to inner, but not both outer)."""
        has_fcu = "F.Cu" in self.layers
        has_bcu = "B.Cu" in self.layers
        return (has_fcu or has_bcu) and not (has_fcu and has_bcu)

    @property
    def is_buried(self) -> bool:
        """Check if this is a buried via (only inner layers, no outer layers)."""
        return "F.Cu" not in self.layers and "B.Cu" not in self.layers

    @property
    def start_layer(self) -> str:
        """Get the first (top) layer this via connects."""
        return self.layers[0]

    @property
    def end_layer(self) -> str:
        """Get the last (bottom) layer this via connects."""
        return self.layers[-1]


@dataclass
class Net:
    """Represents an electrical net connecting component pins.

    A net represents an electrical connection in the PCB design, including both
    the logical connections (which pins are connected) and physical routing
    (trace segments and vias).

    Attributes:
        name: Net name (e.g., "GND", "VCC", "/LED1")
        code: Net code for KiCad compatibility
        connections: List of (component_ref, pin) tuples
        segments: List of routed trace segments
        vias: List of vias placed for this net
        track_width: Default trace width for this net in millimeters
        via_size: Default via outer diameter in millimeters
        via_drill: Default via drill diameter in millimeters
        net_class: Name of the NetClass this net belongs to (or None for defaults)

    Example:
        >>> net = Net(name="GND", code="1")
        >>> net.add_connection("U1", "7")
        >>> segment = TraceSegment("GND", (0, 0), (10, 10), "F.Cu", 0.25)
        >>> net.add_segment(segment)
    """

    name: str
    code: str
    connections: list[tuple[str, str]] = field(default_factory=list)
    segments: list[TraceSegment] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    track_width: float = 0.25
    via_size: float = 0.8
    via_drill: float = 0.4
    net_class: Optional[str] = None  # Reference to NetClass name

    def add_connection(self, ref: str, pin: str) -> None:
        """Add a connection between a component reference and pin number.

        Args:
            ref: Component reference designator (e.g., "U1", "R1")
            pin: Pin number or name (e.g., "1", "VCC")
        """
        self.connections.append((ref, pin))

    def add_segment(self, segment: TraceSegment) -> None:
        """Add a trace segment to this net.

        Args:
            segment: TraceSegment instance to add

        Example:
            >>> net = Net("GND", "1")
            >>> seg = TraceSegment("GND", (0, 0), (10, 10), "F.Cu", 0.25)
            >>> net.add_segment(seg)
        """
        self.segments.append(segment)

    def add_via(self, via: Via) -> None:
        """Add a via to this net.

        Args:
            via: Via instance to add

        Example:
            >>> net = Net("GND", "1")
            >>> via = Via("GND", (50, 60), 0.8, 0.4, ("F.Cu", "B.Cu"))
            >>> net.add_via(via)
        """
        self.vias.append(via)

    def remove_segment(self, segment: TraceSegment) -> None:
        """Remove a trace segment from this net.

        Args:
            segment: TraceSegment instance to remove

        Raises:
            ValueError: If segment is not found in the net

        Example:
            >>> net = Net("GND", "1")
            >>> seg = TraceSegment("GND", (0, 0), (10, 10), "F.Cu", 0.25)
            >>> net.add_segment(seg)
            >>> net.remove_segment(seg)
        """
        try:
            self.segments.remove(segment)
        except ValueError:
            raise ValueError("Segment not found in net")

    def remove_via(self, via: Via) -> None:
        """Remove a via from this net.

        Args:
            via: Via instance to remove

        Raises:
            ValueError: If via is not found in the net

        Example:
            >>> net = Net("GND", "1")
            >>> via = Via("GND", (50, 60), 0.8, 0.4, ("F.Cu", "B.Cu"))
            >>> net.add_via(via)
            >>> net.remove_via(via)
        """
        try:
            self.vias.remove(via)
        except ValueError:
            raise ValueError("Via not found in net")

    def find_segment_near(self, x: float, y: float, tolerance: float = 0.5) -> Optional[TraceSegment]:
        """Find a trace segment with an endpoint near the given position.

        Searches for the first segment that has either its start or end point
        within the specified tolerance of the given coordinates.

        Args:
            x: X coordinate in millimeters
            y: Y coordinate in millimeters
            tolerance: Maximum distance in millimeters (default: 0.5mm)

        Returns:
            First matching TraceSegment, or None if no segment found

        Example:
            >>> net = Net("GND", "1")
            >>> seg = TraceSegment("GND", (10, 20), (30, 40), "F.Cu", 0.25)
            >>> net.add_segment(seg)
            >>> found = net.find_segment_near(10.1, 20.1, tolerance=0.5)
            >>> found == seg
            True
        """
        for segment in self.segments:
            # Check distance to start point
            start_x, start_y = segment.start
            dist_start = math.sqrt((x - start_x) ** 2 + (y - start_y) ** 2)
            if dist_start <= tolerance:
                return segment

            # Check distance to end point
            end_x, end_y = segment.end
            dist_end = math.sqrt((x - end_x) ** 2 + (y - end_y) ** 2)
            if dist_end <= tolerance:
                return segment

        return None

    def find_via_at(self, x: float, y: float, tolerance: float = 0.1) -> Optional[Via]:
        """Find a via at or near the given position.

        Searches for the first via whose center is within the specified
        tolerance of the given coordinates.

        Args:
            x: X coordinate in millimeters
            y: Y coordinate in millimeters
            tolerance: Maximum distance in millimeters (default: 0.1mm)

        Returns:
            First matching Via, or None if no via found

        Example:
            >>> net = Net("GND", "1")
            >>> via = Via("GND", (50, 60), 0.8, 0.4, ("F.Cu", "B.Cu"))
            >>> net.add_via(via)
            >>> found = net.find_via_at(50.05, 60.05, tolerance=0.1)
            >>> found == via
            True
        """
        for via in self.vias:
            via_x, via_y = via.position
            distance = math.sqrt((x - via_x) ** 2 + (y - via_y) ** 2)
            if distance <= tolerance:
                return via

        return None


@dataclass
class CopperZone:
    """Represents a copper pour/zone on a PCB layer.

    A copper zone is a filled polygon of copper typically used for ground planes
    or power distribution. Zones can have clearance from other copper features
    and use thermal reliefs for pad connections.

    Attributes:
        net_name: Name of the net this zone belongs to (e.g., "GND")
        net_code: Net code for KiCad compatibility
        layer: Layer name (e.g., "B.Cu" for bottom copper)
        outline: List of (x, y) coordinates defining the zone boundary
        priority: Zone priority (higher fills first, default 0)
        clearance: Clearance from other copper features in mm
        min_thickness: Minimum filled area width in mm
        thermal_gap: Gap width for thermal reliefs in mm
        thermal_bridge: Bridge width for thermal reliefs in mm
    """

    net_name: str
    net_code: str
    layer: str
    outline: list[tuple[float, float]]
    priority: int = 0
    clearance: float = 0.3
    min_thickness: float = 0.25
    thermal_gap: float = 0.5
    thermal_bridge: float = 0.5


@dataclass
class Board:
    """Represents a PCB board containing components and nets.

    Attributes:
        components: Dictionary of components by reference designator
        nets: Dictionary of nets by name
        zones: List of copper zones/pours
        source_file: Path to the source file (if loaded from file)
        layers: List of copper layer names in stack order (top to bottom)
        net_classes: Dictionary of net classes by name
    """

    components: dict[str, Component] = field(default_factory=dict)
    nets: dict[str, Net] = field(default_factory=dict)
    zones: list[CopperZone] = field(default_factory=list)
    source_file: Optional[Path] = None
    layers: list[str] = field(default_factory=lambda: ["F.Cu", "B.Cu"])
    net_classes: dict[str, NetClass] = field(default_factory=dict)

    def __post_init__(self):
        """Validate board configuration after initialization."""
        # Validate all layers are valid copper layers
        for layer in self.layers:
            if layer not in VALID_COPPER_LAYERS:
                raise ValueError(f"Invalid copper layer: {layer}")

        # Ensure F.Cu is first and B.Cu is last if present
        if self.layers:
            if "F.Cu" in self.layers and self.layers[0] != "F.Cu":
                raise ValueError("F.Cu must be the first layer if present")
            if "B.Cu" in self.layers and self.layers[-1] != "B.Cu":
                raise ValueError("B.Cu must be the last layer if present")

    @property
    def layer_count(self) -> int:
        """Get the number of copper layers."""
        return len(self.layers)

    def is_valid_layer(self, layer: str) -> bool:
        """Check if a layer is valid for this board.

        Args:
            layer: Layer name to check

        Returns:
            True if layer is in the board's layer stack
        """
        return layer in self.layers

    def get_layer_index(self, layer: str) -> int:
        """Get the index of a layer in the stack (0 = top).

        Args:
            layer: Layer name

        Returns:
            Index of the layer

        Raises:
            ValueError: If layer not in board's layer stack
        """
        try:
            return self.layers.index(layer)
        except ValueError:
            raise ValueError(f"Layer {layer} not in board's layer stack: {self.layers}")

    def get_adjacent_layers(self, layer: str) -> list[str]:
        """Get layers adjacent to the given layer.

        Args:
            layer: Layer name

        Returns:
            List of adjacent layer names (up to 2: above and below)
        """
        idx = self.get_layer_index(layer)
        adjacent = []
        if idx > 0:
            adjacent.append(self.layers[idx - 1])
        if idx < len(self.layers) - 1:
            adjacent.append(self.layers[idx + 1])
        return adjacent

    def get_inner_layers(self) -> list[str]:
        """Get all inner copper layers (not F.Cu or B.Cu).

        Returns:
            List of inner layer names
        """
        return [layer for layer in self.layers if layer not in ("F.Cu", "B.Cu")]

    def get_net_width(self, net_name: str) -> float:
        """Get the trace width for a net based on its class.

        Args:
            net_name: Name of the net

        Returns:
            Trace width in millimeters
        """
        net = self.nets.get(net_name)
        if net and net.net_class and net.net_class in self.net_classes:
            return self.net_classes[net.net_class].track_width
        elif net:
            return net.track_width
        return 0.25  # Default

    def get_net_clearance(self, net_name: str) -> float:
        """Get the clearance for a net based on its class.

        Args:
            net_name: Name of the net

        Returns:
            Clearance in millimeters
        """
        net = self.nets.get(net_name)
        if net and net.net_class and net.net_class in self.net_classes:
            return self.net_classes[net.net_class].clearance
        return 0.2  # Default

    def add_net_class(self, net_class: NetClass) -> None:
        """Add a net class to the board.

        Args:
            net_class: NetClass instance to add
        """
        self.net_classes[net_class.name] = net_class

    def assign_net_to_class(self, net_name: str, class_name: str) -> None:
        """Assign a net to a net class.

        Args:
            net_name: Name of the net
            class_name: Name of the net class

        Raises:
            ValueError: If net or class not found
        """
        if net_name not in self.nets:
            raise ValueError(f"Net not found: {net_name}")
        if class_name not in self.net_classes:
            raise ValueError(f"Net class not found: {class_name}")

        self.nets[net_name].net_class = class_name
        if net_name not in self.net_classes[class_name].nets:
            self.net_classes[class_name].nets.append(net_name)

    def add_component(self, comp: Component) -> None:
        """Add a component to the board.

        Args:
            comp: Component instance to add
        """
        self.components[comp.ref] = comp

    def get_component(self, ref: str) -> Optional[Component]:
        """Retrieve a component by reference designator.

        Args:
            ref: Component reference designator

        Returns:
            Component if found, None otherwise
        """
        return self.components.get(ref)

    def add_net(self, net: Net) -> None:
        """Add a net to the board.

        Args:
            net: Net instance to add
        """
        self.nets[net.name] = net
