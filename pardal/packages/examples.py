from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pardal.packages.exports import ExportDefinition
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.yaml import load_yaml_file


@dataclass(frozen=True, slots=True)
class ExampleDefinition:
    id: str
    package_id: str
    path: Path
    example_path: Path
    mode: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def load_example_export(export: ExportDefinition) -> dict[str, ExampleDefinition]:
    raw = load_yaml_file(
        export.absolute_path,
        code="example.yaml_invalid",
        message="example YAML is invalid",
    )
    if not isinstance(raw, dict) or raw.get("schema") != "pardal.examples/v1":
        raise ProjectConfigError(
            "example.schema_invalid",
            "expected schema pardal.examples/v1",
            path=export.absolute_path,
            field="schema",
        )
    examples = raw.get("examples")
    if not isinstance(examples, dict) or not examples:
        raise ProjectConfigError(
            "example.definitions_missing",
            "examples must be a non-empty mapping",
            path=export.absolute_path,
            field="examples",
        )
    loaded: dict[str, ExampleDefinition] = {}
    for example_id, value in examples.items():
        example_name = _local_id(example_id, export.absolute_path, "examples")
        if not isinstance(value, dict):
            raise ProjectConfigError(
                "example.definition_invalid",
                "example definition must be a mapping",
                path=export.absolute_path,
                field=f"examples.{example_name}",
            )
        rel_path = _relative_path(
            value.get("path"),
            export.absolute_path,
            f"examples.{example_name}.path",
        )
        qualified_id = _qualified_id(
            export.package_id,
            example_name,
            export.absolute_path,
            "examples",
        )
        loaded[qualified_id] = ExampleDefinition(
            id=qualified_id,
            package_id=export.package_id,
            path=export.absolute_path,
            example_path=rel_path,
            mode=_optional_mode(value.get("mode"), export.absolute_path, f"examples.{example_name}.mode"),
            description=_optional_str(value.get("description"), export.absolute_path, f"examples.{example_name}.description"),
            metadata=_optional_mapping(value.get("metadata"), export.absolute_path, f"examples.{example_name}.metadata"),
        )
    return loaded


def _qualified_id(package_id: str, value: str, path: Path, field: str) -> str:
    if ":" in value:
        owner, symbol = value.split(":", 1)
        if owner != package_id or not symbol:
            raise ProjectConfigError(
                "example.id_invalid",
                "example id must be local to this package namespace",
                path=path,
                field=field,
            )
        return value
    return f"{package_id}:{value}"


def _local_id(value: Any, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "example.id_invalid",
            "example id must be a non-empty string",
            path=path,
            field=field,
        )
    return value


def _relative_path(value: Any, path: Path, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError("example.path_invalid", "path must be a non-empty string", path=path, field=field)
    candidate = Path(value)
    if candidate.is_absolute():
        raise ProjectConfigError("example.absolute_path", "example paths must be relative", path=path, field=field)
    return candidate


def _optional_str(value: Any, path: Path, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProjectConfigError("example.string_invalid", "value must be a non-empty string", path=path, field=field)
    return value


def _optional_mode(value: Any, path: Path, field: str) -> str | None:
    mode = _optional_str(value, path, field)
    if mode is None:
        return None
    if mode not in {"documentation_only", "build"}:
        raise ProjectConfigError(
            "example.mode_invalid",
            "example mode must be documentation_only or build",
            path=path,
            field=field,
        )
    return mode


def _optional_mapping(value: Any, path: Path, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProjectConfigError("example.mapping_invalid", "value must be a mapping", path=path, field=field)
    return dict(value)
