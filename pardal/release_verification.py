#!/usr/bin/env python3
"""Post-run verification for downstream release-package consumption."""

from __future__ import annotations

import json
import csv
import zipfile
from pathlib import Path
from typing import Any

from pardal.mechanical_verification import verify_mechanical_summary
from pardal.production_summary import VerificationResult, verify_production_summary
from pardal.validation_results import verify_validation_results


_MANUFACTURING_ARCHIVE_MEMBER_MAP: dict[str, tuple[str, ...]] = {
    "bom": "bom.csv",
    "pnp": "pnp.csv",
    "jlc_bom": "jlc_bom.csv",
    "jlc_pnp": "jlc_pnp.csv",
    "drc_report": ("drc-report.rpt", "drc-report.json"),
    "drc_diagnostics": "drc-diagnostics.json",
    "production_report": "production-report.json",
    "build_summary": "build-summary.json",
    "validation_results_template": "validation-results.template.json",
    "gerbers": "gerbers/",
    "drill": "drill/",
}


def verify_release_package(
    summary_path: Path,
    validation_results_path: Path | None = None,
) -> VerificationResult:
    """Validate saved release-package artifacts without rerunning compile/KiCad."""
    errors: list[str] = []

    production_result = verify_production_summary(summary_path)
    if not production_result.ok:
        errors.extend(production_result.errors)
    mechanical_result = verify_mechanical_summary(summary_path)
    if not mechanical_result.ok:
        errors.extend(mechanical_result.errors)

    if validation_results_path is not None:
        validation_result = verify_validation_results(summary_path, validation_results_path)
        if not validation_result.ok:
            errors.extend(validation_result.errors)

    errors.extend(_verify_manufacturing_archive_inventory(summary_path))

    return VerificationResult(not errors, errors)


def _verify_manufacturing_archive_inventory(summary_path: Path) -> list[str]:
    try:
        summary_path = summary_path.resolve()
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Let production summary verification own this failure path.
        return []
    if not isinstance(summary, dict):
        return []

    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, dict):
        return []

    archive_entry = artifacts.get("manufacturing_archive")
    if not isinstance(archive_entry, dict):
        return ["release artifact manufacturing_archive is required and must include generated path"]

    generated = archive_entry.get("generated")
    if not isinstance(generated, str) or not generated.strip():
        return ["release artifact manufacturing_archive generated path is missing"]

    archive_path = Path(generated)
    return _check_manufacturing_archive_members(summary, archive_path)


def _check_manufacturing_archive_members(summary: dict[str, Any], archive_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archive_members = set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        # Production summary already checks zip readability and summary embedding.
        return [f"release manufacturing archive is not a readable zip: {archive_path} ({exc})"]

    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, dict):
        return errors

    for artifact_name, expected_members in _MANUFACTURING_ARCHIVE_MEMBER_MAP.items():
        artifact = artifacts.get(artifact_name)
        if not isinstance(artifact, dict):
            continue
        generated = artifact.get("generated")
        if not isinstance(generated, str) or not generated.strip():
            continue

        if isinstance(expected_members, str):
            expected_members = (expected_members,)
        if any(
            expected_member.endswith("/")
            and any(
                member.startswith(expected_member)
                and member != expected_member
                for member in archive_members
            )
            for expected_member in expected_members
        ):
            continue
        if any(
            not expected_member.endswith("/") and expected_member in archive_members
            for expected_member in expected_members
        ):
            continue

        if any(expected_member.endswith("/") for expected_member in expected_members):
            errors.append(
                "release manufacturing archive is missing expected prefix member: "
                f"{' or '.join(expected_members)}"
            )
        else:
            errors.append(
                "release manufacturing archive is missing expected member: "
                f"{' or '.join(expected_members)}"
            )

    if "jlc_bom.csv" in archive_members:
        errors.extend(_verify_jlc_bom_rows(archive_path))

    return errors


def _verify_jlc_bom_rows(archive_path: Path) -> list[str]:
    helper_prefixes = ("TP", "FID", "MH")
    helper_footprint_tokens = ("testpoint", "fiducial", "mountinghole")
    errors: list[str] = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open("jlc_bom.csv") as handle:
                text = handle.read().decode("utf-8-sig").splitlines()
    except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
        return [f"release manufacturing archive cannot read jlc_bom.csv: {archive_path} ({exc})"]

    if not text:
        return ["release manufacturing archive jlc_bom.csv is empty"]

    reader = csv.DictReader(text)
    for row in reader:
        ref = (row.get("Designator") or "").strip()
        footprint = (row.get("Footprint") or "").strip()
        lcsc = (row.get("LCSC Part #") or "").strip()
        if ref.startswith(helper_prefixes):
            errors.append(f"release jlc_bom.csv includes helper designator: {ref}")
        footprint_lower = footprint.lower()
        if any(token in footprint_lower for token in helper_footprint_tokens):
            errors.append(f"release jlc_bom.csv includes helper footprint: {footprint}")
        if ref.startswith(helper_prefixes) and not lcsc:
            errors.append(f"release jlc_bom.csv helper row has blank LCSC part number: {ref}")

    return errors
