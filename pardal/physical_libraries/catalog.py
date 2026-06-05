"""Validation helpers for the non-executing physical library catalog."""

from __future__ import annotations

import json
from copy import deepcopy
from importlib import resources
from typing import Any


class CatalogValidationError(ValueError):
    """Raised when a physical library catalog entry is malformed."""


def load_catalog() -> dict[str, Any]:
    """Load and validate the bundled physical library catalog."""

    with resources.files(__package__).joinpath("catalog.json").open(
        encoding="utf-8"
    ) as handle:
        catalog = json.load(handle)
    validate_catalog(catalog)
    return catalog


def get_catalog_entry(entry_id: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a validated catalog entry by id."""

    source = load_catalog() if catalog is None else catalog
    validate_catalog(source)
    entries = source["entries"]
    if entry_id not in entries:
        raise CatalogValidationError(f"missing catalog entry: {entry_id}")
    return entries[entry_id]


def expand_catalog_entry(
    entry_id: str,
    parameters: dict[str, Any],
    *,
    route_details: dict[str, Any] | None = None,
    catalog: dict[str, Any] | None = None,
    expanded_by: str = "physical_libraries.catalog",
) -> dict[str, Any]:
    """Expand a placeholder entry into a route_group intent.

    The expansion is pure: it validates inputs, copies the caller-provided
    route details, and returns a new mapping without mutating the catalog or
    any caller-owned state.
    """

    source = load_catalog() if catalog is None else catalog
    validate_catalog(source)
    entry = get_catalog_entry(entry_id, source)
    if entry.get("kind") != "pattern_placeholder":
        raise CatalogValidationError(f"{entry_id}: only pattern placeholders can expand")

    required_parameters = entry["required_parameters"]
    sanitized_parameters = _sanitize_parameters(entry_id, parameters, required_parameters)
    route = _sanitize_route_details(entry_id, route_details, sanitized_parameters)
    name = _build_route_group_name(entry_id, sanitized_parameters, route)
    result: dict[str, Any] = {
        "kind": "route_group",
        "name": name,
        "schema_version": 1,
        "library": {
            "entry_id": entry_id,
            "pattern_family": entry["pattern_family"],
            "parameters": sanitized_parameters,
            "expanded_by": expanded_by,
            "catalog_schema_version": 1,
        },
    }
    description = route.pop("description", None)
    if description is None:
        description = entry.get("description")
    if isinstance(description, str) and description.strip():
        result["description"] = description.strip()
    result.update(route)
    return result


def validate_catalog(catalog: dict[str, Any]) -> None:
    """Validate the data-only catalog shape.

    This deliberately validates metadata only. It does not expand templates,
    call routing code, or mutate board state.
    """

    if not isinstance(catalog, dict):
        raise CatalogValidationError("catalog must be an object")
    if catalog.get("schema_version") != 1:
        raise CatalogValidationError("catalog.schema_version must be 1")
    entries = catalog.get("entries")
    if not isinstance(entries, dict) or not entries:
        raise CatalogValidationError("catalog.entries must be a non-empty object")
    for entry_id, entry in entries.items():
        _validate_entry(entry_id, entry)


def _validate_entry(entry_id: str, entry: Any) -> None:
    if not isinstance(entry_id, str) or not entry_id:
        raise CatalogValidationError("entry ids must be non-empty strings")
    if not isinstance(entry, dict):
        raise CatalogValidationError(f"{entry_id}: entry must be an object")
    if entry.get("id") != entry_id:
        raise CatalogValidationError(f"{entry_id}: id must match catalog key")

    kind = _required_string(entry_id, entry, "kind")
    _required_string(entry_id, entry, "description")

    if kind == "dfm_profile":
        _validate_dfm_profile(entry_id, entry)
        return
    if kind == "pattern_placeholder":
        _validate_pattern_placeholder(entry_id, entry)
        return
    raise CatalogValidationError(f"{entry_id}: unsupported kind {kind!r}")


def _validate_dfm_profile(entry_id: str, entry: dict[str, Any]) -> None:
    manufacturer = _required_string(entry_id, entry, "manufacturer")
    service = _required_string(entry_id, entry, "service")
    if manufacturer != "JLCPCB":
        raise CatalogValidationError(f"{entry_id}: manufacturer must be JLCPCB")
    if service != "2layer_low_cost":
        raise CatalogValidationError(f"{entry_id}: service must be 2layer_low_cost")
    limits = entry.get("limits")
    if not isinstance(limits, dict):
        raise CatalogValidationError(f"{entry_id}: limits must be an object")
    _required_positive_number(entry_id, limits, "max_width_mm")
    _required_positive_number(entry_id, limits, "max_height_mm")
    _required_positive_number(entry_id, limits, "min_track_width_mm")
    _required_positive_number(entry_id, limits, "min_clearance_mm")
    _required_positive_number(entry_id, limits, "min_via_drill_mm")
    _required_positive_number(entry_id, limits, "min_via_diameter_mm")
    if limits["min_via_diameter_mm"] <= limits["min_via_drill_mm"]:
        raise CatalogValidationError(
            f"{entry_id}: min_via_diameter_mm must exceed min_via_drill_mm"
        )


def _validate_pattern_placeholder(entry_id: str, entry: dict[str, Any]) -> None:
    _required_string(entry_id, entry, "pattern_family")
    target = _required_string(entry_id, entry, "target_expansion_kind")
    if target != "route_group":
        raise CatalogValidationError(
            f"{entry_id}: target_expansion_kind must be route_group"
        )
    execution = entry.get("execution")
    if not isinstance(execution, dict):
        raise CatalogValidationError(f"{entry_id}: execution must be an object")
    if execution.get("enabled") is not False:
        raise CatalogValidationError(f"{entry_id}: execution.enabled must be false")
    _required_string(entry_id, execution, "blocked_until")

    required_parameters = entry.get("required_parameters")
    if not isinstance(required_parameters, list) or not required_parameters:
        raise CatalogValidationError(
            f"{entry_id}: required_parameters must be a non-empty list"
        )
    if not all(isinstance(value, str) and value for value in required_parameters):
        raise CatalogValidationError(
            f"{entry_id}: required_parameters must contain non-empty strings"
        )


def _sanitize_parameters(
    entry_id: str, parameters: Any, required_parameters: list[str]
) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        raise CatalogValidationError(f"{entry_id}: parameters must be a mapping")
    sanitized: dict[str, Any] = {}
    missing = [name for name in required_parameters if name not in parameters]
    if missing:
        raise CatalogValidationError(
            f"{entry_id}: missing required parameters: {', '.join(missing)}"
        )
    for name in required_parameters:
        value = parameters[name]
        _validate_parameter_value(entry_id, name, value)
        sanitized[name] = deepcopy(value)
    return sanitized


def _validate_parameter_value(entry_id: str, name: str, value: Any) -> None:
    if isinstance(value, bool) or value is None:
        raise CatalogValidationError(f"{entry_id}: parameter {name} must be a JSON value")
    if isinstance(value, (str, int, float)):
        if isinstance(value, str) and not value.strip():
            raise CatalogValidationError(f"{entry_id}: parameter {name} must be non-empty")
        return
    if isinstance(value, list):
        for item in value:
            _validate_parameter_value(entry_id, name, item)
        return
    if isinstance(value, dict):
        for item_name, item_value in value.items():
            if not isinstance(item_name, str) or not item_name.strip():
                raise CatalogValidationError(
                    f"{entry_id}: parameter {name} contains an invalid object key"
                )
            _validate_parameter_value(entry_id, name, item_value)
        return
    raise CatalogValidationError(f"{entry_id}: parameter {name} must be JSON-serializable")


def _sanitize_route_details(
    entry_id: str, route_details: dict[str, Any] | None, parameters: dict[str, Any]
) -> dict[str, Any]:
    if route_details is None:
        return {}
    if not isinstance(route_details, dict):
        raise CatalogValidationError(f"{entry_id}: route_details must be a mapping")
    route = deepcopy(route_details)
    if "name" in route:
        route["name"] = _required_nonempty_string(entry_id, route, "name")
    if "kind" in route and route["kind"] != "route_group":
        raise CatalogValidationError(f"{entry_id}: route_details.kind must be route_group when present")
    if "schema_version" in route and route["schema_version"] != 1:
        raise CatalogValidationError(f"{entry_id}: route_details.schema_version must be 1 when present")
    if "group" in route:
        _validate_group_value(entry_id, route["group"])
    if "templates" in route:
        if not isinstance(route["templates"], list) or len(route["templates"]) < 2:
            raise CatalogValidationError(f"{entry_id}: route_details.templates must contain at least two templates")
    else:
        raise CatalogValidationError(f"{entry_id}: route_details.templates is required")
    if "replace_existing" in route and not isinstance(route["replace_existing"], dict):
        raise CatalogValidationError(f"{entry_id}: route_details.replace_existing must be a mapping")
    if "library" in route:
        raise CatalogValidationError(f"{entry_id}: route_details must not provide library provenance")
    route.setdefault("schema_version", 1)
    route.setdefault("kind", "route_group")
    return route


def _validate_group_value(entry_id: str, group: Any) -> None:
    if isinstance(group, str):
        if not group.strip():
            raise CatalogValidationError(f"{entry_id}: group must be non-empty")
        return
    if isinstance(group, list):
        if not group:
            raise CatalogValidationError(f"{entry_id}: group must be non-empty")
        for item in group:
            if not isinstance(item, str) or not item.strip():
                raise CatalogValidationError(f"{entry_id}: group must contain non-empty strings")
        return
    raise CatalogValidationError(f"{entry_id}: group must be a string or list of strings")


def _required_nonempty_string(entry_id: str, data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CatalogValidationError(f"{entry_id}: {key} must be a non-empty string")
    return value.strip()


def _build_route_group_name(
    entry_id: str,
    parameters: dict[str, Any],
    route: dict[str, Any],
) -> str:
    if "name" in route:
        return route["name"]
    parts = [entry_id]
    for key in sorted(parameters):
        value = parameters[key]
        if isinstance(value, str):
            parts.append(f"{key}-{_slugify(value)}")
        elif isinstance(value, (int, float)):
            parts.append(f"{key}-{value}")
    return "_".join(part for part in parts if part)


def _slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip()).strip("_")


def _required_string(entry_id: str, data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogValidationError(f"{entry_id}: {key} must be a non-empty string")
    return value


def _required_positive_number(entry_id: str, data: dict[str, Any], key: str) -> float:
    value = data.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise CatalogValidationError(f"{entry_id}: {key} must be a positive number")
    return float(value)
