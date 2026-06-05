from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pardal.project.diagnostics import ProjectConfigError
from pardal.project.yaml import load_yaml_file
from pardal.project.versions import validate_requires_pardal

PROJECT_SCHEMA = "pardal.project/v1"
PACKAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")
TARGET_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
BUILD_OUTPUT_KEYS = {
    "kicad_pcb",
    "manufacturing_archive",
    "production_checks",
    "kicad_drc",
}
PRODUCTION_OUTPUT_KEYS = {
    "manufacturing_archive",
    "production_checks",
    "kicad_drc",
}


@dataclass(frozen=True, slots=True)
class DependencySpec:
    type: str
    identifier: str | None = None
    release: str | None = None
    path: Path | None = None
    repo: str | None = None
    ref: str | None = None
    path_within_repo: str | None = None


@dataclass(frozen=True, slots=True)
class PathConfig:
    source: Path = Path(".")
    layouts: Path = Path("layouts")
    artifacts: Path = Path(".pardal/build")
    packages: Path = Path(".pardal/packages")
    cache: Path = Path(".pardal/cache")


@dataclass(frozen=True, slots=True)
class BuildTarget:
    name: str
    entry: Path
    source_contract: Path | None = None
    profiles: tuple[str, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PackageExportConfig:
    profiles: tuple[Path, ...] = ()
    checks: tuple[Path, ...] = ()
    parts: tuple[Path, ...] = ()
    footprints: tuple[Path, ...] = ()
    physical_libraries: tuple[Path, ...] = ()
    route_policies: tuple[Path, ...] = ()
    board_templates: tuple[Path, ...] = ()
    examples: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectInfo:
    type: str
    name: str | None = None
    identifier: str | None = None
    version: str | None = None
    repository: str | None = None
    summary: str | None = None
    license: str | None = None
    authors: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    path: Path
    root: Path
    schema: str
    requires_pardal: str
    project: ProjectInfo
    paths: PathConfig
    dependencies: tuple[DependencySpec, ...] = ()
    builds: dict[str, BuildTarget] = field(default_factory=dict)
    exports: PackageExportConfig = field(default_factory=PackageExportConfig)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_package(self) -> bool:
        return self.project.type == "package"

    @property
    def is_board(self) -> bool:
        return self.project.type == "board"


def load_project_manifest(
    path: Path | str,
    *,
    allow_absolute_paths: bool = False,
) -> ProjectManifest:
    manifest_path = Path(path)
    raw = load_yaml_file(
        manifest_path,
        code="manifest.yaml_invalid",
        message="manifest file must be valid YAML",
    )
    if not isinstance(raw, dict):
        raise ProjectConfigError(
            "manifest.invalid",
            "manifest must be a mapping",
            path=manifest_path,
        )
    root = manifest_path.parent.resolve()
    return _parse_manifest(
        raw,
        manifest_path,
        root,
        allow_absolute_paths=allow_absolute_paths,
    )


def _parse_manifest(
    raw: dict[str, Any],
    path: Path,
    root: Path,
    *,
    allow_absolute_paths: bool,
) -> ProjectManifest:
    schema = _required_str(raw, "schema", path)
    if schema != PROJECT_SCHEMA:
        raise ProjectConfigError(
            "manifest.schema_unsupported",
            f"expected {PROJECT_SCHEMA!r}, got {schema!r}",
            path=path,
            field="schema",
        )
    requires_pardal = _required_str(raw, "requires-pardal", path)
    validate_requires_pardal(requires_pardal, path=path)
    project = _parse_project(raw.get("project"), path)
    paths = _parse_paths(
        raw.get("paths") or {},
        path,
        allow_absolute_paths=allow_absolute_paths,
    )
    dependencies = tuple(
        _parse_dependency(
            item,
            path,
            f"dependencies[{idx}]",
            allow_absolute_paths=allow_absolute_paths,
        )
        for idx, item in enumerate(_list(raw.get("dependencies") or [], path, "dependencies"))
    )
    builds = _parse_builds(
        raw.get("builds") or {},
        path,
        project.type,
        allow_absolute_paths=allow_absolute_paths,
    )
    exports = _parse_exports(
        raw.get("exports") or {},
        path,
        allow_absolute_paths=allow_absolute_paths,
    )

    if project.type == "board" and "default" not in builds:
        raise ProjectConfigError(
            "manifest.default_build_missing",
            "board projects require builds.default",
            path=path,
            field="builds.default",
        )
    if project.type == "package" and not _exports_nonempty(exports):
        raise ProjectConfigError(
            "manifest.package_exports_missing",
            "package projects require at least one export",
            path=path,
            field="exports",
        )

    return ProjectManifest(
        path=path,
        root=root,
        schema=schema,
        requires_pardal=requires_pardal,
        project=project,
        paths=paths,
        dependencies=dependencies,
        builds=builds,
        exports=exports,
        raw=raw,
    )


def _parse_project(value: Any, path: Path) -> ProjectInfo:
    if not isinstance(value, dict):
        raise ProjectConfigError("manifest.project_missing", "project must be a mapping", path=path, field="project")
    project_type = _required_str(value, "type", path, "project.type")
    if project_type not in {"board", "package"}:
        raise ProjectConfigError(
            "manifest.project_type_invalid",
            "project.type must be 'board' or 'package'",
            path=path,
            field="project.type",
        )
    if project_type == "board":
        return ProjectInfo(type=project_type, name=_optional_str(value, "name", path, "project.name"))

    identifier = _required_str(value, "identifier", path, "project.identifier")
    if not PACKAGE_ID_RE.match(identifier):
        raise ProjectConfigError(
            "manifest.package_identifier_invalid",
            "package identifier must match owner/name",
            path=path,
            field="project.identifier",
        )
    version = _required_str(value, "version", path, "project.version")
    if not SEMVER_RE.match(version):
        raise ProjectConfigError(
            "manifest.package_version_invalid",
            "package version must be SemVer",
            path=path,
            field="project.version",
        )
    authors = _package_authors(value.get("authors") or [], path)
    return ProjectInfo(
        type=project_type,
        identifier=identifier,
        version=version,
        repository=_required_str(value, "repository", path, "project.repository"),
        summary=_required_str(value, "summary", path, "project.summary"),
        license=_required_str(value, "license", path, "project.license"),
        authors=authors,
    )


def _parse_paths(
    value: Any,
    path: Path,
    *,
    allow_absolute_paths: bool,
) -> PathConfig:
    if not isinstance(value, dict):
        raise ProjectConfigError("manifest.paths_invalid", "paths must be a mapping", path=path, field="paths")
    return PathConfig(
        source=_relative_path(value.get("source", "."), path, "paths.source", allow_absolute_paths=allow_absolute_paths),
        layouts=_relative_path(value.get("layouts", "layouts"), path, "paths.layouts", allow_absolute_paths=allow_absolute_paths),
        artifacts=_relative_path(value.get("artifacts", ".pardal/build"), path, "paths.artifacts", allow_absolute_paths=allow_absolute_paths),
        packages=_relative_path(value.get("packages", ".pardal/packages"), path, "paths.packages", allow_absolute_paths=allow_absolute_paths),
        cache=_relative_path(value.get("cache", ".pardal/cache"), path, "paths.cache", allow_absolute_paths=allow_absolute_paths),
    )


def _parse_builds(
    value: Any,
    path: Path,
    project_type: str,
    *,
    allow_absolute_paths: bool,
) -> dict[str, BuildTarget]:
    if not isinstance(value, dict):
        raise ProjectConfigError("manifest.builds_invalid", "builds must be a mapping", path=path, field="builds")
    builds: dict[str, BuildTarget] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not TARGET_RE.match(name):
            raise ProjectConfigError("manifest.build_name_invalid", "invalid build target name", path=path, field=f"builds.{name}")
        if not isinstance(raw, dict):
            raise ProjectConfigError("manifest.build_invalid", "build target must be a mapping", path=path, field=f"builds.{name}")
        options = _dict(raw.get("options") or {}, path, f"builds.{name}.options")
        _validate_build_options(options, path, f"builds.{name}.options")
        outputs = _dict(raw.get("outputs") or {}, path, f"builds.{name}.outputs")
        _validate_build_outputs(
            outputs,
            options,
            path,
            f"builds.{name}.outputs",
        )
        builds[name] = BuildTarget(
            name=name,
            entry=_relative_path(_required_str(raw, "entry", path, f"builds.{name}.entry"), path, f"builds.{name}.entry", allow_absolute_paths=allow_absolute_paths),
            source_contract=(
                _relative_path(raw["source_contract"], path, f"builds.{name}.source_contract", allow_absolute_paths=allow_absolute_paths)
                if raw.get("source_contract") is not None
                else None
            ),
            profiles=tuple(_string_list(raw.get("profiles") or [], path, f"builds.{name}.profiles")),
            options=options,
            outputs=outputs,
        )
    if project_type == "package" and not builds:
        return {}
    return builds


def _validate_build_options(options: dict[str, Any], path: Path, field: str) -> None:
    if "allow_network_checks" in options and not isinstance(options["allow_network_checks"], bool):
        raise ProjectConfigError(
            "manifest.build_option_invalid",
            "build option allow_network_checks must be a boolean",
            path=path,
            field=f"{field}.allow_network_checks",
        )
    if "require_lock" in options and not isinstance(options["require_lock"], bool):
        raise ProjectConfigError(
            "manifest.build_option_invalid",
            "build option require_lock must be a boolean",
            path=path,
            field=f"{field}.require_lock",
        )


def _validate_build_outputs(
    outputs: dict[str, Any],
    options: dict[str, Any],
    path: Path,
    field: str,
) -> None:
    for key, value in outputs.items():
        if key not in BUILD_OUTPUT_KEYS:
            raise ProjectConfigError(
                "manifest.build_output_invalid",
                "build output is not supported",
                path=path,
                field=f"{field}.{key}",
            )
        if not isinstance(value, bool):
            raise ProjectConfigError(
                "manifest.build_output_invalid",
                "build output values must be booleans",
                path=path,
                field=f"{field}.{key}",
            )
    requested_production_outputs = [
        key for key in sorted(PRODUCTION_OUTPUT_KEYS)
        if outputs.get(key) is True
    ]
    if requested_production_outputs and options.get("require_lock") is not True:
        raise ProjectConfigError(
            "manifest.production_output_requires_lock",
            "production outputs require options.require_lock: true",
            path=path,
            field=f"{field}.{requested_production_outputs[0]}",
        )


def _parse_exports(
    value: Any,
    path: Path,
    *,
    allow_absolute_paths: bool,
) -> PackageExportConfig:
    if not isinstance(value, dict):
        raise ProjectConfigError("manifest.exports_invalid", "exports must be a mapping", path=path, field="exports")
    kwargs: dict[str, tuple[Path, ...]] = {}
    for key in PackageExportConfig.__dataclass_fields__:
        kwargs[key] = tuple(
            _relative_path(item, path, f"exports.{key}", allow_absolute_paths=allow_absolute_paths)
            for item in _string_list(value.get(key) or [], path, f"exports.{key}")
        )
    return PackageExportConfig(**kwargs)


def _parse_dependency(
    value: Any,
    path: Path,
    field: str,
    *,
    allow_absolute_paths: bool,
) -> DependencySpec:
    if isinstance(value, str):
        from pardal.packages.spec import parse_dependency_spec

        return parse_dependency_spec(value)
    if not isinstance(value, dict):
        raise ProjectConfigError("dependency.invalid", "dependency must be a mapping or string", path=path, field=field)
    dep_type = _required_str(value, "type", path, f"{field}.type")
    if dep_type == "registry":
        identifier = _required_str(value, "identifier", path, f"{field}.identifier")
        _validate_package_id(identifier, path, f"{field}.identifier")
        return DependencySpec(type=dep_type, identifier=identifier, release=_optional_str(value, "release", path, f"{field}.release"))
    if dep_type == "file":
        return DependencySpec(type=dep_type, path=_relative_path(_required_str(value, "path", path, f"{field}.path"), path, f"{field}.path", allow_absolute_paths=allow_absolute_paths))
    if dep_type == "git":
        identifier = _required_str(value, "identifier", path, f"{field}.identifier")
        _validate_package_id(identifier, path, f"{field}.identifier")
        path_within_repo = _optional_str(value, "path", path, f"{field}.path")
        if path_within_repo is not None:
            _validate_git_path_within_repo(path_within_repo, path, f"{field}.path")
        return DependencySpec(
            type=dep_type,
            identifier=identifier,
            repo=_required_str(value, "repo", path, f"{field}.repo"),
            ref=_optional_str(value, "ref", path, f"{field}.ref"),
            path_within_repo=path_within_repo,
        )
    raise ProjectConfigError("dependency.type_invalid", "dependency type must be registry, file, or git", path=path, field=f"{field}.type")


def _validate_package_id(identifier: str, path: Path, field: str) -> None:
    if not PACKAGE_ID_RE.match(identifier):
        raise ProjectConfigError("dependency.identifier_invalid", "identifier must match owner/name", path=path, field=field)


def _validate_git_path_within_repo(value: str, path: Path, field: str) -> None:
    candidate = Path(value)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ProjectConfigError(
            "dependency.git_path_invalid",
            "git dependency path must be relative and stay inside the repository",
            path=path,
            field=field,
        )


def _relative_path(
    value: Any,
    manifest_path: Path,
    field: str,
    *,
    allow_absolute_paths: bool,
) -> Path:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError("manifest.path_invalid", "path value must be a non-empty string", path=manifest_path, field=field)
    candidate = Path(value)
    if candidate.is_absolute() and not allow_absolute_paths:
        raise ProjectConfigError("manifest.absolute_path", "manifest paths must be relative", path=manifest_path, field=field)
    return candidate


def _required_str(value: dict[str, Any], key: str, path: Path, field: str | None = None) -> str:
    result = value.get(key)
    resolved_field = field or key
    if not isinstance(result, str) or not result:
        raise ProjectConfigError("manifest.required_string_missing", "required string is missing", path=path, field=resolved_field)
    return result


def _optional_str(value: dict[str, Any], key: str, path: Path, field: str) -> str | None:
    result = value.get(key)
    if result is None:
        return None
    if not isinstance(result, str) or not result:
        raise ProjectConfigError("manifest.string_invalid", "value must be a non-empty string", path=path, field=field)
    return result


def _list(value: Any, path: Path, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ProjectConfigError("manifest.list_invalid", "value must be a list", path=path, field=field)
    return value


def _string_list(value: Any, path: Path, field: str) -> list[str]:
    items = _list(value, path, field)
    for idx, item in enumerate(items):
        if not isinstance(item, str) or not item:
            raise ProjectConfigError("manifest.string_invalid", "list item must be a non-empty string", path=path, field=f"{field}[{idx}]")
    return items


def _package_authors(value: Any, path: Path) -> tuple[dict[str, Any], ...]:
    authors = _list(value, path, "project.authors")
    if not authors:
        raise ProjectConfigError(
            "manifest.package_authors_missing",
            "package projects require at least one author",
            path=path,
            field="project.authors",
        )
    parsed: list[dict[str, Any]] = []
    for index, author in enumerate(authors):
        field = f"project.authors[{index}]"
        if not isinstance(author, dict):
            raise ProjectConfigError(
                "manifest.package_author_invalid",
                "package author entries must be mappings",
                path=path,
                field=field,
            )
        name = author.get("name")
        if not isinstance(name, str) or not name:
            raise ProjectConfigError(
                "manifest.package_author_name_missing",
                "package author entries require a non-empty name",
                path=path,
                field=f"{field}.name",
            )
        parsed.append(dict(author))
    return tuple(parsed)


def _dict(value: Any, path: Path, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProjectConfigError("manifest.mapping_invalid", "value must be a mapping", path=path, field=field)
    return value


def _exports_nonempty(exports: PackageExportConfig) -> bool:
    return any(getattr(exports, key) for key in PackageExportConfig.__dataclass_fields__)
