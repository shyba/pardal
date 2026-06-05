from __future__ import annotations

from typing import Any

from pardal.checks.visibility import project_registered_checks
from pardal.profiles.expander import expand_profiles
from pardal.profiles.loader import load_profile_file
from pardal.profiles.model import ProfileDefinition
from pardal.production_checks.models import CheckContext
from pardal.production_checks.profiles import checks_for_profiles


SCHEMA = "pardal.profile_resolution/v1"


def profile_resolution_for_context(
    ctx: CheckContext,
    *,
    cli_profiles: list[str] | tuple[str, ...] | None = None,
    cli_enable_checks: list[str] | tuple[str, ...] | None = None,
    cli_disable_checks: list[str] | tuple[str, ...] | None = None,
    cli_disable_check_reasons: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return the resolved production-profile inputs used by the check runner."""
    legacy_profiles = _legacy_profiles(ctx, cli_profiles=cli_profiles)
    legacy_enabled = checks_for_profiles(legacy_profiles) if legacy_profiles else set()
    package = _package_profile_resolution(ctx, cli_profiles=cli_profiles)

    package_enabled = set(package["enabled_checks"])
    package_disabled = set(package["disabled_checks"])
    source_enabled = set(ctx.source_contract.enable_checks)
    source_disabled = set(ctx.source_contract.disable_checks)
    cli_enabled = set(cli_enable_checks or ())
    cli_disabled = set(cli_disable_checks or ())

    enabled = set()
    enabled.update(legacy_enabled)
    enabled.update(package_enabled)
    enabled.update(source_enabled)
    enabled.update(cli_enabled)

    disabled = set()
    disabled.update(package_disabled)
    disabled.update(source_disabled)
    disabled.update(cli_disabled)
    enabled.difference_update(disabled)
    network = _network_resolution(
        ctx,
        enabled,
        disabled,
        allow_network_checks=ctx.allow_network_checks,
    )

    return {
        "schema": SCHEMA,
        "legacy_profiles": tuple(legacy_profiles),
        "package_profiles": package,
        "source_contract": {
            "profiles": dict(ctx.source_contract.profiles),
            "enable_checks": tuple(ctx.source_contract.enable_checks),
            "disable_checks": tuple(ctx.source_contract.disable_checks),
        },
        "cli": {
            "profiles": tuple(cli_profiles or ()),
            "enable_checks": tuple(cli_enable_checks or ()),
            "disable_checks": tuple(cli_disable_checks or ()),
            "disable_check_reasons": dict(cli_disable_check_reasons or {}),
        },
        "enabled_checks": tuple(sorted(enabled)),
        "disabled_checks": tuple(sorted(disabled)),
        "severity": dict(package["severity"]),
        "requires_contract": dict(package["requires_contract"]),
        "network": network,
    }


def _legacy_profiles(
    ctx: CheckContext,
    *,
    cli_profiles: list[str] | tuple[str, ...] | None,
) -> list[str]:
    profiles = [profile for profile in ctx.production_profiles if ":" not in profile]
    if cli_profiles:
        profiles.extend(profile for profile in cli_profiles if ":" not in profile)
    profiles.extend(
        profile for profile in ctx.source_contract.profiles.values() if ":" not in profile
    )
    dfm = getattr(ctx.spec, "dfm", None)
    if dfm is not None:
        if getattr(dfm, "profile", None) and ":" not in dfm.profile:
            profiles.append(dfm.profile)
        if getattr(dfm, "lcsc_policy", None) and ":" not in dfm.lcsc_policy:
            profiles.append(dfm.lcsc_policy)
    return profiles


def _package_profile_resolution(
    ctx: CheckContext,
    *,
    cli_profiles: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    project_context = getattr(ctx, "project_context", None)
    profile_set = getattr(project_context, "profile_set", None)
    if profile_set is None:
        return {
            "requested": (),
            "expanded": (),
            "imported_profiles": (),
            "import_tree": {},
            "enabled_checks": (),
            "disabled_checks": (),
            "severity": {},
            "requires_contract": {},
        }
    cli_package_profiles = tuple(profile for profile in (cli_profiles or ()) if ":" in profile)
    if cli_package_profiles:
        profile_set = _expand_project_profiles_with_cli(project_context, cli_package_profiles)
    return {
        "requested": tuple(profile_set.requested),
        "expanded": tuple(profile_set.expanded),
        "imported_profiles": tuple(
            profile_id
            for profile_id in profile_set.expanded
            if profile_id not in set(profile_set.requested)
        ),
        "import_tree": {
            profile_id: tuple(imports)
            for profile_id, imports in profile_set.import_tree.items()
        },
        "enabled_checks": tuple(sorted(profile_set.enabled_checks)),
        "disabled_checks": tuple(sorted(profile_set.disabled_checks)),
        "severity": dict(profile_set.severity),
        "requires_contract": dict(profile_set.requires_contract),
    }


def _expand_project_profiles_with_cli(
    project_context: Any,
    cli_package_profiles: tuple[str, ...],
):
    available: dict[str, ProfileDefinition] = {}
    for export in project_context.package_index.profiles_by_id.values():
        available.update(
            load_profile_file(export.absolute_path, package_id=export.package_id)
        )
    return expand_profiles(
        tuple((*project_context.profile_set.requested, *cli_package_profiles)),
        available,
    )


def _network_resolution(
    ctx: CheckContext,
    enabled: set[str],
    disabled: set[str],
    *,
    allow_network_checks: bool,
) -> dict[str, Any]:
    network_capable = {
        check_id: check
        for check_id, check in project_registered_checks(ctx.project_context).items()
        if check.requires_network
    }
    enabled_network = tuple(sorted(check_id for check_id in enabled if check_id in network_capable))
    disabled_network = tuple(sorted(check_id for check_id in disabled if check_id in network_capable))
    return {
        "allow_network_checks": allow_network_checks,
        "network_capable_checks": tuple(sorted(network_capable)),
        "enabled_network_checks": enabled_network,
        "disabled_network_checks": disabled_network,
        "skipped_network_checks": () if allow_network_checks else enabled_network,
    }
