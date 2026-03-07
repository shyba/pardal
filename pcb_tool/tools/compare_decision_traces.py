#!/usr/bin/env python3
"""Compare FR and Mojo per-net decision traces and emit a first-divergence report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


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
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_fr_event(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts_ms": int(ev.get("ts_ms", -1) or -1),
        "net_name": str(ev.get("net_name", "")).strip(),
        "phase": str(ev.get("phase", "")).strip(),
        "state": str(ev.get("state", "")).strip(),
        "reason": str(ev.get("reason", "")).strip(),
    }


def _normalize_mojo_event(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "ts_ms": int(ev.get("ts_ms", -1) or -1),
        "net_name": str(ev.get("net_name", "")).strip(),
        "phase": str(ev.get("phase", "")).strip(),
        "state": str(ev.get("state", "")).strip(),
        "reason": str(ev.get("reason", "")).strip(),
    }


def _sig(ev: dict[str, Any]) -> str:
    return f"{ev.get('phase','')}|{ev.get('state','')}|{ev.get('reason','')}"


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
        candidate_parts = candidate.split("_", 1)
        if len(candidate_parts) != 2:
            continue
        candidate_suffix = candidate_parts[1]
        if len(candidate_suffix) < 2 or candidate_suffix[0] != row_prefix:
            continue
        candidate_digits = candidate_suffix[1:]
        if not candidate_digits.isdigit():
            continue
        delta = abs(int(candidate_digits) - target_num)
        if best_delta is None or delta < best_delta or (delta == best_delta and candidate < best_name):
            best_name = candidate
            best_delta = delta
    return best_name or net_name


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fr-feature-dir", type=Path, required=True)
    ap.add_argument("--mojo-capture-json", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--watched-nets", type=str, default="")
    ap.add_argument("--watch-net", type=str, default="")
    args = ap.parse_args(argv)

    if args.out_dir is None and args.out_json is None:
        raise SystemExit("one of --out-dir or --out-json is required")
    if args.out_dir is not None and args.out_json is not None:
        raise SystemExit("use either --out-dir or --out-json, not both")

    out_json_path = (
        (args.out_dir.resolve() / "decision_divergence.json")
        if args.out_dir is not None
        else args.out_json.resolve()
    )
    fr_feature_summary = _load_json(args.fr_feature_dir.resolve() / "fr_feature_summary.json")
    fr_suite_summary_path = Path(str(fr_feature_summary["suite_summary_json"])).resolve()
    fr_suite_summary = _load_json(fr_suite_summary_path)
    fr_summaries = fr_suite_summary.get("summaries") or []
    if not isinstance(fr_summaries, list) or not fr_summaries:
        raise SystemExit(f"invalid FR suite summary: {fr_suite_summary_path}")
    fr_trace_path_text = str(fr_summaries[0].get("freerouting_trace_jsonl", "")).strip()
    if not fr_trace_path_text:
        raise SystemExit("FR trace JSONL path missing from suite summary")

    mojo_capture = _load_json(args.mojo_capture_json.resolve())
    mojo_trace_path = Path(str(mojo_capture.get("trace_jsonl", ""))).resolve()
    if not mojo_trace_path.exists():
        raise SystemExit(f"Mojo trace JSONL missing: {mojo_trace_path}")

    watched_nets = [x.strip() for x in args.watched_nets.split(",") if x.strip()]
    if not watched_nets and args.watch_net.strip():
        watched_nets = [args.watch_net.strip()]
    if not watched_nets:
        watched_nets = [str(x).strip() for x in mojo_capture.get("watched_nets", []) if str(x).strip()]

    fr_rows = [_normalize_fr_event(r) for r in _load_jsonl(Path(fr_trace_path_text).resolve())]
    mojo_rows = [_normalize_mojo_event(r) for r in _load_jsonl(mojo_trace_path)]
    fr_by_net = _group_by_net(fr_rows)
    mojo_by_net = _group_by_net([r for r in mojo_rows if not watched_nets or r["net_name"] in watched_nets])

    nets = watched_nets or sorted(set(fr_by_net) | set(mojo_by_net))
    rows: list[dict[str, Any]] = []
    improved_nets = 0
    for net in nets:
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
        divergence_class = "equal" if status == "equal" else _classify_divergence(fr_ev, mojo_ev)
        if status == "equal":
            improved_nets += 1
        rows.append(
            {
                "net_name": net,
                "status": status,
                "first_diff_index": first_diff,
                "fr_events": len(fr_net),
                "mojo_events": len(mojo_net),
                "divergence_class": divergence_class,
                "fr_event": fr_ev,
                "mojo_event": mojo_ev,
                "fr_net_name": fr_net_name,
                "fr_prefix": [_sig(ev) for ev in fr_net[:12]],
                "mojo_prefix": [_sig(ev) for ev in mojo_net[:12]],
            }
        )

    payload = {
        "watched_nets": nets,
        "fr_feature_dir": str(args.fr_feature_dir.resolve()),
        "fr_trace_jsonl": str(Path(fr_trace_path_text).resolve()),
        "mojo_capture_json": str(args.mojo_capture_json.resolve()),
        "mojo_trace_jsonl": str(mojo_trace_path),
        "nets_total": len(rows),
        "nets_equal": improved_nets,
        "nets_different": len(rows) - improved_nets,
        "rows": rows,
    }
    _write_json(out_json_path, payload)
    print(out_json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
