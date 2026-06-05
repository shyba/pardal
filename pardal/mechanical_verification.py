#!/usr/bin/env python3
"""Mechanical truth-gate checks for saved production summaries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pardal.sexpr import SExprParseError
from pardal.sexpr import load as load_sexpr


@dataclass(frozen=True)
class MechanicalVerificationResult:
    ok: bool
    errors: list[str]


def verify_mechanical_summary(summary_path: Path) -> MechanicalVerificationResult:
    """Validate mechanical summary data against the generated board artifact."""
    summary_path = summary_path.resolve()
    summary, load_errors = _load_json_dict(summary_path)
    if summary is None:
        return MechanicalVerificationResult(False, load_errors)

    if not isinstance(summary, dict):
        return MechanicalVerificationResult(False, ["summary root must be a JSON object"])

    errors: list[str] = []
    mechanical = summary.get("mechanical_features")
    if not isinstance(mechanical, dict):
        return MechanicalVerificationResult(False, ["mechanical_features must be a JSON object"])

    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, dict):
        return MechanicalVerificationResult(False, ["artifacts must be a JSON object"])

    board_artifact = artifacts.get("board")
    if not isinstance(board_artifact, dict):
        return MechanicalVerificationResult(False, ["artifacts.board must be a JSON object"])

    generated = board_artifact.get("generated")
    if not isinstance(generated, str) or not generated.strip():
        return MechanicalVerificationResult(False, ["artifacts.board.generated must be a non-empty string"])

    board_path = Path(generated)
    if not board_path.exists():
        return MechanicalVerificationResult(False, [f"generated board artifact does not exist: {board_path}"])

    expected_width = _as_float(mechanical.get("board_width_mm"))
    expected_height = _as_float(mechanical.get("board_height_mm"))
    if expected_width is None:
        errors.append(
            f"mechanical_features.board_width_mm must be a number, got {mechanical.get('board_width_mm')!r}"
        )
    if expected_height is None:
        errors.append(
            f"mechanical_features.board_height_mm must be a number, got {mechanical.get('board_height_mm')!r}"
        )

    actual = _board_bbox_mm(board_path)
    if actual is None:
        errors.append(f"unable to extract Edge.Cuts rectangular bbox from generated board: {board_path}")
    else:
        actual_width, actual_height = actual
        if expected_width is not None and abs(actual_width - expected_width) > 1e-6:
            errors.append(
                "mechanical_features.board_width_mm does not match generated board Edge.Cuts bbox: "
                f"summary={expected_width:.6f}mm generated={actual_width:.6f}mm"
            )
        if expected_height is not None and abs(actual_height - expected_height) > 1e-6:
            errors.append(
                "mechanical_features.board_height_mm does not match generated board Edge.Cuts bbox: "
                f"summary={expected_height:.6f}mm generated={actual_height:.6f}mm"
            )

    mechanical_pass = mechanical.get("pass")
    if mechanical_pass is not True and mechanical_pass is not False:
        errors.append("mechanical_features.pass must be true or false")
    elif actual is not None and expected_width is not None and expected_height is not None:
        mismatch = (
            abs(actual[0] - expected_width) > 1e-6
            or abs(actual[1] - expected_height) > 1e-6
        )
        if mechanical_pass is True and mismatch:
            errors.append("mechanical_features.pass is true but the generated board bbox disagrees with the summary")
        if mechanical_pass is False and not mismatch:
            errors.append("mechanical_features.pass is false despite the generated board bbox matching the summary")

    return MechanicalVerificationResult(not errors, errors)


def _board_bbox_mm(board_path: Path) -> tuple[float, float] | None:
    try:
        tree = load_sexpr(board_path)
    except (OSError, ValueError, SExprParseError):
        return None
    if not (isinstance(tree, list) and tree and tree[0] == "kicad_pcb"):
        return None

    xs: list[float] = []
    ys: list[float] = []
    for gr_line in _all(tree, "gr_line"):
        layer = _first(gr_line, "layer")
        if not (layer and len(layer) >= 2 and layer[1] == "Edge.Cuts"):
            continue
        start = _first(gr_line, "start")
        end = _first(gr_line, "end")
        if not (start and end and len(start) >= 3 and len(end) >= 3):
            continue
        start_x = _atom_float(start[1])
        start_y = _atom_float(start[2])
        end_x = _atom_float(end[1])
        end_y = _atom_float(end[2])
        if None in (start_x, start_y, end_x, end_y):
            continue
        xs.extend([start_x, end_x])
        ys.extend([start_y, end_y])

    if not xs or not ys:
        return None
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def _first(sexpr: list, tag: str) -> list | None:
    for item in sexpr:
        if isinstance(item, list) and item and item[0] == tag:
            return item
    return None


def _all(sexpr: list, tag: str) -> list[list]:
    return [item for item in sexpr if isinstance(item, list) and item and item[0] == tag]


def _load_json_dict(path: Path) -> tuple[Any | None, list[str]]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"cannot read summary file: {path} ({exc})"]

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, [f"malformed JSON in summary file: {path} ({exc.msg} at line {exc.lineno})"]

    return payload, []


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value
    return None


def _atom_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
