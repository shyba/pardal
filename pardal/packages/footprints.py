from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pardal.packages.exports import ExportDefinition
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.yaml import load_yaml_file


@dataclass(frozen=True, slots=True)
class FootprintDefinition:
    id: str
    package_id: str
    path: Path
    source_path: Path | None = None
    kind: str = ""
    kicad: str | None = None
    package_name: str = ""
    pitch: str = ""
    courtyard_required: bool = False
    aliases: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def load_footprint_export(export: ExportDefinition) -> dict[str, FootprintDefinition]:
    raw = load_yaml_file(
        export.absolute_path,
        code="footprint.yaml_invalid",
        message="footprint YAML is invalid",
    )
    if not isinstance(raw, dict) or raw.get("schema") != "pardal.footprints/v1":
        raise ProjectConfigError(
            "footprint.schema_invalid",
            "expected schema pardal.footprints/v1",
            path=export.absolute_path,
            field="schema",
        )
    footprints = raw.get("footprints")
    if not isinstance(footprints, dict) or not footprints:
        raise ProjectConfigError(
            "footprint.definitions_missing",
            "footprints must be a non-empty mapping",
            path=export.absolute_path,
            field="footprints",
        )
    loaded: dict[str, FootprintDefinition] = {}
    for footprint_id, value in footprints.items():
        footprint_name = _local_id(footprint_id, export.absolute_path, "footprints")
        if not isinstance(value, dict):
            raise ProjectConfigError(
                "footprint.definition_invalid",
                "footprint definition must be a mapping",
                path=export.absolute_path,
                field=f"footprints.{footprint_name}",
            )
        qualified_id = _qualified_id(
            export.package_id,
            footprint_name,
            export.absolute_path,
            "footprints",
        )
        loaded[qualified_id] = FootprintDefinition(
            id=qualified_id,
            package_id=export.package_id,
            path=export.absolute_path,
            source_path=_optional_relative_path(
                value.get("path"),
                export.absolute_path,
                f"footprints.{footprint_name}.path",
                package_root=export.package_root,
            ),
            kind=_optional_str(value.get("kind"), export.absolute_path, f"footprints.{footprint_name}.kind") or "",
            kicad=_optional_str(value.get("kicad"), export.absolute_path, f"footprints.{footprint_name}.kicad"),
            package_name=_optional_str(value.get("package"), export.absolute_path, f"footprints.{footprint_name}.package") or "",
            pitch=_optional_str(value.get("pitch"), export.absolute_path, f"footprints.{footprint_name}.pitch") or "",
            courtyard_required=_optional_bool(value.get("courtyard_required"), export.absolute_path, f"footprints.{footprint_name}.courtyard_required"),
            aliases=tuple(_string_list(value.get("aliases") or [], export.absolute_path, f"footprints.{footprint_name}.aliases")),
            metadata=_optional_mapping(value.get("metadata"), export.absolute_path, f"footprints.{footprint_name}.metadata"),
        )
    return loaded


def _qualified_id(package_id: str, value: str, path: Path, field: str) -> str:
    if ":" in value:
        owner, symbol = value.split(":", 1)
        if owner != package_id or not symbol:
            raise ProjectConfigError(
                "footprint.id_invalid",
                "footprint id must be local to this package namespace",
                path=path,
                field=field,
            )
        return value
    return f"{package_id}:{value}"


def _local_id(value: Any, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "footprint.id_invalid",
            "footprint id must be a non-empty string",
            path=path,
            field=field,
        )
    return value


def _optional_str(value: Any, path: Path, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProjectConfigError("footprint.string_invalid", "value must be a non-empty string", path=path, field=field)
    return value


def _optional_relative_path(value: Any, path: Path, field: str, *, package_root: Path) -> Path | None:
    raw = _optional_str(value, path, field)
    if raw is None:
        return None
    rel = Path(raw)
    if rel.is_absolute():
        raise ProjectConfigError(
            "footprint.path_absolute",
            "footprint path must be relative to the footprint export file",
            path=path,
            field=field,
        )
    resolved = (path.parent / rel).resolve()
    try:
        resolved.relative_to(package_root.resolve())
    except ValueError as exc:
        raise ProjectConfigError(
            "footprint.path_outside_package",
            "footprint path must stay inside the package root",
            path=path,
            field=field,
        ) from exc
    if not resolved.exists():
        raise ProjectConfigError(
            "footprint.path_missing",
            "footprint path does not exist",
            path=path,
            field=field,
        )
    return resolved


def _string_list(value: Any, path: Path, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ProjectConfigError("footprint.list_invalid", "value must be a list", path=path, field=field)
    result: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ProjectConfigError("footprint.string_invalid", "list item must be a non-empty string", path=path, field=f"{field}[{idx}]")
        result.append(item)
    return result


def _optional_mapping(value: Any, path: Path, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProjectConfigError("footprint.mapping_invalid", "value must be a mapping", path=path, field=field)
    return dict(value)

def _optional_bool(value: Any, path: Path, field: str) -> bool:
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ProjectConfigError("footprint.boolean_invalid", "value must be a boolean", path=path, field=field)
    return value
