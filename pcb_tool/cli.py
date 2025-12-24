#!/usr/bin/env python3
"""Pardal PCB Tool - CLI entry point.

Provides subcommands for PCB operations:
- build: Load netlist, place components, optionally route, save with DRC
- drc: Run DRC check on existing PCB
- place: Place components from netlist
- route: Autoroute existing PCB
- repl: Interactive REPL mode
"""

import argparse
import sys
from pathlib import Path

from pcb_tool import __version__
from pcb_tool.data_model import Board
from pcb_tool.commands import (
    LoadCommand, SaveCommand, MoveCommand, AutoRouteCommand
)
from pcb_tool.drc import run_drc, format_drc_report, check_kicad_cli
from pcb_tool.repl import REPL


def cmd_build(args) -> int:
    """Build PCB from netlist.

    Steps: load netlist -> apply placement -> optionally route -> save -> DRC
    """
    board = Board()

    # 1. Load netlist
    print(f"Loading {args.netlist}...")
    load_cmd = LoadCommand(args.netlist)
    error = load_cmd.validate(board)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    result = load_cmd.execute(board)
    print(result)

    # 2. Apply placement script if provided
    if args.placement:
        print(f"Applying placement from {args.placement}...")
        if not args.placement.exists():
            print(f"Error: Placement file not found: {args.placement}", file=sys.stderr)
            return 1

        with open(args.placement, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                # Parse MOVE command
                parts = line.upper().split()
                if parts[0] == 'MOVE' and 'TO' in parts:
                    try:
                        ref = parts[1]
                        to_idx = parts.index('TO')
                        x = float(parts[to_idx + 1])
                        y = float(parts[to_idx + 2])
                        rotation = 0
                        if 'ROTATION' in parts:
                            rot_idx = parts.index('ROTATION')
                            rotation = float(parts[rot_idx + 1])

                        move_cmd = MoveCommand(ref, x, y, rotation)
                        error = move_cmd.validate(board)
                        if error:
                            print(f"  Line {line_num}: {error}")
                            continue
                        move_cmd.execute(board)
                    except (ValueError, IndexError) as e:
                        print(f"  Line {line_num}: Parse error: {e}")

        print(f"  Placed {len(board.components)} components")

    # 3. Autoroute if requested
    if args.route:
        print("Running autorouter...")
        autoroute_cmd = AutoRouteCommand(net_name="ALL")
        error = autoroute_cmd.validate(board)
        if error:
            print(f"Autoroute warning: {error}")
        else:
            result = autoroute_cmd.execute(board)
            print(result)

    # 4. Save to KiCad PCB
    print(f"Saving to {args.output}...")
    save_cmd = SaveCommand(args.output)
    error = save_cmd.validate(board)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    result = save_cmd.execute(board)
    print(result)

    # 4.5 Finalize if requested
    if args.finalize:
        print("Finalizing board with KiCad library footprints...")
        try:
            from pcb_tool.finalize import finalize_board
            success, msg = finalize_board(args.output, args.output)
            print(msg)
            if not success:
                print(f"Error: Finalization failed", file=sys.stderr)
                return 1
        except ImportError as e:
            print(f"Warning: Cannot finalize - pcbnew not available: {e}")
            print("Run with system Python (not venv) for finalization")

    # 5. Run DRC unless skipped
    if not args.no_drc:
        if not check_kicad_cli():
            print("Warning: kicad-cli not found, skipping DRC")
        else:
            print("Running DRC...")
            drc_result = run_drc(args.output)
            print(format_drc_report(drc_result))

            if not drc_result.success:
                return 1

    return 0


def cmd_drc(args) -> int:
    """Run DRC check on existing PCB file."""
    if not args.pcb.exists():
        print(f"Error: PCB file not found: {args.pcb}", file=sys.stderr)
        return 1

    if not check_kicad_cli():
        print("Error: kicad-cli not found. Install KiCad to use DRC.", file=sys.stderr)
        return 1

    output_path = args.output
    if output_path and args.format == 'text':
        # For text format, use .txt extension
        if output_path.suffix == '.json':
            output_path = output_path.with_suffix('.txt')

    result = run_drc(args.pcb, output_path)

    if args.format == 'json':
        # JSON output - just report the path
        print(f"DRC report saved to: {result.report_path}")
    else:
        # Text output
        print(format_drc_report(result, verbose=True))

    return 0 if result.success else 1


def cmd_place(args) -> int:
    """Place components from netlist without routing."""
    board = Board()

    # 1. Load netlist
    print(f"Loading {args.netlist}...")
    load_cmd = LoadCommand(args.netlist)
    error = load_cmd.validate(board)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    result = load_cmd.execute(board)
    print(result)

    # 2. Apply placement script if provided
    if args.placement:
        print(f"Applying placement from {args.placement}...")
        if not args.placement.exists():
            print(f"Error: Placement file not found: {args.placement}", file=sys.stderr)
            return 1

        with open(args.placement, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                parts = line.upper().split()
                if parts[0] == 'MOVE' and 'TO' in parts:
                    try:
                        ref = parts[1]
                        to_idx = parts.index('TO')
                        x = float(parts[to_idx + 1])
                        y = float(parts[to_idx + 2])
                        rotation = 0
                        if 'ROTATION' in parts:
                            rot_idx = parts.index('ROTATION')
                            rotation = float(parts[rot_idx + 1])

                        move_cmd = MoveCommand(ref, x, y, rotation)
                        error = move_cmd.validate(board)
                        if error:
                            print(f"  Line {line_num}: {error}")
                            continue
                        move_cmd.execute(board)
                    except (ValueError, IndexError) as e:
                        print(f"  Line {line_num}: Parse error: {e}")

        print(f"  Placed {len(board.components)} components")

    # 3. Save to KiCad PCB
    print(f"Saving to {args.output}...")
    save_cmd = SaveCommand(args.output)
    error = save_cmd.validate(board)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    result = save_cmd.execute(board)
    print(result)

    return 0


def cmd_route(args) -> int:
    """Autoroute existing PCB file using pcbnew SDK."""
    try:
        from pcb_tool.kicad_loader import load_board_from_kicad, write_traces_to_kicad
        import pcbnew
    except ImportError:
        print("Error: pcbnew not available. Use system Python.", file=sys.stderr)
        return 1

    if not args.pcb.exists():
        print(f"Error: PCB file not found: {args.pcb}", file=sys.stderr)
        return 1

    print(f"Loading {args.pcb}...")
    kicad_board = pcbnew.LoadBoard(str(args.pcb))
    board = load_board_from_kicad(kicad_board)

    net_name = args.net or "ALL"
    print(f"Routing {net_name}...")
    autoroute_cmd = AutoRouteCommand(net_name=net_name)
    error = autoroute_cmd.validate(board)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    result = autoroute_cmd.execute(board)
    print(result)

    write_traces_to_kicad(board, kicad_board)

    output_path = args.output or args.pcb
    kicad_board.Save(str(output_path))
    print(f"Saved routed board to {output_path}")
    return 0


def cmd_repl(args) -> int:
    """Run interactive REPL mode."""
    repl = REPL()

    # Handle --batch
    if args.batch:
        print(f"Executing commands from {args.batch}")
        with open(args.batch, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.rstrip('\r\n').strip()

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

    # Interactive mode
    repl.run()
    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog='pardal',
        description='PCB layout tool with placement, autorouting, and DRC',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pardal build project.net -p placement.txt -o board.kicad_pcb
  pardal build project.net -o board.kicad_pcb --route --no-drc
  pardal drc board.kicad_pcb
  pardal place project.net -p placement.txt -o board.kicad_pcb
  pardal repl
  pardal repl --batch commands.txt
"""
    )

    parser.add_argument(
        '--version',
        action='version',
        version=f'pardal {__version__}'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # pardal build
    build_parser = subparsers.add_parser(
        'build',
        help='Build PCB from netlist (load + place + route + save + DRC)',
        description='Load netlist, apply placement, optionally autoroute, save PCB, run DRC'
    )
    build_parser.add_argument('netlist', type=Path, help='Input netlist file (.net)')
    build_parser.add_argument('-p', '--placement', type=Path,
                              help='Placement script with MOVE commands')
    build_parser.add_argument('-o', '--output', type=Path, required=True,
                              help='Output KiCad PCB file (.kicad_pcb)')
    build_parser.add_argument('--route', action='store_true',
                              help='Run autorouter after placement')
    build_parser.add_argument('--no-drc', action='store_true',
                              help='Skip DRC check after save')
    build_parser.add_argument('--finalize', action='store_true',
                              help='Replace simplified footprints with KiCad library versions (requires system Python)')

    # pardal drc
    drc_parser = subparsers.add_parser(
        'drc',
        help='Run DRC check on PCB file',
        description='Run KiCad Design Rule Check via kicad-cli'
    )
    drc_parser.add_argument('pcb', type=Path, help='Input PCB file (.kicad_pcb)')
    drc_parser.add_argument('-o', '--output', type=Path,
                            help='Output report file (default: temp file)')
    drc_parser.add_argument('--format', choices=['text', 'json'], default='text',
                            help='Output format (default: text)')

    # pardal place
    place_parser = subparsers.add_parser(
        'place',
        help='Place components from netlist (no routing)',
        description='Load netlist, apply placement, save PCB without routing'
    )
    place_parser.add_argument('netlist', type=Path, help='Input netlist file (.net)')
    place_parser.add_argument('-p', '--placement', type=Path,
                              help='Placement script with MOVE commands')
    place_parser.add_argument('-o', '--output', type=Path, required=True,
                              help='Output KiCad PCB file (.kicad_pcb)')

    # pardal route
    route_parser = subparsers.add_parser(
        'route',
        help='Autoroute existing PCB file',
        description='Run autorouter on existing KiCad PCB file'
    )
    route_parser.add_argument('pcb', type=Path, help='Input PCB file (.kicad_pcb)')
    route_parser.add_argument('-o', '--output', type=Path,
                              help='Output PCB file (default: overwrite input)')
    route_parser.add_argument('--net', help='Route specific net (default: ALL)')

    # pardal repl
    repl_parser = subparsers.add_parser(
        'repl',
        help='Interactive REPL mode',
        description='Start interactive Read-Eval-Print Loop'
    )
    repl_parser.add_argument('--batch', type=Path,
                             help='Execute commands from batch file')

    args = parser.parse_args()

    if args.command == 'build':
        return cmd_build(args)
    elif args.command == 'drc':
        return cmd_drc(args)
    elif args.command == 'place':
        return cmd_place(args)
    elif args.command == 'route':
        return cmd_route(args)
    elif args.command == 'repl':
        return cmd_repl(args)
    else:
        parser.print_help()
        return 0


if __name__ == '__main__':
    sys.exit(main())
