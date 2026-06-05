from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pardal.packages.lock import file_hash
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.manifest import PackageExportConfig, ProjectManifest
from pardal.project.yaml import load_yaml_file

EXPORT_SCHEMAS = {
    "profiles": "pardal.profile/v1",
    "parts": "pardal.parts/v1",
    "footprints": "pardal.footprints/v1",
    "physical_libraries": "pardal.physical_library/v1",
    "route_policies": "pardal.route_policy/v1",
    "board_templates": "pardal.templates/v1",
    "examples": "pardal.examples/v1",
}

TOP_LEVEL_KEYS = {
    "profiles": "profiles",
    "parts": "parts",
    "footprints": "footprints",
    "physical_libraries": "libraries",
    "route_policies": "policies",
    "board_templates": "templates",
    "examples": "examples",
}


@dataclass(frozen=True, slots=True)
class ExportDefinition:
    kind: str
    id: str
    path: Path
    hash: str
    package_id: str
    package_root: Path

    @property
    def absolute_path(self) -> Path:
        return self.package_root / self.path


def scan_package_exports(manifest: ProjectManifest) -> tuple[ExportDefinition, ...]:
    if not manifest.project.identifier:
        raise ProjectConfigError(
            "package.identifier_missing",
            "package manifest has no identifier",
            path=manifest.path,
            field="project.identifier",
        )
    exports: list[ExportDefinition] = []
    config = manifest.exports
    for kind in PackageExportConfig.__dataclass_fields__:
        for rel_path in getattr(config, kind):
            exports.extend(_scan_export_path(manifest, kind, rel_path))
    _check_duplicates(exports, manifest.path)
    return tuple(exports)


def _scan_export_path(
    manifest: ProjectManifest,
    kind: str,
    rel_path: Path,
) -> list[ExportDefinition]:
    package_root = manifest.root.resolve()
    abs_path = (manifest.root / rel_path).resolve()
    try:
        abs_path.relative_to(package_root)
    except ValueError as exc:
        raise ProjectConfigError(
            "package.export_path_outside",
            "export path must stay inside the package root",
            path=manifest.path,
            field=f"exports.{kind}",
        ) from exc
    if not abs_path.exists():
        raise ProjectConfigError(
            "package.export_path_missing",
            "export path does not exist",
            path=manifest.path,
            field=f"exports.{kind}",
        )
    if abs_path.is_dir():
        found: list[ExportDefinition] = []
        for child in sorted(p for p in abs_path.rglob("*") if p.is_file()):
            found.extend(_scan_export_file(manifest, kind, child, explicit=False))
        if not found:
            raise ProjectConfigError(
                "package.export_dir_empty",
                "export directory contains no recognized exports",
                path=manifest.path,
                field=f"exports.{kind}",
            )
        return found
    return _scan_export_file(manifest, kind, abs_path, explicit=True)


def _scan_export_file(
    manifest: ProjectManifest,
    kind: str,
    abs_path: Path,
    *,
    explicit: bool,
) -> list[ExportDefinition]:
    if kind == "checks":
        if abs_path.suffix != ".py":
            if explicit:
                raise ProjectConfigError(
                    "package.export_file_invalid",
                    "check export file must be a Python module",
                    path=abs_path,
                    field=f"exports.{kind}",
                )
            return []
        return [
            ExportDefinition(
                kind=kind,
                id=f"{manifest.project.identifier}:{abs_path.stem}",
                path=abs_path.relative_to(manifest.root),
                hash=file_hash(abs_path),
                package_id=manifest.project.identifier or "",
                package_root=manifest.root,
            )
        ]
    if abs_path.suffix not in {".yaml", ".yml"}:
        if explicit:
            raise ProjectConfigError(
                "package.export_file_invalid",
                "export file must be YAML",
                path=abs_path,
                field=f"exports.{kind}",
            )
        return []
    try:
        raw = load_yaml_file(
            abs_path,
            code="package.export_file_invalid",
            message="export file must be valid YAML",
        )
    except ProjectConfigError as exc:
        if explicit:
            raise
        return []
    if not isinstance(raw, dict):
        if explicit:
            raise ProjectConfigError(
                "package.export_file_invalid",
                "export file must be a mapping",
                path=abs_path,
                field=f"exports.{kind}",
            )
        return []
    expected_schema = EXPORT_SCHEMAS.get(kind)
    if raw.get("schema") != expected_schema:
        if explicit:
            raise ProjectConfigError(
                "package.export_schema_invalid",
                f"expected schema {expected_schema}",
                path=abs_path,
                field="schema",
            )
        return []
    top_key = TOP_LEVEL_KEYS[kind]
    values = raw.get(top_key)
    if not isinstance(values, dict) or not values:
        raise ProjectConfigError(
            "package.export_definitions_missing",
            f"{top_key} must be a non-empty mapping",
            path=abs_path,
            field=top_key,
        )
    return [
        ExportDefinition(
            kind=kind,
            id=_qualified_id(
                manifest.project.identifier or "",
                _export_id(
                    export_id,
                    abs_path,
                    top_key,
                    package_id=manifest.project.identifier or "",
                ),
            ),
            path=abs_path.relative_to(manifest.root),
            hash=file_hash(abs_path),
            package_id=manifest.project.identifier or "",
            package_root=manifest.root,
        )
        for export_id in values
    ]


def _export_id(value: Any, path: Path, field: str, *, package_id: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            _export_id_error_code(field),
            "export id must be a non-empty string",
            path=path,
            field=field,
        )
    if ":" in value:
        owner, symbol = value.split(":", 1)
        if owner != package_id or not symbol:
            raise ProjectConfigError(
                _export_id_error_code(field),
                "export id must be local to this package namespace",
                path=path,
                field=field,
            )
    return value


def _export_id_error_code(field: str) -> str:
    return {
        "profiles": "profile.id_invalid",
        "parts": "part_catalog.id_invalid",
        "footprints": "footprint.id_invalid",
        "libraries": "physical_library.id_invalid",
        "policies": "route_policy.id_invalid",
        "templates": "package.template_id_invalid",
        "examples": "example.id_invalid",
    }.get(field, "package.export_id_invalid")


def _qualified_id(package_id: str, export_id: str) -> str:
    if ":" in export_id:
        return export_id
    return f"{package_id}:{export_id}"


def _check_duplicates(exports: list[ExportDefinition], manifest_path: Path) -> None:
    seen: set[str] = set()
    for export in exports:
        key = f"{export.kind}:{export.id}"
        if key in seen:
            raise ProjectConfigError(
                "package.export_duplicate",
                f"duplicate export {export.id!r} for {export.kind}",
                path=manifest_path,
                field=f"exports.{export.kind}",
            )
        seen.add(key)
