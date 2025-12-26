"""PCB Tool Commands - Modular Command Architecture

This package contains all command classes organized by functionality:
- base: Command ABC (abstract base class)
- io: Help, Load, Save, Exit
- display: List Components/Nets, Show Board/Net/Airwires
- component: Lock, Unlock, Move, Rotate, Flip, Where, GroupMove, Arrange
- history: Undo, Redo, History
- measure: MeasureDistance, MeasureNetLength
- drc: CheckDrc, CheckAirwires, CheckClearance, CheckConnectivity
- routing: Route, Via, DeleteRoute, DeleteVia, AutoRoute, OptimizeRouting
- config: SetWidth, SetLayers, SetClearance
"""

# Base
from pcb_tool.commands.base import Command

# I/O Commands
from pcb_tool.commands.io import (
    HelpCommand,
    LoadCommand,
    SaveCommand,
    ExitCommand,
)

# Display Commands
from pcb_tool.commands.display import (
    ListComponentsCommand,
    ListNetsCommand,
    ShowBoardCommand,
    ShowNetCommand,
    ShowAirwiresCommand,
)

# Component Commands
from pcb_tool.commands.component import (
    LockCommand,
    UnlockCommand,
    MoveCommand,
    RotateCommand,
    FlipCommand,
    WhereCommand,
    GroupMoveCommand,
    ArrangeCommand,
)

# History Commands
from pcb_tool.commands.history import (
    UndoCommand,
    RedoCommand,
    HistoryCommand,
)

# Measure Commands
from pcb_tool.commands.measure import (
    MeasureDistanceCommand,
    MeasureNetLengthCommand,
)

# DRC Commands
from pcb_tool.commands.drc import (
    CheckDrcCommand,
    CheckAirwiresCommand,
    CheckClearanceCommand,
    CheckConnectivityCommand,
)

# Routing Commands
from pcb_tool.commands.routing import (
    RouteCommand,
    ViaCommand,
    DeleteRouteCommand,
    DeleteViaCommand,
    AutoRouteCommand,
    OptimizeRoutingCommand,
)

# Config Commands
from pcb_tool.commands.config import (
    SetWidthCommand,
    SetLayersCommand,
    SetClearanceCommand,
    SetBoardSizeCommand,
    StatsCommand,
    CreateNetCommand,
    CreateComponentCommand,
    AutoRouteStrategyCommand,
)

__all__ = [
    # Base
    "Command",
    # I/O
    "HelpCommand",
    "LoadCommand",
    "SaveCommand",
    "ExitCommand",
    # Display
    "ListComponentsCommand",
    "ListNetsCommand",
    "ShowBoardCommand",
    "ShowNetCommand",
    "ShowAirwiresCommand",
    # Component
    "LockCommand",
    "UnlockCommand",
    "MoveCommand",
    "RotateCommand",
    "FlipCommand",
    "WhereCommand",
    "GroupMoveCommand",
    "ArrangeCommand",
    # History
    "UndoCommand",
    "RedoCommand",
    "HistoryCommand",
    # Measure
    "MeasureDistanceCommand",
    "MeasureNetLengthCommand",
    # DRC
    "CheckDrcCommand",
    "CheckAirwiresCommand",
    "CheckClearanceCommand",
    "CheckConnectivityCommand",
    # Routing
    "RouteCommand",
    "ViaCommand",
    "DeleteRouteCommand",
    "DeleteViaCommand",
    "AutoRouteCommand",
    "OptimizeRoutingCommand",
    # Config
    "SetWidthCommand",
    "SetLayersCommand",
    "SetClearanceCommand",
    "SetBoardSizeCommand",
    "StatsCommand",
    "CreateNetCommand",
    "CreateComponentCommand",
    "AutoRouteStrategyCommand",
]
