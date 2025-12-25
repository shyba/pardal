"""
PCB Tool Command Parser

Parse command strings into Command objects.
"""

from pathlib import Path
from pcb_tool.commands import Command, LoadCommand, ListComponentsCommand, ListNetsCommand, ShowBoardCommand, LockCommand, UnlockCommand, MoveCommand, RotateCommand, SaveCommand, FlipCommand, WhereCommand, ExitCommand, UndoCommand, RedoCommand, HistoryCommand, HelpCommand, RouteCommand, ViaCommand, DeleteRouteCommand, DeleteViaCommand, MeasureDistanceCommand, MeasureNetLengthCommand, GroupMoveCommand, ArrangeCommand, CheckDrcCommand, CheckAirwiresCommand, CheckClearanceCommand, CheckConnectivityCommand, ShowNetCommand, ShowAirwiresCommand, AutoRouteCommand, OptimizeRoutingCommand, SetWidthCommand, SetLayersCommand, SetClearanceCommand, SetBoardSizeCommand, StatsCommand, CreateNetCommand, CreateComponentCommand, AutoRouteStrategyCommand


class CommandParser:
    """Parse command strings into Command objects"""

    def __init__(self):
        """Initialize parser with command registry"""
        self.commands = {}

        # Register commands
        self.register("LOAD", self._parse_load)
        self.register("LIST", self._parse_list)
        self.register("SHOW", self._parse_show)
        self.register("LOCK", self._parse_lock)
        self.register("UNLOCK", self._parse_unlock)
        self.register("MOVE", self._parse_move)
        self.register("ROTATE", self._parse_rotate)
        self.register("SAVE", self._parse_save)
        self.register("FLIP", self._parse_flip)
        self.register("WHERE", self._parse_where)
        self.register("UNDO", self._parse_undo)
        self.register("REDO", self._parse_redo)
        self.register("HISTORY", self._parse_history)
        self.register("HELP", self._parse_help)
        self.register("EXIT", self._parse_exit)
        self.register("QUIT", self._parse_exit)
        self.register("ROUTE", self._parse_route)
        self.register("VIA", self._parse_via)
        self.register("DELETE_ROUTE", self._parse_delete_route)
        self.register("DELETE_VIA", self._parse_delete_via)
        self.register("MEASURE", self._parse_measure)
        self.register("GROUP_MOVE", self._parse_group_move)
        self.register("ARRANGE", self._parse_arrange)
        self.register("CHECK", self._parse_check)
        self.register("AUTOROUTE", self._parse_autoroute)
        self.register("OPTIMIZE", self._parse_optimize)
        self.register("SET", self._parse_set)
        self.register("STATS", self._parse_stats)
        self.register("CREATE", self._parse_create)

    def register(self, verb: str, factory):
        """
        Register a command factory function.

        Args:
            verb: Command verb (will be stored uppercase)
            factory: Callable that takes args list and returns Command instance
        """
        self.commands[verb.upper()] = factory

    def parse(self, line: str) -> Command | None:
        """
        Parse a command line string.
        Returns Command object or None if invalid/empty.
        """
        line = line.strip()
        if not line:
            return None

        tokens = line.split()
        if not tokens:
            return None

        verb = tokens[0].upper()
        args = tokens[1:]  # Remaining tokens as arguments

        # Look up command factory
        if verb not in self.commands:
            return None

        # Call factory to create command instance
        factory = self.commands[verb]
        try:
            return factory(args)
        except Exception:
            return None  # Factory failed, invalid command

    def _parse_load(self, args: list) -> Command:
        """Parse LOAD command.

        Syntax: LOAD <filename>

        Args:
            args: Command arguments split by whitespace

        Returns:
            LoadCommand instance or command that will fail validation if no filename
        """
        if not args:
            return LoadCommand(Path(""))  # Will fail validation
        return LoadCommand(Path(args[0]))

    def _parse_list(self, args: list) -> Command:
        """Parse LIST command.

        Syntax: LIST COMPONENTS | LIST NETS

        Args:
            args: Command arguments split by whitespace

        Returns:
            ListComponentsCommand, ListNetsCommand, or None if invalid
        """
        if not args:
            return None  # Need subcommand

        subcommand = args[0].upper()

        if subcommand == "COMPONENTS":
            return ListComponentsCommand()
        elif subcommand == "NETS":
            return ListNetsCommand()

        return None  # Unknown LIST subcommand

    def _parse_lock(self, args: list) -> Command:
        """Parse LOCK command.

        Syntax: LOCK <ref>

        Args:
            args: Command arguments split by whitespace

        Returns:
            LockCommand instance or None if no reference provided
        """
        if not args:
            return None
        return LockCommand(args[0])

    def _parse_unlock(self, args: list) -> Command:
        """Parse UNLOCK command.

        Syntax: UNLOCK <ref>

        Args:
            args: Command arguments split by whitespace

        Returns:
            UnlockCommand instance or None if no reference provided
        """
        if not args:
            return None
        return UnlockCommand(args[0])

    def _parse_move(self, args: list) -> Command:
        """Parse MOVE command.

        Syntax: MOVE <ref> TO <x> <y> [ROTATION <angle>]

        Args:
            args: Command arguments split by whitespace

        Returns:
            MoveCommand instance or None if parse fails
        """
        if len(args) < 4 or args[1].upper() != "TO":
            return None

        try:
            ref = args[0]
            x = float(args[2])
            y = float(args[3])

            # Check for optional ROTATION
            rotation = None
            if len(args) >= 6 and args[4].upper() == "ROTATION":
                rotation = float(args[5])

            return MoveCommand(ref, x, y, rotation=rotation)
        except (ValueError, IndexError):
            return None

    def _parse_rotate(self, args: list) -> Command:
        """Parse ROTATE command.

        Syntax: ROTATE <ref> TO|BY <angle> or ROTATE <ref> <angle> (legacy)

        Args:
            args: Command arguments split by whitespace

        Returns:
            RotateCommand instance or None if parse fails
        """
        if len(args) < 2:
            return None

        ref = args[0]

        # Try new syntax: ROTATE <ref> TO|BY <angle>
        if len(args) >= 3:
            mode = args[1].upper()
            if mode in ["TO", "BY"]:
                try:
                    angle = float(args[2])
                    absolute = (mode == "TO")
                    return RotateCommand(ref, angle, absolute=absolute)
                except ValueError:
                    return None

        # Fall back to legacy syntax: ROTATE <ref> <angle> (assumes BY)
        try:
            angle = float(args[1])
            return RotateCommand(ref, angle, absolute=False)
        except ValueError:
            return None

    def _parse_save(self, args: list) -> Command:
        """Parse SAVE command.

        Syntax: SAVE [<path>]

        Args:
            args: Command arguments split by whitespace

        Returns:
            SaveCommand instance with path or None (uses source_file)
        """
        if not args:
            return SaveCommand(None)  # No path, will use source_file
        return SaveCommand(Path(args[0]))

    def _parse_flip(self, args: list) -> Command:
        """Parse FLIP command.

        Syntax: FLIP <ref>

        Args:
            args: Command arguments split by whitespace

        Returns:
            FlipCommand instance or None if no reference provided
        """
        if not args:
            return None
        return FlipCommand(args[0])

    def _parse_where(self, args: list) -> Command:
        """Parse WHERE command.

        Syntax: WHERE <ref>

        Args:
            args: Command arguments split by whitespace

        Returns:
            WhereCommand instance or None if no reference provided
        """
        if not args:
            return None
        return WhereCommand(args[0])

    def _parse_exit(self, args: list) -> Command:
        """Parse EXIT/QUIT command.

        Syntax: EXIT or QUIT

        Args:
            args: Command arguments (ignored)

        Returns:
            ExitCommand instance
        """
        return ExitCommand()

    def _parse_show(self, args: list) -> Command:
        """Parse SHOW command.

        Syntax: SHOW BOARD
                SHOW NET <net_name>
                SHOW AIRWIRES [NET <net_name>]

        Args:
            args: Command arguments split by whitespace

        Returns:
            ShowBoardCommand, ShowNetCommand, ShowAirwiresCommand, or None if invalid
        """
        if not args:
            return None

        subcommand = args[0].upper()

        if subcommand == "BOARD":
            return ShowBoardCommand()

        elif subcommand == "NET":
            # SHOW NET <net_name>
            if len(args) < 2:
                return None

            # Extract net name (everything after NET)
            net_name = " ".join(args[1:])
            # Handle quoted names
            if net_name.startswith('"') and net_name.endswith('"'):
                net_name = net_name[1:-1]

            return ShowNetCommand(net_name)

        elif subcommand == "AIRWIRES":
            # SHOW AIRWIRES [NET <net_name>]
            if len(args) == 1:
                # No filter
                return ShowAirwiresCommand()
            elif len(args) >= 3 and args[1].upper() == "NET":
                # With NET filter
                net_name = " ".join(args[2:])
                # Handle quoted names
                if net_name.startswith('"') and net_name.endswith('"'):
                    net_name = net_name[1:-1]
                return ShowAirwiresCommand(net_name)
            else:
                return None

        return None

    def _parse_undo(self, args: list) -> Command:
        """Parse UNDO command.

        Syntax: UNDO

        Args:
            args: Command arguments (ignored)

        Returns:
            UndoCommand instance
        """
        return UndoCommand()

    def _parse_redo(self, args: list) -> Command:
        """Parse REDO command.

        Syntax: REDO

        Args:
            args: Command arguments (ignored)

        Returns:
            RedoCommand instance
        """
        return RedoCommand()

    def _parse_history(self, args: list) -> Command:
        """Parse HISTORY command.

        Syntax: HISTORY

        Args:
            args: Command arguments (ignored)

        Returns:
            HistoryCommand instance
        """
        return HistoryCommand()

    def _parse_help(self, args: list) -> Command:
        """Parse HELP command.

        Syntax: HELP

        Args:
            args: Command arguments (ignored)

        Returns:
            HelpCommand instance
        """
        return HelpCommand()

    def _parse_route(self, args: list) -> Command:
        """Parse ROUTE command.

        Syntax: ROUTE NET <net_name> FROM <x1> <y1> TO <x2> <y2> [LAYER <layer>] [WIDTH <width>]
                ROUTE NET <net_name> FROM <ref>.<pin> TO <ref>.<pin> [LAYER <layer>] [WIDTH <width>]
                ROUTE NET <net_name> FROM <start> VIA (x, y) [VIA (x, y) ...] TO <end> [LAYER <layer>] [WIDTH <width>]

        Args:
            args: Command arguments split by whitespace

        Returns:
            RouteCommand instance or None if parse fails
        """
        if len(args) < 4:
            return None

        # Check for NET keyword
        if args[0].upper() != "NET":
            return None

        # Reconstruct full command string to extract VIA waypoints using regex
        import re
        command_text = " ".join(args)

        # Find FROM and TO keywords
        try:
            from_idx = next(i for i, arg in enumerate(args) if arg.upper() == "FROM")
            to_idx = next(i for i, arg in enumerate(args) if arg.upper() == "TO")
        except StopIteration:
            return None

        # Extract net name (everything between NET and FROM)
        net_name_parts = args[1:from_idx]
        if not net_name_parts:
            return None

        # Handle quoted names
        net_name = " ".join(net_name_parts)
        if net_name.startswith('"') and net_name.endswith('"'):
            net_name = net_name[1:-1]

        # Extract VIA waypoints from command text using regex
        # Pattern matches: VIA (x, y) or VIA (x.x, y.y)
        via_pattern = r'VIA\s*\(\s*(\d+\.?\d*)\s*,\s*(\d+\.?\d*)\s*\)'
        waypoints = []
        for match in re.finditer(via_pattern, command_text):
            x = float(match.group(1))
            y = float(match.group(2))
            waypoints.append((x, y))

        # Parse start position (component.pin or x y coordinates)
        # Stop at TO or VIA keywords
        start_parts = []
        i = from_idx + 1
        while i < len(args) and args[i].upper() not in ["TO", "VIA"]:
            start_parts.append(args[i])
            i += 1

        if not start_parts:
            return None

        # Determine start position type
        if len(start_parts) == 1 and '.' in start_parts[0]:
            # Component.pin notation
            start_pos = start_parts[0]  # Store as string
        elif len(start_parts) == 2:
            # Coordinate notation
            try:
                x1 = float(start_parts[0])
                y1 = float(start_parts[1])
                start_pos = (x1, y1)
            except ValueError:
                return None
        else:
            return None

        # Parse end position (component.pin or x y coordinates)
        # Stop at LAYER, WIDTH, or VIA keywords
        end_parts = []
        i = to_idx + 1
        while i < len(args) and args[i].upper() not in ["LAYER", "WIDTH", "VIA"]:
            end_parts.append(args[i])
            i += 1

        if not end_parts:
            return None

        # Determine end position type
        if len(end_parts) == 1 and '.' in end_parts[0]:
            # Component.pin notation
            end_pos = end_parts[0]  # Store as string
        elif len(end_parts) == 2:
            # Coordinate notation
            try:
                x2 = float(end_parts[0])
                y2 = float(end_parts[1])
                end_pos = (x2, y2)
            except ValueError:
                return None
        else:
            return None

        # Extract optional parameters
        layer = "F.Cu"
        width = None

        # Find LAYER keyword
        try:
            layer_idx = next(i for i, arg in enumerate(args) if arg.upper() == "LAYER")
            if layer_idx + 1 < len(args):
                layer = args[layer_idx + 1]
        except StopIteration:
            pass

        # Find WIDTH keyword
        try:
            width_idx = next(i for i, arg in enumerate(args) if arg.upper() == "WIDTH")
            if width_idx + 1 < len(args):
                width = float(args[width_idx + 1])
        except (StopIteration, ValueError):
            pass

        # Pass waypoints to RouteCommand (None if no VIA waypoints found)
        return RouteCommand(net_name, start_pos, end_pos, layer=layer, width=width,
                          waypoints=waypoints if waypoints else None)

    def _parse_via(self, args: list) -> Command:
        """Parse VIA command.

        Syntax: VIA NET <net_name> AT <x> <y> [SIZE <diameter>] [DRILL <drill>]

        Args:
            args: Command arguments split by whitespace

        Returns:
            ViaCommand instance or None if parse fails
        """
        if len(args) < 4:
            return None

        # Check for NET keyword
        if args[0].upper() != "NET":
            return None

        # Find AT keyword
        try:
            at_idx = next(i for i, arg in enumerate(args) if arg.upper() == "AT")
        except StopIteration:
            return None

        # Extract net name (everything between NET and AT)
        net_name_parts = args[1:at_idx]
        if not net_name_parts:
            return None

        # Handle quoted names
        net_name = " ".join(net_name_parts)
        if net_name.startswith('"') and net_name.endswith('"'):
            net_name = net_name[1:-1]

        # Extract coordinates
        try:
            x = float(args[at_idx + 1])
            y = float(args[at_idx + 2])
        except (ValueError, IndexError):
            return None

        # Extract optional parameters
        size = None
        drill = None

        # Find SIZE keyword
        try:
            size_idx = next(i for i, arg in enumerate(args) if arg.upper() == "SIZE")
            if size_idx + 1 < len(args):
                size = float(args[size_idx + 1])
        except (StopIteration, ValueError):
            pass

        # Find DRILL keyword
        try:
            drill_idx = next(i for i, arg in enumerate(args) if arg.upper() == "DRILL")
            if drill_idx + 1 < len(args):
                drill = float(args[drill_idx + 1])
        except (StopIteration, ValueError):
            pass

        return ViaCommand(net_name, (x, y), size=size, drill=drill)

    def _parse_delete_route(self, args: list) -> Command:
        """Parse DELETE_ROUTE command.

        Syntax: DELETE_ROUTE NET <net_name> AT <x> <y>
                DELETE_ROUTE NET <net_name> ALL

        Args:
            args: Command arguments split by whitespace

        Returns:
            DeleteRouteCommand instance or None if parse fails
        """
        if len(args) < 3:
            return None

        # Check for NET keyword
        if args[0].upper() != "NET":
            return None

        # Find ALL or AT keyword
        try:
            all_idx = next(i for i, arg in enumerate(args) if arg.upper() == "ALL")
            # ALL mode
            net_name_parts = args[1:all_idx]
            if not net_name_parts:
                return None

            # Handle quoted names
            net_name = " ".join(net_name_parts)
            if net_name.startswith('"') and net_name.endswith('"'):
                net_name = net_name[1:-1]

            return DeleteRouteCommand(net_name, delete_all=True)

        except StopIteration:
            # Not ALL mode, try AT mode
            try:
                at_idx = next(i for i, arg in enumerate(args) if arg.upper() == "AT")
            except StopIteration:
                return None

            # Extract net name (everything between NET and AT)
            net_name_parts = args[1:at_idx]
            if not net_name_parts:
                return None

            # Handle quoted names
            net_name = " ".join(net_name_parts)
            if net_name.startswith('"') and net_name.endswith('"'):
                net_name = net_name[1:-1]

            # Extract coordinates
            try:
                x = float(args[at_idx + 1])
                y = float(args[at_idx + 2])
            except (ValueError, IndexError):
                return None

            return DeleteRouteCommand(net_name, position=(x, y))

    def _parse_delete_via(self, args: list) -> Command:
        """Parse DELETE_VIA command.

        Syntax: DELETE_VIA NET <net_name> AT <x> <y>
                DELETE_VIA NET <net_name> ALL

        Args:
            args: Command arguments split by whitespace

        Returns:
            DeleteViaCommand instance or None if parse fails
        """
        if len(args) < 3:
            return None

        # Check for NET keyword
        if args[0].upper() != "NET":
            return None

        # Find ALL or AT keyword
        try:
            all_idx = next(i for i, arg in enumerate(args) if arg.upper() == "ALL")
            # ALL mode
            net_name_parts = args[1:all_idx]
            if not net_name_parts:
                return None

            # Handle quoted names
            net_name = " ".join(net_name_parts)
            if net_name.startswith('"') and net_name.endswith('"'):
                net_name = net_name[1:-1]

            return DeleteViaCommand(net_name, delete_all=True)

        except StopIteration:
            # Not ALL mode, try AT mode
            try:
                at_idx = next(i for i, arg in enumerate(args) if arg.upper() == "AT")
            except StopIteration:
                return None

            # Extract net name (everything between NET and AT)
            net_name_parts = args[1:at_idx]
            if not net_name_parts:
                return None

            # Handle quoted names
            net_name = " ".join(net_name_parts)
            if net_name.startswith('"') and net_name.endswith('"'):
                net_name = net_name[1:-1]

            # Extract coordinates
            try:
                x = float(args[at_idx + 1])
                y = float(args[at_idx + 2])
            except (ValueError, IndexError):
                return None

            return DeleteViaCommand(net_name, position=(x, y))

    def _parse_measure(self, args: list) -> Command:
        """Parse MEASURE command.

        Syntax: MEASURE DISTANCE FROM <x1> <y1> TO <x2> <y2>
                MEASURE DISTANCE FROM <ref1> TO <ref2>
                MEASURE NET <net_name> LENGTH

        Args:
            args: Command arguments split by whitespace

        Returns:
            MeasureDistanceCommand or MeasureNetLengthCommand instance, or None if parse fails
        """
        if not args:
            return None

        subcommand = args[0].upper()

        if subcommand == "DISTANCE":
            # Parse MEASURE DISTANCE
            return self._parse_measure_distance(args[1:])
        elif subcommand == "NET":
            # Parse MEASURE NET LENGTH
            return self._parse_measure_net_length(args[1:])

        return None

    def _parse_measure_distance(self, args: list) -> Command:
        """Parse MEASURE DISTANCE subcommand.

        Syntax: MEASURE DISTANCE FROM <x1> <y1> TO <x2> <y2>
                MEASURE DISTANCE FROM <ref1> TO <ref2>

        Args:
            args: Command arguments after DISTANCE keyword

        Returns:
            MeasureDistanceCommand instance or None if parse fails
        """
        if len(args) < 4:
            return None

        # Check for FROM keyword
        if args[0].upper() != "FROM":
            return None

        # Find TO keyword
        try:
            to_idx = next(i for i, arg in enumerate(args) if arg.upper() == "TO")
        except StopIteration:
            return None

        # Extract start position (between FROM and TO)
        start_parts = args[1:to_idx]
        if not start_parts:
            return None

        # Extract end position (after TO)
        end_parts = args[to_idx + 1:]
        if not end_parts:
            return None

        # Determine if start is coordinates or component ref
        if len(start_parts) == 2:
            # Try to parse as coordinates
            try:
                start_x = float(start_parts[0])
                start_y = float(start_parts[1])
                start = (start_x, start_y)
            except ValueError:
                # Not numbers, treat as component ref (error will be caught in validation)
                return None
        elif len(start_parts) == 1:
            # Component reference
            start = start_parts[0]
        else:
            return None

        # Determine if end is coordinates or component ref
        if len(end_parts) == 2:
            # Try to parse as coordinates
            try:
                end_x = float(end_parts[0])
                end_y = float(end_parts[1])
                end = (end_x, end_y)
            except ValueError:
                # Not numbers, treat as component ref (error will be caught in validation)
                return None
        elif len(end_parts) == 1:
            # Component reference
            end = end_parts[0]
        else:
            return None

        return MeasureDistanceCommand(start, end)

    def _parse_measure_net_length(self, args: list) -> Command:
        """Parse MEASURE NET LENGTH subcommand.

        Syntax: MEASURE NET <net_name> LENGTH

        Args:
            args: Command arguments after NET keyword

        Returns:
            MeasureNetLengthCommand instance or None if parse fails
        """
        if len(args) < 2:
            return None

        # Find LENGTH keyword
        try:
            length_idx = next(i for i, arg in enumerate(args) if arg.upper() == "LENGTH")
        except StopIteration:
            return None

        # Extract net name (everything before LENGTH)
        net_name_parts = args[:length_idx]
        if not net_name_parts:
            return None

        # Handle quoted names
        net_name = " ".join(net_name_parts)
        if net_name.startswith('"') and net_name.endswith('"'):
            net_name = net_name[1:-1]

        return MeasureNetLengthCommand(net_name)

    def _parse_group_move(self, args: list) -> Command:
        """Parse GROUP_MOVE command.

        Syntax: GROUP_MOVE <ref1> <ref2> ... BY <dx> <dy>

        Args:
            args: Command arguments split by whitespace

        Returns:
            GroupMoveCommand instance or None if parse fails
        """
        if len(args) < 4:
            return None

        # Find BY keyword
        try:
            by_idx = next(i for i, arg in enumerate(args) if arg.upper() == "BY")
        except StopIteration:
            return None

        # Extract component references (everything before BY)
        refs = args[:by_idx]
        if not refs:
            return None

        # Extract dx and dy (after BY)
        if by_idx + 2 >= len(args):
            return None

        try:
            dx = float(args[by_idx + 1])
            dy = float(args[by_idx + 2])
        except (ValueError, IndexError):
            return None

        return GroupMoveCommand(refs, dx, dy)

    def _parse_arrange(self, args: list) -> Command:
        """Parse ARRANGE command.

        Syntax: ARRANGE <ref1> <ref2> ... [GRID | ROW | COLUMN] [SPACING <spacing>]

        Args:
            args: Command arguments split by whitespace

        Returns:
            ArrangeCommand instance or None if parse fails
        """
        if not args:
            return None

        # Keywords to look for
        pattern_keywords = {"GRID", "ROW", "COLUMN"}
        spacing_keyword = "SPACING"

        # Parse arguments
        refs = []
        pattern = "GRID"  # Default
        spacing = 5.0     # Default

        i = 0
        # Collect refs until we hit a keyword
        while i < len(args):
            arg_upper = args[i].upper()

            if arg_upper in pattern_keywords:
                pattern = arg_upper
                i += 1
            elif arg_upper == spacing_keyword:
                # Next argument should be spacing value
                if i + 1 < len(args):
                    try:
                        spacing = float(args[i + 1])
                        i += 2
                    except ValueError:
                        return None
                else:
                    return None
            else:
                # It's a component reference
                refs.append(args[i])
                i += 1

        # Must have at least one ref
        if not refs:
            return None

        return ArrangeCommand(refs, pattern=pattern, spacing=spacing)

    def _parse_check(self, args: list) -> Command:
        """Parse CHECK command.

        Syntax: CHECK DRC
                CHECK AIRWIRES [NET <net_name>]
                CHECK CLEARANCE
                CHECK CONNECTIVITY

        Args:
            args: Command arguments split by whitespace

        Returns:
            CheckDrcCommand, CheckAirwiresCommand, CheckClearanceCommand,
            CheckConnectivityCommand, or None if parse fails
        """
        if not args:
            return None

        subcommand = args[0].upper()

        if subcommand == "DRC":
            return CheckDrcCommand()

        elif subcommand == "AIRWIRES":
            # Check for optional NET filter
            if len(args) >= 3 and args[1].upper() == "NET":
                # Extract net name (everything after NET)
                net_name = " ".join(args[2:])
                # Handle quoted names
                if net_name.startswith('"') and net_name.endswith('"'):
                    net_name = net_name[1:-1]
                return CheckAirwiresCommand(net_name=net_name)
            else:
                # No filter, check all nets
                return CheckAirwiresCommand()

        elif subcommand == "CLEARANCE":
            return CheckClearanceCommand()

        elif subcommand == "CONNECTIVITY":
            return CheckConnectivityCommand()

        return None

    def _parse_autoroute(self, args: list) -> Command:
        """Parse AUTOROUTE command.

        Syntax: AUTOROUTE NET <net_name>
                AUTOROUTE NET <net_name> LAYER <layer>
                AUTOROUTE ALL
                AUTOROUTE ALL UNROUTED
                AUTOROUTE STRATEGY <strategy_name>

        Args:
            args: Command arguments split by whitespace

        Returns:
            AutoRouteCommand or AutoRouteStrategyCommand instance or None if parse fails
        """
        if not args:
            return None

        # Check for STRATEGY subcommand
        if args[0].upper() == "STRATEGY":
            if len(args) < 2:
                return None
            return AutoRouteStrategyCommand(strategy_name=args[1])

        # Check for ALL or NET subcommand
        if args[0].upper() == "ALL":
            # AUTOROUTE ALL or AUTOROUTE ALL UNROUTED
            if len(args) > 1 and args[1].upper() == "UNROUTED":
                return AutoRouteCommand(net_name="UNROUTED")
            else:
                return AutoRouteCommand(net_name="ALL")

        elif args[0].upper() == "NET":
            # AUTOROUTE NET <net_name> [LAYER <layer>]
            if len(args) < 2:
                return None

            # Find optional LAYER keyword
            layer_idx = None
            try:
                layer_idx = next(i for i, arg in enumerate(args) if arg.upper() == "LAYER")
            except StopIteration:
                pass

            # Extract net name
            if layer_idx is not None:
                # Net name is between NET and LAYER
                net_name_parts = args[1:layer_idx]
                if not net_name_parts:
                    return None
                net_name = " ".join(net_name_parts)

                # Extract layer
                if layer_idx + 1 >= len(args):
                    return None
                layer = args[layer_idx + 1]

                # Handle quoted names
                if net_name.startswith('"') and net_name.endswith('"'):
                    net_name = net_name[1:-1]

                return AutoRouteCommand(net_name=net_name, prefer_layer=layer)
            else:
                # Net name is everything after NET
                net_name_parts = args[1:]
                if not net_name_parts:
                    return None
                net_name = " ".join(net_name_parts)

                # Handle quoted names
                if net_name.startswith('"') and net_name.endswith('"'):
                    net_name = net_name[1:-1]

                return AutoRouteCommand(net_name=net_name)

        return None

    def _parse_optimize(self, args: list) -> Command:
        """Parse OPTIMIZE command.

        Syntax: OPTIMIZE ROUTING NET <net_name>
                OPTIMIZE ROUTING ALL

        Args:
            args: Command arguments split by whitespace

        Returns:
            OptimizeRoutingCommand instance or None if parse fails
        """
        if not args:
            return None

        # Check for ROUTING subcommand
        if args[0].upper() != "ROUTING":
            return None

        if len(args) < 2:
            return None

        # Check for ALL or NET
        if args[1].upper() == "ALL":
            return OptimizeRoutingCommand(net_name="ALL")

        elif args[1].upper() == "NET":
            # OPTIMIZE ROUTING NET <net_name>
            if len(args) < 3:
                return None

            # Extract net name (everything after NET)
            net_name_parts = args[2:]
            if not net_name_parts:
                return None
            net_name = " ".join(net_name_parts)

            # Handle quoted names
            if net_name.startswith('"') and net_name.endswith('"'):
                net_name = net_name[1:-1]

            return OptimizeRoutingCommand(net_name=net_name)

        return None

    def _parse_set(self, args: list) -> Command:
        """Parse SET command.

        Syntax: SET WIDTH NET <net_name> <width_mm>
                SET WIDTH CLASS <class_name> <width_mm>
                SET WIDTH DEFAULT <width_mm>
                SET LAYERS <count>
                SET CLEARANCE NET <net_name> <clearance_mm>
                SET CLEARANCE CLASS <class_name> <clearance_mm>
                SET BOARD SIZE <width_mm> <height_mm>

        Args:
            args: Command arguments split by whitespace

        Returns:
            SetWidthCommand, SetLayersCommand, SetClearanceCommand, SetBoardSizeCommand, or None if parse fails
        """
        if not args:
            return None

        subcommand = args[0].upper()

        if subcommand == "WIDTH":
            return self._parse_set_width(args[1:])
        elif subcommand == "LAYERS":
            return self._parse_set_layers(args[1:])
        elif subcommand == "CLEARANCE":
            return self._parse_set_clearance(args[1:])
        elif subcommand == "BOARD":
            return self._parse_set_board(args[1:])

        return None

    def _parse_set_width(self, args: list) -> Command:
        """Parse SET WIDTH subcommand.

        Syntax: SET WIDTH NET <net_name> <width_mm>
                SET WIDTH CLASS <class_name> <width_mm>
                SET WIDTH DEFAULT <width_mm>

        Args:
            args: Command arguments after WIDTH keyword

        Returns:
            SetWidthCommand instance or None if parse fails
        """
        if not args:
            return None

        target = args[0].upper()

        if target == "NET":
            # SET WIDTH NET <net_name> <width_mm>
            if len(args) < 3:
                return None

            # Width is the last argument
            try:
                width = float(args[-1])
            except ValueError:
                return None

            # Net name is everything between NET and width
            net_name_parts = args[1:-1]
            if not net_name_parts:
                return None

            net_name = " ".join(net_name_parts)
            # Handle quoted names
            if net_name.startswith('"') and net_name.endswith('"'):
                net_name = net_name[1:-1]

            return SetWidthCommand(width=width, net_name=net_name)

        elif target == "CLASS":
            # SET WIDTH CLASS <class_name> <width_mm>
            if len(args) < 3:
                return None

            # Width is the last argument
            try:
                width = float(args[-1])
            except ValueError:
                return None

            # Class name is everything between CLASS and width
            class_name_parts = args[1:-1]
            if not class_name_parts:
                return None

            class_name = " ".join(class_name_parts)
            # Handle quoted names
            if class_name.startswith('"') and class_name.endswith('"'):
                class_name = class_name[1:-1]

            return SetWidthCommand(width=width, class_name=class_name)

        elif target == "DEFAULT":
            # SET WIDTH DEFAULT <width_mm>
            if len(args) < 2:
                return None

            try:
                width = float(args[1])
            except ValueError:
                return None

            return SetWidthCommand(width=width, set_default=True)

        return None

    def _parse_set_layers(self, args: list) -> Command:
        """Parse SET LAYERS subcommand.

        Syntax: SET LAYERS <count>

        Args:
            args: Command arguments after LAYERS keyword

        Returns:
            SetLayersCommand instance or None if parse fails
        """
        if not args:
            return None

        try:
            layer_count = int(args[0])
        except ValueError:
            return None

        return SetLayersCommand(layer_count=layer_count)

    def _parse_set_clearance(self, args: list) -> Command:
        """Parse SET CLEARANCE subcommand.

        Syntax: SET CLEARANCE NET <net_name> <clearance_mm>
                SET CLEARANCE CLASS <class_name> <clearance_mm>

        Args:
            args: Command arguments after CLEARANCE keyword

        Returns:
            SetClearanceCommand instance or None if parse fails
        """
        if not args:
            return None

        target = args[0].upper()

        if target == "NET":
            # SET CLEARANCE NET <net_name> <clearance_mm>
            if len(args) < 3:
                return None

            # Clearance is the last argument
            try:
                clearance = float(args[-1])
            except ValueError:
                return None

            # Net name is everything between NET and clearance
            net_name_parts = args[1:-1]
            if not net_name_parts:
                return None

            net_name = " ".join(net_name_parts)
            # Handle quoted names
            if net_name.startswith('"') and net_name.endswith('"'):
                net_name = net_name[1:-1]

            return SetClearanceCommand(clearance=clearance, net_name=net_name)

        elif target == "CLASS":
            # SET CLEARANCE CLASS <class_name> <clearance_mm>
            if len(args) < 3:
                return None

            # Clearance is the last argument
            try:
                clearance = float(args[-1])
            except ValueError:
                return None

            # Class name is everything between CLASS and clearance
            class_name_parts = args[1:-1]
            if not class_name_parts:
                return None

            class_name = " ".join(class_name_parts)
            # Handle quoted names
            if class_name.startswith('"') and class_name.endswith('"'):
                class_name = class_name[1:-1]

            return SetClearanceCommand(clearance=clearance, class_name=class_name)

        return None

    def _parse_set_board(self, args: list) -> Command:
        """Parse SET BOARD subcommand.

        Syntax: SET BOARD SIZE <width_mm> <height_mm>

        Args:
            args: Command arguments after BOARD keyword

        Returns:
            SetBoardSizeCommand instance or None if parse fails
        """
        if not args:
            return None

        subcommand = args[0].upper()

        if subcommand == "SIZE":
            # SET BOARD SIZE <width> <height>
            if len(args) < 3:
                return None

            try:
                width = float(args[1])
                height = float(args[2])
            except ValueError:
                return None

            return SetBoardSizeCommand(width=width, height=height)

        return None

    def _parse_stats(self, args: list) -> Command:
        """Parse STATS command.

        Syntax: STATS
                STATS ROUTING
                STATS NETS
                STATS COMPONENTS

        Args:
            args: Command arguments split by whitespace

        Returns:
            StatsCommand instance
        """
        category = None
        if args:
            category = args[0]

        return StatsCommand(category=category)

    def _parse_create(self, args: list) -> Command:
        """Parse CREATE command.

        Syntax: CREATE NET <name> <ref.pin> <ref.pin> [<ref.pin>...]
                CREATE NET <name> CLASS <class_name> <ref.pin> <ref.pin> [<ref.pin>...]
                CREATE COMPONENT <ref> <footprint> <x> <y> [ROTATION <deg>] [VALUE <val>]

        Args:
            args: Command arguments split by whitespace

        Returns:
            CreateNetCommand, CreateComponentCommand, or None if parse fails
        """
        if not args:
            return None

        subcommand = args[0].upper()

        if subcommand == "NET":
            return self._parse_create_net(args[1:])
        elif subcommand == "COMPONENT":
            return self._parse_create_component(args[1:])

        return None

    def _parse_create_net(self, args: list) -> Command:
        """Parse CREATE NET subcommand.

        Syntax: CREATE NET <name> <ref.pin> <ref.pin> [<ref.pin>...]
                CREATE NET <name> CLASS <class_name> <ref.pin> <ref.pin> [<ref.pin>...]

        Args:
            args: Command arguments after NET keyword

        Returns:
            CreateNetCommand instance or None if parse fails
        """
        if len(args) < 3:  # At minimum: <name> <ref.pin> <ref.pin>
            return None

        name = args[0]
        net_class = None
        connection_args = args[1:]

        # Check for CLASS keyword
        if len(args) > 2 and args[1].upper() == "CLASS":
            if len(args) < 5:  # <name> CLASS <class> <ref.pin> <ref.pin>
                return None
            net_class = args[2]
            connection_args = args[3:]

        # Parse connections (ref.pin format)
        connections = []
        for conn in connection_args:
            if "." not in conn:
                return None
            parts = conn.split(".", 1)
            if len(parts) != 2:
                return None
            connections.append((parts[0], parts[1]))

        if len(connections) < 2:
            return None

        return CreateNetCommand(name=name, connections=connections, net_class=net_class)

    def _parse_create_component(self, args: list) -> Command:
        """Parse CREATE COMPONENT subcommand.

        Syntax: CREATE COMPONENT <ref> <footprint> <x> <y> [ROTATION <deg>] [VALUE <val>]

        Args:
            args: Command arguments after COMPONENT keyword

        Returns:
            CreateComponentCommand instance or None if parse fails
        """
        if len(args) < 4:  # <ref> <footprint> <x> <y>
            return None

        ref = args[0]
        footprint = args[1]

        try:
            x = float(args[2])
            y = float(args[3])
        except ValueError:
            return None

        rotation = 0.0
        value = ""

        # Parse optional parameters
        remaining = args[4:]
        i = 0
        while i < len(remaining):
            keyword = remaining[i].upper()
            if keyword == "ROTATION" and i + 1 < len(remaining):
                try:
                    rotation = float(remaining[i + 1])
                except ValueError:
                    return None
                i += 2
            elif keyword == "VALUE" and i + 1 < len(remaining):
                value = remaining[i + 1]
                i += 2
            else:
                i += 1

        return CreateComponentCommand(
            ref=ref,
            footprint=footprint,
            x=x,
            y=y,
            rotation=rotation,
            value=value
        )
