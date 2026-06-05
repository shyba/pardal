from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pardal.packages.exports import ExportDefinition
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.yaml import load_yaml_file


@dataclass(frozen=True, slots=True)
class RoutePolicyDefinition:
    id: str
    package_id: str
    path: Path
    backend: str | None = None
    layer_stack: str | None = None
    net_patterns: tuple[str, ...] = ()
    rules: dict[str, Any] = field(default_factory=dict)


def load_route_policy_export(
    export: ExportDefinition,
) -> dict[str, RoutePolicyDefinition]:
    raw = load_yaml_file(
        export.absolute_path,
        code="route_policy.yaml_invalid",
        message="route policy YAML is invalid",
    )
    if not isinstance(raw, dict) or raw.get("schema") != "pardal.route_policy/v1":
        raise ProjectConfigError(
            "route_policy.schema_invalid",
            "expected schema pardal.route_policy/v1",
            path=export.absolute_path,
            field="schema",
        )
    policies = raw.get("policies")
    if not isinstance(policies, dict) or not policies:
        raise ProjectConfigError(
            "route_policy.definitions_missing",
            "policies must be a non-empty mapping",
            path=export.absolute_path,
            field="policies",
        )
    loaded: dict[str, RoutePolicyDefinition] = {}
    for policy_id, value in policies.items():
        policy_name = _local_id(policy_id, export.absolute_path, "policies")
        if not isinstance(value, dict):
            raise ProjectConfigError(
                "route_policy.definition_invalid",
                "policy definition must be a mapping",
                path=export.absolute_path,
                field=f"policies.{policy_name}",
            )
        qualified_id = _qualified_id(
            export.package_id,
            policy_name,
            export.absolute_path,
            "policies",
        )
        loaded[qualified_id] = RoutePolicyDefinition(
            id=qualified_id,
            package_id=export.package_id,
            path=export.absolute_path,
            backend=_optional_str(value.get("backend"), export.absolute_path, f"policies.{policy_name}.backend"),
            layer_stack=_optional_str(value.get("layer_stack"), export.absolute_path, f"policies.{policy_name}.layer_stack"),
            net_patterns=_optional_str_tuple(value.get("net_patterns"), export.absolute_path, f"policies.{policy_name}.net_patterns"),
            rules=_optional_mapping(value.get("rules"), export.absolute_path, f"policies.{policy_name}.rules"),
        )
    return loaded


def _qualified_id(package_id: str, value: str, path: Path, field: str) -> str:
    if ":" in value:
        owner, symbol = value.split(":", 1)
        if owner != package_id or not symbol:
            raise ProjectConfigError(
                "route_policy.id_invalid",
                "route policy id must be local to this package namespace",
                path=path,
                field=field,
            )
        return value
    return f"{package_id}:{value}"


def _local_id(value: Any, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProjectConfigError(
            "route_policy.id_invalid",
            "route policy id must be a non-empty string",
            path=path,
            field=field,
        )
    return value


def _optional_str(value: Any, path: Path, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProjectConfigError("route_policy.string_invalid", "value must be a non-empty string", path=path, field=field)
    return value


def _optional_mapping(value: Any, path: Path, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ProjectConfigError("route_policy.mapping_invalid", "value must be a mapping", path=path, field=field)
    return dict(value)


def _optional_str_tuple(value: Any, path: Path, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ProjectConfigError("route_policy.list_invalid", "value must be a list", path=path, field=field)
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ProjectConfigError(
                "route_policy.string_invalid",
                "value must be a non-empty string",
                path=path,
                field=f"{field}.{index}",
            )
        result.append(item)
    return tuple(result)
