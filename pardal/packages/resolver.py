from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from pardal.packages.exports import scan_package_exports
from pardal.packages.lock import LockedPackage, LockFile, file_hash, package_content_hash
from pardal.packages.registry_client import (
    RegistryRelease,
    StaticRegistryClient,
    extract_archive,
)
from pardal.packages.source_safety import check_package_source_members
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.manifest import DependencySpec, ProjectManifest, load_project_manifest
from pardal.project.versions import validate_requires_pardal

LOCK_SCHEMA = "pardal.lock/v1"


@dataclass(frozen=True, slots=True)
class ResolvedPackage:
    identifier: str
    manifest: ProjectManifest
    source_path: Path
    install_path: Path
    dependency: DependencySpec
    locked: LockedPackage


@dataclass(frozen=True, slots=True)
class ResolveResult:
    packages: tuple[ResolvedPackage, ...]
    lock: LockFile


def resolve_and_install_dependencies(
    manifest: ProjectManifest,
    *,
    registry_index: Path | None = None,
    existing_lock: LockFile | None = None,
    update_package_id: str | None = None,
) -> ResolveResult:
    packages: list[ResolvedPackage] = []
    seen: dict[str, LockedPackage] = {}
    introduced_by: dict[str, Path] = {}
    locked_packages = dict(existing_lock.packages) if existing_lock is not None else {}
    if update_package_id is not None:
        locked_packages.pop(update_package_id, None)
    resolving: list[str] = []
    for dependency in manifest.dependencies:
        _resolve_dependency_graph(
            manifest,
            dependency,
            root_manifest=manifest,
            registry_index=registry_index,
            locked_packages=locked_packages,
            packages=packages,
            seen=seen,
            introduced_by=introduced_by,
            resolving=resolving,
        )
    _prune_unreferenced_packages(manifest, set(seen))
    return ResolveResult(
        packages=tuple(packages),
        lock=LockFile(
            schema=LOCK_SCHEMA,
            packages=seen,
            project_hash=file_hash(manifest.path),
            manifest=manifest.path.relative_to(manifest.root).as_posix(),
        ),
    )


def resolve_and_install_file_dependencies(manifest: ProjectManifest) -> ResolveResult:
    return resolve_and_install_dependencies(manifest)


def _resolve_one(
    manifest: ProjectManifest,
    dependency: DependencySpec,
    *,
    root_manifest: ProjectManifest,
    registry_index: Path | None,
    locked_packages: dict[str, LockedPackage],
) -> ResolvedPackage:
    if dependency.type == "file":
        return _resolve_file_dependency(manifest, dependency, root_manifest=root_manifest)
    if dependency.type == "registry":
        return _resolve_registry_dependency(
            manifest,
            dependency,
            root_manifest=root_manifest,
            registry_index=registry_index,
            locked_packages=locked_packages,
        )
    if dependency.type == "git":
        return _resolve_git_dependency(manifest, dependency, root_manifest=root_manifest)
    raise ProjectConfigError(
        "dependency.resolver_unsupported",
        "only file, registry, and git dependencies are supported",
        path=manifest.path,
        field="dependencies",
    )


def _resolve_dependency_graph(
    referring_manifest: ProjectManifest,
    dependency: DependencySpec,
    *,
    root_manifest: ProjectManifest,
    registry_index: Path | None,
    locked_packages: dict[str, LockedPackage],
    packages: list[ResolvedPackage],
    seen: dict[str, LockedPackage],
    introduced_by: dict[str, Path],
    resolving: list[str],
) -> ResolvedPackage:
    if dependency.identifier is not None:
        existing = seen.get(dependency.identifier)
        if existing is not None:
            _ensure_seen_dependency_compatible(
                dependency,
                existing,
                referring_manifest.path,
                introduced_by.get(dependency.identifier),
            )
            return _resolved_seen_package(referring_manifest, dependency, existing)
    resolved = _resolve_one(
        referring_manifest,
        dependency,
        root_manifest=root_manifest,
        registry_index=registry_index,
        locked_packages=locked_packages,
    )
    identifier = resolved.identifier
    if identifier in resolving:
        cycle = " -> ".join([*resolving, identifier])
        raise ProjectConfigError(
            "dependency.cycle",
            f"dependency cycle detected: {cycle}",
            path=referring_manifest.path,
            field="dependencies",
        )
    existing = seen.get(identifier)
    if existing is not None:
        _ensure_compatible_duplicate(
            existing,
            resolved.locked,
            referring_manifest.path,
            introduced_by.get(identifier),
        )
        return resolved

    resolving.append(identifier)
    try:
        transitive_ids: list[str] = []
        for transitive in resolved.manifest.dependencies:
            transitive_resolved = _resolve_dependency_graph(
                resolved.manifest,
                transitive,
                root_manifest=root_manifest,
                registry_index=registry_index,
                locked_packages=locked_packages,
                packages=packages,
                seen=seen,
                introduced_by=introduced_by,
                resolving=resolving,
            )
            transitive_ids.append(transitive_resolved.identifier)
    finally:
        resolving.pop()

    resolved = replace(
        resolved,
        locked=replace(
            resolved.locked,
            dependencies=tuple(transitive_ids),
        ),
    )
    seen[identifier] = resolved.locked
    introduced_by[identifier] = referring_manifest.path
    packages.append(resolved)
    return resolved


def _ensure_compatible_duplicate(
    existing: LockedPackage,
    candidate: LockedPackage,
    referring_path: Path,
    existing_path: Path | None,
) -> None:
    if existing == candidate:
        return
    if _file_registry_override_compatible(existing, candidate):
        return
    detail = _duplicate_conflict_detail(existing, candidate)
    raise ProjectConfigError(
        "dependency.conflict",
        (
            f"conflicting dependency for {candidate.identifier}: {detail}; "
            f"introduced_by={_display_path(existing_path)}, "
            f"requested_by={_display_path(referring_path)}"
        ),
        path=referring_path,
        field="dependencies",
    )


def _duplicate_conflict_detail(
    existing: LockedPackage,
    candidate: LockedPackage,
) -> str:
    if existing.type == "git" and candidate.type == "git":
        if existing.repo != candidate.repo:
            return f"requested repo {candidate.repo!r} does not match locked repo {existing.repo!r}"
        if existing.ref != candidate.ref:
            return f"requested ref {candidate.ref!r} does not match locked ref {existing.ref!r}"
        if existing.path_within_repo != candidate.path_within_repo:
            return (
                f"requested path {candidate.path_within_repo!r} does not match "
                f"locked path {existing.path_within_repo!r}"
            )
    if existing.type == "registry" and candidate.type == "registry":
        if existing.release != candidate.release:
            return (
                f"requested release {candidate.release!r} does not match "
                f"locked release {existing.release!r}"
            )
    return (
        f"existing={_locked_package_source(existing)}, "
        f"requested={_locked_package_source(candidate)}"
    )


def _ensure_seen_dependency_compatible(
    dependency: DependencySpec,
    existing: LockedPackage,
    referring_path: Path,
    existing_path: Path | None,
) -> None:
    if (
        dependency.type != existing.type
        and not _file_satisfies_registry_dependency(existing, dependency)
    ):
        _raise_dependency_conflict(
            existing,
            dependency,
            referring_path,
            existing_path,
            reason=f"source type {dependency.type!r} does not match locked {existing.type!r}",
        )
    if dependency.type == "registry":
        if dependency.release is not None and dependency.release != existing.release:
            _raise_dependency_conflict(
                existing,
                dependency,
                referring_path,
                existing_path,
                reason=(
                    f"requested release {dependency.release!r} does not match "
                    f"locked release {existing.release!r}"
                ),
            )
    elif dependency.type == "git":
        if dependency.repo is not None and dependency.repo != existing.repo:
            _raise_dependency_conflict(
                existing,
                dependency,
                referring_path,
                existing_path,
                reason=(
                    f"requested repo {dependency.repo!r} does not match "
                    f"locked repo {existing.repo!r}"
                ),
            )
        if dependency.ref is not None and dependency.ref != existing.ref:
            _raise_dependency_conflict(
                existing,
                dependency,
                referring_path,
                existing_path,
                reason=(
                    f"requested ref {dependency.ref!r} does not match "
                    f"locked ref {existing.ref!r}"
                ),
            )
        if dependency.path_within_repo is not None and dependency.path_within_repo != existing.path_within_repo:
            _raise_dependency_conflict(
                existing,
                dependency,
                referring_path,
                existing_path,
                reason=(
                    f"requested path {dependency.path_within_repo!r} does not match "
                    f"locked path {existing.path_within_repo!r}"
                ),
            )


def _raise_dependency_conflict(
    existing: LockedPackage,
    dependency: DependencySpec,
    referring_path: Path,
    existing_path: Path | None,
    *,
    reason: str,
) -> None:
    assert dependency.identifier is not None
    raise ProjectConfigError(
        "dependency.conflict",
        (
            f"conflicting dependency for {dependency.identifier}: {reason}; "
            f"existing={_locked_package_source(existing)}, "
            f"requested={_dependency_source(dependency)}, "
            f"introduced_by={_display_path(existing_path)}, "
            f"requested_by={_display_path(referring_path)}"
        ),
        path=referring_path,
        field="dependencies",
    )


def _display_path(path: Path | None) -> str:
    return "<unknown>" if path is None else path.as_posix()


def _locked_package_source(package: LockedPackage) -> str:
    if package.type == "registry":
        return f"registry:{package.identifier}@{package.release}"
    if package.type == "git":
        path = f":{package.path_within_repo}" if package.path_within_repo else ""
        return f"git:{package.repo}#{package.ref}{path}"
    return package.type


def _dependency_source(dependency: DependencySpec) -> str:
    if dependency.type == "registry":
        return f"registry:{dependency.identifier}@{dependency.release}"
    if dependency.type == "git":
        path = f":{dependency.path_within_repo}" if dependency.path_within_repo else ""
        return f"git:{dependency.repo}#{dependency.ref}{path}"
    return dependency.type


def _file_satisfies_registry_dependency(
    existing: LockedPackage,
    dependency: DependencySpec,
) -> bool:
    return (
        existing.type == "file"
        and dependency.type == "registry"
        and dependency.release is not None
        and existing.release == dependency.release
    )


def _file_registry_override_compatible(
    existing: LockedPackage,
    candidate: LockedPackage,
) -> bool:
    if existing.identifier != candidate.identifier:
        return False
    if existing.release != candidate.release:
        return False
    return {existing.type, candidate.type} == {"file", "registry"}


def _resolved_seen_package(
    referring_manifest: ProjectManifest,
    dependency: DependencySpec,
    locked: LockedPackage,
) -> ResolvedPackage:
    install_path = referring_manifest.root / referring_manifest.paths.packages / _identifier_path(locked.identifier)
    if locked.source is not None:
        install_path = Path(locked.source)
    manifest_path = install_path / "pardal.yaml"
    manifest = (
        load_project_manifest(manifest_path)
        if manifest_path.exists()
        else referring_manifest
    )
    return ResolvedPackage(
        identifier=locked.identifier,
        manifest=manifest,
        source_path=install_path,
        install_path=install_path,
        dependency=dependency,
        locked=locked,
    )


def _resolve_file_dependency(
    manifest: ProjectManifest,
    dependency: DependencySpec,
    *,
    root_manifest: ProjectManifest,
) -> ResolvedPackage:
    if dependency.path is None:
        raise ProjectConfigError(
            "dependency.file_path_missing",
            "file dependency requires path",
            path=manifest.path,
            field="dependencies",
        )
    source_path = (manifest.root / dependency.path).resolve()
    package_manifest_path = source_path / "pardal.yaml"
    if not package_manifest_path.exists():
        raise ProjectConfigError(
            "dependency.file_package_invalid",
            "file dependency path must point at a package root containing pardal.yaml",
            path=manifest.path,
            field="dependencies",
        )
    package_manifest = load_project_manifest(package_manifest_path)
    if not package_manifest.is_package or not package_manifest.project.identifier:
        raise ProjectConfigError(
            "dependency.file_package_invalid",
            "file dependency must point at a package project",
            path=package_manifest_path,
            field="project.type",
        )
    identifier = package_manifest.project.identifier
    install_path = root_manifest.root / root_manifest.paths.packages / _identifier_path(identifier)
    check_package_source_members(source_path, code="dependency.package_source_unsafe")
    _copy_package(source_path, install_path)
    installed_manifest = load_project_manifest(install_path / "pardal.yaml")
    locked = _locked_file_package(identifier, installed_manifest, install_path)
    return ResolvedPackage(
        identifier=identifier,
        manifest=package_manifest,
        source_path=source_path,
        install_path=install_path,
        dependency=dependency,
        locked=locked,
    )


def _resolve_registry_dependency(
    manifest: ProjectManifest,
    dependency: DependencySpec,
    *,
    root_manifest: ProjectManifest,
    registry_index: Path | None,
    locked_packages: dict[str, LockedPackage],
) -> ResolvedPackage:
    if dependency.identifier is None:
        raise ProjectConfigError(
            "dependency.registry_identifier_missing",
            "registry dependency requires identifier",
            path=manifest.path,
            field="dependencies",
        )
    if registry_index is None:
        raise ProjectConfigError(
            "registry.index_missing",
            "registry dependencies require --registry-index",
            path=manifest.path,
            field="dependencies",
        )
    client = StaticRegistryClient(registry_index)
    locked_release = _locked_registry_release(dependency, locked_packages)
    requested_release = dependency.release or locked_release
    release = client.get_release(
        dependency.identifier,
        requested_release,
        allow_yanked=locked_release is not None and requested_release == locked_release,
    )
    if release.requires_pardal is not None:
        validate_requires_pardal(
            release.requires_pardal,
            path=registry_index,
            field=f"packages.{release.identifier}.versions.{release.version}.requires_pardal",
        )
    archive = client.fetch_release_archive(release, root_manifest.root / root_manifest.paths.cache / "registry")
    install_path = root_manifest.root / root_manifest.paths.packages / _identifier_path(release.identifier)
    extract_archive(archive, install_path)
    installed_manifest = load_project_manifest(install_path / "pardal.yaml")
    if installed_manifest.project.identifier != release.identifier:
        raise ProjectConfigError(
            "registry.identifier_mismatch",
            "registry archive manifest identifier does not match release",
            path=installed_manifest.path,
            field="project.identifier",
        )
    if installed_manifest.project.version != release.version:
        raise ProjectConfigError(
            "registry.version_mismatch",
            "registry archive manifest version does not match release",
            path=installed_manifest.path,
            field="project.version",
        )
    locked = _locked_registry_package(release, installed_manifest, install_path, archive)
    return ResolvedPackage(
        identifier=release.identifier,
        manifest=installed_manifest,
        source_path=archive,
        install_path=install_path,
        dependency=dependency,
        locked=locked,
    )


def _locked_registry_release(
    dependency: DependencySpec,
    locked_packages: dict[str, LockedPackage],
) -> str | None:
    if dependency.identifier is None:
        return None
    locked = locked_packages.get(dependency.identifier)
    if locked is None or locked.type != "registry":
        return None
    if dependency.release is not None and locked.release != dependency.release:
        return None
    return locked.release


def _resolve_git_dependency(
    manifest: ProjectManifest,
    dependency: DependencySpec,
    *,
    root_manifest: ProjectManifest,
) -> ResolvedPackage:
    if dependency.repo is None:
        raise ProjectConfigError(
            "dependency.git_repo_missing",
            "git dependency requires repo",
            path=manifest.path,
            field="dependencies",
        )
    clone_path = root_manifest.root / root_manifest.paths.cache / "git" / _git_cache_name(dependency.repo)
    _prepare_git_checkout(dependency.repo, dependency.ref, clone_path, manifest.path)
    commit = _git_output(clone_path, "rev-parse", "HEAD").strip()
    package_root = clone_path / dependency.path_within_repo if dependency.path_within_repo else clone_path
    package_manifest_path = package_root / "pardal.yaml"
    if not package_manifest_path.exists():
        raise ProjectConfigError(
            "dependency.git_package_invalid",
            "git dependency package path must contain pardal.yaml",
            path=manifest.path,
            field="dependencies",
        )
    package_manifest = load_project_manifest(package_manifest_path)
    if not package_manifest.is_package or not package_manifest.project.identifier:
        raise ProjectConfigError(
            "dependency.git_package_invalid",
            "git dependency must point at a package project",
            path=package_manifest_path,
            field="project.type",
        )
    if dependency.identifier and package_manifest.project.identifier != dependency.identifier:
        raise ProjectConfigError(
            "dependency.git_identifier_mismatch",
            "git dependency manifest identifier does not match dependency identifier",
            path=package_manifest_path,
            field="project.identifier",
        )
    identifier = package_manifest.project.identifier
    install_path = root_manifest.root / root_manifest.paths.packages / _identifier_path(identifier)
    check_package_source_members(package_root, code="dependency.package_source_unsafe")
    _copy_package(package_root, install_path)
    installed_manifest = load_project_manifest(install_path / "pardal.yaml")
    locked = _locked_git_package(dependency, commit, installed_manifest, install_path)
    return ResolvedPackage(
        identifier=identifier,
        manifest=package_manifest,
        source_path=clone_path,
        install_path=install_path,
        dependency=dependency,
        locked=locked,
    )


def _locked_file_package(
    identifier: str,
    manifest: ProjectManifest,
    install_path: Path,
) -> LockedPackage:
    exports = scan_package_exports(manifest)
    export_hashes: dict[str, list[dict[str, str]]] = {}
    for export in exports:
        export_hashes.setdefault(export.kind, []).append(
            {"id": export.id, "path": export.path.as_posix(), "hash": export.hash}
        )
    return LockedPackage(
        identifier=identifier,
        type="file",
        release=manifest.project.version,
        source=str(install_path),
        manifest_hash=file_hash(install_path / "pardal.yaml"),
        content_hash=package_content_hash(install_path),
        export_hashes={
            kind: tuple(sorted(entries, key=lambda entry: (entry["id"], entry["path"])))
            for kind, entries in export_hashes.items()
        },
        dependencies=tuple(
            dep.identifier
            for dep in manifest.dependencies
            if dep.identifier is not None
        ),
    )


def _locked_registry_package(
    release: RegistryRelease,
    manifest: ProjectManifest,
    install_path: Path,
    archive: Path,
) -> LockedPackage:
    exports = scan_package_exports(manifest)
    export_hashes: dict[str, list[dict[str, str]]] = {}
    for export in exports:
        export_hashes.setdefault(export.kind, []).append(
            {"id": export.id, "path": export.path.as_posix(), "hash": export.hash}
        )
    return LockedPackage(
        identifier=release.identifier,
        type="registry",
        release=release.version,
        source=str(archive),
        manifest_hash=file_hash(install_path / "pardal.yaml"),
        content_hash=package_content_hash(install_path),
        export_hashes={
            kind: tuple(sorted(entries, key=lambda entry: (entry["id"], entry["path"])))
            for kind, entries in export_hashes.items()
        },
        dependencies=tuple(
            dep.identifier
            for dep in manifest.dependencies
            if dep.identifier is not None
        ),
    )


def _locked_git_package(
    dependency: DependencySpec,
    commit: str,
    manifest: ProjectManifest,
    install_path: Path,
) -> LockedPackage:
    exports = scan_package_exports(manifest)
    export_hashes: dict[str, list[dict[str, str]]] = {}
    for export in exports:
        export_hashes.setdefault(export.kind, []).append(
            {"id": export.id, "path": export.path.as_posix(), "hash": export.hash}
        )
    return LockedPackage(
        identifier=manifest.project.identifier or "",
        type="git",
        repo=dependency.repo,
        ref=dependency.ref,
        commit=commit,
        path_within_repo=dependency.path_within_repo,
        source=str(install_path),
        manifest_hash=file_hash(install_path / "pardal.yaml"),
        content_hash=package_content_hash(install_path),
        export_hashes={
            kind: tuple(sorted(entries, key=lambda entry: (entry["id"], entry["path"])))
            for kind, entries in export_hashes.items()
        },
        dependencies=tuple(
            dep.identifier
            for dep in manifest.dependencies
            if dep.identifier is not None
        ),
    )


def _copy_package(source_path: Path, install_path: Path) -> None:
    if install_path.exists():
        shutil.rmtree(install_path)
    ignore = shutil.ignore_patterns(
        ".git",
        ".pardal",
        "dist",
        "build",
        "__pycache__",
        "*.pyc",
        "*.pyo",
        "*.egg-info",
    )
    shutil.copytree(source_path, install_path, ignore=ignore)


def _prune_unreferenced_packages(manifest: ProjectManifest, referenced: set[str]) -> None:
    package_root = manifest.root / manifest.paths.packages
    if not package_root.exists():
        return
    for owner_dir in package_root.iterdir():
        if not owner_dir.is_dir():
            continue
        for package_dir in owner_dir.iterdir():
            if not package_dir.is_dir():
                continue
            identifier = f"{owner_dir.name}/{package_dir.name}"
            if identifier not in referenced:
                shutil.rmtree(package_dir)
        if owner_dir.exists() and not any(owner_dir.iterdir()):
            owner_dir.rmdir()


def _identifier_path(identifier: str) -> Path:
    owner, name = identifier.split("/", 1)
    return Path(owner) / name


def _prepare_git_checkout(
    repo: str,
    ref: str | None,
    clone_path: Path,
    manifest_path: Path,
) -> None:
    clone_path.parent.mkdir(parents=True, exist_ok=True)
    if clone_path.exists():
        if not (clone_path / ".git").exists():
            shutil.rmtree(clone_path)
            _git_clone(repo, clone_path, manifest_path)
        else:
            _git_checked(clone_path, manifest_path, "fetch", "--all", "--tags", "--prune")
    else:
        _git_clone(repo, clone_path, manifest_path)
    _git_checked(clone_path, manifest_path, "checkout", "--detach", ref or "HEAD")


def _git_clone(repo: str, clone_path: Path, manifest_path: Path) -> None:
    try:
        subprocess.run(
            ["git", "clone", repo, str(clone_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ProjectConfigError(
            "dependency.git_clone_failed",
            exc.stderr.strip() or str(exc),
            path=manifest_path,
            field="dependencies",
        ) from exc


def _git_checked(repo_path: Path, manifest_path: Path, *args: str) -> None:
    try:
        subprocess.run(
            ["git", *args],
            cwd=repo_path,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ProjectConfigError(
            "dependency.git_command_failed",
            exc.stderr.strip() or str(exc),
            path=manifest_path,
            field="dependencies",
        ) from exc


def _git_output(repo_path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout


def _git_cache_name(repo: str) -> str:
    import hashlib

    digest = hashlib.sha256(repo.encode("utf-8")).hexdigest()[:16]
    stem = repo.rstrip("/").removesuffix(".git").split("/")[-1] or "repo"
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in stem)
    return f"{safe_stem}-{digest}"
