"""
PCB Tool Data Model

Core data structures for representing PCB boards, components, and nets.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import math


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

        if self.layer not in ("F.Cu", "B.Cu"):
            raise ValueError(f"TraceSegment layer must be F.Cu or B.Cu, got {self.layer}")


@dataclass
class Via:
    """Represents a via connecting copper layers on a PCB.

    A via is a plated through-hole that electrically connects traces on different layers.
    It consists of a drilled hole with plated walls and pads on the connected layers.

    Attributes:
        net_name: Name of the net this via belongs to (e.g., "GND", "VCC")
        position: Position as (x, y) tuple in millimeters
        size: Outer diameter of the via pad in millimeters, must be positive
        drill: Drill hole diameter in millimeters, must be positive and smaller than size
        layers: Tuple of two layer names this via connects (e.g., ("F.Cu", "B.Cu"))

    Example:
        >>> via = Via(
        ...     net_name="GND",
        ...     position=(50.0, 60.0),
        ...     size=0.8,
        ...     drill=0.4,
        ...     layers=("F.Cu", "B.Cu")
        ... )
    """

    net_name: str
    position: tuple[float, float]
    size: float
    drill: float
    layers: tuple[str, str]

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
    """Represents a PCB board containing components and nets."""

    components: dict[str, Component] = field(default_factory=dict)
    nets: dict[str, Net] = field(default_factory=dict)
    zones: list[CopperZone] = field(default_factory=list)
    source_file: Optional[Path] = None

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
