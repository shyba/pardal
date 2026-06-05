#!/usr/bin/env python3
"""Extract FreeRouting runtime feature datasets for important parity fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES_JSON = PROJECT_ROOT / "tests/fixtures/parity_fixtures" / "fr_runtime_feature_cases.json"

PASS_LINE_RE = re.compile(
    r"Auto-router pass #(?P<pass_no>\d+).*?completed in (?P<duration>.+?) with the score of (?P<score>[0-9.+-]+)"
)


@dataclass(frozen=True)
class FrRuntimeFeatureRow:
    run_label: str
    fixture: str
    input_pcb: str
    seed: int | None
    max_passes: int | None
    job_timeout: str
    freerouting_java_image: str
    freerouting_jar: str
    freerouting_ok: bool
    fr_violations: int
    fr_unconnected: int
    fr_violations_routing_only: int
    fr_unconnected_routing_only: int
    fr_runtime_s: float
    fr_log_lines: int
    fr_stdout_lines: int
    fr_stderr_lines: int
    trace_present: bool
    trace_events: int
    trace_max_events: int
    trace_truncated: bool
    phase_attempt_start: int
    phase_attempt_end: int
    phase_autoroute_connection: int
    phase_maze_search: int
    phase_maze_search_progress: int
    phase_insert_connection: int
    phase_pass_start: int
    phase_pass_end: int
    state_routed: int
    state_failed: int
    state_no_unconnected: int
    state_skipped: int
    state_running: int
    state_stop: int
    reason_inactive_layer: int
    reason_maze_no_connection: int
    reason_insert_via_failed: int
    reason_insert_trace_failed: int
    reason_via_mask_not_found: int
    reason_forced_via_failed: int
    reason_normalize_failed: int
    reason_other: int
    mojo_violations: int
    mojo_unconnected: int
    mojo_violations_routing_only: int
    mojo_unconnected_routing_only: int
    mojo_failed_nets: int
    delta_drc_violations: int
    delta_drc_unconnected: int
    delta_drc_violations_routing_only: int
    delta_drc_unconnected_routing_only: int


@dataclass(frozen=True)
class FrPassFeatureRow:
    run_label: str
    fixture: str
    pass_no: int
    pass_state: str
    score_before: float
    score_after: float
    incomplete_after: int
    violations_after: int
    pass_duration_s: float
    restored_earlier_board: bool


@dataclass(frozen=True)
class FrNetFeatureRow:
    run_label: str
    fixture: str
    net_name: str
    net_no: int
    events: int
    routed_count: int
    failed_count: int
    no_unconnected_count: int
    top_reason_1: str
    top_reason_2: str
    top_reason_3: str
    first_ts_ms: int
    last_ts_ms: int


@dataclass(frozen=True)
class FrDecisionSignatureRow:
    run_label: str
    fixture: str
    signature_len: int
    signature_sha256: str
    signature_prefix: str
    signature_elements: list[str]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _line_count(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _to_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_float(value: Any, default: float = -1.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _duration_to_seconds(text: str) -> float:
    seconds = 0.0
    hour_match = re.search(r"([0-9]+)\s+hours?", text)
    minute_match = re.search(r"([0-9]+)\s+minutes?", text)
    sec_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+seconds?", text)
    if hour_match:
        seconds += float(hour_match.group(1)) * 3600.0
    if minute_match:
        seconds += float(minute_match.group(1)) * 60.0
    if sec_match:
        seconds += float(sec_match.group(1))
    return seconds


def _reason_class(reason: str) -> str:
    r = reason.strip().lower()
    if not r:
        return "other"
    if "inactive_layer" in r or "layers are disabled" in r:
        return "inactive_layer"
    if "maze_no_connection" in r or "search_exhausted" in r or "no connection was found" in r:
        return "maze_no_connection"
    if "insert_via_failed" in r or "final_insert_via_failed" in r:
        return "insert_via_failed"
    if "insert_trace_failed" in r or "forced_trace_insert_failed" in r:
        return "insert_trace_failed"
    if "via_mask_not_found" in r:
        return "via_mask_not_found"
    if "forced_via_failed" in r:
        return "forced_via_failed"
    if "normalize_failed" in r:
        return "normalize_failed"
    return "other"


def _net_key(event: dict[str, Any]) -> tuple[str, int]:
    net_name = str(event.get("net_name", "")).strip()
    net_no_raw = event.get("net_no")
    net_no = _to_int(net_no_raw, default=-1)
    if net_name:
        return net_name, net_no
    if net_no >= 0:
        return f"#{net_no}", net_no
    return "<unknown>", -1


def _phase_count(phases: dict[str, Any], key: str) -> int:
    return _to_int(phases.get(key, 0), default=0)


def _state_count(states: dict[str, Any], key: str) -> int:
    return _to_int(states.get(key, 0), default=0)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")


def _load_cases_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        return {}, {}, payload
    if not isinstance(payload, dict):
        raise ValueError(f"cases manifest must be list or object: {path}")
    defaults = payload.get("defaults") or {}
    suite = payload.get("suite") or {}
    cases = payload.get("cases") or []
    if not isinstance(defaults, dict) or not isinstance(suite, dict) or not isinstance(cases, list):
        raise ValueError(f"invalid manifest shape: {path}")
    out_cases: list[dict[str, Any]] = []
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"case[{i}] must be object")
        if "name" not in case or "pcb" not in case:
            raise ValueError(f"case[{i}] missing name/pcb")
        merged = dict(defaults)
        merged.update(case)
        out_cases.append(merged)
    return defaults, suite, out_cases


def _run_suite(
    *,
    cases: list[dict[str, Any]],
    suite_options: dict[str, Any],
    suite_out_dir: Path,
) -> Path:
    fixtures_json = suite_out_dir / "_runtime_feature_cases.effective.json"
    fixtures_json.parent.mkdir(parents=True, exist_ok=True)
    fixtures_json.write_text(json.dumps(cases, indent=2, sort_keys=True), encoding="utf-8")

    cmd = [
        str(PROJECT_ROOT / "venv" / "bin" / "python"),
        "-m",
        "pardal.tools.run_parity_suite",
        "--fixtures-json",
        str(fixtures_json),
        "--out-dir",
        str(suite_out_dir),
        "--no-update-diary",
    ]
    if bool(suite_options.get("no_cache", True)):
        cmd.append("--no-cache")
    if bool(suite_options.get("allow_unpinned_mojo_cfg", True)):
        cmd.append("--allow-unpinned-mojo-cfg")
    if "kicad_drc_timeout_s" in suite_options:
        cmd.extend(["--kicad-drc-timeout-s", str(suite_options["kicad_drc_timeout_s"])])

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    summary_path = suite_out_dir / "suite_summary.json"
    if result.returncode != 0 and not summary_path.exists():
        raise subprocess.CalledProcessError(result.returncode, cmd)
    if result.returncode != 0:
        print(
            f"[warn] parity suite exited {result.returncode}; continuing with {summary_path}",
            file=sys.stderr,
        )
    return summary_path


def _summarize_trace(trace_path: Path) -> Path:
    cmd = [
        str(PROJECT_ROOT / "venv" / "bin" / "python"),
        str(PROJECT_ROOT / "pardal" / "tools" / "summarize_freerouting_trace.py"),
        "--in",
        str(trace_path),
    ]
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True)
    return trace_path.with_suffix(".summary.json")


def _extract_pass_rows(
    *,
    run_label: str,
    fixture: str,
    trace_events: list[dict[str, Any]],
    stdout_lines: list[str],
) -> list[FrPassFeatureRow]:
    per_pass: dict[int, dict[str, Any]] = {}

    for ev in trace_events:
        phase = str(ev.get("phase", ""))
        pass_no = _to_int(ev.get("pass_no"), default=-1)
        if pass_no < 0:
            continue
        row = per_pass.setdefault(
            pass_no,
            {
                "pass_state": "",
                "score_before": -1.0,
                "score_after": -1.0,
                "incomplete_after": -1,
                "violations_after": -1,
                "pass_duration_s": -1.0,
                "restored_earlier_board": False,
            },
        )
        metrics = ev.get("metrics") if isinstance(ev.get("metrics"), dict) else {}
        if phase == "pass_start":
            row["pass_state"] = str(ev.get("state", "RUNNING"))
            if "board_score_before" in metrics:
                row["score_before"] = _to_float(metrics.get("board_score_before"))
        elif phase == "pass_end":
            row["pass_state"] = str(ev.get("state", "STOP"))
            if "board_score_after" in metrics:
                row["score_after"] = _to_float(metrics.get("board_score_after"))
            if "incomplete" in metrics:
                row["incomplete_after"] = _to_int(metrics.get("incomplete"))
            if "violations" in metrics:
                row["violations_after"] = _to_int(metrics.get("violations"))

    for line in stdout_lines:
        m = PASS_LINE_RE.search(line)
        if not m:
            continue
        pass_no = _to_int(m.group("pass_no"), default=-1)
        if pass_no < 0:
            continue
        row = per_pass.setdefault(
            pass_no,
            {
                "pass_state": "",
                "score_before": -1.0,
                "score_after": -1.0,
                "incomplete_after": -1,
                "violations_after": -1,
                "pass_duration_s": -1.0,
                "restored_earlier_board": False,
            },
        )
        row["pass_duration_s"] = _duration_to_seconds(m.group("duration"))
        if row["score_after"] < 0:
            row["score_after"] = _to_float(m.group("score"))

    out: list[FrPassFeatureRow] = []
    for pass_no in sorted(per_pass):
        row = per_pass[pass_no]
        out.append(
            FrPassFeatureRow(
                run_label=run_label,
                fixture=fixture,
                pass_no=pass_no,
                pass_state=str(row["pass_state"]),
                score_before=_to_float(row["score_before"]),
                score_after=_to_float(row["score_after"]),
                incomplete_after=_to_int(row["incomplete_after"]),
                violations_after=_to_int(row["violations_after"]),
                pass_duration_s=_to_float(row["pass_duration_s"]),
                restored_earlier_board=bool(row["restored_earlier_board"]),
            )
        )
    return out


def _extract_net_rows(
    *,
    run_label: str,
    fixture: str,
    trace_events: list[dict[str, Any]],
) -> list[FrNetFeatureRow]:
    per_net: dict[str, dict[str, Any]] = {}

    for ev in trace_events:
        net_name, net_no = _net_key(ev)
        row = per_net.setdefault(
            net_name,
            {
                "net_no": net_no,
                "events": 0,
                "routed_count": 0,
                "failed_count": 0,
                "no_unconnected_count": 0,
                "first_ts_ms": -1,
                "last_ts_ms": -1,
                "reason_counts": {},
            },
        )
        row["events"] += 1
        state = str(ev.get("state", ""))
        if state == "ROUTED":
            row["routed_count"] += 1
        if state == "FAILED":
            row["failed_count"] += 1
        if state == "NO_UNCONNECTED_NETS":
            row["no_unconnected_count"] += 1

        ts_ms = _to_int(ev.get("ts_ms"), default=-1)
        if ts_ms >= 0:
            if row["first_ts_ms"] < 0 or ts_ms < row["first_ts_ms"]:
                row["first_ts_ms"] = ts_ms
            if row["last_ts_ms"] < 0 or ts_ms > row["last_ts_ms"]:
                row["last_ts_ms"] = ts_ms

        reason = str(ev.get("reason", "")).strip()
        if reason:
            rc = _reason_class(reason)
            reason_counts: dict[str, int] = row["reason_counts"]
            reason_counts[rc] = reason_counts.get(rc, 0) + 1

    out: list[FrNetFeatureRow] = []
    for net_name in sorted(per_net):
        row = per_net[net_name]
        ranked = sorted(row["reason_counts"].items(), key=lambda kv: (-kv[1], kv[0]))
        top = [k for k, _ in ranked[:3]]
        while len(top) < 3:
            top.append("")
        out.append(
            FrNetFeatureRow(
                run_label=run_label,
                fixture=fixture,
                net_name=net_name,
                net_no=_to_int(row["net_no"], default=-1),
                events=_to_int(row["events"], default=0),
                routed_count=_to_int(row["routed_count"], default=0),
                failed_count=_to_int(row["failed_count"], default=0),
                no_unconnected_count=_to_int(row["no_unconnected_count"], default=0),
                top_reason_1=top[0],
                top_reason_2=top[1],
                top_reason_3=top[2],
                first_ts_ms=_to_int(row["first_ts_ms"], default=-1),
                last_ts_ms=_to_int(row["last_ts_ms"], default=-1),
            )
        )
    return out


def _build_signature_row(
    *,
    run_label: str,
    fixture: str,
    trace_events: list[dict[str, Any]],
) -> FrDecisionSignatureRow:
    elements: list[str] = []
    for ev in trace_events:
        pass_no = _to_int(ev.get("pass_no"), default=-1)
        net_name, _ = _net_key(ev)
        phase = str(ev.get("phase", ""))
        state = str(ev.get("state", ""))
        reason = _reason_class(str(ev.get("reason", "")))
        elements.append(f"{pass_no}|{net_name}|{phase}|{state}|{reason}")
    sig_text = "\n".join(elements)
    sig_sha = hashlib.sha256(sig_text.encode("utf-8")).hexdigest()
    sig_prefix = " ; ".join(elements[:20])
    return FrDecisionSignatureRow(
        run_label=run_label,
        fixture=fixture,
        signature_len=len(elements),
        signature_sha256=sig_sha,
        signature_prefix=sig_prefix,
        signature_elements=elements,
    )


def _compare_signatures(
    *,
    dir_a: Path,
    dir_b: Path,
    out_path: Path,
) -> None:
    sig_a_path = dir_a / "fr_decision_signatures.jsonl"
    sig_b_path = dir_b / "fr_decision_signatures.jsonl"
    rows_a = _load_jsonl(sig_a_path)
    rows_b = _load_jsonl(sig_b_path)
    by_fixture_a = {str(r.get("fixture", "")): r for r in rows_a}
    by_fixture_b = {str(r.get("fixture", "")): r for r in rows_b}
    fixtures = sorted(set(by_fixture_a) | set(by_fixture_b))

    out_rows: list[dict[str, Any]] = []
    for fixture in fixtures:
        a = by_fixture_a.get(fixture)
        b = by_fixture_b.get(fixture)
        if a is None or b is None:
            out_rows.append(
                {
                    "fixture": fixture,
                    "status": "missing",
                    "in_a": a is not None,
                    "in_b": b is not None,
                }
            )
            continue
        a_elems = a.get("signature_elements") or []
        b_elems = b.get("signature_elements") or []
        if not isinstance(a_elems, list) or not isinstance(b_elems, list):
            out_rows.append({"fixture": fixture, "status": "invalid_signature_elements"})
            continue
        first_diff = -1
        n = min(len(a_elems), len(b_elems))
        for i in range(n):
            if str(a_elems[i]) != str(b_elems[i]):
                first_diff = i
                break
        if first_diff < 0 and len(a_elems) != len(b_elems):
            first_diff = n
        out_rows.append(
            {
                "fixture": fixture,
                "status": "different" if first_diff >= 0 else "equal",
                "first_diff_index": first_diff,
                "len_a": len(a_elems),
                "len_b": len(b_elems),
                "sha_a": str(a.get("signature_sha256", "")),
                "sha_b": str(b.get("signature_sha256", "")),
            }
        )

    payload = {
        "dir_a": str(dir_a),
        "dir_b": str(dir_b),
        "fixtures": out_rows,
    }
    _write_json(out_path, payload)


def _extract_from_suite(
    *,
    run_label: str,
    suite_summary_path: Path,
    cases_by_name: dict[str, dict[str, Any]],
    summarize_trace: bool,
    emit_decision_signature: bool,
    out_dir: Path,
) -> None:
    suite_summary = _load_json(suite_summary_path)
    summaries = suite_summary.get("summaries", [])
    if not isinstance(summaries, list):
        raise RuntimeError(f"invalid suite_summary payload: {suite_summary_path}")

    runtime_rows: list[dict[str, Any]] = []
    pass_rows: list[dict[str, Any]] = []
    net_rows: list[dict[str, Any]] = []
    signature_rows: list[dict[str, Any]] = []

    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        fixture = str(summary.get("fixture", ""))
        case_cfg = cases_by_name.get(fixture, {})

        trace_path_text = str(summary.get("freerouting_trace_jsonl", "")).strip()
        trace_path = Path(trace_path_text).resolve() if trace_path_text else None
        trace_events: list[dict[str, Any]] = []
        trace_summary: dict[str, Any] = {}
        trace_present = False

        if trace_path is not None and trace_path.exists():
            trace_present = True
            trace_events = _load_jsonl(trace_path)
            trace_summary_path = trace_path.with_suffix(".summary.json")
            if summarize_trace:
                trace_summary_path = _summarize_trace(trace_path)
            if trace_summary_path.exists():
                loaded = _load_json(trace_summary_path)
                if isinstance(loaded, dict):
                    trace_summary = loaded

        phases = trace_summary.get("phases", {}) if isinstance(trace_summary.get("phases"), dict) else {}
        states = trace_summary.get("states", {}) if isinstance(trace_summary.get("states"), dict) else {}
        trace_events_count = _to_int(trace_summary.get("events", len(trace_events)), default=len(trace_events))
        trace_max_events = _to_int(case_cfg.get("freerouting_trace_max_events", 0), default=0)
        trace_truncated = bool(trace_max_events > 0 and trace_events_count >= trace_max_events)

        reason_counts = {
            "inactive_layer": 0,
            "maze_no_connection": 0,
            "insert_via_failed": 0,
            "insert_trace_failed": 0,
            "via_mask_not_found": 0,
            "forced_via_failed": 0,
            "normalize_failed": 0,
            "other": 0,
        }
        for ev in trace_events:
            reason = str(ev.get("reason", "")).strip()
            if not reason:
                continue
            rc = _reason_class(reason)
            reason_counts[rc] = reason_counts.get(rc, 0) + 1

        stdout_log = str(summary.get("freerouting_stdout_log", "")).strip()
        stderr_log = str(summary.get("freerouting_stderr_log", "")).strip()
        fr_log = str(summary.get("freerouting_log_file", "")).strip()
        stdout_path = Path(stdout_log).resolve() if stdout_log else None
        stderr_path = Path(stderr_log).resolve() if stderr_log else None
        fr_log_path = Path(fr_log).resolve() if fr_log else None
        stdout_lines = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines() if stdout_path and stdout_path.exists() else []

        timing = summary.get("timing_s", {}) if isinstance(summary.get("timing_s"), dict) else {}
        fr_drc = summary.get("freerouting_drc", {}) if isinstance(summary.get("freerouting_drc"), dict) else {}
        fr_drc_ro = summary.get("freerouting_drc_routing_only", {}) if isinstance(summary.get("freerouting_drc_routing_only"), dict) else {}
        mojo_drc = summary.get("mojo_drc", {}) if isinstance(summary.get("mojo_drc"), dict) else {}
        mojo_drc_ro = summary.get("mojo_drc_routing_only", {}) if isinstance(summary.get("mojo_drc_routing_only"), dict) else {}

        runtime_row = FrRuntimeFeatureRow(
            run_label=run_label,
            fixture=fixture,
            input_pcb=str(summary.get("input_pcb", "")),
            seed=_to_int(case_cfg.get("freerouting_seed"), default=-1),
            max_passes=_to_int(case_cfg.get("freerouting_max_passes"), default=-1),
            job_timeout=str(case_cfg.get("freerouting_job_timeout", "")),
            freerouting_java_image=str(case_cfg.get("freerouting_java_image", "")),
            freerouting_jar=str(case_cfg.get("freerouting_use_local_jar", "")),
            freerouting_ok=bool(summary.get("freerouting_ok", False)),
            fr_violations=_to_int(fr_drc.get("violations"), default=-1),
            fr_unconnected=_to_int(fr_drc.get("unconnected"), default=-1),
            fr_violations_routing_only=_to_int(fr_drc_ro.get("violations"), default=-1),
            fr_unconnected_routing_only=_to_int(fr_drc_ro.get("unconnected"), default=-1),
            fr_runtime_s=_to_float(timing.get("freerouting_route_s"), default=-1.0),
            fr_log_lines=_line_count(fr_log_path),
            fr_stdout_lines=_line_count(stdout_path),
            fr_stderr_lines=_line_count(stderr_path),
            trace_present=trace_present,
            trace_events=trace_events_count,
            trace_max_events=trace_max_events,
            trace_truncated=trace_truncated,
            phase_attempt_start=_phase_count(phases, "attempt_start"),
            phase_attempt_end=_phase_count(phases, "attempt_end"),
            phase_autoroute_connection=_phase_count(phases, "autoroute_connection"),
            phase_maze_search=_phase_count(phases, "maze_search"),
            phase_maze_search_progress=_phase_count(phases, "maze_search_progress"),
            phase_insert_connection=_phase_count(phases, "insert_connection"),
            phase_pass_start=_phase_count(phases, "pass_start"),
            phase_pass_end=_phase_count(phases, "pass_end"),
            state_routed=_state_count(states, "ROUTED"),
            state_failed=_state_count(states, "FAILED"),
            state_no_unconnected=_state_count(states, "NO_UNCONNECTED_NETS"),
            state_skipped=_state_count(states, "SKIPPED"),
            state_running=_state_count(states, "RUNNING"),
            state_stop=_state_count(states, "STOP"),
            reason_inactive_layer=_to_int(reason_counts.get("inactive_layer"), default=0),
            reason_maze_no_connection=_to_int(reason_counts.get("maze_no_connection"), default=0),
            reason_insert_via_failed=_to_int(reason_counts.get("insert_via_failed"), default=0),
            reason_insert_trace_failed=_to_int(reason_counts.get("insert_trace_failed"), default=0),
            reason_via_mask_not_found=_to_int(reason_counts.get("via_mask_not_found"), default=0),
            reason_forced_via_failed=_to_int(reason_counts.get("forced_via_failed"), default=0),
            reason_normalize_failed=_to_int(reason_counts.get("normalize_failed"), default=0),
            reason_other=_to_int(reason_counts.get("other"), default=0),
            mojo_violations=_to_int(mojo_drc.get("violations"), default=-1),
            mojo_unconnected=_to_int(mojo_drc.get("unconnected"), default=-1),
            mojo_violations_routing_only=_to_int(mojo_drc_ro.get("violations"), default=-1),
            mojo_unconnected_routing_only=_to_int(mojo_drc_ro.get("unconnected"), default=-1),
            mojo_failed_nets=_to_int(summary.get("mojo_failed_nets"), default=-1),
            delta_drc_violations=_to_int(summary.get("delta_drc_violations"), default=-1),
            delta_drc_unconnected=_to_int(summary.get("delta_drc_unconnected"), default=-1),
            delta_drc_violations_routing_only=_to_int(summary.get("delta_drc_violations_routing_only"), default=-1),
            delta_drc_unconnected_routing_only=_to_int(summary.get("delta_drc_unconnected_routing_only"), default=-1),
        )
        runtime_rows.append(asdict(runtime_row))

        fixture_pass_rows = _extract_pass_rows(
            run_label=run_label,
            fixture=fixture,
            trace_events=trace_events,
            stdout_lines=stdout_lines,
        )
        pass_rows.extend(asdict(r) for r in fixture_pass_rows)

        fixture_net_rows = _extract_net_rows(
            run_label=run_label,
            fixture=fixture,
            trace_events=trace_events,
        )
        net_rows.extend(asdict(r) for r in fixture_net_rows)

        if emit_decision_signature and trace_events:
            sig_row = _build_signature_row(
                run_label=run_label,
                fixture=fixture,
                trace_events=trace_events,
            )
            signature_rows.append(asdict(sig_row))

    _write_jsonl(out_dir / "fr_runtime_features.jsonl", runtime_rows)
    _write_jsonl(out_dir / "fr_pass_features.jsonl", pass_rows)
    _write_jsonl(out_dir / "fr_net_features.jsonl", net_rows)
    if emit_decision_signature:
        _write_jsonl(out_dir / "fr_decision_signatures.jsonl", signature_rows)

    feature_summary = {
        "run_label": run_label,
        "generated_at_unix_s": int(time.time()),
        "suite_summary_json": str(suite_summary_path),
        "fixtures_total": len(runtime_rows),
        "fixtures_with_trace": sum(1 for r in runtime_rows if bool(r.get("trace_present", False))),
        "fixtures_freerouting_ok": sum(1 for r in runtime_rows if bool(r.get("freerouting_ok", False))),
        "total_trace_events": sum(_to_int(r.get("trace_events"), default=0) for r in runtime_rows),
        "output_files": {
            "runtime": str((out_dir / "fr_runtime_features.jsonl").resolve()),
            "passes": str((out_dir / "fr_pass_features.jsonl").resolve()),
            "nets": str((out_dir / "fr_net_features.jsonl").resolve()),
            "signatures": str((out_dir / "fr_decision_signatures.jsonl").resolve()) if emit_decision_signature else "",
        },
    }
    _write_json(out_dir / "fr_feature_summary.json", feature_summary)

    md_lines = [
        f"# FR Runtime Feature Report: {run_label}",
        "",
        f"- suite summary: `{suite_summary_path}`",
        f"- fixtures: `{feature_summary['fixtures_total']}`",
        f"- fixtures with trace: `{feature_summary['fixtures_with_trace']}`",
        f"- FR ok fixtures: `{feature_summary['fixtures_freerouting_ok']}`",
        f"- total trace events: `{feature_summary['total_trace_events']}`",
        "",
        "## Output datasets",
        "",
        f"- `{feature_summary['output_files']['runtime']}`",
        f"- `{feature_summary['output_files']['passes']}`",
        f"- `{feature_summary['output_files']['nets']}`",
    ]
    if emit_decision_signature:
        md_lines.append(f"- `{feature_summary['output_files']['signatures']}`")
    (out_dir / "fr_feature_report.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases-json", type=Path, default=DEFAULT_CASES_JSON)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--run-label", type=str, default="")
    ap.add_argument("--suite-out-dir", type=Path, default=None)
    ap.add_argument("--run-suite", action="store_true", help="Run parity suite before extraction.")
    ap.add_argument("--summarize-trace", action="store_true", help="Generate/update trace summary files.")
    ap.add_argument("--emit-decision-signature", action="store_true", help="Emit decision signature dataset.")
    ap.add_argument("--compare-dir-a", type=Path, default=None, help="Compare signatures from extraction dir A.")
    ap.add_argument("--compare-dir-b", type=Path, default=None, help="Compare signatures from extraction dir B.")
    args = ap.parse_args(argv)

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.compare_dir_a is not None or args.compare_dir_b is not None:
        if args.compare_dir_a is None or args.compare_dir_b is None:
            raise SystemExit("both --compare-dir-a and --compare-dir-b are required for compare mode")
        compare_out = out_dir / "fr_decision_signature_compare.json"
        _compare_signatures(
            dir_a=args.compare_dir_a.resolve(),
            dir_b=args.compare_dir_b.resolve(),
            out_path=compare_out,
        )
        print(compare_out)
        return 0

    run_label = args.run_label.strip() or time.strftime("fr_runtime_features_%Y%m%d_%H%M%S")

    _, suite_options, merged_cases = _load_cases_manifest(args.cases_json.resolve())
    cases_by_name = {str(c.get("name", "")): c for c in merged_cases}

    suite_out_dir = args.suite_out_dir.resolve() if args.suite_out_dir else (out_dir / "suite_run")
    suite_summary_path = suite_out_dir / "suite_summary.json"

    if args.run_suite:
        suite_summary_path = _run_suite(
            cases=merged_cases,
            suite_options=suite_options,
            suite_out_dir=suite_out_dir,
        )
    elif not suite_summary_path.exists():
        raise SystemExit(f"suite summary not found: {suite_summary_path}")

    _extract_from_suite(
        run_label=run_label,
        suite_summary_path=suite_summary_path,
        cases_by_name=cases_by_name,
        summarize_trace=bool(args.summarize_trace),
        emit_decision_signature=bool(args.emit_decision_signature),
        out_dir=out_dir,
    )

    print(out_dir / "fr_feature_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
