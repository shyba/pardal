from __future__ import annotations

from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path

from pardal.checks.loader import load_package_check_modules
from pardal.checks.visibility import project_registered_checks
from pardal.packages.examples import ExampleDefinition, load_example_export
from pardal.packages.footprints import FootprintDefinition, load_footprint_export
from pardal.packages.index import PackageIndex, build_package_index
from pardal.packages.lock import LockFile, file_hash, package_content_hash
from pardal.packages.parts import PartDefinition, load_part_catalog_export
from pardal.packages.physical_libraries import (
    PhysicalLibraryDefinition,
    load_physical_library_export,
)
from pardal.packages.route_policies import RoutePolicyDefinition, load_route_policy_export
from pardal.packages.templates import (
    BoardTemplateDefinition,
    load_board_template_export,
)
from pardal.profiles.expander import ExpandedProfileSet, expand_profiles
from pardal.profiles.loader import load_profile_file
from pardal.profiles.model import ProfileDefinition
from pardal.production_checks.models import SourceContract
from pardal.production_checks.registry import registry
from pardal.production_checks.source_contract import load_source_contract
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.lockfile import load_project_lock_file
from pardal.project.manifest import BuildTarget, ProjectManifest, load_project_manifest


@dataclass(frozen=True, slots=True)
class ProjectContext:
    root: Path
    manifest: ProjectManifest
    build_target: BuildTarget
    lock: LockFile | None
    package_index: PackageIndex
    parts: dict[str, PartDefinition]
    footprints: dict[str, FootprintDefinition]
    physical_libraries: dict[str, PhysicalLibraryDefinition]
    route_policies: dict[str, RoutePolicyDefinition]
    board_templates: dict[str, BoardTemplateDefinition]
    examples: dict[str, ExampleDefinition]
    source_contract: SourceContract
    profile_set: ExpandedProfileSet
    loaded_check_exports: tuple[str, ...]
    output_root: Path


def create_project_context(
    manifest_path: Path | str,
    *,
    target: str = "default",
    allow_absolute_paths: bool = False,
) -> ProjectContext:
    manifest = load_project_manifest(
        manifest_path,
        allow_absolute_paths=allow_absolute_paths,
    )
    if target not in manifest.builds:
        raise ProjectConfigError(
            "project.target_unknown",
            f"unknown build target {target!r}",
            path=manifest.path,
            field=f"builds.{target}",
        )
    build_target = manifest.builds[target]
    lock = _load_project_lock(manifest)
    package_index = build_package_index(manifest)
    parts = _load_parts(package_index)
    footprints = _load_footprints(package_index)
    physical_libraries = _load_physical_libraries(package_index)
    route_policies = _load_route_policies(package_index)
    board_templates = _load_board_templates(package_index)
    examples = _load_examples(package_index)
    loaded_check_exports = load_package_check_modules(package_index)
    source_contract = _resolve_source_contract_part_aliases(
        _load_build_source_contract(manifest, build_target),
        parts,
    )
    profile_set = _expand_build_profiles(build_target, package_index, source_contract)
    _validate_required_source_contract(profile_set, source_contract)
    known_check_ids = _known_production_check_ids(package_index)
    _validate_profile_check_references(profile_set, source_contract, known_check_ids)
    _validate_source_contract_check_references(source_contract, known_check_ids)
    ctx = ProjectContext(
        root=manifest.root,
        manifest=manifest,
        build_target=build_target,
        lock=lock,
        package_index=package_index,
        parts=parts,
        footprints=footprints,
        physical_libraries=physical_libraries,
        route_policies=route_policies,
        board_templates=board_templates,
        examples=examples,
        source_contract=source_contract,
        profile_set=profile_set,
        loaded_check_exports=loaded_check_exports,
        output_root=manifest.root / manifest.paths.artifacts / target,
    )
    if bool(build_target.options.get("require_lock", False)):
        require_project_lock(ctx)
    return ctx


def _expand_build_profiles(
    build_target: BuildTarget,
    package_index: PackageIndex,
    source_contract: SourceContract | None = None,
) -> ExpandedProfileSet:
    available: dict[str, ProfileDefinition] = {}
    for export in package_index.profiles_by_id.values():
        available.update(
            load_profile_file(export.absolute_path, package_id=export.package_id)
        )
    requested = [*build_target.profiles]
    if source_contract is not None:
        requested.extend(source_contract.profiles.values())
    if not requested:
        return ExpandedProfileSet(
            requested=(),
            expanded=(),
            enabled_checks=frozenset(),
            disabled_checks=frozenset(),
        )
    return expand_profiles(tuple(requested), available)


def _load_build_source_contract(
    manifest: ProjectManifest,
    build_target: BuildTarget,
) -> SourceContract:
    if build_target.source_contract is None:
        return SourceContract()
    path = manifest.root / build_target.source_contract
    try:
        return load_source_contract(path)
    except ValueError as exc:
        raise ProjectConfigError(
            "source_contract.invalid",
            str(exc),
            path=path,
        ) from exc


def _resolve_source_contract_part_aliases(
    source_contract: SourceContract,
    parts: dict[str, PartDefinition],
) -> SourceContract:
    aliases = source_contract.part_aliases
    if not source_contract.components and not aliases:
        return source_contract
    for alias, target in sorted(aliases.items()):
        if ":" in alias or "/" in alias:
            raise ProjectConfigError(
                "source_contract.part_alias_invalid",
                "part aliases must be local unqualified names",
                path=source_contract.path,
                field=f"part_aliases.{alias}",
            )
        if ":" not in target or target not in parts:
            raise ProjectConfigError(
                "source_contract.part_alias_target_unknown",
                f"part alias {alias!r} must point to a known fully qualified part ID",
                path=source_contract.path,
                field=f"part_aliases.{alias}",
            )
    resolved_components: dict[str, dict[str, object]] = {}
    for ref, component in source_contract.components.items():
        copied = dict(component)
        raw_part_id = copied.get("part_id")
        if isinstance(raw_part_id, str) and raw_part_id and ":" not in raw_part_id:
            copied["part_id"] = _resolve_local_part_id(
                raw_part_id,
                aliases,
                parts,
                source_contract.path,
                f"components.{ref}.part_id",
            )
            copied["part_alias"] = raw_part_id
        resolved_components[str(ref)] = copied
    return replace(source_contract, components=resolved_components)


def _resolve_local_part_id(
    part_id: str,
    aliases: dict[str, str],
    parts: dict[str, PartDefinition],
    path: Path | None,
    field: str,
) -> str:
    if part_id in aliases:
        return aliases[part_id]
    matches = sorted(
        qualified_id for qualified_id in parts if qualified_id.rsplit(":", 1)[-1] == part_id
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ProjectConfigError(
            "source_contract.part_alias_required",
            f"unqualified part ID {part_id!r} matches multiple package parts; add part_aliases.{part_id}",
            path=path,
            field=field,
        )
    return part_id


def _load_project_lock(manifest: ProjectManifest) -> LockFile | None:
    lock_path = manifest.root / "pardal.lock"
    if not lock_path.exists():
        return None
    return load_project_lock_file(lock_path)


def _load_parts(package_index: PackageIndex) -> dict[str, PartDefinition]:
    loaded: dict[str, PartDefinition] = {}
    for export in package_index.parts_by_id.values():
        loaded.update(load_part_catalog_export(export))
    return loaded


def _load_footprints(package_index: PackageIndex) -> dict[str, FootprintDefinition]:
    loaded: dict[str, FootprintDefinition] = {}
    for export in package_index.footprints_by_id.values():
        loaded.update(load_footprint_export(export))
    return loaded


def _load_physical_libraries(
    package_index: PackageIndex,
) -> dict[str, PhysicalLibraryDefinition]:
    loaded: dict[str, PhysicalLibraryDefinition] = {}
    for export in package_index.physical_libraries_by_id.values():
        loaded.update(load_physical_library_export(export))
    return loaded


def _load_route_policies(
    package_index: PackageIndex,
) -> dict[str, RoutePolicyDefinition]:
    loaded: dict[str, RoutePolicyDefinition] = {}
    for export in package_index.route_policies_by_id.values():
        loaded.update(load_route_policy_export(export))
    return loaded


def _load_board_templates(
    package_index: PackageIndex,
) -> dict[str, BoardTemplateDefinition]:
    loaded: dict[str, BoardTemplateDefinition] = {}
    for export in package_index.board_templates_by_id.values():
        loaded.update(load_board_template_export(export))
    return loaded


def _load_examples(package_index: PackageIndex) -> dict[str, ExampleDefinition]:
    loaded: dict[str, ExampleDefinition] = {}
    for export in package_index.examples_by_id.values():
        loaded.update(load_example_export(export))
    return loaded


def _validate_required_source_contract(
    profile_set: ExpandedProfileSet,
    source_contract: SourceContract,
) -> None:
    for section in sorted(profile_set.requires_contract):
        if not _contract_section_present(source_contract, section):
            raise ProjectConfigError(
                "source_contract.required_section_missing",
                f"active profile requires source-contract section {section!r}",
                path=source_contract.path,
                field=section,
            )


def _contract_section_present(source_contract: SourceContract, section: str) -> bool:
    field_name = _SOURCE_CONTRACT_SECTION_ALIASES.get(section, section)
    value = getattr(source_contract, field_name, None)
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, tuple):
        return bool(value)
    return value is not None


def _validate_source_contract_check_references(
    source_contract: SourceContract,
    known: set[str],
) -> None:
    if not source_contract.waive_checks:
        return
    for check_id in sorted(source_contract.waive_checks):
        if check_id in known:
            continue
        raise ProjectConfigError(
            "source_contract.waiver_unknown",
            f"waiver refers to unknown finding ID {check_id!r}",
            path=source_contract.path,
            field=f"waive_checks.{check_id}",
        )


def _validate_profile_check_references(
    profile_set: ExpandedProfileSet,
    source_contract: SourceContract,
    known: set[str],
) -> None:
    check_ids = (
        set(profile_set.enabled_checks)
        | set(profile_set.disabled_checks)
        | set(profile_set.severity)
    )
    for check_id in sorted(check_ids):
        if check_id in known:
            continue
        raise ProjectConfigError(
            "profile.check_unknown",
            f"profile refers to unknown production check {check_id!r}",
            path=source_contract.path,
            field=check_id,
        )


def _known_production_check_ids(package_index: PackageIndex | None = None) -> set[str]:
    for module in ("analog", "general", "gd32", "jlcpcb", "lcsc"):
        import_module(f"pardal.production_checks.{module}")
    project_context = None
    if package_index is not None:
        project_context = type("_CheckVisibilityContext", (), {"package_index": package_index})()
    return registry.registered_ids() | set(project_registered_checks(project_context))


_SOURCE_CONTRACT_SECTION_ALIASES = {
    "supply_rails": "rails",
    "adc_frontends": "adc_filters",
}


def require_project_lock(ctx: ProjectContext) -> None:
    if ctx.lock is not None:
        _validate_root_lock_hash(ctx)
        _validate_installed_package_lock_hashes(ctx)
        _validate_file_dependency_lock_freshness(ctx)
        return
    raise ProjectConfigError(
        "project.lock_required",
        "production project commands require pardal.lock; run `pardal sync` first",
        path=ctx.manifest.path,
        field="pardal.lock",
    )


def _validate_root_lock_hash(ctx: ProjectContext) -> None:
    assert ctx.lock is not None
    expected_manifest = ctx.manifest.path.relative_to(ctx.manifest.root).as_posix()
    if ctx.lock.manifest != expected_manifest or ctx.lock.project_hash != file_hash(
        ctx.manifest.path
    ):
        raise ProjectConfigError(
            "project.lock_out_of_sync",
            "pardal.lock does not match pardal.yaml; run `pardal sync`",
            path=ctx.manifest.path,
            field="pardal.lock",
        )


def _validate_installed_package_lock_hashes(ctx: ProjectContext) -> None:
    assert ctx.lock is not None
    for package_id, locked in sorted(ctx.lock.packages.items()):
        install_root = ctx.manifest.root / ctx.manifest.paths.packages / _package_install_path(package_id)
        if not (install_root / "pardal.yaml").exists():
            raise ProjectConfigError(
                "project.lock_stale",
                f"locked package {package_id!r} is not installed; run `pardal sync`",
                path=ctx.manifest.path,
                field="pardal.lock",
            )
        current_hash = package_content_hash(install_root)
        if current_hash != locked.content_hash:
            raise ProjectConfigError(
                "project.lock_stale",
                f"installed package {package_id!r} does not match pardal.lock; run `pardal sync`",
                path=ctx.manifest.path,
                field="pardal.lock",
            )
        if locked.type == "git" and not locked.commit:
            raise ProjectConfigError(
                "project.lock_stale",
                f"locked git package {package_id!r} is missing resolved commit; run `pardal sync`",
                path=ctx.manifest.path,
                field="pardal.lock",
            )


def _package_install_path(package_id: str) -> Path:
    return Path(*package_id.split("/"))


def _validate_file_dependency_lock_freshness(ctx: ProjectContext) -> None:
    assert ctx.lock is not None
    for dependency in ctx.manifest.dependencies:
        if dependency.type != "file" or dependency.path is None:
            continue
        source_root = (ctx.manifest.root / dependency.path).resolve()
        package_manifest_path = source_root / "pardal.yaml"
        if not package_manifest_path.exists():
            raise ProjectConfigError(
                "project.lock_stale",
                "file dependency no longer points at a package root; run `pardal sync`",
                path=ctx.manifest.path,
                field="dependencies",
            )
        package_manifest = load_project_manifest(package_manifest_path)
        package_id = package_manifest.project.identifier
        locked = ctx.lock.packages.get(package_id or "")
        if locked is None:
            raise ProjectConfigError(
                "project.lock_stale",
                f"file dependency {package_id!r} is missing from pardal.lock; run `pardal sync`",
                path=ctx.manifest.path,
                field="pardal.lock",
            )
        current_hash = package_content_hash(source_root)
        if current_hash != locked.content_hash:
            raise ProjectConfigError(
                "project.lock_stale",
                f"file dependency {package_id!r} changed after pardal.lock was written; run `pardal lock --update {package_id}`",
                path=ctx.manifest.path,
                field="pardal.lock",
            )
