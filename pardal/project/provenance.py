from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pardal.checks.visibility import project_registered_checks
from pardal.packages.exports import ExportDefinition
from pardal.packages.lock import file_hash
from pardal.project.context import ProjectContext
from pardal.project.manifest import DependencySpec, load_project_manifest
from pardal.production_checks.models import CheckContext
from pardal.production_checks.profile_resolution import profile_resolution_for_context


SCHEMA = "pardal.package_resolution/v1"


@dataclass(frozen=True, slots=True)
class ProvenanceArtifacts:
    package_resolution: Path
    profile_resolution: Path


def package_resolution_for_context(ctx: ProjectContext) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "project": _project_payload(ctx),
        "lock": _lock_payload(ctx),
        "packages": _packages_payload(ctx),
        "exports": _exports_payload(ctx),
        "parts": {
            part_id: {
                "package": part.package_id,
                "path": _project_relative_path(ctx, part.path),
                "manufacturer": part.manufacturer,
                "mpn": part.mpn,
                "package_name": part.package,
                "pins": part.pins,
                "lcsc": part.lcsc,
                "footprint": part.footprint,
                "attributes": dict(part.attributes),
            }
            for part_id, part in sorted(ctx.parts.items())
        },
        "footprints": {
            footprint_id: {
                "package": footprint.package_id,
                "path": _project_relative_path(ctx, footprint.path),
                "source_path": (
                    _project_relative_path(ctx, footprint.source_path)
                    if footprint.source_path is not None
                    else None
                ),
                "kind": footprint.kind,
                "kicad": footprint.kicad,
                "package_name": footprint.package_name,
                "pitch": footprint.pitch,
                "courtyard_required": footprint.courtyard_required,
                "aliases": tuple(footprint.aliases),
                "metadata": dict(footprint.metadata),
            }
            for footprint_id, footprint in sorted(ctx.footprints.items())
        },
        "physical_libraries": {
            library_id: {
                "package": library.package_id,
                "path": _project_relative_path(ctx, library.path),
                "footprints": tuple(library.footprints),
                "netclasses": tuple(library.netclasses),
                "placements": tuple(library.placements),
                "route_groups": tuple(library.route_groups),
                "mechanical": tuple(library.mechanical),
                "metadata": dict(library.metadata),
            }
            for library_id, library in sorted(ctx.physical_libraries.items())
        },
        "route_policies": {
            policy_id: {
                "package": policy.package_id,
                "path": _project_relative_path(ctx, policy.path),
                "backend": policy.backend,
                "layer_stack": policy.layer_stack,
                "net_patterns": tuple(policy.net_patterns),
                "rules": dict(policy.rules),
            }
            for policy_id, policy in sorted(ctx.route_policies.items())
        },
        "board_templates": {
            template_id: {
                "package": template.package_id,
                "path": _project_relative_path(ctx, template.path),
                "template_path": template.template_path.as_posix(),
                "default_dependencies": tuple(template.default_dependencies),
                "description": template.description,
                "metadata": dict(template.metadata),
            }
            for template_id, template in sorted(ctx.board_templates.items())
        },
        "examples": {
            example_id: {
                "package": example.package_id,
                "path": _project_relative_path(ctx, example.path),
                "example_path": example.example_path.as_posix(),
                "mode": example.mode,
                "description": example.description,
                "metadata": dict(example.metadata),
            }
            for example_id, example in sorted(ctx.examples.items())
        },
        "profiles": {
            "requested": tuple(ctx.profile_set.requested),
            "expanded": tuple(ctx.profile_set.expanded),
            "enabled_checks": tuple(sorted(ctx.profile_set.enabled_checks)),
            "disabled_checks": tuple(sorted(ctx.profile_set.disabled_checks)),
            "severity": dict(ctx.profile_set.severity),
            "requires_contract": dict(ctx.profile_set.requires_contract),
        },
        "dependency_tree": _dependency_tree_payload(ctx),
        "flattened_package_set": _flattened_package_set(ctx),
        "part_aliases": dict(ctx.source_contract.part_aliases),
        "selected_components": _selected_components_payload(ctx),
        "checks": {
            "loaded_exports": tuple(ctx.loaded_check_exports),
            "registered": {
                check_id: {
                    "stage": str(check.stage.value),
                    "default_severity": str(check.default_severity.value),
                    "requires_network": check.requires_network,
                    "package": check.package,
                }
                for check_id, check in sorted(project_registered_checks(ctx).items())
            },
        },
    }


def _selected_components_payload(ctx: ProjectContext) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for ref, component in sorted(ctx.source_contract.components.items()):
        part_id = component.get("part_id")
        footprint_id = component.get("footprint_id")
        part = ctx.parts.get(str(part_id)) if part_id else None
        resolved_footprint_id = str(footprint_id or getattr(part, "footprint", "") or "")
        footprint = ctx.footprints.get(resolved_footprint_id) if resolved_footprint_id else None
        selected[str(ref)] = {
            "part_id": str(part_id) if part_id else None,
            "part_package": part.package_id if part is not None else None,
            "manufacturer": part.manufacturer if part is not None else None,
            "mpn": part.mpn if part is not None else None,
            "lcsc": part.lcsc if part is not None else component.get("lcsc"),
            "footprint_id": resolved_footprint_id or None,
            "footprint_package": footprint.package_id if footprint is not None else None,
            "kicad_footprint": footprint.kicad if footprint is not None else component.get("footprint"),
        }
    return selected


def write_project_provenance_artifacts(
    ctx: ProjectContext,
    *,
    output_dir: Path | None = None,
    allow_network_checks: bool | None = None,
    cli_profiles: list[str] | tuple[str, ...] | None = None,
    cli_enable_checks: list[str] | tuple[str, ...] | None = None,
    cli_disable_checks: list[str] | tuple[str, ...] | None = None,
    cli_disable_check_reasons: dict[str, str] | None = None,
) -> ProvenanceArtifacts:
    root = output_dir or ctx.output_root
    root.mkdir(parents=True, exist_ok=True)
    package_path = root / "package-resolution.json"
    profile_path = root / "profile-resolution.json"
    _write_json(package_path, package_resolution_for_context(ctx))
    _write_json(
        profile_path,
        profile_resolution_for_context(
            CheckContext(
                spec=ctx.manifest,
                source_contract=ctx.source_contract,
                project_context=ctx,
                allow_network_checks=(
                    bool(ctx.build_target.options.get("allow_network_checks", False))
                    if allow_network_checks is None
                    else allow_network_checks
                ),
            ),
            cli_profiles=cli_profiles,
            cli_enable_checks=cli_enable_checks,
            cli_disable_checks=cli_disable_checks,
            cli_disable_check_reasons=cli_disable_check_reasons,
        ),
    )
    return ProvenanceArtifacts(
        package_resolution=package_path,
        profile_resolution=profile_path,
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _project_payload(ctx: ProjectContext) -> dict[str, Any]:
    return {
        "type": ctx.manifest.project.type,
        "name": ctx.manifest.project.name,
        "identifier": ctx.manifest.project.identifier,
        "target": ctx.build_target.name,
        "manifest": ctx.manifest.path.relative_to(ctx.root).as_posix(),
        "output_root": ctx.output_root.relative_to(ctx.root).as_posix(),
    }


def _lock_payload(ctx: ProjectContext) -> dict[str, Any]:
    if ctx.lock is None:
        return {
            "present": False,
            "packages": {},
        }
    return {
        "present": True,
        "schema": ctx.lock.schema,
        "project_hash": ctx.lock.project_hash,
        "lock_hash": file_hash(ctx.root / "pardal.lock"),
        "manifest": ctx.lock.manifest,
        "packages": {
            package_id: {
                key: value
                for key, value in {
                    "type": package.type,
                    "release": package.release,
                    "repo": package.repo,
                    "ref": package.ref,
                    "commit": package.commit,
                    "path": package.path_within_repo,
                    "source": package.source,
                    "manifest_hash": package.manifest_hash,
                    "content_hash": package.content_hash,
                    "export_hashes": _lock_export_hashes_payload(package.export_hashes),
                    "dependencies": tuple(package.dependencies),
                }.items()
                if value not in (None, "", (), {})
            }
            for package_id, package in sorted(ctx.lock.packages.items())
        },
    }


def _lock_export_hashes_payload(
    export_hashes: dict[str, tuple[dict[str, str], ...]],
) -> dict[str, tuple[dict[str, str], ...]]:
    return {
        kind: tuple(
            dict(entry)
            for entry in sorted(
                entries,
                key=lambda item: (
                    item.get("id", ""),
                    item.get("path", ""),
                    item.get("hash", ""),
                ),
            )
        )
        for kind, entries in sorted(export_hashes.items())
    }


def _packages_payload(ctx: ProjectContext) -> dict[str, Any]:
    package_ids = sorted(
        {
            export.package_id
            for export in _all_exports(ctx)
            if export.package_id
        }
    )
    payload: dict[str, dict[str, Any]] = {}
    for package_id in package_ids:
        entry: dict[str, Any] = {
            "installed": True,
            "locked": bool(ctx.lock and package_id in ctx.lock.packages),
        }
        if ctx.lock is not None and package_id in ctx.lock.packages:
            locked = ctx.lock.packages[package_id]
            entry.update(
                {
                    key: value
                    for key, value in {
                        "type": locked.type,
                        "release": locked.release,
                        "repo": locked.repo,
                        "ref": locked.ref,
                        "commit": locked.commit,
                        "path": locked.path_within_repo,
                        "source": locked.source,
                        "manifest_hash": locked.manifest_hash,
                        "content_hash": locked.content_hash,
                        "export_hashes": _lock_export_hashes_payload(locked.export_hashes),
                        "dependencies": tuple(locked.dependencies),
                    }.items()
                    if value not in (None, "", (), {})
                }
            )
        payload[package_id] = entry
    return payload


def _dependency_tree_payload(ctx: ProjectContext) -> tuple[dict[str, Any], ...]:
    if ctx.lock is None:
        return ()
    return tuple(
        _dependency_tree_node(package_id, ctx)
        for package_id in _direct_dependency_ids(ctx)
        if package_id in ctx.lock.packages
    )


def _dependency_tree_node(package_id: str, ctx: ProjectContext) -> dict[str, Any]:
    assert ctx.lock is not None
    locked = ctx.lock.packages[package_id]
    return {
        "id": package_id,
        "dependencies": tuple(
            _dependency_tree_node(dependency_id, ctx)
            for dependency_id in sorted(locked.dependencies)
            if dependency_id in ctx.lock.packages
        ),
    }


def _flattened_package_set(ctx: ProjectContext) -> tuple[str, ...]:
    if ctx.lock is not None:
        return tuple(sorted(ctx.lock.packages))
    return tuple(sorted(_packages_payload(ctx)))


def _direct_dependency_ids(ctx: ProjectContext) -> tuple[str, ...]:
    package_ids: list[str] = []
    for dependency in ctx.manifest.dependencies:
        package_id = _dependency_package_id(ctx, dependency)
        if package_id is not None:
            package_ids.append(package_id)
    return tuple(dict.fromkeys(package_ids))


def _dependency_package_id(
    ctx: ProjectContext,
    dependency: DependencySpec,
) -> str | None:
    if dependency.identifier:
        return dependency.identifier
    if dependency.type == "file" and dependency.path is not None:
        package_manifest_path = ctx.manifest.path.parent / dependency.path / "pardal.yaml"
        if package_manifest_path.exists():
            package_manifest = load_project_manifest(package_manifest_path)
            return package_manifest.project.identifier
    return None


def _exports_payload(ctx: ProjectContext) -> dict[str, tuple[dict[str, str], ...]]:
    return {
        kind: tuple(_export_payload(export) for export in sorted(exports.values(), key=lambda item: item.id))
        for kind, exports in {
            "profiles": ctx.package_index.profiles_by_id,
            "checks": ctx.package_index.checks_by_id,
            "parts": ctx.package_index.parts_by_id,
            "footprints": ctx.package_index.footprints_by_id,
            "physical_libraries": ctx.package_index.physical_libraries_by_id,
            "route_policies": ctx.package_index.route_policies_by_id,
            "board_templates": ctx.package_index.board_templates_by_id,
            "examples": ctx.package_index.examples_by_id,
        }.items()
    }


def _export_payload(export: ExportDefinition) -> dict[str, str]:
    return {
        "id": export.id,
        "package": export.package_id,
        "path": export.path.as_posix(),
        "hash": export.hash,
    }


def _project_relative_path(ctx: ProjectContext, path) -> str:
    if path.is_relative_to(ctx.root):
        return path.relative_to(ctx.root).as_posix()
    return path.as_posix()


def _all_exports(ctx: ProjectContext) -> tuple[ExportDefinition, ...]:
    exports: list[ExportDefinition] = []
    for bucket in (
        ctx.package_index.profiles_by_id,
        ctx.package_index.checks_by_id,
        ctx.package_index.parts_by_id,
        ctx.package_index.footprints_by_id,
        ctx.package_index.physical_libraries_by_id,
        ctx.package_index.route_policies_by_id,
        ctx.package_index.board_templates_by_id,
        ctx.package_index.examples_by_id,
    ):
        exports.extend(bucket.values())
    return tuple(exports)
