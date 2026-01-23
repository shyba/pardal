#!/usr/bin/env python3
"""Summarize FreeRouting oracle baselines in `parity_fixtures/baselines/`.

Prints counts and writes a JSON summary if requested.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class BaselineRow:
    fixture_type: str
    fixture_relpath: str
    fixture_id: str
    oracle_ok: bool
    oracle_error: str | None
    violations: int
    unconnected: int


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baselines-root", type=Path, default=Path("parity_fixtures/baselines"))
    ap.add_argument("--out", type=Path, default=None, help="Write JSON summary here.")
    args = ap.parse_args(argv)

    root = args.baselines_root
    if not root.exists():
        raise SystemExit(f"missing baselines root: {root}")

    rows: list[BaselineRow] = []
    for p in sorted(root.rglob("baseline.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        drc = d.get("drc") or {}
        rows.append(
            BaselineRow(
                fixture_type=str(d.get("fixture_type", "?")),
                fixture_relpath=str(d.get("fixture_relpath", "?")),
                fixture_id=str(d.get("fixture_id", p.parent.name)),
                oracle_ok=bool(d.get("oracle_ok", True)),
                oracle_error=d.get("oracle_error"),
                violations=int(drc.get("violations", 0)),
                unconnected=int(drc.get("unconnected", 0)),
            )
        )

    total = len(rows)
    ok = sum(1 for r in rows if r.oracle_ok)
    fail = total - ok
    dsn = sum(1 for r in rows if r.fixture_type == "dsn")
    kicad = sum(1 for r in rows if r.fixture_type == "kicad")

    print(f"baselines: total={total} ok={ok} fail={fail} dsn={dsn} kicad={kicad}")
    if fail:
        print("oracle_failures:")
        for r in rows:
            if r.oracle_ok:
                continue
            print(f"- {r.fixture_relpath}: {r.oracle_error}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "summary": {"total": total, "ok": ok, "fail": fail, "dsn": dsn, "kicad": kicad},
            "rows": [asdict(r) for r in rows],
        }
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

