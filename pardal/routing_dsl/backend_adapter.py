"""Pure backend adapter for staged routing DSL outputs.

This layer consumes only a resolved route plan plus a backend manifest. It does
not read KiCad boards, does not mutate authoritative board state, and does not
claim downstream authority. The adapter either returns normalized staged
candidate output or normalized diagnostics for failed cases.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .candidate_schema import RouteCandidateSchemaError, route_candidates_to_json_payload, validate_route_candidates
from .capability_gate import CapabilityFailure, evaluate_backend_capabilities, load_backend_manifest
from .diagnostics import normalize_route_diagnostics


ROUTE_CANDIDATE_SCHEMA = "pardal.route_candidates"
ROUTE_CANDIDATE_VERSION = "0.1"
ROUTE_DIAGNOSTICS_SCHEMA = "pardal.route_diagnostics"
ROUTE_DIAGNOSTICS_VERSION = "0.1"

_FORBIDDEN_AUTHORITY_FIELDS = (
    "generated_board_authority",
    "routing_authority",
    "release_authority",
    "jlc_upload_authority",
    "orderable_claim",
)


class BackendAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class BackendAdapterResult:
    kind: str
    payload: dict[str, Any]


class RouteBackend(Protocol):
    def stage_candidates(self, route_plan: Mapping[str, Any], backend_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return a raw route-candidates-compatible payload."""


@dataclass(frozen=True)
class InMemoryRouteBackend:
    """Tiny test backend that returns a fixed staged payload."""

    staged_payload: Mapping[str, Any]

    def stage_candidates(self, route_plan: Mapping[str, Any], backend_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        del route_plan, backend_manifest
        return dict(self.staged_payload)


def adapt_backend_route_output(
    route_plan: Mapping[str, Any],
    backend_manifest: Mapping[str, Any] | str,
    backend: RouteBackend | None = None,
) -> BackendAdapterResult:
    """Run capability gating and backend staging for one resolved route plan."""

    manifest = load_backend_manifest(backend_manifest)
    capability_view = _capability_gate_view(route_plan, manifest)
    capabilities = evaluate_backend_capabilities(capability_view, manifest)
    if not capabilities["supported"]:
        return BackendAdapterResult(kind="route-diagnostics", payload=_diagnostics_from_failures(capabilities["failures"], route_plan, manifest))

    backend_impl = backend or InMemoryRouteBackend(
        staged_payload=_default_staged_payload(route_plan, manifest)
    )
    raw_payload = backend_impl.stage_candidates(route_plan, manifest)
    try:
        validated = validate_route_candidates(raw_payload)
    except RouteCandidateSchemaError as exc:
        return BackendAdapterResult(
            kind="route-diagnostics",
            payload=_diagnostics_from_backend_error(route_plan, manifest, "malformed_backend_output", str(exc)),
        )

    _reject_authority_claims(validated)
    _validate_linkage(route_plan, manifest, validated)
    return BackendAdapterResult(
        kind="route-candidates",
        payload=route_candidates_to_json_payload(validated),
    )


def _default_staged_payload(route_plan: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    route_groups = list(route_plan.get("route_groups") or [])
    candidates: list[dict[str, Any]] = []
    for index, group in enumerate(sorted(route_groups, key=lambda item: str(item.get("route_group_id") or ""))):
        group_id = str(group.get("route_group_id") or group.get("id") or "")
        assignment = {"route_group_id": group_id, "profile": str((manifest.get("backend") or {}).get("id") or "")}
        candidates.append(
            {
                "candidate_id": f"cand_{group_id}_0000",
                "candidate_index": index,
                "route_group_id": group_id,
                "assignment_hash": str(group.get("assignment_hash") or ""),
                "assignment": assignment,
                "patch": _staged_patch_for_group(group, manifest),
                "diagnostics": [],
                "backend_debug": {"backend_profile": str((manifest.get("backend") or {}).get("id") or "")},
            }
        )
    return {
        "schema": ROUTE_CANDIDATE_SCHEMA,
        "version": ROUTE_CANDIDATE_VERSION,
        "route_plan_id": str(route_plan.get("route_plan_id") or ""),
        "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
        "frozen_board_snapshot_id": str(route_plan.get("frozen_board_snapshot_id") or ""),
        "backend": dict(manifest.get("backend") or {}),
        "candidates": candidates,
    }


def _staged_patch_for_group(group: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    allowed_layers = list((group.get("scope") or {}).get("allowed_layers") or [])
    layer_name = str(allowed_layers[0].get("name") if allowed_layers and isinstance(allowed_layers[0], Mapping) else "F.Cu")
    net_name = _first_net_name(group)
    return {
        "remove_objects": [],
        "move_components": [],
        "add_tracks": [
            {
                "net": net_name,
                "layer": layer_name,
                "width": 0.18,
                "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}],
            }
        ],
        "add_vias": [],
        "add_arcs": [],
        "add_zones": [],
        "set_net_ties": [],
    }


def _first_net_name(group: Mapping[str, Any]) -> str:
    select = group.get("select") or {}
    nets = list(select.get("nets") or [])
    if nets and isinstance(nets[0], Mapping):
        return str(nets[0].get("name") or "")
    return ""


def _diagnostics_from_failures(
    failures: list[CapabilityFailure],
    route_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    route_groups = list(route_plan.get("route_groups") or [])
    canonical_failures = []
    normalized_failures = [_coerce_failure(failure) for failure in failures]
    for failure in sorted(normalized_failures, key=lambda item: (item.route_group_id, item.code, item.source_field, item.message)):
        route_group_id = failure.route_group_id or "backend"
        route_group = _match_group(route_groups, failure.route_group_id)
        canonical_failures.append(
            {
                "run_id": _run_id(route_plan, manifest),
                "route_plan_id": str(route_plan.get("route_plan_id") or ""),
                "route_group_id": route_group_id,
                "source_route_group_name": str(route_group.get("source_route_group_name") or route_group.get("name") or ""),
                "candidate_id": "",
                "candidate_index": None,
                "assignment": {},
                "strategy": {
                    "kind": str((route_plan.get("defaults") or {}).get("search", {}).get("candidate_order") or ""),
                    "profile_id": str((manifest.get("backend") or {}).get("id") or ""),
                },
                "backend_profile_id": str((manifest.get("backend") or {}).get("id") or ""),
                "failed_stage": "capability",
                "code": failure.code,
                "message": failure.message,
                "source_span": {},
                "provenance": {
                    "source_field": failure.source_field,
                    "expected": failure.expected,
                    "actual": failure.actual,
                },
                "generated_board_authority": False,
                "routing_authority": False,
                "release_authority": False,
                "jlc_upload_authority": False,
                "orderable_claim": False,
            }
        )
    return normalize_route_diagnostics(
        {
            "run_id": _run_id(route_plan, manifest),
            "route_plan_id": str(route_plan.get("route_plan_id") or ""),
            "route_plan_hash": str(route_plan.get("route_plan_hash") or ""),
            "failures": canonical_failures,
        }
    )


def _diagnostics_from_backend_error(
    route_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    code: str,
    message: str,
) -> dict[str, Any]:
    payload = _diagnostics_from_failures(
        [
            CapabilityFailure(
                code=code,
                message=message,
                route_group_id="",
                source_field="backend.output",
            )
        ],
        route_plan,
        manifest,
    )
    return payload


def _validate_linkage(
    route_plan: Mapping[str, Any],
    manifest: Mapping[str, Any],
    candidate_payload: Mapping[str, Any],
) -> None:
    expected_backend = manifest.get("backend") or {}
    backend = candidate_payload.get("backend") or {}
    if expected_backend.get("id") and backend.get("id") != expected_backend.get("id"):
        raise BackendAdapterError("backend identity mismatch")
    if expected_backend.get("version") and backend.get("version") != expected_backend.get("version"):
        raise BackendAdapterError("backend version mismatch")
    if candidate_payload.get("route_plan_id") != route_plan.get("route_plan_id"):
        raise BackendAdapterError("route_plan_id mismatch")
    if candidate_payload.get("route_plan_hash") != route_plan.get("route_plan_hash"):
        raise BackendAdapterError("route_plan_hash mismatch")
    if candidate_payload.get("frozen_board_snapshot_id") != route_plan.get("frozen_board_snapshot_id"):
        raise BackendAdapterError("frozen_board_snapshot_id mismatch")
    expected_groups = [str(group.get("route_group_id") or "") for group in route_plan.get("route_groups") or []]
    actual_groups = [str(candidate.get("route_group_id") or "") for candidate in candidate_payload.get("candidates") or []]
    if any(group_id not in expected_groups for group_id in actual_groups):
        raise BackendAdapterError("candidate route_group_id outside route plan")


def _reject_authority_claims(candidate_payload: Mapping[str, Any]) -> None:
    for candidate in candidate_payload.get("candidates") or []:
        if not isinstance(candidate, Mapping):
            raise BackendAdapterError("candidate payload must be a mapping")
        for field in _FORBIDDEN_AUTHORITY_FIELDS:
            if candidate.get(field) is True:
                raise BackendAdapterError(f"{field} authority claims are not allowed")
            if field in candidate:
                raise BackendAdapterError(f"{field} authority claims are not allowed")
        patch = candidate.get("patch") or {}
        if isinstance(patch, Mapping) and "committed_copper" in patch:
            raise BackendAdapterError("committed_copper authority claims are not allowed")


def _run_id(route_plan: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    backend = manifest.get("backend") or {}
    return f"{route_plan.get('route_plan_id', '')}:{backend.get('id', '')}:{backend.get('version', '')}"


def _capability_gate_view(route_plan: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, Any]:
    del manifest
    groups = []
    for group in list(route_plan.get("route_groups") or []):
        if not isinstance(group, Mapping):
            continue
        scope = group.get("scope") or {}
        allowed_layers = []
        if isinstance(scope, Mapping):
            for layer in list(scope.get("allowed_layers") or []):
                if isinstance(layer, Mapping):
                    allowed_layers.append(str(layer.get("name") or ""))
                else:
                    allowed_layers.append(str(layer))
        groups.append(
            {
                "id": str(group.get("route_group_id") or group.get("id") or ""),
                "scope": {
                    "allowed_layers": allowed_layers,
                    "zones": bool((scope or {}).get("zones")),
                    "keepouts": bool((scope or {}).get("keepouts")),
                    "differential_pairs": bool((scope or {}).get("differential_pairs")),
                },
                "constraints": dict(group.get("constraints") or {}),
                "via": dict(group.get("via") or {}),
                "features": list(group.get("features") or []),
            }
        )
    return {
        "route_plan_id": route_plan.get("route_plan_id", ""),
        "route_plan_hash": route_plan.get("route_plan_hash", ""),
        "backend": dict(route_plan.get("backend") or {}),
        "route_groups": groups,
    }


def _match_group(route_groups: list[Mapping[str, Any]], route_group_id: str) -> Mapping[str, Any]:
    for group in route_groups:
        if str(group.get("route_group_id") or group.get("id") or "") == route_group_id:
            return group
    return {}


def _coerce_failure(failure: CapabilityFailure | Mapping[str, Any]) -> CapabilityFailure:
    if isinstance(failure, CapabilityFailure):
        return failure
    return CapabilityFailure(
        code=str(failure.get("code") or ""),
        message=str(failure.get("message") or ""),
        route_group_id=str(failure.get("route_group_id") or ""),
        source_field=str(failure.get("source_field") or ""),
        expected=failure.get("expected"),
        actual=failure.get("actual"),
    )


def _as_json_compatible(value: Any) -> Any:
    if isinstance(value, tuple):
        if len(value) == 2 and all(isinstance(item, (int, float)) for item in value):
            return {"x": value[0], "y": value[1]}
        return [_as_json_compatible(item) for item in value]
    if isinstance(value, list):
        return [_as_json_compatible(item) for item in value]
    if isinstance(value, dict):
        return {key: _as_json_compatible(item) for key, item in value.items()}
    return value
