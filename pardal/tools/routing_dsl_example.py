#!/usr/bin/env python3
"""Assemble the checked-in routing DSL example tooling pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pardal.routing_dsl.example_tools import (
    assemble_example_workflow,
    ensure_example_seed_files,
    example_command_sequence,
    init_example_directory,
)
from pardal.routing_dsl.board_ir_producer import produce_board_ir
from pardal.routing_dsl.board_ir import load_board_ir
from pardal.routing_dsl.route_plan import resolve_route_plan
from pardal.routing_dsl.source import load_routes_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--example-dir", type=Path, default=Path("examples/routing_dsl"))
    parser.add_argument("--board-source", type=Path, default=None)
    parser.add_argument("--routes-source", type=Path, default=None)
    parser.add_argument("--board-ir", type=Path, default=None)
    parser.add_argument("--route-plan", type=Path, default=None)
    parser.add_argument("command", nargs="?", choices=("init", "run"), default="run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    example_dir = args.example_dir
    if args.command == "init":
        init_example_directory(example_dir)
        print(example_dir)
        return 0

    seeds = ensure_example_seed_files(example_dir)
    board_source_path = args.board_source or seeds["board_source"]
    routes_source_path = args.routes_source or seeds["routes_source"]
    board_payload = json.loads(board_source_path.read_text(encoding="utf-8"))
    routes = load_routes_source(routes_source_path)
    board_ir = load_board_ir(produce_board_ir(board_source_path).payload)
    route_plan = resolve_route_plan(routes, board_ir)
    result = assemble_example_workflow(
        example_dir=example_dir,
        board_source_payload=board_payload,
        routes_source_payload=routes_source_path.read_text(encoding="utf-8"),
        board_ir_payload=board_ir,
        route_plan_payload=route_plan,
        commands=example_command_sequence(board_source_path, routes_source_path),
    )
    print(result.artifact_manifest_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
