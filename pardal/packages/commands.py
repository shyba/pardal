from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pardal.packages.lock import write_lock_file
from pardal.packages.resolver import ResolveResult, resolve_and_install_dependencies
from pardal.packages.spec import parse_dependency_spec
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.lockfile import load_project_lock_file
from pardal.project.manifest import DependencySpec, load_project_manifest
from pardal.project.yaml import load_yaml_file


def sync_project(
    manifest_path: Path | str = "pardal.yaml",
    *,
    registry_index: Path | None = None,
    update_package_id: str | None = None,
) -> ResolveResult:
    manifest = load_project_manifest(manifest_path)
    lock_path = manifest.root / "pardal.lock"
    existing_lock = load_project_lock_file(lock_path) if lock_path.exists() else None
    result = resolve_and_install_dependencies(
        manifest,
        registry_index=registry_index,
        existing_lock=existing_lock,
        update_package_id=update_package_id,
    )
    write_lock_file(result.lock, manifest.root / "pardal.lock")
    return result


def check_project_sync(manifest_path: Path | str = "pardal.yaml") -> None:
    """Validate manifest, lock, and installed packages without mutating files."""
    manifest = load_project_manifest(manifest_path)
    lock_path = manifest.root / "pardal.lock"
    if not lock_path.exists():
        raise ProjectConfigError(
            "project.lock_required",
            "project is not synced; run `pardal sync`",
            path=manifest.path,
            field="pardal.lock",
        )
    lock = load_project_lock_file(lock_path)
    expected_roots = _declared_dependency_ids(manifest.dependencies, manifest.path)
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
    from pardal.project.context import create_project_context, require_project_lock

    require_project_lock(create_project_context(manifest.path))


def update_lock(
    manifest_path: Path | str = "pardal.yaml",
    *,
    package_id: str | None = None,
    registry_index: Path | None = None,
) -> ResolveResult:
    manifest = load_project_manifest(manifest_path)
    if package_id is not None:
        declared = _declared_dependency_ids(manifest.dependencies, manifest.path)
        lock_path = manifest.root / "pardal.lock"
        locked_reachable: set[str] = set()
        if lock_path.exists():
            lock = load_project_lock_file(lock_path)
            locked_reachable = _reachable_locked_package_ids(
                lock.packages,
                declared,
                manifest.path,
            )
        if package_id not in declared and package_id not in locked_reachable:
            raise ProjectConfigError(
                "dependency.update_missing",
                f"dependency {package_id!r} is not in the project dependency graph",
                path=manifest.path,
                field="dependencies",
            )
    return sync_project(
        manifest.path,
        registry_index=registry_index,
        update_package_id=package_id,
    )


def add_dependency(
    spec: str,
    manifest_path: Path | str = "pardal.yaml",
    *,
    registry_index: Path | None = None,
) -> ResolveResult:
    manifest_file = Path(manifest_path)
    dependency = parse_dependency_spec(spec)
    raw = _load_raw_manifest(manifest_file)
    dependencies = list(raw.get("dependencies") or [])
    dependencies.append(_dependency_to_manifest_entry(dependency))
    raw["dependencies"] = dependencies
    _write_raw_manifest(manifest_file, raw)
    return sync_project(manifest_file, registry_index=registry_index)


def remove_dependency(
    identifier: str,
    manifest_path: Path | str = "pardal.yaml",
    *,
    registry_index: Path | None = None,
) -> ResolveResult:
    manifest_file = Path(manifest_path)
    raw = _load_raw_manifest(manifest_file)
    kept: list[Any] = []
    removed = False
    for entry in raw.get("dependencies") or []:
        if _dependency_entry_identifier(entry, manifest_file) == identifier:
            removed = True
            continue
        kept.append(entry)
    if not removed:
        raise ProjectConfigError(
            "dependency.remove_missing",
            f"dependency {identifier!r} is not declared",
            path=manifest_file,
            field="dependencies",
        )
    if kept:
        raw["dependencies"] = kept
    else:
        raw.pop("dependencies", None)
    _write_raw_manifest(manifest_file, raw)
    return sync_project(manifest_file, registry_index=registry_index)


def list_dependencies(
    manifest_path: Path | str = "pardal.yaml",
    *,
    include_status: bool = False,
) -> list[str]:
    manifest = load_project_manifest(manifest_path)
    lock_path = manifest.root / "pardal.lock"
    lock = load_project_lock_file(lock_path) if include_status and lock_path.exists() else None
    result: list[str] = []
    for dependency in manifest.dependencies:
        if dependency.type == "file" and dependency.path is not None:
            line = f"file://{dependency.path.as_posix()}"
        elif dependency.type == "registry":
            suffix = f"@{dependency.release}" if dependency.release else ""
            line = f"{dependency.identifier}{suffix}"
        elif dependency.type == "git":
            ref = f"#{dependency.ref}" if dependency.ref else ""
            path = f":{dependency.path_within_repo}" if dependency.path_within_repo else ""
            line = f"git://{dependency.repo}{ref}{path}"
        else:
            continue
        if lock is not None:
            line = f"{line} {_dependency_status_suffix(manifest, dependency, lock.packages)}"
        result.append(line)
    return result


def _dependency_status_suffix(
    manifest,
    dependency: DependencySpec,
    locked_packages: dict[str, Any],
) -> str:
    identifier = _dependency_status_identifier(manifest, dependency, locked_packages)
    if identifier is None:
        return "[unlocked]"
    locked = locked_packages.get(identifier)
    if locked is None:
        return f"[unlocked {identifier}]"
    installed_path = manifest.root / manifest.paths.packages / _package_install_path(identifier)
    installed = "installed" if (installed_path / "pardal.yaml").exists() else "missing"
    return f"[locked {identifier} {installed}]"


def _dependency_status_identifier(
    manifest,
    dependency: DependencySpec,
    locked_packages: dict[str, Any],
) -> str | None:
    if dependency.identifier:
        return dependency.identifier
    if dependency.type == "file" and dependency.path is not None:
        package_manifest = manifest.root / dependency.path / "pardal.yaml"
        if package_manifest.exists():
            package = load_project_manifest(package_manifest)
            return package.project.identifier
    if dependency.type == "git":
        matches = [
            identifier
            for identifier, locked in locked_packages.items()
            if (
                locked.type == "git"
                and locked.repo == dependency.repo
                and locked.ref == dependency.ref
                and locked.path_within_repo == dependency.path_within_repo
            )
        ]
        if len(matches) == 1:
            return matches[0]
    return None


def _package_install_path(identifier: str) -> Path:
    owner, name = identifier.split("/", 1)
    return Path(owner) / name


def _declared_dependency_ids(
    dependencies: tuple[DependencySpec, ...],
    manifest_path: Path,
) -> set[str]:
    result: set[str] = set()
    for dependency in dependencies:
        if dependency.identifier:
            result.add(dependency.identifier)
            continue
        if dependency.type == "file" and dependency.path is not None:
            package_manifest = manifest_path.parent / dependency.path / "pardal.yaml"
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


def _load_raw_manifest(path: Path) -> dict[str, Any]:
    raw = load_yaml_file(
        path,
        code="manifest.yaml_invalid",
        message="manifest file must be valid YAML",
    )
    if not isinstance(raw, dict):
        raise ProjectConfigError("manifest.invalid", "manifest must be a mapping", path=path)
    return raw


def _write_raw_manifest(path: Path, raw: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _dependency_to_manifest_entry(dependency: DependencySpec) -> dict[str, Any]:
    if dependency.type == "file":
        assert dependency.path is not None
        return {"type": "file", "path": dependency.path.as_posix()}
    if dependency.type == "registry":
        entry: dict[str, Any] = {"type": "registry", "identifier": dependency.identifier}
        if dependency.release:
            entry["release"] = dependency.release
        return entry
    if dependency.type == "git":
        entry = {"type": "git", "identifier": dependency.identifier, "repo": dependency.repo}
        if dependency.ref:
            entry["ref"] = dependency.ref
        if dependency.path_within_repo:
            entry["path"] = dependency.path_within_repo
        return entry
    raise ProjectConfigError("dependency.type_invalid", f"unknown dependency type {dependency.type!r}")


def _dependency_entry_identifier(entry: Any, manifest_path: Path) -> str | None:
    if isinstance(entry, str):
        dependency = parse_dependency_spec(entry)
    elif isinstance(entry, dict):
        dependency = _parse_entry_for_remove(entry, manifest_path)
    else:
        return None
    if dependency.identifier:
        return dependency.identifier
    if dependency.type == "file" and dependency.path is not None:
        package_manifest = manifest_path.parent / dependency.path / "pardal.yaml"
        if package_manifest.exists():
            package = load_project_manifest(package_manifest)
            return package.project.identifier
    return None


def _parse_entry_for_remove(entry: dict[str, Any], manifest_path: Path) -> DependencySpec:
    dep_type = entry.get("type")
    if dep_type == "file":
        value = entry.get("path")
        if isinstance(value, str):
            return DependencySpec(type="file", path=Path(value))
    if dep_type == "registry":
        value = entry.get("identifier")
        if isinstance(value, str):
            return DependencySpec(type="registry", identifier=value)
    if dep_type == "git":
        value = entry.get("identifier")
        if isinstance(value, str):
            return DependencySpec(type="git", identifier=value)
    return DependencySpec(type=str(dep_type or "unknown"))
