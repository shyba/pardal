#!/usr/bin/env python3
"""Extract UUIDs/positions from a KiCad DRC JSON for fast debugging.

Given a DRC JSON (KiCad 9 `kicad-cli pcb drc --format json`) this outputs:
- a ranked list of item UUIDs involved in many violations
- net-pair summary for `shorting_items`
- a short CSV-like text for quick copy/paste into scripts

This is meant to be used on parity fixture outputs to jump to the worst spots.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _extract_uuid_items(v: dict[str, Any]) -> list[dict[str, Any]]:
    items = v.get("items", []) or []
    out: list[dict[str, Any]] = []
    for it in items:
        uid = it.get("uuid")
        if not uid or uid == "00000000-0000-0000-0000-000000000000":
            continue
        pos = it.get("pos")
        if not isinstance(pos, dict):
            pos = None
        out.append(
            {
                "uuid": str(uid),
                "pos": pos,
                "desc": str(it.get("description") or ""),
            }
        )
    return out


def _net_pair(v: dict[str, Any]) -> str | None:
    desc = str(v.get("description") or "")
    if "nets " in desc and " and " in desc:
        try:
            frag = desc.split("nets ", 1)[1]
            frag = frag.split(")", 1)[0]
            a, b = frag.split(" and ", 1)
            return " <> ".join(sorted([a.strip(), b.strip()]))
        except Exception:
            return None
    # Heuristic fallback for truncated descriptions like "(nets GND,Net-(C8-Pad2"
    if "nets " in desc:
        try:
            frag = desc.split("nets ", 1)[1]
            frag = frag.split(")", 1)[0]
            frag = frag.strip()
            # Split on comma when present.
            if "," in frag:
                a, b = frag.split(",", 1)
                return " <> ".join(sorted([a.strip(), b.strip()]))
        except Exception:
            return None
    return None


@dataclass(frozen=True)
class UuidScore:
    uuid: str
    count: int
    types: dict[str, int]
    example_pos: dict[str, float] | None
    example_desc: str


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--drc-json", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args(argv)

    drc = _read_json(args.drc_json)
    violations = drc.get("violations", []) or []

    uuid_map: dict[str, dict[str, Any]] = {}
    pair_map: dict[str, int] = {}

    for v in violations:
        vtype = str(v.get("type") or "unknown")
        pair = _net_pair(v)
        if pair:
            pair_map[pair] = pair_map.get(pair, 0) + 1
        for it in _extract_uuid_items(v):
            uid = it["uuid"]
            if uid not in uuid_map:
                uuid_map[uid] = {"count": 0, "types": {}, "pos": it.get("pos"), "desc": it.get("desc") or ""}
            uuid_map[uid]["count"] += 1
            tmap = uuid_map[uid]["types"]
            tmap[vtype] = tmap.get(vtype, 0) + 1

    scores: list[UuidScore] = []
    for uid, info in uuid_map.items():
        scores.append(
            UuidScore(
                uuid=uid,
                count=int(info["count"]),
                types=dict(sorted(info["types"].items(), key=lambda kv: (-kv[1], kv[0]))),
                example_pos=info.get("pos"),
                example_desc=str(info.get("desc") or ""),
            )
        )
    scores.sort(key=lambda s: s.count, reverse=True)
    scores = scores[: max(1, int(args.limit))]

    args.out_dir.mkdir(parents=True, exist_ok=True)

    out_json = {
        "drc_json": str(args.drc_json),
        "uuid_scores": [
            {
                "uuid": s.uuid,
                "count": s.count,
                "types": s.types,
                "pos": s.example_pos,
                "example_desc": s.example_desc,
            }
            for s in scores
        ],
        "net_pairs": dict(sorted(pair_map.items(), key=lambda kv: (-kv[1], kv[0]))),
    }
    (args.out_dir / "uuid_targets.json").write_text(json.dumps(out_json, indent=2, sort_keys=True), encoding="utf-8")

    md: list[str] = []
    md.append(f"# UUID targets\n")
    md.append(f"- DRC JSON: `{args.drc_json}`\n")
    md.append("## Top UUIDs\n")
    md.append("| Rank | UUID | Count | Top types | Example (x,y) |")
    md.append("|---:|---|---:|---|---|")
    for i, s in enumerate(scores, start=1):
        types = ", ".join([f"{k}:{v}" for k, v in list(s.types.items())[:4]])
        pos = s.example_pos or {}
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            xy = f"{pos.get('x')},{pos.get('y')}"
        else:
            xy = ""
        md.append(f"| {i} | {s.uuid} | {s.count} | {types} | {xy} |")
    md.append("")

    if pair_map:
        md.append("## Top net pairs (shorting_items)\n")
        md.append("| Pair | Count |")
        md.append("|---|---:|")
        for k, v in list(sorted(pair_map.items(), key=lambda kv: (-kv[1], kv[0])))[:25]:
            md.append(f"| {k} | {v} |")
        md.append("")

    # CSV-ish quick list: uuid,x,y
    md.append("## Copy/paste list\n")
    md.append("```")
    for s in scores:
        pos = s.example_pos or {}
        x = pos.get("x") if isinstance(pos, dict) else ""
        y = pos.get("y") if isinstance(pos, dict) else ""
        md.append(f"{s.uuid},{x},{y}")
    md.append("```")
    md.append("")

    (args.out_dir / "uuid_targets.md").write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    print(args.out_dir / "uuid_targets.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
