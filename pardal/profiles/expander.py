from __future__ import annotations

from dataclasses import dataclass, field

from pardal.profiles.model import ProfileDefinition
from pardal.project.diagnostics import ProjectConfigError


@dataclass(frozen=True, slots=True)
class ExpandedProfileSet:
    requested: tuple[str, ...]
    expanded: tuple[str, ...]
    enabled_checks: frozenset[str]
    disabled_checks: frozenset[str]
    severity: dict[str, str] = field(default_factory=dict)
    requires_contract: dict[str, bool] = field(default_factory=dict)
    import_tree: dict[str, tuple[str, ...]] = field(default_factory=dict)


def expand_profiles(
    requested: list[str] | tuple[str, ...],
    available: dict[str, ProfileDefinition],
) -> ExpandedProfileSet:
    expanded: list[str] = []
    seen: set[str] = set()
    stack: list[str] = []
    import_tree: dict[str, tuple[str, ...]] = {}

    def visit(profile_ref: str) -> None:
        profile_id = _resolve_profile_ref(profile_ref, available)
        if profile_id in stack:
            cycle = " -> ".join([*stack, profile_id])
            raise ProjectConfigError("profile.import_cycle", f"profile import cycle: {cycle}")
        if profile_id in seen:
            return
        profile = available.get(profile_id)
        if profile is None:
            raise ProjectConfigError("profile.unknown", f"unknown profile {profile_id!r}")
        stack.append(profile_id)
        resolved_imports = tuple(sorted(
            _resolve_profile_ref(imported, available)
            for imported in profile.imports
        ))
        import_tree[profile_id] = resolved_imports
        for imported in resolved_imports:
            visit(imported)
        stack.pop()
        seen.add(profile_id)
        expanded.append(profile_id)

    for profile_id in requested:
        visit(profile_id)

    enabled: set[str] = set()
    disabled: set[str] = set()
    severity: dict[str, str] = {}
    requires_contract: dict[str, bool] = {}
    for profile_id in expanded:
        profile = available[profile_id]
        enabled.update(profile.enable_checks)
        disabled.update(profile.disable_checks)
        requires_contract.update({key: value for key, value in profile.requires_contract.items() if value})
        severity.update(profile.severity)
    enabled.difference_update(disabled)
    return ExpandedProfileSet(
        requested=tuple(_resolve_profile_ref(profile_id, available) for profile_id in requested),
        expanded=tuple(expanded),
        enabled_checks=frozenset(enabled),
        disabled_checks=frozenset(disabled),
        severity=severity,
        requires_contract=requires_contract,
        import_tree=import_tree,
    )


def _resolve_profile_ref(
    profile_ref: str,
    available: dict[str, ProfileDefinition],
) -> str:
    if ":" in profile_ref:
        if profile_ref not in available:
            raise ProjectConfigError("profile.unknown", f"unknown profile {profile_ref!r}")
        return profile_ref
    core_ref = f"pardal/core:{profile_ref}"
    if core_ref in available:
        return core_ref
    non_core_matches = sorted(
        profile_id
        for profile_id in available
        if profile_id.endswith(f":{profile_ref}") and not profile_id.startswith("pardal/core:")
    )
    if non_core_matches:
        raise ProjectConfigError(
            "profile.unqualified_non_core",
            (
                f"unqualified profile {profile_ref!r} does not resolve outside "
                f"pardal/core; use {non_core_matches[0]!r}"
            ),
        )
    raise ProjectConfigError("profile.unknown", f"unknown profile {profile_ref!r}")
