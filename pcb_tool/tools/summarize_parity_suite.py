#!/usr/bin/env python3
"""Summarize a `run_parity_suite.py` output directory.

Reads:
- `<suite_out>/suite_summary.json`
- per-fixture `<suite_out>/<fixture>/<fixture>.summary.json` (if present)
- per-fixture `<suite_out>/<fixture>/analysis.json` (if present)

Writes:
- `<suite_out>/suite_report.md`
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _top_items(d: dict[str, int] | None, n: int = 5) -> str:
    if not d:
        return ""
    items = list(d.items())[:n]
    return ", ".join([f"{k}:{v}" for k, v in items])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite-out", type=Path, required=True)
    args = ap.parse_args(argv)

    suite_out: Path = args.suite_out
    summary_path = suite_out / "suite_summary.json"
    if not summary_path.exists():
        raise SystemExit(f"missing {summary_path}")

    suite = _read_json(summary_path)
    rows = suite.get("rows") or []
    if not isinstance(rows, list):
        raise SystemExit("suite_summary.json invalid: rows not list")

    # Compute rankings
    def key_delta(r: dict[str, Any]) -> tuple[int, int, float]:
        # bigger = worse
        dv = int(r.get("mojo_violations", -1)) - int(r.get("freerouting_violations", -1))
        du = int(r.get("mojo_unconnected", -1)) - int(r.get("freerouting_unconnected", -1))
        sec = float(r.get("runtime_s", 0.0))
        return (dv, du, sec)

    ranked = sorted(rows, key=key_delta, reverse=True)

    md: list[str] = []
    md.append("# Parity suite report\n")
    md.append(f"- Suite out: `{suite_out}`")
    md.append(f"- Fixtures run: `{len(rows)}`")
    md.append(f"- Runtime: `{float(suite.get('runtime_s', 0.0)):.2f}s`\n")

    md.append("## Ranking (worst delta first)\n")
    md.append("| Fixture | FR v/u | Mojo v/u | Δv | Δu | Mojo failed | Top Mojo types | Top short pairs | Sec |")
    md.append("|---|---:|---:|---:|---:|---:|---|---|---:|")

    for r in ranked:
        fixture = str(r.get("fixture"))
        fr_v = int(r.get("freerouting_violations", -1))
        fr_u = int(r.get("freerouting_unconnected", -1))
        m_v = int(r.get("mojo_violations", -1))
        m_u = int(r.get("mojo_unconnected", -1))
        dv = m_v - fr_v if fr_v >= 0 else m_v
        du = m_u - fr_u if fr_u >= 0 else m_u
        failed = int(r.get("mojo_failed_nets", -1))
        sec = float(r.get("runtime_s", 0.0))

        analysis_path = suite_out / fixture / "analysis.json"
        mojo_types = ""
        mojo_pairs = ""
        if analysis_path.exists():
            a = _read_json(analysis_path)
            mojo = a.get("mojo") or {}
            mojo_types = _top_items(mojo.get("by_type"), 5)
            mojo_pairs = _top_items(mojo.get("by_pair"), 5)

        md.append(
            f"| {fixture} | {fr_v}/{fr_u} | {m_v}/{m_u} | {dv} | {du} | {failed} | {mojo_types} | {mojo_pairs} | {sec:.2f} |"
        )

    md.append("")
    md.append("## Per-fixture pointers\n")
    for r in ranked:
        fixture = str(r.get("fixture"))
        md.append(f"- `{fixture}/` (see `{fixture}/{fixture}.summary.json` and `{fixture}/analysis.md`)")

    out_path = suite_out / "suite_report.md"
    out_path.write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

