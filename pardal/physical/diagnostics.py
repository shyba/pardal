"""Route diagnostics dashboard helpers.

This module summarizes existing route/DRC/build artifacts. It does not mutate
boards, routing state, production checks, or release gates.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any


_DISTANCE_MESSAGE_RE = re.compile(
    r"(?P<subject>.+?)\s+"
    r"(?P<subject_kind>segment|via)\s+on\s+"
    r"(?P<layer>\S+)\s+is\s+"
    r"(?P<distance>-?\d+(?:\.\d+)?)mm\s+from\s+"
    r"(?P<counterparty>.+?);\s+requires\s+"
    r"(?P<required>\d+(?:\.\d+)?)mm"
)
_REF_PAD_RE = re.compile(r"^(?P<ref>[A-Za-z]+\d+)\.(?P<pad>[^.\s;]+)$")


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _find_artifact(path_or_root: Path, filename: str) -> Path | None:
    if path_or_root.is_file():
        if path_or_root.name == filename:
            return path_or_root
        sibling = path_or_root.parent / filename
        if sibling.exists():
            return sibling
        return None
    direct = path_or_root / filename
    if direct.exists():
        return direct
    matches = sorted(path_or_root.rglob(filename))
    return matches[0] if matches else None


def _assignment_hash(assignment: Any) -> str:
    if not assignment:
        return ""
    if isinstance(assignment, dict):
        text = json.dumps(assignment, sort_keys=True, separators=(",", ":"))
    else:
        text = str(assignment)
    return _sha12(text)


def _candidate_id(failure: dict[str, Any]) -> str:
    return "|".join(
        [
            str(failure.get("route_name") or ""),
            str(failure.get("route_index") or ""),
            str(failure.get("alternative_name") or ""),
            _assignment_hash(failure.get("assignment")),
        ]
    )


def _parse_counterparty(message: str) -> dict[str, Any]:
    parsed = {
        "subject": "",
        "subject_kind": "",
        "counterparty": "",
        "counterparty_ref": "",
        "counterparty_pad": "",
        "counterparty_kind": "unknown",
        "layer": None,
        "distance_mm": None,
        "required_clearance_mm": None,
    }
    match = _DISTANCE_MESSAGE_RE.search(message or "")
    if not match:
        return parsed

    counterparty = match.group("counterparty").strip()
    parsed.update(
        {
            "subject": match.group("subject").strip(),
            "subject_kind": match.group("subject_kind").strip(),
            "counterparty": counterparty,
            "layer": match.group("layer"),
            "distance_mm": float(match.group("distance")),
            "required_clearance_mm": float(match.group("required")),
        }
    )
    ref_pad = _REF_PAD_RE.match(counterparty)
    if ref_pad:
        parsed["counterparty_ref"] = ref_pad.group("ref")
        parsed["counterparty_pad"] = ref_pad.group("pad")
        parsed["counterparty_kind"] = "pad"
    elif counterparty.endswith(" via"):
        parsed["counterparty_kind"] = "via"
    elif counterparty:
        parsed["counterparty_kind"] = "net_or_object"
    return parsed


def normalize_route_diagnostic_violations(
    route_diagnostics: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flatten route-diagnostics failures into normalized violation rows."""

    rows: list[dict[str, Any]] = []
    for failure_index, failure in enumerate(route_diagnostics.get("failures") or []):
        candidate_id = _candidate_id(failure)
        replacement = failure.get("replacement") or {}
        candidate = failure.get("candidate") or {}
        primary_net = str(failure.get("net") or "")
        for violation_index, violation in enumerate(failure.get("violations") or []):
            message = str(violation.get("message") or "")
            parsed = _parse_counterparty(message)
            distance = violation.get("distance")
            if not isinstance(distance, (int, float)):
                distance = parsed["distance_mm"]
            required = parsed["required_clearance_mm"]
            margin = (
                float(distance) - float(required)
                if isinstance(distance, (int, float)) and isinstance(required, (int, float))
                else None
            )
            counterparty = parsed["counterparty"] or str(violation.get("net") or "")

            rows.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_index": failure_index,
                    "route_name": failure.get("route_name") or "",
                    "route_index": failure.get("route_index"),
                    "alternative_name": failure.get("alternative_name") or "",
                    "template_name": failure.get("template_name") or "",
                    "assignment_hash": _assignment_hash(failure.get("assignment")),
                    "failed_stage": failure.get("failed_stage") or "route_commit",
                    "primary_net": primary_net,
                    "subject": parsed["subject"] or primary_net,
                    "subject_kind": parsed["subject_kind"],
                    "counterparty": counterparty,
                    "counterparty_ref": parsed["counterparty_ref"],
                    "counterparty_pad": parsed["counterparty_pad"],
                    "counterparty_kind": parsed["counterparty_kind"],
                    "layer": violation.get("layer") or parsed["layer"],
                    "code": violation.get("code") or "unknown",
                    "message": message,
                    "source": violation.get("source") or failure.get("source") or "",
                    "distance_mm": distance,
                    "required_clearance_mm": required,
                    "margin_mm": margin,
                    "overlap_mm": -margin if isinstance(margin, (int, float)) and margin < 0 else None,
                    "candidate_segments": len(candidate.get("segments") or []),
                    "candidate_vias": len(candidate.get("vias") or []),
                    "moved_refs": list(failure.get("moved_refs") or []),
                    "replacement_nets": list(replacement.get("nets") or []),
                    "replacement_removed_segments": replacement.get("removed_segments", 0),
                    "replacement_removed_vias": replacement.get("removed_vias", 0),
                    "first_for_candidate": violation_index == 0,
                }
            )
    return rows


def _bucket_counterparty(row: dict[str, Any]) -> str:
    return str(row.get("counterparty") or row.get("counterparty_ref") or row.get("counterparty_pad") or "")


def _bucket_key(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("failed_stage") or ""),
            str(row.get("primary_net") or ""),
            _bucket_counterparty(row),
            str(row.get("layer") or ""),
            str(row.get("code") or ""),
        ]
    )


def summarize_conflict_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate_total = len({row["candidate_id"] for row in rows}) if rows else 0
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _bucket_key(row)
        bucket = buckets.setdefault(
            key,
            {
                "bucket_key": key,
                "failed_stage": row.get("failed_stage") or "",
                "primary_net": row.get("primary_net") or "",
                "counterparty": _bucket_counterparty(row),
                "counterparty_ref": row.get("counterparty_ref") or "",
                "counterparty_pad": row.get("counterparty_pad") or "",
                "counterparty_kind": row.get("counterparty_kind") or "unknown",
                "layer": row.get("layer") or "",
                "code": row.get("code") or "",
                "candidate_ids": set(),
                "messages": [],
                "margins": [],
                "sources": [],
            },
        )
        bucket["candidate_ids"].add(row["candidate_id"])
        bucket["messages"].append(row["message"])
        if row.get("source"):
            bucket["sources"].append(row["source"])
        if isinstance(row.get("margin_mm"), (int, float)):
            bucket["margins"].append(float(row["margin_mm"]))

    ranked: list[dict[str, Any]] = []
    for rank, (_key, bucket) in enumerate(
        sorted(
            buckets.items(),
            key=lambda item: (
                -len(item[1]["candidate_ids"]),
                min(item[1]["margins"]) if item[1]["margins"] else 999999,
                item[0],
            ),
        ),
        start=1,
    ):
        margins = bucket["margins"]
        candidate_count = len(bucket["candidate_ids"])
        coverage = candidate_count / candidate_total if candidate_total else 0.0
        ranked.append(
            {
                "rank": rank,
                "bucket_key": bucket["bucket_key"],
                "failed_stage": bucket["failed_stage"],
                "primary_net": bucket["primary_net"],
                "counterparty": bucket["counterparty"],
                "counterparty_ref": bucket["counterparty_ref"],
                "counterparty_pad": bucket["counterparty_pad"],
                "counterparty_kind": bucket["counterparty_kind"],
                "layer": bucket["layer"],
                "code": bucket["code"],
                "candidate_count": candidate_count,
                "candidate_coverage": coverage,
                "violation_count": len(bucket["messages"]),
                "min_margin_mm": min(margins) if margins else None,
                "median_margin_mm": median(margins) if margins else None,
                "dominance_score": round(coverage * 10.0, 3),
                "representative_source": bucket["sources"][0] if bucket["sources"] else "",
                "example_candidates": sorted(bucket["candidate_ids"])[:3],
            }
        )
    return ranked


def _stop_decision(rows: list[dict[str, Any]], top_buckets: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "action": "continue",
            "confidence": 1.0,
            "reason": "No route diagnostic violations were found.",
            "allowed_next_run_type": "none",
        }
    if top_buckets and top_buckets[0]["candidate_coverage"] >= 0.5:
        return {
            "action": "stop_sweep",
            "confidence": 0.9,
            "reason": (
                "Dominant bucket "
                f"{top_buckets[0]['bucket_key']} covers most failed candidates."
            ),
            "allowed_next_run_type": "route_group_or_replacement",
        }
    return {
        "action": "continue_sweep",
        "confidence": 0.6,
        "reason": "Failures are split across buckets.",
        "allowed_next_run_type": "coordinate_sweep",
    }


_STAGE_RANK = {
    "none": 0,
    "route_commit": 1,
    "drc": 2,
    "production": 3,
}


def _stage_rank(stage: str) -> int:
    return _STAGE_RANK.get(stage or "", 0)


def _summary_int(dashboard: dict[str, Any], key: str) -> int:
    value = (dashboard.get("summary") or {}).get(key)
    return int(value) if isinstance(value, int) else 0


def _summary_number(dashboard: dict[str, Any], key: str) -> float | None:
    value = (dashboard.get("summary") or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _top_bucket_keys(dashboard: dict[str, Any], limit: int = 5) -> list[str]:
    return [
        str(bucket.get("bucket_key") or "")
        for bucket in (dashboard.get("top_buckets") or [])[:limit]
        if bucket.get("bucket_key")
    ]


def _bucket_overlap(previous: dict[str, Any], current: dict[str, Any]) -> float:
    previous_keys = set(_top_bucket_keys(previous))
    current_keys = set(_top_bucket_keys(current))
    if not previous_keys and not current_keys:
        return 1.0
    if not previous_keys or not current_keys:
        return 0.0
    return len(previous_keys & current_keys) / len(previous_keys | current_keys)


def compare_diagnostics_dashboards(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    previous_label: str = "previous",
    current_label: str = "current",
) -> dict[str, Any]:
    """Compare two diagnostics dashboards and classify progress.

    The comparison is intentionally conservative: it reports no-progress only
    when the same failure shape persists without stage, margin, or count
    improvement. It does not affect compile, routing, production, or release
    gates.
    """

    previous_run = previous.get("run") or {}
    current_run = current.get("run") or {}
    previous_stage = str(previous_run.get("verification_stage_reached") or "none")
    current_stage = str(current_run.get("verification_stage_reached") or "none")
    stage_delta = _stage_rank(current_stage) - _stage_rank(previous_stage)
    previous_violations = _summary_int(previous, "violation_count")
    current_violations = _summary_int(current, "violation_count")
    previous_buckets = _summary_int(previous, "unique_bucket_count")
    current_buckets = _summary_int(current, "unique_bucket_count")
    previous_margin = _summary_number(previous, "best_margin_mm")
    current_margin = _summary_number(current, "best_margin_mm")
    margin_delta = (
        current_margin - previous_margin
        if previous_margin is not None and current_margin is not None
        else None
    )
    overlap = _bucket_overlap(previous, current)
    previous_action = str((previous.get("stop_decision") or {}).get("action") or "")
    current_action = str((current.get("stop_decision") or {}).get("action") or "")
    current_passes = current_stage == "production" and current_violations == 0

    evidence: list[str] = []
    if stage_delta > 0:
        evidence.append("verification_stage_advanced")
    if current_violations < previous_violations:
        evidence.append("violation_count_decreased")
    if current_buckets < previous_buckets:
        evidence.append("unique_bucket_count_decreased")
    if margin_delta is not None and margin_delta > 0.02:
        evidence.append("clearance_margin_improved")
    if current_passes:
        evidence.append("current_snapshot_passes")

    stable_failure = (
        previous_violations > 0
        and current_violations > 0
        and stage_delta <= 0
        and current_violations >= previous_violations
        and current_buckets >= previous_buckets
        and overlap >= 0.8
        and (margin_delta is None or margin_delta <= 0.02)
    )

    if current_passes:
        progress_state = "completed"
        no_progress = False
        action = "continue"
        reason = "Current dashboard reaches production with zero route diagnostic violations."
    elif evidence:
        progress_state = "progressing"
        no_progress = False
        action = current_action or "continue_sweep"
        reason = "Current dashboard improved versus the previous snapshot."
    elif stable_failure:
        progress_state = "plateaued"
        no_progress = True
        action = "stop_sweep"
        reason = "Failure buckets, stage, violation count, and margin did not improve."
    else:
        progress_state = "inconclusive"
        no_progress = False
        action = current_action or "continue_sweep"
        reason = "Comparison does not prove progress or a stable plateau."

    return {
        "schema_version": 1,
        "tool": "pardal-physical-diagnostics-progress",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "inputs": {
            "previous_label": previous_label,
            "current_label": current_label,
            "previous_source_path": previous_run.get("source_path") or "",
            "current_source_path": current_run.get("source_path") or "",
        },
        "progress_delta": {
            "verification_stage_previous": previous_stage,
            "verification_stage_current": current_stage,
            "verification_stage_delta": stage_delta,
            "violation_count_previous": previous_violations,
            "violation_count_current": current_violations,
            "violation_count_delta": current_violations - previous_violations,
            "unique_bucket_count_previous": previous_buckets,
            "unique_bucket_count_current": current_buckets,
            "unique_bucket_count_delta": current_buckets - previous_buckets,
            "best_margin_previous_mm": previous_margin,
            "best_margin_current_mm": current_margin,
            "best_margin_delta_mm": margin_delta,
            "top_bucket_previous": (previous.get("summary") or {}).get("top_bucket_key") or "",
            "top_bucket_current": (current.get("summary") or {}).get("top_bucket_key") or "",
            "top_bucket_overlap": round(overlap, 3),
            "stop_action_previous": previous_action,
            "stop_action_current": current_action,
            "evidence": evidence,
        },
        "no_progress": {
            "detected": no_progress,
            "state": progress_state,
            "confidence": 0.9 if no_progress or current_passes else 0.6,
            "reason": reason,
        },
        "recommendation": {
            "action": action,
            "reason": reason,
            "next_dimension": (
                (current.get("suggested_next_dimension") or {}).get("category")
                if not current_passes
                else "none"
            ),
        },
    }


def build_diagnostics_dashboard(
    *,
    route_diagnostics: dict[str, Any] | None = None,
    build_summary: dict[str, Any] | None = None,
    drc_diagnostics: dict[str, Any] | None = None,
    source_path: str = "",
) -> dict[str, Any]:
    route_diagnostics = route_diagnostics or {}
    build_summary = build_summary or {}
    drc_diagnostics = drc_diagnostics or {}
    rows = normalize_route_diagnostic_violations(route_diagnostics)
    top_buckets = summarize_conflict_buckets(rows)
    margins = [row["margin_mm"] for row in rows if isinstance(row.get("margin_mm"), (int, float))]
    failed_candidate_count = int(route_diagnostics.get("failed_candidate_count") or 0)
    strict_aborted = bool(route_diagnostics.get("strict_aborted"))
    stage = "route_commit" if strict_aborted or rows else "production"

    dashboard = {
        "schema_version": 1,
        "tool": "pardal-physical-diagnostics",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "run": {
            "source_path": source_path,
            "source_hash": _sha12(json.dumps(route_diagnostics, sort_keys=True)),
            "strict_aborted": strict_aborted,
            "candidate_count": failed_candidate_count or None,
            "failed_candidate_count": failed_candidate_count,
            "verification_stage_reached": stage,
        },
        "summary": {
            "violation_count": len(rows),
            "unique_bucket_count": len(top_buckets),
            "top_bucket_key": top_buckets[0]["bucket_key"] if top_buckets else "",
            "best_margin_mm": min(margins) if margins else None,
        },
        "first_blockers": top_buckets[:5],
        "top_buckets": top_buckets,
        "stop_decision": _stop_decision(rows, top_buckets),
        "suggested_next_dimension": {
            "category": "replace_existing" if rows else "none",
            "confidence": 0.8 if rows else 1.0,
            "reason": (
                "Failure cluster is concentrated around route-commit geometry."
                if rows
                else "Passing or no route diagnostic failure."
            ),
            "recommended_source_actions": [],
        },
        "inputs": {
            "build_summary_present": bool(build_summary),
            "drc_diagnostics_present": bool(drc_diagnostics),
            "route_diagnostics_present": bool(route_diagnostics),
        },
    }
    if build_summary:
        if "production_checks" in build_summary:
            dashboard["production_checks"] = build_summary["production_checks"]
        if "dfm_report" in build_summary:
            dashboard["dfm_report"] = build_summary["dfm_report"]
    return dashboard


def load_route_diagnostics_dashboard(path_or_root: Path) -> dict[str, Any]:
    """Build a dashboard from a route diagnostics JSON path or artifact root."""

    route_path = (
        path_or_root
        if path_or_root.is_file() and path_or_root.name == "route-diagnostics.json"
        else _find_artifact(path_or_root, "route-diagnostics.json")
    )
    build_summary_path = (
        _find_artifact(path_or_root, "build-summary-strict.json")
        or _find_artifact(path_or_root, "build-summary.json")
    )
    drc_diagnostics_path = _find_artifact(path_or_root, "drc-diagnostics.json")
    return build_diagnostics_dashboard(
        route_diagnostics=_read_json(route_path),
        build_summary=_read_json(build_summary_path),
        drc_diagnostics=_read_json(drc_diagnostics_path),
        source_path=str(route_path or path_or_root),
    )


def write_diagnostics_dashboard(path: Path, dashboard: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dashboard, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_progress_comparison(path: Path, comparison: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
