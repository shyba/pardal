from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pardal.packages.exports import ExportDefinition
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.yaml import load_yaml_file


@dataclass(frozen=True, slots=True)
class PhysicalLibraryDefinition:
    id: str
    package_id: str
    path: Path
    footprints: tuple[str, ...] = ()
    netclasses: tuple[str, ...] = ()
    placements: tuple[str, ...] = ()
    route_groups: tuple[str, ...] = ()
    mechanical: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def load_physical_library_export(
    export: ExportDefinition,
) -> dict[str, PhysicalLibraryDefinition]:
    raw = load_yaml_file(
        export.absolute_path,
        code="physical_library.yaml_invalid",
        message="physical library YAML is invalid",
    )
    if not isinstance(raw, dict) or raw.get("schema") != "pardal.physical_library/v1":
        raise ProjectConfigError(
            "physical_library.schema_invalid",
            "expected schema pardal.physical_library/v1",
            path=export.absolute_path,
            field="schema",
        )
    libraries = raw.get("libraries")
    if not isinstance(libraries, dict) or not libraries:
        raise ProjectConfigError(
            "physical_library.definitions_missing",
            "libraries must be a non-empty mapping",
            path=export.absolute_path,
            field="libraries",
        )
    loaded: dict[str, PhysicalLibraryDefinition] = {}
    for library_id, value in libraries.items():
        library_name = _local_id(library_id, export.absolute_path, "libraries")
        if not isinstance(value, dict):
            raise ProjectConfigError(
                "physical_library.definition_invalid",
                "library definition must be a mapping",
                path=export.absolute_path,
                field=f"libraries.{library_name}",
            )
        qualified_id = _qualified_id(
            export.package_id,
            library_name,
            export.absolute_path,
            "libraries",
        )
        loaded[qualified_id] = PhysicalLibraryDefinition(
            id=qualified_id,
            package_id=export.package_id,
            path=export.absolute_path,
            footprints=tuple(_string_list(value.get("footprints") or [], export.absolute_path, f"libraries.{library_name}.footprints")),
            netclasses=tuple(_string_list(value.get("netclasses") or [], export.absolute_path, f"libraries.{library_name}.netclasses")),
            placements=tuple(_string_list(value.get("placements") or [], export.absolute_path, f"libraries.{library_name}.placements")),
            route_groups=tuple(_string_list(value.get("route_groups") or [], export.absolute_path, f"libraries.{library_name}.route_groups")),
            mechanical=tuple(_string_list(value.get("mechanical") or [], export.absolute_path, f"libraries.{library_name}.mechanical")),
            metadata=_optional_mapping(value.get("metadata"), export.absolute_path, f"libraries.{library_name}.metadata"),
        )
    return loaded


def _qualified_id(package_id: str, value: str, path: Path, field: str) -> str:
    if ":" in value:
        owner, symbol = value.split(":", 1)
        if owner != package_id or not symbol:
            raise ProjectConfigError(
                "physical_library.id_invalid",
                "physical library id must be local to this package namespace",
                path=path,
                field=field,
            )
        return value
    return f"{package_id}:{value}"


def _local_id(value: Any, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "physical_library.id_invalid",
            "physical library id must be a non-empty string",
            path=path,
            field=field,
        )
    return value


def _string_list(value: Any, path: Path, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ProjectConfigError("physical_library.list_invalid", "value must be a list", path=path, field=field)
    result: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ProjectConfigError("physical_library.string_invalid", "list item must be a non-empty string", path=path, field=f"{field}[{idx}]")
        result.append(item)
    return result


def _optional_mapping(value: Any, path: Path, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProjectConfigError("physical_library.mapping_invalid", "value must be a mapping", path=path, field=field)
    return dict(value)
