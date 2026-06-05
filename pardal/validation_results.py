#!/usr/bin/env python3
"""Post-run verification for captured validation results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pardal.production_summary import VerificationResult


_VALID_STATUSES = {"pass", "fail", "skip"}


def verify_validation_results(summary_path: Path, results_path: Path) -> VerificationResult:
    """Validate captured validation-results.json against build-summary validation contract."""
    summary_path = summary_path.resolve()
    results_path = results_path.resolve()

    summary, load_errors = _load_json_dict(summary_path, "summary")
    if summary is None:
        return VerificationResult(False, load_errors)

    validation = summary.get("validation")
    if not isinstance(validation, dict):
        return VerificationResult(
            False,
            ["summary validation section missing or is not a JSON object"],
        )

    errors: list[str] = []
    declared_names: list[str] = []
    declared_count = validation.get("count")
    if not isinstance(declared_count, int):
        errors.append("validation.count must be an integer")
    names = validation.get("names")
    if not isinstance(names, list):
        errors.append("validation.names must be a list")
    else:
        for idx, name in enumerate(names):
            if isinstance(name, str) and name.strip():
                declared_names.append(name)
            else:
                errors.append(f"validation.names[{idx}] must be a non-empty string")

    if declared_count is None or declared_count <= 0:
        errors.append("validation.count must be greater than 0")
    if declared_names:
        if declared_count != len(declared_names):
            errors.append(
                "validation.count does not match number of validation.names entries"
            )

    if errors:
        return VerificationResult(False, errors)

    payload, load_errors = _load_json_dict(results_path, "results")
    if payload is None:
        return VerificationResult(False, load_errors)

    if not isinstance(payload, dict):
        return VerificationResult(False, ["results file root must be a JSON object"])

    if payload.get("status") == "template":
        return VerificationResult(
            False,
            [
                "validation results file is a template, not completed evidence; "
                "capture real validation results with pass/fail/skip statuses"
            ],
        )

    result_entries = payload.get("results")
    if not isinstance(result_entries, list):
        return VerificationResult(False, ["results must be a list"])

    result_names: list[str] = []
    result_by_name: dict[str, int] = {}
    for index, entry in enumerate(result_entries):
        if not isinstance(entry, dict):
            errors.append(f"results[{index}] must be an object")
            continue
        name = entry.get("name")
        status = entry.get("status")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"results[{index}].name must be a non-empty string")
            continue
        if not isinstance(status, str):
            errors.append(f"results[{index}].status must be a string")
            continue
        result_names.append(name)
        if not status.strip():
            errors.append(f"results[{index}].status must be a non-empty string")
        elif status == "not_run":
            errors.append(
                f"validation results template entry {name} is not completed evidence "
                "(status is not_run; expected pass, fail, or skip)"
            )
        elif status not in _VALID_STATUSES:
            errors.append(
                f"invalid status {status!r} for {name} at results[{index}] "
                "(expected one of: pass, fail, skip)"
            )
        result_by_name[name] = result_by_name.get(name, 0) + 1

    if errors:
        return VerificationResult(False, errors)

    declared_set = set(declared_names)
    result_set = set(result_names)

    missing = sorted(declared_set - result_set)
    if missing:
        errors.append(f"missing validation results: {missing}")

    unknown = sorted(result_set - declared_set)
    if unknown:
        errors.append(f"unknown validation results: {unknown}")

    duplicate_names = sorted(
        name for name, count in result_by_name.items() if count > 1
    )
    if duplicate_names:
        errors.append(f"duplicate validation result names: {duplicate_names}")

    for name in declared_names:
        if result_by_name.get(name, 0) != 1:
            # Missing/duplicate already reported via set checks above, but this keeps one
            # direct message per declared name when either case occurs.
            if result_by_name.get(name, 0) == 0:
                errors.append(f"validation result missing: {name}")
            else:
                errors.append(f"validation result not unique: {name}")

    for entry in result_entries:
        status = entry["status"] if isinstance(entry, dict) else None
        if status != "pass":
            name = entry["name"] if isinstance(entry, dict) else "<unknown>"
            errors.append(f"validation result did not pass: {name} -> {status}")

    if errors:
        return VerificationResult(False, errors)

    return VerificationResult(True, [])


def _load_json_dict(path: Path, noun: str) -> tuple[Any | None, list[str]]:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [f"cannot read {noun} file: {path} ({exc})"]

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, [
            f"malformed JSON in {noun} file: {path} ({exc.msg} at line {exc.lineno})"
        ]

    return payload, []
