"""Copy-only routing DSL apply helper.

This module writes an apply report for a validated candidate. It does not talk
to pcbnew and does not mutate the source board path.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

from .commit_gate import APPLY_REPORT_SCHEMA, APPLY_REPORT_VERSION, apply_candidate_to_copy, validate_candidate_commit


class ApplyCandidateError(ValueError):
    pass


def apply_candidate_report(
    board_ir: str | Path | Mapping[str, Any],
    route_plan: str | Path | Mapping[str, Any],
    candidate_payload: str | Path | Mapping[str, Any],
    output_report_path: str | Path,
    *,
    selected_candidate_id: str | None = None,
    input_board_path: str | Path | None = None,
    output_board_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate and write a neutral apply report for a candidate copy."""

    result = validate_candidate_commit(
        board_ir,
        route_plan,
        candidate_payload,
        selected_candidate_id=selected_candidate_id,
    )
    if not result.accepted:
        raise ApplyCandidateError("candidate is not eligible for copy-only apply")
    if (input_board_path is None) != (output_board_path is None):
        raise ApplyCandidateError("input and output board paths must be provided together")
    if input_board_path is not None and output_board_path is not None:
        source = Path(input_board_path)
        target = Path(output_board_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return apply_candidate_to_copy(
        board_ir,
        route_plan,
        candidate_payload,
        output_report_path,
        selected_candidate_id=selected_candidate_id,
    )
