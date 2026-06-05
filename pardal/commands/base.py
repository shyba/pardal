"""
PCB Tool Command Pattern

Abstract base class for all commands following the Command Pattern.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pardal.data_model import Board


class Command(ABC):
    """Abstract base class for all commands"""

    @abstractmethod
    def validate(self, board: "Board") -> str | None:
        """
        Validate command can execute.
        Returns None if valid, error message string if invalid.
        """
        pass

    @abstractmethod
    def execute(self, board: "Board") -> str:
        """
        Execute the command.
        Returns result message string.
        """
        pass

    def undo(self, board: "Board") -> str:
        """Undo the command (override in subclasses that support undo)"""
        return "Undo not implemented for this command"
