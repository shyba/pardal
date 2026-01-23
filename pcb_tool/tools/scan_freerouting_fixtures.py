#!/usr/bin/env python3
"""Scan `freerouting/tests/` and emit a JSON manifest of fixtures.

This keeps the parity plan "mechanical": callers can iterate a fixed list,
diff it across time, and use it to drive baseline/oracle jobs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    workspace_root = Path(__file__).resolve().parents[3]
    tests_root = workspace_root / "freerouting" / "tests"

    fixtures: list[dict[str, str]] = []
    for p in sorted(tests_root.rglob("*")):
        if p.name.startswith("._"):
            continue
        if "__MACOSX" in p.parts:
            continue
        if p.suffix.lower() == ".dsn":
            fixtures.append({"type": "dsn", "path": str(p.relative_to(workspace_root))})
        elif p.suffix.lower() == ".kicad_pcb":
            fixtures.append({"type": "kicad", "path": str(p.relative_to(workspace_root))})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixtures, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(fixtures)} fixtures -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

