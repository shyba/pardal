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
import json
import tempfile
import subprocess
import sys
import zipfile
from pathlib import Path

from pardal import __version__
from pardal.data_model import Board
from pardal.commands import LoadCommand, SaveCommand, MoveCommand, AutoRouteCommand
from pardal.drc import run_drc, format_drc_report, check_kicad_cli
from pardal.production_summary import verify_production_summary
from pardal.release_verification import verify_release_package
from pardal.validation_results import verify_validation_results
from pardal.physical.diagnostics import (
    load_route_diagnostics_dashboard,
    write_diagnostics_dashboard,
)
from pardal.repl import REPL


class _StoreWithExplicitFlag(argparse.Action):
    """Store an argument value and record that the user set it explicitly."""

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        setattr(namespace, f"{self.dest}_explicit", True)


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
            f"       /usr/bin/python3 -m pardal.cli {command_name} ...",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        print("  2. Use pardal-finalize (system Python entry point):", file=sys.stderr)
        print(
            "     /usr/bin/python3 -m pardal.finalize input.kicad_pcb output.kicad_pcb",
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
            from pardal.finalize import finalize_board

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
        from shutil import which
        from pardal.drc import _kicad_cli_supports_pcb_drc

        if which("kicad-cli") is None:
            print(
                "Error: kicad-cli not found. Install KiCad (8+) or set PARDAL_KICAD_DOCKER=1.",
                file=sys.stderr,
            )
        elif not _kicad_cli_supports_pcb_drc():
            print(
                "Error: local kicad-cli does not support `pcb drc` (KiCad 8+ required). "
                "Upgrade KiCad or set PARDAL_KICAD_DOCKER=1 to run KiCad 9 in docker.",
                file=sys.stderr,
            )
        else:
            print(
                "Error: KiCad DRC is not available (set PARDAL_KICAD_DOCKER=1 for docker fallback).",
                file=sys.stderr,
            )
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
    from pardal.freerouting_backend import (  # noqa: PLC0415
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
    from pardal.data_model import STANDARD_LAYER_STACKS
    from pardal.kicad_project_loader import apply_project_net_settings

    if not args.pcb.exists():
        print(f"Error: PCB file not found: {args.pcb}", file=sys.stderr)
        return 1

    net_name = args.net or "ALL"
    output_path = args.output or args.pcb

    try:
        import pcbnew  # type: ignore
    except ImportError:
        # Fallback: text loader + minimal writer (no pcbnew required).
        from pardal.kicad_text_loader import load_board_kicad_pcb
        from pardal.kicad_writer import KicadWriter

        print(f"Loading {args.pcb} (text loader)...")
        load_result = load_board_kicad_pcb(args.pcb)
        board = load_result.board
        if load_result.warnings:
            print(f"Warning: {len(load_result.warnings)} load warnings (continuing)")
        proj_warnings = apply_project_net_settings(board, args.pcb)
        if proj_warnings:
            print(f"Warning: {len(proj_warnings)} project warnings (continuing)")

        if args.layers and args.layers in STANDARD_LAYER_STACKS:
            board.layers = STANDARD_LAYER_STACKS[args.layers]
            print(f"Using {args.layers}-layer stack: {board.layers}")

        print(f"Routing {net_name}...")
        autoroute_cmd = AutoRouteCommand(net_name=net_name)
        error = autoroute_cmd.validate(board)
        if error:
            print(f"Error: {error}", file=sys.stderr)
            return 1
        result = autoroute_cmd.execute(board)
        print(result)

        KicadWriter().write(board, output_path)
        print(f"Saved routed board to {output_path} (minimal .kicad_pcb)")
        return 0

    # pcbnew-backed route: preserves the existing board file and writes tracks/vias in-place.
    if not _check_pcbnew_available("route"):
        return 1

    from pardal.kicad_loader import load_board_from_kicad, write_traces_to_kicad

    print(f"Loading {args.pcb} (pcbnew SDK)...")
    kicad_board = pcbnew.LoadBoard(str(args.pcb))
    board = load_board_from_kicad(kicad_board)
    proj_warnings = apply_project_net_settings(board, args.pcb)
    if proj_warnings:
        print(f"Warning: {len(proj_warnings)} project warnings (continuing)")

    if args.layers and args.layers in STANDARD_LAYER_STACKS:
        board.layers = STANDARD_LAYER_STACKS[args.layers]
        print(f"Using {args.layers}-layer stack: {board.layers}")
    else:
        try:
            layer_count = int(kicad_board.GetCopperLayerCount())
        except Exception:
            layer_count = 0
        if layer_count in STANDARD_LAYER_STACKS:
            board.layers = STANDARD_LAYER_STACKS[layer_count]
            print(f"Using inferred {layer_count}-layer stack: {board.layers}")

    print(f"Routing {net_name}...")
    autoroute_cmd = AutoRouteCommand(net_name=net_name)
    error = autoroute_cmd.validate(board)
    if error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    result = autoroute_cmd.execute(board)
    print(result)

    write_traces_to_kicad(board, kicad_board)
    kicad_board.Save(str(output_path))
    # Keep project settings consistent for KiCad CLI DRC: copy sibling `.kicad_pro/.kicad_prl`
    # when the output file name differs.
    if output_path != args.pcb:
        in_pro = args.pcb.with_suffix(".kicad_pro")
        out_pro = output_path.with_suffix(".kicad_pro")
        in_prl = args.pcb.with_suffix(".kicad_prl")
        out_prl = output_path.with_suffix(".kicad_prl")
        try:
            if in_pro.exists():
                out_pro.write_text(in_pro.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            if in_prl.exists():
                out_prl.write_text(in_prl.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        except Exception:
            pass
    print(f"Saved routed board to {output_path}")
    return 0


def cmd_rust_route(args) -> int:
    """Deprecated: route via docker pcbnew extraction + host backend router.

    Kept for backwards compatibility. Prefer `pardal backend-route`.
    """
    print("warning: `pardal rust-route` is deprecated; use `pardal backend-route`", file=sys.stderr)
    return cmd_backend_route(args)


def cmd_backend_route(args) -> int:
    """Route a KiCad PCB via docker pcbnew extraction + host router + docker apply (Mojo)."""
    from pardal.api.route_kicad_docker import route_kicad_via_docker

    if not args.pcb.exists():
        print(f"Error: PCB file not found: {args.pcb}", file=sys.stderr)
        return 1

    try:
        route_kicad_via_docker(
            in_pcb=args.pcb,
            out_pcb=args.output,
            docker_image=str(args.docker_image),
            resolution_mm=float(args.resolution),
            inflate_mm=None if args.inflate is None else float(args.inflate),
            cfg_json=args.cfg,
            routes_json=args.routes_json,
            problem_json=args.problem_json,
            extract_timeout_s=args.extract_timeout_s,
            route_timeout_s=args.route_timeout_s,
            apply_timeout_s=args.apply_timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        print(f"Error: backend-route timed out: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error: backend-route failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(f"Saved routed board to {args.output}")
    return 0


def _format_csv(values) -> str:
    return ",".join(str(value) for value in sorted(values))


def _print_bucket_reasons(bucket) -> None:
    grouped = {}
    for source_reason in bucket.source_reasons:
        source = (
            f"{source_reason.name}@{source_reason.source}"
            if source_reason.source
            else source_reason.name
        )
        grouped.setdefault(source_reason.reason, set()).add(source)
    if not grouped:
        return
    items = sorted(grouped.items())
    if len(items) == 1:
        reason, names = items[0]
        if bucket.kind == "group":
            print(f"    reason: {reason}")
            print(f"    sources: {_format_csv(names)}")
        else:
            print(f"    reason: {_format_csv(names)}: {reason}")
        return

    print("    reasons:")
    for reason, names in items[:3]:
        print(f"      {_format_csv(names)}: {reason}")
    if len(items) > 3:
        print(f"      ... +{len(items) - 3} more reasons")


def _board_output_base_name(output_path: Path) -> str:
    stem = output_path.stem
    if stem.endswith(".routed_physical"):
        return stem[: -len(".routed_physical")]
    return stem


def _apply_production_output_dir_preset(args) -> None:
    production_output_dir = getattr(args, "production_output_dir", None)
    if production_output_dir is None:
        return

    board_base = _board_output_base_name(args.output)
    defaults = {
        "drc_report": production_output_dir / "routed-physical-drc.rpt",
        "bom_output": production_output_dir / f"{board_base}.bom.csv",
        "pnp_output": production_output_dir / f"{board_base}.pnp.csv",
        "jlc_bom_output": production_output_dir / f"{board_base}.jlc.bom.csv",
        "jlc_pnp_output": production_output_dir / f"{board_base}.jlc.pnp.csv",
        "production_report": production_output_dir / "production-checks.json",
        "drc_diagnostics_report": production_output_dir / "drc-diagnostics.json",
        "route_diagnostics_report": production_output_dir / "route-diagnostics.json",
        "gerber_output_dir": production_output_dir / "gerbers",
        "drill_output_dir": production_output_dir / "drill",
        "build_summary_output": production_output_dir / "build-summary.json",
        "manufacturing_archive_output": production_output_dir / "manufacturing-package.zip",
    }
    for attr, value in defaults.items():
        if getattr(args, attr) is None:
            setattr(args, attr, value)

    if not getattr(args, "production_report_format_explicit", False):
        args.production_report_format = "json"
    if not getattr(args, "drc_diagnostics_format_explicit", False):
        args.drc_diagnostics_format = "json"


def _project_provenance_output_dir(args) -> Path | None:
    if getattr(args, "production_output_dir", None) is not None:
        return args.production_output_dir
    build_summary_output = getattr(args, "build_summary_output", None)
    if build_summary_output is not None:
        return build_summary_output.parent
    return None


def _load_compile_project_context(args):
    if getattr(args, "production_check", False) and getattr(args, "allow_unlocked", False):
        raise ValueError("--allow-unlocked is invalid with --production-check")
    if getattr(args, "production_check", False) and getattr(args, "allow_absolute_paths", False):
        raise ValueError("--allow-absolute-paths is invalid with --production-check")
    project = getattr(args, "project", None)
    if project is None:
        if getattr(args, "production_check", False):
            raise ValueError(
                "compile-physical --production-check requires --project and pardal.lock"
            )
        return None
    from pardal.project.context import create_project_context, require_project_lock

    context_kwargs = {"target": getattr(args, "target", "default")}
    if getattr(args, "allow_absolute_paths", False):
        context_kwargs["allow_absolute_paths"] = True
    ctx = create_project_context(project, **context_kwargs)
    _validate_cli_check_overrides(args, ctx)
    if getattr(args, "production_check", False) or _build_target_requires_lock(ctx):
        require_project_lock(ctx)
    return ctx


def _disable_check_reasons_for_args(args, *, production_mode: bool) -> dict[str, str]:
    disabled = list(getattr(args, "disable_check", []) or [])
    reason = str(getattr(args, "reason", "") or "").strip()
    if disabled and production_mode and not reason:
        raise ValueError("--disable-check requires --reason in production mode")
    if not disabled:
        return {}
    return {check_id: reason for check_id in disabled if reason}


def _allow_network_checks_for_args(args, ctx) -> bool:
    if getattr(args, "allow_network_checks", False):
        return True
    if ctx is None:
        return False
    build_target = getattr(ctx, "build_target", None)
    options = getattr(build_target, "options", {}) if build_target is not None else {}
    return bool(options.get("allow_network_checks", False))


def _build_target_requires_lock(ctx) -> bool:
    build_target = getattr(ctx, "build_target", None)
    options = getattr(build_target, "options", {}) if build_target is not None else {}
    return bool(options.get("require_lock", False))


def _validate_cli_check_overrides(args, ctx) -> None:
    manifest = getattr(ctx, "manifest", None)
    if manifest is None:
        return
    from pardal.checks.visibility import project_registered_checks
    from pardal.production_checks.registry import registry
    from pardal.project.diagnostics import ProjectConfigError

    known = registry.registered_ids() | set(project_registered_checks(ctx))
    overrides = {
        "cli.enable_check": list(getattr(args, "enable_check", []) or []),
        "cli.disable_check": list(getattr(args, "disable_check", []) or []),
    }
    for field, check_ids in overrides.items():
        for check_id in check_ids:
            if check_id in known:
                continue
            raise ProjectConfigError(
                "profile.check_unknown",
                f"unknown CLI production check requested: {check_id}",
                path=getattr(manifest, "path", None),
                field=field,
            )


def _write_compile_project_provenance(args, ctx):
    if ctx is None:
        return None
    from pardal.project.provenance import write_project_provenance_artifacts

    artifacts = write_project_provenance_artifacts(
        ctx,
        output_dir=_project_provenance_output_dir(args),
        allow_network_checks=_allow_network_checks_for_args(args, ctx),
        cli_profiles=_profile_overrides_for_args(args),
        cli_enable_checks=list(getattr(args, "enable_check", []) or []),
        cli_disable_checks=list(getattr(args, "disable_check", []) or []),
        cli_disable_check_reasons=_disable_check_reasons_for_args(
            args,
            production_mode=getattr(args, "production_check", False),
        ),
    )
    print(f"Saved package resolution to {artifacts.package_resolution}")
    print(f"Saved profile resolution to {artifacts.profile_resolution}")
    return artifacts


def _write_production_check_project_provenance(args, ctx):
    output_dir = getattr(args, "output_dir", None)
    if ctx is None or output_dir is None:
        return None
    from pardal.project.provenance import write_project_provenance_artifacts

    artifacts = write_project_provenance_artifacts(
        ctx,
        output_dir=output_dir,
        allow_network_checks=_allow_network_checks_for_args(args, ctx),
        cli_profiles=_profile_overrides_for_args(args),
        cli_enable_checks=list(getattr(args, "enable_check", []) or []),
        cli_disable_checks=list(getattr(args, "disable_check", []) or []),
        cli_disable_check_reasons=_disable_check_reasons_for_args(
            args,
            production_mode=True,
        ),
    )
    print(f"Saved package resolution to {artifacts.package_resolution}", file=sys.stderr)
    print(f"Saved profile resolution to {artifacts.profile_resolution}", file=sys.stderr)
    return artifacts


def _augment_build_summary_with_project_parts(args, ctx, provenance_artifacts=None) -> None:
    if ctx is None or getattr(args, "build_summary_output", None) is None:
        return
    summary_path = args.build_summary_output
    if not summary_path.exists():
        return
    from pardal.project.provenance import package_resolution_for_context

    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    package_resolution = package_resolution_for_context(ctx)
    payload["package_parts"] = {
        "schema": "pardal.package_parts_summary/v1",
        "part_aliases": package_resolution.get("part_aliases", {}),
        "selected_components": package_resolution.get("selected_components", {}),
    }
    payload["package_physical"] = {
        "schema": "pardal.package_physical_summary/v1",
        "physical_libraries": package_resolution.get("physical_libraries", {}),
        "route_policies": package_resolution.get("route_policies", {}),
    }
    payload["project_overrides"] = _project_override_summary(args, ctx)
    payload["project_provenance"] = _project_provenance_summary(
        ctx,
        provenance_artifacts=provenance_artifacts,
    )
    summary_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _refresh_archive_build_summary(
        getattr(args, "manufacturing_archive_output", None),
        summary_path,
    )


def _refresh_archive_build_summary(archive_path: Path | None, summary_path: Path) -> None:
    if archive_path is None or not archive_path.exists():
        return
    if archive_path.suffix.lower() != ".zip":
        return
    summary_text = summary_path.read_text(encoding="utf-8")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(
        prefix=f".{archive_path.name}.tmp-",
        suffix=".zip",
        dir=archive_path.parent,
        delete=False,
    )
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        with (
            zipfile.ZipFile(archive_path, "r") as source_archive,
            zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as output_archive,
        ):
            replaced = False
            for info in source_archive.infolist():
                if info.filename == "build-summary.json":
                    output_archive.writestr(info, summary_text)
                    replaced = True
                else:
                    output_archive.writestr(info, source_archive.read(info.filename))
            if not replaced:
                output_archive.writestr("build-summary.json", summary_text)
        temp_path.replace(archive_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _project_provenance_summary(ctx, *, provenance_artifacts=None) -> dict[str, object]:
    profile_set = getattr(ctx, "profile_set", None)
    return {
        "schema": "pardal.project_provenance_summary/v1",
        "package_resolution": (
            str(provenance_artifacts.package_resolution)
            if provenance_artifacts is not None
            else None
        ),
        "profile_resolution": (
            str(provenance_artifacts.profile_resolution)
            if provenance_artifacts is not None
            else None
        ),
        "loaded_check_exports": list(getattr(ctx, "loaded_check_exports", ()) or ()),
        "profiles": {
            "requested": list(getattr(profile_set, "requested", ()) or ()),
            "expanded": list(getattr(profile_set, "expanded", ()) or ()),
            "enabled_checks": sorted(getattr(profile_set, "enabled_checks", ()) or ()),
            "disabled_checks": sorted(getattr(profile_set, "disabled_checks", ()) or ()),
            "severity": dict(getattr(profile_set, "severity", {}) or {}),
            "requires_contract": dict(getattr(profile_set, "requires_contract", {}) or {}),
        },
    }


def _project_override_summary(args, ctx) -> dict[str, object]:
    source_contract_path = _project_source_contract_path(args, ctx)
    explicit_source_contract = getattr(args, "source_contract", None)
    return {
        "schema": "pardal.project_overrides/v1",
        "project": str(getattr(args, "project", "")),
        "target": str(getattr(args, "target", "default")),
        "production_profiles": _profile_overrides_for_args(args),
        "enable_checks": list(getattr(args, "enable_check", []) or []),
        "disable_checks": list(getattr(args, "disable_check", []) or []),
        "disable_check_reasons": _disable_check_reasons_for_args(
            args,
            production_mode=getattr(args, "production_check", False),
        ),
        "source_contract": str(source_contract_path) if source_contract_path is not None else None,
        "source_contract_override": (
            str(explicit_source_contract) if explicit_source_contract is not None else None
        ),
        "warnerr": bool(getattr(args, "warnerr", False)),
    }


def _profile_overrides_for_args(args) -> list[str]:
    return list(getattr(args, "production_profile", []) or [])


def _project_source_contract_path(args, ctx) -> Path | None:
    explicit = getattr(args, "source_contract", None)
    if explicit is not None:
        return explicit
    if ctx is None:
        return None
    return getattr(getattr(ctx, "source_contract", None), "path", None)


def _project_spec_overlay(args, ctx):
    if ctx is None:
        return None
    footprint_refs = _write_project_footprint_library(args, ctx)
    selected = _selected_project_footprints(ctx, footprint_refs=footprint_refs)
    if not selected:
        return None
    import yaml

    spec_path = args.spec
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return None
    parts = data.setdefault("parts", {})
    if not isinstance(parts, dict):
        return None
    aliases = data.setdefault("footprint_aliases", {})
    if not isinstance(aliases, dict):
        aliases = {}
        data["footprint_aliases"] = aliases
    changed = False
    for ref, selected_footprint in selected.items():
        entry = parts.get(ref)
        if not isinstance(entry, dict):
            continue
        raw_footprint = entry.get("footprint")
        if raw_footprint and str(raw_footprint) != selected_footprint:
            aliases[str(raw_footprint)] = selected_footprint
        if entry.get("footprint") != selected_footprint:
            entry["footprint"] = selected_footprint
            changed = True
    if not changed and not aliases:
        return None
    tmpdir = tempfile.TemporaryDirectory()
    overlay_path = Path(tmpdir.name) / spec_path.name
    overlay_path.write_text(
        yaml.safe_dump(data, sort_keys=False),
        encoding="utf-8",
    )
    return tmpdir, overlay_path


def _write_project_footprint_library(args, ctx) -> dict[str, str]:
    source_contract = getattr(ctx, "source_contract", None)
    components = getattr(source_contract, "components", {}) if source_contract is not None else {}
    footprints = getattr(ctx, "footprints", {}) or {}
    selected_ids = _selected_project_footprint_ids(ctx, components)
    package_footprints = {
        footprint_id: footprints[footprint_id]
        for footprint_id in sorted(selected_ids)
        if footprint_id in footprints and getattr(footprints[footprint_id], "source_path", None) is not None
    }
    if not package_footprints:
        return {}
    import shutil

    output_dir = args.output.parent
    pretty_dir = output_dir / "pardal-footprints.pretty"
    pretty_dir.mkdir(parents=True, exist_ok=True)
    refs: dict[str, str] = {}
    for footprint_id, footprint in package_footprints.items():
        source_path = footprint.source_path
        if source_path is None or not source_path.exists():
            continue
        target_name = f"{source_path.stem}.kicad_mod"
        shutil.copyfile(source_path, pretty_dir / target_name)
        refs[footprint_id] = f"pardal_project_footprints:{source_path.stem}"
    if refs:
        _write_fp_lib_table(output_dir, pretty_dir)
    return refs


def _write_fp_lib_table(output_dir: Path, pretty_dir: Path) -> None:
    rel = pretty_dir.relative_to(output_dir).as_posix()
    (output_dir / "fp-lib-table").write_text(
        (
            "(fp_lib_table\n"
            "  (lib (name \"pardal_project_footprints\")"
            "(type \"KiCad\")"
            f"(uri \"${{KIPRJMOD}}/{rel}\")"
            "(options \"\")"
            "(descr \"Pardal package footprints\"))\n"
            ")\n"
        ),
        encoding="utf-8",
    )


def _selected_project_footprints(ctx, *, footprint_refs: dict[str, str] | None = None) -> dict[str, str]:
    footprint_refs = footprint_refs or {}
    source_contract = getattr(ctx, "source_contract", None)
    components = getattr(source_contract, "components", {}) if source_contract is not None else {}
    parts = getattr(ctx, "parts", {}) or {}
    footprints = getattr(ctx, "footprints", {}) or {}
    selected: dict[str, str] = {}
    for ref, component in sorted(components.items()):
        footprint_id = _component_footprint_id(component, parts)
        if not footprint_id:
            continue
        if str(footprint_id) in footprint_refs:
            selected[str(ref)] = footprint_refs[str(footprint_id)]
            continue
        footprint = footprints.get(str(footprint_id))
        if footprint is None or not getattr(footprint, "kicad", None):
            continue
        selected[str(ref)] = str(footprint.kicad)
    return selected


def _selected_project_footprint_ids(ctx, components) -> set[str]:
    parts = getattr(ctx, "parts", {}) or {}
    selected: set[str] = set()
    for component in components.values():
        footprint_id = _component_footprint_id(component, parts)
        if footprint_id:
            selected.add(str(footprint_id))
    return selected


def _component_footprint_id(component, parts) -> str | None:
    footprint_id = component.get("footprint_id")
    if not footprint_id and component.get("part_id"):
        part = parts.get(str(component["part_id"]))
        footprint_id = getattr(part, "footprint", None) if part is not None else None
    return str(footprint_id) if footprint_id else None


def cmd_compile_physical(args) -> int:
    """Compile a text-defined physical design spec to a KiCad PCB."""
    _apply_production_output_dir_preset(args)
    try:
        project_context = _load_compile_project_context(args)
        from pardal.physical import (
            compile_physical,
            summarize_drc_unconnected,
        )

        spec_overlay = _project_spec_overlay(args, project_context)
        spec_for_compile = spec_overlay[1] if spec_overlay is not None else args.spec
        disable_check_reasons = _disable_check_reasons_for_args(
            args,
            production_mode=getattr(args, "production_check", False),
        )
        try:
            result = compile_physical(
                spec_for_compile,
                netlist_path=args.netlist,
                output_path=args.output,
                place_only=args.place_only,
                drc_report=args.drc_report,
                run_drc=not args.no_drc,
                strict=args.strict,
                enabled_route_groups=set(args.enable_route_group) if args.enable_route_group else None,
                probe_deferred_power=args.probe_deferred_power,
                production_check=args.production_check,
                bom_output=args.bom_output,
                pnp_output=args.pnp_output,
                jlc_bom_output=args.jlc_bom_output,
                jlc_pnp_output=args.jlc_pnp_output,
                gerber_output_dir=args.gerber_output_dir,
                drill_output_dir=args.drill_output_dir,
                production_report=args.production_report,
                production_report_format=args.production_report_format,
                drc_diagnostics_report=args.drc_diagnostics_report,
                drc_diagnostics_format=args.drc_diagnostics_format,
                route_diagnostics_report=args.route_diagnostics_report,
                build_summary_output=args.build_summary_output,
                manufacturing_archive_output=args.manufacturing_archive_output,
                include_helpers_in_exports=not args.exclude_helpers_in_exports,
                source_contract_path=_project_source_contract_path(args, project_context),
                enable_checks=getattr(args, "enable_check", []),
                disable_checks=getattr(args, "disable_check", []),
                disable_check_reasons=disable_check_reasons,
                production_profiles=_profile_overrides_for_args(args),
                warnerr=getattr(args, "warnerr", False),
                allow_network_checks=_allow_network_checks_for_args(args, project_context),
                project_context=project_context,
            )
        finally:
            if spec_overlay is not None:
                spec_overlay[0].cleanup()
        provenance_artifacts = _write_compile_project_provenance(args, project_context)
        _augment_build_summary_with_project_parts(
            args,
            project_context,
            provenance_artifacts=provenance_artifacts,
        )
    except Exception as e:
        diagnostics_dashboard = getattr(args, "diagnostics_dashboard", None)
        route_diagnostics_report = getattr(args, "route_diagnostics_report", None)
        if (
            diagnostics_dashboard is not None
            and route_diagnostics_report is not None
            and route_diagnostics_report.exists()
        ):
            dashboard = load_route_diagnostics_dashboard(route_diagnostics_report)
            write_diagnostics_dashboard(diagnostics_dashboard, dashboard)
            print(f"Saved diagnostics dashboard to {diagnostics_dashboard}")
        print(f"Error: compile-physical failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"Saved physical board to {result.output}")
    print(f"Placed {len(result.placement_report)} components")
    for entry in result.placement_report:
        print(
            f"  {entry.ref}: {entry.footprint} at "
            f"({entry.x:.3f}, {entry.y:.3f}) rot {entry.rotation:g}"
        )
    if result.route_report:
        committable = [entry for entry in result.route_report if entry.strategy != "power_probe"]
        committed = sum(1 for entry in committable if entry.committed)
        print(f"Routes committed {committed}/{len(committable)}")
        probes = sum(1 for entry in result.route_report if entry.strategy == "power_probe")
        if probes:
            print(f"Power probes reported {probes}")
        for entry in result.route_report:
            if entry.strategy == "power_probe":
                status = "PROBE"
            else:
                status = "OK" if entry.committed else "SKIPPED"
            extra = f": {entry.message}" if entry.message else ""
            layers = f" layers={','.join(entry.used_layers)}" if entry.used_layers else ""
            print(
                f"  {status} {entry.net} {entry.strategy}: "
                f"{entry.segments} segment(s), {entry.vias} via(s), "
                f"{entry.length:.3f}mm{layers}{extra}"
            )
    if result.commit_violations:
        print(f"Route commit violations: {len(result.commit_violations)}")
    if result.drc_unconnected:
        summary = summarize_drc_unconnected(result.drc_unconnected)
        if summary.buckets:
            print("DRC residual summary:")
            for bucket in summary.buckets:
                label = f"{bucket.kind}={bucket.name}"
                parts = [
                    label,
                    f"unconnected={bucket.unconnected}",
                    f"pads={bucket.pads}",
                ]
                if bucket.nets:
                    parts.append(f"nets={_format_csv(bucket.nets)}")
                if bucket.route_intents:
                    parts.append(f"routes={_format_csv(bucket.route_intents)}")
                if bucket.power_stitches:
                    parts.append(f"stitches={_format_csv(bucket.power_stitches)}")
                print("  " + " ".join(parts))
                _print_bucket_reasons(bucket)
        print(f"DRC unconnected items: {len(result.drc_unconnected)}")
        for entry in result.drc_unconnected:
            groups = f" groups={','.join(entry.route_groups)}" if entry.route_groups else ""
            routes = f" routes={','.join(entry.route_intents)}" if entry.route_intents else ""
            stitches = (
                f" stitches={','.join(entry.power_stitches)}"
                if entry.power_stitches
                else ""
            )
            print(
                f"  {entry.net}: {', '.join(entry.pads)} - "
                f"{entry.message}{groups}{routes}{stitches}"
            )
    if result.drc_violations:
        print(f"DRC violations: {len(result.drc_violations)}")
        for entry in result.drc_violations:
            nets = f" nets={','.join(entry.nets)}" if entry.nets else ""
            pads = f" pads={','.join(entry.pads)}" if entry.pads else ""
            print(f"  {entry.severity.upper()} {entry.code}: {entry.title}{nets}{pads}")
            if entry.source_reasons:
                reasons = sorted(
                    {
                        (
                            f"{reason.kind}:{reason.name}@{reason.source}"
                            if reason.source
                            else f"{reason.kind}:{reason.name}"
                        ): reason.reason
                        for reason in entry.source_reasons
                    }.items()
                )
                for source_name, reason_text in reasons[:3]:
                    print(f"    source: {source_name} -> {reason_text}")
                if len(reasons) > 3:
                    print(f"    ... +{len(reasons) - 3} more source reasons")
    for warning in result.warnings:
        print(warning)
    if result.production_checks:
        print(f"Production checks: {len(result.production_checks)} finding(s)")
        for entry in result.production_checks:
            source = f" @ {entry.source}" if entry.source else ""
            print(f"  {entry.severity.upper()} {entry.code}: {entry.message}{source}")
    if result.lcsc_policy_summary is not None and result.lcsc_policy_summary.enabled:
        summary = result.lcsc_policy_summary
        print(
            "LCSC policy summary: "
            f"mapped={summary.mapped} excepted={summary.excepted} missing={summary.missing}"
        )
        if summary.missing_refs:
            print(f"  missing refs: {','.join(summary.missing_refs)}")
    if args.production_report:
        print(f"Saved production report to {args.production_report}")
    if args.bom_output:
        print(f"Saved BOM CSV to {args.bom_output}")
    if args.pnp_output:
        print(f"Saved PNP CSV to {args.pnp_output}")
    if args.jlc_bom_output:
        print(f"Saved JLC BOM CSV to {args.jlc_bom_output}")
    if args.jlc_pnp_output:
        print(f"Saved JLC PNP CSV to {args.jlc_pnp_output}")
    if args.gerber_output_dir:
        print(f"Saved Gerber files to {args.gerber_output_dir}")
    if args.drill_output_dir:
        print(f"Saved drill files to {args.drill_output_dir}")
    if args.drc_diagnostics_report and not args.no_drc and args.drc_report is not None:
        print(f"Saved DRC diagnostics report to {args.drc_diagnostics_report}")
    diagnostics_dashboard = getattr(args, "diagnostics_dashboard", None)
    if diagnostics_dashboard is not None:
        if args.route_diagnostics_report and args.route_diagnostics_report.exists():
            source = args.route_diagnostics_report
        elif args.build_summary_output is not None:
            source = args.build_summary_output
        else:
            source = result.output.parent
        dashboard = load_route_diagnostics_dashboard(source)
        write_diagnostics_dashboard(diagnostics_dashboard, dashboard)
        print(f"Saved diagnostics dashboard to {diagnostics_dashboard}")
    if args.build_summary_output:
        print(f"Saved build summary to {args.build_summary_output}")
    if args.manufacturing_archive_output:
        print(f"Saved manufacturing archive to {args.manufacturing_archive_output}")
    if result.production_checks:
        if any(entry.severity == "error" for entry in result.production_checks):
            return 1
    return 0


def cmd_verify_production_summary(args) -> int:
    """Verify a saved production summary and artifact package."""
    result = verify_production_summary(args.summary_json)
    if result.ok:
        print(f"PASS: fabrication-ready production summary verified: {args.summary_json}")
        return 0

    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1


def cmd_production_check(args) -> int:
    """Run profile-enabled production checks from a spec and optional artifacts."""
    try:
        from pardal.netlist_reader import NetlistReader
        from pardal.physical.compiler import (
            ProductionCheckEntry,
            build_physical_board,
            escalate_production_warnings,
        )
        from pardal.physical.spec import load_physical_spec
        from pardal.production_checks import CheckContext, load_source_contract, run_production_checks

        project_context = _load_production_check_project_context(args)
        spec = load_physical_spec(args.spec)
        board = None
        netlist = args.netlist or spec.source_netlist
        if netlist is not None:
            netlist_path = netlist if netlist.is_absolute() else args.spec.parent / netlist
            loaded_board = NetlistReader().read(netlist_path)
            board, _placement = build_physical_board(spec, netlist_path, loaded_board=loaded_board)
        contract = (
            load_source_contract(args.source_contract)
            if args.source_contract is not None
            else getattr(project_context, "source_contract", None) or load_source_contract(None)
        )
        build_summary = None
        artifact_paths = {}
        if args.build_summary is not None:
            build_summary = json.loads(args.build_summary.read_text(encoding="utf-8"))
            for key, value in (build_summary.get("artifacts") or {}).items():
                path = None
                if isinstance(value, dict):
                    path = value.get("generated") or value.get("requested") or value.get("path")
                if path:
                    artifact_paths[key] = Path(path)
        if args.manufacturing_archive is not None:
            artifact_paths["manufacturing_archive"] = args.manufacturing_archive
        ctx = CheckContext(
            spec=spec,
            board=board,
            source_contract=contract,
            artifact_root=args.spec.parent,
            artifact_paths=artifact_paths,
            build_summary=build_summary,
            manufacturing_archive=args.manufacturing_archive,
            production_profiles=tuple(_profile_overrides_for_args(args)),
            project_context=project_context,
            allow_network_checks=_allow_network_checks_for_args(args, project_context),
        )
        findings = run_production_checks(
            ctx,
            enable_checks=args.enable_check,
            disable_checks=args.disable_check,
            disable_check_reasons=_disable_check_reasons_for_args(
                args,
                production_mode=True,
            ),
            production_profiles=_profile_overrides_for_args(args),
        )
        _write_production_check_project_provenance(args, project_context)
    except Exception as exc:
        print(f"Error: production-check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    entries = [
        ProductionCheckEntry(
            severity=finding.severity,
            code=finding.code,
            message=finding.message,
            source=finding.source,
            stage=getattr(finding, "stage", ""),
            package=getattr(finding, "package", ""),
            evidence=dict(getattr(finding, "evidence", {}) or {}),
            source_details=dict(getattr(finding, "source_details", {}) or {}),
            waived=bool(getattr(finding, "waived", False)),
            waiver_reason=str(getattr(finding, "waiver_reason", "") or ""),
        )
        for finding in findings
    ]
    if getattr(args, "warnerr", False):
        entries = escalate_production_warnings(entries)
    if args.format == "json":
        from pardal.physical.compiler import format_production_checks_json

        print(format_production_checks_json(entries), end="")
    else:
        from pardal.physical.compiler import format_production_checks

        print(format_production_checks(entries), end="")
    return 1 if any(entry.severity == "error" for entry in entries) else 0


def _load_production_check_project_context(args):
    if getattr(args, "allow_unlocked", False):
        raise ValueError("--allow-unlocked is invalid with production-check")
    if getattr(args, "allow_absolute_paths", False):
        raise ValueError("--allow-absolute-paths is invalid with production-check")
    project = getattr(args, "project", None)
    if project is None:
        raise ValueError("production-check requires --project and pardal.lock")
    from pardal.project.context import create_project_context, require_project_lock

    ctx = create_project_context(
        project,
        target=getattr(args, "target", "default"),
    )
    _validate_cli_check_overrides(args, ctx)
    require_project_lock(ctx)
    return ctx


def cmd_verify_validation_results(args) -> int:
    """Verify captured validation results against build-summary validation names."""
    result = verify_validation_results(args.summary_json, args.validation_results_json)
    if result.ok:
        print(
            "PASS: captured validation results verified "
            f"for {args.summary_json}"
        )
        return 0

    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1


def cmd_verify_release_package(args) -> int:
    """Verify saved release-package artifacts for downstream automation."""
    result = verify_release_package(args.summary_json, args.validation_results)
    if result.ok:
        print(f"PASS: release package verified: {args.summary_json}")
        return 0

    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1


def cmd_repl(args) -> int:
    """Run interactive REPL mode."""
    repl = REPL()

    if args.load:
        result = repl.process_command(f"LOAD {args.load}")
        if result:
            print(result)

    if args.commands:
        print("PCB Place & Route Tool")
        print("Type HELP for available commands, EXIT to quit")
        print()
        for command in args.commands:
            result = repl.process_command(command)
            if result:
                print(result)
        return 0

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


def cmd_route_dsl_board_ir(args) -> int:
    from pardal.routing_dsl import board_ir_producer as board_ir_producer_module  # noqa: PLC0415

    try:
        result = board_ir_producer_module.produce_board_ir(args.source, args.output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {result.path}")
    return 0


def cmd_route_dsl_plan(args) -> int:
    from pardal.routing_dsl import workflow as workflow_module  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="pardal-route-dsl-plan-") as tmpdir:
        try:
            result = workflow_module.run_route_workflow(
                args.routes_source,
                args.board_ir,
                args.backend_manifest,
                tmpdir,
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        Path(args.route_plan_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.route_plan_output).write_text(
            result.route_plan_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        Path(args.artifact_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.artifact_output).write_text(
            result.artifact_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    print(f"Wrote {args.route_plan_output}")
    print(f"Wrote {args.artifact_output}")
    return 0


def cmd_route_dsl_candidates(args) -> int:
    from pardal.routing_dsl import backend_adapter as backend_adapter_module  # noqa: PLC0415
    from pardal.routing_dsl import board_ir as board_ir_module  # noqa: PLC0415
    from pardal.routing_dsl import candidate_schema as candidate_schema_module  # noqa: PLC0415
    from pardal.routing_dsl import mojo_bridge as mojo_bridge_module  # noqa: PLC0415
    from pardal.routing_dsl import route_plan as route_plan_module  # noqa: PLC0415

    try:
        board = board_ir_module.load_board_ir(args.board_ir)
        route_plan = route_plan_module.normalize_route_plan_payload(args.route_plan)
        manifest = backend_adapter_module.load_backend_manifest(args.backend_manifest)
        if args.routes is not None:
            routes_payload = mojo_bridge_module.load_mojo_routes_payload(args.routes)
            payload = mojo_bridge_module.convert_mojo_routes_to_route_candidates(routes_payload, route_plan, manifest)
        elif args.problem is not None:
            problem_payload = mojo_bridge_module.load_mojo_problem_payload(args.problem)

            class _Backend:
                def stage_candidates(self, route_plan_payload, backend_manifest):
                    del backend_manifest
                    return {
                        "schema": "pardal.route_candidates",
                        "version": "0.1",
                        "route_plan_id": str(route_plan_payload.get("route_plan_id") or ""),
                        "route_plan_hash": str(route_plan_payload.get("route_plan_hash") or ""),
                        "frozen_board_snapshot_id": str(route_plan_payload.get("frozen_board_snapshot_id") or ""),
                        "backend": dict(manifest.get("backend") or {}),
                        "candidates": [],
                        "problem_hash": str(problem_payload.get("problem_hash") or ""),
                    }

            result = backend_adapter_module.adapt_backend_route_output(route_plan, manifest, _Backend())
            if result.kind != "route-candidates":
                raise ValueError("problem payload did not produce route candidates")
            payload = result.payload
        else:
            raise ValueError("either --routes or --problem is required")
        candidate_schema_module.validate_route_candidates(payload)
        candidate_schema_module.write_route_candidates(args.output, payload)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output}")
    return 0


def cmd_route_dsl_apply(args) -> int:
    from pardal.routing_dsl import apply_candidate as apply_candidate_module  # noqa: PLC0415

    try:
        payload = apply_candidate_module.apply_candidate_report(
            args.board_ir,
            args.route_plan,
            args.candidates,
            args.output,
            selected_candidate_id=args.selected_candidate_id,
            input_board_path=args.input_board,
            output_board_path=args.output_board,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output}")
    print(f"accepted={payload.get('accepted')}")
    return 0


def cmd_route_dsl_diagnostics(args) -> int:
    from pardal.routing_dsl import diagnostics as diagnostics_module  # noqa: PLC0415
    from pardal.routing_dsl import oracle as oracle_module  # noqa: PLC0415

    try:
        payload = diagnostics_module.load_route_diagnostics(args.input)
        if payload.get("schema") == "pardal.route_diagnostics":
            if "rows" not in payload or "diagnostics_hash" not in payload:
                raise ValueError("normalized diagnostics must include rows and diagnostics_hash")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
        elif "oracle" in payload or "output_board_copy_path" in payload or "apply_report" in payload:
            payload = oracle_module.route_oracle_report_to_route_diagnostics(payload)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            payload = diagnostics_module.normalize_route_diagnostics(payload)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {args.output}")
    return 0


def cmd_route_dsl_check(args) -> int:
    try:
        if args.artifact == "board-ir":
            from pardal.routing_dsl import board_ir as board_ir_module  # noqa: PLC0415

            board = board_ir_module.load_board_ir(args.input)
            print(board.board_ir_id)
        elif args.artifact == "route-plan":
            import json as _json  # noqa: PLC0415
            from pardal.routing_dsl import route_plan as route_plan_module  # noqa: PLC0415

            payload = _json.loads(Path(args.input).read_text(encoding="utf-8"))
            if payload.get("schema") != route_plan_module.ROUTE_PLAN_SCHEMA:
                raise ValueError("schema must be pardal.route_plan")
            if payload.get("version") != route_plan_module.ROUTE_PLAN_VERSION:
                raise ValueError("version must be 0.1")
            normalized = route_plan_module.normalize_route_plan_payload(payload)
            print(normalized["route_plan_id"])
        elif args.artifact == "candidates":
            from pardal.routing_dsl import candidate_schema as candidate_schema_module  # noqa: PLC0415

            payload = candidate_schema_module.load_route_candidates(args.input)
            print(payload["batch_hash"])
        elif args.artifact == "diagnostics":
            from pardal.routing_dsl import diagnostics as diagnostics_module  # noqa: PLC0415

            payload = diagnostics_module.load_route_diagnostics(args.input)
            if payload.get("schema") != "pardal.route_diagnostics":
                raise ValueError("schema must be pardal.route_diagnostics")
            if "failures" in payload:
                payload = diagnostics_module.normalize_route_diagnostics(payload)
            elif "rows" not in payload or "diagnostics_hash" not in payload:
                raise ValueError("normalized diagnostics must include rows and diagnostics_hash")
            print(payload["diagnostics_hash"])
        else:
            raise ValueError(f"unknown artifact {args.artifact!r}")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_route_dsl_fpga_large(args) -> int:
    from pardal.routing_dsl.fpga_large_tools import build_fpga_large_finish_readiness_pack  # noqa: PLC0415

    try:
        result = build_fpga_large_finish_readiness_pack(
            repo_root=args.repo_root,
            work_dir=args.work_dir,
            board_fixture=args.board_fixture,
            backend_cfg=args.backend_cfg,
            routes_source=args.routes_source,
            manifest_path=args.manifest,
            net_list=tuple(args.net_list or ()),
            from_drc=args.from_drc,
            max_route_groups=args.max_route_groups,
            budget_s=args.budget_s,
            candidate_cap=args.candidate_cap,
            dry_run=(args.fpga_large_command != "one-pass"),
            one_pass=(args.fpga_large_command == "one-pass"),
            resume=(args.fpga_large_command == "resume"),
            commands=[
                {"name": "prepare", "command": ["pardal", "route-dsl", "fpga-large", "prepare"]},
                {"name": "pass", "command": ["pardal", "route-dsl", "fpga-large", "pass"]},
                {"name": "next-worklist", "command": ["pardal", "route-dsl", "fpga-large", "next-worklist"]},
                {"name": "report", "command": ["pardal", "route-dsl", "fpga-large", "report"]},
                {"name": "resume", "command": ["pardal", "route-dsl", "fpga-large", "resume"]},
            ],
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {result.manifest_path}")
    return 0


def cmd_route_dsl_example(args) -> int:
    from pardal.routing_dsl import example_tools as example_tools_module  # noqa: PLC0415

    try:
        example_dir = args.example_dir or args.example_dir_flag or Path("examples/routing_dsl")
        if args.example_command == "init":
            example_tools_module.init_example_directory(example_dir)
            print(example_dir)
            return 0

        seeds = example_tools_module.ensure_example_seed_files(example_dir)
        board_source_path = args.board_source or seeds["board_source"]
        routes_source_path = args.routes_source or seeds["routes_source"]
        board_payload = json.loads(board_source_path.read_text(encoding="utf-8"))
        routes_source_text = routes_source_path.read_text(encoding="utf-8")
        board_ir = example_tools_module.load_board_ir(
            example_tools_module.produce_board_ir(board_source_path).payload
        )
        route_plan = example_tools_module.route_plan_module.resolve_route_plan(
            example_tools_module.source_module.load_routes_source(routes_source_path),
            board_ir,
        )
        result = example_tools_module.assemble_example_workflow(
            example_dir=example_dir,
            board_source_payload=board_payload,
            routes_source_payload=routes_source_text,
            board_ir_payload=board_ir,
            route_plan_payload=route_plan,
            commands=example_tools_module.example_command_sequence(board_source_path, routes_source_path),
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(result.artifact_manifest_path)
    return 0


def cmd_project_add(args) -> int:
    """Add a package dependency to pardal.yaml and sync local packages."""
    try:
        from pardal.packages.commands import add_dependency

        result = add_dependency(args.spec, args.project, registry_index=args.registry_index)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for package in result.packages:
        print(f"installed {package.identifier} -> {package.install_path}")
    print("wrote pardal.lock")
    return 0


def cmd_project_sync(args) -> int:
    """Install declared dependencies and write pardal.lock."""
    try:
        from pardal.packages.commands import check_project_sync, sync_project

        if getattr(args, "check", False):
            check_project_sync(args.project)
            print("pardal.lock is up to date")
            return 0
        result = sync_project(args.project, registry_index=args.registry_index)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for package in result.packages:
        print(f"installed {package.identifier} -> {package.install_path}")
    print("wrote pardal.lock")
    return 0


def cmd_project_lock(args) -> int:
    """Update pardal.lock without mutating pardal.yaml."""
    try:
        from pardal.packages.commands import update_lock

        result = update_lock(
            args.project,
            package_id=args.update,
            registry_index=args.registry_index,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for package in result.packages:
        print(f"installed {package.identifier} -> {package.install_path}")
    print("wrote pardal.lock")
    return 0


def cmd_project_list(args) -> int:
    """List dependencies declared in pardal.yaml."""
    try:
        from pardal.packages.commands import list_dependencies

        dependencies = list_dependencies(args.project, include_status=True)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for dependency in dependencies:
        print(dependency)
    return 0


def cmd_project_remove(args) -> int:
    """Remove a package dependency from pardal.yaml and sync."""
    try:
        from pardal.packages.commands import remove_dependency

        result = remove_dependency(
            args.identifier,
            args.project,
            registry_index=args.registry_index,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for package in result.packages:
        print(f"installed {package.identifier} -> {package.install_path}")
    print("wrote pardal.lock")
    return 0


def cmd_package_check(args) -> int:
    """Validate a Pardal package project."""
    try:
        from pardal.packages.authoring import check_package

        report = check_package(args.project, publish=args.publish)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"package ok: {report.manifest.project.identifier}")
    print(f"exports: {len(report.exports)}")
    return 0


def cmd_package_build(args) -> int:
    """Build a Pardal package archive."""
    try:
        from pardal.packages.authoring import build_package

        result = build_package(args.project, output_dir=args.output_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(result.archive_path)
    print(result.manifest_path)
    print(result.sha256_path)
    return 0


def cmd_package_publish(args) -> int:
    """Validate a package publish request."""
    try:
        from pardal.packages.authoring import publish_package

        result = publish_package(
            args.project,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
            registry_index=args.registry_index,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if result.dry_run:
        print("publish dry-run ok")
    else:
        print(f"published to {result.registry_index}")
    print(result.archive_path)
    print(result.manifest_path)
    print(result.sha256_path)
    return 0


def cmd_create_package(args) -> int:
    """Create a new Pardal package project."""
    try:
        from pardal.packages.create import create_package_project

        result = create_package_project(args.identifier, output_dir=args.output_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(result.manifest_path)
    return 0


def cmd_create_board(args) -> int:
    """Create a new Pardal board project."""
    try:
        from pardal.packages.create import create_board_project

        result = create_board_project(
            args.name,
            output_dir=args.output_dir,
            template=args.template,
            package_root=args.package_root,
            package_install_root=args.package_install_root,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(result.manifest_path)
    return 0


def cmd_project_provenance(args) -> int:
    """Write package/profile provenance artifacts for a project target."""
    try:
        from pardal.project.context import create_project_context, require_project_lock
        from pardal.project.provenance import write_project_provenance_artifacts

        ctx = create_project_context(args.project, target=args.target)
        if args.production:
            require_project_lock(ctx)
        artifacts = write_project_provenance_artifacts(ctx, output_dir=args.output_dir)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(artifacts.package_resolution)
    print(artifacts.profile_resolution)
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

    create_parser = subparsers.add_parser(
        "create",
        help="Create Pardal projects and packages",
    )
    create_subparsers = create_parser.add_subparsers(dest="create_command", required=True)
    create_package_parser = create_subparsers.add_parser(
        "package",
        help="Create a new Pardal package project",
    )
    create_package_parser.add_argument("identifier", help="Package identifier owner/name")
    create_package_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: package name)",
    )
    create_board_parser = create_subparsers.add_parser(
        "board",
        help="Create a new Pardal board project",
    )
    create_board_parser.add_argument("name", help="Board project name")
    create_board_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: board name)",
    )
    create_board_parser.add_argument(
        "--template",
        type=str,
        default=None,
        help="Template ID OWNER/NAME:TEMPLATE",
    )
    create_board_parser.add_argument(
        "--package-root",
        type=Path,
        default=None,
        help="Local package root for resolving --template",
    )
    create_board_parser.add_argument(
        "--package-install-root",
        type=Path,
        default=None,
        help="Installed package root for resolving --template (default: .pardal/packages)",
    )
    create_project_parser = create_subparsers.add_parser(
        "project",
        help="Create a new generic Pardal board project",
    )
    create_project_parser.add_argument("name", help="Project name")
    create_project_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: project name)",
    )

    add_parser = subparsers.add_parser(
        "add",
        help="Add a Pardal package dependency and sync",
    )
    add_parser.add_argument("spec", help="Dependency spec, e.g. file://../pkg")
    add_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Project manifest path",
    )
    add_parser.add_argument(
        "--registry-index",
        type=Path,
        default=None,
        help="Static registry index path for registry dependencies",
    )

    sync_parser = subparsers.add_parser(
        "sync",
        help="Install declared Pardal package dependencies",
    )
    sync_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Project manifest path",
    )
    sync_parser.add_argument(
        "--registry-index",
        type=Path,
        default=None,
        help="Static registry index path for registry dependencies",
    )
    sync_parser.add_argument(
        "--check",
        action="store_true",
        help="Validate pardal.lock and installed packages without mutating files",
    )

    lock_parser = subparsers.add_parser(
        "lock",
        help="Update pardal.lock without changing pardal.yaml",
    )
    lock_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Project manifest path",
    )
    lock_parser.add_argument(
        "--update",
        metavar="OWNER/NAME",
        default=None,
        help="Refresh one declared package and affected dependencies",
    )
    lock_parser.add_argument(
        "--registry-index",
        type=Path,
        default=None,
        help="Static registry index path for registry dependencies",
    )

    list_parser = subparsers.add_parser(
        "list",
        help="List declared Pardal package dependencies",
    )
    list_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Project manifest path",
    )

    remove_parser = subparsers.add_parser(
        "remove",
        help="Remove a Pardal package dependency and sync",
    )
    remove_parser.add_argument("identifier", help="Package identifier owner/name")
    remove_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Project manifest path",
    )
    remove_parser.add_argument(
        "--registry-index",
        type=Path,
        default=None,
        help="Static registry index path for registry dependencies",
    )

    project_parser = subparsers.add_parser(
        "project",
        help="Project context commands",
    )
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)
    project_provenance_parser = project_subparsers.add_parser(
        "provenance",
        help="Write package/profile provenance artifacts",
    )
    project_provenance_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Project manifest path",
    )
    project_provenance_parser.add_argument(
        "--target",
        type=str,
        default="default",
        help="Build target name",
    )
    project_provenance_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: selected target output root)",
    )
    project_provenance_parser.add_argument(
        "--production",
        action="store_true",
        help="Require pardal.lock before writing provenance",
    )

    package_parser = subparsers.add_parser(
        "package",
        help="Package authoring commands",
    )
    package_subparsers = package_parser.add_subparsers(dest="package_command", required=True)
    package_check_parser = package_subparsers.add_parser(
        "check",
        help="Validate a Pardal package project",
    )
    package_check_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Package manifest path",
    )
    package_check_parser.add_argument(
        "--publish",
        action="store_true",
        help="Apply publishability checks",
    )
    package_build_parser = package_subparsers.add_parser(
        "build",
        help="Build a Pardal package archive",
    )
    package_build_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Package manifest path",
    )
    package_build_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output dist directory",
    )
    package_publish_parser = package_subparsers.add_parser(
        "publish",
        help="Validate and publish a Pardal package",
    )
    package_publish_parser.add_argument(
        "--project",
        type=Path,
        default=Path("pardal.yaml"),
        help="Package manifest path",
    )
    package_publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate publishability and build artifacts without uploading",
    )
    package_publish_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output dist directory for dry-run artifacts",
    )
    package_publish_parser.add_argument(
        "--registry-index",
        type=Path,
        default=None,
        help="Static registry index path for dry-run metadata validation",
    )

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

    # pardal compile-physical
    compile_physical_parser = subparsers.add_parser(
        "compile-physical",
        help="Compile a text-defined physical PCB spec",
        description="Load a physical spec and netlist, apply placement, and write KiCad PCB",
    )
    compile_physical_parser.add_argument(
        "spec", type=Path, help="Input physical spec file (.pdl.yaml)"
    )
    compile_physical_parser.add_argument(
        "--project",
        type=Path,
        help="Optional pardal.yaml project manifest for package/profile provenance",
    )
    compile_physical_parser.add_argument(
        "--target",
        default="default",
        help="Project build target used with --project (default: default)",
    )
    compile_physical_parser.add_argument(
        "--netlist", type=Path, help="Input netlist file (.net); overrides source.netlist"
    )
    compile_physical_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output KiCad PCB file (.kicad_pcb)",
    )
    compile_physical_parser.add_argument(
        "--place-only",
        action="store_true",
        help="Only compile placement; route/fanout/plane intents are ignored",
    )
    compile_physical_parser.add_argument(
        "--drc-report", type=Path, help="Optional KiCad DRC report path"
    )
    compile_physical_parser.add_argument(
        "--no-drc", action="store_true", help="Skip KiCad DRC even if --drc-report is set"
    )
    compile_physical_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if any route intent is rejected by the internal commit gate",
    )
    compile_physical_parser.add_argument(
        "--enable-route-group",
        action="append",
        default=[],
        help=(
            "Only compile route intents in this group, plus ungrouped routes. "
            "May be passed more than once."
        ),
    )
    compile_physical_parser.add_argument(
        "--probe-deferred-power",
        action="store_true",
        help="Report deferred power-stitch auto candidates without committing copper",
    )
    compile_physical_parser.add_argument(
        "--production-check",
        action="store_true",
        help="Run production-readiness checks for DFM, rails, testpoints, and mechanical intent",
    )
    compile_physical_parser.add_argument(
        "--source-contract",
        type=Path,
        help="Optional source-contract YAML enabling profile-specific production checks",
    )
    compile_physical_parser.add_argument(
        "--enable-check",
        action="append",
        default=[],
        help="Enable a production check ID; may be passed more than once",
    )
    compile_physical_parser.add_argument(
        "--disable-check",
        action="append",
        default=[],
        help="Disable a production check ID; may be passed more than once",
    )
    compile_physical_parser.add_argument(
        "--reason",
        help="Required reason when disabling production checks in production mode",
    )
    compile_physical_parser.add_argument(
        "--profile",
        "--production-profile",
        dest="production_profile",
        action="append",
        default=[],
        help="Enable a project production profile; may be passed more than once",
    )
    compile_physical_parser.add_argument(
        "--warnerr",
        action="store_true",
        help="Treat production-check warnings as errors",
    )
    compile_physical_parser.add_argument(
        "--allow-unlocked",
        action="store_true",
        help="Development-only project override; invalid with --production-check",
    )
    compile_physical_parser.add_argument(
        "--allow-absolute-paths",
        action="store_true",
        help="Development-only project override; invalid with --production-check",
    )
    compile_physical_parser.add_argument(
        "--production-output-dir",
        type=Path,
        help=(
            "Preset standard production artifact paths under DIR for DRC, "
            "exports, reports, summary, and archive"
        ),
    )
    compile_physical_parser.add_argument(
        "--production-report",
        type=Path,
        help="Optional production-check report output path",
    )
    compile_physical_parser.add_argument(
        "--production-report-format",
        action=_StoreWithExplicitFlag,
        choices=["text", "json"],
        default="text",
        help="Production report format (default: text)",
    )
    compile_physical_parser.add_argument(
        "--drc-diagnostics-report",
        type=Path,
        help="Optional parsed KiCad DRC-violations report output path",
    )
    compile_physical_parser.add_argument(
        "--route-diagnostics-report",
        type=Path,
        help="Optional strict route-commit diagnostics output path",
    )
    compile_physical_parser.add_argument(
        "--diagnostics-dashboard",
        type=Path,
        help="Optional route diagnostics dashboard JSON output path",
    )
    compile_physical_parser.add_argument(
        "--drc-diagnostics-format",
        action=_StoreWithExplicitFlag,
        choices=["text", "json"],
        default="text",
        help="DRC diagnostics report format (default: text)",
    )
    compile_physical_parser.add_argument(
        "--bom-output",
        type=Path,
        help="Optional BOM CSV output path",
    )
    compile_physical_parser.add_argument(
        "--pnp-output",
        type=Path,
        help="Optional pick-and-place CSV output path",
    )
    compile_physical_parser.add_argument(
        "--jlc-bom-output",
        type=Path,
        help="Optional JLC-formatted BOM CSV output path",
    )
    compile_physical_parser.add_argument(
        "--jlc-pnp-output",
        type=Path,
        help="Optional JLC-formatted pick-and-place CSV output path",
    )
    compile_physical_parser.add_argument(
        "--exclude-helpers-in-exports",
        action="store_true",
        help="Exclude helper components (TP*, FID*, MH*) from BOM/PNP exports",
    )
    compile_physical_parser.add_argument(
        "--gerber-output-dir",
        type=Path,
        help="Optional KiCad Gerber export directory",
    )
    compile_physical_parser.add_argument(
        "--drill-output-dir",
        type=Path,
        help="Optional KiCad drill export directory",
    )
    compile_physical_parser.add_argument(
        "--build-summary-output",
        type=Path,
        help="Optional machine-readable build summary JSON output path",
    )
    compile_physical_parser.add_argument(
        "--manufacturing-archive-output",
        type=Path,
        help="Optional zip archive bundling current-run manufacturing outputs",
    )

    production_check_parser = subparsers.add_parser(
        "production-check",
        help="Run profile-enabled production checks against a spec and artifacts",
    )
    production_check_parser.add_argument("spec", type=Path, help="Input physical spec file")
    production_check_parser.add_argument(
        "--project",
        type=Path,
        help="Optional pardal.yaml project manifest for package/profile checks",
    )
    production_check_parser.add_argument(
        "--target",
        default="default",
        help="Project build target used with --project (default: default)",
    )
    production_check_parser.add_argument("--netlist", type=Path, help="Input netlist override")
    production_check_parser.add_argument("--source-contract", type=Path)
    production_check_parser.add_argument("--build-summary", type=Path)
    production_check_parser.add_argument("--manufacturing-archive", type=Path)
    production_check_parser.add_argument(
        "--enable-check", action="append", default=[], help="Enable a check ID"
    )
    production_check_parser.add_argument(
        "--disable-check", action="append", default=[], help="Disable a check ID"
    )
    production_check_parser.add_argument(
        "--reason",
        help="Required reason when disabling production checks",
    )
    production_check_parser.add_argument(
        "--profile",
        "--production-profile",
        dest="production_profile",
        action="append",
        default=[],
        help="Enable a project production profile",
    )
    production_check_parser.add_argument(
        "--warnerr",
        action="store_true",
        help="Treat production-check warnings as errors",
    )
    production_check_parser.add_argument(
        "--allow-unlocked",
        action="store_true",
        help="Development-only project override; invalid with production-check",
    )
    production_check_parser.add_argument(
        "--allow-absolute-paths",
        action="store_true",
        help="Development-only project override; invalid with production-check",
    )
    production_check_parser.add_argument(
        "--allow-network-checks",
        action="store_true",
        help="Allow network-capable package checks to run",
    )
    production_check_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for package/profile provenance JSON artifacts",
    )
    production_check_parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format"
    )

    # pardal verify-production-summary
    verify_production_summary_parser = subparsers.add_parser(
        "verify-production-summary",
        help="Verify fabrication readiness from a saved build-summary.json package",
        description=(
            "Check a saved build-summary.json and its generated artifacts without "
            "rerunning compile-physical or KiCad DRC"
        ),
    )
    verify_production_summary_parser.add_argument(
        "summary_json",
        type=Path,
        help="Path to the saved build-summary.json file",
    )

    # pardal verify-validation-results
    verify_validation_results_parser = subparsers.add_parser(
        "verify-validation-results",
        help="Verify captured validation results against build-summary validation names",
        description=(
            "Check a saved build-summary.json and matching validation-results.json "
            "before deciding whether measured test artifacts satisfy declared validation tests"
        ),
    )
    verify_validation_results_parser.add_argument(
        "summary_json",
        type=Path,
        help="Path to the saved build-summary.json file",
    )
    verify_validation_results_parser.add_argument(
        "validation_results_json",
        type=Path,
        help="Path to the captured validation results JSON file",
    )

    # pardal verify-release-package
    verify_release_package_parser = subparsers.add_parser(
        "verify-release-package",
        help="Verify a saved release package for downstream CI or release consumers",
        description=(
            "Check a saved build-summary.json package and optionally captured "
            "validation-results.json without rerunning compile-physical or KiCad DRC"
        ),
    )
    verify_release_package_parser.add_argument(
        "summary_json",
        type=Path,
        help="Path to the saved build-summary.json file",
    )
    verify_release_package_parser.add_argument(
        "--validation-results",
        type=Path,
        help="Optional path to captured validation-results.json",
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
        default=None,
        help="Number of copper layers (2, 4, 6, or 8). Default: infer from PCB when possible",
    )

    # pardal backend-route (docker pcbnew I/O + Mojo router)
    backend_route_parser = subparsers.add_parser(
        "backend-route",
        help="Autoroute via backend router (docker pcbnew I/O)",
        description="Extract routing problem via pcbnew in docker, route with host backend (Mojo), apply via pcbnew.",
    )
    backend_route_parser.add_argument("pcb", type=Path, help="Input PCB file (.kicad_pcb)")
    backend_route_parser.add_argument(
        "-o", "--output", type=Path, required=True, help="Output PCB file (.kicad_pcb)"
    )
    backend_route_parser.add_argument(
        "--docker-image",
        default="kicad/kicad:9.0.6-full",
        help="KiCad docker image to use for pcbnew",
    )
    backend_route_parser.add_argument(
        "--resolution",
        type=float,
        default=0.2,
        help="Grid resolution (mm) for routing problem extraction",
    )
    backend_route_parser.add_argument(
        "--inflate",
        type=float,
        default=None,
        help="Optional extra obstacle inflation (mm) for extraction (default: derived from netclass)",
    )
    backend_route_parser.add_argument(
        "--cfg",
        type=Path,
        default=None,
        help="Optional Mojo router config JSON",
    )
    backend_route_parser.add_argument(
        "--routes-json",
        type=Path,
        default=None,
        help="Optional path to write routes JSON (default: alongside output)",
    )

    route_dsl_parser = subparsers.add_parser(
        "route-dsl",
        help="Work with staged routing DSL artifacts",
        description=(
            "File-oriented helpers for staged board IR, route plans, candidates, diagnostics, "
            "and apply reports. Outputs are neutral/staged only and do not claim routing, "
            "release, JLC, or orderable authority."
        ),
    )
    route_dsl_subparsers = route_dsl_parser.add_subparsers(dest="route_dsl_command", required=True)

    route_dsl_board_ir_parser = route_dsl_subparsers.add_parser(
        "board-ir",
        help="Produce board.ir.json from structured board source JSON",
    )
    route_dsl_board_ir_parser.add_argument("source", type=Path, help="Input board source JSON")
    route_dsl_board_ir_parser.add_argument("-o", "--output", type=Path, required=True, help="Output board.ir.json path")

    route_dsl_plan_parser = route_dsl_subparsers.add_parser(
        "plan",
        help="Produce route-plan and capability or diagnostics artifacts",
    )
    route_dsl_plan_parser.add_argument("routes_source", type=Path, help="Input routes.pdl.yaml")
    route_dsl_plan_parser.add_argument("board_ir", type=Path, help="Input board.ir.json")
    route_dsl_plan_parser.add_argument("backend_manifest", type=Path, help="Input backend manifest JSON")
    route_dsl_plan_parser.add_argument("--route-plan-output", type=Path, required=True, help="Output route-plan.ir.json path")
    route_dsl_plan_parser.add_argument("--artifact-output", type=Path, required=True, help="Output capability-report.json or route-diagnostics.json path")

    route_dsl_candidates_parser = route_dsl_subparsers.add_parser(
        "candidates",
        help="Stage validated route candidates from routes/problem fixtures",
    )
    route_dsl_candidates_parser.add_argument("board_ir", type=Path, help="Input board.ir.json")
    route_dsl_candidates_parser.add_argument("route_plan", type=Path, help="Input route-plan.ir.json")
    route_dsl_candidates_parser.add_argument("backend_manifest", type=Path, help="Input backend manifest JSON")
    route_dsl_candidates_parser.add_argument("-o", "--output", type=Path, required=True, help="Output route-candidates.json path")
    route_dsl_candidates_parser.add_argument("--routes", type=Path, default=None, help="Optional input mojo routes.json fixture")
    route_dsl_candidates_parser.add_argument("--problem", type=Path, default=None, help="Optional input mojo problem.json fixture")

    route_dsl_apply_parser = route_dsl_subparsers.add_parser(
        "apply",
        help="Write a neutral apply report only",
        description=(
            "Validate a selected candidate and write an apply report only. "
            "This does not commit routing, release, JLC, or orderable authority."
        ),
    )
    route_dsl_apply_parser.add_argument("board_ir", type=Path, help="Input board.ir.json")
    route_dsl_apply_parser.add_argument("route_plan", type=Path, help="Input route-plan.ir.json")
    route_dsl_apply_parser.add_argument("candidates", type=Path, help="Input route-candidates.json")
    route_dsl_apply_parser.add_argument("-o", "--output", type=Path, required=True, help="Output apply-report.json path")
    route_dsl_apply_parser.add_argument("--selected-candidate-id", type=str, default=None, help="Optional candidate_id to select")
    route_dsl_apply_parser.add_argument("--input-board", type=Path, default=None, help="Optional input board bytes to copy after validation")
    route_dsl_apply_parser.add_argument("--output-board", type=Path, default=None, help="Optional output board path for copy-only apply")

    route_dsl_diagnostics_parser = route_dsl_subparsers.add_parser(
        "diagnostics",
        help="Normalize diagnostics or oracle reports",
    )
    route_dsl_diagnostics_parser.add_argument("input", type=Path, help="Input route-diagnostics.json or route-oracle-report.json")
    route_dsl_diagnostics_parser.add_argument("-o", "--output", type=Path, required=True, help="Output normalized route-diagnostics.json path")

    route_dsl_check_parser = route_dsl_subparsers.add_parser(
        "check",
        help="Validate or round-trip routing DSL artifacts",
    )
    route_dsl_check_subparsers = route_dsl_check_parser.add_subparsers(dest="artifact", required=True)
    for artifact_name in ("board-ir", "route-plan", "candidates", "diagnostics"):
        artifact_parser = route_dsl_check_subparsers.add_parser(artifact_name, help=f"Validate {artifact_name} artifact")
        artifact_parser.add_argument("input", type=Path, help=f"Input {artifact_name} artifact path")

    route_dsl_board_ir_parser.set_defaults(func=cmd_route_dsl_board_ir)
    route_dsl_plan_parser.set_defaults(func=cmd_route_dsl_plan)
    route_dsl_candidates_parser.set_defaults(func=cmd_route_dsl_candidates)
    route_dsl_apply_parser.set_defaults(func=cmd_route_dsl_apply)
    route_dsl_diagnostics_parser.set_defaults(func=cmd_route_dsl_diagnostics)
    route_dsl_check_parser.set_defaults(func=cmd_route_dsl_check)

    route_dsl_fpga_large_parser = route_dsl_subparsers.add_parser(
        "fpga-large",
        help="Run the fpga_large finish-readiness lane",
    )
    route_dsl_fpga_large_subparsers = route_dsl_fpga_large_parser.add_subparsers(dest="fpga_large_command", required=True)
    for command_name in ("prepare", "pass", "one-pass", "next-worklist", "report", "resume"):
        command_parser = route_dsl_fpga_large_subparsers.add_parser(
            command_name,
            help=f"{command_name} fpga_large finish-readiness artifacts",
        )
        command_parser.add_argument("--repo-root", type=Path, default=Path("."))
        command_parser.add_argument("--work-dir", type=Path, required=True)
        command_parser.add_argument("--board-fixture", type=Path, default=None)
        command_parser.add_argument("--backend-cfg", type=Path, default=None)
        command_parser.add_argument("--routes-source", type=Path, default=None)
        command_parser.add_argument("--manifest", type=Path, default=None)
        command_parser.add_argument("--net-list", type=str, nargs="*", default=())
        command_parser.add_argument("--from-drc", type=Path, default=None)
        command_parser.add_argument("--max-route-groups", type=int, default=None)
        command_parser.add_argument("--budget-s", type=float, default=None)
        command_parser.add_argument("--candidate-cap", type=int, default=None)
        command_parser.set_defaults(func=cmd_route_dsl_fpga_large)

    route_dsl_example_parser = route_dsl_subparsers.add_parser(
        "example",
        help="Seed or assemble the checked-in routing DSL example",
    )
    route_dsl_example_subparsers = route_dsl_example_parser.add_subparsers(dest="example_command", required=True)
    route_dsl_example_init_parser = route_dsl_example_subparsers.add_parser(
        "init",
        help="Create or seed the example directory",
    )
    route_dsl_example_init_parser.add_argument("example_dir", nargs="?", type=Path, default=None)
    route_dsl_example_init_parser.add_argument("--example-dir", dest="example_dir_flag", type=Path, default=None)
    route_dsl_example_init_parser.set_defaults(func=cmd_route_dsl_example)

    route_dsl_example_run_parser = route_dsl_example_subparsers.add_parser(
        "run",
        help="Assemble the example artifacts and print the manifest path",
    )
    route_dsl_example_run_parser.add_argument("example_dir", nargs="?", type=Path, default=None)
    route_dsl_example_run_parser.add_argument("--example-dir", dest="example_dir_flag", type=Path, default=None)
    route_dsl_example_run_parser.add_argument("--board-source", type=Path, default=None)
    route_dsl_example_run_parser.add_argument("--routes-source", type=Path, default=None)
    route_dsl_example_run_parser.set_defaults(func=cmd_route_dsl_example)

    backend_route_parser.add_argument(
        "--problem-json",
        type=Path,
        default=None,
        help="Optional path to write extracted problem JSON (default: alongside output)",
    )
    backend_route_parser.add_argument(
        "--extract-timeout-s",
        type=float,
        default=None,
        help="Timeout for pcbnew extraction step inside docker (seconds)",
    )
    backend_route_parser.add_argument(
        "--route-timeout-s",
        type=float,
        default=None,
        help="Timeout for backend routing step on host (seconds)",
    )
    backend_route_parser.add_argument(
        "--apply-timeout-s",
        type=float,
        default=None,
        help="Timeout for pcbnew apply step inside docker (seconds)",
    )

    # pardal rust-route (experimental Rust backend via docker + pcbnew)
    rust_route_parser = subparsers.add_parser(
        "rust-route",
        help="Deprecated: alias for backend-route",
        description="Deprecated: use `pardal backend-route`.",
    )
    rust_route_parser.add_argument("pcb", type=Path, help="Input PCB file (.kicad_pcb)")
    rust_route_parser.add_argument(
        "-o", "--output", type=Path, required=True, help="Output PCB file (.kicad_pcb)"
    )
    rust_route_parser.add_argument(
        "--docker-image",
        default="kicad/kicad:9.0.6-full",
        help="KiCad docker image to use for pcbnew",
    )
    rust_route_parser.add_argument(
        "--resolution",
        type=float,
        default=0.2,
        help="Grid resolution (mm) for routing problem extraction",
    )
    rust_route_parser.add_argument(
        "--inflate",
        type=float,
        default=None,
        help="Optional extra obstacle inflation (mm) for extraction (default: derived from netclass)",
    )
    rust_route_parser.add_argument(
        "--cfg",
        type=Path,
        default=None,
        help="Optional Mojo router config JSON",
    )
    rust_route_parser.add_argument(
        "--routes-json",
        type=Path,
        default=None,
        help="Optional path to write routes JSON (default: alongside output)",
    )
    rust_route_parser.add_argument(
        "--problem-json",
        type=Path,
        default=None,
        help="Optional path to write extracted problem JSON (default: alongside output)",
    )
    rust_route_parser.add_argument(
        "--extract-timeout-s",
        type=float,
        default=None,
        help="Timeout for pcbnew extraction step inside docker (seconds)",
    )
    rust_route_parser.add_argument(
        "--route-timeout-s",
        type=float,
        default=None,
        help="Timeout for backend routing step on host (seconds)",
    )
    rust_route_parser.add_argument(
        "--apply-timeout-s",
        type=float,
        default=None,
        help="Timeout for pcbnew apply step inside docker (seconds)",
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
    repl_parser.add_argument(
        "--load", type=Path, metavar="FILE", help="Load netlist or PCB file"
    )
    repl_parser.add_argument(
        "--exec",
        action="append",
        dest="commands",
        metavar="CMD",
        help="Execute a REPL command; may be repeated",
    )

    args = parser.parse_args()

    if args.command == "build":
        return cmd_build(args)
    elif args.command == "create":
        if args.create_command == "package":
            return cmd_create_package(args)
        if args.create_command == "board":
            return cmd_create_board(args)
        if args.create_command == "project":
            args.template = None
            args.package_root = None
            args.package_install_root = None
            return cmd_create_board(args)
        parser.print_help()
        return 1
    elif args.command == "add":
        return cmd_project_add(args)
    elif args.command == "sync":
        return cmd_project_sync(args)
    elif args.command == "lock":
        return cmd_project_lock(args)
    elif args.command == "list":
        return cmd_project_list(args)
    elif args.command == "remove":
        return cmd_project_remove(args)
    elif args.command == "project":
        if args.project_command == "provenance":
            return cmd_project_provenance(args)
        parser.print_help()
        return 1
    elif args.command == "package":
        if args.package_command == "check":
            return cmd_package_check(args)
        if args.package_command == "build":
            return cmd_package_build(args)
        if args.package_command == "publish":
            return cmd_package_publish(args)
        parser.print_help()
        return 1
    elif args.command == "drc":
        return cmd_drc(args)
    elif args.command == "freeroute":
        return cmd_freeroute(args)
    elif args.command == "place":
        return cmd_place(args)
    elif args.command == "compile-physical":
        return cmd_compile_physical(args)
    elif args.command == "production-check":
        return cmd_production_check(args)
    elif args.command == "verify-production-summary":
        return cmd_verify_production_summary(args)
    elif args.command == "verify-validation-results":
        return cmd_verify_validation_results(args)
    elif args.command == "verify-release-package":
        return cmd_verify_release_package(args)
    elif args.command == "route":
        return cmd_route(args)
    elif args.command == "backend-route":
        return cmd_backend_route(args)
    elif args.command == "rust-route":
        return cmd_rust_route(args)
    elif args.command == "route-dsl":
        if args.route_dsl_command == "board-ir":
            return cmd_route_dsl_board_ir(args)
        elif args.route_dsl_command == "plan":
            return cmd_route_dsl_plan(args)
        elif args.route_dsl_command == "candidates":
            return cmd_route_dsl_candidates(args)
        elif args.route_dsl_command == "apply":
            return cmd_route_dsl_apply(args)
        elif args.route_dsl_command == "diagnostics":
            return cmd_route_dsl_diagnostics(args)
        elif args.route_dsl_command == "check":
            return cmd_route_dsl_check(args)
        elif args.route_dsl_command == "fpga-large":
            return cmd_route_dsl_fpga_large(args)
        elif args.route_dsl_command == "example":
            return cmd_route_dsl_example(args)
        parser.print_help()
        return 1
    elif args.command == "repl":
        return cmd_repl(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
