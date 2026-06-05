from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tests.parallel_source_tree_runtime_helpers import build_verification_lane_command_map


@dataclass(frozen=True, slots=True)
class SourceTreeLaneSelection:
    package_id: str
    lane_name: str
    manifest_path: Path
    interpreter: str
    command: str
    package_entry: dict[str, object]


def select_source_tree_lane(
    index_path: Path | str,
    package_id: str,
    lane_name: str | None = None,
) -> SourceTreeLaneSelection:
    path = Path(index_path)
    index = json.loads(path.read_text(encoding="utf-8"))

    packages = index.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError(f"{path}: expected a non-empty 'packages' list")

    package_entry: dict[str, object] | None = None
    for entry in packages:
        if not isinstance(entry, dict):
            continue
        if entry.get("package_id") == package_id:
            package_entry = entry
            break

    if package_entry is None:
        raise ValueError(f"{path}: unknown package_id {package_id!r}")

    entry_lane_names = package_entry.get("lane_names")
    if not isinstance(entry_lane_names, list) or not entry_lane_names:
        raise ValueError(f"{path}: package {package_id!r} is missing lane_names")

    entry_lane_interpreters = package_entry.get("lane_interpreters")
    if not isinstance(entry_lane_interpreters, dict) or not entry_lane_interpreters:
        raise ValueError(f"{path}: package {package_id!r} is missing lane_interpreters")

    selected_lane = package_entry.get("safe_default_lane") if lane_name is None else lane_name
    if not isinstance(selected_lane, str) or not selected_lane:
        raise ValueError(f"{path}: package {package_id!r} has an invalid safe default lane")

    if selected_lane not in entry_lane_names:
        raise ValueError(
            f"{path}: unknown lane_name {selected_lane!r} for package {package_id!r}"
        )

    interpreter = entry_lane_interpreters.get(selected_lane)
    if not isinstance(interpreter, str) or not interpreter:
        raise ValueError(
            f"{path}: lane_name {selected_lane!r} has no interpreter in package {package_id!r}"
        )

    manifest_path_value = package_entry.get("verification_lanes_manifest_path")
    if not isinstance(manifest_path_value, str) or not manifest_path_value:
        raise ValueError(
            f"{path}: package {package_id!r} is missing verification_lanes_manifest_path"
        )

    manifest_path = Path(manifest_path_value)
    if not manifest_path.exists():
        raise ValueError(f"{manifest_path}: manifest path does not exist")

    commands = build_verification_lane_command_map(manifest_path)
    command = commands.get(selected_lane)
    if not isinstance(command, str) or not command.startswith(f"{interpreter} -m pytest"):
        raise ValueError(
            f"{path}: no command found for lane_name {selected_lane!r} with interpreter {interpreter!r}"
        )

    return SourceTreeLaneSelection(
        package_id=package_id,
        lane_name=selected_lane,
        manifest_path=manifest_path,
        interpreter=interpreter,
        command=command,
        package_entry=package_entry,
    )
