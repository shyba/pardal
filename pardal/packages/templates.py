from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pardal.packages.exports import ExportDefinition
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.manifest import PACKAGE_ID_RE
from pardal.project.yaml import load_yaml_file


@dataclass(frozen=True, slots=True)
class BoardTemplateDefinition:
    id: str
    package_id: str
    path: Path
    template_path: Path
    default_dependencies: tuple[str, ...] = ()
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def load_board_template_export(
    export: ExportDefinition,
) -> dict[str, BoardTemplateDefinition]:
    raw = load_yaml_file(
        export.absolute_path,
        code="template.yaml_invalid",
        message="template YAML is invalid",
    )
    if not isinstance(raw, dict) or raw.get("schema") != "pardal.templates/v1":
        raise ProjectConfigError(
            "template.schema_invalid",
            "expected schema pardal.templates/v1",
            path=export.absolute_path,
            field="schema",
        )
    templates = raw.get("templates")
    if not isinstance(templates, dict) or not templates:
        raise ProjectConfigError(
            "template.definitions_missing",
            "templates must be a non-empty mapping",
            path=export.absolute_path,
            field="templates",
        )
    loaded: dict[str, BoardTemplateDefinition] = {}
    for template_id, value in templates.items():
        template_name = _local_id(template_id, export.absolute_path, "templates")
        if not isinstance(value, dict):
            raise ProjectConfigError(
                "template.definition_invalid",
                "template definition must be a mapping",
                path=export.absolute_path,
                field=f"templates.{template_name}",
            )
        rel_path = _relative_path(
            value.get("path"),
            export.absolute_path,
            f"templates.{template_name}.path",
        )
        qualified_id = _qualified_id(
            export.package_id,
            template_name,
            export.absolute_path,
            "templates",
        )
        loaded[qualified_id] = BoardTemplateDefinition(
            id=qualified_id,
            package_id=export.package_id,
            path=export.absolute_path,
            template_path=rel_path,
            default_dependencies=tuple(
                _string_list(
                    value.get("default_dependencies") or [],
                    export.absolute_path,
                    f"templates.{template_name}.default_dependencies",
                )
            ),
            description=_optional_str(
                value.get("description"),
                export.absolute_path,
                f"templates.{template_name}.description",
            ),
            metadata=_optional_mapping(
                value.get("metadata"),
                export.absolute_path,
                f"templates.{template_name}.metadata",
            ),
        )
    return loaded


def _qualified_id(package_id: str, value: str, path: Path, field: str) -> str:
    if ":" in value:
        owner, symbol = value.split(":", 1)
        if owner != package_id or not symbol:
            raise ProjectConfigError(
                "template.id_invalid",
                "template id must be local to this package namespace",
                path=path,
                field=field,
            )
        return value
    return f"{package_id}:{value}"


def _local_id(value: Any, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "template.id_invalid",
            "template id must be a non-empty string",
            path=path,
            field=field,
        )
    return value


def _relative_path(value: Any, path: Path, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "template.path_invalid",
            "path must be a non-empty string",
            path=path,
            field=field,
        )
    candidate = Path(value)
    if candidate.is_absolute():
        raise ProjectConfigError(
            "template.absolute_path",
            "template paths must be relative",
            path=path,
            field=field,
        )
    return candidate


def _string_list(value: Any, path: Path, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ProjectConfigError(
            "template.list_invalid",
            "value must be a list",
            path=path,
            field=field,
        )
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not PACKAGE_ID_RE.match(item):
            raise ProjectConfigError(
                "template.string_invalid",
                "list item must be a package identifier",
                path=path,
                field=f"{field}[{index}]",
            )
        result.append(item)
    return result


def _optional_str(value: Any, path: Path, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "template.string_invalid",
            "value must be a non-empty string",
            path=path,
            field=field,
        )
    return value


def _optional_mapping(value: Any, path: Path, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProjectConfigError(
            "template.mapping_invalid",
            "value must be a mapping",
            path=path,
            field=field,
        )
    return dict(value)
