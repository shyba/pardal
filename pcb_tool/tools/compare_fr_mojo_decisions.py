#!/usr/bin/env python3
"""Compare decision-event streams and report first divergence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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


def _event_key(ev: dict[str, Any]) -> tuple[Any, ...]:
    net = ev.get("net_name")
    if not isinstance(net, str) or not net.strip():
        net_no = ev.get("net_no")
        net = f"#{net_no}" if isinstance(net_no, int) else "<unknown>"
    return (
        ev.get("pass_no"),
        net,
        ev.get("phase"),
        ev.get("state"),
    )


def _first_divergence(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    n = min(len(a), len(b))
    for i in range(n):
        ka = _event_key(a[i])
        kb = _event_key(b[i])
        if ka != kb:
            return {
                "index": i,
                "a_key": ka,
                "b_key": kb,
                "a_event": a[i],
                "b_event": b[i],
            }
    if len(a) != len(b):
        return {
            "index": n,
            "a_key": _event_key(a[n]) if len(a) > n else None,
            "b_key": _event_key(b[n]) if len(b) > n else None,
            "a_event": a[n] if len(a) > n else None,
            "b_event": b[n] if len(b) > n else None,
        }
    return {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--a", type=Path, required=True, help="First decision stream (JSONL).")
    ap.add_argument("--b", type=Path, required=True, help="Second decision stream (JSONL).")
    ap.add_argument("--out", type=Path, default=None, help="Output JSON path.")
    args = ap.parse_args(argv)

    a_path = args.a.resolve()
    b_path = args.b.resolve()
    if not a_path.exists():
        raise SystemExit(f"missing --a: {a_path}")
    if not b_path.exists():
        raise SystemExit(f"missing --b: {b_path}")

    a_rows = _load_jsonl(a_path)
    b_rows = _load_jsonl(b_path)
    divergence = _first_divergence(a_rows, b_rows)

    payload = {
        "a": str(a_path),
        "b": str(b_path),
        "a_events": len(a_rows),
        "b_events": len(b_rows),
        "identical_prefix": divergence == {},
        "first_divergence": divergence,
    }

    out_path = args.out.resolve() if args.out else a_path.with_suffix(".vs_b.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
