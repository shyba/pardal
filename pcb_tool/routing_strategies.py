"""
Routing Strategies - Pre-configured routing patterns for common board types.

Provides high-level routing strategies that handle the complexity of
layer assignments, via costs, and net ordering automatically.

Strategies:
- two_layer_ground_plane: Classic 2-layer with B.Cu ground pour
- four_layer_fpga: 4-layer for dense FPGA/MCU designs
- four_layer_mixed: 4-layer with balanced signal/power distribution
- two_layer_simple: Basic 2-layer routing

Example:
    from pcb_tool.routing_strategies import route_board, FourLayerFPGA

    # Using strategy class
    strategy = FourLayerFPGA()
    result = strategy.route(board)

    # Using convenience function
    result = route_board(board, "fpga")
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from pcb_tool.data_model import Board
from pcb_tool.commands.routing import AutoRouteCommand


@dataclass
class RoutingResult:
    """Result of a routing operation.

    Attributes:
        success: Whether all nets were routed
        nets_routed: Number of successfully routed nets
        nets_total: Total nets attempted
        total_length_mm: Total trace length in mm
        total_vias: Number of vias placed
        layers_used: Set of layers that have traces
        message: Detailed result message
    """

    success: bool
    nets_routed: int
    nets_total: int
    total_length_mm: float
    total_vias: int
    layers_used: set = field(default_factory=set)
    message: str = ""


class RoutingStrategy(ABC):
    """Base class for routing strategies.

    Subclasses implement specific routing patterns for different
    board types (2-layer, 4-layer, ground plane, etc.).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for display."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Brief description of the strategy."""
        pass

    @abstractmethod
    def route(self, board: Board) -> RoutingResult:
        """Route the board using this strategy.

        Args:
            board: Board to route

        Returns:
            RoutingResult with statistics
        """
        pass

    def _collect_stats(
        self, board: Board, nets_attempted: List[str]
    ) -> Tuple[int, float, int, set]:
        """Collect routing statistics from board.

        Args:
            board: Board with routing applied
            nets_attempted: List of net names that were attempted

        Returns:
            Tuple of (nets_routed, total_length_mm, total_vias, layers_used)
        """
        nets_routed = 0
        total_length = 0.0
        total_vias = 0
        layers_used = set()

        for net_name in nets_attempted:
            net = board.nets.get(net_name)
            if net and len(net.segments) > 0:
                nets_routed += 1
                total_vias += len(net.vias)
                for seg in net.segments:
                    layers_used.add(seg.layer)
                    # Calculate segment length
                    dx = seg.end[0] - seg.start[0]
                    dy = seg.end[1] - seg.start[1]
                    total_length += (dx**2 + dy**2) ** 0.5

        return nets_routed, total_length, total_vias, layers_used


class TwoLayerGroundPlane(RoutingStrategy):
    """2-layer board with bottom copper ground pour.

    Strategy:
    - Route all signals on F.Cu (top layer)
    - Use B.Cu for GND plane (copper pour)
    - Minimize vias to preserve ground plane integrity

    Best for:
    - Simple analog circuits
    - Audio equipment
    - Low-frequency designs
    """

    @property
    def name(self) -> str:
        return "Two-Layer Ground Plane"

    @property
    def description(self) -> str:
        return "Signals on F.Cu, GND plane on B.Cu"

    def route(self, board: Board) -> RoutingResult:
        """Route using ground plane strategy."""
        # Get nets to route
        nets_to_route = [
            name for name, net in board.nets.items() if len(net.connections) >= 2
        ]

        # Route with ground plane mode enabled
        cmd = AutoRouteCommand(
            net_name="ALL",
            prefer_layer="F.Cu",
            ground_plane_mode=True,
            via_costs={"*": 5.0},  # High via cost to stay on F.Cu
        )
        result_msg = cmd.execute(board)

        # Collect stats
        routed, length, vias, layers = self._collect_stats(board, nets_to_route)

        return RoutingResult(
            success=routed == len(nets_to_route),
            nets_routed=routed,
            nets_total=len(nets_to_route),
            total_length_mm=length,
            total_vias=vias,
            layers_used=layers,
            message=result_msg,
        )


class TwoLayerSimple(RoutingStrategy):
    """Basic 2-layer routing with balanced layer usage.

    Strategy:
    - Distribute signals evenly between F.Cu and B.Cu
    - Use standard via costs
    - No special layer assignments

    Best for:
    - Simple digital circuits
    - Hobbyist projects
    - Low-density designs
    """

    @property
    def name(self) -> str:
        return "Two-Layer Simple"

    @property
    def description(self) -> str:
        return "Balanced routing on both layers"

    def route(self, board: Board) -> RoutingResult:
        """Route with balanced layer usage."""
        nets_to_route = [
            name for name, net in board.nets.items() if len(net.connections) >= 2
        ]

        cmd = AutoRouteCommand(
            net_name="ALL", via_costs={"*": 3.0}  # Moderate via cost
        )
        result_msg = cmd.execute(board)

        routed, length, vias, layers = self._collect_stats(board, nets_to_route)

        return RoutingResult(
            success=routed == len(nets_to_route),
            nets_routed=routed,
            nets_total=len(nets_to_route),
            total_length_mm=length,
            total_vias=vias,
            layers_used=layers,
            message=result_msg,
        )


class FourLayerFPGA(RoutingStrategy):
    """4-layer board optimized for FPGA/MCU designs.

    Strategy:
    - VCC on F.Cu (top)
    - Signals on In1.Cu and In2.Cu (inner layers)
    - GND on B.Cu (bottom)
    - Low via costs to encourage layer switching
    - Route power nets first

    Best for:
    - FPGA development boards
    - MCU boards with many I/O
    - High-density digital designs
    """

    def __init__(
        self,
        power_nets: Optional[List[str]] = None,
        ground_nets: Optional[List[str]] = None,
        net_layer_overrides: Optional[Dict[str, str]] = None,
        net_via_costs: Optional[Dict[str, float]] = None,
        verbose: bool = False,
    ):
        """Initialize FPGA strategy.

        Args:
            power_nets: Net names for power (default: ["VCC", "3V3", "5V", "VCCIO"])
            ground_nets: Net names for ground (default: ["GND", "VSS", "GNDA"])
            net_layer_overrides: Optional per-net preferred layer overrides.
            net_via_costs: Optional mapping of net name patterns to via costs (mm-equivalent).
                Use {"*": 2.0} to set a global via cost.
            verbose: If True, print progress during routing.
        """
        self.power_nets = power_nets or ["VCC", "3V3", "5V", "VCCIO", "VDD"]
        self.ground_nets = ground_nets or ["GND", "VSS", "GNDA", "GNDPWR"]
        self.net_layer_overrides = net_layer_overrides or {}
        self.net_via_costs = net_via_costs or {"*": 2.0}
        self.verbose = bool(verbose)

    @property
    def name(self) -> str:
        return "Four-Layer FPGA"

    @property
    def description(self) -> str:
        return "VCC on F.Cu, signals on inner layers, GND on B.Cu"

    def _classify_nets(self, board: Board) -> Tuple[List[str], List[str], List[str]]:
        """Classify nets into power, ground, and signal groups.

        Returns:
            Tuple of (power_net_names, ground_net_names, signal_net_names)
        """
        power = []
        ground = []
        signals = []

        for name, net in board.nets.items():
            if len(net.connections) < 2:
                continue
            name_upper = name.upper()
            if any(p.upper() in name_upper for p in self.power_nets):
                power.append(name)
            elif any(g.upper() in name_upper for g in self.ground_nets):
                ground.append(name)
            else:
                signals.append(name)

        return power, ground, signals

    def route(self, board: Board) -> RoutingResult:
        """Route FPGA board with layer assignments."""
        power, ground, signals = self._classify_nets(board)
        all_nets = power + ground + signals

        # Route power nets first on F.Cu
        for net_name in power:
            layer = self.net_layer_overrides.get(net_name, "F.Cu")
            cmd = AutoRouteCommand(
                net_name=net_name,
                prefer_layer=layer,
                via_costs=self.net_via_costs,
                verbose=self.verbose,
            )
            cmd.execute(board)

        # Route signal nets on inner layers
        for i, net_name in enumerate(signals):
            # Default alternation between In1.Cu and In2.Cu, unless overridden.
            layer = self.net_layer_overrides.get(
                net_name, ("In1.Cu" if i % 2 == 0 else "In2.Cu")
            )
            cmd = AutoRouteCommand(
                net_name=net_name,
                prefer_layer=layer,
                via_costs=self.net_via_costs,
                verbose=self.verbose,
            )
            cmd.execute(board)

        # Route ground nets on B.Cu
        for net_name in ground:
            layer = self.net_layer_overrides.get(net_name, "B.Cu")
            cmd = AutoRouteCommand(
                net_name=net_name,
                prefer_layer=layer,
                via_costs=self.net_via_costs,
                verbose=self.verbose,
            )
            cmd.execute(board)

        routed, length, vias, layers = self._collect_stats(board, all_nets)

        return RoutingResult(
            success=routed == len(all_nets),
            nets_routed=routed,
            nets_total=len(all_nets),
            total_length_mm=length,
            total_vias=vias,
            layers_used=layers,
            message=f"FPGA strategy: {len(power)} power, {len(signals)} signal, {len(ground)} ground nets",
        )


class FourLayerMixed(RoutingStrategy):
    """4-layer board with balanced signal/power distribution.

    Strategy:
    - F.Cu: Horizontal signals + power traces
    - In1.Cu: Vertical signals
    - In2.Cu: Power plane (unrouted, for copper pour)
    - B.Cu: Horizontal signals + ground traces

    Best for:
    - Mixed-signal designs
    - Medium-density boards
    - Designs requiring EMI control
    """

    @property
    def name(self) -> str:
        return "Four-Layer Mixed"

    @property
    def description(self) -> str:
        return "Balanced signal/power distribution across all layers"

    def route(self, board: Board) -> RoutingResult:
        """Route with mixed layer strategy."""
        nets_to_route = [
            name for name, net in board.nets.items() if len(net.connections) >= 2
        ]

        # Balanced usage: moderate global via cost.
        cmd = AutoRouteCommand(net_name="ALL", via_costs={"*": 3.0})
        result_msg = cmd.execute(board)

        routed, length, vias, layers = self._collect_stats(board, nets_to_route)

        return RoutingResult(
            success=routed == len(nets_to_route),
            nets_routed=routed,
            nets_total=len(nets_to_route),
            total_length_mm=length,
            total_vias=vias,
            layers_used=layers,
            message=result_msg,
        )


# Strategy registry for lookup by name
STRATEGIES: Dict[str, type] = {
    "ground_plane": TwoLayerGroundPlane,
    "2layer_ground": TwoLayerGroundPlane,
    "simple": TwoLayerSimple,
    "2layer": TwoLayerSimple,
    "fpga": FourLayerFPGA,
    "4layer_fpga": FourLayerFPGA,
    "mixed": FourLayerMixed,
    "4layer": FourLayerMixed,
}


def get_strategy(name: str) -> RoutingStrategy:
    """Get a routing strategy by name.

    Args:
        name: Strategy name (see STRATEGIES for options)

    Returns:
        RoutingStrategy instance

    Raises:
        ValueError: If strategy name not found

    Example:
        >>> strategy = get_strategy("fpga")
        >>> result = strategy.route(board)
    """
    name_lower = name.lower().replace("-", "_").replace(" ", "_")
    if name_lower not in STRATEGIES:
        available = ", ".join(STRATEGIES.keys())
        raise ValueError(f"Unknown strategy: {name}. Available: {available}")

    return STRATEGIES[name_lower]()


def route_board(board: Board, strategy: str = "simple") -> RoutingResult:
    """Route a board using a named strategy.

    Convenience function that combines strategy lookup and routing.

    Args:
        board: Board to route
        strategy: Strategy name (default "simple")
            - "simple" / "2layer": Basic 2-layer routing
            - "ground_plane" / "2layer_ground": 2-layer with GND plane
            - "fpga" / "4layer_fpga": 4-layer FPGA optimized
            - "mixed" / "4layer": 4-layer balanced

    Returns:
        RoutingResult with statistics

    Example:
        >>> from pcb_tool.routing_strategies import route_board
        >>> result = route_board(board, "fpga")
        >>> print(f"Routed {result.nets_routed}/{result.nets_total} nets")
    """
    strat = get_strategy(strategy)
    return strat.route(board)


def list_strategies() -> Dict[str, str]:
    """List available routing strategies.

    Returns:
        Dictionary mapping strategy name to description

    Example:
        >>> for name, desc in list_strategies().items():
        ...     print(f"{name}: {desc}")
    """
    result = {}
    seen = set()
    for name, cls in STRATEGIES.items():
        if cls not in seen:
            instance = cls()
            result[name] = instance.description
            seen.add(cls)
    return result


def auto_select_strategy(board: Board) -> str:
    """Automatically select the best strategy for a board.

    Selects strategy based on:
    - Layer count
    - Number of nets
    - Presence of power/ground nets

    Args:
        board: Board to analyze

    Returns:
        Strategy name string

    Example:
        >>> strategy_name = auto_select_strategy(board)
        >>> result = route_board(board, strategy_name)
    """
    layer_count = board.layer_count

    if layer_count >= 4:
        # Check if this looks like an FPGA board
        has_power_class = "Power" in board.net_classes
        has_many_nets = len(board.nets) > 10
        if has_power_class or has_many_nets:
            return "fpga"
        return "mixed"

    # 2-layer board
    # Check for GND net that would benefit from ground plane
    has_gnd = any(n.upper() in ("GND", "VSS") for n in board.nets.keys())
    many_gnd_connections = False
    for name, net in board.nets.items():
        if name.upper() in ("GND", "VSS") and len(net.connections) > 5:
            many_gnd_connections = True
            break

    if has_gnd and many_gnd_connections:
        return "ground_plane"

    return "simple"
