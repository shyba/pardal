#!/usr/bin/env python3
"""Post-run verification for saved production build summaries."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pardal.mechanical_verification import verify_mechanical_summary


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    errors: list[str]


def verify_production_summary(summary_path: Path) -> VerificationResult:
    summary_path = summary_path.resolve()
    try:
        raw_text = summary_path.read_text(encoding="utf-8")
    except OSError as exc:
        return VerificationResult(False, [f"cannot read summary file: {summary_path} ({exc})"])

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return VerificationResult(
            False,
            [f"malformed JSON in summary file: {summary_path} ({exc.msg} at line {exc.lineno})"],
        )

    if not isinstance(payload, dict):
        return VerificationResult(False, ["summary root must be a JSON object"])

    errors: list[str] = []

    if payload.get("pass") is not True:
        errors.append("top-level pass flag is not true")

    strict = _require_mapping(payload, "strict", errors)
    if strict is not None:
        if strict.get("requested") is not True:
            errors.append("strict route gate was not requested")
        if strict.get("route_gate_pass") is not True:
            errors.append("strict route gate did not pass")
        if _as_int(strict.get("commit_violations")) != 0:
            errors.append(
                f"strict commit violations must be 0, got {strict.get('commit_violations')!r}"
            )

    routes = _require_mapping(payload, "routes", errors)
    if routes is not None:
        committed = _as_int(routes.get("committed"))
        total = _as_int(routes.get("total"))
        if committed is None:
            errors.append(f"routes.committed must be an integer, got {routes.get('committed')!r}")
        if total is None:
            errors.append(f"routes.total must be an integer, got {routes.get('total')!r}")
        if committed is not None and total is not None and committed != total:
            errors.append(f"routes committed/total mismatch: {committed}/{total}")

    testpoint_coverage = _require_mapping(payload, "testpoint_coverage", errors)
    residual_testpoints = _require_nested_mapping(
        payload,
        errors,
        "physical_residuals",
        "physical_intent_nets",
        "testpoints",
    )
    if testpoint_coverage is not None:
        declared_count = _as_int(testpoint_coverage.get("declared_count"))
        declared_names = testpoint_coverage.get("declared_names")
        declared_nets = testpoint_coverage.get("declared_nets")
        missing_count = _as_int(testpoint_coverage.get("missing_from_netlist_count"))
        missing_from_netlist = testpoint_coverage.get("missing_from_netlist")
        coverage_pass = testpoint_coverage.get("pass")

        if declared_count is None:
            errors.append(
                f"testpoint_coverage.declared_count must be an integer, got {testpoint_coverage.get('declared_count')!r}"
            )
        if not isinstance(declared_names, list) or not all(isinstance(item, str) for item in declared_names):
            errors.append("testpoint_coverage.declared_names must be a list of strings")
        if not isinstance(declared_nets, list) or not all(isinstance(item, str) for item in declared_nets):
            errors.append("testpoint_coverage.declared_nets must be a list of strings")
        if missing_count is None:
            errors.append(
                "testpoint_coverage.missing_from_netlist_count must be an integer, "
                f"got {testpoint_coverage.get('missing_from_netlist_count')!r}"
            )
        if not isinstance(missing_from_netlist, list) or not all(
            isinstance(item, str) for item in missing_from_netlist
        ):
            errors.append(
                "testpoint_coverage.missing_from_netlist must be a list of strings"
            )
        if coverage_pass is not True and coverage_pass is not False:
            errors.append("testpoint_coverage.pass must be true or false")

        if declared_count is not None:
            if isinstance(declared_names, list) and declared_count != len(declared_names):
                errors.append(
                    f"testpoint_coverage.declared_count mismatch: {declared_count} != len(declared_names)"
                )

        if missing_count is not None and isinstance(missing_from_netlist, list):
            if missing_count != len(missing_from_netlist):
                errors.append(
                    "testpoint_coverage.missing_from_netlist_count mismatch: "
                    f"{missing_count} != len(missing_from_netlist)"
                )
            if isinstance(declared_nets, list):
                unknown = [net for net in missing_from_netlist if net not in declared_nets]
                if unknown:
                    errors.append(
                        "testpoint_coverage.missing_from_netlist contains unknown declared nets: "
                        + ", ".join(sorted(unknown))
                    )
            if missing_count > 0 and coverage_pass is True:
                errors.append(
                    "testpoint_coverage.pass is true but missing testpoints remain"
                )
            if missing_count == 0 and coverage_pass is False:
                errors.append(
                    "testpoint_coverage.pass is false but no missing testpoints remain"
                )

        if isinstance(declared_names, list):
            if declared_names != sorted(declared_names):
                errors.append("testpoint_coverage.declared_names must be sorted")
            if len(set(declared_names)) != len(declared_names):
                errors.append("testpoint_coverage.declared_names must not contain duplicates")
        if isinstance(declared_nets, list):
            if declared_nets != sorted(declared_nets):
                errors.append("testpoint_coverage.declared_nets must be sorted")
            if len(set(declared_nets)) != len(declared_nets):
                errors.append("testpoint_coverage.declared_nets must not contain duplicates")

        if residual_testpoints is not None:
            residual_missing_count = _as_int(residual_testpoints.get("missing_count"))
            residual_missing_from_netlist = residual_testpoints.get("missing_from_netlist")
            if residual_missing_count is None:
                errors.append(
                    "physical_residuals.physical_intent_nets.testpoints.missing_count "
                    f"must be an integer, got {residual_testpoints.get('missing_count')!r}"
                )
            if not isinstance(residual_missing_from_netlist, list) or not all(
                isinstance(item, str) for item in residual_missing_from_netlist
            ):
                errors.append(
                    "physical_residuals.physical_intent_nets.testpoints.missing_from_netlist "
                    "must be a list of strings"
                )
            if (
                missing_count is not None
                and residual_missing_count is not None
                and missing_count != residual_missing_count
            ):
                errors.append(
                    "testpoint_coverage.missing_from_netlist_count does not match "
                    "physical_residuals.physical_intent_nets.testpoints.missing_count"
                )
            if (
                isinstance(missing_from_netlist, list)
                and isinstance(residual_missing_from_netlist, list)
                and missing_from_netlist != residual_missing_from_netlist
            ):
                errors.append(
                    "testpoint_coverage.missing_from_netlist does not match "
                    "physical_residuals.physical_intent_nets.testpoints.missing_from_netlist"
                )

    footprint_state = _require_mapping(payload, "footprint_state", errors)
    if footprint_state is not None:
        _validate_footprint_state(footprint_state, errors)

    source_handoff = _require_mapping(payload, "source_handoff", errors)
    if source_handoff is not None:
        _validate_source_handoff(
            source_handoff,
            physical_residuals=payload.get("physical_residuals"),
            footprint_state=footprint_state,
            errors=errors,
        )
    atopile_source_state = _require_mapping(payload, "atopile_source_state", errors)
    if atopile_source_state is not None:
        _validate_atopile_source_state(
            atopile_source_state,
            source_handoff=source_handoff,
            errors=errors,
        )

    mechanical_features = _require_mapping(payload, "mechanical_features", errors)
    if mechanical_features is not None:
        _validate_mechanical_features(mechanical_features, errors)
        errors.extend(verify_mechanical_summary(summary_path).errors)
    manufacturing_geometry = _require_mapping(payload, "manufacturing_geometry", errors)
    if manufacturing_geometry is not None:
        _validate_manufacturing_geometry(manufacturing_geometry, errors)

    drc = _require_mapping(payload, "drc", errors)
    if drc is not None:
        if drc.get("requested") is not True:
            errors.append("DRC was not requested in the saved run")
        if drc.get("ran") is not True:
            errors.append("DRC did not run")
        if drc.get("pass") is not True:
            errors.append("DRC did not pass")
        if _as_int(drc.get("returncode")) != 0:
            errors.append(f"DRC returncode must be 0, got {drc.get('returncode')!r}")
        if _as_int(drc.get("violation_count")) != 0:
            errors.append(
                f"DRC violation_count must be 0, got {drc.get('violation_count')!r}"
            )
        if _as_int(drc.get("unconnected_count")) != 0:
            errors.append(
                f"DRC unconnected_count must be 0, got {drc.get('unconnected_count')!r}"
            )
    drc_source_coverage = _require_mapping(payload, "drc_source_coverage", errors)
    if drc_source_coverage is not None:
        _validate_drc_source_coverage(drc_source_coverage, drc, errors)

    route_layer_usage = payload.get("route_layer_usage")
    if route_layer_usage is not None and not isinstance(route_layer_usage, dict):
        errors.append("route_layer_usage must be a JSON object")
        route_layer_usage = None
    route_source_coverage = _require_mapping(payload, "route_source_coverage", errors)
    if route_source_coverage is not None:
        _validate_route_source_coverage(
            route_source_coverage,
            routes,
            route_layer_usage,
            errors,
        )

    production_checks = _require_mapping(payload, "production_checks", errors)
    if production_checks is not None:
        if production_checks.get("enabled") is not True:
            errors.append("production checks were not enabled")
        if _as_int(production_checks.get("error_count")) != 0:
            errors.append(
                "production checks error_count must be 0, "
                f"got {production_checks.get('error_count')!r}"
            )

    bom_state = _require_mapping(payload, "bom_state", errors)
    if bom_state is not None:
        _validate_bom_state(bom_state, errors)

    part_alternates = _require_mapping(payload, "part_alternates", errors)
    if part_alternates is not None:
        _validate_part_alternates(part_alternates, bom_state, errors)
    assembly_plan = _require_mapping(payload, "assembly_plan", errors)
    if assembly_plan is not None:
        _validate_assembly_plan(assembly_plan, bom_state, errors)

    lcsc_policy = payload.get("lcsc_policy")
    if lcsc_policy is not None:
        if not isinstance(lcsc_policy, dict):
            errors.append("lcsc_policy must be a JSON object when present")
        else:
            if _as_int(lcsc_policy.get("missing")) != 0:
                errors.append(
                    f"LCSC policy missing count must be 0, got {lcsc_policy.get('missing')!r}"
                )
            if bom_state is not None:
                _cross_check_bom_state_against_lcsc_policy(bom_state, lcsc_policy, errors)

    lcsc_database = payload.get("lcsc_database")
    if lcsc_database is not None:
        _validate_lcsc_database(lcsc_database, errors)
        if isinstance(part_alternates, dict):
            _cross_check_lcsc_database_against_part_alternates(
                lcsc_database,
                part_alternates,
                errors,
            )
    else:
        _validate_lcsc_database(
            {
                "configured": False,
                "strict": False,
                "exists": False,
                "checked_codes": [],
                "checked_code_count": 0,
                "found_code_count": 0,
                "missing_codes": [],
                "missing_code_count": 0,
                "codes": {},
                "pass": True,
                "path": None,
            },
            errors,
        )

    lcsc_availability = payload.get("lcsc_availability")
    if lcsc_availability is not None:
        _validate_lcsc_availability(lcsc_availability, errors)
    else:
        _validate_lcsc_availability(
            {
                "configured": False,
                "batch_quantity": None,
                "line_count": 0,
                "checked_line_count": 0,
                "shortage_line_count": 0,
                "unknown_stock_line_count": 0,
                "shortage_codes": [],
                "unknown_stock_codes": [],
                "pass": True,
                "lines": {},
            },
            errors,
        )
    lcsc_cost = payload.get("lcsc_cost")
    if lcsc_cost is not None:
        _validate_lcsc_cost(lcsc_cost, errors)

    artifacts = _require_mapping(payload, "artifacts", errors)
    if artifacts is not None:
        for artifact_name, artifact_entry in sorted(artifacts.items()):
            if not isinstance(artifact_entry, dict):
                errors.append(f"artifact {artifact_name} must be a JSON object")
                continue
            generated = artifact_entry.get("generated")
            if generated is None:
                continue
            if not isinstance(generated, str) or not generated.strip():
                errors.append(f"artifact {artifact_name} generated path must be a non-empty string")
                continue
            artifact_path = Path(generated)
            errors.extend(_validate_generated_artifact(artifact_name, artifact_path))
            if artifact_name == "manufacturing_archive":
                errors.extend(_validate_archive_summary(artifact_path, raw_text))
    _validate_validation_results_template(payload, errors)

    return VerificationResult(not errors, errors)


def _validate_validation_results_template(payload: dict[str, Any], errors: list[str]) -> None:
    block = _require_mapping(payload, "validation_results_template", errors)
    if block is None:
        return
    status = block.get("status")
    if status != "template":
        errors.append("validation_results_template.status must be 'template'")
    generated = block.get("generated")
    if not isinstance(generated, bool):
        errors.append("validation_results_template.generated must be a boolean")
    path = block.get("path")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        errors.append("validation_results_template.path must be null or a non-empty string")
    test_count = _as_int(block.get("test_count"))
    if test_count is None:
        errors.append("validation_results_template.test_count must be an integer")
    names = _validate_string_list(block.get("names"), "validation_results_template.names", errors)
    if test_count is not None and names is not None and test_count != len(names):
        errors.append("validation_results_template.test_count mismatch with names length")
    passed = block.get("pass")
    if not isinstance(passed, bool):
        errors.append("validation_results_template.pass must be a boolean")
    if isinstance(generated, bool):
        if generated and path is None:
            errors.append("validation_results_template.path must be set when generated is true")
        if not generated and path is not None:
            errors.append("validation_results_template.path must be null when generated is false")
        if isinstance(passed, bool) and passed != generated:
            errors.append("validation_results_template.pass must equal validation_results_template.generated")



def _require_mapping(payload: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any] | None:
    value = payload.get(key)
    if not isinstance(value, dict):
        errors.append(f"{key} must be a JSON object")
        return None
    return value


def _require_nested_mapping(
    payload: dict[str, Any],
    errors: list[str],
    *keys: str,
) -> dict[str, Any] | None:
    current: Any = payload
    traversed: list[str] = []
    for key in keys:
        traversed.append(key)
        if not isinstance(current, dict):
            errors.append(".".join(traversed) + " must be a JSON object")
            return None
        current = current.get(key)
    if not isinstance(current, dict):
        errors.append(".".join(keys) + " must be a JSON object")
        return None
    return current


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return value
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _as_nonempty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text


def _validate_string_list(value: Any, field_name: str, errors: list[str]) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append(f"{field_name} must be a list of strings")
        return None
    if value != sorted(value):
        errors.append(f"{field_name} must be sorted")
    if len(set(value)) != len(value):
        errors.append(f"{field_name} must not contain duplicates")
    return value


def _validate_mechanical_features(mechanical_features: dict[str, Any], errors: list[str]) -> None:
    def _edge_margin_formula(x: float, y: float, radius: float) -> float:
        return min(
            x,
            y,
            max(0.0, board_width - x),
            max(0.0, board_height - y),
        ) - radius

    board_width = _as_float(mechanical_features.get("board_width_mm"))
    board_height = _as_float(mechanical_features.get("board_height_mm"))
    if board_width is None:
        errors.append(
            f"mechanical_features.board_width_mm must be a number, got {mechanical_features.get('board_width_mm')!r}"
        )
        board_width = 0.0
    if board_height is None:
        errors.append(
            f"mechanical_features.board_height_mm must be a number, got {mechanical_features.get('board_height_mm')!r}"
        )
        board_height = 0.0

    fiducial_count = _as_int(mechanical_features.get("fiducial_count"))
    fiducial_names = _validate_string_list(
        mechanical_features.get("fiducial_names"),
        "mechanical_features.fiducial_names",
        errors,
    )
    fiducials = mechanical_features.get("fiducials")
    if not isinstance(fiducials, dict):
        errors.append("mechanical_features.fiducials must be a JSON object")
        fiducials = {}

    mounting_hole_count = _as_int(mechanical_features.get("mounting_hole_count"))
    mounting_hole_names = _validate_string_list(
        mechanical_features.get("mounting_hole_names"),
        "mechanical_features.mounting_hole_names",
        errors,
    )
    mounting_holes = mechanical_features.get("mounting_holes")
    if not isinstance(mounting_holes, dict):
        errors.append("mechanical_features.mounting_holes must be a JSON object")
        mounting_holes = {}

    min_fiducial_edge_margin = mechanical_features.get("min_fiducial_edge_margin_mm")
    min_mounting_hole_edge_margin = mechanical_features.get(
        "min_mounting_hole_edge_margin_mm"
    )

    if fiducial_count is None:
        errors.append(
            f"mechanical_features.fiducial_count must be an integer, got {mechanical_features.get('fiducial_count')!r}"
        )
    if mounting_hole_count is None:
        errors.append(
            f"mechanical_features.mounting_hole_count must be an integer, got {mechanical_features.get('mounting_hole_count')!r}"
        )

    if fiducial_names is not None and fiducial_count is not None:
        if fiducial_count != len(fiducial_names):
            errors.append(
                "mechanical_features.fiducial_count mismatch: "
                f"{fiducial_count} != len(fiducial_names)"
            )
    if mounting_hole_names is not None and mounting_hole_count is not None:
        if mounting_hole_count != len(mounting_hole_names):
            errors.append(
                "mechanical_features.mounting_hole_count mismatch: "
                f"{mounting_hole_count} != len(mounting_hole_names)"
            )

    fiducial_keys = sorted(str(key) for key in fiducials.keys())
    if fiducial_names is not None and fiducial_names != fiducial_keys:
        errors.append(
            "mechanical_features.fiducial_names must match sorted mechanical_features.fiducials keys"
        )
    mounting_hole_keys = sorted(str(key) for key in mounting_holes.keys())
    if mounting_hole_names is not None and mounting_hole_names != mounting_hole_keys:
        errors.append(
            "mechanical_features.mounting_hole_names must match sorted mechanical_features.mounting_holes keys"
        )

    fiducial_edge_margins: list[float] = []
    for fiducial_name in fiducial_names or []:
        fiducial = fiducials.get(fiducial_name)
        if not isinstance(fiducial, dict):
            errors.append(f"mechanical_features.fiducials[{fiducial_name}] must be a JSON object")
            continue
        for field_name in ("x_mm", "y_mm", "diameter_mm", "edge_margin_mm"):
            if _as_float(fiducial.get(field_name)) is None:
                errors.append(
                    f"mechanical_features.fiducials[{fiducial_name}].{field_name} must be a number"
                )
        clearance = fiducial.get("clearance_mm")
        clearance_margin = fiducial.get("clearance_edge_margin_mm")
        if clearance is None and clearance_margin is not None:
            errors.append(
                f"mechanical_features.fiducials[{fiducial_name}].clearance_edge_margin_mm should be null when clearance_mm is omitted"
            )
        if clearance is not None and _as_float(clearance_margin) is None:
            errors.append(
                f"mechanical_features.fiducials[{fiducial_name}].clearance_edge_margin_mm must be a number"
            )
        x_mm = _as_float(fiducial.get("x_mm"))
        y_mm = _as_float(fiducial.get("y_mm"))
        diameter_mm = _as_float(fiducial.get("diameter_mm"))
        edge_margin_mm = _as_float(fiducial.get("edge_margin_mm"))
        clearance_mm = _as_float(clearance)
        if x_mm is not None and y_mm is not None and diameter_mm is not None and edge_margin_mm is not None:
            expected_edge_margin = _edge_margin_formula(x_mm, y_mm, diameter_mm / 2.0)
            if abs(edge_margin_mm - expected_edge_margin) > 1e-6:
                errors.append(
                    f"mechanical_features.fiducials[{fiducial_name}].edge_margin_mm must equal center-to-edge distance minus feature radius"
                )
            if clearance_mm is not None and clearance_margin is not None:
                expected_clearance_margin = edge_margin_mm - clearance_mm
                if abs(_as_float(clearance_margin) - expected_clearance_margin) > 1e-6:
                    errors.append(
                        f"mechanical_features.fiducials[{fiducial_name}].clearance_edge_margin_mm must equal edge_margin_mm - clearance_mm"
                    )
            fiducial_edge_margins.append(edge_margin_mm)

    mounting_hole_edge_margins: list[float] = []
    for mounting_hole_name in mounting_hole_names or []:
        mounting_hole = mounting_holes.get(mounting_hole_name)
        if not isinstance(mounting_hole, dict):
            errors.append(f"mechanical_features.mounting_holes[{mounting_hole_name}] must be a JSON object")
            continue
        for field_name in ("x_mm", "y_mm", "diameter_mm", "drill_mm", "edge_margin_mm"):
            if _as_float(mounting_hole.get(field_name)) is None:
                errors.append(
                    f"mechanical_features.mounting_holes[{mounting_hole_name}].{field_name} must be a number"
                )
        x_mm = _as_float(mounting_hole.get("x_mm"))
        y_mm = _as_float(mounting_hole.get("y_mm"))
        diameter_mm = _as_float(mounting_hole.get("diameter_mm"))
        edge_margin_mm = _as_float(mounting_hole.get("edge_margin_mm"))
        if x_mm is not None and y_mm is not None and diameter_mm is not None and edge_margin_mm is not None:
            expected_edge_margin = _edge_margin_formula(x_mm, y_mm, diameter_mm / 2.0)
            if abs(edge_margin_mm - expected_edge_margin) > 1e-6:
                errors.append(
                    f"mechanical_features.mounting_holes[{mounting_hole_name}].edge_margin_mm must equal center-to-edge distance minus feature radius"
                )
            mounting_hole_edge_margins.append(edge_margin_mm)

    if fiducial_count is not None:
        if fiducial_count > 0:
            if min_fiducial_edge_margin is None:
                errors.append(
                    "mechanical_features.min_fiducial_edge_margin_mm must be set when fiducial_count > 0"
                )
            elif not fiducial_edge_margins:
                errors.append(
                    "mechanical_features.fiducials entry count must be greater than 0 when fiducial_count > 0"
                )
            elif _as_float(min_fiducial_edge_margin) is None:
                errors.append("mechanical_features.min_fiducial_edge_margin_mm must be a number")
            elif abs(_as_float(min_fiducial_edge_margin) - min(fiducial_edge_margins)) > 1e-6:
                errors.append(
                    "mechanical_features.min_fiducial_edge_margin_mm must equal the minimum fiducial edge_margin_mm"
                )
        elif min_fiducial_edge_margin is not None:
            errors.append(
                "mechanical_features.min_fiducial_edge_margin_mm should be null when no fiducials are declared"
            )

    if mounting_hole_count is not None:
        if mounting_hole_count > 0:
            if min_mounting_hole_edge_margin is None:
                errors.append(
                    "mechanical_features.min_mounting_hole_edge_margin_mm must be set when mounting_hole_count > 0"
                )
            elif not mounting_hole_edge_margins:
                errors.append(
                    "mechanical_features.mounting_holes entry count must be greater than 0 when mounting_hole_count > 0"
                )
            elif _as_float(min_mounting_hole_edge_margin) is None:
                errors.append("mechanical_features.min_mounting_hole_edge_margin_mm must be a number")
            elif (
                abs(_as_float(min_mounting_hole_edge_margin) - min(mounting_hole_edge_margins))
                > 1e-6
            ):
                errors.append(
                    "mechanical_features.min_mounting_hole_edge_margin_mm must equal the minimum mounting_hole edge_margin_mm"
                )
        elif min_mounting_hole_edge_margin is not None:
            errors.append(
                "mechanical_features.min_mounting_hole_edge_margin_mm should be null when no mounting holes are declared"
            )

    mechanical_pass = mechanical_features.get("pass")
    if mechanical_pass is not True and mechanical_pass is not False:
        errors.append("mechanical_features.pass must be true or false")
    else:
        negative_fiducial = any(value < 0.0 for value in fiducial_edge_margins)
        negative_mounting_hole = any(value < 0.0 for value in mounting_hole_edge_margins)
        if mechanical_pass is True and (negative_fiducial or negative_mounting_hole):
            errors.append(
                "mechanical_features.pass is true but one or more edge margins are negative"
            )
        if mechanical_pass is False and not negative_fiducial and not negative_mounting_hole:
            errors.append("mechanical_features.pass is false despite no negative edge margins")


def _validate_manufacturing_geometry(manufacturing_geometry: dict[str, Any], errors: list[str]) -> None:
    trace_segment_count = _as_int(manufacturing_geometry.get("trace_segment_count"))
    via_count = _as_int(manufacturing_geometry.get("via_count"))
    copper_zone_count = _as_int(manufacturing_geometry.get("copper_zone_count"))
    min_trace_width = manufacturing_geometry.get("min_trace_width_mm")
    min_via_drill = manufacturing_geometry.get("min_via_drill_mm")
    min_via_diameter = manufacturing_geometry.get("min_via_diameter_mm")
    layers_used = _validate_string_list(
        manufacturing_geometry.get("layers_used"),
        "manufacturing_geometry.layers_used",
        errors,
    )
    thresholds = manufacturing_geometry.get("thresholds")
    violations = _validate_string_list(
        manufacturing_geometry.get("violations"),
        "manufacturing_geometry.violations",
        errors,
    )
    violation_count = _as_int(manufacturing_geometry.get("violation_count"))
    geometry_pass = manufacturing_geometry.get("pass")

    for field_name, value, raw in (
        ("manufacturing_geometry.trace_segment_count", trace_segment_count, "trace_segment_count"),
        ("manufacturing_geometry.via_count", via_count, "via_count"),
        ("manufacturing_geometry.copper_zone_count", copper_zone_count, "copper_zone_count"),
        ("manufacturing_geometry.violation_count", violation_count, "violation_count"),
    ):
        if value is None:
            errors.append(f"{field_name} must be an integer, got {manufacturing_geometry.get(raw)!r}")
        elif value < 0:
            errors.append(f"{field_name} must be >= 0")

    for field_name, value in (
        ("manufacturing_geometry.min_trace_width_mm", min_trace_width),
        ("manufacturing_geometry.min_via_drill_mm", min_via_drill),
        ("manufacturing_geometry.min_via_diameter_mm", min_via_diameter),
    ):
        if value is not None and _as_float(value) is None:
            errors.append(f"{field_name} must be a number or null")

    if trace_segment_count == 0 and min_trace_width is not None:
        errors.append("manufacturing_geometry.min_trace_width_mm should be null when trace_segment_count is 0")
    if trace_segment_count is not None and trace_segment_count > 0 and _as_float(min_trace_width) is None:
        errors.append("manufacturing_geometry.min_trace_width_mm must be set when trace_segment_count > 0")
    if via_count == 0 and (min_via_drill is not None or min_via_diameter is not None):
        errors.append("manufacturing_geometry.min_via_drill_mm and min_via_diameter_mm should be null when via_count is 0")
    if via_count is not None and via_count > 0:
        if _as_float(min_via_drill) is None:
            errors.append("manufacturing_geometry.min_via_drill_mm must be set when via_count > 0")
        if _as_float(min_via_diameter) is None:
            errors.append("manufacturing_geometry.min_via_diameter_mm must be set when via_count > 0")
    if (
        _as_float(min_via_drill) is not None
        and _as_float(min_via_diameter) is not None
        and _as_float(min_via_drill) >= _as_float(min_via_diameter)
    ):
        errors.append("manufacturing_geometry.min_via_drill_mm must be smaller than min_via_diameter_mm")

    if thresholds is not None:
        if not isinstance(thresholds, dict):
            errors.append("manufacturing_geometry.thresholds must be a JSON object when present")
        else:
            for key in (
                "default_trace_width_mm",
                "default_clearance_mm",
                "default_via_drill_mm",
                "default_via_diameter_mm",
            ):
                if key in thresholds and thresholds[key] is not None and _as_float(thresholds[key]) is None:
                    errors.append(f"manufacturing_geometry.thresholds.{key} must be a number or null")

    if violations is not None and violation_count is not None and violation_count != len(violations):
        errors.append("manufacturing_geometry.violation_count mismatch: violation_count != len(violations)")
    if geometry_pass not in (True, False):
        errors.append("manufacturing_geometry.pass must be true or false")
    elif violation_count is not None:
        if geometry_pass is True and violation_count > 0:
            errors.append("manufacturing_geometry.pass is true but violation_count > 0")
        if geometry_pass is False and violation_count == 0:
            errors.append("manufacturing_geometry.pass is false but violation_count is 0")


def _validate_bom_state(bom_state: dict[str, Any], errors: list[str]) -> None:
    part_count = _as_int(bom_state.get("part_count"))
    mapped_count = _as_int(bom_state.get("mapped_count"))
    missing_count = _as_int(bom_state.get("missing_count"))
    excepted_count = _as_int(bom_state.get("excepted_count"))
    mapped_refs = _validate_string_list(bom_state.get("mapped_refs"), "bom_state.mapped_refs", errors)
    missing_refs = _validate_string_list(bom_state.get("missing_refs"), "bom_state.missing_refs", errors)
    excepted_refs = _validate_string_list(
        bom_state.get("excepted_refs"),
        "bom_state.excepted_refs",
        errors,
    )
    passed = bom_state.get("pass")

    for field_name, value in (
        ("bom_state.part_count", part_count),
        ("bom_state.mapped_count", mapped_count),
        ("bom_state.missing_count", missing_count),
        ("bom_state.excepted_count", excepted_count),
    ):
        if value is None:
            raw_key = field_name.split(".")[-1]
            errors.append(f"{field_name} must be an integer, got {bom_state.get(raw_key)!r}")

    if passed not in (True, False):
        errors.append("bom_state.pass must be true or false")

    if mapped_count is not None and mapped_refs is not None and mapped_count != len(mapped_refs):
        errors.append("bom_state.mapped_count mismatch: " f"{mapped_count} != len(mapped_refs)")
    if missing_count is not None and missing_refs is not None and missing_count != len(missing_refs):
        errors.append("bom_state.missing_count mismatch: " f"{missing_count} != len(missing_refs)")
    if excepted_count is not None and excepted_refs is not None and excepted_count != len(excepted_refs):
        errors.append("bom_state.excepted_count mismatch: " f"{excepted_count} != len(excepted_refs)")
    if (
        part_count is not None
        and mapped_count is not None
        and missing_count is not None
        and excepted_count is not None
        and part_count != mapped_count + missing_count + excepted_count
    ):
        errors.append(
            "bom_state.part_count mismatch: "
            f"{part_count} != mapped_count + missing_count + excepted_count"
        )
    if missing_count is not None and passed is True and missing_count != 0:
        errors.append("bom_state.pass is true but missing parts remain")
    if missing_count is not None and passed is False and missing_count == 0:
        errors.append("bom_state.pass is false but no missing parts remain")


def _validate_part_alternates(
    part_alternates: dict[str, Any],
    bom_state: dict[str, Any] | None,
    errors: list[str],
) -> None:
    declared_count = _as_int(part_alternates.get("declared_count"))
    ref_count = _as_int(part_alternates.get("ref_count"))
    refs = _validate_string_list(part_alternates.get("refs"), "part_alternates.refs", errors)
    unused_ref_count = _as_int(part_alternates.get("unused_ref_count"))
    unused_refs = _validate_string_list(
        part_alternates.get("unused_refs"),
        "part_alternates.unused_refs",
        errors,
    )
    passed = _as_bool(part_alternates.get("pass"))

    alternates_by_ref_raw = part_alternates.get("alternates_by_ref")
    alternates_by_ref: dict[str, list[str]] | None = None
    if not isinstance(alternates_by_ref_raw, dict):
        errors.append("part_alternates.alternates_by_ref must be a JSON object")
    else:
        alternates_by_ref = {}
        for ref, value in sorted(alternates_by_ref_raw.items()):
            field_name = f"part_alternates.alternates_by_ref.{ref}"
            if not isinstance(ref, str) or not ref:
                errors.append("part_alternates.alternates_by_ref contains an empty reference key")
                continue
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                errors.append(f"{field_name} must be a list of strings")
                continue
            if not value:
                errors.append(f"{field_name} must be a non-empty list")
            if value != sorted(value):
                errors.append(f"{field_name} must be sorted")
            if len(set(value)) != len(value):
                errors.append(f"{field_name} must not contain duplicates")
            if any(not item.strip() for item in value):
                errors.append(f"{field_name} must contain only non-empty strings")
            alternates_by_ref[ref] = value

    for field_name, value in (
        ("part_alternates.declared_count", declared_count),
        ("part_alternates.ref_count", ref_count),
        ("part_alternates.unused_ref_count", unused_ref_count),
    ):
        if value is None:
            raw_key = field_name.split(".")[-1]
            errors.append(f"{field_name} must be an integer, got {part_alternates.get(raw_key)!r}")

    if passed is None:
        errors.append("part_alternates.pass must be true or false")

    if refs is not None and alternates_by_ref is not None:
        mapping_refs = sorted(alternates_by_ref)
        if refs != mapping_refs:
            errors.append("part_alternates.refs does not match alternates_by_ref keys")
        if ref_count is not None and ref_count != len(refs):
            errors.append("part_alternates.ref_count mismatch: " f"{ref_count} != len(refs)")
        if declared_count is not None:
            alternate_total = sum(len(alternates_by_ref[ref]) for ref in mapping_refs)
            if declared_count != alternate_total:
                errors.append(
                    "part_alternates.declared_count mismatch: "
                    f"{declared_count} != total alternates declared"
                )

    if unused_ref_count is not None and unused_refs is not None and unused_ref_count != len(unused_refs):
        errors.append(
            "part_alternates.unused_ref_count mismatch: "
            f"{unused_ref_count} != len(unused_refs)"
        )

    if bom_state is not None and refs is not None and unused_refs is not None:
        mapped_refs = bom_state.get("mapped_refs")
        excepted_refs = bom_state.get("excepted_refs")
        missing_refs = bom_state.get("missing_refs")
        if all(isinstance(value, list) for value in (mapped_refs, excepted_refs, missing_refs)):
            valid_refs = set(mapped_refs) | set(excepted_refs) | set(missing_refs)
            computed_unused_refs = sorted(ref for ref in refs if ref not in valid_refs)
            if unused_refs != computed_unused_refs:
                errors.append(
                    "part_alternates.unused_refs does not match refs absent from bom_state"
                )
            if passed is True and computed_unused_refs:
                errors.append("part_alternates.pass is true but unused refs remain")
        if passed is False and not computed_unused_refs:
            errors.append("part_alternates.pass is false but no unused refs remain")


def _validate_assembly_plan(
    assembly_plan: dict[str, Any],
    bom_state: dict[str, Any] | None,
    errors: list[str],
) -> None:
    configured = _as_bool(assembly_plan.get("configured"))
    component_count = _as_int(assembly_plan.get("component_count"))
    assigned_count = _as_int(assembly_plan.get("assigned_count"))
    missing_count = _as_int(assembly_plan.get("missing_count"))
    unknown_ref_count = _as_int(assembly_plan.get("unknown_ref_count"))
    missing_refs = _validate_string_list(assembly_plan.get("missing_refs"), "assembly_plan.missing_refs", errors)
    unknown_refs = _validate_string_list(assembly_plan.get("unknown_refs"), "assembly_plan.unknown_refs", errors)
    passed = _as_bool(assembly_plan.get("pass"))
    method_counts = assembly_plan.get("method_counts")
    refs_by_method = assembly_plan.get("refs_by_method")

    for field_name, value in (
        ("assembly_plan.component_count", component_count),
        ("assembly_plan.assigned_count", assigned_count),
        ("assembly_plan.missing_count", missing_count),
        ("assembly_plan.unknown_ref_count", unknown_ref_count),
    ):
        if value is None:
            raw_key = field_name.split(".")[-1]
            errors.append(f"{field_name} must be an integer, got {assembly_plan.get(raw_key)!r}")
    if configured is None:
        errors.append("assembly_plan.configured must be true or false")
    if passed is None:
        errors.append("assembly_plan.pass must be true or false")
    if not isinstance(method_counts, dict):
        errors.append("assembly_plan.method_counts must be a JSON object")
        method_counts = None
    if not isinstance(refs_by_method, dict):
        errors.append("assembly_plan.refs_by_method must be a JSON object")
        refs_by_method = None

    if missing_count is not None and missing_refs is not None and missing_count != len(missing_refs):
        errors.append("assembly_plan.missing_count mismatch: " f"{missing_count} != len(missing_refs)")
    if unknown_ref_count is not None and unknown_refs is not None and unknown_ref_count != len(unknown_refs):
        errors.append("assembly_plan.unknown_ref_count mismatch: " f"{unknown_ref_count} != len(unknown_refs)")

    if method_counts is not None:
        keys = list(method_counts.keys())
        if keys != sorted(keys):
            errors.append("assembly_plan.method_counts keys must be sorted")
        method_total = 0
        for method, count in method_counts.items():
            if not isinstance(method, str) or not method.strip():
                errors.append("assembly_plan.method_counts contains empty method key")
                continue
            parsed = _as_int(count)
            if parsed is None or parsed < 0:
                errors.append(f"assembly_plan.method_counts.{method} must be a non-negative integer")
                continue
            method_total += parsed
        if assigned_count is not None and method_total != assigned_count:
            errors.append("assembly_plan.assigned_count does not match method_counts total")

    if refs_by_method is not None:
        keys = list(refs_by_method.keys())
        if keys != sorted(keys):
            errors.append("assembly_plan.refs_by_method keys must be sorted")
        refs_total = 0
        for method, refs in refs_by_method.items():
            field_name = f"assembly_plan.refs_by_method.{method}"
            parsed_refs = _validate_string_list(refs, field_name, errors)
            if parsed_refs is None:
                continue
            refs_total += len(parsed_refs)
            if method_counts is not None and method in method_counts and method_counts[method] != len(parsed_refs):
                errors.append(f"{field_name} length does not match assembly_plan.method_counts.{method}")
        if assigned_count is not None and refs_total != assigned_count:
            errors.append("assembly_plan.assigned_count does not match refs_by_method totals")
        if method_counts is not None and sorted(method_counts.keys()) != sorted(refs_by_method.keys()):
            errors.append("assembly_plan.refs_by_method keys do not match assembly_plan.method_counts keys")

    if component_count is not None and assigned_count is not None and missing_count is not None:
        if component_count != assigned_count + missing_count:
            errors.append("assembly_plan.component_count mismatch: component_count != assigned_count + missing_count")

    if bom_state is not None and component_count is not None:
        bom_part_count = _as_int(bom_state.get("part_count"))
        if bom_part_count is not None and component_count != bom_part_count:
            errors.append("assembly_plan.component_count does not match bom_state.part_count")

    if passed is True:
        if missing_count is not None and missing_count > 0:
            errors.append("assembly_plan.pass is true but missing refs remain")
        if unknown_ref_count is not None and unknown_ref_count > 0:
            errors.append("assembly_plan.pass is true but unknown refs remain")
    if passed is False and missing_count == 0 and unknown_ref_count == 0 and configured is True:
        errors.append("assembly_plan.pass is false but no missing or unknown refs remain")


def _cross_check_lcsc_database_against_part_alternates(
    lcsc_database: dict[str, Any],
    part_alternates: dict[str, Any],
    errors: list[str],
) -> None:
    declared_alternate_codes: list[str] = []
    alternates_by_ref = part_alternates.get("alternates_by_ref")
    if not isinstance(alternates_by_ref, dict):
        return

    for ref, raw_alternates in sorted(alternates_by_ref.items()):
        if not isinstance(ref, str) or not ref:
            continue
        if not isinstance(raw_alternates, list) or not all(
            isinstance(code, str) for code in raw_alternates
        ):
            continue
        for code in raw_alternates:
            declared_alternate_codes.append(code)

    checked_codes = _validate_string_list(
        lcsc_database.get("checked_codes"),
        "lcsc_database.checked_codes",
        errors,
    )
    if checked_codes is None:
        return

    missing_declared = sorted(set(declared_alternate_codes) - set(checked_codes))
    if missing_declared:
        errors.append(
            "lcsc_database.checked_codes does not include all declared alternate codes: "
            + ", ".join(missing_declared)
        )



def _validate_lcsc_database(
    lcsc_database: dict[str, Any],
    errors: list[str],
) -> None:
    configured = _as_bool(lcsc_database.get("configured"))
    if configured is None:
        errors.append("lcsc_database.configured must be true or false")
        configured = False

    strict = _as_bool(lcsc_database.get("strict"))
    if strict is None:
        errors.append("lcsc_database.strict must be true or false")
        strict = False

    exists = _as_bool(lcsc_database.get("exists"))
    if exists is None:
        errors.append("lcsc_database.exists must be true or false")
        exists = False

    checked_codes_raw = lcsc_database.get("checked_codes")
    checked_codes = _validate_string_list(
        checked_codes_raw,
        "lcsc_database.checked_codes",
        errors,
    )
    missing_codes = _validate_string_list(
        lcsc_database.get("missing_codes"),
        "lcsc_database.missing_codes",
        errors,
    )

    checked_code_count = _as_int(lcsc_database.get("checked_code_count"))
    if checked_code_count is None:
        errors.append(
            "lcsc_database.checked_code_count must be an integer, "
            f"got {lcsc_database.get('checked_code_count')!r}"
        )

    found_code_count = _as_int(lcsc_database.get("found_code_count"))
    if found_code_count is None:
        errors.append(
            "lcsc_database.found_code_count must be an integer, "
            f"got {lcsc_database.get('found_code_count')!r}"
        )

    missing_code_count = _as_int(lcsc_database.get("missing_code_count"))
    if missing_code_count is None:
        errors.append(
            "lcsc_database.missing_code_count must be an integer, "
            f"got {lcsc_database.get('missing_code_count')!r}"
        )

    path = lcsc_database.get("path")
    if configured:
        if path is None:
            errors.append("lcsc_database.path must be a string when configured")
        elif not isinstance(path, str) or not path.strip():
            errors.append("lcsc_database.path must be a non-empty string")
    else:
        if path not in (None, ""):
            errors.append("lcsc_database.path must be null when not configured")

    codes_raw = lcsc_database.get("codes")
    if codes_raw is None:
        errors.append("lcsc_database.codes must be a JSON object")
    elif not isinstance(codes_raw, dict):
        errors.append("lcsc_database.codes must be a JSON object")
        codes_raw = {}

    missing_codes_set = set(missing_codes) if missing_codes is not None else None
    found_codes = sorted(codes_raw)
    invalid_codes = [code for code in (checked_codes or []) if not re.fullmatch(r"C\d+", code)]

    if checked_codes is not None:
        if configured is True:
            if checked_code_count is not None and checked_code_count != len(checked_codes):
                errors.append(
                    "lcsc_database.checked_code_count mismatch: "
                    f"{checked_code_count} != len(checked_codes)"
                )

            if len(set(checked_codes)) != len(checked_codes):
                errors.append("lcsc_database.checked_codes must not contain duplicates")

            if missing_codes is not None and missing_code_count is not None:
                if missing_code_count != len(missing_codes):
                    errors.append(
                        "lcsc_database.missing_code_count mismatch: "
                        f"{missing_code_count} != len(missing_codes)"
                    )
                if len(set(missing_codes)) != len(missing_codes):
                    errors.append("lcsc_database.missing_codes must not contain duplicates")
            if checked_code_count is not None and found_code_count is not None and missing_code_count is not None:
                if checked_code_count != found_code_count + missing_code_count:
                    errors.append(
                        "lcsc_database.found_code_count + missing_code_count does not equal "
                        "checked_code_count"
                    )

            if found_code_count is not None and found_code_count != len(found_codes):
                errors.append(
                    "lcsc_database.found_code_count mismatch: "
                    f"{found_code_count} != len(codes)"
                )
            extra_codes = [code for code in found_codes if code not in checked_codes]
            if extra_codes:
                errors.append(
                    "lcsc_database.codes contains codes that were not checked: "
                    + ", ".join(extra_codes)
                )

            if not exists and strict and len(checked_codes) > 0:
                errors.append(
                    "lcsc_database.pass must be false when configured DB path is missing "
                    "with strict mode"
                )

            if checked_codes and missing_codes_set is not None:
                if not all(code in checked_codes for code in missing_codes_set):
                    errors.append("lcsc_database.missing_codes must be subset of checked_codes")

            if missing_code_count is not None and missing_code_count > 0:
                if lcsc_database.get("pass") is not True:
                    if _as_bool(lcsc_database.get("pass")) is None:
                        errors.append("lcsc_database.pass must be true or false")
                if _as_bool(lcsc_database.get("pass")) is True:
                    errors.append("lcsc_database.pass is true but missing_code_count is not 0")
            elif missing_code_count == 0 and _as_bool(lcsc_database.get("pass")) is False:
                errors.append("lcsc_database.pass is false despite no missing codes")

        if checked_code_count is not None and checked_code_count != len(checked_codes):
            errors.append(
                "lcsc_database.checked_code_count mismatch: "
                f"{checked_code_count} != len(checked_codes)"
            )

    if invalid_codes:
        errors.append(
            "lcsc_database.checked_codes contains malformed LCSC codes: "
            + ", ".join(sorted(invalid_codes))
        )

    for code, details_raw in sorted(codes_raw.items()):
        if not isinstance(code, str) or not code.strip():
            errors.append("lcsc_database.codes must use string keys")
            continue
        if not isinstance(details_raw, dict):
            errors.append(f"lcsc_database.codes[{code}] must be a JSON object")
            continue
        stock = details_raw.get("stock")
        if stock is not None and not isinstance(stock, int):
            errors.append(f"lcsc_database.codes[{code}].stock must be an integer or null")
        for field_name in ("basic", "preferred", "package", "description"):
            value = details_raw.get(field_name)
            if value is not None and not isinstance(value, str):
                errors.append(f"lcsc_database.codes[{code}].{field_name} must be a string or null")

    if configured is False:
        if checked_codes is not None and checked_codes != []:
            errors.append("lcsc_database.unchecked configured block must have no checked_codes")
        if checked_code_count is not None and checked_code_count != 0:
            errors.append("lcsc_database.unchecked configured block must have checked_code_count 0")
        if found_code_count is not None and found_code_count != 0:
            errors.append("lcsc_database.unchecked configured block must have found_code_count 0")
        if missing_code_count is not None and missing_code_count != 0:
            errors.append("lcsc_database.unchecked configured block must have missing_code_count 0")
        if strict is not None and strict is not False:
            errors.append("lcsc_database.strict must be false when not configured")
        if exists is not False:
            errors.append("lcsc_database.exists must be false when not configured")

    if _as_bool(lcsc_database.get("pass")) is None:
        errors.append(f"lcsc_database.pass must be true or false, got {lcsc_database.get('pass')!r}")


def _validate_lcsc_cost(lcsc_cost: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(lcsc_cost, dict):
        errors.append("lcsc_cost must be a JSON object")
        return
    configured = _as_bool(lcsc_cost.get("configured"))
    if configured is None:
        errors.append("lcsc_cost.configured must be true or false")
        return
    if configured is False:
        return
    batch_quantity = _as_int(lcsc_cost.get("batch_quantity"))
    if batch_quantity is None or batch_quantity <= 0:
        errors.append("lcsc_cost.batch_quantity must be a positive integer")
    line_count = _as_int(lcsc_cost.get("line_count"))
    priced_count = _as_int(lcsc_cost.get("priced_line_count"))
    unpriced_count = _as_int(lcsc_cost.get("unpriced_line_count"))
    for name, value in [("line_count", line_count), ("priced_line_count", priced_count), ("unpriced_line_count", unpriced_count)]:
        if value is None or value < 0:
            errors.append(f"lcsc_cost.{name} must be a non-negative integer")
    lines = lcsc_cost.get("lines")
    if not isinstance(lines, dict):
        errors.append("lcsc_cost.lines must be a JSON object")
        return
    unpriced_codes = _validate_string_list(lcsc_cost.get("unpriced_codes"), "lcsc_cost.unpriced_codes", errors) or []
    parsed_unpriced: list[str] = []
    total = 0.0
    for code in sorted(lines):
        if not re.fullmatch(r"C\d+", code):
            errors.append(f"lcsc_cost.lines contains malformed code {code}")
            continue
        item = lines[code]
        if not isinstance(item, dict):
            errors.append(f"lcsc_cost.lines[{code}] must be a JSON object")
            continue
        ref_count = _as_int(item.get("ref_count"))
        required = _as_int(item.get("required_quantity"))
        refs = item.get("refs")
        if ref_count is None or ref_count <= 0:
            errors.append(f"lcsc_cost.lines[{code}].ref_count must be a positive integer")
        if required is None or required <= 0:
            errors.append(f"lcsc_cost.lines[{code}].required_quantity must be a positive integer")
        if not isinstance(refs, list) or not all(isinstance(r, str) and r for r in refs):
            errors.append(f"lcsc_cost.lines[{code}].refs must be a non-empty list of strings")
        elif ref_count is not None and len(refs) != ref_count:
            errors.append(f"lcsc_cost.lines[{code}].ref_count mismatch with refs length")
        unit = item.get("unit_price_usd")
        ext = item.get("extended_price_usd")
        if unit is None or ext is None:
            parsed_unpriced.append(code)
        else:
            if not isinstance(unit, int | float) or not isinstance(ext, int | float):
                errors.append(f"lcsc_cost.lines[{code}] prices must be numbers or null")
            else:
                total += float(ext)
                if required is not None and abs(float(ext) - float(unit) * required) > 1e-6:
                    errors.append(f"lcsc_cost.lines[{code}] extended_price_usd mismatch")
    if line_count is not None and line_count != len(lines):
        errors.append("lcsc_cost.line_count mismatch")
    if priced_count is not None and priced_count != len(lines) - len(parsed_unpriced):
        errors.append("lcsc_cost.priced_line_count mismatch")
    if unpriced_count is not None and unpriced_count != len(parsed_unpriced):
        errors.append("lcsc_cost.unpriced_line_count mismatch")
    if sorted(unpriced_codes) != sorted(parsed_unpriced):
        errors.append("lcsc_cost.unpriced_codes mismatch")
    batch_total = lcsc_cost.get("estimated_batch_components_usd")
    if not isinstance(batch_total, int | float):
        errors.append("lcsc_cost.estimated_batch_components_usd must be numeric")
    elif abs(float(batch_total) - total) > 1e-6:
        errors.append("lcsc_cost.estimated_batch_components_usd mismatch")
    unit_total = lcsc_cost.get("estimated_unit_components_usd")
    if not isinstance(unit_total, int | float):
        errors.append("lcsc_cost.estimated_unit_components_usd must be numeric")
    elif batch_quantity and isinstance(batch_total, int | float):
        if abs(float(unit_total) - float(batch_total) / batch_quantity) > 1e-6:
            errors.append("lcsc_cost.estimated_unit_components_usd mismatch")
    passed = _as_bool(lcsc_cost.get("pass"))
    if passed is None:
        errors.append("lcsc_cost.pass must be true or false")
    elif passed and parsed_unpriced:
        errors.append("lcsc_cost.pass is true but unpriced_line_count is not 0")


def _validate_lcsc_availability(lcsc_availability: dict[str, Any], errors: list[str]) -> None:
    if not isinstance(lcsc_availability, dict):
        errors.append("lcsc_availability must be a JSON object")
        return

    configured = _as_bool(lcsc_availability.get("configured"))
    if configured is None:
        errors.append("lcsc_availability.configured must be true or false")
        return

    batch_quantity = lcsc_availability.get("batch_quantity")
    if configured is True:
        batch_quantity_int = _as_int(batch_quantity)
        if batch_quantity_int is None or batch_quantity_int <= 0:
            errors.append("lcsc_availability.batch_quantity must be a positive integer")
    else:
        if batch_quantity is not None:
            errors.append("lcsc_availability.batch_quantity must be null when not configured")
        batch_quantity_int = None

    line_count = _as_int(lcsc_availability.get("line_count"))
    checked_line_count = _as_int(lcsc_availability.get("checked_line_count"))
    shortage_line_count = _as_int(lcsc_availability.get("shortage_line_count"))
    unknown_stock_line_count = _as_int(lcsc_availability.get("unknown_stock_line_count"))

    for field_name, value in (
        ("line_count", line_count),
        ("checked_line_count", checked_line_count),
        ("shortage_line_count", shortage_line_count),
        ("unknown_stock_line_count", unknown_stock_line_count),
    ):
        if value is None or value < 0:
            errors.append(f"lcsc_availability.{field_name} must be a non-negative integer")

    shortage_codes = _validate_string_list(
        lcsc_availability.get("shortage_codes"),
        "lcsc_availability.shortage_codes",
        errors,
    ) or []
    unknown_stock_codes = _validate_string_list(
        lcsc_availability.get("unknown_stock_codes"),
        "lcsc_availability.unknown_stock_codes",
        errors,
    ) or []
    lines = lcsc_availability.get("lines")
    if not isinstance(lines, dict):
        errors.append("lcsc_availability.lines must be a JSON object")
        return

    if checked_line_count is not None:
        if checked_line_count != len(lines):
            errors.append("lcsc_availability.checked_line_count mismatch")
    if line_count is not None and line_count != len(lines):
        errors.append("lcsc_availability.line_count mismatch")

    parsed_shortage = []
    parsed_unknown_stock = []
    for code in sorted(lines):
        if not re.fullmatch(r"C\d+", str(code)):
            errors.append(f"lcsc_availability.lines contains malformed code {code}")
            continue
        item = lines[code]
        if not isinstance(item, dict):
            errors.append(f"lcsc_availability.lines[{code}] must be a JSON object")
            continue

        refs = item.get("refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"lcsc_availability.lines[{code}].refs must be a non-empty list of strings")
        elif not all(isinstance(ref, str) and ref for ref in refs):
            errors.append(f"lcsc_availability.lines[{code}].refs must be a non-empty list of strings")

        ref_count = _as_int(item.get("ref_count"))
        required = _as_int(item.get("required_quantity"))
        if ref_count is None or ref_count <= 0:
            errors.append(f"lcsc_availability.lines[{code}].ref_count must be a positive integer")
        if required is None or required <= 0:
            errors.append(f"lcsc_availability.lines[{code}].required_quantity must be a positive integer")
        if configured is True and isinstance(refs, list) and ref_count is not None and len(refs) != ref_count:
            errors.append(f"lcsc_availability.lines[{code}].ref_count mismatch with refs length")
        if configured is True and isinstance(refs, list) and isinstance(ref_count, int) and isinstance(required, int):
            if batch_quantity_int is None or batch_quantity_int <= 0:
                errors.append("lcsc_availability.batch_quantity must be a positive integer")
            else:
                expected = ref_count * batch_quantity_int
                if required != expected:
                    errors.append(
                        "lcsc_availability.lines[{}].required_quantity mismatch: {} != ref_count * batch_quantity"
                        .format(code, item.get("required_quantity"))
                    )

        stock = item.get("stock")
        if stock is not None and not isinstance(stock, int):
            errors.append(f"lcsc_availability.lines[{code}].stock must be an integer or null")

        stock_sufficient = item.get("stock_sufficient")
        if stock_sufficient is not None and not isinstance(stock_sufficient, bool):
            errors.append(f"lcsc_availability.lines[{code}].stock_sufficient must be true or false")

        shortage_quantity = _as_int(item.get("shortage_quantity"))
        if shortage_quantity is None or shortage_quantity < 0:
            errors.append(
                f"lcsc_availability.lines[{code}].shortage_quantity must be a non-negative integer"
            )
        if configured is True and shortage_quantity is not None and shortage_quantity > 0:
            parsed_shortage.append(code)

        if configured is True and stock is None:
            parsed_unknown_stock.append(code)

    if shortage_codes is not None and sorted(shortage_codes) != sorted(parsed_shortage):
        errors.append("lcsc_availability.shortage_codes mismatch")
    if unknown_stock_codes is not None and sorted(unknown_stock_codes) != sorted(parsed_unknown_stock):
        errors.append("lcsc_availability.unknown_stock_codes mismatch")

    if shortage_line_count is not None and shortage_line_count != len(parsed_shortage):
        errors.append("lcsc_availability.shortage_line_count mismatch")
    if unknown_stock_line_count is not None and unknown_stock_line_count != len(parsed_unknown_stock):
        errors.append("lcsc_availability.unknown_stock_line_count mismatch")

    passed = lcsc_availability.get("pass")
    if not isinstance(passed, bool):
        errors.append("lcsc_availability.pass must be true or false")
    else:
        if passed and (parsed_shortage or parsed_unknown_stock):
            errors.append("lcsc_availability.pass is true but shortage or unknown stock exists")
        if not passed and not (parsed_shortage or parsed_unknown_stock):
            errors.append("lcsc_availability.pass is false despite no shortages or unknown stock")


def _validate_footprint_state(
    footprint_state: dict[str, Any],
    errors: list[str],
) -> None:
    field_names = (
        "checked_count",
        "matched_count",
        "mismatch_count",
        "missing_spec_count",
        "unused_spec_count",
    )
    parsed_counts: dict[str, int] = {}
    for field_name in field_names:
        value = _as_int(footprint_state.get(field_name))
        if value is None:
            errors.append(
                f"footprint_state.{field_name} must be an integer, got {footprint_state.get(field_name)!r}"
            )
            continue
        parsed_counts[field_name] = value

    mismatch_entries_raw = footprint_state.get("mismatches")
    mismatch_entries: list[dict[str, str]] | None = None
    if not isinstance(mismatch_entries_raw, list):
        errors.append("footprint_state.mismatches must be a list")
    else:
        mismatch_entries = []
        seen_refs: set[str] = set()
        last_ref: str | None = None
        for index, entry in enumerate(mismatch_entries_raw):
            field_name = f"footprint_state.mismatches[{index}]"
            if not isinstance(entry, dict):
                errors.append(f"{field_name} must be a JSON object")
                continue
            ref = entry.get("ref")
            netlist_footprint = entry.get("netlist_footprint")
            spec_footprint = entry.get("spec_footprint")
            if not isinstance(ref, str) or not ref:
                errors.append(f"{field_name}.ref must be a non-empty string")
                continue
            if not isinstance(netlist_footprint, str) or not netlist_footprint:
                errors.append(f"{field_name}.netlist_footprint must be a non-empty string")
            if not isinstance(spec_footprint, str) or not spec_footprint:
                errors.append(f"{field_name}.spec_footprint must be a non-empty string")
            if last_ref is not None and ref < last_ref:
                errors.append("footprint_state.mismatches must be sorted by ref")
            last_ref = ref
            if ref in seen_refs:
                errors.append("footprint_state.mismatches must not contain duplicate refs")
            seen_refs.add(ref)
            if (
                isinstance(netlist_footprint, str)
                and isinstance(spec_footprint, str)
                and netlist_footprint == spec_footprint
            ):
                errors.append(
                    f"{field_name} must only contain actual mismatches"
                )
            mismatch_entries.append(
                {
                    "ref": ref,
                    "netlist_footprint": netlist_footprint,
                    "spec_footprint": spec_footprint,
                }
            )

    missing_spec_refs = _validate_string_list(
        footprint_state.get("missing_spec_refs"),
        "footprint_state.missing_spec_refs",
        errors,
    )
    unused_spec_refs = _validate_string_list(
        footprint_state.get("unused_spec_refs"),
        "footprint_state.unused_spec_refs",
        errors,
    )

    passed = footprint_state.get("pass")
    if passed not in (True, False):
        errors.append("footprint_state.pass must be true or false")

    checked_count = parsed_counts.get("checked_count")
    matched_count = parsed_counts.get("matched_count")
    mismatch_count = parsed_counts.get("mismatch_count")
    missing_spec_count = parsed_counts.get("missing_spec_count")
    unused_spec_count = parsed_counts.get("unused_spec_count")

    if mismatch_count is not None and mismatch_entries is not None and mismatch_count != len(mismatch_entries):
        errors.append(
            "footprint_state.mismatch_count mismatch: "
            f"{mismatch_count} != len(mismatches)"
        )
    if (
        missing_spec_count is not None
        and missing_spec_refs is not None
        and missing_spec_count != len(missing_spec_refs)
    ):
        errors.append(
            "footprint_state.missing_spec_count mismatch: "
            f"{missing_spec_count} != len(missing_spec_refs)"
        )
    if (
        unused_spec_count is not None
        and unused_spec_refs is not None
        and unused_spec_count != len(unused_spec_refs)
    ):
        errors.append(
            "footprint_state.unused_spec_count mismatch: "
            f"{unused_spec_count} != len(unused_spec_refs)"
        )
    if (
        checked_count is not None
        and matched_count is not None
        and mismatch_count is not None
        and checked_count != matched_count + mismatch_count
    ):
        errors.append(
            "footprint_state.checked_count mismatch: "
            f"{checked_count} != matched_count + mismatch_count"
        )
    if mismatch_count is not None and mismatch_count != 0:
        errors.append(
            f"footprint_state mismatch_count must be 0, got {mismatch_count!r}"
        )
    if missing_spec_count is not None and missing_spec_count != 0:
        errors.append(
            "footprint_state missing_spec_count must be 0, "
            f"got {missing_spec_count!r}"
        )
    if unused_spec_count is not None and unused_spec_count != 0:
        errors.append(
            "footprint_state unused_spec_count must be 0, "
            f"got {unused_spec_count!r}"
        )
    if (
        passed is True
        and mismatch_count is not None
        and missing_spec_count is not None
        and unused_spec_count is not None
        and (mismatch_count != 0 or missing_spec_count != 0 or unused_spec_count != 0)
    ):
        errors.append(
            "footprint_state.pass is true but footprint discrepancies remain"
        )
    if (
        passed is False
        and mismatch_count is not None
        and missing_spec_count is not None
        and unused_spec_count is not None
        and mismatch_count == 0
        and missing_spec_count == 0
        and unused_spec_count == 0
    ):
        errors.append(
            "footprint_state.pass is false but no footprint discrepancies remain"
        )


def _derive_physical_residual_pass(physical_residuals: dict[str, Any]) -> bool | None:
    component_placement = physical_residuals.get("component_placement")
    physical_intent_nets = physical_residuals.get("physical_intent_nets")
    if not isinstance(component_placement, dict) or not isinstance(physical_intent_nets, dict):
        return None

    unplaced_count = _as_int(component_placement.get("unplaced_count"))
    unused_placement_count = _as_int(component_placement.get("unused_placement_count"))
    if unplaced_count is None or unused_placement_count is None:
        return None

    missing_counts: list[int] = []
    for bucket in physical_intent_nets.values():
        if not isinstance(bucket, dict):
            return None
        missing_count = _as_int(bucket.get("missing_count"))
        if missing_count is None:
            return None
        missing_counts.append(missing_count)

    return unplaced_count == 0 and unused_placement_count == 0 and all(
        count == 0 for count in missing_counts
    )


def _validate_source_handoff(
    source_handoff: dict[str, Any],
    *,
    physical_residuals: Any,
    footprint_state: dict[str, Any] | None,
    errors: list[str],
) -> None:
    kind = _as_nonempty_string(source_handoff.get("kind"))
    if kind is None:
        errors.append(f"source_handoff.kind must be a non-empty string, got {source_handoff.get('kind')!r}")

    format_name = _as_nonempty_string(source_handoff.get("format"))
    if format_name is None:
        errors.append(
            f"source_handoff.format must be a non-empty string, got {source_handoff.get('format')!r}"
        )

    netlist = _as_nonempty_string(source_handoff.get("netlist"))
    if netlist is None:
        errors.append(
            f"source_handoff.netlist must be a non-empty string, got {source_handoff.get('netlist')!r}"
        )

    for field_name in (
        "netlist_exists",
        "physical_residual_pass",
        "footprint_state_pass",
        "pass",
    ):
        if _as_bool(source_handoff.get(field_name)) is None:
            errors.append(
                f"source_handoff.{field_name} must be true or false, got {source_handoff.get(field_name)!r}"
            )

    for field_name in ("component_count", "net_count"):
        value = _as_int(source_handoff.get(field_name))
        if value is None:
            errors.append(
                f"source_handoff.{field_name} must be an integer, got {source_handoff.get(field_name)!r}"
            )
        elif value < 0:
            errors.append(f"source_handoff.{field_name} must be >= 0, got {value!r}")

    netlist_exists = _as_bool(source_handoff.get("netlist_exists"))
    if netlist is not None and netlist_exists is not None:
        actual_exists = Path(netlist).exists()
        if netlist_exists != actual_exists:
            errors.append(
                f"source_handoff.netlist_exists does not match filesystem state for {netlist}"
            )

    if isinstance(physical_residuals, dict):
        component_placement = physical_residuals.get("component_placement")
        if isinstance(component_placement, dict):
            expected_component_count = _as_int(component_placement.get("total_non_helper_netlist_components"))
            actual_component_count = _as_int(source_handoff.get("component_count"))
            if (
                expected_component_count is not None
                and actual_component_count is not None
                and actual_component_count != expected_component_count
            ):
                errors.append(
                    "source_handoff.component_count does not match "
                    "physical_residuals.component_placement.total_non_helper_netlist_components"
                )
        derived_physical_residual_pass = _derive_physical_residual_pass(physical_residuals)
        actual_physical_residual_pass = _as_bool(source_handoff.get("physical_residual_pass"))
        if (
            derived_physical_residual_pass is not None
            and actual_physical_residual_pass is not None
            and actual_physical_residual_pass != derived_physical_residual_pass
        ):
            errors.append(
                "source_handoff.physical_residual_pass does not match physical_residuals"
            )

    if footprint_state is not None:
        actual_footprint_state_pass = _as_bool(source_handoff.get("footprint_state_pass"))
        expected_footprint_state_pass = _as_bool(footprint_state.get("pass"))
        if (
            actual_footprint_state_pass is not None
            and expected_footprint_state_pass is not None
            and actual_footprint_state_pass != expected_footprint_state_pass
        ):
            errors.append("source_handoff.footprint_state_pass does not match footprint_state.pass")

    actual_pass = _as_bool(source_handoff.get("pass"))
    if actual_pass is not None:
        derived_pass: bool | None = None
        if netlist_exists is not None:
            derived_physical_residual_pass = None
            if isinstance(physical_residuals, dict):
                derived_physical_residual_pass = _derive_physical_residual_pass(physical_residuals)
            expected_footprint_state_pass = (
                _as_bool(footprint_state.get("pass")) if footprint_state is not None else None
            )
            if derived_physical_residual_pass is not None and expected_footprint_state_pass is not None:
                derived_pass = (
                    netlist_exists and derived_physical_residual_pass and expected_footprint_state_pass
                )
        if derived_pass is not None and actual_pass != derived_pass:
            errors.append("source_handoff.pass contradicts netlist/residual/footprint evidence")

    atopile = source_handoff.get("atopile")
    if kind == "atopile":
        if not isinstance(atopile, dict):
            errors.append("source_handoff.atopile must be a JSON object when source_handoff.kind is atopile")
        else:
            for field_name in ("project", "ato_yaml", "build", "entry"):
                if _as_nonempty_string(atopile.get(field_name)) is None:
                    errors.append(
                        f"source_handoff.atopile.{field_name} must be a non-empty string, got {atopile.get(field_name)!r}"
                    )
    elif kind is not None and atopile is not None and not isinstance(atopile, dict):
        errors.append("source_handoff.atopile must be a JSON object when present")


def _validate_atopile_source_state(
    state: dict[str, Any],
    *,
    source_handoff: dict[str, Any] | None,
    errors: list[str],
) -> None:
    configured = _as_bool(state.get("configured"))
    if configured is None:
        errors.append(f"atopile_source_state.configured must be true or false, got {state.get('configured')!r}")
        return

    if _as_nonempty_string(state.get("netlist")) is None:
        errors.append(f"atopile_source_state.netlist must be a non-empty string, got {state.get('netlist')!r}")
    for field_name in ("netlist_exists", "netlist_newer_or_equal", "pass"):
        if _as_bool(state.get(field_name)) is None:
            errors.append(f"atopile_source_state.{field_name} must be true or false, got {state.get(field_name)!r}")
    for field_name in ("missing_source_count",):
        value = _as_int(state.get(field_name))
        if value is None or value < 0:
            errors.append(f"atopile_source_state.{field_name} must be a non-negative integer, got {state.get(field_name)!r}")
    for field_name in ("netlist_size_bytes",):
        value = state.get(field_name)
        if value is not None and (_as_int(value) is None or _as_int(value) < 0):
            errors.append(f"atopile_source_state.{field_name} must be null or a non-negative integer, got {value!r}")
    if state.get("netlist_sha256") is not None and not (
        isinstance(state.get("netlist_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", state["netlist_sha256"])
    ):
        errors.append("atopile_source_state.netlist_sha256 must be null or 64 lowercase hex chars")

    source_files = state.get("source_files")
    if not isinstance(source_files, list):
        errors.append("atopile_source_state.source_files must be a list")
        source_files = []
    missing_sources = state.get("missing_sources")
    if not isinstance(missing_sources, list) or not all(isinstance(item, str) for item in missing_sources):
        errors.append("atopile_source_state.missing_sources must be a list of strings")
        missing_sources = []

    seen_paths: list[str] = []
    computed_missing: list[str] = []
    newest_source_mtime_epoch: float | None = None
    for index, item in enumerate(source_files):
        field = f"atopile_source_state.source_files[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{field} must be a JSON object")
            continue
        path = _as_nonempty_string(item.get("path"))
        if path is None:
            errors.append(f"{field}.path must be a non-empty string")
            continue
        seen_paths.append(path)
        exists = _as_bool(item.get("exists"))
        if exists is None:
            errors.append(f"{field}.exists must be true or false")
            continue
        size = item.get("size_bytes")
        digest = item.get("sha256")
        mtime = item.get("mtime_epoch")
        if exists:
            if _as_int(size) is None or _as_int(size) < 0:
                errors.append(f"{field}.size_bytes must be a non-negative integer when exists=true")
            if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest)):
                errors.append(f"{field}.sha256 must be 64 lowercase hex chars when exists=true")
            if not isinstance(mtime, (int, float)):
                errors.append(f"{field}.mtime_epoch must be numeric when exists=true")
            elif newest_source_mtime_epoch is None or float(mtime) > newest_source_mtime_epoch:
                newest_source_mtime_epoch = float(mtime)
        else:
            computed_missing.append(path)
    if seen_paths != sorted(seen_paths):
        errors.append("atopile_source_state.source_files must be sorted by path")

    if sorted(missing_sources) != sorted(computed_missing):
        errors.append("atopile_source_state.missing_sources contradicts source_files existence")
    missing_source_count = _as_int(state.get("missing_source_count"))
    if missing_source_count is not None and missing_source_count != len(missing_sources):
        errors.append("atopile_source_state.missing_source_count mismatch with missing_sources")

    stated_newest = state.get("newest_source_mtime_epoch")
    if newest_source_mtime_epoch is None:
        if stated_newest is not None:
            errors.append("atopile_source_state.newest_source_mtime_epoch must be null when no sources exist")
    elif not isinstance(stated_newest, (int, float)) or float(stated_newest) != newest_source_mtime_epoch:
        errors.append("atopile_source_state.newest_source_mtime_epoch contradicts source_files mtimes")

    if source_handoff is not None:
        handoff_netlist = _as_nonempty_string(source_handoff.get("netlist"))
        state_netlist = _as_nonempty_string(state.get("netlist"))
        if handoff_netlist is not None and state_netlist is not None and handoff_netlist != state_netlist:
            errors.append("atopile_source_state.netlist must match source_handoff.netlist")

    state_pass = _as_bool(state.get("pass"))
    netlist_exists = _as_bool(state.get("netlist_exists"))
    netlist_newer_or_equal = _as_bool(state.get("netlist_newer_or_equal"))
    if state_pass is not None and configured is not None:
        if configured:
            derived = (
                netlist_exists is True
                and netlist_newer_or_equal is True
                and len(missing_sources) == 0
            )
            if state_pass != derived:
                errors.append("atopile_source_state.pass contradicts missing source or freshness evidence")
        elif state_pass is not True:
            errors.append("atopile_source_state.pass must be true when configured=false")


def _validate_drc_source_coverage(
    coverage: dict[str, Any],
    drc: dict[str, Any] | None,
    errors: list[str],
) -> None:
    field_names = (
        "violation_count",
        "unconnected_count",
        "attributed_violation_count",
        "unattributed_violation_count",
        "attributed_unconnected_count",
        "unattributed_unconnected_count",
    )
    parsed_counts: dict[str, int] = {}
    for field_name in field_names:
        value = _as_int(coverage.get(field_name))
        if value is None:
            errors.append(
                f"drc_source_coverage.{field_name} must be an integer, got {coverage.get(field_name)!r}"
            )
            continue
        parsed_counts[field_name] = value

    passed = coverage.get("pass")
    if passed not in (True, False):
        errors.append("drc_source_coverage.pass must be true or false")

    violation_kinds = coverage.get("violation_source_kinds")
    unconnected_kinds = coverage.get("unconnected_source_kinds")
    if not isinstance(violation_kinds, dict):
        errors.append("drc_source_coverage.violation_source_kinds must be a JSON object")
    else:
        _validate_count_mapping(
            violation_kinds,
            "drc_source_coverage.violation_source_kinds",
            errors,
        )
    if not isinstance(unconnected_kinds, dict):
        errors.append("drc_source_coverage.unconnected_source_kinds must be a JSON object")
    else:
        _validate_count_mapping(
            unconnected_kinds,
            "drc_source_coverage.unconnected_source_kinds",
            errors,
        )

    violation_count = parsed_counts.get("violation_count")
    unattributed_violation_count = parsed_counts.get("unattributed_violation_count")
    attributed_violation_count = parsed_counts.get("attributed_violation_count")
    unconnected_count = parsed_counts.get("unconnected_count")
    unattributed_unconnected_count = parsed_counts.get("unattributed_unconnected_count")
    attributed_unconnected_count = parsed_counts.get("attributed_unconnected_count")

    if (
        violation_count is not None
        and attributed_violation_count is not None
        and unattributed_violation_count is not None
        and violation_count != attributed_violation_count + unattributed_violation_count
    ):
        errors.append(
            "drc_source_coverage.violation_count mismatch: "
            f"{violation_count} != attributed_violation_count + unattributed_violation_count"
        )
    if (
        unconnected_count is not None
        and attributed_unconnected_count is not None
        and unattributed_unconnected_count is not None
        and unconnected_count != attributed_unconnected_count + unattributed_unconnected_count
    ):
        errors.append(
            "drc_source_coverage.unconnected_count mismatch: "
            f"{unconnected_count} != attributed_unconnected_count + unattributed_unconnected_count"
        )

    if drc is not None:
        drc_violation_count = _as_int(drc.get("violation_count"))
        drc_unconnected_count = _as_int(drc.get("unconnected_count"))
        if violation_count is not None and drc_violation_count is not None and violation_count != drc_violation_count:
            errors.append(
                "drc_source_coverage.violation_count does not match drc.violation_count"
            )
        if (
            unconnected_count is not None
            and drc_unconnected_count is not None
            and unconnected_count != drc_unconnected_count
        ):
            errors.append(
                "drc_source_coverage.unconnected_count does not match drc.unconnected_count"
            )

    if (
        unattributed_violation_count is not None
        and unattributed_unconnected_count is not None
        and passed is True
        and (unattributed_violation_count != 0 or unattributed_unconnected_count != 0)
    ):
        errors.append(
            "drc_source_coverage.pass is true but unattributed DRC entries remain"
        )
    if (
        unattributed_violation_count is not None
        and unattributed_unconnected_count is not None
        and passed is False
        and unattributed_violation_count == 0
        and unattributed_unconnected_count == 0
    ):
        errors.append(
            "drc_source_coverage.pass is false but all DRC entries are attributed"
        )


def _validate_count_mapping(
    mapping: dict[str, Any],
    field_name: str,
    errors: list[str],
) -> None:
    sorted_keys = sorted(mapping)
    if list(mapping) != sorted_keys:
        errors.append(f"{field_name} keys must be sorted")
    for key, value in mapping.items():
        if not isinstance(key, str) or not key:
            errors.append(f"{field_name} keys must be non-empty strings")
        if _as_int(value) is None:
            errors.append(f"{field_name}.{key} must be an integer, got {value!r}")


def _validate_route_source_coverage(
    coverage: dict[str, Any],
    routes: dict[str, Any] | None,
    route_layer_usage: dict[str, Any] | None,
    errors: list[str],
) -> None:
    field_names = (
        "committed_entry_count",
        "named_entry_count",
        "source_mapped_entry_count",
        "unnamed_entry_count",
        "unmapped_named_entry_count",
    )
    parsed_counts: dict[str, int] = {}
    for field_name in field_names:
        value = _as_int(coverage.get(field_name))
        if value is None:
            errors.append(
                f"route_source_coverage.{field_name} must be an integer, got {coverage.get(field_name)!r}"
            )
        else:
            parsed_counts[field_name] = value

    passed = coverage.get("pass")
    if passed not in (True, False):
        errors.append("route_source_coverage.pass must be true or false")

    strategy_counts = coverage.get("strategy_counts")
    if not isinstance(strategy_counts, dict):
        errors.append("route_source_coverage.strategy_counts must be a JSON object")
    else:
        _validate_count_mapping(
            strategy_counts,
            "route_source_coverage.strategy_counts",
            errors,
        )

    unmapped_named_entries = coverage.get("unmapped_named_entries")
    if not isinstance(unmapped_named_entries, list):
        errors.append("route_source_coverage.unmapped_named_entries must be a list")
        unmapped_named_entries = None

    parsed_unmapped: list[dict[str, Any]] = []
    observed_unmapped_keys: set[tuple[str, str, str, int | None]] = set()
    if unmapped_named_entries is not None:
        for index, entry in enumerate(unmapped_named_entries):
            field_name = f"route_source_coverage.unmapped_named_entries[{index}]"
            if not isinstance(entry, dict):
                errors.append(f"{field_name} must be a JSON object")
                continue
            net = entry.get("net")
            strategy = entry.get("strategy")
            route_name = entry.get("route_name")
            route_index = entry.get("route_index")
            if not isinstance(net, str) or not net:
                errors.append(f"{field_name}.net must be a non-empty string")
            if not isinstance(strategy, str) or not strategy:
                errors.append(f"{field_name}.strategy must be a non-empty string")
            if not isinstance(route_name, str) or not route_name:
                errors.append(f"{field_name}.route_name must be a non-empty string")
            if route_index is not None and not isinstance(route_index, int):
                errors.append(f"{field_name}.route_index must be an integer or null")
            if (
                isinstance(net, str)
                and isinstance(strategy, str)
                and isinstance(route_name, str)
                and (route_index is None or isinstance(route_index, int))
            ):
                entry_key = (net, strategy, route_name, route_index)
            else:
                entry_key = None
            if isinstance(entry_key, tuple):
                if entry_key in observed_unmapped_keys:
                    errors.append("route_source_coverage.unmapped_named_entries must not contain duplicates")
                observed_unmapped_keys.add(entry_key)
            parsed_unmapped.append(
                {
                    "net": str(net) if isinstance(net, str) else "",
                    "strategy": str(strategy) if isinstance(strategy, str) else "",
                    "route_name": str(route_name) if isinstance(route_name, str) else "",
                    "route_index": route_index,
                }
            )

    if unmapped_named_entries is not None:
        sorted_unmapped = sorted(
            parsed_unmapped,
            key=lambda item: (
                item["net"],
                item["strategy"],
                item["route_name"],
                -1 if item["route_index"] is None else item["route_index"],
            ),
        )
        if parsed_unmapped != sorted_unmapped:
            errors.append(
                "route_source_coverage.unmapped_named_entries must be sorted "
                "by net, strategy, route_name, route_index"
            )

    committed_entry_count = parsed_counts.get("committed_entry_count")
    named_entry_count = parsed_counts.get("named_entry_count")
    source_mapped_entry_count = parsed_counts.get("source_mapped_entry_count")
    unnamed_entry_count = parsed_counts.get("unnamed_entry_count")
    unmapped_named_entry_count = parsed_counts.get("unmapped_named_entry_count")

    if route_layer_usage is not None:
        route_layer_usage_committed_count = _as_int(
            route_layer_usage.get("committed_entry_count")
        )
        if (
            route_layer_usage_committed_count is not None
            and committed_entry_count is not None
            and committed_entry_count != route_layer_usage_committed_count
        ):
            errors.append(
                "route_source_coverage.committed_entry_count does not match "
                "route_layer_usage.committed_entry_count"
            )
    elif (
        routes is not None
        and isinstance(routes.get("committed"), int)
        and committed_entry_count is not None
        and committed_entry_count != routes["committed"]
    ):
        errors.append(
            "route_source_coverage.committed_entry_count does not match routes.committed"
        )

    if (
        committed_entry_count is not None
        and named_entry_count is not None
        and unnamed_entry_count is not None
        and committed_entry_count != named_entry_count + unnamed_entry_count
    ):
        errors.append(
            "route_source_coverage.committed_entry_count mismatch: "
            f"{committed_entry_count} != named_entry_count + unnamed_entry_count"
        )
    if (
        named_entry_count is not None
        and source_mapped_entry_count is not None
        and unmapped_named_entry_count is not None
        and named_entry_count != source_mapped_entry_count + unmapped_named_entry_count
    ):
        errors.append(
            "route_source_coverage.named_entry_count mismatch: "
            "named_entry_count != source_mapped_entry_count + unmapped_named_entry_count"
        )
    if (
        unmapped_named_entry_count is not None
        and len(parsed_unmapped) != unmapped_named_entry_count
    ):
        errors.append(
            "route_source_coverage.unmapped_named_entry_count mismatch: "
            f"{unmapped_named_entry_count} != len(unmapped_named_entries)"
        )
    if strategy_counts is not None and isinstance(strategy_counts, dict):
        strategy_count_sum = sum(value for value in strategy_counts.values() if _as_int(value) is not None)
        if committed_entry_count is not None and strategy_count_sum != committed_entry_count:
            errors.append(
                "route_source_coverage.strategy_counts does not sum to committed_entry_count"
            )

    if (
        passed is False
        and source_mapped_entry_count is not None
        and unmapped_named_entry_count is not None
        and named_entry_count is not None
        and source_mapped_entry_count == named_entry_count
        and unmapped_named_entry_count == 0
        and named_entry_count > 0
    ):
        errors.append(
            "route_source_coverage.pass is false but all named committed entries are mapped"
        )
    if (
        passed is True
        and unmapped_named_entry_count is not None
        and unmapped_named_entry_count > 0
    ):
        errors.append(
            "route_source_coverage.pass is true but unmapped named route entries remain"
        )


def _cross_check_bom_state_against_lcsc_policy(
    bom_state: dict[str, Any],
    lcsc_policy: dict[str, Any],
    errors: list[str],
) -> None:
    field_pairs = (
        ("mapped_count", "mapped"),
        ("missing_count", "missing"),
        ("excepted_count", "excepted"),
        ("mapped_refs", "mapped_refs"),
        ("missing_refs", "missing_refs"),
        ("excepted_refs", "excepted_refs"),
    )
    for bom_field, policy_field in field_pairs:
        if bom_state.get(bom_field) != lcsc_policy.get(policy_field):
            errors.append(
                f"bom_state.{bom_field} does not match lcsc_policy.{policy_field}"
            )


def _validate_generated_artifact(name: str, path: Path) -> list[str]:
    if not path.exists():
        return [f"artifact {name} missing: {path}"]
    if path.is_dir():
        if not any(child.is_file() for child in path.rglob("*")):
            return [f"artifact {name} directory is empty: {path}"]
        return []
    if path.stat().st_size <= 0:
        return [f"artifact {name} file is empty: {path}"]
    return []


def _validate_archive_summary(archive_path: Path, raw_summary_text: str) -> list[str]:
    errors: list[str] = []
    if archive_path.suffix.lower() != ".zip":
        return errors
    try:
        with zipfile.ZipFile(archive_path) as archive:
            try:
                embedded_summary = archive.read("build-summary.json").decode("utf-8")
            except KeyError:
                return errors
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"artifact manufacturing_archive is not a readable zip: {archive_path} ({exc})"]

    if embedded_summary != raw_summary_text:
        errors.append(
            "manufacturing archive contains a stale build-summary.json payload "
            f"({archive_path})"
        )
    return errors
