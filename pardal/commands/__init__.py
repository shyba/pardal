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
from pardal.commands.base import Command

# I/O Commands
from pardal.commands.io import (
    HelpCommand,
    LoadCommand,
    SaveCommand,
    ExitCommand,
)

# Display Commands
from pardal.commands.display import (
    ListComponentsCommand,
    ListNetsCommand,
    ShowBoardCommand,
    ShowNetCommand,
    ShowAirwiresCommand,
)

# Component Commands
from pardal.commands.component import (
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
from pardal.commands.history import (
    UndoCommand,
    RedoCommand,
    HistoryCommand,
)

# Measure Commands
from pardal.commands.measure import (
    MeasureDistanceCommand,
    MeasureNetLengthCommand,
)

# DRC Commands
from pardal.commands.drc import (
    CheckDrcCommand,
    CheckAirwiresCommand,
    CheckClearanceCommand,
    CheckConnectivityCommand,
)

# Routing Commands
from pardal.commands.routing import (
    RouteCommand,
    ViaCommand,
    DeleteRouteCommand,
    DeleteViaCommand,
    AutoRouteCommand,
    OptimizeRoutingCommand,
)

# Config Commands
from pardal.commands.config import (
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
