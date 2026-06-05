#!/usr/bin/env python3
"""Assemble a dry-run fpga_large routing DSL tooling pack."""

from __future__ import annotations

import argparse
from pathlib import Path

from pardal.routing_dsl.fpga_large_tools import build_fpga_large_tooling_pack


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--board-fixture", type=Path, default=None)
    parser.add_argument("--backend-cfg", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = build_fpga_large_tooling_pack(
        repo_root=args.repo_root,
        work_dir=args.work_dir,
        board_fixture=args.board_fixture,
        backend_cfg=args.backend_cfg,
        commands=[
            {"name": "extract", "command": ["python3", "pardal/tools/extract_routing_problem_pcbnew.py"]},
            {"name": "route", "command": ["python3", "pardal/tools/iterative_backend_route_fpga_large.py"]},
            {"name": "apply", "command": ["python3", "pardal/tools/apply_routes_pcbnew.py"]},
            {"name": "suite", "command": ["python3", "pardal/tools/run_parity_suite.py"]},
            {"name": "analyze", "command": ["python3", "pardal/tools/analyze_parity_run.py"]},
        ],
    )
    print(result.manifest_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
