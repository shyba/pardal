"""Normalized routing DSL diagnostics.

This module turns raw route-diagnostics payloads into deterministic rows and
summaries. It does not execute routing, mutate boards, or claim downstream
authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


_FALSE_AUTHORITY_FIELDS = (
    "generated_board_authority",
    "routing_authority",
    "release_authority",
    "jlc_upload_authority",
    "orderable_claim",
)


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def load_route_diagnostics(source: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    path = Path(source)
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_route_diagnostics(route_diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    rows = [_normalize_failure(failure, index) for index, failure in enumerate(_sorted_failures(route_diagnostics))]
    rows.sort(key=_row_sort_key)
    payload = {
        "schema": "pardal.route_diagnostics",
        "version": "0.1",
        "run_id": str(route_diagnostics.get("run_id") or ""),
        "route_plan_id": str(route_diagnostics.get("route_plan_id") or ""),
        "route_plan_hash": str(route_diagnostics.get("route_plan_hash") or ""),
        "diagnostics_hash": _sha12(_canonical_json(rows)),
        "row_count": len(rows),
        "rows": rows,
        "summary": _summarize(rows),
    }
    for field in _FALSE_AUTHORITY_FIELDS:
        payload[field] = False
    return payload


def route_diagnostics_to_json_payload(route_diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    return normalize_route_diagnostics(route_diagnostics)


def write_route_diagnostics(path: str | Path, route_diagnostics: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(_canonical_json(normalize_route_diagnostics(route_diagnostics)) + "\n", encoding="utf-8")


def _sorted_failures(route_diagnostics: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    failures = list(route_diagnostics.get("failures") or [])
    return sorted(failures, key=_failure_sort_key)


def _failure_sort_key(failure: Mapping[str, Any]) -> tuple[Any, ...]:
    candidate = failure.get("candidate") or {}
    return (
        str(failure.get("route_group_id") or ""),
        str(failure.get("source_route_group_name") or ""),
        str(failure.get("candidate_id") or ""),
        _sort_index(failure.get("candidate_index")),
        str(failure.get("failed_stage") or ""),
        str(failure.get("code") or ""),
        str(candidate.get("id") or ""),
    )


def _row_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("route_group_id") or ""),
        str(row.get("source_route_group_name") or ""),
        _sort_index(row.get("candidate_index")),
        str(row.get("failed_stage") or ""),
        str(row.get("code") or ""),
        str(row.get("source_span") or ""),
        str(row.get("candidate_id") or ""),
    )


def _normalize_failure(failure: Mapping[str, Any], failure_index: int) -> dict[str, Any]:
    route_group_id = str(failure.get("route_group_id") or "")
    source_route_group_name = str(failure.get("source_route_group_name") or "")
    candidate = failure.get("candidate") or {}
    assignment = failure.get("assignment") or {}
    strategy = failure.get("strategy") or {}
    source_span = failure.get("source_span")
    if isinstance(source_span, Mapping):
        source_span = dict(source_span)
    provenance = failure.get("provenance")
    if isinstance(provenance, Mapping):
        provenance = dict(provenance)
    candidate_id = str(failure.get("candidate_id") or candidate.get("id") or "")
    candidate_index = failure.get("candidate_index")
    row = {
        "run_id": str(failure.get("run_id") or ""),
        "route_plan_id": str(failure.get("route_plan_id") or ""),
        "route_group_id": route_group_id,
        "source_route_group_name": source_route_group_name,
        "candidate_id": candidate_id,
        "candidate_index": candidate_index if isinstance(candidate_index, int) else None,
        "assignment_hash": str(failure.get("assignment_hash") or _hash_assignment(assignment)),
        "strategy.kind": str(strategy.get("kind") or ""),
        "strategy.profile_id": str(strategy.get("profile_id") or ""),
        "backend_profile_id": str(failure.get("backend_profile_id") or ""),
        "failed_stage": str(failure.get("failed_stage") or ""),
        "code": str(failure.get("code") or ""),
        "message": str(failure.get("message") or ""),
        "source": _failure_source(failure),
        "source_span": source_span,
        "net": str(failure.get("net") or ""),
        "object_id": str(failure.get("object_id") or ""),
        "layer": str(failure.get("layer") or ""),
        "counterparty": str(failure.get("counterparty") or ""),
        "distance_mm": _optional_number(failure.get("distance_mm")),
        "required_clearance_mm": _optional_number(failure.get("required_clearance_mm")),
        "length_mm": _optional_number(failure.get("length_mm")),
        "allowed_length_mm": _optional_number(failure.get("allowed_length_mm")),
        "replacement": _copy_mapping(failure.get("replacement")),
        "movement": _copy_mapping(failure.get("movement")),
        "provenance": provenance,
        "failure_index": failure_index,
    }
    _validate_row(row, failure)
    row["row_hash"] = _sha12(_canonical_json({k: v for k, v in row.items() if k != "row_hash"}))
    return row


def _validate_row(row: Mapping[str, Any], failure: Mapping[str, Any]) -> None:
    if row["failed_stage"] == "":
        raise ValueError("failed_stage must be present")
    if (row["source_span"] is None or row["source_span"] == {}) and failure.get("source_owned", False):
        raise ValueError("source_span must be present for source-owned errors")
    if not row["route_group_id"]:
        raise ValueError("route_group_id must be present")
    if failure.get("candidate") and not row["candidate_id"]:
        raise ValueError("candidate_id must be present when candidate exists")
    if row["code"] in {"clearance", "length"} and row["distance_mm"] is None and row["length_mm"] is None:
        raise ValueError("numeric blocker must be present for clearance/length diagnostics")
    if any(failure.get(field) is True for field in _FALSE_AUTHORITY_FIELDS):
        raise ValueError("authority fields must remain false")


def _summarize(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    def _count_by(field: str) -> list[dict[str, Any]]:
        buckets: dict[str, int] = {}
        for row in rows:
            key = str(row.get(field) or "")
            buckets[key] = buckets.get(key, 0) + 1
        return [{"key": key, "count": count} for key, count in sorted(buckets.items())]

    return {
        "by_route_group": _count_by("route_group_id"),
        "by_candidate": _count_by("candidate_id"),
        "by_stage": _count_by("failed_stage"),
        "by_net": _count_by("net"),
        "by_layer": _count_by("layer"),
        "by_code": _count_by("code"),
    }


def _failure_source(failure: Mapping[str, Any]) -> str:
    source = failure.get("source")
    if isinstance(source, str) and source:
        return source
    source_span = failure.get("source_span")
    if isinstance(source_span, Mapping):
        path = str(source_span.get("path") or "")
        if path:
            return path
    provenance = failure.get("provenance")
    if isinstance(provenance, Mapping):
        for key in ("source_path", "source", "command"):
            value = provenance.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _hash_assignment(assignment: Any) -> str:
    if assignment in (None, {}, []):
        return ""
    return _sha12(_canonical_json(assignment))


def _optional_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _copy_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _sort_index(value: Any) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 10**9
