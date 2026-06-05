#!/usr/bin/env python3
"""Clear KiCad board items by UUID using textual (string-aware) parsing.

We avoid `pcbnew` here because repeated pcbnew runs can be slow/noisy and may
crash on very large boards when used in tight loops.

Strategy:
- Single-pass scan that is aware of strings and parentheses.
- Maintain a stack of open S-expression frames with their starting offsets.
- When we encounter `(uuid "<value>")` and `<value>` matches, mark the nearest
  enclosing item frame (segment/via/arc) for deletion.
- When that frame closes, record its [start,end) byte offsets.
- Remove intervals in reverse order and write the modified file.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


UUID_TAGS = {"segment", "via", "arc"}
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _read_lines(path: Path) -> set[str]:
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    return out


def _net_name_map(text: str) -> dict[str, str]:
    # KiCad board net defs are: (net <code> "<name>")
    out: dict[str, str] = {}
    for m in re.finditer(r'\(net\s+([0-9]+)\s+"([^"]+)"\s*\)', text):
        out[m.group(1)] = m.group(2)
    # fallback: unquoted names
    for m in re.finditer(r"\(net\s+([0-9]+)\s+([A-Za-z0-9_\-\.]+)\s*\)", text):
        out.setdefault(m.group(1), m.group(2))
    return out


def _net_codes_in_span(text: str) -> set[str]:
    codes: set[str] = set()
    for m in re.finditer(r"\(net\s+([0-9]+)\s*\)", text):
        codes.add(m.group(1))
    return codes


@dataclass
class _Frame:
    start: int
    tag: str | None = None
    delete: bool = False


def _scan_delete_spans(text: str, uuids: set[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    stack: list[_Frame] = []

    i = 0
    n = len(text)
    in_string = False
    escape = False

    def _skip_ws(j: int) -> int:
        while j < n and text[j].isspace():
            j += 1
        return j

    def _read_atom(j: int) -> tuple[str, int]:
        j = _skip_ws(j)
        if j >= n:
            return "", j
        if text[j] == '"':
            j += 1
            out = []
            esc = False
            while j < n:
                c = text[j]
                if esc:
                    out.append(c)
                    esc = False
                    j += 1
                    continue
                if c == "\\":
                    esc = True
                    j += 1
                    continue
                if c == '"':
                    j += 1
                    break
                out.append(c)
                j += 1
            return "".join(out), j
        start = j
        while j < n and (not text[j].isspace()) and text[j] not in "()":
            j += 1
        return text[start:j], j

    while i < n:
        c = text[i]
        if in_string:
            if escape:
                escape = False
                i += 1
                continue
            if c == "\\":
                escape = True
                i += 1
                continue
            if c == '"':
                in_string = False
            i += 1
            continue

        if c == '"':
            in_string = True
            i += 1
            continue
        if c == "(":
            frame = _Frame(start=i)
            stack.append(frame)
            # Capture tag immediately.
            tag, j2 = _read_atom(i + 1)
            if tag:
                frame.tag = tag
            i += 1
            continue
        if c == ")":
            if stack:
                frame = stack.pop()
                if frame.delete:
                    spans.append((frame.start, i + 1))
            i += 1
            continue

        # Detect a uuid field: the current list's tag may be "uuid".
        if stack and stack[-1].tag == "uuid":
            # We are inside (uuid ...). Read the value atom and mark parent.
            val, j2 = _read_atom(i)
            if val and val in uuids and UUID_RE.match(val):
                # Mark nearest deletable ancestor.
                for fr in reversed(stack):
                    if fr.tag in UUID_TAGS:
                        fr.delete = True
                        break
            i = j2
            continue

        i += 1

    return spans


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcb", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--uuids-file", required=True)
    ap.add_argument("--out-nets-file", default=None)
    ap.add_argument("--tracks-only", action="store_true", help="Do not delete vias even if UUID matches.")
    args = ap.parse_args()

    uuids = _read_lines(Path(args.uuids_file))
    src = Path(args.pcb).read_text(encoding="utf-8", errors="replace")
    net_map = _net_name_map(src)

    spans = _scan_delete_spans(src, uuids)
    if args.tracks_only:
        spans2: list[tuple[int, int]] = []
        for a, b in spans:
            frag = src[a:b]
            # If this is a via, keep it.
            if frag.lstrip().startswith("(via"):
                continue
            spans2.append((a, b))
        spans = spans2

    touched: set[str] = set()
    removed = 0

    # Remove in reverse order to preserve offsets.
    spans.sort(key=lambda t: t[0], reverse=True)
    out = src
    for a, b in spans:
        frag = out[a:b]
        for code in _net_codes_in_span(frag):
            name = net_map.get(code)
            if name:
                touched.add(name)
        out = out[:a] + out[b:]
        removed += 1

    Path(args.out).write_text(out, encoding="utf-8")
    if args.out_nets_file:
        Path(args.out_nets_file).write_text("\n".join(sorted(touched)) + ("\n" if touched else ""), encoding="utf-8")
    print(f"removed={removed} touched_nets={len(touched)}")


if __name__ == "__main__":
    main()

