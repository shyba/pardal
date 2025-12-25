"""History Commands - Undo, Redo, History"""

from pcb_tool.commands.base import Command
from pcb_tool.data_model import Board
from pcb_tool.messages import success


class UndoCommand(Command):
    """Undo last command"""

    def __init__(self):
        self.history = None  # Will be set by REPL

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        if not self.history or not self.history.undo_stack:
            return "Nothing to undo"

        self.history.undo(board)
        return success("Undid last command")


class RedoCommand(Command):
    """Redo last undone command"""

    def __init__(self):
        self.history = None

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        if not self.history or not self.history.redo_stack:
            return "Nothing to redo"

        self.history.redo(board)
        return success("Redid last command")


class HistoryCommand(Command):
    """Show command history"""

    def __init__(self):
        self.history = None

    def validate(self, board: Board) -> str | None:
        return None

    def execute(self, board: Board) -> str:
        if not self.history or not self.history.undo_stack:
            return "No command history"

        lines = [f"Command History ({len(self.history.undo_stack)} commands):"]
        for i, cmd in enumerate(self.history.undo_stack, 1):
            # Convert MoveCommand -> MOVE, RotateCommand -> ROTATE, etc.
            cmd_name = cmd.__class__.__name__.replace("Command", "").upper()
            lines.append(f"  {i}. {cmd_name}")
        return "\n".join(lines)
