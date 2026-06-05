"""Deterministic backend capability gating for route plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CapabilityFailure:
    code: str
    message: str
    route_group_id: str = ""
    source_field: str = ""
    expected: Any = None
    actual: Any = None

    def as_dict(self) -> dict[str, Any]:
        data = {
            "code": self.code,
            "message": self.message,
            "route_group_id": self.route_group_id,
            "source_field": self.source_field,
        }
        if self.expected is not None:
            data["expected"] = self.expected
        if self.actual is not None:
            data["actual"] = self.actual
        return data


def load_backend_manifest(path_or_manifest: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(path_or_manifest, dict):
        manifest = dict(path_or_manifest)
    else:
        path = Path(path_or_manifest)
        manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("backend manifest must be a JSON object")
    return manifest


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _range_contains(bounds: Any, value: float) -> bool:
    if not isinstance(bounds, dict):
        return False
    minimum = bounds.get("min")
    maximum = bounds.get("max")
    if minimum is not None and value < float(minimum):
        return False
    if maximum is not None and value > float(maximum):
        return False
    return True


def _failure(
    code: str,
    message: str,
    *,
    route_group_id: str = "",
    source_field: str = "",
    expected: Any = None,
    actual: Any = None,
) -> CapabilityFailure:
    return CapabilityFailure(
        code=code,
        message=message,
        route_group_id=route_group_id,
        source_field=source_field,
        expected=expected,
        actual=actual,
    )


def evaluate_backend_capabilities(
    route_plan: dict[str, Any], backend_manifest: dict[str, Any] | str | Path
) -> dict[str, Any]:
    """Check a resolved route plan against backend manifest capabilities."""

    manifest = load_backend_manifest(backend_manifest)
    failures: list[CapabilityFailure] = []

    backend_info = manifest.get("backend") or {}
    plan_backend = route_plan.get("backend") or {}
    if isinstance(backend_info, dict):
        expected_backend_id = backend_info.get("id")
        expected_backend_version = backend_info.get("version")
        actual_backend_id = plan_backend.get("id")
        actual_backend_version = plan_backend.get("version")
        if expected_backend_id and actual_backend_id and expected_backend_id != actual_backend_id:
            failures.append(
                _failure(
                    "backend_identity_mismatch",
                    f"route plan targets backend {actual_backend_id!r} but manifest declares {expected_backend_id!r}",
                    source_field="backend.id",
                    expected=expected_backend_id,
                    actual=actual_backend_id,
                )
            )
        if expected_backend_version and actual_backend_version and expected_backend_version != actual_backend_version:
            failures.append(
                _failure(
                    "backend_version_mismatch",
                    f"route plan targets backend version {actual_backend_version!r} but manifest declares {expected_backend_version!r}",
                    source_field="backend.version",
                    expected=expected_backend_version,
                    actual=actual_backend_version,
                )
            )

    supported_layers = set(_as_list((manifest.get("capabilities") or {}).get("supported_layers")))
    via_caps = (manifest.get("capabilities") or {}).get("vias") or {}
    supported_via_types = set(_as_list(via_caps.get("types")))
    max_vias = via_caps.get("max_count")
    supports_differential = bool((manifest.get("capabilities") or {}).get("differential_pairs"))
    supports_zones = bool((manifest.get("capabilities") or {}).get("zones"))
    supports_keepouts = bool((manifest.get("capabilities") or {}).get("keepouts"))
    width_range = (manifest.get("capabilities") or {}).get("width_mm") or {}
    clearance_range = (manifest.get("capabilities") or {}).get("clearance_mm") or {}
    unsupported_features = set(_as_list((manifest.get("capabilities") or {}).get("unsupported_features")))

    for route_group in _as_list(route_plan.get("route_groups")):
        if not isinstance(route_group, dict):
            continue
        route_group_id = str(route_group.get("id") or "")
        scope = route_group.get("scope") or {}
        if isinstance(scope, dict):
            for layer in _as_list(scope.get("allowed_layers")):
                if supported_layers and layer not in supported_layers:
                    failures.append(
                        _failure(
                            "unsupported_layer",
                            f"backend does not support layer {layer!r}",
                            route_group_id=route_group_id,
                            source_field="scope.allowed_layers",
                            expected=sorted(supported_layers),
                            actual=layer,
                        )
                    )
            if scope.get("differential_pairs") and not supports_differential:
                failures.append(
                    _failure(
                        "unsupported_differential_pair",
                        "backend does not support differential pairs",
                        route_group_id=route_group_id,
                        source_field="scope.differential_pairs",
                        expected=True,
                        actual=False,
                    )
                )
            if scope.get("zones") and not supports_zones:
                failures.append(
                    _failure(
                        "unsupported_zones",
                        "backend does not support zones",
                        route_group_id=route_group_id,
                        source_field="scope.zones",
                        expected=True,
                        actual=False,
                    )
                )
            if scope.get("keepouts") and not supports_keepouts:
                failures.append(
                    _failure(
                        "unsupported_keepouts",
                        "backend does not support keepouts",
                        route_group_id=route_group_id,
                        source_field="scope.keepouts",
                        expected=True,
                        actual=False,
                    )
                )

        constraints = route_group.get("constraints") or {}
        if isinstance(constraints, dict):
            width = constraints.get("trace_width_mm")
            if isinstance(width, (int, float)) and not _range_contains(width_range, float(width)):
                failures.append(
                    _failure(
                        "trace_width_out_of_range",
                        f"trace width {width}mm is outside backend range",
                        route_group_id=route_group_id,
                        source_field="constraints.trace_width_mm",
                        expected=width_range,
                        actual=width,
                    )
                )
            clearance = constraints.get("clearance_mm")
            if isinstance(clearance, (int, float)) and not _range_contains(clearance_range, float(clearance)):
                failures.append(
                    _failure(
                        "clearance_out_of_range",
                        f"clearance {clearance}mm is outside backend range",
                        route_group_id=route_group_id,
                        source_field="constraints.clearance_mm",
                        expected=clearance_range,
                        actual=clearance,
                    )
                )

        via = route_group.get("via") or {}
        if isinstance(via, dict) and via:
            via_type = via.get("type")
            via_count = via.get("count")
            if via_type and supported_via_types and via_type not in supported_via_types:
                failures.append(
                    _failure(
                        "unsupported_via_type",
                        f"backend does not support via type {via_type!r}",
                        route_group_id=route_group_id,
                        source_field="via.type",
                        expected=sorted(supported_via_types),
                        actual=via_type,
                    )
                )
            if isinstance(via_count, int) and isinstance(max_vias, int) and via_count > max_vias:
                failures.append(
                    _failure(
                        "via_count_exceeded",
                        f"route group requests {via_count} vias, backend max is {max_vias}",
                        route_group_id=route_group_id,
                        source_field="via.count",
                        expected=max_vias,
                        actual=via_count,
                    )
                )

        route_group_unsupported_features = {
            token for token in _as_list(route_group.get("unsupported_features")) if isinstance(token, str) and token
        }
        for feature in sorted(route_group_unsupported_features & unsupported_features):
            failures.append(
                _failure(
                    "unsupported_feature",
                    f"backend does not support feature {feature!r}",
                    route_group_id=route_group_id,
                    source_field="features",
                    expected=False,
                    actual=feature,
                )
            )

    return {
        "backend": {
            "id": backend_info.get("id", ""),
            "version": backend_info.get("version", ""),
        },
        "route_plan_id": route_plan.get("route_plan_id", ""),
        "route_plan_hash": route_plan.get("route_plan_hash", ""),
        "supported": not failures,
        "failure_count": len(failures),
        "failures": [failure.as_dict() for failure in failures],
    }
