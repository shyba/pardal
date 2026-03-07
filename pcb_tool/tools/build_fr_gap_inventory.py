#!/usr/bin/env python3
"""Build an exhaustive FR->Mojo feature gap inventory for the parity corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_JSONS = [
    PROJECT_ROOT / "parity_fixtures" / "fr_runtime_feature_cases.json",
    PROJECT_ROOT / "parity_fixtures" / "fr_runtime_feature_cases_fpga_large.json",
]
DEFAULT_WORKLIST = PROJECT_ROOT / "parity_worklist.json"
VENV_PY = PROJECT_ROOT / "venv" / "bin" / "python"
EXTRACT_TOOL = PROJECT_ROOT / "pcb_tool" / "tools" / "extract_fr_runtime_features.py"
MOJO_CAPTURE_TOOL = PROJECT_ROOT / "pcb_tool" / "tools" / "capture_mojo_trace.py"


@dataclass(frozen=True)
class NetCompareRow:
    fixture: str
    net_name: str
    fr_net_name: str
    status: str
    first_diff_index: int
    divergence_class: str
    fr_events: int
    mojo_events: int


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


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_json(payload: Any) -> str:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        return {}, {}, [dict(x) for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        raise ValueError(f"invalid manifest: {path}")
    suite = dict(payload.get("suite") or {})
    defaults = dict(payload.get("defaults") or {})
    cases_raw = payload.get("cases") or []
    if not isinstance(cases_raw, list):
        raise ValueError(f"invalid manifest cases list: {path}")
    cases: list[dict[str, Any]] = []
    for case in cases_raw:
        if not isinstance(case, dict):
            continue
        merged = dict(defaults)
        merged.update(case)
        if "name" not in merged or "pcb" not in merged:
            continue
        cases.append(merged)
    return suite, defaults, cases


def _merge_corpus(cases_jsons: list[Path]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    merged_suite: dict[str, Any] = {}
    merged_defaults: dict[str, Any] = {}
    by_name: dict[str, dict[str, Any]] = {}

    for manifest_path in cases_jsons:
        suite, defaults, cases = _load_manifest(manifest_path)
        merged_suite.update(suite)
        merged_defaults.update(defaults)
        for case in cases:
            name = str(case.get("name", "")).strip()
            if not name:
                continue
            # Last manifest wins when names collide.
            by_name[name] = dict(case)

    merged_cases = [by_name[k] for k in sorted(by_name)]
    return merged_suite, merged_defaults, merged_cases


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, check=False)


def _extract_fr_features(
    *,
    effective_manifest_path: Path,
    out_dir: Path,
    run_suite: bool,
    run_label: str,
) -> Path:
    cmd = [
        str(VENV_PY),
        str(EXTRACT_TOOL),
        "--cases-json",
        str(effective_manifest_path),
        "--out-dir",
        str(out_dir),
        "--summarize-trace",
        "--emit-decision-signature",
    ]
    if run_suite:
        cmd.extend(["--run-suite", "--suite-out-dir", str(out_dir / "suite_run")])
    if run_label:
        cmd.extend(["--run-label", run_label])

    res = _run(cmd, PROJECT_ROOT)
    if res.returncode != 0:
        raise RuntimeError(f"FR extraction failed ({res.returncode}):\n{res.stdout}\n{res.stderr}")
    summary_path = out_dir / "fr_feature_summary.json"
    if not summary_path.exists():
        raise RuntimeError(f"FR extraction missing summary: {summary_path}")
    return summary_path


def _worklist_target_nets(worklist_path: Path) -> set[str]:
    if not worklist_path.exists():
        return set()
    payload = _load_json(worklist_path)
    out: set[str] = set()
    for feat in payload.get("features", []) or []:
        if not isinstance(feat, dict):
            continue
        net = str(feat.get("target_net", "")).strip()
        if net:
            out.add(net)
    return out


def _fr_trace_paths_by_fixture(fr_summary_path: Path) -> dict[str, Path]:
    summary = _load_json(fr_summary_path)
    suite_summary_path = Path(str(summary.get("suite_summary_json", ""))).resolve()
    suite = _load_json(suite_summary_path)
    out: dict[str, Path] = {}
    for row in suite.get("summaries", []) or []:
        if not isinstance(row, dict):
            continue
        fixture = str(row.get("fixture", "")).strip()
        trace_jsonl = str(row.get("freerouting_trace_jsonl", "")).strip()
        if fixture and trace_jsonl:
            out[fixture] = Path(trace_jsonl).resolve()
    return out


def _build_watched_nets(
    *,
    fr_net_rows: list[dict[str, Any]],
    top_n: int,
    worklist_nets: set[str],
    fixtures: list[str],
) -> dict[str, list[str]]:
    by_fixture: dict[str, list[dict[str, Any]]] = {fx: [] for fx in fixtures}
    for row in fr_net_rows:
        fixture = str(row.get("fixture", "")).strip()
        if fixture in by_fixture:
            by_fixture[fixture].append(row)

    out: dict[str, list[str]] = {}
    for fixture in fixtures:
        rows = by_fixture.get(fixture, [])
        rows_sorted = sorted(rows, key=lambda r: int(r.get("events", 0) or 0), reverse=True)
        chosen: set[str] = set()

        for row in rows:
            net = str(row.get("net_name", "")).strip()
            if not net:
                continue
            failed = int(row.get("failed_count", 0) or 0)
            reasons = [
                str(row.get("top_reason_1", "")).strip(),
                str(row.get("top_reason_2", "")).strip(),
                str(row.get("top_reason_3", "")).strip(),
            ]
            non_other_reason = any(r and r != "other" for r in reasons)
            if failed > 0 or non_other_reason:
                chosen.add(net)

        for row in rows_sorted[: max(1, top_n)]:
            net = str(row.get("net_name", "")).strip()
            if net:
                chosen.add(net)

        chosen.update(worklist_nets)
        out[fixture] = sorted(chosen)
    return out


def _fixture_manifest_payload(
    *,
    suite: dict[str, Any],
    defaults: dict[str, Any],
    case: dict[str, Any],
) -> list[dict[str, Any]]:
    # capture_mojo_trace.py delegates to run_parity_suite fixtures-json mode,
    # which expects a plain JSON list of fixture objects.
    _ = suite
    _ = defaults
    return [dict(case)]


def _capture_mojo_fixture(
    *,
    fixture: str,
    fixture_manifest_path: Path,
    trace_nets: list[str],
    out_dir: Path,
    trace_max_events: int,
    allow_unpinned_mojo_cfg: bool,
    kicad_drc_timeout_s: float | None,
) -> Path:
    cmd = [
        str(VENV_PY),
        str(MOJO_CAPTURE_TOOL),
        "--fixtures-json",
        str(fixture_manifest_path),
        "--out-dir",
        str(out_dir),
        "--trace-nets",
        ",".join(trace_nets),
        "--trace-max-events",
        str(trace_max_events),
        "--run-label",
        f"mojo_capture_{fixture}_{time.strftime('%Y%m%d_%H%M%S')}",
    ]
    if allow_unpinned_mojo_cfg:
        cmd.append("--allow-unpinned-mojo-cfg")
    if kicad_drc_timeout_s is not None:
        cmd.extend(["--kicad-drc-timeout-s", str(kicad_drc_timeout_s)])

    res = _run(cmd, PROJECT_ROOT)
    capture_json = out_dir / "mojo_trace_capture.json"
    if res.returncode != 0 and not capture_json.exists():
        raise RuntimeError(
            f"Mojo capture failed for {fixture} ({res.returncode}):\n{res.stdout}\n{res.stderr}"
        )
    if not capture_json.exists():
        raise RuntimeError(f"Mojo capture missing artifact for {fixture}: {capture_json}")
    return capture_json


def _normalize_event(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts_ms": int(ev.get("ts_ms", -1) or -1),
        "net_name": str(ev.get("net_name", "")).strip(),
        "phase": str(ev.get("phase", "")).strip(),
        "state": str(ev.get("state", "")).strip(),
        "reason": str(ev.get("reason", "")).strip(),
    }


def _sig(ev: dict[str, Any]) -> str:
    return f"{ev.get('phase','')}|{ev.get('state','')}|{ev.get('reason','')}"


def _group_by_net(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        net_name = str(row.get("net_name", "")).strip()
        if not net_name:
            continue
        out.setdefault(net_name, []).append(row)
    return out


def _fallback_fr_net(net_name: str, available: set[str]) -> str:
    if net_name in available:
        return net_name
    parts = net_name.split("_", 1)
    if len(parts) != 2:
        return net_name
    suffix = parts[1]
    if len(suffix) < 2:
        return net_name
    row_prefix = suffix[0]
    digits = suffix[1:]
    if not digits.isdigit():
        return net_name
    target_num = int(digits)
    best_name = ""
    best_delta: int | None = None
    for candidate in available:
        cp = candidate.split("_", 1)
        if len(cp) != 2:
            continue
        cs = cp[1]
        if len(cs) < 2 or cs[0] != row_prefix:
            continue
        d = cs[1:]
        if not d.isdigit():
            continue
        delta = abs(int(d) - target_num)
        if best_delta is None or delta < best_delta or (delta == best_delta and candidate < best_name):
            best_name = candidate
            best_delta = delta
    return best_name or net_name


def _classify_divergence(fr_ev: dict[str, Any] | None, mojo_ev: dict[str, Any] | None) -> str:
    phase = str((mojo_ev or fr_ev or {}).get("phase", ""))
    reason = str((mojo_ev or fr_ev or {}).get("reason", ""))
    if phase == "maze_search" and reason in {"maze_no_connection", "no_astar_path"}:
        return "no_path_before_component_connect"
    if phase == "component_connect" and reason in {"no_candidate", "no_astar_path", "iter_no_connect", "no_progress"}:
        return "component_connect_no_progress"
    if "keepout" in reason or "conflict" in reason or "legality" in reason:
        return "legality_reject"
    if "rollback" in reason:
        return "rollback"
    if fr_ev is None or mojo_ev is None:
        return "length_mismatch"
    if str(fr_ev.get("phase", "")) != str(mojo_ev.get("phase", "")):
        return "ordering_mismatch"
    return "reason_mismatch"


def _compare_fixture(
    *,
    fixture: str,
    fr_trace_path: Path,
    mojo_capture_json: Path,
    watched_nets: list[str],
) -> tuple[list[NetCompareRow], list[dict[str, Any]], list[dict[str, Any]]]:
    fr_rows = [_normalize_event(r) for r in _load_jsonl(fr_trace_path)]
    mojo_capture = _load_json(mojo_capture_json)
    mojo_trace_path = Path(str(mojo_capture.get("trace_jsonl", ""))).resolve()
    mojo_rows = [_normalize_event(r) for r in _load_jsonl(mojo_trace_path)]

    fr_by_net = _group_by_net(fr_rows)
    mojo_by_net = _group_by_net([r for r in mojo_rows if not watched_nets or r["net_name"] in watched_nets])

    compare_rows: list[NetCompareRow] = []
    for net in watched_nets:
        fr_net_name = _fallback_fr_net(net, set(fr_by_net))
        fr_net = fr_by_net.get(fr_net_name, [])
        mojo_net = mojo_by_net.get(net, [])
        first_diff = -1
        n = min(len(fr_net), len(mojo_net))
        for i in range(n):
            if _sig(fr_net[i]) != _sig(mojo_net[i]):
                first_diff = i
                break
        if first_diff < 0 and len(fr_net) != len(mojo_net):
            first_diff = n
        status = "equal" if first_diff < 0 else "different"
        fr_ev = fr_net[first_diff] if 0 <= first_diff < len(fr_net) else None
        mojo_ev = mojo_net[first_diff] if 0 <= first_diff < len(mojo_net) else None
        compare_rows.append(
            NetCompareRow(
                fixture=fixture,
                net_name=net,
                fr_net_name=fr_net_name,
                status=status,
                first_diff_index=first_diff,
                divergence_class="equal" if status == "equal" else _classify_divergence(fr_ev, mojo_ev),
                fr_events=len(fr_net),
                mojo_events=len(mojo_net),
            )
        )

    return compare_rows, fr_rows, mojo_rows


def _priority_for_feature(feature_key: str, status: str) -> str:
    if status == "ported":
        return "P2"
    lowered = feature_key.lower()
    if "insert_trace_failed" in lowered or "maze_no_connection" in lowered or "component_connect" in lowered:
        return "P0"
    if "maze_search" in lowered or "insert_connection" in lowered or "autoroute_connection" in lowered:
        return "P1"
    return "P2"


def _recommended_probe(feature_key: str, fixture_hint: str, net_hint: str) -> str:
    return (
        f"./venv/bin/python pcb_tool/tools/capture_mojo_trace.py --fixtures-json <single-fixture-manifest> "
        f"--out-dir parity_runs/probe_{fixture_hint}_{net_hint} --trace-nets {net_hint}"
    )


def _build_inventory(
    *,
    compare_rows: list[NetCompareRow],
    fr_event_pairs: dict[str, set[tuple[str, str]]],
    mojo_event_pairs: dict[str, set[tuple[str, str]]],
    fr_transition_pairs: dict[str, set[tuple[str, str]]],
    mojo_transition_pairs: dict[str, set[tuple[str, str]]],
    evidence_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    diverged_pairs = {
        (r.fixture, r.net_name)
        for r in compare_rows
        if r.status != "equal"
    }

    features: list[dict[str, Any]] = []

    def add_feature_rows(kind: str, fr_map: dict[str, set[tuple[str, str]]], mojo_map: dict[str, set[tuple[str, str]]]) -> None:
        for key in sorted(fr_map):
            fr_pairs = fr_map.get(key, set())
            mojo_pairs = mojo_map.get(key, set())
            if not fr_pairs:
                continue
            if not mojo_pairs:
                status = "unported"
            elif fr_pairs.issubset(mojo_pairs) and not any(pair in diverged_pairs for pair in fr_pairs):
                status = "ported"
            else:
                status = "incomplete"

            fixtures = sorted({fx for fx, _ in fr_pairs})
            nets = sorted({nt for _, nt in fr_pairs})
            fixture_hint = fixtures[0] if fixtures else "fixture"
            net_hint = nets[0] if nets else "net"
            features.append(
                {
                    "feature_key": f"{kind}:{key}",
                    "feature_kind": kind,
                    "status": status,
                    "priority": _priority_for_feature(key, status),
                    "fixtures": fixtures,
                    "nets": nets,
                    "fr_evidence_count": len(fr_pairs),
                    "mojo_evidence_count": len(mojo_pairs),
                    "recommended_next_probe": _recommended_probe(key, fixture_hint, net_hint),
                }
            )

    add_feature_rows("event", fr_event_pairs, mojo_event_pairs)
    add_feature_rows("transition", fr_transition_pairs, mojo_transition_pairs)

    for gap in evidence_gaps:
        features.append(
            {
                "feature_key": f"evidence_gap:{gap['fixture']}:{gap['class']}",
                "feature_kind": "evidence_gap",
                "status": "evidence_gap",
                "priority": "P0",
                "fixtures": [gap["fixture"]],
                "nets": [],
                "fr_evidence_count": 0,
                "mojo_evidence_count": 0,
                "recommended_next_probe": gap.get("recommendation", "rerun fixture capture and compare"),
                "details": gap,
            }
        )

    features.sort(key=lambda x: (x["status"], x["priority"], x["feature_key"]))

    status_counts: dict[str, int] = {}
    priority_counts: dict[str, int] = {}
    for row in features:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        priority_counts[row["priority"]] = priority_counts.get(row["priority"], 0) + 1

    return {
        "features": features,
        "rollups": {
            "status_counts": status_counts,
            "priority_counts": priority_counts,
            "feature_total": len(features),
            "evidence_gap_count": len(evidence_gaps),
        },
    }


def _render_markdown(payload: dict[str, Any], out_path: Path) -> None:
    features = payload.get("features", [])
    rollups = payload.get("rollups", {})
    lines: list[str] = []
    lines.append("# FR -> Mojo Gap Inventory")
    lines.append("")
    lines.append("## Rollup")
    lines.append("")
    lines.append(f"- Total feature rows: {rollups.get('feature_total', 0)}")
    lines.append(f"- Evidence gaps: {rollups.get('evidence_gap_count', 0)}")
    lines.append(f"- Status counts: `{json.dumps(rollups.get('status_counts', {}), sort_keys=True)}`")
    lines.append(f"- Priority counts: `{json.dumps(rollups.get('priority_counts', {}), sort_keys=True)}`")
    lines.append("")
    lines.append("## Top Unported/Incomplete")
    lines.append("")
    lines.append("| Status | Priority | Feature | Fixtures | Nets | FR Count | Mojo Count |")
    lines.append("|---|---|---|---|---|---:|---:|")
    shown = 0
    for row in features:
        if row.get("status") not in {"unported", "incomplete", "evidence_gap"}:
            continue
        lines.append(
            "| {status} | {priority} | `{feature}` | {fixtures} | {nets} | {fr} | {mojo} |".format(
                status=row.get("status", ""),
                priority=row.get("priority", ""),
                feature=row.get("feature_key", ""),
                fixtures=", ".join(row.get("fixtures", [])[:3]),
                nets=", ".join(row.get("nets", [])[:3]),
                fr=row.get("fr_evidence_count", 0),
                mojo=row.get("mojo_evidence_count", 0),
            )
        )
        shown += 1
        if shown >= 200:
            break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases-json", action="append", type=Path, default=[])
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--run-label", type=str, default="")
    ap.add_argument("--run-fr-suite", action="store_true")
    ap.add_argument("--fr-feature-dir", type=Path, default=None)
    ap.add_argument("--top-nets", type=int, default=20)
    ap.add_argument("--trace-max-events", type=int, default=300000)
    ap.add_argument("--allow-unpinned-mojo-cfg", action="store_true", default=True)
    ap.add_argument("--kicad-drc-timeout-s", type=float, default=None)
    ap.add_argument("--worklist", type=Path, default=DEFAULT_WORKLIST)
    args = ap.parse_args(argv)

    cases_jsons = [p.resolve() for p in (args.cases_json or DEFAULT_CASES_JSONS)]
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    run_label = args.run_label.strip() or time.strftime("fr_gap_inventory_%Y%m%d_%H%M%S")

    suite, defaults, merged_cases = _merge_corpus(cases_jsons)
    fixtures = [str(c.get("name", "")).strip() for c in merged_cases if str(c.get("name", "")).strip()]
    corpus_manifest = {
        "suite": suite,
        "defaults": defaults,
        "cases": merged_cases,
    }
    corpus_manifest_path = out_dir / "effective_cases.json"
    _write_json(corpus_manifest_path, corpus_manifest)

    fr_dir = (args.fr_feature_dir.resolve() if args.fr_feature_dir is not None else (out_dir / "fr_extract"))
    if args.fr_feature_dir is not None:
        fr_summary_path = fr_dir / "fr_feature_summary.json"
        if not fr_summary_path.exists():
            raise RuntimeError(f"--fr-feature-dir missing fr_feature_summary.json: {fr_summary_path}")
    else:
        if not args.run_fr_suite:
            raise RuntimeError("non-suite mode requires --fr-feature-dir; otherwise use --run-fr-suite")
        fr_summary_path = _extract_fr_features(
            effective_manifest_path=corpus_manifest_path,
            out_dir=fr_dir,
            run_suite=args.run_fr_suite,
            run_label=run_label,
        )

    fr_net_rows = _load_jsonl(fr_dir / "fr_net_features.jsonl")
    worklist_nets = _worklist_target_nets(args.worklist.resolve())
    watched_by_fixture = _build_watched_nets(
        fr_net_rows=fr_net_rows,
        top_n=max(1, int(args.top_nets)),
        worklist_nets=worklist_nets,
        fixtures=fixtures,
    )
    _write_json(out_dir / "watched_nets_by_fixture.json", watched_by_fixture)

    fr_trace_by_fixture = _fr_trace_paths_by_fixture(fr_summary_path)

    compare_rows_all: list[NetCompareRow] = []
    fr_event_pairs: dict[str, set[tuple[str, str]]] = {}
    mojo_event_pairs: dict[str, set[tuple[str, str]]] = {}
    fr_transition_pairs: dict[str, set[tuple[str, str]]] = {}
    mojo_transition_pairs: dict[str, set[tuple[str, str]]] = {}
    evidence_gaps: list[dict[str, Any]] = []

    for case in merged_cases:
        fixture = str(case.get("name", "")).strip()
        if not fixture:
            continue
        watched_nets = watched_by_fixture.get(fixture, [])
        if not watched_nets:
            evidence_gaps.append(
                {
                    "fixture": fixture,
                    "class": "watchlist_empty",
                    "recommendation": "increase top-nets or validate FR net feature extraction",
                }
            )
            continue

        fr_trace_path = fr_trace_by_fixture.get(fixture)
        if fr_trace_path is None or not fr_trace_path.exists():
            evidence_gaps.append(
                {
                    "fixture": fixture,
                    "class": "fr_trace_missing",
                    "recommendation": "rerun extract_fr_runtime_features with trace enabled for this fixture",
                }
            )
            continue

        fixture_manifest_path = out_dir / "mojo_capture" / fixture / "fixture_manifest.json"
        fixture_manifest_payload = _fixture_manifest_payload(suite=suite, defaults=defaults, case=case)
        _write_json(fixture_manifest_path, fixture_manifest_payload)

        capture_out_dir = fixture_manifest_path.parent
        try:
            mojo_capture_json = _capture_mojo_fixture(
                fixture=fixture,
                fixture_manifest_path=fixture_manifest_path,
                trace_nets=watched_nets,
                out_dir=capture_out_dir,
                trace_max_events=max(1, int(args.trace_max_events)),
                allow_unpinned_mojo_cfg=bool(args.allow_unpinned_mojo_cfg),
                kicad_drc_timeout_s=args.kicad_drc_timeout_s,
            )
        except Exception as exc:
            evidence_gaps.append(
                {
                    "fixture": fixture,
                    "class": "mojo_capture_failed",
                    "error": str(exc),
                    "recommendation": "repair runner/build and rerun fixture capture",
                }
            )
            continue

        try:
            compare_rows, fr_rows, mojo_rows = _compare_fixture(
                fixture=fixture,
                fr_trace_path=fr_trace_path,
                mojo_capture_json=mojo_capture_json,
                watched_nets=watched_nets,
            )
        except Exception as exc:
            evidence_gaps.append(
                {
                    "fixture": fixture,
                    "class": "compare_failed",
                    "error": str(exc),
                    "recommendation": "validate trace JSONL payloads for this fixture",
                }
            )
            continue

        compare_rows_all.extend(compare_rows)

        fr_by_net = _group_by_net(fr_rows)
        mojo_by_net = _group_by_net(mojo_rows)
        for net_name in watched_nets:
            fr_net_name = _fallback_fr_net(net_name, set(fr_by_net))
            fr_events = fr_by_net.get(fr_net_name, [])
            mojo_events = mojo_by_net.get(net_name, [])
            pair = (fixture, net_name)

            for ev in fr_events:
                key = _sig(ev)
                fr_event_pairs.setdefault(key, set()).add(pair)
            for ev in mojo_events:
                key = _sig(ev)
                mojo_event_pairs.setdefault(key, set()).add(pair)

            for i in range(max(0, len(fr_events) - 1)):
                tr = f"{_sig(fr_events[i])} -> {_sig(fr_events[i+1])}"
                fr_transition_pairs.setdefault(tr, set()).add(pair)
            for i in range(max(0, len(mojo_events) - 1)):
                tr = f"{_sig(mojo_events[i])} -> {_sig(mojo_events[i+1])}"
                mojo_transition_pairs.setdefault(tr, set()).add(pair)

    compare_payload = {
        "rows": [
            {
                "fixture": r.fixture,
                "net_name": r.net_name,
                "fr_net_name": r.fr_net_name,
                "status": r.status,
                "first_diff_index": r.first_diff_index,
                "divergence_class": r.divergence_class,
                "fr_events": r.fr_events,
                "mojo_events": r.mojo_events,
            }
            for r in compare_rows_all
        ]
    }
    _write_json(out_dir / "compare_rows.json", compare_payload)

    inv = _build_inventory(
        compare_rows=compare_rows_all,
        fr_event_pairs=fr_event_pairs,
        mojo_event_pairs=mojo_event_pairs,
        fr_transition_pairs=fr_transition_pairs,
        mojo_transition_pairs=mojo_transition_pairs,
        evidence_gaps=evidence_gaps,
    )

    run_meta = {
        "run_label": run_label,
        "generated_at_unix_s": int(time.time()),
        "project_root": str(PROJECT_ROOT),
        "cases_jsons": [str(p) for p in cases_jsons],
        "corpus_manifest_sha256": _sha256_json(corpus_manifest),
        "synthetic_mojo_policy": "excluded",
        "scope": "current parity corpus",
    }

    final_payload = {
        "run_meta": run_meta,
        "corpus_manifest": {
            "fixture_count": len(fixtures),
            "fixtures": fixtures,
            "effective_manifest_json": str(corpus_manifest_path),
        },
        "watchlists": {
            "watchlists_json": str(out_dir / "watched_nets_by_fixture.json"),
            "top_nets": int(args.top_nets),
            "worklist_target_nets_included": sorted(worklist_nets),
        },
        "artifacts": {
            "fr_extract_dir": str(fr_dir),
            "compare_rows_json": str(out_dir / "compare_rows.json"),
        },
        "features": inv["features"],
        "rollups": inv["rollups"],
    }

    inventory_json = out_dir / "fr_gap_inventory.json"
    inventory_md = out_dir / "fr_gap_inventory.md"
    _write_json(inventory_json, final_payload)
    _render_markdown(final_payload, inventory_md)

    print(str(inventory_json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
