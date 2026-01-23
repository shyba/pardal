#!/usr/bin/env python3
"""Generate a prioritized TODO list from a parity suite run.

This tool turns `suite_report.md` / per-fixture `analysis.json` into a compact,
execution-ordered triage list that can be pasted into the parity plan.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


@dataclass(frozen=True)
class Item:
    fixture: str
    score: float
    mojo_v: int
    mojo_u: int
    fr_v: int
    fr_u: int
    mojo_failed: int
    top_types: list[tuple[str, int]]
    top_pairs: list[tuple[str, int]]


def _top(d: dict[str, int] | None, n: int = 5) -> list[tuple[str, int]]:
    if not d:
        return []
    return list(d.items())[:n]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite-out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args(argv)

    suite_out: Path = args.suite_out
    suite_summary = suite_out / "suite_summary.json"
    if not suite_summary.exists():
        raise SystemExit(f"missing {suite_summary}")

    suite = _read_json(suite_summary)
    rows = suite.get("rows") or []
    if not isinstance(rows, list):
        raise SystemExit("suite_summary.json invalid: rows not list")

    items: list[Item] = []
    for r in rows:
        fixture = str(r.get("fixture"))
        fr_v = int(r.get("freerouting_violations", -1))
        fr_u = int(r.get("freerouting_unconnected", -1))
        mojo_v = int(r.get("mojo_violations", -1))
        mojo_u = int(r.get("mojo_unconnected", -1))
        mojo_failed = int(r.get("mojo_failed_nets", -1))

        analysis_path = suite_out / fixture / "analysis.json"
        top_types: list[tuple[str, int]] = []
        top_pairs: list[tuple[str, int]] = []
        if analysis_path.exists():
            a = _read_json(analysis_path)
            mojo = a.get("mojo") or {}
            top_types = _top(mojo.get("by_type"), 6)
            top_pairs = _top(mojo.get("by_pair"), 6)

        dv = (mojo_v - fr_v) if fr_v >= 0 else mojo_v
        du = (mojo_u - fr_u) if fr_u >= 0 else mojo_u
        # Score emphasizes "badness": violations dominate, then unconnected, then failed nets.
        score = float(dv) + (10.0 * float(du)) + (5.0 * float(max(0, mojo_failed)))

        items.append(
            Item(
                fixture=fixture,
                score=score,
                mojo_v=mojo_v,
                mojo_u=mojo_u,
                fr_v=fr_v,
                fr_u=fr_u,
                mojo_failed=mojo_failed,
                top_types=top_types,
                top_pairs=top_pairs,
            )
        )

    items.sort(key=lambda i: i.score, reverse=True)
    items = items[: max(1, int(args.limit))]

    md: list[str] = []
    md.append("## Triage TODOs (auto-generated)\n")
    md.append(f"Source suite: `{suite_out}`\n")
    md.append("| Priority | Fixture | FR v/u | Mojo v/u | Δv | Δu | Mojo failed | Focus (types) | Focus (pairs) |")
    md.append("|---:|---|---:|---:|---:|---:|---:|---|---|")
    for idx, it in enumerate(items, start=1):
        dv = it.mojo_v - it.fr_v if it.fr_v >= 0 else it.mojo_v
        du = it.mojo_u - it.fr_u if it.fr_u >= 0 else it.mojo_u
        types = ", ".join([f"{k}:{v}" for k, v in it.top_types]) if it.top_types else ""
        pairs = ", ".join([f"{k}:{v}" for k, v in it.top_pairs]) if it.top_pairs else ""
        md.append(
            f"| {idx} | {it.fixture} | {it.fr_v}/{it.fr_u} | {it.mojo_v}/{it.mojo_u} | {dv} | {du} | {it.mojo_failed} | {types} | {pairs} |"
        )

    md.append("")
    md.append("### Per-fixture actions\n")
    for it in items:
        md.append(f"- `{it.fixture}`")
        md.append(f"  - Open `{suite_out}/{it.fixture}/analysis.md` and start with the top violation types above.")
        md.append(f"  - Run `{Path('pardal-pcb')/'pcb_tool'/'tools'/'analyze_parity_run.py'}` on the fixture out-dir after each change to track movement.")
        if it.top_pairs:
            md.append("  - For the top short pairs, find the exact offending items in the KiCad DRC JSON and map them back to routed segments via the IR wiring.")
        if it.mojo_failed > 0:
            md.append("  - Investigate failed nets first (they tend to cause secondary DRC cascades).")
        md.append("  - Prefer routing-semantic fixes over silkscreen/library noise (ignore `lib_footprint_*`, `text_height`, etc. when prioritizing).")
    md.append("")

    out_path = suite_out / "triage_todos.md"
    out_path.write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
