"""CLI entry point for PCB Place & Route Tool"""
import argparse
import sys
from pcb_tool import __version__
from pcb_tool.repl import REPL


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog="pcb-tool",
        description="PCB Place & Route Tool"
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"pcb-tool {__version__} (MVP1)"
    )

    parser.add_argument(
        "--load",
        type=str,
        metavar="FILE",
        help="Load netlist or PCB file"
    )

    parser.add_argument(
        "--batch",
        type=str,
        metavar="FILE",
        help="Execute commands from file"
    )

    parser.add_argument(
        "--exec",
        action="append",
        dest="commands",
        metavar="CMD",
        help="Execute single command"
    )

    args = parser.parse_args()

    # Create REPL instance
    repl = REPL()

    # Handle --load
    if args.load:
        result = repl.process_command(f"LOAD {args.load}")
        if result:
            print(result)

    # Handle --exec (can have multiple)
    if args.commands:
        # Print welcome banner for exec mode
        print("PCB Place & Route Tool")
        print("Type HELP for available commands, EXIT to quit")
        print()

        for cmd in args.commands:
            result = repl.process_command(cmd)
            if result:
                print(result)
        return 0

    # Handle --batch
    if args.batch:
        print(f"Executing commands from {args.batch}")
        with open(args.batch, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.rstrip('\r\n').strip()

                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue

                try:
                    result = repl.process_command(line)
                    if result:
                        print(result)
                except Exception as e:
                    print(f"Error on line {line_num}: {e}", file=sys.stderr)
                    return 1
        return 0

    # Default: interactive mode
    repl.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
