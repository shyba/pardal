from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pardal.packages.exports import ExportDefinition, scan_package_exports
from pardal.packages.examples import load_example_export
from pardal.packages.footprints import load_footprint_export
from pardal.packages.lock import (
    file_hash,
    is_ignored_package_generated_path,
    package_content_hash,
)
from pardal.packages.parts import load_part_catalog_export
from pardal.packages.physical_libraries import load_physical_library_export
from pardal.packages.registry_client import REGISTRY_SCHEMA
from pardal.packages.route_policies import load_route_policy_export
from pardal.packages.source_safety import check_package_source_members
from pardal.profiles.loader import load_profile_file
from pardal.profiles.model import ProfileDefinition
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.lockfile import load_project_lock_file
from pardal.project.manifest import PACKAGE_ID_RE, ProjectManifest, load_project_manifest
from pardal.project.yaml import load_yaml_file
from pardal.project.versions import SEMVER_RE, validate_requires_pardal

SHA256_RE = re.compile(r"^(sha256:)?[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class PackageCheckReport:
    manifest: ProjectManifest
    exports: tuple[ExportDefinition, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PackageBuildResult:
    archive_path: Path
    manifest_path: Path
    sha256_path: Path


@dataclass(frozen=True, slots=True)
class PackagePublishResult:
    archive_path: Path
    manifest_path: Path
    sha256_path: Path
    dry_run: bool
    registry_index: Path | None = None


def check_package(
    manifest_path: Path | str = "pardal.yaml",
    *,
    publish: bool = False,
) -> PackageCheckReport:
    manifest = load_project_manifest(manifest_path)
    if not manifest.is_package:
        raise ProjectConfigError(
            "package.check_not_package",
            "package check requires project.type: package",
            path=manifest.path,
            field="project.type",
        )
    if publish:
        _check_publishable_dependencies(manifest)
    check_package_source_members(manifest.root)
    source_hash_before = package_content_hash(manifest.root)
    exports = scan_package_exports(manifest)
    _check_python_check_trust(manifest, exports)
    _check_profiles(manifest, exports)
    _check_part_catalogs(exports)
    _check_footprints(exports)
    _check_physical_libraries(exports)
    _check_route_policies(exports)
    _check_check_modules(manifest, exports)
    _check_templates(manifest, exports)
    _check_examples(manifest, exports)
    source_hash_after = package_content_hash(manifest.root)
    if source_hash_after != source_hash_before:
        raise ProjectConfigError(
            "package.source_mutated",
            "package check validation must not mutate package source files",
            path=manifest.path,
            field="package",
        )
    return PackageCheckReport(manifest=manifest, exports=exports)


def build_package(
    manifest_path: Path | str = "pardal.yaml",
    *,
    output_dir: Path | str | None = None,
) -> PackageBuildResult:
    report = check_package(manifest_path)
    manifest = report.manifest
    _require_package_lock(manifest)
    assert manifest.project.identifier is not None
    assert manifest.project.version is not None
    paths = _package_build_paths(manifest, output_dir=output_dir)
    paths.archive_path.parent.mkdir(parents=True, exist_ok=True)

    with paths.archive_path.open("wb") as raw_archive:
        with gzip.GzipFile(fileobj=raw_archive, mode="wb", mtime=0) as gzip_archive:
            with tarfile.open(fileobj=gzip_archive, mode="w") as archive:
                for path in _iter_package_files(manifest.root):
                    _add_deterministic_tar_file(
                        archive,
                        path,
                        arcname=path.relative_to(manifest.root).as_posix(),
                    )

    manifest_payload = {
        "schema": "pardal.package_manifest/v1",
        "identifier": manifest.project.identifier,
        "version": manifest.project.version,
        "content_hash": package_content_hash(manifest.root),
        "archive": paths.archive_path.name,
        "exports": [
            {
                "kind": export.kind,
                "id": export.id,
                "path": export.path.as_posix(),
                "hash": export.hash,
            }
            for export in sorted(
                report.exports,
                key=lambda item: (item.kind, item.id, item.path.as_posix()),
            )
        ],
    }
    paths.manifest_path.write_text(
        json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths.sha256_path.write_text(
        f"{_sha256_file(paths.archive_path)}  {paths.archive_path.name}\n",
        encoding="utf-8",
    )
    return paths


def _package_build_paths(
    manifest: ProjectManifest,
    *,
    output_dir: Path | str | None = None,
) -> PackageBuildResult:
    assert manifest.project.identifier is not None
    assert manifest.project.version is not None
    dist_dir = Path(output_dir) if output_dir is not None else manifest.root / "dist"
    archive_stem = f"{manifest.project.identifier.replace('/', '-')}-{manifest.project.version}"
    return PackageBuildResult(
        archive_path=dist_dir / f"{archive_stem}.tar.gz",
        manifest_path=dist_dir / f"{archive_stem}.manifest.json",
        sha256_path=dist_dir / f"{archive_stem}.sha256",
    )


def _require_package_lock(manifest: ProjectManifest) -> None:
    lock_path = manifest.root / "pardal.lock"
    if not lock_path.exists():
        raise ProjectConfigError(
            "project.lock_required",
            "project is not synced; run `pardal sync`",
            path=manifest.path,
            field="pardal.lock",
        )
    lock = load_project_lock_file(lock_path)
    expected_manifest = manifest.path.relative_to(manifest.root).as_posix()
    if lock.manifest != expected_manifest or lock.project_hash != file_hash(manifest.path):
        raise ProjectConfigError(
            "project.lock_out_of_sync",
            "pardal.lock does not match pardal.yaml; run `pardal sync`",
            path=manifest.path,
            field="pardal.lock",
        )
    expected_roots = _declared_dependency_ids(manifest)
    reachable = _reachable_locked_package_ids(lock.packages, expected_roots, manifest.path)
    extra = set(lock.packages) - reachable
    if extra:
        first = sorted(extra)[0]
        raise ProjectConfigError(
            "project.lock_out_of_sync",
            f"pardal.lock includes package {first!r} not reachable from pardal.yaml; run `pardal sync`",
            path=manifest.path,
            field="pardal.lock",
        )


def _declared_dependency_ids(manifest: ProjectManifest) -> set[str]:
    result: set[str] = set()
    for dependency in manifest.dependencies:
        if dependency.identifier:
            result.add(dependency.identifier)
        elif dependency.type == "file" and dependency.path is not None:
            package_manifest = manifest.path.parent / dependency.path / "pardal.yaml"
            if package_manifest.exists():
                package = load_project_manifest(package_manifest)
                if package.project.identifier:
                    result.add(package.project.identifier)
    return result


def _reachable_locked_package_ids(
    packages: dict[str, Any],
    roots: set[str],
    manifest_path: Path,
) -> set[str]:
    reachable: set[str] = set()
    pending = list(sorted(roots))
    while pending:
        package_id = pending.pop()
        if package_id in reachable:
            continue
        locked = packages.get(package_id)
        if locked is None:
            raise ProjectConfigError(
                "project.lock_out_of_sync",
                f"dependency {package_id!r} is missing from pardal.lock; run `pardal sync`",
                path=manifest_path,
                field="pardal.lock",
            )
        reachable.add(package_id)
        pending.extend(
            dependency
            for dependency in locked.dependencies
            if dependency not in reachable
        )
    return reachable


def publish_package(
    manifest_path: Path | str = "pardal.yaml",
    *,
    dry_run: bool,
    output_dir: Path | str | None = None,
    registry_index: Path | str | None = None,
) -> PackagePublishResult:
    report = check_package(manifest_path, publish=True)
    _require_package_lock(report.manifest)
    _check_publish_registry_metadata(report.manifest, registry_index)
    if not dry_run and registry_index is None:
        raise ProjectConfigError(
            "package.publish_registry_required",
            "package publish requires --registry-index or --dry-run",
            path=Path(manifest_path),
        )
    if not dry_run and output_dir is not None:
        raise ProjectConfigError(
            "package.publish_output_dir_invalid",
            "package publish writes registry-local archives; --output-dir is dry-run only",
            path=Path(manifest_path),
            field="output_dir",
        )
    if dry_run:
        planned = _package_build_paths(report.manifest, output_dir=output_dir)
        with tempfile.TemporaryDirectory(prefix="pardal-package-publish-") as temp_dir:
            build_package(manifest_path, output_dir=Path(temp_dir))
        return PackagePublishResult(
            archive_path=planned.archive_path,
            manifest_path=planned.manifest_path,
            sha256_path=planned.sha256_path,
            dry_run=True,
            registry_index=Path(registry_index) if registry_index is not None else None,
        )
    build_output_dir = Path(registry_index).parent / "packages"
    build = build_package(manifest_path, output_dir=build_output_dir)
    _publish_to_static_registry(report.manifest, build, Path(registry_index))
    return PackagePublishResult(
        archive_path=build.archive_path,
        manifest_path=build.manifest_path,
        sha256_path=build.sha256_path,
        dry_run=dry_run,
        registry_index=Path(registry_index) if registry_index is not None else None,
    )


def _publish_to_static_registry(
    manifest: ProjectManifest,
    build: PackageBuildResult,
    registry_index: Path,
) -> None:
    assert manifest.project.identifier is not None
    assert manifest.project.version is not None
    raw = load_yaml_file(
        registry_index,
        code="package.publish_registry_yaml_invalid",
        message="registry index must be valid YAML",
    )
    if not isinstance(raw, dict):
        raise ProjectConfigError(
            "package.publish_registry_invalid",
            "registry index must be a mapping",
            path=registry_index,
        )
    packages = raw.setdefault("packages", {})
    package = packages.setdefault(manifest.project.identifier, {})
    versions = package.setdefault("versions", {})
    archive_path = _registry_local_archive_path(build.archive_path, registry_index)
    archive_url = archive_path.relative_to(registry_index.parent).as_posix()
    versions[manifest.project.version] = {
        "url": archive_url,
        "sha256": f"sha256:{_sha256_file(archive_path)}",
        "yanked": False,
        "requires_pardal": manifest.requires_pardal,
    }
    registry_index.write_text(
        yaml.safe_dump(raw, sort_keys=True),
        encoding="utf-8",
    )


def _registry_local_archive_path(archive_path: Path, registry_index: Path) -> Path:
    try:
        archive_path.relative_to(registry_index.parent)
        return archive_path
    except ValueError:
        destination = registry_index.parent / "packages" / archive_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive_path, destination)
        return destination


def _check_publishable_dependencies(manifest: ProjectManifest) -> None:
    for dependency in manifest.dependencies:
        if dependency.type == "file":
            raise ProjectConfigError(
                "package.file_dependency_not_publishable",
                "file dependencies are not publishable",
                path=manifest.path,
                field="dependencies",
            )
        if dependency.type == "git" and not dependency.ref:
            raise ProjectConfigError(
                "package.git_dependency_ref_required",
                "git dependencies require ref for package publish",
                path=manifest.path,
                field="dependencies",
            )


def _check_publish_registry_metadata(
    manifest: ProjectManifest,
    registry_index: Path | str | None,
) -> None:
    if registry_index is None:
        return
    assert manifest.project.identifier is not None
    assert manifest.project.version is not None
    index_path = Path(registry_index)
    raw = load_yaml_file(
        index_path,
        code="package.publish_registry_yaml_invalid",
        message="registry index must be valid YAML",
    )
    if not isinstance(raw, dict):
        raise ProjectConfigError(
            "package.publish_registry_invalid",
            "registry index must be a mapping",
            path=index_path,
        )
    if raw.get("schema") != REGISTRY_SCHEMA:
        raise ProjectConfigError(
            "package.publish_registry_schema_invalid",
            "expected schema pardal.registry/v1",
            path=index_path,
            field="schema",
        )
    packages = raw.get("packages")
    if not isinstance(packages, dict):
        raise ProjectConfigError(
            "package.publish_registry_packages_invalid",
            "registry packages must be a mapping",
            path=index_path,
            field="packages",
        )
    for package_id in packages:
        if not isinstance(package_id, str) or not PACKAGE_ID_RE.fullmatch(package_id):
            raise ProjectConfigError(
                "package.publish_registry_package_id_invalid",
                "registry package keys must be package IDs in owner/name form",
                path=index_path,
                field=f"packages.{package_id}",
            )
    for package_id, package in packages.items():
        if not isinstance(package, dict):
            raise ProjectConfigError(
                "package.publish_registry_package_invalid",
                "registry package entry must be a mapping",
                path=index_path,
                field=f"packages.{package_id}",
            )
        versions = package.get("versions")
        if not isinstance(versions, dict):
            raise ProjectConfigError(
                "package.publish_registry_versions_invalid",
                "registry package versions must be a mapping",
                path=index_path,
                field=f"packages.{package_id}.versions",
            )
        _check_publish_registry_version_keys(
            versions,
            package_id=package_id,
            index_path=index_path,
        )
        for version, release in versions.items():
            _check_publish_registry_release_metadata(
                release,
                package_id=package_id,
                version=version,
                index_path=index_path,
            )
    package = packages.get(manifest.project.identifier)
    if package is None:
        return
    versions = package["versions"]
    release = versions.get(manifest.project.version)
    if release is None:
        return
    raise ProjectConfigError(
        "package.publish_registry_release_exists",
        f"registry already contains {manifest.project.identifier}@{manifest.project.version}",
        path=index_path,
        field=f"packages.{manifest.project.identifier}.versions.{manifest.project.version}",
    )


def _check_publish_registry_release_metadata(
    release: Any,
    *,
    package_id: str,
    version: str,
    index_path: Path,
) -> None:
    if not isinstance(release, dict):
        raise ProjectConfigError(
            "package.publish_registry_release_invalid",
            "registry release entry must be a mapping",
            path=index_path,
            field=f"packages.{package_id}.versions.{version}",
        )
    if not isinstance(release.get("url"), str) or not isinstance(release.get("sha256"), str):
        raise ProjectConfigError(
            "package.publish_registry_release_invalid",
            "registry release requires url and sha256",
            path=index_path,
            field=f"packages.{package_id}.versions.{version}",
        )
    if SHA256_RE.fullmatch(release["sha256"]) is None:
        raise ProjectConfigError(
            "package.publish_registry_sha256_invalid",
            "registry release sha256 must be a sha256-prefixed or raw 64-character hex digest",
            path=index_path,
            field=f"packages.{package_id}.versions.{version}.sha256",
        )
    yanked = release.get("yanked", False)
    if not isinstance(yanked, bool):
        raise ProjectConfigError(
            "package.publish_registry_yanked_invalid",
            "registry release yanked must be a boolean",
            path=index_path,
            field=f"packages.{package_id}.versions.{version}.yanked",
        )
    requires_pardal = release.get("requires_pardal")
    if requires_pardal is not None:
        if not isinstance(requires_pardal, str):
            raise ProjectConfigError(
                "package.publish_registry_requires_pardal_invalid",
                "registry release requires_pardal must be a string",
                path=index_path,
                field=f"packages.{package_id}.versions.{version}.requires_pardal",
            )
        validate_requires_pardal(
            requires_pardal,
            path=index_path,
            field=f"packages.{package_id}.versions.{version}.requires_pardal",
        )


def _check_publish_registry_version_keys(
    versions: dict[Any, Any],
    *,
    package_id: str,
    index_path: Path,
) -> None:
    for version in versions:
        if not isinstance(version, str):
            raise ProjectConfigError(
                "package.publish_registry_version_invalid",
                "registry version keys must be strings",
                path=index_path,
                field=f"packages.{package_id}.versions",
            )
        if SEMVER_RE.fullmatch(version) is None:
            raise ProjectConfigError(
                "package.publish_registry_version_invalid",
                "registry version keys must be SemVer major.minor.patch strings",
                path=index_path,
                field=f"packages.{package_id}.versions.{version}",
            )


def _check_python_check_trust(
    manifest: ProjectManifest,
    exports: tuple[ExportDefinition, ...],
) -> None:
    if not any(export.kind == "checks" for export in exports):
        return
    trust = manifest.raw.get("trust")
    if not isinstance(trust, dict) or trust.get("python_checks") is not True:
        raise ProjectConfigError(
            "package.python_checks_untrusted",
            "packages exporting Python checks must declare trust.python_checks: true",
            path=manifest.path,
            field="trust.python_checks",
        )


def _check_profiles(
    manifest: ProjectManifest,
    exports: tuple[ExportDefinition, ...],
) -> None:
    profiles: dict[str, ProfileDefinition] = {}
    for export in exports:
        if export.kind != "profiles":
            continue
        profiles.update(load_profile_file(export.absolute_path, package_id=export.package_id))
    if profiles:
        _check_local_profile_import_cycles(profiles)


def _check_local_profile_import_cycles(profiles: dict[str, ProfileDefinition]) -> None:
    visiting: list[str] = []
    seen: set[str] = set()

    def visit(profile_id: str) -> None:
        if profile_id in visiting:
            cycle = " -> ".join([*visiting, profile_id])
            raise ProjectConfigError("profile.import_cycle", f"profile import cycle: {cycle}")
        if profile_id in seen:
            return
        profile = profiles.get(profile_id)
        if profile is None:
            return
        visiting.append(profile_id)
        for imported in profile.imports:
            if imported in profiles:
                visit(imported)
        visiting.pop()
        seen.add(profile_id)

    for profile_id in sorted(profiles):
        visit(profile_id)


def _check_part_catalogs(exports: tuple[ExportDefinition, ...]) -> None:
    parts_by_package: dict[str, dict[str, object]] = {}
    for export in exports:
        if export.kind == "parts":
            parts_by_package.setdefault(export.package_id, {}).update(
                load_part_catalog_export(export)
            )
    footprints_by_package: dict[str, set[str]] = {}
    for export in exports:
        if export.kind == "footprints":
            footprints_by_package.setdefault(export.package_id, set()).update(
                load_footprint_export(export)
            )
    for package_id, parts in parts_by_package.items():
        footprints = footprints_by_package.get(package_id, set())
        for part in parts.values():
            footprint_id = getattr(part, "footprint", None)
            if footprint_id is None:
                continue
            if ":" not in footprint_id:
                raise ProjectConfigError(
                    "part_catalog.footprint_unqualified",
                    "part footprint must be a fully qualified package footprint ID",
                    path=getattr(part, "path", None),
                    field=f"parts.{part.id.rsplit(':', 1)[-1]}.footprint",
                )
            if footprint_id.startswith(f"{package_id}:") and footprint_id not in footprints:
                raise ProjectConfigError(
                    "part_catalog.footprint_unknown",
                    "part footprint references an unknown package footprint",
                    path=getattr(part, "path", None),
                    field=f"parts.{part.id.rsplit(':', 1)[-1]}.footprint",
                )


def _check_footprints(exports: tuple[ExportDefinition, ...]) -> None:
    for export in exports:
        if export.kind == "footprints":
            load_footprint_export(export)


def _check_physical_libraries(exports: tuple[ExportDefinition, ...]) -> None:
    for export in exports:
        if export.kind == "physical_libraries":
            load_physical_library_export(export)


def _check_route_policies(exports: tuple[ExportDefinition, ...]) -> None:
    for export in exports:
        if export.kind == "route_policies":
            load_route_policy_export(export)


def _check_check_modules(
    manifest: ProjectManifest,
    exports: tuple[ExportDefinition, ...],
) -> None:
    from pardal.checks import api as check_api
    from pardal.checks.api import DuplicateCheckIdError

    snapshot = dict(check_api._REGISTERED)
    try:
        check_api._REGISTERED.clear()
        for export in exports:
            if export.kind != "checks":
                continue
            _check_public_check_import_boundary(export.absolute_path, export.absolute_path)
            _check_package_python_import_boundaries(export.package_root)
            before = set(check_api._REGISTERED)
            module_name = (
                "_pardal_package_check_"
                + export.package_id.replace("/", "_").replace("-", "_")
                + "_"
                + export.path.stem
            )
            spec = importlib.util.spec_from_file_location(module_name, export.absolute_path)
            if spec is None or spec.loader is None:
                raise ProjectConfigError(
                    "package.check_import_failed",
                    "could not create import spec for check module",
                    path=export.absolute_path,
                )
            module = importlib.util.module_from_spec(spec)
            try:
                _exec_package_check_module(spec, module, export.package_root)
            except DuplicateCheckIdError as exc:
                raise ProjectConfigError(
                    "package.check_duplicate",
                    f"duplicate check id {exc.check_id!r}",
                    path=export.absolute_path,
                ) from exc
            except ValueError as exc:
                raise ProjectConfigError(
                    "package.check_import_failed",
                    f"check module import failed: {exc}",
                    path=export.absolute_path,
                ) from exc
            except Exception as exc:  # pragma: no cover - message carries user module error
                raise ProjectConfigError(
                    "package.check_import_failed",
                    f"check module import failed: {exc}",
                    path=export.absolute_path,
                ) from exc
            registered = set(check_api._REGISTERED) - before
            if not registered:
                raise ProjectConfigError(
                    "package.check_export_empty",
                    "check export module must register at least one public check",
                    path=export.absolute_path,
                )
    finally:
        check_api._REGISTERED.clear()
        check_api._REGISTERED.update(snapshot)


def _check_package_python_import_boundaries(package_root: Path) -> None:
    for path in _iter_package_python_files(package_root):
        _check_public_check_import_boundary(path, path)


def _iter_package_python_files(package_root: Path) -> tuple[Path, ...]:
    ignored_dirs = {".pardal", "dist", "build", "__pycache__"}
    paths = []
    for path in package_root.rglob("*.py"):
        if set(path.relative_to(package_root).parts) & ignored_dirs:
            continue
        paths.append(path)
    return tuple(sorted(paths))


def _check_public_check_import_boundary(path: Path, diagnostic_path: Path) -> None:
    try:
        tree = ast.parse(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
    except SyntaxError as exc:
        raise ProjectConfigError(
            "package.check_import_failed",
            f"check module parse failed: {exc.msg}",
            path=path,
            field=f"line {exc.lineno}",
        ) from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_internal_pardal_import(alias.name):
                    raise ProjectConfigError(
                        "package.check_internal_import",
                        "package check modules must import public APIs from pardal.*, not pardal.*",
                        path=diagnostic_path,
                        field=f"line {node.lineno}",
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None and _is_internal_pardal_import(node.module):
                raise ProjectConfigError(
                    "package.check_internal_import",
                    "package check modules must import public APIs from pardal.*, not pardal.*",
                    path=diagnostic_path,
                    field=f"line {node.lineno}",
                )


def _is_internal_pardal_import(module: str) -> bool:
    if module == "pardal.checks":
        return False
    return module == "pardal" or module.startswith("pardal.")


def _exec_package_check_module(spec: importlib.machinery.ModuleSpec, module: Any, package_root: Path) -> None:
    package_root_text = str(package_root)
    inserted = False
    old_dont_write_bytecode = sys.dont_write_bytecode
    local_module_names = _package_local_module_names(package_root)
    saved_modules = {
        name: sys.modules.pop(name)
        for name in _matching_package_local_module_names(local_module_names)
    }
    sys.dont_write_bytecode = True
    if package_root_text not in sys.path:
        sys.path.insert(0, package_root_text)
        inserted = True
    try:
        assert spec.loader is not None
        spec.loader.exec_module(module)
    finally:
        _remove_loaded_package_modules(package_root)
        sys.modules.update(saved_modules)
        sys.dont_write_bytecode = old_dont_write_bytecode
        if inserted:
            try:
                sys.path.remove(package_root_text)
            except ValueError:  # pragma: no cover - defensive against user import side effects
                pass


def _package_local_module_names(package_root: Path) -> set[str]:
    names = {path.stem for path in package_root.glob("*.py") if path.name != "__init__.py"}
    names.update(
        path.name
        for path in package_root.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    )
    return names


def _matching_package_local_module_names(local_module_names: set[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in sys.modules
            if any(name == local or name.startswith(f"{local}.") for local in local_module_names)
        )
    )


def _remove_loaded_package_modules(package_root: Path) -> None:
    for name, module in list(sys.modules.items()):
        loaded_file = getattr(module, "__file__", None)
        if loaded_file is not None and _is_path_inside(Path(loaded_file), package_root):
            sys.modules.pop(name, None)


def _is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _check_templates(
    manifest: ProjectManifest,
    exports: tuple[ExportDefinition, ...],
) -> None:
    for export in exports:
        if export.kind != "board_templates":
            continue
        raw = load_yaml_file(
            export.absolute_path,
            code="package.template_invalid",
            message="template export file must be valid YAML",
        )
        if not isinstance(raw, dict):
            raise ProjectConfigError(
                "package.template_invalid",
                "template export file must be a mapping",
                path=export.absolute_path,
            )
        templates = raw.get("templates") or {}
        if not isinstance(templates, dict):
            raise ProjectConfigError(
                "package.template_invalid",
                "templates must be a mapping",
                path=export.absolute_path,
                field="templates",
            )
        for template_id, template in templates.items():
            template_name = _template_id(template_id, export.absolute_path)
            if not isinstance(template, dict):
                raise ProjectConfigError(
                    "package.template_invalid",
                    "template definition must be a mapping",
                    path=export.absolute_path,
                    field=f"templates.{template_name}",
                )
            template_path = template.get("path")
            if not isinstance(template_path, str) or not template_path:
                raise ProjectConfigError(
                    "package.template_path_missing",
                    "template requires path",
                    path=export.absolute_path,
                    field=f"templates.{template_name}.path",
                )
            _check_template_default_dependencies(
                template,
                source_path=export.absolute_path,
                field=f"templates.{template_name}.default_dependencies",
            )
            root = (manifest.root / template_path).resolve()
            if not _is_inside(root, manifest.root.resolve()):
                raise ProjectConfigError(
                    "package.template_path_outside",
                    "template path must stay inside package root",
                    path=export.absolute_path,
                    field=f"templates.{template_name}.path",
                )
            if not (root / "pardal.yaml").exists():
                raise ProjectConfigError(
                    "package.template_manifest_missing",
                    "template directory must contain pardal.yaml",
                    path=export.absolute_path,
                    field=f"templates.{template_name}.path",
                )
            _check_template_dependencies(
                root / "pardal.yaml",
                source_path=export.absolute_path,
                field=f"templates.{template_name}.path",
            )
            _check_template_has_no_absolute_project_paths(
                root,
                project_roots=(manifest.root.resolve(), root),
                source_path=export.absolute_path,
                field=f"templates.{template_name}.path",
            )


def _template_id(value: Any, source_path: Path) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "package.template_id_invalid",
            "template id must be a non-empty string",
            path=source_path,
            field="templates",
        )
    return value


def _check_template_default_dependencies(
    template: dict[str, Any],
    *,
    source_path: Path,
    field: str,
) -> None:
    dependencies = template.get("default_dependencies") or []
    if not isinstance(dependencies, list):
        raise ProjectConfigError(
            "package.template_default_dependencies_invalid",
            "template default_dependencies must be a list",
            path=source_path,
            field=field,
        )
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, str) or not PACKAGE_ID_RE.match(dependency):
            raise ProjectConfigError(
                "package.template_default_dependency_invalid",
                "template default dependency must be a package identifier",
                path=source_path,
                field=f"{field}[{index}]",
            )


def _check_template_has_no_absolute_project_paths(
    template_root: Path,
    *,
    project_roots: tuple[Path, ...],
    source_path: Path,
    field: str,
) -> None:
    absolute_markers = {
        marker
        for root in project_roots
        for marker in (root.as_posix(), str(root))
    }
    for path in sorted(template_root.rglob("*")):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(marker and marker in content for marker in absolute_markers):
            rel = path.relative_to(template_root).as_posix()
            raise ProjectConfigError(
                "package.template_absolute_path",
                "template files cannot contain absolute project paths",
                path=source_path,
                field=f"{field}.{rel}",
            )


def _check_template_dependencies(
    manifest_path: Path,
    *,
    source_path: Path,
    field: str,
) -> None:
    template_manifest = load_project_manifest(manifest_path)
    for index, dependency in enumerate(template_manifest.dependencies):
        if dependency.type == "file":
            raise ProjectConfigError(
                "package.template_file_dependency",
                "template dependencies must use registry or git package specs",
                path=source_path,
                field=f"{field}.dependencies[{index}]",
            )


def _check_examples(
    manifest: ProjectManifest,
    exports: tuple[ExportDefinition, ...],
) -> None:
    for export in exports:
        if export.kind != "examples":
            continue
        examples = load_example_export(export)
        for example_id, example in examples.items():
            mode = example.mode
            if mode is None:
                raise ProjectConfigError(
                    "package.example_mode_invalid",
                    "example mode must be documentation_only or build",
                    path=export.absolute_path,
                    field=f"examples.{_unqualified_id(example_id)}.mode",
                )
            root = (manifest.root / example.example_path).resolve()
            if not _is_inside(root, manifest.root.resolve()):
                raise ProjectConfigError(
                    "package.example_path_outside",
                    "example path must stay inside package root",
                    path=export.absolute_path,
                    field=f"examples.{_unqualified_id(example_id)}.path",
                )
            if mode == "build":
                if not (root / "pardal.yaml").exists():
                    raise ProjectConfigError(
                        "package.example_manifest_missing",
                        "build example must contain pardal.yaml",
                        path=export.absolute_path,
                        field=f"examples.{_unqualified_id(example_id)}.path",
                    )
                _smoke_check_build_example(
                    root,
                    source_path=export.absolute_path,
                    field=f"examples.{_unqualified_id(example_id)}.path",
                )


def _unqualified_id(value: str) -> str:
    return value.rsplit(":", 1)[-1]


def _smoke_check_build_example(
    example_root: Path,
    *,
    source_path: Path,
    field: str,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        isolated_root = Path(tmp) / "example"
        shutil.copytree(example_root, isolated_root)
        manifest_path = isolated_root / "pardal.yaml"
        try:
            from pardal.packages.commands import sync_project
            from pardal.project.context import create_project_context

            sync_project(manifest_path)
            create_project_context(manifest_path)
        except ProjectConfigError as exc:
            raise ProjectConfigError(
                "package.example_smoke_failed",
                f"build example smoke test failed: {exc}",
                path=source_path,
                field=field,
            ) from exc


def _iter_package_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if is_ignored_package_generated_path(path, root):
            continue
        files.append(path)
    return files


def _add_deterministic_tar_file(
    archive: tarfile.TarFile,
    path: Path,
    *,
    arcname: str,
) -> None:
    info = archive.gettarinfo(str(path), arcname=arcname)
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
    with path.open("rb") as file:
        archive.addfile(info, file)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
