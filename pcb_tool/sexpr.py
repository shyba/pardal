"""Minimal S-expression parser used for KiCad file formats.

KiCad uses an s-expression-like format for `.kicad_pcb` and footprint files.
For large boards, we want a small, dependency-free parser that is tolerant of
unknown constructs and fast enough for fixture extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SExprParseError(ValueError):
    message: str

    def __str__(self) -> str:  # pragma: no cover
        return self.message


def _tokenize(text: str):
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "(" or c == ")":
            yield c
            i += 1
            continue
        if c == '"':
            i += 1
            out = []
            while i < n:
                c = text[i]
                if c == "\\":
                    i += 1
                    if i >= n:
                        raise SExprParseError("unterminated escape in string")
                    out.append(text[i])
                    i += 1
                    continue
                if c == '"':
                    i += 1
                    break
                out.append(c)
                i += 1
            else:
                raise SExprParseError("unterminated string")
            yield "".join(out)
            continue

        # symbol / number atom
        start = i
        while i < n and (not text[i].isspace()) and text[i] not in "()":
            i += 1
        yield text[start:i]


def loads(text: str):
    """Parse a single S-expression from text into nested Python lists."""
    stack: list[list] = []
    root = None
    for tok in _tokenize(text):
        if tok == "(":
            new_list: list = []
            if stack:
                stack[-1].append(new_list)
            stack.append(new_list)
            continue
        if tok == ")":
            if not stack:
                raise SExprParseError("unexpected ')'")
            finished = stack.pop()
            if not stack:
                root = finished
            continue
        if not stack:
            raise SExprParseError(f"atom outside list: {tok!r}")
        stack[-1].append(tok)

    if stack:
        raise SExprParseError("unexpected EOF (missing ')')")
    if root is None:
        raise SExprParseError("empty input")
    return root


def load(path: str | Path):
    return loads(Path(path).read_text(encoding="utf-8", errors="replace"))

