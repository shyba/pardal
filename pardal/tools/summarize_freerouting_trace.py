#!/usr/bin/env python3
"""Summarize FreeRouting decision trace NDJSON into compact per-net stats."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _net_key(ev: dict[str, Any]) -> str:
    name = str(ev.get("net_name", "")).strip()
    if name:
        return name
    net_no = ev.get("net_no")
    if isinstance(net_no, int):
        return f"#{net_no}"
    return "<unknown>"


def _summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "events": len(events),
        "phases": {},
        "states": {},
        "nets": {},
    }
    for ev in events:
        phase = str(ev.get("phase", "unknown"))
        state = str(ev.get("state", "unknown"))
        net = _net_key(ev)
        ts = ev.get("ts_ms")

        out["phases"][phase] = int(out["phases"].get(phase, 0)) + 1
        out["states"][state] = int(out["states"].get(state, 0)) + 1

        net_row = out["nets"].setdefault(
            net,
            {
                "events": 0,
                "phases": {},
                "states": {},
                "first_ts_ms": None,
                "last_ts_ms": None,
                "reasons": {},
            },
        )
        net_row["events"] += 1
        net_row["phases"][phase] = int(net_row["phases"].get(phase, 0)) + 1
        net_row["states"][state] = int(net_row["states"].get(state, 0)) + 1
        reason = str(ev.get("reason", "")).strip()
        if reason:
            net_row["reasons"][reason] = int(net_row["reasons"].get(reason, 0)) + 1
        if isinstance(ts, int):
            if net_row["first_ts_ms"] is None or ts < int(net_row["first_ts_ms"]):
                net_row["first_ts_ms"] = ts
            if net_row["last_ts_ms"] is None or ts > int(net_row["last_ts_ms"]):
                net_row["last_ts_ms"] = ts
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_trace", type=Path, required=True)
    ap.add_argument("--out", dest="out_json", type=Path, default=None)
    args = ap.parse_args(argv)

    in_trace = args.in_trace.resolve()
    if not in_trace.exists():
        raise SystemExit(f"trace file not found: {in_trace}")

    events = _load_events(in_trace)
    summary = _summarize(events)
    summary["trace_jsonl"] = str(in_trace)

    out_json = args.out_json.resolve() if args.out_json else in_trace.with_suffix(".summary.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(out_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
