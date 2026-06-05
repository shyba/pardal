"""Oracle and DRC helpers for routing DSL diagnostics.

This module turns JSON-like DRC and apply evidence into normalized
route-diagnostics payloads. It does not execute KiCad, mutate boards, or claim
authority over committed copper or release artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .diagnostics import normalize_route_diagnostics

_FALSE_AUTHORITY_FIELDS = (
    "generated_board_authority",
    "routing_authority",
    "release_authority",
    "jlc_upload_authority",
    "orderable_claim",
)


def load_route_oracle_report(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def normalize_route_oracle_report(report: Mapping[str, Any]) -> dict[str, Any]:
    route_diagnostics = _route_diagnostics_view(report)
    normalized = normalize_route_diagnostics(route_diagnostics)
    normalized["oracle"] = {
        "output_board_copy_path": str(_output_board_copy_path(report)),
        "command": _command_metadata(report),
        "report_kind": str(report.get("report_kind") or "oracle"),
    }
    for field in _FALSE_AUTHORITY_FIELDS:
        normalized[field] = False
    return normalized


def route_oracle_report_to_route_diagnostics(report: Mapping[str, Any]) -> dict[str, Any]:
    return normalize_route_oracle_report(report)


def summarize_route_oracle_report(report: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_route_oracle_report(report)
    return {
        "oracle": normalized["oracle"],
        "row_count": normalized["row_count"],
        "summary": normalized["summary"],
        "route_plan_id": normalized["route_plan_id"],
        "route_plan_hash": normalized["route_plan_hash"],
    }


def _route_diagnostics_view(report: Mapping[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    for failure in list(report.get("failures") or []):
        failures.append(_normalize_failure(failure, report))
    return {
        "run_id": str(report.get("run_id") or ""),
        "route_plan_id": str(report.get("route_plan_id") or ""),
        "route_plan_hash": str(report.get("route_plan_hash") or ""),
        "failures": failures,
    }


def _normalize_failure(failure: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    drc_evidence = failure.get("drc_evidence") or {}
    apply_report = report.get("apply_report") or {}
    route_group_id = str(failure.get("route_group_id") or drc_evidence.get("route_group_id") or "")
    candidate_id = str(failure.get("candidate_id") or drc_evidence.get("candidate_id") or apply_report.get("candidate_id") or "")
    candidate_index = failure.get("candidate_index")
    if not isinstance(candidate_index, int):
        candidate_index = drc_evidence.get("candidate_index")
    if not isinstance(candidate_index, int):
        candidate_index = apply_report.get("candidate_index")

    provenance = _merge_provenance(
        failure.get("provenance"),
        {
            "output_board_copy_path": _output_board_copy_path(report),
            "command": _command_metadata(report),
            "drc_source": drc_evidence.get("source") or failure.get("source") or "",
        },
    )
    return {
        "run_id": str(failure.get("run_id") or report.get("run_id") or ""),
        "route_plan_id": str(failure.get("route_plan_id") or report.get("route_plan_id") or ""),
        "route_group_id": route_group_id,
        "source_route_group_name": str(
            failure.get("source_route_group_name")
            or drc_evidence.get("source_route_group_name")
            or ""
        ),
        "candidate_id": candidate_id,
        "candidate_index": candidate_index if isinstance(candidate_index, int) else None,
        "assignment": dict(failure.get("assignment") or drc_evidence.get("assignment") or {}),
        "strategy": dict(failure.get("strategy") or {}),
        "backend_profile_id": str(failure.get("backend_profile_id") or ""),
        "failed_stage": str(failure.get("failed_stage") or drc_evidence.get("failed_stage") or "oracle"),
        "code": str(failure.get("code") or drc_evidence.get("code") or "oracle_mismatch"),
        "message": str(failure.get("message") or drc_evidence.get("message") or ""),
        "source_span": dict(failure.get("source_span") or drc_evidence.get("source_span") or {}),
        "source": str(failure.get("source") or drc_evidence.get("source") or _output_board_copy_path(report) or ""),
        "net": str(failure.get("net") or drc_evidence.get("net") or ""),
        "object_id": str(failure.get("object_id") or drc_evidence.get("object_id") or ""),
        "layer": str(failure.get("layer") or drc_evidence.get("layer") or ""),
        "counterparty": str(failure.get("counterparty") or drc_evidence.get("counterparty") or ""),
        "distance_mm": failure.get("distance_mm") if isinstance(failure.get("distance_mm"), (int, float)) else drc_evidence.get("distance_mm"),
        "required_clearance_mm": failure.get("required_clearance_mm")
        if isinstance(failure.get("required_clearance_mm"), (int, float))
        else drc_evidence.get("required_clearance_mm"),
        "length_mm": failure.get("length_mm") if isinstance(failure.get("length_mm"), (int, float)) else drc_evidence.get("length_mm"),
        "allowed_length_mm": failure.get("allowed_length_mm")
        if isinstance(failure.get("allowed_length_mm"), (int, float))
        else drc_evidence.get("allowed_length_mm"),
        "replacement": dict(failure.get("replacement") or drc_evidence.get("replacement") or {}),
        "movement": dict(failure.get("movement") or drc_evidence.get("movement") or {}),
        "provenance": provenance,
    }


def _output_board_copy_path(report: Mapping[str, Any]) -> str:
    for key in ("output_board_copy_path", "board_copy_path", "output_board_path"):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value
    evidence = report.get("drc_evidence") or {}
    value = evidence.get("output_board_copy_path") or evidence.get("board_copy_path")
    return str(value or "")


def _command_metadata(report: Mapping[str, Any]) -> dict[str, Any]:
    command = report.get("command")
    if isinstance(command, Mapping):
        return dict(command)
    return {}


def _merge_provenance(*parts: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        if isinstance(part, Mapping):
            merged.update(part)
    return merged
