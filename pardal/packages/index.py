from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from pardal.packages.exports import ExportDefinition, scan_package_exports
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.manifest import ProjectManifest, load_project_manifest


@dataclass(frozen=True, slots=True)
class InstalledPackage:
    identifier: str
    root: Path
    manifest: ProjectManifest


@dataclass(frozen=True, slots=True)
class PackageIndex:
    packages_by_id: dict[str, InstalledPackage] = field(default_factory=dict)
    profiles_by_id: dict[str, ExportDefinition] = field(default_factory=dict)
    checks_by_id: dict[str, ExportDefinition] = field(default_factory=dict)
    parts_by_id: dict[str, ExportDefinition] = field(default_factory=dict)
    footprints_by_id: dict[str, ExportDefinition] = field(default_factory=dict)
    physical_libraries_by_id: dict[str, ExportDefinition] = field(default_factory=dict)
    route_policies_by_id: dict[str, ExportDefinition] = field(default_factory=dict)
    board_templates_by_id: dict[str, ExportDefinition] = field(default_factory=dict)
    examples_by_id: dict[str, ExportDefinition] = field(default_factory=dict)


def build_package_index(manifest: ProjectManifest) -> PackageIndex:
    if not manifest.is_package:
        return build_installed_package_index(manifest)
    return _index_exports(manifest, scan_package_exports(manifest))


def build_installed_package_index(manifest: ProjectManifest) -> PackageIndex:
    package_root = manifest.root / manifest.paths.packages
    exports: list[tuple[ProjectManifest, ExportDefinition]] = []
    packages: list[ProjectManifest] = []
    if not package_root.exists():
        return PackageIndex()
    for package_manifest_path in sorted(package_root.glob("*/*/pardal.yaml")):
        package_manifest = load_project_manifest(package_manifest_path)
        if not package_manifest.is_package:
            continue
        packages.append(package_manifest)
        exports.extend(
            (package_manifest, export)
            for export in scan_package_exports(package_manifest)
        )
    return _index_export_pairs(exports, packages)


def _index_exports(
    manifest: ProjectManifest,
    exports: tuple[ExportDefinition, ...],
) -> PackageIndex:
    packages = (manifest,) if manifest.is_package else ()
    return _index_export_pairs(((manifest, export) for export in exports), packages)


def _index_export_pairs(
    exports: Iterable[tuple[ProjectManifest, ExportDefinition]],
    packages: Iterable[ProjectManifest] = (),
) -> PackageIndex:
    packages_by_id: dict[str, InstalledPackage] = {}
    for manifest in packages:
        identifier = manifest.project.identifier
        if not identifier:
            continue
        if identifier in packages_by_id:
            existing = packages_by_id[identifier]
            raise ProjectConfigError(
                "package.index_duplicate",
                (
                    f"duplicate package id {identifier!r}; first loaded from "
                    f"{existing.root}"
                ),
                path=manifest.path,
                field="project.identifier",
            )
        packages_by_id[identifier] = InstalledPackage(
            identifier=identifier,
            root=manifest.root,
            manifest=manifest,
        )
    buckets: dict[str, dict[str, ExportDefinition]] = {
        "profiles": {},
        "checks": {},
        "parts": {},
        "footprints": {},
        "physical_libraries": {},
        "route_policies": {},
        "board_templates": {},
        "examples": {},
    }
    for manifest, export in exports:
        bucket = buckets.get(export.kind)
        if bucket is None:
            continue
        if export.id in bucket:
            existing = bucket[export.id]
            raise ProjectConfigError(
                "package.index_duplicate",
                (
                    f"duplicate export id {export.id!r}; first defined by "
                    f"{existing.package_id} at {existing.path.as_posix()}"
                ),
                path=manifest.path,
                field=f"exports.{export.kind}",
            )
        bucket[export.id] = export
    return PackageIndex(
        profiles_by_id=buckets["profiles"],
        checks_by_id=buckets["checks"],
        parts_by_id=buckets["parts"],
        footprints_by_id=buckets["footprints"],
        physical_libraries_by_id=buckets["physical_libraries"],
        route_policies_by_id=buckets["route_policies"],
        board_templates_by_id=buckets["board_templates"],
        examples_by_id=buckets["examples"],
        packages_by_id=packages_by_id,
    )
