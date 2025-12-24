"""
PCB Tool Interactive REPL

Read-Eval-Print Loop for interactive PCB tool usage.
"""

from pcb_tool.command_parser import CommandParser
from pcb_tool.command_history import CommandHistory
from pcb_tool.data_model import Board
from pcb_tool.commands import UndoCommand, RedoCommand, HistoryCommand


class REPL:
    """Read-Eval-Print Loop for interactive PCB tool"""

    def __init__(self):
        self.board = Board()
        self.parser = CommandParser()
        self.history = CommandHistory()
        self.should_exit = False

    def process_command(self, line: str) -> str:
        """Process a single command line"""
        line = line.strip()

        if not line:
            return ""

        # Parse command
        cmd = self.parser.parse(line)

        if cmd is None:
            return f"Error: Unknown command '{line}'"

        # Set history for undo/redo commands
        if isinstance(cmd, (UndoCommand, RedoCommand, HistoryCommand)):
            cmd.history = self.history

        # Validate
        error = cmd.validate(self.board)
        if error:
            return error

        # Execute
        result = cmd.execute(self.board)

        # Check for exit
        if cmd.__class__.__name__ == "ExitCommand":
            self.should_exit = True

        # Add to history (except for undo/redo/history/exit commands)
        if cmd.__class__.__name__ not in ["UndoCommand", "RedoCommand", "HistoryCommand", "ExitCommand", "HelpCommand"]:
            self.history.add(cmd)

        return result

    def run(self):
        """Run the interactive REPL"""
        print("PCB Place & Route Tool")
        print("Type HELP for available commands, EXIT to quit")
        print()

        while not self.should_exit:
            try:
                line = input("pcb> ")
                result = self.process_command(line)
                if result:
                    print(result)
                    print()
            except EOFError:
                break
            except KeyboardInterrupt:
                print("\nUse EXIT to quit")
                continue
