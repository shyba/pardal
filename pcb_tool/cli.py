#!/usr/bin/env python3
"""Pardal PCB Tool - CLI entry point.

Provides subcommands for PCB operations:
- build: Load netlist, place components, optionally route, save with DRC
- drc: Run DRC check on existing PCB
- freeroute: Autoroute via FreeRouting (optional)
- place: Place components from netlist
- route: Autoroute existing PCB
- repl: Interactive REPL mode
"""

import argparse
import sys
from pathlib import Path

from pcb_tool import __version__
from pcb_tool.data_model import Board
from pcb_tool.commands import LoadCommand, SaveCommand, MoveCommand, AutoRouteCommand
from pcb_tool.drc import run_drc, format_drc_report, check_kicad_cli
from pcb_tool.repl import REPL


def _check_pcbnew_available(command_name: str) -> bool:
    """Check pcbnew availability with helpful error message.

    Args:
        command_name: Name of the command requiring pcbnew (for error message)

    Returns:
        True if pcbnew is available, False otherwise
    """
    try:
        import pcbnew

        return True
    except ImportError:
        print(
            f"Error: '{command_name}' requires KiCad Python SDK (pcbnew).",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        print(
            "pcbnew is only available in system Python, not virtual environments.",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        print("Solutions:", file=sys.stderr)
        print("  1. Run with system Python + venv packages:", file=sys.stderr)
        print(
            "     PYTHONPATH=$(python -c 'import site; print(site.getsitepackages()[0])') \\",
            file=sys.stderr,
        )
        print(
            f"       /usr/bin/python3 -m pcb_tool.cli {command_name} ...",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        print("  2. Use pardal-finalize (system Python entry point):", file=sys.stderr)
        print(
            "     /usr/bin/python3 -m pcb_tool.finalize input.kicad_pcb output.kicad_pcb",
            file=sys.stderr,
        )
        return False


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

        with open(args.placement, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Parse MOVE command
                parts = line.upper().split()
                if parts[0] == "MOVE" and "TO" in parts:
                    try:
                        ref = parts[1]
                        to_idx = parts.index("TO")
                        x = float(parts[to_idx + 1])
                        y = float(parts[to_idx + 2])
                        rotation = 0
                        if "ROTATION" in parts:
                            rot_idx = parts.index("ROTATION")
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
        if not _check_pcbnew_available("build --finalize"):
            print("Continuing without finalization...", file=sys.stderr)
        else:
            print("Finalizing board with KiCad library footprints...")
            from pcb_tool.finalize import finalize_board

            success, msg = finalize_board(args.output, args.output)
            print(msg)
            if not success:
                print(f"Error: Finalization failed", file=sys.stderr)
                return 1

    # 5. Run DRC unless skipped
    if not args.no_drc:
        if not check_kicad_cli():
            print("Warning: kicad-cli not found, skipping DRC")
        else:
            print("Running DRC...")
            drc_result = run_drc(args.output)

            # Always print warnings
            if drc_result.warnings > 0:
                print(f"DRC: {drc_result.warnings} warning(s)")
                for v in drc_result.violations:
                    if v.severity == "warning":
                        print(f"  WARNING: {v.description}")

            # Determine if build should fail
            has_errors = drc_result.errors > 0
            has_warnings_as_errors = args.warnerr and drc_result.warnings > 0

            if has_errors or has_warnings_as_errors:
                print(format_drc_report(drc_result))
                if not args.force:
                    if has_warnings_as_errors and not has_errors:
                        print(
                            "Build failed: warnings treated as errors (--warnerr). Use --force to override."
                        )
                    else:
                        print(
                            "Build failed: DRC errors found. Use --force to override."
                        )
                    return 1
                else:
                    print("WARNING: Continuing despite DRC issues (--force)")
            elif drc_result.errors == 0 and drc_result.warnings == 0:
                print("DRC: PASSED (0 errors, 0 warnings)")

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
    if output_path and args.format == "text":
        # For text format, use .txt extension
        if output_path.suffix == ".json":
            output_path = output_path.with_suffix(".txt")

    result = run_drc(args.pcb, output_path)

    if args.format == "json":
        # JSON output - just report the path
        print(f"DRC report saved to: {result.report_path}")
    else:
        # Text output
        print(format_drc_report(result, verbose=True))

    return 0 if result.success else 1


def cmd_freeroute(args) -> int:
    """Route a KiCad PCB using FreeRouting (Specctra DSN/SES) via docker."""
    # Lazy import to keep FreeRouting integration optional and easy to remove.
    from pcb_tool.freerouting_backend import (  # noqa: PLC0415
        FreeroutingRunConfig,
        freeroute_kicad_pcb,
        run_kicad9_drc,
    )

    input_pcb: Path = args.input
    output_pcb: Path = args.output

    if not input_pcb.exists():
        print(f"Error: PCB file not found: {input_pcb}", file=sys.stderr)
        return 1

    ignore_net_classes = tuple(
        n.strip() for n in str(args.ignore_net_classes).split(",") if n.strip()
    )

    config = FreeroutingRunConfig(
        max_passes=args.max_passes,
        fanout=not args.no_fanout,
        fanout_max_passes=args.fanout_max_passes,
        threads=args.threads,
        optimizer_improvement_threshold=args.oit,
        save_intermediate=args.save_intermediate,
        disable_logging=not args.enable_logging,
        log_level=args.log_level,
        random_seed=args.random_seed,
        via_costs=args.via_costs,
        start_ripup_costs=args.start_ripup_costs,
        ignore_net_classes=ignore_net_classes,
        strip_planes=args.strip_planes,
        router_job_timeout=args.router_job_timeout,
        router_max_threads=args.router_max_threads,
        trace_pull_tight_accuracy=args.trace_pull_tight_accuracy,
    )

    try:
        freeroute_kicad_pcb(input_pcb, output_pcb, config=config)
    except Exception as e:
        print(f"Error: FreeRouting failed: {e}", file=sys.stderr)
        return 1

    if args.drc_json:
        try:
            run_kicad9_drc(output_pcb, args.drc_json)
        except Exception as e:
            print(f"Warning: KiCad 9 DRC failed: {e}", file=sys.stderr)

    print(f"Wrote routed board: {output_pcb}")
    if args.drc_json:
        print(f"Wrote DRC report: {args.drc_json}")
    return 0


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

        with open(args.placement, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = line.upper().split()
                if parts[0] == "MOVE" and "TO" in parts:
                    try:
                        ref = parts[1]
                        to_idx = parts.index("TO")
                        x = float(parts[to_idx + 1])
                        y = float(parts[to_idx + 2])
                        rotation = 0
                        if "ROTATION" in parts:
                            rot_idx = parts.index("ROTATION")
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
    if not _check_pcbnew_available("route"):
        return 1

    from pcb_tool.kicad_loader import load_board_from_kicad, write_traces_to_kicad
    from pcb_tool.data_model import STANDARD_LAYER_STACKS
    import pcbnew

    if not args.pcb.exists():
        print(f"Error: PCB file not found: {args.pcb}", file=sys.stderr)
        return 1

    print(f"Loading {args.pcb}...")
    kicad_board = pcbnew.LoadBoard(str(args.pcb))
    board = load_board_from_kicad(kicad_board)

    # Set layer stack based on --layers argument
    if args.layers and args.layers in STANDARD_LAYER_STACKS:
        board.layers = STANDARD_LAYER_STACKS[args.layers]
        print(f"Using {args.layers}-layer stack: {board.layers}")

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
        with open(args.batch, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.rstrip("\r\n").strip()

                if not line or line.startswith("#"):
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
        prog="pardal",
        description="PCB layout tool with placement, autorouting, and DRC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pardal build project.net -p placement.txt -o board.kicad_pcb
  pardal build project.net -o board.kicad_pcb --route --no-drc
  pardal drc board.kicad_pcb
  pardal place project.net -p placement.txt -o board.kicad_pcb
  pardal repl
  pardal repl --batch commands.txt
""",
    )

    parser.add_argument("--version", action="version", version=f"pardal {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # pardal build
    build_parser = subparsers.add_parser(
        "build",
        help="Build PCB from netlist (load + place + route + save + DRC)",
        description="Load netlist, apply placement, optionally autoroute, save PCB, run DRC",
    )
    build_parser.add_argument("netlist", type=Path, help="Input netlist file (.net)")
    build_parser.add_argument(
        "-p", "--placement", type=Path, help="Placement script with MOVE commands"
    )
    build_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output KiCad PCB file (.kicad_pcb)",
    )
    build_parser.add_argument(
        "--route", action="store_true", help="Run autorouter after placement"
    )
    build_parser.add_argument(
        "--no-drc", action="store_true", help="Skip DRC check after save"
    )
    build_parser.add_argument(
        "--force", action="store_true", help="Continue build even if DRC has errors"
    )
    build_parser.add_argument(
        "--warnerr", action="store_true", help="Treat DRC warnings as errors"
    )
    build_parser.add_argument(
        "--finalize",
        action="store_true",
        help="Replace simplified footprints with KiCad library versions (requires system Python)",
    )

    # pardal drc
    drc_parser = subparsers.add_parser(
        "drc",
        help="Run DRC check on PCB file",
        description="Run KiCad Design Rule Check via kicad-cli",
    )
    drc_parser.add_argument("pcb", type=Path, help="Input PCB file (.kicad_pcb)")
    drc_parser.add_argument(
        "-o", "--output", type=Path, help="Output report file (default: temp file)"
    )
    drc_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    # pardal freeroute (FreeRouting via Specctra DSN/SES)
    freeroute_parser = subparsers.add_parser(
        "freeroute",
        help="Autoroute via FreeRouting (DSN/SES, docker-based KiCad 9)",
        description="Export Specctra DSN via KiCad 9, run FreeRouting, import SES, save board",
    )
    freeroute_parser.add_argument("input", type=Path, help="Input PCB file (.kicad_pcb)")
    freeroute_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output KiCad PCB file (.kicad_pcb)",
    )
    freeroute_parser.add_argument(
        "--max-passes", type=int, default=50, help="FreeRouting router max passes"
    )
    freeroute_parser.add_argument(
        "--no-fanout", action="store_true", help="Disable FreeRouting fanout pass"
    )
    freeroute_parser.add_argument(
        "--fanout-max-passes",
        type=int,
        default=20,
        help="FreeRouting fanout max passes",
    )
    freeroute_parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="Optimizer thread count (default: FreeRouting default; 0 disables optimizer)",
    )
    freeroute_parser.add_argument(
        "--oit",
        type=float,
        default=None,
        help="Optimizer improvement threshold per pass (maps to FreeRouting -oit)",
    )
    freeroute_parser.add_argument(
        "--save-intermediate",
        action="store_true",
        help="Save intermediate routing snapshots (maps to FreeRouting -im)",
    )
    freeroute_parser.add_argument(
        "--enable-logging",
        action="store_true",
        help="Enable FreeRouting logging (omit -dl); useful for debugging slow routes",
    )
    freeroute_parser.add_argument(
        "--log-level",
        default=None,
        help="FreeRouting console log level (maps to -ll; e.g. INFO, DEBUG, 4, 5)",
    )
    freeroute_parser.add_argument(
        "--random-seed",
        type=int,
        default=None,
        help="Deterministic routing seed (maps to FreeRouting -random_seed)",
    )
    freeroute_parser.add_argument(
        "--via-costs", type=int, default=50, help="Via cost heuristic"
    )
    freeroute_parser.add_argument(
        "--start-ripup-costs",
        type=int,
        default=100,
        help="Initial ripup cost heuristic",
    )
    freeroute_parser.add_argument(
        "--ignore-net-classes",
        default="",
        help="Comma-separated net class names to ignore (maps to FreeRouting -inc)",
    )
    freeroute_parser.add_argument(
        "--strip-planes",
        action="store_true",
        help="Remove copper plane polygons from DSN before routing (can speed routing)",
    )
    freeroute_parser.add_argument(
        "--router-job-timeout",
        default=None,
        help="FreeRouting router job timeout (HH:MM:SS) (maps to --router.job_timeout=...)",
    )
    freeroute_parser.add_argument(
        "--router-max-threads",
        type=int,
        default=None,
        help="FreeRouting router max threads (maps to --router.max_threads=...)",
    )
    freeroute_parser.add_argument(
        "--trace-pull-tight-accuracy",
        type=int,
        default=None,
        help="FreeRouting trace pull-tight accuracy (maps to --router.trace_pull_tight_accuracy=...)",
    )
    freeroute_parser.add_argument(
        "--drc-json",
        type=Path,
        default=None,
        help="If set, runs KiCad 9 DRC and writes JSON report",
    )

    # pardal place
    place_parser = subparsers.add_parser(
        "place",
        help="Place components from netlist (no routing)",
        description="Load netlist, apply placement, save PCB without routing",
    )
    place_parser.add_argument("netlist", type=Path, help="Input netlist file (.net)")
    place_parser.add_argument(
        "-p", "--placement", type=Path, help="Placement script with MOVE commands"
    )
    place_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output KiCad PCB file (.kicad_pcb)",
    )

    # pardal route
    route_parser = subparsers.add_parser(
        "route",
        help="Autoroute existing PCB file",
        description="Run autorouter on existing KiCad PCB file",
    )
    route_parser.add_argument("pcb", type=Path, help="Input PCB file (.kicad_pcb)")
    route_parser.add_argument(
        "-o", "--output", type=Path, help="Output PCB file (default: overwrite input)"
    )
    route_parser.add_argument("--net", help="Route specific net (default: ALL)")
    route_parser.add_argument(
        "--layers",
        type=int,
        choices=[2, 4, 6, 8],
        default=2,
        help="Number of copper layers (2, 4, 6, or 8). Default: 2",
    )

    # pardal repl
    repl_parser = subparsers.add_parser(
        "repl",
        help="Interactive REPL mode",
        description="Start interactive Read-Eval-Print Loop",
    )
    repl_parser.add_argument(
        "--batch", type=Path, help="Execute commands from batch file"
    )

    args = parser.parse_args()

    if args.command == "build":
        return cmd_build(args)
    elif args.command == "drc":
        return cmd_drc(args)
    elif args.command == "freeroute":
        return cmd_freeroute(args)
    elif args.command == "place":
        return cmd_place(args)
    elif args.command == "route":
        return cmd_route(args)
    elif args.command == "repl":
        return cmd_repl(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
