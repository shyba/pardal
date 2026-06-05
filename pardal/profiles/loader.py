from __future__ import annotations

from pathlib import Path
from typing import Any

from pardal.profiles.model import ProfileDefinition
from pardal.project.diagnostics import ProjectConfigError
from pardal.project.yaml import load_yaml_file

SEVERITIES = frozenset({"error", "warning", "info"})


def load_profile_file(path: Path | str, *, package_id: str) -> dict[str, ProfileDefinition]:
    profile_path = Path(path)
    raw = load_yaml_file(
        profile_path,
        code="profile.yaml_invalid",
        message="profile YAML is invalid",
    )
    if not isinstance(raw, dict):
        raise ProjectConfigError("profile.file_invalid", "profile file must be a mapping", path=profile_path)
    if raw.get("schema") != "pardal.profile/v1":
        raise ProjectConfigError("profile.schema_invalid", "expected schema pardal.profile/v1", path=profile_path, field="schema")
    profiles = raw.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ProjectConfigError("profile.definitions_missing", "profiles must be a non-empty mapping", path=profile_path, field="profiles")
    loaded: dict[str, ProfileDefinition] = {}
    for profile_id, value in profiles.items():
        if not isinstance(profile_id, str) or not profile_id:
            raise ProjectConfigError("profile.id_invalid", "profile id must be a non-empty string", path=profile_path, field="profiles")
        if not isinstance(value, dict):
            raise ProjectConfigError("profile.definition_invalid", "profile definition must be a mapping", path=profile_path, field=f"profiles.{profile_id}")
        qualified_id = profile_id if ":" in profile_id else f"{package_id}:{profile_id}"
        loaded[qualified_id] = ProfileDefinition(
            id=qualified_id,
            package_id=package_id,
            imports=tuple(_string_list(value.get("imports") or [], profile_path, f"profiles.{profile_id}.imports")),
            enable_checks=frozenset(_string_list(value.get("enable_checks") or [], profile_path, f"profiles.{profile_id}.enable_checks")),
            disable_checks=frozenset(_string_list(value.get("disable_checks") or [], profile_path, f"profiles.{profile_id}.disable_checks")),
            severity=_string_mapping(value.get("severity") or {}, profile_path, f"profiles.{profile_id}.severity"),
            requires_contract=_bool_mapping(value.get("requires_contract") or {}, profile_path, f"profiles.{profile_id}.requires_contract"),
            path=profile_path,
            raw=value,
        )
    return loaded


def _string_list(value: Any, path: Path, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ProjectConfigError("profile.list_invalid", "value must be a list", path=path, field=field)
    result: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise ProjectConfigError("profile.string_invalid", "list item must be a non-empty string", path=path, field=f"{field}[{idx}]")
        result.append(item)
    return result


def _string_mapping(value: Any, path: Path, field: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ProjectConfigError("profile.mapping_invalid", "value must be a mapping", path=path, field=field)
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or not isinstance(item, str) or not item:
            raise ProjectConfigError("profile.mapping_invalid", "mapping keys and values must be strings", path=path, field=field)
        if item not in SEVERITIES:
            raise ProjectConfigError(
                "profile.severity_invalid",
                "severity must be one of error, warning, info",
                path=path,
                field=f"{field}.{key}",
            )
        result[key] = item
    return result


def _bool_mapping(value: Any, path: Path, field: str) -> dict[str, bool]:
    if not isinstance(value, dict):
        raise ProjectConfigError("profile.mapping_invalid", "value must be a mapping", path=path, field=field)
    result: dict[str, bool] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or not isinstance(item, bool):
            raise ProjectConfigError("profile.mapping_invalid", "requires_contract keys must be strings and values bools", path=path, field=field)
        result[key] = item
    return result
