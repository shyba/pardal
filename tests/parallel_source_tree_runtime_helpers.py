from __future__ import annotations

import json
import importlib.util
from collections.abc import Callable
from pathlib import Path
from shlex import quote

import pytest


def require_pcbnew_for_preflight(
    find_spec: Callable[[str], object | None] = importlib.util.find_spec,
) -> None:
    if find_spec("pcbnew") is not None:
        return

    pytest.skip(
        "pcbnew-backed preflight tests should run with /usr/bin/python3; "
        "virtualenv Python is expected to skip when pcbnew is unavailable",
        allow_module_level=False,
    )


def build_verification_lane_commands(manifest_path: Path | str) -> list[str]:
    return list(build_verification_lane_command_map(manifest_path).values())


def build_verification_lane_command_map(manifest_path: Path | str) -> dict[str, str]:
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))

    lanes = manifest.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        raise ValueError(f"{path}: expected a non-empty 'lanes' list")

    commands: dict[str, str] = {}
    for index, lane in enumerate(lanes):
        if not isinstance(lane, dict):
            raise ValueError(f"{path}: lane {index} must be an object")

        lane_name = lane.get("name")
        if not isinstance(lane_name, str) or not lane_name:
            raise ValueError(f"{path}: lane {index} is missing 'name'")

        interpreter = lane.get("interpreter")
        if not isinstance(interpreter, str) or not interpreter:
            raise ValueError(f"{path}: lane {index} is missing 'interpreter'")

        tests = lane.get("tests")
        if not isinstance(tests, list) or not tests:
            raise ValueError(f"{path}: lane {index} is missing non-empty 'tests'")

        test_args: list[str] = []
        for test_index, test_path in enumerate(tests):
            if not isinstance(test_path, str) or not test_path:
                raise ValueError(
                    f"{path}: lane {index} test {test_index} must be a non-empty string"
                )
            test_args.append(str(Path(test_path)))

        command_parts = [quote(interpreter), "-m", "pytest", *map(quote, test_args), "-q"]
        commands[lane_name] = " ".join(command_parts)

    return commands
