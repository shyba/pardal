#!/usr/bin/env python3
"""Render `parity_out/mojo_vs_baseline_suite.json` into a Markdown report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--in", dest="in_path", type=Path, default=Path("parity_out/mojo_vs_baseline_suite.json"))
    ap.add_argument("--out", dest="out_path", type=Path, default=Path("parity_out/mojo_vs_baseline_suite.md"))
    ap.add_argument("--top", type=int, default=10, help="Show top N worst deltas")
    args = ap.parse_args(argv)

    data = json.loads(args.in_path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []

    def score(r: dict) -> tuple[int, int]:
        bv, bu = r.get("baseline_v"), r.get("baseline_u")
        mv, mu = r.get("mojo_v"), r.get("mojo_u")
        if None in (bv, bu, mv, mu):
            return (10**9, 10**9)
        return (abs(int(mu) - int(bu)), abs(int(mv) - int(bv)))

    worst = sorted(rows, key=score, reverse=True)[: int(args.top)]

    timed_out = [r for r in rows if int(r.get("exit_code", 0)) == 124]
    diffs = [r for r in rows if int(r.get("exit_code", 0)) == 1]
    oks = [r for r in rows if int(r.get("exit_code", 0)) == 0]

    lines: list[str] = []
    lines.append("# Mojo vs KiCad Baseline Suite\n")
    lines.append(f"- Input: `{args.in_path}`\n")
    lines.append(f"- Total fixtures: {data.get('summary', {}).get('total')}\n")
    lines.append(f"- OK: {len(oks)}  Diff: {len(diffs)}  Timeouts(killed): {len(timed_out)}\n")
    lines.append("\n## Worst deltas (by |Δunconnected|, |Δviolations|)\n")
    lines.append("| Fixture | Baseline (v/u) | Mojo (v/u) | Δv | Δu | Runtime (s) | Exit |\n")
    lines.append("|---|---:|---:|---:|---:|---:|---:|\n")
    for r in worst:
        name = Path(r["fixture"]).name
        bv, bu = r.get("baseline_v"), r.get("baseline_u")
        mv, mu = r.get("mojo_v"), r.get("mojo_u")
        dv = du = ""
        if None not in (bv, bu, mv, mu):
            dv = f"{int(mv) - int(bv):+d}"
            du = f"{int(mu) - int(bu):+d}"
        lines.append(
            f"| `{name}` | {bv}/{bu} | {mv}/{mu} | {dv} | {du} | {r.get('runtime_s'):.1f} | {r.get('exit_code')} |\n"
        )

    if timed_out:
        lines.append("\n## Timed out fixtures (killed)\n")
        for r in timed_out:
            lines.append(f"- `{r['fixture']}` (baseline {r.get('baseline_v')}/{r.get('baseline_u')})\n")

    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    args.out_path.write_text("".join(lines), encoding="utf-8")
    print(f"wrote: {args.out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

