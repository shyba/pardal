#!/usr/bin/env python3
"""Analyze a `run_parity_fixture.py` output directory.

Inputs:
- `<fixture>.summary.json` (required)
- `<fixture>.freerouting.kicad_pcb.drc.json` (optional)
- `<fixture>.mojo.kicad_pcb.drc.json` (optional)
- `*.ir_diff.*.json` (optional)

Outputs:
- `analysis.json` (machine-readable)
- `analysis.md` (human summary)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _drc_counts(drc: dict[str, Any]) -> dict[str, int]:
    v = drc.get("violations", []) or []
    u = drc.get("unconnected_items", []) or []
    return {"violations": len(v), "unconnected": len(u)}


def _violation_hist(drc: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in drc.get("violations", []) or []:
        t = v.get("type") or "unknown"
        out[t] = out.get(t, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _violation_net_hist(drc: dict[str, Any]) -> dict[str, int]:
    # KiCad DRC JSON doesn't always give a net, but when it does, we capture it.
    out: dict[str, int] = {}
    for v in drc.get("violations", []) or []:
        for k in ("net", "net_name", "netname"):
            net = v.get(k)
            if net:
                out[str(net)] = out.get(str(net), 0) + 1
                break
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

def _violation_pair_hist(drc: dict[str, Any]) -> dict[str, int]:
    # Useful for `shorting_items`: captures "SIG1 <> TMS" style pairs.
    out: dict[str, int] = {}
    for v in drc.get("violations", []) or []:
        items = v.get("items") or []
        nets: list[str] = []
        for it in items:
            desc = str(it.get("description") or "")
            # KiCad uses "... [NET] ..." in many descriptions.
            if "[" in desc and "]" in desc:
                frag = desc.split("[", 1)[1].split("]", 1)[0].strip()
                if frag:
                    nets.append(frag)
        if len(nets) >= 2:
            a, b = sorted(nets[:2])
            key = f"{a} <> {b}"
            out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _violation_hotspots(drc: dict[str, Any], *, limit: int = 30) -> list[dict[str, Any]]:
    """Extract frequent violation locations.

    Returns a list of {type, severity, x, y, count, examples[]} with coarse bucketing.
    """
    buckets: dict[tuple[str, str, int, int], dict[str, Any]] = {}
    for v in drc.get("violations", []) or []:
        vtype = str(v.get("type") or "unknown")
        sev = str(v.get("severity") or "")
        items = v.get("items") or []
        # Use first item's position as representative.
        pos = None
        for it in items:
            p = it.get("pos")
            if isinstance(p, dict) and "x" in p and "y" in p:
                pos = p
                break
        if not isinstance(pos, dict):
            continue
        try:
            x = float(pos["x"])
            y = float(pos["y"])
        except Exception:
            continue

        # Bucket to 0.5mm cells to de-noise.
        bx = int(round(x * 2))
        by = int(round(y * 2))
        key = (vtype, sev, bx, by)
        if key not in buckets:
            buckets[key] = {
                "type": vtype,
                "severity": sev,
                "x": bx / 2.0,
                "y": by / 2.0,
                "count": 0,
                "examples": [],
            }
        buckets[key]["count"] += 1
        if len(buckets[key]["examples"]) < 3:
            buckets[key]["examples"].append(str(v.get("description") or ""))

    rows = sorted(buckets.values(), key=lambda r: (-int(r["count"]), r["type"], r["severity"]))
    return rows[: max(1, int(limit))]


def _extract_violation_nets(v: dict[str, Any]) -> list[str]:
    # Try structured descriptions first.
    desc = str(v.get("description") or "")
    out: list[str] = []
    if "nets " in desc and " and " in desc:
        # "Items shorting two nets (nets SIG1 and TMS)"
        try:
            frag = desc.split("nets ", 1)[1]
            frag = frag.split(")", 1)[0]
            a, b = frag.split(" and ", 1)
            out.extend([a.strip(), b.strip()])
        except Exception:
            pass
    # Fall back to parsing bracketed "[NET]" from item descriptions.
    for it in v.get("items", []) or []:
        d = str(it.get("description") or "")
        if "[" in d and "]" in d:
            net = d.split("[", 1)[1].split("]", 1)[0].strip()
            if net and net not in out:
                out.append(net)
    return out


def _violation_samples(drc: dict[str, Any], *, limit: int = 25) -> list[dict[str, Any]]:
    """Return representative violations with UUIDs and positions for debugging."""
    out: list[dict[str, Any]] = []
    for v in drc.get("violations", []) or []:
        items = v.get("items", []) or []
        uuids: list[str] = []
        pos = None
        for it in items:
            uid = it.get("uuid")
            if uid and uid != "00000000-0000-0000-0000-000000000000":
                uuids.append(str(uid))
            p = it.get("pos")
            if pos is None and isinstance(p, dict) and "x" in p and "y" in p:
                pos = p
        sample = {
            "type": v.get("type") or "unknown",
            "severity": v.get("severity") or "",
            "description": v.get("description") or "",
            "nets": _extract_violation_nets(v),
            "pos": pos,
            "uuids": uuids[:4],
        }
        out.append(sample)
        if len(out) >= limit:
            break
    return out


def _ir_counts(path: Path) -> dict[str, int] | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    payload = _read_json(path)
    pins = payload.get("pin_positions_mm") or {}
    wiring = payload.get("wiring_mm") or {}
    wires = wiring.get("wires") or []
    vias = wiring.get("vias") or []
    return {
        "pins": len(pins) if isinstance(pins, dict) else -1,
        "wires": len(wires) if isinstance(wires, list) else -1,
        "vias": len(vias) if isinstance(vias, list) else -1,
    }


def _ir_wiring_index(path: Path) -> dict[str, Any] | None:
    """Build a coarse spatial index of wires/vias to map DRC hotspots to routed items."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    payload = _read_json(path)
    wiring = payload.get("wiring_mm") or {}
    wires = wiring.get("wires") or []
    vias = wiring.get("vias") or []
    if not isinstance(wires, list) or not isinstance(vias, list):
        return None

    # bucket to 0.5mm grid: int(round(mm*2))
    buckets: dict[tuple[int, int], dict[str, Any]] = {}

    def add(kind: str, x: float, y: float, obj: dict[str, Any]) -> None:
        bx = int(round(x * 2))
        by = int(round(y * 2))
        key = (bx, by)
        if key not in buckets:
            buckets[key] = {"wires": [], "vias": []}
        buckets[key][kind].append(obj)

    for w in wires:
        if not isinstance(w, dict):
            continue
        pts = w.get("points_mm") or w.get("points") or []
        if isinstance(pts, list) and pts:
            # points can be [{x,y},...] or [[x,y],...]
            for p in pts[:2] + pts[-2:]:
                try:
                    if isinstance(p, dict) and "x" in p and "y" in p:
                        add("wires", float(p["x"]), float(p["y"]), w)
                    elif isinstance(p, (list, tuple)) and len(p) >= 2:
                        add("wires", float(p[0]), float(p[1]), w)
                except Exception:
                    pass

    for v in vias:
        if not isinstance(v, dict):
            continue
        # via can be {x_mm,y_mm} or pos dict
        if "x_mm" in v and "y_mm" in v:
            try:
                add("vias", float(v["x_mm"]), float(v["y_mm"]), v)
                continue
            except Exception:
                pass
        p = v.get("pos_mm") or v.get("pos") or v.get("position")
        if isinstance(p, dict) and "x" in p and "y" in p:
            try:
                add("vias", float(p["x"]), float(p["y"]), v)
            except Exception:
                pass

    return {"path": str(path), "buckets": buckets}


def _hotspot_correlations(
    *,
    drc: dict[str, Any],
    ir_path: Path,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """For top hotspots, list nearby IR wire/via references."""
    idx = _ir_wiring_index(ir_path)
    if idx is None:
        return []

    # quick access
    buckets: dict[tuple[int, int], dict[str, Any]] = idx["buckets"]

    out: list[dict[str, Any]] = []
    for h in _violation_hotspots(drc, limit=limit):
        try:
            x = float(h["x"])
            y = float(h["y"])
            bx = int(round(x * 2))
            by = int(round(y * 2))
        except Exception:
            continue
        near: list[dict[str, Any]] = []
        # There are two common coordinate mismatches between KiCad DRC JSON and
        # DSN-derived IRs:
        # - Y axis sign flip
        # - unexpected scale factor (some KiCad outputs appear 10x smaller)
        # We try a small set of transforms and keep the one with most hits.
        def collect(cx: int, cy: int) -> list[dict[str, Any]]:
            found: list[dict[str, Any]] = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    key = (cx + dx, cy + dy)
                    if key in buckets:
                        b = buckets[key]
                        for w in b.get("wires", [])[:2]:
                            found.append({"kind": "wire", "net": w.get("net"), "layer": w.get("layer")})
                        for v in b.get("vias", [])[:2]:
                            found.append({"kind": "via", "net": v.get("net")})
            return found

        candidates: list[list[dict[str, Any]]] = []
        # (x,y)
        candidates.append(collect(bx, by))
        # (x,-y)
        candidates.append(collect(bx, int(round((-y) * 2))))
        # (10x, -10y)
        candidates.append(collect(int(round((x * 10) * 2)), int(round(((-y) * 10) * 2))))
        # (10x, 10y)
        candidates.append(collect(int(round((x * 10) * 2)), int(round((y * 10) * 2))))

        near = max(candidates, key=len) if candidates else []
        out.append(
            {
                "type": h.get("type"),
                "severity": h.get("severity"),
                "x": h.get("x"),
                "y": h.get("y"),
                "count": h.get("count"),
                "examples": h.get("examples") or [],
                "nearby": near,
            }
        )
    return out


@dataclass(frozen=True)
class Side:
    name: str
    drc_path: str
    counts: dict[str, int] | None
    violations_by_type: dict[str, int] | None
    violations_by_net: dict[str, int] | None
    violations_by_pair: dict[str, int] | None
    hotspots: list[dict[str, Any]] | None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True, help="Directory used as --out-dir for run_parity_fixture.py")
    ap.add_argument("--fixture", type=str, default=None, help="Fixture name; inferred from *.summary.json if omitted")
    args = ap.parse_args(argv)

    out_dir: Path = args.out_dir
    if not out_dir.exists():
        raise SystemExit(f"missing out-dir: {out_dir}")

    summary_paths = sorted(out_dir.glob("*.summary.json"))
    if args.fixture:
        summary_paths = [out_dir / f"{args.fixture}.summary.json"]
    if not summary_paths or not summary_paths[0].exists():
        raise SystemExit("missing <fixture>.summary.json in out-dir")

    summary = _read_json(summary_paths[0])
    fixture = str(args.fixture or summary.get("fixture") or summary_paths[0].stem.replace(".summary", ""))

    fr_drc_path = out_dir / f"{fixture}.freerouting.kicad_pcb.drc.json"
    mojo_drc_path = out_dir / f"{fixture}.mojo.kicad_pcb.drc.json"

    fr = None
    if fr_drc_path.exists():
        fr_payload = _read_json(fr_drc_path)
        fr_corr = _hotspot_correlations(drc=fr_payload, ir_path=(out_dir / f"{fixture}.freerouting.kicad.dsn.ir.json"))
        fr = Side(
            name="freerouting",
            drc_path=str(fr_drc_path),
            counts=_drc_counts(fr_payload),
            violations_by_type=_violation_hist(fr_payload),
            violations_by_net=_violation_net_hist(fr_payload),
            violations_by_pair=_violation_pair_hist(fr_payload),
            hotspots=fr_corr or _violation_hotspots(fr_payload),
        )

    mojo = None
    if mojo_drc_path.exists():
        mojo_payload = _read_json(mojo_drc_path)
        mojo_corr = _hotspot_correlations(drc=mojo_payload, ir_path=(out_dir / f"{fixture}.mojo.kicad.dsn.ir.json"))
        mojo = Side(
            name="mojo",
            drc_path=str(mojo_drc_path),
            counts=_drc_counts(mojo_payload),
            violations_by_type=_violation_hist(mojo_payload),
            violations_by_net=_violation_net_hist(mojo_payload),
            violations_by_pair=_violation_pair_hist(mojo_payload),
            hotspots=mojo_corr or _violation_hotspots(mojo_payload),
        )

    ir = {
        "kicad": _ir_counts(out_dir / f"{fixture}.kicad.dsn.ir.json"),
        "freerouting_output": _ir_counts(out_dir / f"{fixture}.freerouting.kicad.dsn.ir.json"),
        "mojo_output": _ir_counts(out_dir / f"{fixture}.mojo.kicad.dsn.ir.json"),
    }

    analysis = {
        "fixture": fixture,
        "out_dir": str(out_dir),
        "summary": summary,
        "freerouting": None
        if fr is None
        else {
            "drc_path": fr.drc_path,
            "counts": fr.counts,
            "by_type": fr.violations_by_type,
            "by_pair": fr.violations_by_pair,
            "hotspots": fr.hotspots,
        },
        "mojo": None
        if mojo is None
        else {
            "drc_path": mojo.drc_path,
            "counts": mojo.counts,
            "by_type": mojo.violations_by_type,
            "by_pair": mojo.violations_by_pair,
            "hotspots": mojo.hotspots,
        },
        "ir_counts": ir,
        "mojo_violation_samples": _violation_samples(_read_json(mojo_drc_path)) if mojo_drc_path.exists() else [],
    }

    (out_dir / "analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True), encoding="utf-8")

    md_lines: list[str] = []
    md_lines.append(f"# Parity analysis: `{fixture}`\n")
    md_lines.append(f"- Out dir: `{out_dir}`")
    if fr is not None:
        md_lines.append(f"- FreeRouting DRC: `{fr_drc_path.name}` violations={fr.counts['violations']} unconnected={fr.counts['unconnected']}")
    if mojo is not None:
        md_lines.append(f"- Mojo DRC: `{mojo_drc_path.name}` violations={mojo.counts['violations']} unconnected={mojo.counts['unconnected']}")
    md_lines.append("")

    md_lines.append("## IR counts\n")
    md_lines.append("| Source | Pins | Wires | Vias |")
    md_lines.append("|---|---:|---:|---:|")
    for k, v in ir.items():
        if v is None:
            md_lines.append(f"| {k} |  |  |  |")
        else:
            md_lines.append(f"| {k} | {v['pins']} | {v['wires']} | {v['vias']} |")
    md_lines.append("")

    if mojo is not None and mojo.violations_by_type:
        md_lines.append("## Mojo violations by type\n")
        md_lines.append("| Type | Count |")
        md_lines.append("|---|---:|")
        for t, c in list(mojo.violations_by_type.items())[:25]:
            md_lines.append(f"| {t} | {c} |")
        md_lines.append("")

    if mojo is not None and mojo.violations_by_pair:
        pairs = [(k, v) for k, v in mojo.violations_by_pair.items() if v > 0]
        if pairs:
            md_lines.append("## Mojo short pairs (from DRC items)\n")
            md_lines.append("| Pair | Count |")
            md_lines.append("|---|---:|")
            for p, c in pairs[:25]:
                md_lines.append(f"| {p} | {c} |")
            md_lines.append("")

    if mojo is not None and mojo.hotspots:
        md_lines.append("## Mojo hotspots (bucketed positions)\n")
        md_lines.append("| Type | Severity | X(mm) | Y(mm) | Count | Examples |")
        md_lines.append("|---|---|---:|---:|---:|---|")
        for h in mojo.hotspots[:25]:
            ex_list = [e for e in h.get("examples", []) if e]
            ex = "; ".join(ex_list)[:160] if ex_list else ""
            near = h.get("nearby") or []
            if near:
                # Compact hints: "wire:NET@LAYER"
                hints = []
                for n in near[:6]:
                    if n.get("kind") == "wire":
                        hints.append(f"wire:{n.get('net','')}@{n.get('layer','')}")
                    else:
                        hints.append(f"via:{n.get('net','')}")
                ex = (ex + " | " if ex else "") + ",".join(hints)
            md_lines.append(
                f"| {h.get('type','')} | {h.get('severity','')} | {h.get('x','')} | {h.get('y','')} | {h.get('count','')} | {ex} |"
            )
        md_lines.append("")

    if mojo_drc_path.exists():
        md_lines.append("## Mojo sample violations (first N)\n")
        md_lines.append("| Type | X(mm) | Y(mm) | Nets | UUIDs | Description |")
        md_lines.append("|---|---:|---:|---|---|---|")
        for s in analysis.get("mojo_violation_samples", [])[:25]:
            pos = s.get("pos") or {}
            try:
                x = float(pos.get("x"))
                y = float(pos.get("y"))
            except Exception:
                x = ""
                y = ""
            nets = ",".join([n for n in (s.get("nets") or []) if n is not None])
            uuids = ",".join([u for u in (s.get("uuids") or []) if u])
            desc = str(s.get("description") or "")
            desc = desc.replace("\n", " ").strip()
            md_lines.append(f"| {s.get('type','')} | {x} | {y} | {nets} | {uuids} | {desc[:160]} |")
        md_lines.append("")

    if fr is not None and fr.violations_by_type:
        md_lines.append("## FreeRouting violations by type\n")
        md_lines.append("| Type | Count |")
        md_lines.append("|---|---:|")
        for t, c in list(fr.violations_by_type.items())[:25]:
            md_lines.append(f"| {t} | {c} |")
        md_lines.append("")

    (out_dir / "analysis.md").write_text("\n".join(md_lines).strip() + "\n", encoding="utf-8")
    print(out_dir / "analysis.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
