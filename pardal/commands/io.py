"""I/O Commands - Help, Load, Save, Exit"""

from pathlib import Path
from pardal.commands.base import Command
from pardal.data_model import Board
from pardal.messages import success, error


class HelpCommand(Command):
    """Display help information about available commands"""

    def validate(self, board: Board) -> str | None:
        """Help is always valid"""
        return None

    def execute(self, board: Board) -> str:
        """Return help text"""
        return """Available Commands:

State Management:
  LOAD <file>              Load netlist from file
  SAVE <file>              Save board to .kicad_pcb file
  UNDO                     Undo last command
  REDO                     Redo previously undone command
  HISTORY                  Show command history

Component Placement:
  MOVE <ref> TO <x> <y> [ROTATION <angle>]  Move component to position
  ROTATE <ref> TO|BY <angle>                Rotate component
  FLIP <ref>                                Flip component to other side
  LOCK <ref>                                Lock component position
  UNLOCK <ref>                              Unlock component

Query:
  SHOW BOARD               Display ASCII board view
  LIST COMPONENTS          List all components
  LIST NETS                List all nets
  WHERE <ref>              Show component location
  HELP                     Show this help message

Control:
  EXIT                     Exit program
  QUIT                     Exit program
"""


class LoadCommand(Command):
    """Load a netlist file into the board"""

    def __init__(self, path: Path):
        self.path = path

    def validate(self, board: Board) -> str | None:
        """Check if file exists"""
        # Check for empty path
        if str(self.path) == "" or str(self.path) == ".":
            return error("No file path provided")
        if not self.path.exists():
            return error(f"File not found: {self.path}")
        if self.path.is_dir():
            return error(f"{self.path} is a directory, not a file")
        return None

    def execute(self, board: Board) -> str:
        """Load netlist and populate board"""
        from pardal.netlist_reader import NetlistReader

        reader = NetlistReader()
        loaded_board = reader.read(self.path)

        # Transfer components and nets to the board
        board.components = loaded_board.components
        board.nets = loaded_board.nets
        board.source_file = loaded_board.source_file

        comp_count = len(board.components)
        net_count = len(board.nets)

        return success(f"Loaded board with {comp_count} components, {net_count} nets")


class SaveCommand(Command):
    """Save board to .kicad_pcb file"""

    def __init__(self, path: Path = None):
        self.path = path

    def validate(self, board: Board) -> str | None:
        # Check if board has any components
        if not board.components:
            return error("Cannot save: board is empty (no components loaded)")
        # If no path provided, check if board has source_file
        if self.path is None and board.source_file is None:
            return error("No filename specified and no source file loaded")
        return None

    def execute(self, board: Board) -> str:
        from pardal.kicad_writer import KicadWriter

        # Use provided path or default to source_file
        output_path = self.path if self.path is not None else board.source_file

        writer = KicadWriter()
        try:
            writer.write(board, output_path)
        except PermissionError as e:
            return error(f"Permission denied writing to {output_path}")
        except IOError as e:
            return error(f"Error writing to {output_path}: {e}")

        return success(f"Saved to {output_path}")


class ExitCommand(Command):
    """Exit the interactive session"""

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        return "Goodbye!"
