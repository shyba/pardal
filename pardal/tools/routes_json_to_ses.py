#!/usr/bin/env python3
"""Convert `routes.json` (from pardal Mojo backend-route) into a Specctra SES.

This is a Phase-1 parity primitive:
- It lets us compare against FreeRouting outputs in the same interchange format.
- It enables applying Mojo routes via `pcbnew.ImportSpecctraSES(...)` in KiCad docker.

Scope: minimal SES sufficient for KiCad import.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


_PCB_NAME_RE = re.compile(r"^\s*\(\s*pcb\s+([^\s\)]+)", re.IGNORECASE | re.MULTILINE)
_RES_RE = re.compile(r"^\s*\(\s*resolution\s+([^\s\)]+)\s+([0-9]+)", re.IGNORECASE | re.MULTILINE)
_PLACE_RE = re.compile(
    r"\(\s*place\s+([^\s\)]+)\s+([0-9\.\-]+)\s+([0-9\.\-]+)\s+(front|back)\s+([0-9\.\-]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DsnMeta:
    pcb_name: str
    unit_name: str
    div: int


def _read_dsn_meta(dsn: Path) -> DsnMeta:
    src = dsn.read_text(encoding="utf-8", errors="replace")
    m = _PCB_NAME_RE.search(src)
    if not m:
        raise ValueError("DSN missing (pcb NAME ...) header")
    pcb_name = m.group(1)
    m2 = _RES_RE.search(src)
    if not m2:
        raise ValueError("DSN missing (resolution <unit> <div>)")
    unit_name = m2.group(1)
    div = int(m2.group(2))
    return DsnMeta(pcb_name=pcb_name, unit_name=unit_name, div=div)

def _extract_balanced_block(src: str, head: str) -> str | None:
    """Return the substring of the first '(head ...)' S-expression (balanced, string-aware)."""
    m = re.search(rf"\(\s*{re.escape(head)}\b", src)
    if not m:
        return None
    i = m.start()
    n = len(src)
    depth = 0
    in_string = False
    escape = False
    j = i
    while j < n:
        c = src[j]
        if in_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            j += 1
            continue
        if c == '"':
            in_string = True
            j += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
        j += 1
    return None


def _replace_balanced_block(src: str, head: str, new_block: str) -> str:
    block = _extract_balanced_block(src, head)
    if block is None:
        raise ValueError(f"missing ({head} ...) block in template")
    start = src.find(block)
    if start < 0:
        raise ValueError(f"failed to locate ({head} ...) block")
    end = start + len(block)
    return src[:start] + new_block + src[end:]


def _placement_from_dsn(src: str, *, unit_name: str, div: int) -> str:
    """Extract DSN placement and convert `(place ...)` coords into SES integers."""
    block = _extract_balanced_block(src, "placement")
    if not block:
        return _emit("(placement", indent=1) + _emit(f"(resolution {unit_name} {div})", indent=2) + _emit(")", indent=1)

    def repl(m: re.Match[str]) -> str:
        ref = m.group(1)
        x = float(m.group(2))
        y = float(m.group(3))
        side = m.group(4)
        rot = float(m.group(5))
        # DSN placement coords are in "um" base units; SES uses "um*div".
        xi = int(round(x * float(div)))
        yi = int(round(y * float(div)))
        ri = int(round(rot))
        return f"(place {ref} {xi} {yi} {side} {ri}"

    # Strip any (PN ...) trailing list in place entries (KiCad adds it).
    out = _PLACE_RE.sub(repl, block)
    out = re.sub(r"\(PN\s+[^\)]+\)", "", out)
    # Prepend resolution line like FreeRouting SES does.
    # Replace first "(placement" with "(placement\n  (resolution ...)".
    out = re.sub(
        r"^\(\s*placement\b",
        f"(placement\n  (resolution {unit_name} {div})",
        out,
        flags=re.IGNORECASE,
    )
    return out + "\n"


def _mm_to_dsn_int(mm: float, *, unit_name: str, div: int) -> int:
    # KiCad DSNs in this repo predominantly use: (resolution um 10)
    # Meaning: coordinates are in units of `div` micrometers.
    if unit_name.lower() != "um":
        raise ValueError(f"Unsupported DSN unit for SES writing: {unit_name!r}")
    # DSN/SES convention (as used by KiCad+FreeRouting here):
    # (resolution um 10) means "1/10 um" coordinate grid, i.e. 0.1um.
    # Therefore: mm -> um -> (um * div).
    return int(round(mm * 1000.0 * float(div)))


def _emit(*parts: str, indent: int = 0) -> str:
    return ("  " * indent) + "".join(parts) + "\n"


def _padstack_name(v: dict) -> str:
    # Example FreeRouting naming: Via[0-3]_600:300_um
    layers = v.get("layers") or []
    size_mm = float(v.get("size_mm") or 0.0)
    drill_mm = float(v.get("drill_mm") or 0.0)
    # Best-effort span indices from layer names: F.Cu=0, B.Cu=last.
    # For now just use 0-(len(layers)-1) as span token; KiCad seems tolerant if
    # the padstack shapes are correct for the layers we emit.
    a = 0
    b = max(0, len(layers) - 1)
    size_um = int(round(size_mm * 1000.0))
    drill_um = int(round(drill_mm * 1000.0))
    return f"Via[{a}-{b}]_{size_um}:{drill_um}_um"


def routes_to_ses(
    *,
    dsn: Path,
    routes_json: Path,
    out_ses: Path,
    host: str = "pardal",
    template_ses: Path | None = None,
) -> None:
    dsn_src = dsn.read_text(encoding="utf-8", errors="replace")
    meta = _read_dsn_meta(dsn)
    payload = json.loads(routes_json.read_text(encoding="utf-8", errors="replace"))
    tracks = payload.get("tracks") or []
    vias = payload.get("vias") or []

    # Group wires per net.
    wires_by_net: dict[str, list[dict]] = {}
    for t in tracks:
        net = str(t.get("net") or "")
        if not net:
            continue
        wires_by_net.setdefault(net, []).append(t)

    # Collect unique via padstacks.
    via_defs: dict[str, dict] = {}
    for v in vias:
        name = _padstack_name(v)
        via_defs.setdefault(name, v)

    out_ses.parent.mkdir(parents=True, exist_ok=True)

    # Build new `network_out` block.
    net_out_lines: list[str] = []
    net_out_lines.append(_emit("(network_out ", indent=2).rstrip("\n") + "\n")
    for net, ws in sorted(wires_by_net.items()):
        if any(c.isspace() for c in net) or any(c in '()"' for c in net):
            net_atom = '"' + net.replace('"', '\\"') + '"'
        else:
            net_atom = net
        net_out_lines.append(_emit("(net ", net_atom, indent=3))
        for w in ws:
            layer = str(w.get("layer") or "F.Cu")
            width_mm = float(w.get("width_mm") or 0.2)
            width = int(round(width_mm * 1000.0 * float(meta.div)))  # (um * div)
            (sx, sy) = w.get("start_mm") or (0.0, 0.0)
            (ex, ey) = w.get("end_mm") or (0.0, 0.0)
            sx_i = _mm_to_dsn_int(float(sx), unit_name=meta.unit_name, div=meta.div)
            sy_i = _mm_to_dsn_int(-float(sy), unit_name=meta.unit_name, div=meta.div)
            ex_i = _mm_to_dsn_int(float(ex), unit_name=meta.unit_name, div=meta.div)
            ey_i = _mm_to_dsn_int(-float(ey), unit_name=meta.unit_name, div=meta.div)
            net_out_lines.append(_emit("(wire", indent=4))
            net_out_lines.append(_emit("(path ", layer, " ", str(width), indent=5))
            net_out_lines.append(_emit(f"{sx_i} {sy_i}", indent=6))
            net_out_lines.append(_emit(f"{ex_i} {ey_i}", indent=6))
            net_out_lines.append(_emit(")", indent=5))
            net_out_lines.append(_emit(")", indent=4))
        net_out_lines.append(_emit(")", indent=3))
    net_out_lines.append(_emit(")", indent=2))
    network_out_block = "".join(net_out_lines)

    if template_ses is not None:
        src = template_ses.read_text(encoding="utf-8", errors="replace")
        # Replace the existing network_out with our generated one.
        out_txt = _replace_balanced_block(src, "network_out", network_out_block.strip() + "\n")
        out_ses.write_text(out_txt, encoding="utf-8")
        return

    # Fallback: emit a standalone SES (best-effort).
    buf: list[str] = []
    buf.append(_emit("(session freerouting", indent=0))
    buf.append(_emit("(base_design freerouting)", indent=1))
    buf.append(_placement_from_dsn(dsn_src, unit_name=meta.unit_name, div=meta.div))
    buf.append(_emit("(was_is", indent=1))
    buf.append(_emit(")", indent=1))
    buf.append(_emit("(routes ", indent=1))
    buf.append(_emit("(resolution ", meta.unit_name, " ", str(meta.div), ")", indent=2))
    buf.append(_emit("(parser", indent=2))
    buf.append(_emit("(host_cad \"KiCad's Pcbnew\")", indent=3))
    buf.append(_emit("(host_version 9.0.6)", indent=3))
    buf.append(_emit(")", indent=2))

    if via_defs:
        buf.append(_emit("(library_out", indent=2))
        for name, v in sorted(via_defs.items()):
            layers = v.get("layers") or []
            size_mm = float(v.get("size_mm") or 0.0)
            # SES wants diameter in DSN units; KiCad-exported DSN uses um.
            dia = int(round(size_mm * 1000.0 * float(meta.div)))
            buf.append(_emit('(padstack "', name, '"', indent=3))
            for layer in layers:
                buf.append(_emit("(shape", indent=4))
                buf.append(_emit("(circle ", str(layer), " ", str(dia), " 0 0)", indent=5))
                buf.append(_emit(")", indent=4))
            buf.append(_emit("(attach off)", indent=4))
            buf.append(_emit(")", indent=3))
        buf.append(_emit(")", indent=2))

    buf.append(network_out_block)
    buf.append(_emit(")", indent=1))  # routes
    buf.append(_emit(")", indent=0))  # session

    out_ses.write_text("".join(buf), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", type=Path, required=True, help="Base DSN used for pcb name + resolution.")
    ap.add_argument("--routes", type=Path, required=True, help="routes.json from Mojo backend-route.")
    ap.add_argument("--out", type=Path, required=True, help="Output .ses")
    ap.add_argument("--host", type=str, default="pardal", help="host_cad string in SES.")
    ap.add_argument("--template-ses", type=Path, default=None, help="Optional importable SES whose network_out will be replaced.")
    args = ap.parse_args()
    routes_to_ses(
        dsn=args.dsn,
        routes_json=args.routes,
        out_ses=args.out,
        host=str(args.host),
        template_ses=args.template_ses,
    )


if __name__ == "__main__":
    main()
