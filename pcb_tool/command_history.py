"""
PCB Tool Command History

Manages command history for undo/redo functionality.
"""

from pcb_tool.data_model import Board
from typing import Optional


class CommandHistory:
    """Manages command history for undo/redo"""

    def __init__(self):
        self.undo_stack = []
        self.redo_stack = []

    def add(self, command):
        """Add command to history"""
        self.undo_stack.append(command)
        self.redo_stack.clear()  # Clear redo stack on new command

    def undo(self, board: Board) -> Optional[object]:
        """Undo last command"""
        if not self.undo_stack:
            return None

        cmd = self.undo_stack.pop()
        cmd.undo(board)
        self.redo_stack.append(cmd)
        return cmd

    def redo(self, board: Board) -> Optional[object]:
        """Redo last undone command"""
        if not self.redo_stack:
            return None

        cmd = self.redo_stack.pop()
        cmd.execute(board)
        self.undo_stack.append(cmd)
        return cmd
