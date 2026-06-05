from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pardal.packages.exports import ExportDefinition
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.yaml import load_yaml_file


@dataclass(frozen=True, slots=True)
class PartDefinition:
    id: str
    package_id: str
    path: Path
    manufacturer: str | None = None
    mpn: str | None = None
    package: str | None = None
    pins: int | None = None
    lcsc: str | None = None
    footprint: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


def load_part_catalog_export(export: ExportDefinition) -> dict[str, PartDefinition]:
    raw = load_yaml_file(
        export.absolute_path,
        code="part_catalog.yaml_invalid",
        message="part catalog YAML is invalid",
    )
    if not isinstance(raw, dict) or raw.get("schema") != "pardal.parts/v1":
        raise ProjectConfigError(
            "part_catalog.schema_invalid",
            "expected schema pardal.parts/v1",
            path=export.absolute_path,
            field="schema",
        )
    parts = raw.get("parts")
    if not isinstance(parts, dict) or not parts:
        raise ProjectConfigError(
            "part_catalog.definitions_missing",
            "parts must be a non-empty mapping",
            path=export.absolute_path,
            field="parts",
        )
    loaded: dict[str, PartDefinition] = {}
    for part_id, value in parts.items():
        part_name = _local_id(part_id, export.absolute_path, "parts")
        if not isinstance(value, dict):
            raise ProjectConfigError(
                "part_catalog.definition_invalid",
                "part definition must be a mapping",
                path=export.absolute_path,
                field=f"parts.{part_name}",
            )
        qualified_id = _qualified_id(
            export.package_id,
            part_name,
            export.absolute_path,
            "parts",
        )
        loaded[qualified_id] = PartDefinition(
            id=qualified_id,
            package_id=export.package_id,
            path=export.absolute_path,
            manufacturer=_optional_str(value.get("manufacturer"), export.absolute_path, f"parts.{part_name}.manufacturer"),
            mpn=_optional_str(value.get("mpn"), export.absolute_path, f"parts.{part_name}.mpn"),
            package=_optional_str(value.get("package"), export.absolute_path, f"parts.{part_name}.package"),
            pins=_optional_positive_int(value.get("pins"), export.absolute_path, f"parts.{part_name}.pins"),
            lcsc=_optional_str(value.get("lcsc"), export.absolute_path, f"parts.{part_name}.lcsc"),
            footprint=_optional_str(value.get("footprint"), export.absolute_path, f"parts.{part_name}.footprint"),
            attributes=_optional_mapping(value.get("attributes"), export.absolute_path, f"parts.{part_name}.attributes"),
        )
    return loaded


def _qualified_id(package_id: str, value: str, path: Path, field: str) -> str:
    if ":" in value:
        owner, symbol = value.split(":", 1)
        if owner != package_id or not symbol:
            raise ProjectConfigError(
                "part_catalog.id_invalid",
                "part id must be local to this package namespace",
                path=path,
                field=field,
            )
        return value
    return f"{package_id}:{value}"


def _local_id(value: Any, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "part_catalog.id_invalid",
            "part id must be a non-empty string",
            path=path,
            field=field,
        )
    return value


def _optional_str(value: Any, path: Path, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProjectConfigError("part_catalog.string_invalid", "value must be a non-empty string", path=path, field=field)
    return value


def _optional_mapping(value: Any, path: Path, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProjectConfigError("part_catalog.mapping_invalid", "value must be a mapping", path=path, field=field)
    return dict(value)


def _optional_positive_int(value: Any, path: Path, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProjectConfigError(
            "part_catalog.positive_int_invalid",
            "value must be a positive integer",
            path=path,
            field=field,
        )
    return value
