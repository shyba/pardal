"""Compiler for text-defined physical design specs."""

from __future__ import annotations

import subprocess
import sqlite3
from dataclasses import dataclass, field
import json
import hashlib
import math
import csv
from pathlib import Path
import re
import tempfile
from typing import Any
import zipfile

from pardal.data_model import Board, Component, NetClass, Pad, STANDARD_LAYER_STACKS
from pardal.kicad_cli_exports import export_drill, export_gerbers
from pardal.netlist_reader import NetlistReader
from pardal.physical.commit_gate import CommitViolation
from pardal.physical.fanout import compile_fanouts
from pardal.physical.power import apply_planes, apply_power_stitches
from pardal.physical.routes import (
    RouteFailureReport,
    RouteReportEntry,
    RouteCommitFailureError,
    apply_routes,
)
from pardal.physical.spec import (
    ALLOWED_LAYER_ROLES,
    SOURCE_LOCATION_KEY,
    PhysicalSpec,
    SourceLocation,
    load_physical_spec,
)
from pardal.production_checks import (
    CheckContext,
    load_source_contract,
    run_production_checks,
)
from pardal.production_checks.models import SourceContract


STACKUP_LAYERS = {
    "two_layer": STANDARD_LAYER_STACKS[2],
    "2layer": STANDARD_LAYER_STACKS[2],
    "2_layer": STANDARD_LAYER_STACKS[2],
    "four_layer": STANDARD_LAYER_STACKS[4],
    "4layer": STANDARD_LAYER_STACKS[4],
    "4_layer": STANDARD_LAYER_STACKS[4],
}

JLCPCB_PANELIZATION_MODES = {"single_board", "vendor_panel", "customer_panel"}
VALIDATION_TEST_KINDS = {
    "power_on",
    "programming",
    "debug_interface",
    "interface_loopback",
    "analog_measurement",
    "fault_state",
    "visual_inspection",
}
# Conservative floor: enough rail to express explicit customer-owned handling
# without implying we can generate panel geometry from it.
CUSTOMER_PANEL_MIN_RAIL_WIDTH_MM = 5.0


@dataclass
class PlacementReportEntry:
    ref: str
    footprint: str
    x: float
    y: float
    rotation: float


@dataclass
class CompilePhysicalResult:
    output: Path
    placement_report: list[PlacementReportEntry] = field(default_factory=list)
    route_report: list[RouteReportEntry] = field(default_factory=list)
    commit_violations: list[CommitViolation] = field(default_factory=list)
    drc_unconnected: list["DrcUnconnectedEntry"] = field(default_factory=list)
    drc_violations: list["DrcViolationEntry"] = field(default_factory=list)
    production_checks: list["ProductionCheckEntry"] = field(default_factory=list)
    lcsc_policy_summary: "LcscPolicySummary | None" = None
    lcsc_database_summary: "LcscDatabaseSummary | None" = None
    physical_residuals: dict[str, Any] = field(default_factory=dict)
    footprint_state: dict[str, Any] = field(default_factory=dict)
    source_handoff: dict[str, Any] = field(default_factory=dict)
    package_physical_context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    drc_returncode: int | None = None
    route_failures: list[RouteFailureReport] = field(default_factory=list)


@dataclass(frozen=True)
class ProductionCheckEntry:
    severity: str
    code: str
    message: str
    source: str = ""
    stage: str = ""
    package: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    source_details: dict[str, Any] = field(default_factory=dict)
    waived: bool = False
    waiver_reason: str = ""


def escalate_production_warnings(entries: list["ProductionCheckEntry"]) -> list["ProductionCheckEntry"]:
    return [
        ProductionCheckEntry(
            severity="error" if entry.severity == "warning" else entry.severity,
            code=entry.code,
            message=entry.message,
            source=entry.source,
            stage=entry.stage,
            package=entry.package,
            evidence=dict(entry.evidence),
            source_details=dict(entry.source_details),
            waived=entry.waived,
            waiver_reason=entry.waiver_reason,
        )
        for entry in entries
    ]


def format_production_checks(entries: list["ProductionCheckEntry"]) -> str:
    lines = [f"production_checks: {len(entries)}"]
    for entry in entries:
        source = f" @ {entry.source}" if entry.source else ""
        lines.append(f"{entry.severity}\t{entry.code}\t{entry.message}{source}")
    return "\n".join(lines) + "\n"


def _build_dfm_report(entries: list["ProductionCheckEntry"]) -> dict[str, Any]:
    by_severity: dict[str, int] = {}
    by_code: dict[str, dict[str, Any]] = {}
    for entry in entries:
        by_severity[entry.severity] = by_severity.get(entry.severity, 0) + 1
        code_entry = by_code.setdefault(
            entry.code,
            {
                "count": 0,
                "severities": set(),
                "sources": set(),
                "messages": set(),
            },
        )
        code_entry["count"] += 1
        code_entry["severities"].add(entry.severity)
        if entry.source:
            code_entry["sources"].add(entry.source)
        code_entry["messages"].add(entry.message)

    return {
        "count": len(entries),
        "error_count": by_severity.get("error", 0),
        "warning_count": by_severity.get("warning", 0),
        "by_severity": {
            severity: by_severity[severity]
            for severity in sorted(by_severity)
        },
        "by_code": {
            code: {
                "count": code_entry["count"],
                "severities": sorted(code_entry["severities"]),
                "sources": sorted(code_entry["sources"]),
                "messages": sorted(code_entry["messages"]),
            }
            for code, code_entry in sorted(by_code.items())
        },
    }


def _build_validation_summary(spec: PhysicalSpec) -> dict[str, Any]:
    return {
        "count": len(spec.validation_tests),
        "kinds": sorted(
            {
                test.kind
                for test in spec.validation_tests
                if isinstance(test.kind, str) and test.kind.strip()
            }
        ),
        "names": [
            test.name
            for test in spec.validation_tests
            if isinstance(test.name, str) and test.name.strip()
        ],
    }


def _build_mechanical_features_summary(spec: PhysicalSpec) -> dict[str, Any]:
    def _edge_margin_to_board(x: float, y: float) -> float:
        return min(
            x,
            y,
            max(0.0, spec.width - x),
            max(0.0, spec.height - y),
        )

    fiducials = sorted(spec.fiducials, key=lambda intent: intent.name)
    mounting_holes = sorted(spec.mounting_holes, key=lambda intent: intent.name)

    fiducial_entries: dict[str, dict[str, Any]] = {}
    fiducial_edge_margins: list[float] = []
    for fiducial in fiducials:
        fid_diameter = fiducial.diameter if fiducial.diameter is not None else 1.0
        edge_margin = _edge_margin_to_board(fiducial.at[0], fiducial.at[1]) - (fid_diameter / 2.0)
        clearance = fiducial.clearance
        clearance_edge_margin = (
            edge_margin - clearance if clearance is not None else None
        )
        entry = {
            "x_mm": fiducial.at[0],
            "y_mm": fiducial.at[1],
            "diameter_mm": fid_diameter,
            "clearance_mm": clearance,
            "edge_margin_mm": edge_margin,
            "clearance_edge_margin_mm": clearance_edge_margin,
        }
        fiducial_entries[fiducial.name] = entry
        fiducial_edge_margins.append(edge_margin)

    mounting_hole_entries: dict[str, dict[str, Any]] = {}
    mounting_hole_edge_margins: list[float] = []
    for mounting_hole in mounting_holes:
        edge_margin = (
            _edge_margin_to_board(mounting_hole.at[0], mounting_hole.at[1])
            - (mounting_hole.diameter / 2.0)
        )
        entry = {
            "x_mm": mounting_hole.at[0],
            "y_mm": mounting_hole.at[1],
            "diameter_mm": mounting_hole.diameter,
            "drill_mm": mounting_hole.drill,
            "edge_margin_mm": edge_margin,
        }
        mounting_hole_entries[mounting_hole.name] = entry
        mounting_hole_edge_margins.append(edge_margin)

    return {
        "board_width_mm": spec.width,
        "board_height_mm": spec.height,
        "fiducial_count": len(fiducial_entries),
        "fiducial_names": [name for name in fiducial_entries],
        "fiducials": fiducial_entries,
        "mounting_hole_count": len(mounting_hole_entries),
        "mounting_hole_names": [name for name in mounting_hole_entries],
        "mounting_holes": mounting_hole_entries,
        "min_fiducial_edge_margin_mm": min(fiducial_edge_margins)
        if fiducial_edge_margins
        else None,
        "min_mounting_hole_edge_margin_mm": min(mounting_hole_edge_margins)
        if mounting_hole_edge_margins
        else None,
        "pass": (
            all(margin >= 0.0 for margin in fiducial_edge_margins)
            and all(margin >= 0.0 for margin in mounting_hole_edge_margins)
        ),
    }


def _build_manufacturing_geometry_summary(board: Board, spec: PhysicalSpec) -> dict[str, Any]:
    segments = [segment for net in board.nets.values() for segment in net.segments]
    vias = [via for net in board.nets.values() for via in net.vias]
    layers_used = sorted(
        {
            layer
            for segment in segments
            for layer in (segment.layer,)
        }
        | {
            layer
            for via in vias
            for layer in via.layers
        }
    )

    min_trace_width = min((segment.width for segment in segments), default=None)
    min_via_drill = min((via.drill for via in vias), default=None)
    min_via_diameter = min((via.size for via in vias), default=None)

    thresholds = {
        "default_trace_width_mm": min(
            [net_class.width for net_class in spec.rules.netclasses.values()],
            default=None,
        ),
        "default_clearance_mm": spec.rules.default_clearance,
        "default_via_drill_mm": min(
            [
                net_class.via.drill
                for net_class in spec.rules.netclasses.values()
                if net_class.via is not None
            ],
            default=None,
        ),
        "default_via_diameter_mm": min(
            [
                net_class.via.diameter
                for net_class in spec.rules.netclasses.values()
                if net_class.via is not None
            ],
            default=None,
        ),
    }
    violations: list[str] = []
    if (
        min_trace_width is not None
        and thresholds["default_trace_width_mm"] is not None
        and min_trace_width < thresholds["default_trace_width_mm"]
    ):
        violations.append("min_trace_width_below_rules_default")
    if (
        min_via_drill is not None
        and thresholds["default_via_drill_mm"] is not None
        and min_via_drill < thresholds["default_via_drill_mm"]
    ):
        violations.append("min_via_drill_below_rules_default")
    if (
        min_via_diameter is not None
        and thresholds["default_via_diameter_mm"] is not None
        and min_via_diameter < thresholds["default_via_diameter_mm"]
    ):
        violations.append("min_via_diameter_below_rules_default")
    if min_via_drill is not None and min_via_diameter is not None and min_via_drill >= min_via_diameter:
        violations.append("min_via_drill_not_smaller_than_diameter")

    return {
        "trace_segment_count": len(segments),
        "via_count": len(vias),
        "copper_zone_count": len(board.zones),
        "min_trace_width_mm": min_trace_width,
        "min_via_drill_mm": min_via_drill,
        "min_via_diameter_mm": min_via_diameter,
        "layers_used": layers_used,
        "thresholds": thresholds,
        "violations": sorted(set(violations)),
        "violation_count": len(set(violations)),
        "pass": len(violations) == 0,
    }


def _validation_results_template_filename() -> str:
    return "validation-results.template.json"


def _build_validation_results_template_payload(
    spec: PhysicalSpec,
    *,
    summary_output: Path | None,
) -> dict[str, Any]:
    tests = []
    for test in spec.validation_tests:
        tests.append(
            {
                "name": test.name,
                "kind": test.kind,
                "criteria": test.criteria,
                "net": test.net,
                "rail": test.rail,
                "source": _source_display(test.raw),
                "status": "not_run",
            }
        )
    payload: dict[str, Any] = {
        "status": "template",
        "results": tests,
    }
    if summary_output is not None:
        payload["generated_from"] = {"build_summary": str(summary_output.resolve())}
    return payload


def _write_validation_results_template(
    spec: PhysicalSpec,
    output_path: Path,
    *,
    summary_output: Path | None,
    generated_artifacts: set[Path],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _build_validation_results_template_payload(
        spec,
        summary_output=summary_output,
    )
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    generated_artifacts.add(output_path.resolve())


def _build_validation_results_template_summary(
    spec: PhysicalSpec,
    template_output: Path | None,
    *,
    generated_artifacts: set[Path],
) -> dict[str, Any]:
    names = sorted(
        [
        test.name
        for test in spec.validation_tests
        if isinstance(test.name, str) and test.name.strip()
        ]
    )
    generated = (
        template_output is not None and template_output.resolve() in generated_artifacts
    )
    return {
        "status": "template",
        "generated": generated,
        "path": str(template_output.resolve()) if generated and template_output is not None else None,
        "test_count": len(spec.validation_tests),
        "names": names,
        "pass": generated,
    }


def _build_layer_role_summary(spec: PhysicalSpec) -> dict[str, Any]:
    layers = {
        layer: spec.layer_roles[layer]
        for layer in sorted(spec.layer_roles)
    }
    role_buckets: dict[str, list[str]] = {}
    for layer, role in layers.items():
        role_buckets.setdefault(role, []).append(layer)
    return {
        "count": len(layers),
        "layers": layers,
        "role_buckets": {
            role: sorted(role_buckets[role])
            for role in sorted(role_buckets)
        },
    }


def _route_intent_name(raw: dict[str, Any], index: int) -> str:
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    kind = str(raw.get("kind") or raw.get("strategy") or "route")
    return f"{kind}[{index + 1:04d}]"


def _route_intent_nets(raw: dict[str, Any]) -> list[str]:
    nets: set[str] = set()
    net = raw.get("net")
    if net is not None:
        text = str(net).strip()
        if text:
            nets.add(text)
    raw_nets = raw.get("nets")
    if isinstance(raw_nets, list):
        for item in raw_nets:
            text = str(item).strip()
            if text:
                nets.add(text)
    return sorted(nets)


def _route_group_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    kind = str(raw.get("kind") or "").strip()
    if kind == "route_group":
        metadata["route_group_name"] = _route_intent_name(raw, 0)
        metadata["route_group_source_kind"] = kind
    library = raw.get("library")
    if isinstance(library, dict):
        entry_id = library.get("entry_id")
        if isinstance(entry_id, str) and entry_id.strip():
            metadata["library_entry_id"] = entry_id.strip()
        pattern_family = library.get("pattern_family")
        if isinstance(pattern_family, str) and pattern_family.strip():
            metadata["pattern_family"] = pattern_family.strip()
        expanded_by = library.get("expanded_by")
        if isinstance(expanded_by, str) and expanded_by.strip():
            metadata["library_expanded_by"] = expanded_by.strip()
        catalog_schema_version = library.get("catalog_schema_version")
        if isinstance(catalog_schema_version, int):
            metadata["library_catalog_schema_version"] = catalog_schema_version
    schema_version = raw.get("schema_version")
    if isinstance(schema_version, int):
        metadata["schema_version"] = schema_version
    description = raw.get("description")
    if isinstance(description, str) and description.strip():
        metadata["description"] = description.strip()
    return metadata


def _build_route_group_summary(
    spec: PhysicalSpec,
    *,
    enabled_route_groups: set[str] | None,
) -> dict[str, Any]:
    grouped_entries: dict[str, list[tuple[str, list[str]]]] = {}
    ungrouped_entries: list[tuple[str, list[str]]] = []
    declared_groups: set[str] = set()
    route_group_intents: list[dict[str, Any]] = []
    active_route_intents = 0

    for index, intent in enumerate(spec.routes):
        raw = intent.raw
        route_name = _route_intent_name(raw, index)
        route_nets = _route_intent_nets(raw)
        route_group_metadata = _route_group_metadata(raw)
        groups = sorted(set(_route_groups(raw)))
        is_active = (
            enabled_route_groups is None
            or not groups
            or any(group in enabled_route_groups for group in groups)
        )
        if is_active:
            active_route_intents += 1
        if route_group_metadata:
            route_group_intents.append(
                {
                    "name": route_name,
                    "route_index": index,
                    "source": _source_display(raw),
                    **route_group_metadata,
                }
            )
        if groups:
            declared_groups.update(groups)
            for group in groups:
                grouped_entries.setdefault(group, []).append((route_name, route_nets))
        else:
            ungrouped_entries.append((route_name, route_nets))

    enabled_filter = (
        sorted(declared_groups)
        if enabled_route_groups is None
        else sorted(str(group) for group in enabled_route_groups)
    )

    return {
        "enabled_filter": enabled_filter,
        "filter_includes_ungrouped": True,
        "total_route_intents": len(spec.routes),
        "active_route_intents": active_route_intents,
        "route_group_intents": sorted(
            route_group_intents,
            key=lambda entry: (
                str(entry["name"]),
                -1 if entry["route_index"] is None else entry["route_index"],
            ),
        ),
        "declared_groups": [
            {
                "name": group,
                "active": enabled_route_groups is None or group in enabled_route_groups,
                "route_intent_count": len(entries),
                "route_names": sorted(route_name for route_name, _nets in entries),
                "nets": sorted({net for _route_name, nets in entries for net in nets}),
            }
            for group, entries in sorted(grouped_entries.items())
        ],
        "ungrouped": {
            "active": True,
            "route_intent_count": len(ungrouped_entries),
            "route_names": sorted(route_name for route_name, _nets in ungrouped_entries),
            "nets": sorted({net for _route_name, nets in ungrouped_entries for net in nets}),
        },
    }


def _build_route_layer_usage(
    route_report: list[RouteReportEntry],
    *,
    route_metadata_by_index: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    committed_entries = [
        entry
        for entry in route_report
        if entry.committed and (entry.used_layers or entry.segment_layers or entry.via_layers)
    ]
    by_layer: dict[str, set[str]] = {}
    for entry in committed_entries:
        for layer in entry.segment_layers:
            by_layer.setdefault(layer, set()).add(entry.net)
    return {
        "committed_entry_count": len(committed_entries),
        "entries": [
            {
                "net": entry.net,
                "strategy": entry.strategy,
                "route_name": entry.route_name,
                "route_index": entry.route_index,
                "source": entry.source,
                **(
                    {"alternative_name": entry.alternative_name}
                    if entry.alternative_name
                    else {}
                ),
                **route_metadata_by_index.get(entry.route_index, {}),
                "used_layers": list(entry.used_layers),
                "segment_layers": list(entry.segment_layers),
                "via_layers": [list(layer_span) for layer_span in entry.via_layers],
            }
            for entry in committed_entries
        ],
        "segment_nets_by_layer": {
            layer: sorted(nets)
            for layer, nets in sorted(by_layer.items())
        },
    }


def _build_route_source_coverage(
    route_report: list[RouteReportEntry],
    *,
    route_metadata_by_index: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    committed_entries = [
        entry
        for entry in route_report
        if entry.committed and (entry.used_layers or entry.segment_layers or entry.via_layers)
    ]
    named_entries = [
        entry
        for entry in committed_entries
        if str(entry.route_name).strip()
    ]
    source_mapped_named_entries = [
        entry
        for entry in named_entries
        if str(entry.source).strip()
    ]
    unmapped_named_entries = sorted(
        (
            {
                "net": entry.net,
                "strategy": entry.strategy,
                "route_name": entry.route_name,
                "route_index": entry.route_index,
                **route_metadata_by_index.get(entry.route_index, {}),
            }
            for entry in named_entries
            if not str(entry.source).strip()
        ),
        key=lambda entry: (
            str(entry["net"]),
            str(entry["strategy"]),
            str(entry["route_name"]),
            -1 if entry["route_index"] is None else entry["route_index"],
        ),
    )
    strategy_counts: dict[str, int] = {}
    for entry in committed_entries:
        strategy_counts[entry.strategy] = strategy_counts.get(entry.strategy, 0) + 1

    committed_entry_count = len(committed_entries)
    named_entry_count = len(named_entries)
    source_mapped_entry_count = len(source_mapped_named_entries)
    unnamed_entry_count = committed_entry_count - named_entry_count
    unmapped_named_entry_count = len(unmapped_named_entries)

    return {
        "committed_entry_count": committed_entry_count,
        "named_entry_count": named_entry_count,
        "source_mapped_entry_count": source_mapped_entry_count,
        "unnamed_entry_count": unnamed_entry_count,
        "unmapped_named_entry_count": unmapped_named_entry_count,
        "unmapped_named_entries": unmapped_named_entries,
        "strategy_counts": {
            strategy: strategy_counts[strategy]
            for strategy in sorted(strategy_counts)
        },
        "pass": named_entry_count == source_mapped_entry_count,
    }


def _build_route_group_metadata_lookup(
    spec: PhysicalSpec,
) -> dict[int, dict[str, Any]]:
    metadata_by_route_index: dict[int, dict[str, Any]] = {}
    for index, intent in enumerate(spec.routes):
        if index in metadata_by_route_index:
            continue
        metadata_by_route_index[index] = _route_group_metadata(intent.raw)
    return metadata_by_route_index


def _bom_state_payload(summary: "BomStateSummary") -> dict[str, Any]:
    return {
        "excepted_count": summary.excepted_count,
        "excepted_refs": list(summary.excepted_refs),
        "mapped_count": summary.mapped_count,
        "mapped_refs": list(summary.mapped_refs),
        "missing_count": summary.missing_count,
        "missing_refs": list(summary.missing_refs),
        "part_count": summary.part_count,
        "pass": summary.passed,
    }


def _part_alternates_payload(summary: "PartAlternatesSummary") -> dict[str, Any]:
    return {
        "alternates_by_ref": {
            ref: list(summary.alternates_by_ref[ref])
            for ref in summary.refs
        },
        "declared_count": summary.declared_count,
        "pass": summary.passed,
        "ref_count": summary.ref_count,
        "refs": list(summary.refs),
        "unused_ref_count": summary.unused_ref_count,
        "unused_refs": list(summary.unused_refs),
    }


def _lcsc_database_payload(summary: "LcscDatabaseSummary | None") -> dict[str, Any]:
    if summary is None:
        return {
            "configured": False,
            "path": None,
            "strict": False,
            "exists": False,
            "checked_codes": [],
            "checked_code_count": 0,
            "found_code_count": 0,
            "missing_codes": [],
            "missing_code_count": 0,
            "codes": {},
            "pass": True,
        }

    return {
        "configured": summary.configured,
        "path": summary.path,
        "strict": summary.strict,
        "exists": summary.exists,
        "checked_codes": list(summary.checked_codes),
        "checked_code_count": summary.checked_code_count,
        "found_code_count": summary.found_code_count,
        "missing_codes": list(summary.missing_codes),
        "missing_code_count": summary.missing_code_count,
        "codes": {
            code: {
                "stock": payload.stock,
                "basic": payload.basic,
                "preferred": payload.preferred,
                "package": payload.package,
                "description": payload.description,
                "price": payload.price,
            }
            for code, payload in sorted(summary.codes.items())
        },
        "pass": summary.passed,
    }


def _lcsc_cost_payload(summary: "LcscCostSummary | None") -> dict[str, Any]:
    if summary is None:
        return {
            "configured": False,
            "batch_quantity": None,
            "line_count": 0,
            "priced_line_count": 0,
            "unpriced_line_count": 0,
            "unpriced_codes": [],
            "estimated_batch_components_usd": 0.0,
            "estimated_unit_components_usd": 0.0,
            "pass": True,
            "lines": {},
        }
    return {
        "configured": summary.configured,
        "batch_quantity": summary.batch_quantity,
        "line_count": summary.line_count,
        "priced_line_count": summary.priced_line_count,
        "unpriced_line_count": summary.unpriced_line_count,
        "unpriced_codes": list(summary.unpriced_codes),
        "estimated_batch_components_usd": summary.estimated_batch_components_usd,
        "estimated_unit_components_usd": summary.estimated_unit_components_usd,
        "pass": summary.passed,
        "lines": {
            line.code: {
                "refs": list(line.refs),
                "ref_count": line.ref_count,
                "required_quantity": line.required_quantity,
                "unit_price_usd": line.unit_price_usd,
                "extended_price_usd": line.extended_price_usd,
                "selected_tier": {"qFrom": line.tier_q_from, "qTo": line.tier_q_to},
                "below_minimum": line.below_minimum,
            }
            for line in summary.lines
        },
    }


def _lcsc_availability_payload(summary: "LcscAvailabilitySummary | None") -> dict[str, Any]:
    if summary is None:
        return {
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
        }

    return {
        "configured": summary.configured,
        "batch_quantity": summary.batch_quantity,
        "line_count": summary.line_count,
        "checked_line_count": summary.checked_line_count,
        "shortage_line_count": summary.shortage_line_count,
        "unknown_stock_line_count": summary.unknown_stock_line_count,
        "shortage_codes": list(summary.shortage_codes),
        "unknown_stock_codes": list(summary.unknown_stock_codes),
        "pass": summary.passed,
        "lines": {
            line.code: {
                "refs": list(line.refs),
                "ref_count": line.ref_count,
                "required_quantity": line.required_quantity,
                "stock": line.stock,
                "stock_sufficient": line.stock_sufficient,
                "shortage_quantity": line.shortage_quantity,
                "basic": line.basic,
                "preferred": line.preferred,
            }
            for line in summary.lines
        },
    }


def format_production_checks_json(
    entries: list["ProductionCheckEntry"],
    lcsc_policy_summary: "LcscPolicySummary | None" = None,
) -> str:
    payload = {
        "production_checks": len(entries),
        "dfm_report": _build_dfm_report(entries),
        "findings": [_production_check_json_entry(entry) for entry in entries],
    }
    if lcsc_policy_summary is not None and lcsc_policy_summary.enabled:
        payload["lcsc_policy_summary"] = {
            "mapped": lcsc_policy_summary.mapped,
            "excepted": lcsc_policy_summary.excepted,
            "missing": lcsc_policy_summary.missing,
            "mapped_refs": list(lcsc_policy_summary.mapped_refs),
            "excepted_refs": list(lcsc_policy_summary.excepted_refs),
            "missing_refs": list(lcsc_policy_summary.missing_refs),
        }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _production_check_json_entry(entry: "ProductionCheckEntry") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "severity": entry.severity,
        "code": entry.code,
        "message": entry.message,
        "source": entry.source,
    }
    if entry.stage:
        payload["stage"] = entry.stage
    if entry.package:
        payload["package"] = entry.package
    if entry.evidence:
        payload["evidence"] = entry.evidence
    if entry.source_details:
        payload["source_details"] = entry.source_details
    if entry.waived:
        payload["waived"] = True
    if entry.waiver_reason:
        payload["waiver_reason"] = entry.waiver_reason
    return payload


def _resolve_output_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path.resolve()


def _artifact_record(
    requested: Path | None,
    *,
    generated_artifacts: set[Path],
    pending_generated_artifacts: set[Path] | None = None,
) -> dict[str, str | None]:
    requested_path = _resolve_output_path(requested)
    generated_known = requested_path is not None and requested_path in generated_artifacts
    if not generated_known and pending_generated_artifacts is not None and requested_path is not None:
        generated_known = requested_path in pending_generated_artifacts
    return {
        "requested": str(requested_path) if requested_path is not None else None,
        "generated": str(requested_path) if generated_known and requested_path is not None else None,
    }


@dataclass
class DrcUnconnectedEntry:
    net: str
    pads: list[str]
    route_intents: list[str] = field(default_factory=list)
    route_groups: list[str] = field(default_factory=list)
    power_stitches: list[str] = field(default_factory=list)
    source_reasons: list["DrcSourceReason"] = field(default_factory=list)
    message: str = ""


@dataclass(frozen=True)
class DrcSourceReason:
    kind: str
    name: str
    reason: str
    source: str = ""


@dataclass
class DrcUnconnectedSummary:
    route_groups: dict[str, int] = field(default_factory=dict)
    route_intents: dict[str, int] = field(default_factory=dict)
    power_stitches: dict[str, int] = field(default_factory=dict)
    unattributed_nets: dict[str, int] = field(default_factory=dict)
    buckets: list["DrcResidualBucket"] = field(default_factory=list)


@dataclass(frozen=True)
class LcscPolicySummary:
    enabled: bool
    mapped: int = 0
    excepted: int = 0
    missing: int = 0
    mapped_refs: tuple[str, ...] = ()
    excepted_refs: tuple[str, ...] = ()
    missing_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class BomStateSummary:
    part_count: int = 0
    mapped_count: int = 0
    missing_count: int = 0
    excepted_count: int = 0
    mapped_refs: tuple[str, ...] = ()
    missing_refs: tuple[str, ...] = ()
    excepted_refs: tuple[str, ...] = ()
    passed: bool = False


@dataclass(frozen=True)
class PartAlternatesSummary:
    declared_count: int = 0
    ref_count: int = 0
    refs: tuple[str, ...] = ()
    alternates_by_ref: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unused_ref_count: int = 0
    unused_refs: tuple[str, ...] = ()
    passed: bool = False


@dataclass(frozen=True)
class LcscDatabaseCodePayload:
    stock: int | None = None
    basic: str | None = None
    preferred: str | None = None
    package: str | None = None
    description: str | None = None
    price: str | None = None


@dataclass(frozen=True)
class LcscDatabaseSummary:
    configured: bool
    path: str | None
    strict: bool
    exists: bool
    checked_codes: tuple[str, ...]
    checked_code_count: int
    found_code_count: int
    missing_codes: tuple[str, ...]
    missing_code_count: int
    codes: dict[str, LcscDatabaseCodePayload]
    passed: bool


@dataclass(frozen=True)
class LcscCostLine:
    code: str
    refs: tuple[str, ...]
    ref_count: int
    required_quantity: int
    unit_price_usd: float | None
    extended_price_usd: float | None
    tier_q_from: int | None
    tier_q_to: int | None
    below_minimum: bool


@dataclass(frozen=True)
class LcscCostSummary:
    configured: bool
    batch_quantity: int | None
    line_count: int
    priced_line_count: int
    unpriced_line_count: int
    unpriced_codes: tuple[str, ...]
    estimated_batch_components_usd: float
    estimated_unit_components_usd: float
    passed: bool
    lines: tuple[LcscCostLine, ...]


@dataclass(frozen=True)
class LcscAvailabilityLine:
    code: str
    refs: tuple[str, ...]
    ref_count: int
    required_quantity: int
    stock: int | None
    stock_sufficient: bool
    shortage_quantity: int
    basic: str | None
    preferred: str | None


@dataclass(frozen=True)
class LcscAvailabilitySummary:
    configured: bool
    batch_quantity: int | None
    line_count: int
    checked_line_count: int
    shortage_line_count: int
    unknown_stock_line_count: int
    shortage_codes: tuple[str, ...]
    unknown_stock_codes: tuple[str, ...]
    passed: bool
    lines: tuple[LcscAvailabilityLine, ...]


@dataclass
class DrcViolationEntry:
    code: str
    title: str
    severity: str
    lines: list[str] = field(default_factory=list)
    nets: list[str] = field(default_factory=list)
    pads: list[str] = field(default_factory=list)
    source_reasons: list["DrcSourceReason"] = field(default_factory=list)
    coordinates: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class DrcResidualBucket:
    kind: str
    name: str
    unconnected: int = 0
    pads: int = 0
    nets: set[str] = field(default_factory=set)
    route_intents: set[str] = field(default_factory=set)
    power_stitches: set[str] = field(default_factory=set)
    source_reasons: set[DrcSourceReason] = field(default_factory=set)


def _resolve(path: Path, base: Path) -> Path:
    return path if path.is_absolute() else base / path


def _layers_for_spec(spec: PhysicalSpec) -> list[str]:
    if spec.copper_layers:
        return list(spec.copper_layers)
    try:
        return list(STACKUP_LAYERS[spec.stackup])
    except KeyError as exc:
        raise ValueError(f"Unknown stackup {spec.stackup!r}") from exc


def _apply_rules(board: Board, spec: PhysicalSpec) -> None:
    for class_name, class_spec in spec.rules.netclasses.items():
        via_size = class_spec.via.diameter if class_spec.via else 0.8
        via_drill = class_spec.via.drill if class_spec.via else 0.4
        clearance = (
            class_spec.clearance
            if class_spec.clearance is not None
            else spec.rules.default_clearance
        )
        board.add_net_class(
            NetClass(
                name=class_name,
                track_width=class_spec.width,
                clearance=clearance,
                via_size=via_size,
                via_drill=via_drill,
            )
        )

    wildcard_classes = []
    for class_name, nets in spec.netclass_assignments.items():
        if class_name not in board.net_classes:
            continue
        for net_name in nets:
            if net_name == "*":
                wildcard_classes.append(class_name)
            elif net_name in board.nets:
                board.assign_net_to_class(net_name, class_name)

    for class_name in wildcard_classes:
        for net_name, net in board.nets.items():
            if not net.net_class:
                board.assign_net_to_class(net_name, class_name)


def _apply_placements(board: Board, spec: PhysicalSpec) -> list[PlacementReportEntry]:
    report = []
    for ref, placement in spec.parts.items():
        comp = board.components.get(ref)
        if comp is None:
            raise ValueError(f"Physical spec references missing component {ref}")
        comp.footprint = spec.footprint_aliases.get(placement.footprint, placement.footprint)
        comp.position = placement.at
        comp.rotation = placement.rotation
        if placement.value is not None:
            comp.value = placement.value
        report.append(
            PlacementReportEntry(
                ref=ref,
                footprint=comp.footprint,
                x=placement.at[0],
                y=placement.at[1],
                rotation=placement.rotation,
            )
        )
    return report


def _next_ref(board: Board, prefix: str, index: int) -> str:
    while f"{prefix}{index}" in board.components:
        index += 1
    return f"{prefix}{index}"


def _apply_production_components(board: Board, spec: PhysicalSpec) -> None:
    for index, testpoint in enumerate(spec.testpoints, start=1):
        ref = _next_ref(board, "TP", index)
        board.add_component(
            Component(
                ref=ref,
                value=testpoint.net,
                footprint="TestPoint:TestPoint_Pad_1.0mm",
                position=testpoint.at if testpoint.at is not None else (0.0, 0.0),
                rotation=0.0,
                pads=[
                    Pad(
                        number="1",
                        position_offset=(0.0, 0.0),
                        size=(1.0, 1.0),
                        shape="circle",
                        net_name=testpoint.net,
                    )
                ],
            )
        )
        if testpoint.net in board.nets:
            board.nets[testpoint.net].add_connection(ref, "1")

    for index, fiducial in enumerate(spec.fiducials, start=1):
        ref = _next_ref(board, "FID", index)
        board.add_component(
            Component(
                ref=ref,
                value=fiducial.name,
                footprint="Fiducial:Fiducial_1mm_Mask2mm",
                position=fiducial.at,
                rotation=0.0,
                pads=[
                    Pad(
                        number="1",
                        position_offset=(0.0, 0.0),
                        size=(fiducial.diameter or 1.0, fiducial.diameter or 1.0),
                        shape="circle",
                    )
                ],
            )
        )

    for index, mounting_hole in enumerate(spec.mounting_holes, start=1):
        ref = _next_ref(board, "MH", index)
        board.add_component(
            Component(
                ref=ref,
                value=mounting_hole.name,
                footprint="MountingHole:MountingHole_3.2mm_M3",
                position=mounting_hole.at,
                rotation=0.0,
                pads=[
                    Pad(
                        number="1",
                        position_offset=(0.0, 0.0),
                        size=(mounting_hole.diameter, mounting_hole.diameter),
                        drill=mounting_hole.drill,
                        shape="circle",
                    )
                ],
            )
        )


def build_physical_board(
    spec: PhysicalSpec,
    netlist: Path,
    *,
    loaded_board: Board | None = None,
) -> tuple[Board, list[PlacementReportEntry]]:
    board = loaded_board if loaded_board is not None else NetlistReader().read(netlist)
    board.width = spec.width
    board.height = spec.height
    board.layers = _layers_for_spec(spec)

    for comp in board.components.values():
        comp.footprint = spec.footprint_aliases.get(comp.footprint, comp.footprint)

    _apply_rules(board, spec)
    placement_report = _apply_placements(board, spec)
    _apply_production_components(board, spec)
    return board, placement_report


def _build_physical_residuals(spec: PhysicalSpec, board: Board) -> dict[str, Any]:
    netlist_refs = sorted(ref for ref in board.components if not _is_helper_component(ref))
    placed_refs = sorted(ref for ref in netlist_refs if ref in spec.parts)
    unplaced_refs = sorted(ref for ref in netlist_refs if ref not in spec.parts)
    unused_placement_refs = sorted(
        ref for ref in spec.parts if not _is_helper_component(ref) and ref not in board.components
    )

    route_nets = sorted({net for intent in spec.routes for net in _route_intent_nets(intent.raw)})
    testpoint_nets = sorted(
        {
            testpoint.net.strip()
            for testpoint in spec.testpoints
            if isinstance(testpoint.net, str) and testpoint.net.strip()
        }
    )
    validation_nets = sorted(
        {
            validation_test.net.strip()
            for validation_test in spec.validation_tests
            if isinstance(validation_test.net, str) and validation_test.net.strip()
        }
    )

    def missing_nets(nets: list[str]) -> list[str]:
        return [net for net in nets if net not in board.nets]

    missing_route_nets = missing_nets(route_nets)
    missing_testpoint_nets = missing_nets(testpoint_nets)
    missing_validation_nets = missing_nets(validation_nets)

    return {
        "component_placement": {
            "total_non_helper_netlist_components": len(netlist_refs),
            "placed_count": len(placed_refs),
            "placed_refs": placed_refs,
            "unplaced_count": len(unplaced_refs),
            "unplaced_refs": unplaced_refs,
            "unused_placement_count": len(unused_placement_refs),
            "unused_placement_refs": unused_placement_refs,
        },
        "physical_intent_nets": {
            "routes": {
                "missing_count": len(missing_route_nets),
                "missing_from_netlist": missing_route_nets,
            },
            "testpoints": {
                "missing_count": len(missing_testpoint_nets),
                "missing_from_netlist": missing_testpoint_nets,
            },
            "validation_tests": {
                "missing_count": len(missing_validation_nets),
                "missing_from_netlist": missing_validation_nets,
            },
        },
    }


def _build_footprint_state(spec: PhysicalSpec, board: Board) -> dict[str, Any]:
    netlist_refs = sorted(ref for ref in board.components if not _is_helper_component(ref))
    spec_refs = sorted(ref for ref in spec.parts if not _is_helper_component(ref))
    netlist_ref_set = set(netlist_refs)
    spec_ref_set = set(spec_refs)

    missing_spec_refs = sorted(ref for ref in netlist_refs if ref not in spec_ref_set)
    unused_spec_refs = sorted(ref for ref in spec_refs if ref not in netlist_ref_set)

    mismatches: list[dict[str, str]] = []
    matched_count = 0
    for ref in sorted(netlist_ref_set & spec_ref_set):
        netlist_footprint = spec.footprint_aliases.get(
            board.components[ref].footprint,
            board.components[ref].footprint,
        )
        spec_footprint = spec.footprint_aliases.get(
            spec.parts[ref].footprint,
            spec.parts[ref].footprint,
        )
        if netlist_footprint == spec_footprint:
            matched_count += 1
            continue
        mismatches.append(
            {
                "ref": ref,
                "netlist_footprint": netlist_footprint,
                "spec_footprint": spec_footprint,
            }
        )

    checked_count = matched_count + len(mismatches)
    return {
        "checked_count": checked_count,
        "matched_count": matched_count,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "missing_spec_count": len(missing_spec_refs),
        "missing_spec_refs": missing_spec_refs,
        "pass": (
            not mismatches
            and not missing_spec_refs
            and not unused_spec_refs
        ),
        "unused_spec_count": len(unused_spec_refs),
        "unused_spec_refs": unused_spec_refs,
    }


def _physical_residual_pass(physical_residuals: dict[str, Any]) -> bool:
    component_placement = physical_residuals.get("component_placement", {})
    physical_intent_nets = physical_residuals.get("physical_intent_nets", {})
    if not isinstance(component_placement, dict) or not isinstance(physical_intent_nets, dict):
        return False
    return (
        component_placement.get("unplaced_count") == 0
        and component_placement.get("unused_placement_count") == 0
        and all(
            isinstance(bucket, dict) and bucket.get("missing_count") == 0
            for bucket in physical_intent_nets.values()
        )
    )


def _build_source_handoff(
    spec: PhysicalSpec,
    *,
    netlist: Path,
    board: Board,
    physical_residuals: dict[str, Any],
    footprint_state: dict[str, Any],
) -> dict[str, Any]:
    physical_residual_pass = _physical_residual_pass(physical_residuals)
    footprint_state_pass = footprint_state.get("pass") is True
    payload: dict[str, Any] = {
        "kind": "atopile" if spec.source_atopile is not None else "netlist",
        "format": spec.source_format,
        "netlist": str(netlist.resolve()),
        "netlist_exists": netlist.exists(),
        "component_count": physical_residuals.get("component_placement", {}).get(
            "total_non_helper_netlist_components",
            0,
        ),
        "net_count": len(board.nets),
        "physical_residual_pass": physical_residual_pass,
        "footprint_state_pass": footprint_state_pass,
        "pass": netlist.exists() and physical_residual_pass and footprint_state_pass,
    }
    if spec.source_atopile is not None:
        payload["atopile"] = {
            "project": str(_resolve(spec.source_atopile.project, spec.path.parent).resolve()),
            "ato_yaml": str(_resolve(spec.source_atopile.ato_yaml, spec.path.parent).resolve()),
            "build": spec.source_atopile.build,
            "entry": spec.source_atopile.entry,
        }
    return payload


def _build_package_physical_context(project_context: Any | None) -> dict[str, Any]:
    physical_libraries = getattr(project_context, "physical_libraries", {}) or {}
    route_policies = getattr(project_context, "route_policies", {}) or {}
    return {
        "schema": "pardal.package_physical_context/v1",
        "physical_libraries": {
            library_id: {
                "package_id": getattr(library, "package_id", ""),
                "path": str(getattr(library, "path", "")),
                "footprints": list(getattr(library, "footprints", ()) or ()),
                "netclasses": list(getattr(library, "netclasses", ()) or ()),
                "placements": list(getattr(library, "placements", ()) or ()),
                "route_groups": list(getattr(library, "route_groups", ()) or ()),
                "mechanical": list(getattr(library, "mechanical", ()) or ()),
                "metadata": dict(getattr(library, "metadata", {}) or {}),
            }
            for library_id, library in sorted(physical_libraries.items())
        },
        "route_policies": {
            policy_id: {
                "package_id": getattr(policy, "package_id", ""),
                "path": str(getattr(policy, "path", "")),
                "backend": getattr(policy, "backend", None),
                "layer_stack": getattr(policy, "layer_stack", None),
                "net_patterns": list(getattr(policy, "net_patterns", ()) or ()),
                "rules": dict(getattr(policy, "rules", {}) or {}),
            }
            for policy_id, policy in sorted(route_policies.items())
        },
    }


def _file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path.resolve()),
            "exists": False,
            "size_bytes": None,
            "sha256": None,
            "mtime_epoch": None,
        }
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "exists": True,
        "size_bytes": int(stat.st_size),
        "sha256": digest,
        "mtime_epoch": stat.st_mtime,
    }


def _build_atopile_source_state(spec: PhysicalSpec, *, netlist: Path) -> dict[str, Any]:
    if spec.source_atopile is None:
        return {
            "configured": False,
            "project": None,
            "ato_yaml": None,
            "entry": None,
            "netlist": str(netlist.resolve()),
            "source_files": [],
            "netlist_exists": netlist.exists(),
            "netlist_size_bytes": int(netlist.stat().st_size) if netlist.exists() else None,
            "netlist_sha256": hashlib.sha256(netlist.read_bytes()).hexdigest() if netlist.exists() else None,
            "netlist_mtime_epoch": netlist.stat().st_mtime if netlist.exists() else None,
            "newest_source_mtime_epoch": None,
            "netlist_newer_or_equal": True,
            "missing_source_count": 0,
            "missing_sources": [],
            "pass": True,
        }

    project = _resolve(spec.source_atopile.project, spec.path.parent).resolve()
    ato_yaml = _resolve(spec.source_atopile.ato_yaml, spec.path.parent).resolve()
    entry = spec.source_atopile.entry
    entry_source = entry.split(":", 1)[0].strip() if isinstance(entry, str) else ""
    tracked_sources: list[Path] = [ato_yaml]
    if entry_source:
        tracked_sources.append((project / entry_source).resolve())
    tracked_sources = sorted(set(tracked_sources), key=lambda p: str(p))
    source_files = [_file_state(path) for path in tracked_sources]

    netlist_state = _file_state(netlist.resolve())
    source_mtimes = [item["mtime_epoch"] for item in source_files if item["exists"] and item["mtime_epoch"] is not None]
    newest_source_mtime_epoch = max(source_mtimes) if source_mtimes else None
    missing_sources = sorted(item["path"] for item in source_files if not item["exists"])
    netlist_newer_or_equal = (
        True
        if newest_source_mtime_epoch is None
        else (
            netlist_state["mtime_epoch"] is not None
            and netlist_state["mtime_epoch"] >= newest_source_mtime_epoch
        )
    )

    passed = (
        len(missing_sources) == 0
        and netlist_state["exists"] is True
        and netlist_newer_or_equal is True
    )
    return {
        "configured": True,
        "project": str(project),
        "ato_yaml": str(ato_yaml),
        "entry": entry,
        "netlist": netlist_state["path"],
        "source_files": source_files,
        "netlist_exists": netlist_state["exists"],
        "netlist_size_bytes": netlist_state["size_bytes"],
        "netlist_sha256": netlist_state["sha256"],
        "netlist_mtime_epoch": netlist_state["mtime_epoch"],
        "newest_source_mtime_epoch": newest_source_mtime_epoch,
        "netlist_newer_or_equal": bool(netlist_newer_or_equal),
        "missing_source_count": len(missing_sources),
        "missing_sources": missing_sources,
        "pass": passed,
    }


def _build_testpoint_coverage(spec: PhysicalSpec, board: Board) -> dict[str, Any]:
    declared_entries = [
        testpoint
        for testpoint in spec.testpoints
        if isinstance(testpoint.name, str)
        and str(testpoint.name).strip()
        and isinstance(testpoint.net, str)
        and str(testpoint.net).strip()
    ]
    declared_names = sorted(str(testpoint.name).strip() for testpoint in declared_entries)
    declared_nets = sorted({str(testpoint.net).strip() for testpoint in declared_entries})
    missing_from_netlist = sorted(net for net in declared_nets if net not in board.nets)
    return {
        "declared_count": len(declared_entries),
        "declared_names": declared_names,
        "declared_nets": declared_nets,
        "missing_from_netlist_count": len(missing_from_netlist),
        "missing_from_netlist": missing_from_netlist,
        "pass": len(missing_from_netlist) == 0,
    }


def _build_drc_source_coverage(
    *,
    drc_violations: list["DrcViolationEntry"],
    drc_unconnected: list["DrcUnconnectedEntry"],
) -> dict[str, Any]:
    attributed_violation_count = sum(1 for entry in drc_violations if entry.source_reasons)
    attributed_unconnected_count = sum(1 for entry in drc_unconnected if entry.source_reasons)
    violation_kinds: dict[str, int] = {}
    unconnected_kinds: dict[str, int] = {}

    for entry in drc_violations:
        for reason in {reason.kind for reason in entry.source_reasons}:
            violation_kinds[reason] = violation_kinds.get(reason, 0) + 1
    for entry in drc_unconnected:
        for reason in {reason.kind for reason in entry.source_reasons}:
            unconnected_kinds[reason] = unconnected_kinds.get(reason, 0) + 1

    violation_count = len(drc_violations)
    unconnected_count = len(drc_unconnected)
    unattributed_violation_count = violation_count - attributed_violation_count
    unattributed_unconnected_count = unconnected_count - attributed_unconnected_count

    return {
        "violation_count": violation_count,
        "unconnected_count": unconnected_count,
        "attributed_violation_count": attributed_violation_count,
        "unattributed_violation_count": unattributed_violation_count,
        "attributed_unconnected_count": attributed_unconnected_count,
        "unattributed_unconnected_count": unattributed_unconnected_count,
        "pass": unattributed_violation_count == 0 and unattributed_unconnected_count == 0,
        "violation_source_kinds": {
            kind: violation_kinds[kind]
            for kind in sorted(violation_kinds)
        },
        "unconnected_source_kinds": {
            kind: unconnected_kinds[kind]
            for kind in sorted(unconnected_kinds)
        },
    }


_PAD_RE = re.compile(
    r"(?:PTH\s+)?pad\s+(?P<pin>\S+)\s+\[(?P<net>[^\]]+)\]\s+of\s+(?P<ref>\S+)",
    re.IGNORECASE,
)


def _route_groups(raw: dict) -> list[str]:
    group = raw.get("group")
    if group is None:
        return []
    if isinstance(group, list):
        return [str(item) for item in group]
    return [str(group)]


def _stitch_refs(raw: dict, key: str) -> set[str]:
    refs = raw.get(key) or {}
    if not isinstance(refs, dict):
        return set()
    result = set()
    for ref, pins in refs.items():
        if isinstance(pins, list):
            result.update(f"{ref}.{pin}" for pin in pins)
    return result


def _stitch_pad_refs(raw: dict) -> set[str]:
    return _stitch_refs(raw, "refs")


def _stitch_deferred_refs(raw: dict) -> set[str]:
    if str(raw.get("kind", "pad_vias")) in {"deferred", "unrouted", "airwire"}:
        return _stitch_pad_refs(raw)
    return _stitch_refs(raw, "deferred_refs")


def _reason(raw: dict) -> str | None:
    reason = raw.get("reason")
    if reason is None:
        return None
    text = str(reason).strip()
    return text or None


def _source_reason(
    kind: str,
    raw: dict,
    *,
    fallback_reason: str | None = None,
) -> DrcSourceReason | None:
    reason = _reason(raw) or fallback_reason
    if reason is None:
        return None
    source = raw.get(SOURCE_LOCATION_KEY)
    source_display = source.display() if isinstance(source, SourceLocation) else ""
    return DrcSourceReason(
        kind=kind,
        name=str(raw.get("name", raw.get("kind", kind))),
        reason=reason,
        source=source_display,
    )


def _source_display(raw: dict) -> str:
    source = raw.get(SOURCE_LOCATION_KEY)
    return source.display() if isinstance(source, SourceLocation) else ""


def _source_display_from_location(source: SourceLocation | None) -> str:
    return source.display() if isinstance(source, SourceLocation) else ""


FORBIDDEN_SIGNAL_LAYER_ROLES = {"power_plane", "ground_reference", "restricted"}
SIGNAL_ROUTE_STRATEGIES = {
    "manual_polyline",
    "direct",
    "bus",
    "header_bank",
    "escape_bundle",
    "escape_bundle_fanout",
}


def _route_exception_reason(raw: dict[str, Any]) -> str:
    reason = raw.get("reason")
    if reason is None:
        return ""
    return str(reason).strip()


def _route_layer_exception_matches(
    exception: dict[str, Any],
    *,
    layer: str,
    role: str,
    net: str,
) -> bool:
    if str(exception.get("layer", "")).strip() != layer:
        return False
    if str(exception.get("role", "")).strip() != role:
        return False
    nets = exception.get("nets")
    if not isinstance(nets, list):
        return False
    return net in {str(item).strip() for item in nets}


def _route_layer_policy_source(entry: RouteReportEntry, raw: dict[str, Any] | None) -> str:
    if entry.source:
        return entry.source
    if raw is not None:
        return _source_display(raw)
    return ""


def _check_route_layer_policy(
    spec: PhysicalSpec,
    route_report: list[RouteReportEntry],
    add,
) -> None:
    route_raw_by_index = {
        index: intent.raw
        for index, intent in enumerate(spec.routes)
    }
    for entry in route_report:
        if not entry.committed or entry.strategy not in SIGNAL_ROUTE_STRATEGIES:
            continue
        raw = route_raw_by_index.get(entry.route_index) if entry.route_index is not None else None
        exceptions = []
        if raw is not None:
            exceptions_raw = raw.get("route_layer_exceptions") or []
            if isinstance(exceptions_raw, list):
                exceptions = [item for item in exceptions_raw if isinstance(item, dict)]
                for index, exception in enumerate(exceptions_raw):
                    if not isinstance(exception, dict):
                        add(
                            "error",
                            "route_layer_exception.invalid",
                            (
                                f"route {entry.route_name or entry.strategy} "
                                f"route_layer_exceptions[{index}] must be a mapping"
                            ),
                            _route_layer_policy_source(entry, raw),
                        )
                        continue
                    if not _route_exception_reason(exception):
                        add(
                            "error",
                            "route_layer_exception.reason_missing",
                            (
                                f"route {entry.route_name or entry.strategy} "
                                f"exception for layer {exception.get('layer', '<missing>')} "
                                f"net(s) {exception.get('nets', '<missing>')} requires a non-empty reason"
                            ),
                            _route_layer_policy_source(entry, raw),
                        )
            else:
                add(
                    "error",
                    "route_layer_exception.invalid",
                    f"route {entry.route_name or entry.strategy} route_layer_exceptions must be a list",
                    _route_layer_policy_source(entry, raw),
                )
        for layer in entry.segment_layers:
            role = spec.layer_roles.get(layer, "")
            if role not in FORBIDDEN_SIGNAL_LAYER_ROLES:
                continue
            has_exception = any(
                _route_layer_exception_matches(
                    exception,
                    layer=layer,
                    role=role,
                    net=entry.net,
                )
                and _route_exception_reason(exception)
                for exception in exceptions
            )
            if has_exception:
                continue
            route_label = entry.route_name or entry.strategy
            add(
                "error",
                "route.layer_role_forbidden",
                (
                    f"route {route_label} net {entry.net} uses {layer} as signal copper "
                    f"but layer role is {role}; add route_layer_exceptions with exact "
                    "layer, role, net, and non-empty reason"
                ),
                _route_layer_policy_source(entry, raw),
            )


def check_production_readiness(
    spec: PhysicalSpec,
    board: Board,
    *,
    artifact_root: Path | None = None,
    include_artifact_contract: bool = True,
    generated_artifacts: set[Path] | None = None,
    physical_residuals: dict[str, Any] | None = None,
    route_report: list[RouteReportEntry] | None = None,
    source_contract: SourceContract | None = None,
    artifact_paths: dict[str, Path | None] | None = None,
    enable_checks: list[str] | None = None,
    disable_checks: list[str] | None = None,
    disable_check_reasons: dict[str, str] | None = None,
    production_profiles: list[str] | None = None,
    warnerr: bool = False,
    allow_network_checks: bool = False,
    project_context: Any | None = None,
) -> list[ProductionCheckEntry]:
    checks: list[ProductionCheckEntry] = []

    def add(severity: str, code: str, message: str, source: str = "") -> None:
        checks.append(
            ProductionCheckEntry(
                severity=severity,
                code=code,
                message=message,
                source=source,
            )
        )

    def artifact_is_empty(path: Path) -> bool:
        if path.is_dir():
            return not any(path.iterdir())
        try:
            return path.stat().st_size <= 0
        except OSError:
            return True

    def add_profile_enabled_checks() -> None:
        contract = source_contract or SourceContract()
        ctx = CheckContext(
            spec=spec,
            board=board,
            source_contract=contract,
            artifact_root=artifact_root,
            generated_artifacts=frozenset(generated_artifacts or set()),
            artifact_paths=artifact_paths or {},
            production_profiles=tuple(production_profiles or ()),
            allow_network_checks=allow_network_checks,
            project_context=project_context,
        )
        for finding in run_production_checks(
            ctx,
            enable_checks=enable_checks,
            disable_checks=disable_checks,
            disable_check_reasons=disable_check_reasons,
            production_profiles=production_profiles,
        ):
            checks.append(_production_entry_from_check_finding(finding))

    if spec.dfm is None:
        add("error", "dfm.missing", "production spec requires dfm.profile")

    testpoints_by_net: dict[str, list[str]] = {}
    for testpoint in spec.testpoints:
        testpoints_by_net.setdefault(testpoint.net.casefold(), []).append(testpoint.name)
        if testpoint.net not in board.nets:
            add(
                "error",
                "testpoint.net_missing",
                f"testpoint {testpoint.name} references missing net {testpoint.net}",
                _source_display(testpoint.raw),
            )

    for rail_name, rail in spec.rails.items():
        source = _source_display(rail.raw)
        if rail.nominal_voltage is None:
            add("error", "rail.nominal_missing", f"rail {rail_name} requires nominal voltage", source)
        if (
            rail.nominal_voltage is not None
            and abs(rail.nominal_voltage) > 1e-9
            and rail.max_current is None
        ):
            add("error", "rail.current_missing", f"rail {rail_name} requires max_current", source)
        if rail_name.casefold() not in testpoints_by_net:
            add(
                "error",
                "rail.testpoint_missing",
                f"rail {rail_name} has no declared testpoint",
                source,
            )

    if spec.dfm is not None and spec.dfm.profile.startswith("jlcpcb"):
        validation_source = _source_display(spec.dfm.raw)
        component_residuals = (
            physical_residuals.get("component_placement", {})
            if isinstance(physical_residuals, dict)
            else {}
        )
        unplaced_refs = component_residuals.get("unplaced_refs", [])
        if unplaced_refs:
            refs = ", ".join(str(ref) for ref in unplaced_refs)
            add(
                "error",
                "physical.component_unplaced",
                f"netlist components missing placement intent: {refs}",
            )
        rails_by_name = {name.casefold(): name for name in spec.rails}
        if spec.copper_layers is not None:
            copper_layer_source = _source_display_from_location(
                spec.copper_layers_source or spec.board_source
            )
            for layer_name in spec.copper_layers:
                role = spec.layer_roles.get(layer_name, "")
                if not role:
                    add(
                        "error",
                        "layer.role_missing",
                        f"copper layer {layer_name} requires layer_roles entry",
                        copper_layer_source,
                    )
                    continue
                if role not in ALLOWED_LAYER_ROLES:
                    allowed = ", ".join(sorted(ALLOWED_LAYER_ROLES))
                    add(
                        "error",
                        "layer.role_invalid",
                        (
                            f"layer_roles.{layer_name} must be one of {allowed} "
                            f"(got {role!r})"
                        ),
                        _source_display_from_location(spec.layer_role_sources.get(layer_name)),
                    )
            for layer_name in sorted(spec.layer_roles):
                if layer_name in spec.copper_layers:
                    continue
                add(
                    "error",
                    "layer.role_unknown",
                    (
                        f"layer_roles.{layer_name} does not match any declared "
                        "board.copper_layers entry"
                    ),
                    _source_display_from_location(spec.layer_role_sources.get(layer_name)),
                )
        _check_route_layer_policy(spec, route_report or [], add)
        if not spec.validation_tests:
            add(
                "error",
                "validation.tests_missing",
                "jlcpcb production profile requires validation_tests with measurable pass/fail criteria",
                validation_source,
            )
        for index, validation_test in enumerate(spec.validation_tests):
            source = _source_display(validation_test.raw) or validation_source
            test_label = (
                validation_test.name
                if isinstance(validation_test.name, str) and validation_test.name.strip()
                else f"validation_tests[{index}]"
            )
            if not validation_test.name:
                add(
                    "error",
                    "validation.name_missing",
                    f"{test_label} requires non-empty name",
                    source,
                )
            if validation_test.kind not in VALIDATION_TEST_KINDS:
                allowed = ", ".join(sorted(VALIDATION_TEST_KINDS))
                add(
                    "error",
                    "validation.kind_invalid",
                    f"{test_label} kind must be one of {allowed}",
                    source,
                )
            if not validation_test.criteria:
                add(
                    "error",
                    "validation.criteria_missing",
                    f"{test_label} requires measurable pass/fail criteria",
                    source,
                )
            if validation_test.rail is not None and validation_test.rail.casefold() not in rails_by_name:
                add(
                    "error",
                    "validation.rail_missing",
                    f"{test_label} references missing rail {validation_test.rail}",
                    source,
                )
            if validation_test.net is not None and validation_test.net not in board.nets:
                add(
                    "error",
                    "validation.net_missing",
                    f"{test_label} references missing net {validation_test.net}",
                    source,
                )

        panelization = spec.dfm.panelization
        panelization_source = _source_display(spec.dfm.raw)
        if panelization is not None:
            panelization_source = _source_display(panelization.raw) or panelization_source
        if panelization is None:
            add(
                "error",
                "dfm.panelization_missing",
                "jlcpcb production profile requires dfm.panelization policy",
                _source_display(spec.dfm.raw),
            )
        elif panelization.mode not in JLCPCB_PANELIZATION_MODES:
            add(
                "error",
                "dfm.panelization_invalid",
                (
                    "dfm.panelization.mode must be one of "
                    "single_board, vendor_panel, customer_panel "
                    f"(got {panelization.mode!r})"
                ),
                panelization_source,
            )
        elif panelization.mode == "customer_panel":
            if panelization.breakaway not in {"v_cut", "mouse_bites"}:
                add(
                    "error",
                    "dfm.panelization_breakaway_missing",
                    "customer_panel requires dfm.panelization.breakaway of v_cut or mouse_bites",
                    panelization_source,
                )
            if panelization.rail_width is None:
                add(
                    "error",
                    "dfm.panelization_rail_width_missing",
                    (
                        "customer_panel requires dfm.panelization.rail_width with explicit mm units "
                        f">= {CUSTOMER_PANEL_MIN_RAIL_WIDTH_MM:.1f}mm"
                    ),
                    panelization_source,
                )
            elif panelization.rail_width < CUSTOMER_PANEL_MIN_RAIL_WIDTH_MM:
                add(
                    "error",
                    "dfm.panelization_rail_width_below_min",
                    (
                        f"dfm.panelization.rail_width {panelization.rail_width:.3f}mm is below "
                        f"{CUSTOMER_PANEL_MIN_RAIL_WIDTH_MM:.1f}mm minimum for customer_panel rails"
                    ),
                    panelization_source,
                )
        if artifact_root is not None and not spec.dfm.required_artifacts:
            add(
                "error",
                "dfm.artifact_contract_missing",
                "jlcpcb production profile requires dfm.required_artifacts contract",
                _source_display(spec.dfm.raw),
            )
        if spec.dfm.assembly is not None and spec.dfm.assembly not in {"top", "bottom", "mixed"}:
            add(
                "error",
                "dfm.assembly_invalid",
                (
                    f"dfm.assembly must be one of top, bottom, mixed "
                    f"(got {spec.dfm.assembly!r})"
                ),
                _source_display(spec.dfm.raw),
            )
        if len(spec.fiducials) < 3:
            add(
                "error",
                "dfm.fiducials_missing",
                "JLCPCB production profile requires at least 3 fiducials",
            )
        if len(spec.mounting_holes) < 2:
            add(
                "warning",
                "dfm.mounting_holes_low",
                "production board has fewer than 2 declared mounting holes",
            )

        # Basic manufacturer-profile gates from declared routing/mechanical intent.
        # This keeps checks deterministic without needing full geometry extraction.
        profile_min_width_mm = 0.10
        profile_min_clearance_mm = 0.10
        profile_min_via_drill_mm = 0.20
        profile_min_via_annular_ring_mm = 0.10
        profile_min_mount_hole_drill_mm = 0.20

        if spec.rules.default_clearance < profile_min_clearance_mm:
            add(
                "error",
                "dfm.clearance_below_profile",
                (
                    f"rules.default_clearance {spec.rules.default_clearance:.3f}mm is below "
                    f"{profile_min_clearance_mm:.3f}mm for {spec.dfm.profile}"
                ),
                _source_display(spec.dfm.raw),
            )

        for class_name, class_spec in spec.rules.netclasses.items():
            source = ""
            if class_spec.width < profile_min_width_mm:
                add(
                    "error",
                    "dfm.track_width_below_profile",
                    (
                        f"netclass {class_name} width {class_spec.width:.3f}mm is below "
                        f"{profile_min_width_mm:.3f}mm for {spec.dfm.profile}"
                    ),
                    source,
                )
            if class_spec.clearance is not None and class_spec.clearance < profile_min_clearance_mm:
                add(
                    "error",
                    "dfm.netclass_clearance_below_profile",
                    (
                        f"netclass {class_name} clearance {class_spec.clearance:.3f}mm is below "
                        f"{profile_min_clearance_mm:.3f}mm for {spec.dfm.profile}"
                    ),
                    source,
                )
            if class_spec.via is not None:
                drill = class_spec.via.drill
                diameter = class_spec.via.diameter
                annular = (diameter - drill) / 2.0
                if drill < profile_min_via_drill_mm:
                    add(
                        "error",
                        "dfm.via_drill_below_profile",
                        (
                            f"netclass {class_name} via drill {drill:.3f}mm is below "
                            f"{profile_min_via_drill_mm:.3f}mm for {spec.dfm.profile}"
                        ),
                        source,
                    )
                if annular < profile_min_via_annular_ring_mm:
                    add(
                        "error",
                        "dfm.via_annular_below_profile",
                        (
                            f"netclass {class_name} via annular ring {annular:.3f}mm is below "
                            f"{profile_min_via_annular_ring_mm:.3f}mm for {spec.dfm.profile}"
                        ),
                        source,
                    )

        for mounting_hole in spec.mounting_holes:
            source = _source_display(mounting_hole.raw)
            if mounting_hole.drill < profile_min_mount_hole_drill_mm:
                add(
                    "error",
                    "dfm.mounting_hole_drill_below_profile",
                    (
                        f"mounting hole {mounting_hole.name} drill {mounting_hole.drill:.3f}mm is below "
                        f"{profile_min_mount_hole_drill_mm:.3f}mm for {spec.dfm.profile}"
                    ),
                    source,
                )
            if mounting_hole.diameter < mounting_hole.drill:
                add(
                    "error",
                    "dfm.mounting_hole_geometry_invalid",
                    (
                        f"mounting hole {mounting_hole.name} diameter {mounting_hole.diameter:.3f}mm "
                        f"is below drill {mounting_hole.drill:.3f}mm"
                    ),
                    source,
                )

        if include_artifact_contract and artifact_root is not None and spec.dfm.required_artifacts:
            root = artifact_root if artifact_root is not None else spec.path.parent
            for artifact in spec.dfm.required_artifacts:
                artifact_path = Path(artifact)
                path_obj = artifact_path if artifact_path.is_absolute() else root / artifact_path
                path_obj = path_obj.resolve()
                if generated_artifacts is not None and path_obj in generated_artifacts:
                    continue
                if generated_artifacts is not None and path_obj not in generated_artifacts:
                    add(
                        "error",
                        "dfm.artifact_missing",
                        f"required manufacturing artifact missing: {artifact}",
                        _source_display(spec.dfm.raw),
                    )
                    continue
                if not path_obj.exists():
                    add(
                        "error",
                        "dfm.artifact_missing",
                        f"required manufacturing artifact missing: {artifact}",
                        _source_display(spec.dfm.raw),
                    )
                    continue
                if artifact_is_empty(path_obj):
                    artifact_kind = "directory" if path_obj.is_dir() else "file"
                    add(
                        "error",
                        "dfm.artifact_empty",
                        f"required manufacturing artifact {artifact_kind} is empty: {artifact}",
                        _source_display(spec.dfm.raw),
                    )

        if spec.dfm.lcsc_policy == "require_or_exception":
            # JLC assembly policy: each non-helper component must have either an LCSC
            # part number or an explicit exception reason.
            lcsc_parts = spec.dfm.lcsc_parts
            lcsc_exceptions = spec.dfm.lcsc_exceptions
            for ref, comp in board.components.items():
                if _is_helper_component(ref):
                    continue
                if ref in lcsc_exceptions:
                    continue
                part_number = lcsc_parts.get(ref, "").strip()
                if not part_number:
                    add(
                        "error",
                        "dfm.lcsc_part_missing",
                        (
                            f"component {ref} ({comp.footprint}) requires LCSC part mapping "
                            "or explicit lcsc_exceptions reason"
                        ),
                        _source_display(spec.dfm.raw),
                    )

            for ref in sorted(lcsc_parts):
                if ref not in board.components:
                    add(
                        "warning",
                        "dfm.lcsc_part_unused",
                        f"dfm.lcsc_parts entry {ref} does not exist on the board",
                        _source_display(spec.dfm.raw),
                    )
            if spec.dfm.max_lcsc_exceptions is not None:
                excepted_count = sum(
                    1
                    for ref in board.components
                    if not _is_helper_component(ref) and ref in lcsc_exceptions
                )
                if excepted_count > spec.dfm.max_lcsc_exceptions:
                    add(
                        "error",
                        "dfm.lcsc_exceptions_exceed_limit",
                        (
                            f"lcsc exceptions {excepted_count} exceed allowed "
                            f"{spec.dfm.max_lcsc_exceptions}"
                        ),
                        _source_display(spec.dfm.raw),
                    )

    # First mechanical gate: hole-to-edge margin and fiducial-vs-hole overlap.
    minimum_hole_edge_clearance_mm = 0.25
    for mounting_hole in spec.mounting_holes:
        source = _source_display(mounting_hole.raw)
        radius = mounting_hole.drill / 2.0
        min_edge = min(
            mounting_hole.at[0],
            mounting_hole.at[1],
            max(0.0, spec.width - mounting_hole.at[0]),
            max(0.0, spec.height - mounting_hole.at[1]),
        )
        edge_clearance = min_edge - radius
        if edge_clearance < minimum_hole_edge_clearance_mm:
            add(
                "error",
                "mech.hole_edge_clearance",
                (
                    f"mounting hole {mounting_hole.name} edge clearance {edge_clearance:.3f}mm "
                    f"is below {minimum_hole_edge_clearance_mm:.3f}mm"
                ),
                source,
            )

    for fiducial in spec.fiducials:
        fid_source = _source_display(fiducial.raw)
        fid_radius = (fiducial.diameter or 1.0) / 2.0
        for mounting_hole in spec.mounting_holes:
            delta_x = fiducial.at[0] - mounting_hole.at[0]
            delta_y = fiducial.at[1] - mounting_hole.at[1]
            center_distance = math.sqrt(delta_x * delta_x + delta_y * delta_y)
            required = fid_radius + mounting_hole.diameter / 2.0 + 0.2
            if center_distance < required:
                add(
                    "error",
                    "mech.fiducial_hole_overlap",
                    (
                        f"fiducial {fiducial.name} is {center_distance:.3f}mm from hole {mounting_hole.name}; "
                        f"requires >= {required:.3f}mm"
                    ),
                    fid_source,
                )

    add_profile_enabled_checks()
    if warnerr:
        return escalate_production_warnings(checks)
    return checks


def _parse_drc_unconnected(report_path: Path, spec: PhysicalSpec) -> list[DrcUnconnectedEntry]:
    if not report_path.exists():
        return []
    route_by_net: dict[str, list[dict]] = {}
    for route in spec.routes:
        raw = route.raw
        if "net" in raw:
            route_by_net.setdefault(str(raw["net"]), []).append(raw)
        for net_name in raw.get("nets") or []:
            route_by_net.setdefault(str(net_name), []).append(raw)

    stitch_by_net: dict[str, list[dict]] = {}
    for stitch in spec.power_stitches:
        raw = stitch.raw
        if "net" in raw:
            stitch_by_net.setdefault(str(raw["net"]), []).append(raw)

    entries: list[DrcUnconnectedEntry] = []
    current: list[tuple[str, str]] = []
    in_unconnected = False
    for line in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[unconnected_items]" in line:
            if current:
                entries.append(_drc_entry_from_pads(current, route_by_net, stitch_by_net))
                current = []
            in_unconnected = True
            continue
        if line.startswith("[") and in_unconnected:
            if current:
                entries.append(_drc_entry_from_pads(current, route_by_net, stitch_by_net))
                current = []
            in_unconnected = False
        if not in_unconnected:
            continue
        match = _PAD_RE.search(line)
        if match:
            current.append((match.group("net"), f"{match.group('ref')}.{match.group('pin')}"))
    if current:
        entries.append(_drc_entry_from_pads(current, route_by_net, stitch_by_net))
    return entries


_DRC_HEADER_RE = re.compile(r"^\[(?P<code>[^\]]+)\]:\s*(?P<title>.+?)\s*$")
_DRC_COORD_RE = re.compile(
    r"@\((?P<x>-?\d+(?:\.\d+)?)\s*mm,\s*(?P<y>-?\d+(?:\.\d+)?)\s*mm\)",
    re.IGNORECASE,
)
_DRC_NET_TOKEN_RE = re.compile(r"\[([^\]]+)\]")
_DRC_SEVERITY_RE = re.compile(r";\s*(error|warning)\s*$", re.IGNORECASE)


def _route_and_stitch_by_net(spec: PhysicalSpec) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    route_by_net: dict[str, list[dict]] = {}
    for route in spec.routes:
        raw = route.raw
        if "net" in raw:
            route_by_net.setdefault(str(raw["net"]), []).append(raw)
        for net_name in raw.get("nets") or []:
            route_by_net.setdefault(str(net_name), []).append(raw)

    stitch_by_net: dict[str, list[dict]] = {}
    for stitch in spec.power_stitches:
        raw = stitch.raw
        if "net" in raw:
            stitch_by_net.setdefault(str(raw["net"]), []).append(raw)
    return route_by_net, stitch_by_net


def _stitch_refs_for_violation(raw: dict) -> set[str]:
    refs = _stitch_pad_refs(raw)
    refs.update(_stitch_deferred_refs(raw))
    return refs


def _specific_violation_source_reasons(
    *,
    pads: list[str],
    nets: set[str],
    stitch_by_net: dict[str, list[dict]],
) -> set[DrcSourceReason]:
    if not pads:
        return set()
    pad_set = set(pads)
    source_reasons: set[DrcSourceReason] = set()
    for net in nets:
        for raw in stitch_by_net.get(net, []):
            if not _stitch_refs_for_violation(raw).intersection(pad_set):
                continue
            source_reason = _source_reason(
                "power_stitch",
                raw,
                fallback_reason="matched violated pad in power stitch intent",
            )
            if source_reason is not None:
                source_reasons.add(source_reason)
    return source_reasons


def _net_fallback_violation_source_reasons(
    *,
    nets: set[str],
    route_by_net: dict[str, list[dict]],
    stitch_by_net: dict[str, list[dict]],
) -> set[DrcSourceReason]:
    source_reasons: set[DrcSourceReason] = set()
    for net in nets:
        for raw in route_by_net.get(net, []):
            source_reason = _source_reason(
                "route",
                raw,
                fallback_reason="net-level fallback from route intent on violated net",
            )
            if source_reason is not None:
                source_reasons.add(source_reason)
        for raw in stitch_by_net.get(net, []):
            source_reason = _source_reason(
                "power_stitch",
                raw,
                fallback_reason="net-level fallback from power stitch intent on violated net",
            )
            if source_reason is not None:
                source_reasons.add(source_reason)
    return source_reasons


def _parse_drc_violations(report_path: Path, spec: PhysicalSpec) -> list[DrcViolationEntry]:
    if not report_path.exists():
        return []

    route_by_net, stitch_by_net = _route_and_stitch_by_net(spec)
    violations: list[DrcViolationEntry] = []
    current_code: str | None = None
    current_title = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_code, current_title, current_lines
        if current_code is None:
            return
        if current_code == "unconnected_items":
            current_code = None
            current_title = ""
            current_lines = []
            return
        entry = _drc_violation_from_block(
            code=current_code,
            title=current_title,
            lines=current_lines,
            route_by_net=route_by_net,
            stitch_by_net=stitch_by_net,
        )
        violations.append(entry)
        current_code = None
        current_title = ""
        current_lines = []

    for raw_line in report_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.rstrip()
        header = _DRC_HEADER_RE.match(line)
        if header:
            flush()
            current_code = header.group("code").strip()
            current_title = header.group("title").strip()
            continue
        if current_code is not None and line.strip():
            current_lines.append(line.strip())
    flush()
    return violations


def _drc_violation_from_block(
    *,
    code: str,
    title: str,
    lines: list[str],
    route_by_net: dict[str, list[dict]],
    stitch_by_net: dict[str, list[dict]],
) -> DrcViolationEntry:
    severity = "error"
    coords: list[tuple[float, float]] = []
    pads: list[str] = []
    nets: set[str] = set()

    for line in lines:
        severity_match = _DRC_SEVERITY_RE.search(line)
        if severity_match:
            severity = severity_match.group(1).lower()
        for coord_match in _DRC_COORD_RE.finditer(line):
            coords.append((float(coord_match.group("x")), float(coord_match.group("y"))))
        pad_match = _PAD_RE.search(line)
        if pad_match:
            pad_net = pad_match.group("net")
            nets.add(pad_net)
            pads.append(f"{pad_match.group('ref')}.{pad_match.group('pin')}")
        for token in _DRC_NET_TOKEN_RE.findall(line):
            if token and token.lower() not in {"f.cu", "b.cu", "in1.cu", "in2.cu"}:
                nets.add(token)

    source_reasons = _specific_violation_source_reasons(
        pads=pads,
        nets=nets,
        stitch_by_net=stitch_by_net,
    )
    if not source_reasons and nets:
        source_reasons = _net_fallback_violation_source_reasons(
            nets=nets,
            route_by_net=route_by_net,
            stitch_by_net=stitch_by_net,
        )

    return DrcViolationEntry(
        code=code,
        title=title,
        severity=severity,
        lines=lines,
        nets=sorted(nets),
        pads=pads,
        source_reasons=sorted(source_reasons, key=lambda reason: (reason.kind, reason.name)),
        coordinates=coords,
    )


def format_drc_violations(entries: list[DrcViolationEntry]) -> str:
    lines = [f"drc_violations: {len(entries)}"]
    for entry in entries:
        nets = f" nets={','.join(entry.nets)}" if entry.nets else ""
        pads = f" pads={','.join(entry.pads)}" if entry.pads else ""
        lines.append(f"{entry.severity}\t{entry.code}\t{entry.title}{nets}{pads}")
    return "\n".join(lines) + "\n"


def _sorted_source_reasons(
    reasons: list[DrcSourceReason] | set[DrcSourceReason],
) -> list[DrcSourceReason]:
    return sorted(
        reasons,
        key=lambda reason: (reason.kind, reason.name, reason.reason, reason.source),
    )


def _source_reason_payload(reason: DrcSourceReason) -> dict[str, str]:
    return {
        "kind": reason.kind,
        "name": reason.name,
        "reason": reason.reason,
        "source": reason.source,
    }


def _drc_unconnected_summary_payload(summary: DrcUnconnectedSummary) -> dict[str, Any]:
    return {
        "route_groups": {
            name: summary.route_groups[name]
            for name in sorted(summary.route_groups)
        },
        "route_intents": {
            name: summary.route_intents[name]
            for name in sorted(summary.route_intents)
        },
        "power_stitches": {
            name: summary.power_stitches[name]
            for name in sorted(summary.power_stitches)
        },
        "unattributed_nets": {
            name: summary.unattributed_nets[name]
            for name in sorted(summary.unattributed_nets)
        },
        "buckets": [
            {
                "kind": bucket.kind,
                "name": bucket.name,
                "unconnected": bucket.unconnected,
                "pads": bucket.pads,
                "nets": sorted(bucket.nets),
                "route_intents": sorted(bucket.route_intents),
                "power_stitches": sorted(bucket.power_stitches),
                "source_reasons": [
                    _source_reason_payload(reason)
                    for reason in _sorted_source_reasons(bucket.source_reasons)
                ],
            }
            for bucket in summary.buckets
        ],
    }


def format_drc_diagnostics_json(
    drc_violations: list[DrcViolationEntry],
    drc_unconnected: list[DrcUnconnectedEntry],
) -> str:
    payload = {
        "drc_violations": len(drc_violations),
        "drc_unconnected": len(drc_unconnected),
        "findings": [
            {
                "severity": entry.severity,
                "code": entry.code,
                "title": entry.title,
                "nets": entry.nets,
                "pads": entry.pads,
                "coordinates": [[x, y] for x, y in entry.coordinates],
                "source_reasons": [
                    _source_reason_payload(reason)
                    for reason in _sorted_source_reasons(entry.source_reasons)
                ],
            }
            for entry in drc_violations
        ],
        "unconnected_items": [
            {
                "net": entry.net,
                "pads": sorted(entry.pads),
                "route_intents": sorted(entry.route_intents),
                "route_groups": sorted(entry.route_groups),
                "power_stitches": sorted(entry.power_stitches),
                "source_reasons": [
                    _source_reason_payload(reason)
                    for reason in _sorted_source_reasons(entry.source_reasons)
                ],
                "message": entry.message,
            }
            for entry in drc_unconnected
        ],
        "unconnected_summary": _drc_unconnected_summary_payload(
            summarize_drc_unconnected(drc_unconnected)
        ),
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def format_drc_violations_json(entries: list[DrcViolationEntry]) -> str:
    return format_drc_diagnostics_json(entries, [])


def format_route_failures_json(failures: list[RouteFailureReport]) -> str:
    payload = {
        "strict_aborted": True,
        "failed_candidate_count": len(failures),
        "violation_count": sum(len(failure.violations) for failure in failures),
        "failures": [
            {
                "net": failure.net,
                "strategy": failure.strategy,
                "route_name": failure.route_name,
                "route_index": failure.route_index,
                "alternative_name": failure.alternative_name,
                "template_name": failure.template_name,
                "assignment": failure.assignment or {},
                "failed_stage": failure.failed_stage,
                "moved_refs": list(failure.moved_refs),
                "placement_moves": [
                    {
                        "name": move.get("name", ""),
                        "ref": move.get("ref", ""),
                        "original_position": list(move.get("original_position", ())),
                        "staged_position": list(move.get("staged_position", ())),
                        "dx": move.get("dx"),
                        "dy": move.get("dy"),
                    }
                    for move in failure.placement_moves
                ],
                "replacement": (
                    {
                        "nets": list(failure.replacement_report.nets),
                        "removed_segments": failure.replacement_report.removed_segments,
                        "removed_vias": failure.replacement_report.removed_vias,
                        "by_net": [
                            {
                                "net": entry.get("net", ""),
                                "removed_segments": entry.get("removed_segments", 0),
                                "removed_vias": entry.get("removed_vias", 0),
                            }
                            for entry in failure.replacement_report.by_net
                        ],
                    }
                    if failure.replacement_report is not None
                    else {}
                ),
                "source": failure.source,
                "candidate": {
                    "segments": [
                        {
                            "start": list(segment.start),
                            "end": list(segment.end),
                            "layer": segment.layer,
                            "width": segment.width,
                        }
                        for segment in failure.candidate.segments
                    ],
                    "vias": [
                        {
                            "position": list(via.position),
                            "size": via.size,
                            "drill": via.drill,
                            "layers": list(via.layers),
                            "via_type": via.via_type,
                        }
                        for via in failure.candidate.vias
                    ],
                    "segment_layers": list(failure.candidate.segment_layers),
                    "via_layers": [
                        list(via_layers) for via_layers in failure.candidate.via_layers
                    ],
                    "used_layers": list(failure.candidate.used_layers),
                },
                "violations": [
                    {
                        "code": violation.code,
                        "message": violation.message,
                        "net": violation.net,
                        "layer": violation.layer,
                        "source": violation.source,
                    }
                    | ({"distance": violation.distance} if violation.distance is not None else {})
                    for violation in failure.violations
                ],
            }
            for failure in failures
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _write_production_report(
    result: CompilePhysicalResult,
    output_path: Path,
    *,
    report_format: str,
    lcsc_policy_summary: LcscPolicySummary | None,
    generated_artifacts: set[Path],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if report_format == "json":
        report_text = format_production_checks_json(
            result.production_checks,
            lcsc_policy_summary,
        )
    else:
        report_text = format_production_checks(result.production_checks)
    output_path.write_text(report_text, encoding="utf-8")
    generated_artifacts.add(output_path.resolve())


def _write_drc_diagnostics_report(
    result: CompilePhysicalResult,
    output_path: Path,
    *,
    report_format: str,
    generated_artifacts: set[Path],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if report_format == "json":
        diagnostics_text = format_drc_diagnostics_json(
            result.drc_violations,
            result.drc_unconnected,
        )
    else:
        diagnostics_text = format_drc_violations(result.drc_violations)
    output_path.write_text(diagnostics_text, encoding="utf-8")
    generated_artifacts.add(output_path.resolve())


def _write_route_diagnostics_report(
    failures: list[RouteFailureReport],
    output_path: Path,
    *,
    generated_artifacts: set[Path],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        format_route_failures_json(failures),
        encoding="utf-8",
    )
    generated_artifacts.add(output_path.resolve())


def _stable_archive_name(stem: str, source_path: Path) -> str:
    suffix = "".join(source_path.suffixes)
    return f"{stem}{suffix}" if suffix else stem


def _write_manufacturing_archive(
    output_path: Path,
    *,
    run_drc: bool,
    drc_report: Path | None,
    route_diagnostics_report: Path | None,
    bom_output: Path | None,
    pnp_output: Path | None,
    jlc_bom_output: Path | None,
    jlc_pnp_output: Path | None,
    gerber_output_dir: Path | None,
    drill_output_dir: Path | None,
    drc_diagnostics_report: Path | None,
    production_report: Path | None,
    build_summary_output: Path | None,
    validation_results_template_output: Path | None,
    generated_artifacts: set[Path],
) -> None:
    files_to_write: list[tuple[Path, str]] = []

    def require_generated(path: Path, *, kind: str) -> Path:
        resolved = path.resolve()
        if resolved not in generated_artifacts:
            raise RuntimeError(
                f"manufacturing archive source was not generated by the current run: {kind}: {path}"
            )
        if not path.exists():
            raise RuntimeError(
                f"manufacturing archive source is missing: {kind}: {path}"
            )
        if path.is_dir():
            entries = sorted(child for child in path.rglob("*") if child.is_file())
            if not entries:
                raise RuntimeError(
                    f"manufacturing archive source directory is empty: {kind}: {path}"
                )
        else:
            try:
                if path.stat().st_size <= 0:
                    raise RuntimeError(
                        f"manufacturing archive source file is empty: {kind}: {path}"
                    )
            except OSError as exc:
                raise RuntimeError(
                    f"manufacturing archive source is unreadable: {kind}: {path}"
                ) from exc
        return resolved

    def add_file(path: Path | None, archive_name: str, *, kind: str) -> None:
        if path is None:
            return
        require_generated(path, kind=kind)
        files_to_write.append((path, archive_name))

    def add_dir(path: Path | None, prefix: str, *, kind: str) -> None:
        if path is None:
            return
        require_generated(path, kind=kind)
        for child in sorted(entry for entry in path.rglob("*") if entry.is_file()):
            files_to_write.append((child, f"{prefix}/{child.relative_to(path).as_posix()}"))

    add_file(bom_output, "bom.csv", kind="bom")
    add_file(pnp_output, "pnp.csv", kind="pnp")
    add_file(
        jlc_bom_output,
        "jlc_bom.csv",
        kind="jlc_bom",
    )
    add_file(
        jlc_pnp_output,
        "jlc_pnp.csv",
        kind="jlc_pnp",
    )
    if route_diagnostics_report is not None:
        add_file(
            route_diagnostics_report,
            _stable_archive_name("route-diagnostics", route_diagnostics_report),
            kind="route_diagnostics",
        )
    if run_drc and drc_report is not None:
        add_file(drc_report, _stable_archive_name("drc-report", drc_report), kind="drc_report")
        if drc_diagnostics_report is not None:
            add_file(
                drc_diagnostics_report,
                _stable_archive_name("drc-diagnostics", drc_diagnostics_report),
                kind="drc_diagnostics",
            )
    if production_report is not None:
        add_file(
            production_report,
            _stable_archive_name("production-report", production_report),
            kind="production_report",
        )
    if build_summary_output is not None:
        add_file(
            build_summary_output,
            _stable_archive_name("build-summary", build_summary_output),
            kind="build_summary",
        )
    if validation_results_template_output is not None:
        add_file(
            validation_results_template_output,
            _validation_results_template_filename(),
            kind="validation_results_template",
        )
    add_dir(gerber_output_dir, "gerbers", kind="gerbers")
    add_dir(drill_output_dir, "drill", kind="drill")

    if not files_to_write:
        raise RuntimeError(
            "manufacturing archive requested but no manufacturing outputs were generated"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = tempfile.NamedTemporaryFile(
        prefix=f".{output_path.name}.tmp-",
        suffix=".zip",
        dir=output_path.parent,
        delete=False,
    )
    temp_path = Path(temp_file.name)
    temp_file.close()
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source_path, archive_name in files_to_write:
                archive.write(source_path, arcname=archive_name)
        temp_path.replace(output_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    generated_artifacts.add(output_path.resolve())


def _build_summary_payload(
    result: CompilePhysicalResult,
    spec: PhysicalSpec,
    *,
    board: Board,
    output_path: Path,
    enabled_route_groups: set[str] | None,
    strict: bool,
    production_check: bool,
    run_drc: bool,
    drc_report: Path | None,
    bom_output: Path | None,
    pnp_output: Path | None,
    jlc_bom_output: Path | None,
    jlc_pnp_output: Path | None,
    gerber_output_dir: Path | None,
    drill_output_dir: Path | None,
    drc_diagnostics_report: Path | None,
    production_report: Path | None,
    build_summary_output: Path | None,
    manufacturing_archive_output: Path | None,
    route_diagnostics_report: Path | None,
    validation_results_template_output: Path | None,
    generated_artifacts: set[Path],
) -> dict[str, Any]:
    route_metadata_by_index = _build_route_group_metadata_lookup(spec)
    committable = [entry for entry in result.route_report if entry.strategy != "power_probe"]
    committed = sum(1 for entry in committable if entry.committed)
    probes = sum(1 for entry in result.route_report if entry.strategy == "power_probe")
    route_gate_pass = committed == len(committable) and not result.commit_violations
    production_error_count = sum(1 for entry in result.production_checks if entry.severity == "error")
    drc_ran = result.drc_returncode is not None
    drc_pass = (
        drc_ran
        and result.drc_returncode == 0
        and not result.drc_violations
        and not result.drc_unconnected
    )
    pending_generated_artifacts: set[Path] = set()
    if build_summary_output is not None:
        pending_generated_artifacts.add(build_summary_output.resolve())
    if manufacturing_archive_output is not None:
        pending_generated_artifacts.add(manufacturing_archive_output.resolve())
    dfm_report = _build_dfm_report(result.production_checks)
    bom_state = summarize_bom_state(spec, board)
    part_alternates = summarize_part_alternates(spec, board)
    assembly_plan = summarize_assembly_plan(spec, board)
    lcsc_database = summarize_lcsc_database(spec, board)
    lcsc_cost = summarize_lcsc_cost(spec, board)
    lcsc_availability = summarize_lcsc_availability(spec, board)
    drc_source_coverage = _build_drc_source_coverage(
        drc_violations=result.drc_violations,
        drc_unconnected=result.drc_unconnected,
    )
    payload: dict[str, Any] = {
        "output_board": str(output_path.resolve()),
        "pass": (
            production_check
            and production_error_count == 0
            and drc_pass
            and route_gate_pass
        ),
        "strict": {
            "requested": strict,
            "route_gate_pass": route_gate_pass,
            "commit_violations": len(result.commit_violations),
        },
        "routes": {
            "committed": committed,
            "total": len(committable),
            "probe_count": probes,
        },
        "route_layer_usage": _build_route_layer_usage(
            result.route_report,
            route_metadata_by_index=route_metadata_by_index,
        ),
        "route_source_coverage": _build_route_source_coverage(
            result.route_report,
            route_metadata_by_index=route_metadata_by_index,
        ),
        "drc": {
            "requested": run_drc and drc_report is not None,
            "ran": drc_ran,
            "returncode": result.drc_returncode,
            "violation_count": len(result.drc_violations),
            "unconnected_count": len(result.drc_unconnected),
            "pass": drc_pass,
        },
        "drc_source_coverage": drc_source_coverage,
        "production_checks": {
            "enabled": production_check,
            "count": len(result.production_checks),
            "error_count": production_error_count,
        },
        "bom_state": _bom_state_payload(bom_state),
        "part_alternates": _part_alternates_payload(part_alternates),
        "assembly_plan": assembly_plan,
        "lcsc_database": _lcsc_database_payload(lcsc_database),
        "lcsc_cost": _lcsc_cost_payload(lcsc_cost),
        "lcsc_availability": _lcsc_availability_payload(lcsc_availability),
        "testpoint_coverage": _build_testpoint_coverage(spec, board),
        "route_groups": _build_route_group_summary(
            spec,
            enabled_route_groups=enabled_route_groups,
        ),
        "layer_roles": _build_layer_role_summary(spec),
        "mechanical_features": _build_mechanical_features_summary(spec),
        "manufacturing_geometry": _build_manufacturing_geometry_summary(board, spec),
        "validation": _build_validation_summary(spec),
        "validation_results_template": _build_validation_results_template_summary(
            spec,
            validation_results_template_output,
            generated_artifacts=generated_artifacts,
        ),
        "physical_residuals": result.physical_residuals,
        "footprint_state": result.footprint_state,
        "source_handoff": result.source_handoff,
        "package_physical_context": result.package_physical_context,
        "atopile_source_state": _build_atopile_source_state(
            spec,
            netlist=Path(str(result.source_handoff.get("netlist"))),
        ),
        "dfm_report": dfm_report,
        "artifacts": {
            "board": _artifact_record(output_path, generated_artifacts=generated_artifacts),
            "bom": _artifact_record(bom_output, generated_artifacts=generated_artifacts),
            "pnp": _artifact_record(pnp_output, generated_artifacts=generated_artifacts),
            "jlc_bom": _artifact_record(jlc_bom_output, generated_artifacts=generated_artifacts),
            "jlc_pnp": _artifact_record(jlc_pnp_output, generated_artifacts=generated_artifacts),
            "gerbers": _artifact_record(gerber_output_dir, generated_artifacts=generated_artifacts),
            "drill": _artifact_record(drill_output_dir, generated_artifacts=generated_artifacts),
            "drc_report": _artifact_record(drc_report, generated_artifacts=generated_artifacts),
            "route_diagnostics": _artifact_record(
                route_diagnostics_report,
                generated_artifacts=generated_artifacts,
            ),
            "drc_diagnostics": _artifact_record(
                drc_diagnostics_report,
                generated_artifacts=generated_artifacts,
            ),
            "production_report": _artifact_record(
                production_report,
                generated_artifacts=generated_artifacts,
            ),
            "build_summary": _artifact_record(
                build_summary_output,
                generated_artifacts=generated_artifacts,
                pending_generated_artifacts=pending_generated_artifacts,
            ),
            "manufacturing_archive": _artifact_record(
                manufacturing_archive_output,
                generated_artifacts=generated_artifacts,
                pending_generated_artifacts=pending_generated_artifacts,
            ),
            "validation_results_template": _artifact_record(
                validation_results_template_output,
                generated_artifacts=generated_artifacts,
            ),
        },
    }
    if result.lcsc_policy_summary is not None and result.lcsc_policy_summary.enabled:
        payload["lcsc_policy"] = {
            "mapped": result.lcsc_policy_summary.mapped,
            "excepted": result.lcsc_policy_summary.excepted,
            "missing": result.lcsc_policy_summary.missing,
            "mapped_refs": list(result.lcsc_policy_summary.mapped_refs),
            "excepted_refs": list(result.lcsc_policy_summary.excepted_refs),
            "missing_refs": list(result.lcsc_policy_summary.missing_refs),
        }
    return payload


def _write_build_summary(
    result: CompilePhysicalResult,
    spec: PhysicalSpec,
    output_path: Path,
    *,
    board: Board,
    enabled_route_groups: set[str] | None,
    strict: bool,
    production_check: bool,
    run_drc: bool,
    drc_report: Path | None,
    bom_output: Path | None,
    pnp_output: Path | None,
    jlc_bom_output: Path | None,
    jlc_pnp_output: Path | None,
    gerber_output_dir: Path | None,
    drill_output_dir: Path | None,
    drc_diagnostics_report: Path | None,
    production_report: Path | None,
    build_summary_output: Path,
    manufacturing_archive_output: Path | None,
    route_diagnostics_report: Path | None,
    validation_results_template_output: Path | None,
    generated_artifacts: set[Path],
) -> None:
    build_summary_output.parent.mkdir(parents=True, exist_ok=True)
    payload = _build_summary_payload(
        result,
        spec,
        board=board,
        output_path=output_path,
        enabled_route_groups=enabled_route_groups,
        strict=strict,
        production_check=production_check,
        run_drc=run_drc,
        drc_report=drc_report,
        bom_output=bom_output,
        pnp_output=pnp_output,
        jlc_bom_output=jlc_bom_output,
        jlc_pnp_output=jlc_pnp_output,
        gerber_output_dir=gerber_output_dir,
        drill_output_dir=drill_output_dir,
        drc_diagnostics_report=drc_diagnostics_report,
        production_report=production_report,
        build_summary_output=build_summary_output,
        manufacturing_archive_output=manufacturing_archive_output,
        route_diagnostics_report=route_diagnostics_report,
        validation_results_template_output=validation_results_template_output,
        generated_artifacts=generated_artifacts,
    )
    build_summary_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    generated_artifacts.add(build_summary_output.resolve())


def _drc_dfm_policy_for_profile(profile: str) -> dict[str, tuple[str, str]]:
    if profile.startswith("jlcpcb"):
        return {
            "hole_clearance": ("error", "dfm.drc_hole_clearance"),
            "hole_to_hole": ("error", "dfm.drc_hole_to_hole"),
            "holes_co_located": ("error", "dfm.drc_holes_co_located"),
            "copper_edge_clearance": ("error", "dfm.drc_copper_edge_clearance"),
            "solder_mask_bridge": ("error", "dfm.drc_solder_mask_bridge"),
            "silk_edge_clearance": ("warning", "dfm.drc_silk_edge_clearance"),
            "silk_over_copper": ("warning", "dfm.drc_silk_over_copper"),
        }
    return {}


def _collect_declared_lcsc_codes(spec: PhysicalSpec) -> tuple[str, ...]:
    declared: set[str] = set()
    if spec.dfm is not None:
        for _ref, code in spec.dfm.lcsc_parts.items():
            canonical = _canonicalize_lcsc_code(str(code))
            if canonical:
                declared.add(canonical)
        for _ref, alternates in spec.dfm.lcsc_alternates.items():
            for code in alternates:
                canonical = _canonicalize_lcsc_code(str(code))
                if canonical:
                    declared.add(canonical)
    return tuple(sorted(declared))


def _canonicalize_lcsc_code(code: str) -> str:
    text = code.strip()
    if not text:
        return text
    if re.fullmatch(r"[Cc]\d+", text):
        return "C" + text[1:]
    if re.fullmatch(r"\d+", text):
        return "C" + text
    return text


def _normalize_lcsc_code_for_lookup(code: str) -> str:
    if re.fullmatch(r"[Cc]\d+", code):
        return code[1:]
    return code


def _query_lcsc_database(database_path: Path, codes: list[str]) -> dict[str, LcscDatabaseCodePayload]:
    results: dict[str, LcscDatabaseCodePayload] = {}
    if not codes:
        return results

    lookup_to_canonical: dict[str, list[str]] = {}
    lookup_codes: list[str] = []
    seen_lookup_codes: set[str] = set()
    for canonical in codes:
        canonical = canonical.strip()
        if not canonical:
            continue
        lookup_variants = (canonical, _normalize_lcsc_code_for_lookup(canonical))
        for lookup_code in lookup_variants:
            if lookup_code not in seen_lookup_codes:
                seen_lookup_codes.add(lookup_code)
                lookup_codes.append(lookup_code)
            canonical_targets = lookup_to_canonical.setdefault(lookup_code, [])
            if canonical not in canonical_targets:
                canonical_targets.append(canonical)

    query_marks = ",".join(["?"] * len(lookup_codes))
    sql = f"SELECT lcsc, stock, basic, preferred, package, description, price FROM v_components WHERE lcsc IN ({query_marks})"
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, lookup_codes).fetchall()
    for row in rows:
        lookup_code = str(row["lcsc"]).strip()
        if not lookup_code:
            continue
        canonical_targets = lookup_to_canonical.get(lookup_code, [])
        if not canonical_targets:
            continue
        canonical_code = sorted(canonical_targets)[0]
        canonical_code = _canonicalize_lcsc_code(canonical_code)
        if canonical_code in results:
            continue
        stock_value = row["stock"] if row["stock"] is not None else None
        try:
            stock = int(stock_value)
        except (TypeError, ValueError):
            stock = None
        results[canonical_code] = LcscDatabaseCodePayload(
            stock=stock,
            basic=str(row["basic"]) if row["basic"] is not None else None,
            preferred=str(row["preferred"]) if row["preferred"] is not None else None,
            package=str(row["package"]) if row["package"] is not None else None,
            description=str(row["description"]) if row["description"] is not None else None,
            price=str(row["price"]) if row["price"] is not None else None,
        )
    return results


def summarize_lcsc_database(spec: PhysicalSpec, board: Board) -> LcscDatabaseSummary:
    if spec.dfm is None or not spec.dfm.lcsc_database:
        return LcscDatabaseSummary(
            configured=False,
            path=None,
            strict=False,
            exists=False,
            checked_codes=(),
            checked_code_count=0,
            found_code_count=0,
            missing_codes=(),
            missing_code_count=0,
            codes={},
            passed=True,
        )

    lcsc_database_config = spec.dfm.lcsc_database
    path = _resolve(lcsc_database_config["path"], spec.path.parent)
    strict = lcsc_database_config.get("strict", True)
    declared_codes = _collect_declared_lcsc_codes(spec)
    resolved_path = path.resolve()

    if not resolved_path.exists():
        return LcscDatabaseSummary(
            configured=True,
            path=str(resolved_path),
            strict=bool(strict),
            exists=False,
            checked_codes=declared_codes,
            checked_code_count=len(declared_codes),
            found_code_count=0,
            missing_codes=declared_codes,
            missing_code_count=len(declared_codes),
            codes={},
            passed=(not strict) and (not declared_codes),
        )

    rows = _query_lcsc_database(resolved_path, list(declared_codes))
    missing_codes = tuple(sorted(code for code in declared_codes if code not in rows))
    return LcscDatabaseSummary(
        configured=True,
        path=str(resolved_path),
        strict=bool(strict),
        exists=resolved_path.exists(),
        checked_codes=declared_codes,
        checked_code_count=len(declared_codes),
        found_code_count=len(rows),
        missing_codes=missing_codes,
        missing_code_count=len(missing_codes),
        codes=rows,
        passed=(len(missing_codes) == 0),
    )


def _pick_price_tier(price_json: str | None, required_quantity: int) -> tuple[float | None, int | None, int | None, bool]:
    if not price_json:
        return None, None, None, False
    try:
        tiers_raw = json.loads(price_json)
    except (TypeError, ValueError):
        return None, None, None, False
    if not isinstance(tiers_raw, list) or not tiers_raw:
        return None, None, None, False
    tiers: list[tuple[int, int | None, float]] = []
    for tier in tiers_raw:
        if not isinstance(tier, dict):
            continue
        q_from = tier.get("qFrom")
        price = tier.get("price")
        if not isinstance(q_from, int) or isinstance(q_from, bool):
            continue
        try:
            unit_price = float(price)
        except (TypeError, ValueError):
            continue
        q_to_raw = tier.get("qTo")
        q_to = q_to_raw if isinstance(q_to_raw, int) and not isinstance(q_to_raw, bool) else None
        tiers.append((q_from, q_to, unit_price))
    if not tiers:
        return None, None, None, False
    tiers = sorted(tiers, key=lambda item: item[0])
    for q_from, q_to, unit_price in tiers:
        if required_quantity >= q_from and (q_to is None or required_quantity <= q_to):
            return unit_price, q_from, q_to, False
    first_q_from, first_q_to, first_price = tiers[0]
    if required_quantity < first_q_from:
        return first_price, first_q_from, first_q_to, True
    last_q_from, last_q_to, last_price = tiers[-1]
    return last_price, last_q_from, last_q_to, False


def summarize_lcsc_cost(spec: PhysicalSpec, board: Board) -> LcscCostSummary:
    if spec.dfm is None or not spec.dfm.lcsc_cost:
        return LcscCostSummary(False, None, 0, 0, 0, (), 0.0, 0.0, True, ())
    batch_quantity = spec.dfm.lcsc_cost["batch_quantity"]
    lcsc_db = summarize_lcsc_database(spec, board)
    refs_by_code: dict[str, list[str]] = {}
    for ref, code in sorted(spec.dfm.lcsc_parts.items()):
        code_text = str(code).strip()
        if code_text:
            refs_by_code.setdefault(code_text, []).append(ref)
    lines: list[LcscCostLine] = []
    estimated_batch = 0.0
    unpriced_codes: list[str] = []
    for code in sorted(refs_by_code):
        refs = tuple(sorted(refs_by_code[code]))
        ref_count = len(refs)
        required_quantity = ref_count * batch_quantity
        db_entry = lcsc_db.codes.get(code)
        unit_price, q_from, q_to, below_minimum = _pick_price_tier(
            db_entry.price if db_entry is not None else None,
            required_quantity,
        )
        extended = None if unit_price is None else round(unit_price * required_quantity, 6)
        if extended is None:
            unpriced_codes.append(code)
        else:
            estimated_batch += extended
        lines.append(
            LcscCostLine(code, refs, ref_count, required_quantity, unit_price, extended, q_from, q_to, below_minimum)
        )
    line_count = len(lines)
    priced_line_count = sum(1 for line in lines if line.extended_price_usd is not None)
    unpriced_line_count = line_count - priced_line_count
    estimated_batch = round(estimated_batch, 6)
    estimated_unit = round(estimated_batch / batch_quantity, 6)
    return LcscCostSummary(
        configured=True,
        batch_quantity=batch_quantity,
        line_count=line_count,
        priced_line_count=priced_line_count,
        unpriced_line_count=unpriced_line_count,
        unpriced_codes=tuple(sorted(unpriced_codes)),
        estimated_batch_components_usd=estimated_batch,
        estimated_unit_components_usd=estimated_unit,
        passed=unpriced_line_count == 0,
        lines=tuple(lines),
    )


def summarize_lcsc_availability(spec: PhysicalSpec, board: Board) -> LcscAvailabilitySummary:
    if spec.dfm is None or not spec.dfm.lcsc_availability:
        return LcscAvailabilitySummary(
            configured=False,
            batch_quantity=None,
            line_count=0,
            checked_line_count=0,
            shortage_line_count=0,
            unknown_stock_line_count=0,
            shortage_codes=(),
            unknown_stock_codes=(),
            passed=True,
            lines=(),
        )

    lcsc_cost_config = spec.dfm.lcsc_cost if spec.dfm is not None else {}
    batch_quantity = 1
    if lcsc_cost_config.get("batch_quantity") is not None:
        batch_quantity = int(lcsc_cost_config["batch_quantity"])

    primary_refs_by_code: dict[str, list[str]] = {}
    for ref, code in sorted(spec.dfm.lcsc_parts.items()):
        code_text = _canonicalize_lcsc_code(str(code))
        if not code_text:
            continue
        primary_refs_by_code.setdefault(code_text, []).append(ref)

    lcsc_db = summarize_lcsc_database(spec, board)
    lines: list[LcscAvailabilityLine] = []
    shortage_codes: list[str] = []
    unknown_stock_codes: list[str] = []

    for code in sorted(primary_refs_by_code):
        refs = tuple(sorted(primary_refs_by_code[code]))
        ref_count = len(refs)
        required_quantity = ref_count * batch_quantity
        db_entry = lcsc_db.codes.get(code)
        stock = db_entry.stock if db_entry is not None else None
        stock_sufficient = (
            stock is not None and stock >= required_quantity
        )
        if stock is None:
            shortage = required_quantity
        elif stock_sufficient:
            shortage = 0
        else:
            shortage = required_quantity - stock

        if stock is None:
            unknown_stock_codes.append(code)
        elif shortage > 0:
            shortage_codes.append(code)

        lines.append(
            LcscAvailabilityLine(
                code=code,
                refs=refs,
                ref_count=ref_count,
                required_quantity=required_quantity,
                stock=stock,
                stock_sufficient=stock_sufficient,
                shortage_quantity=shortage,
                basic=db_entry.basic if db_entry is not None else None,
                preferred=db_entry.preferred if db_entry is not None else None,
            )
        )

    line_count = len(lines)
    checked_line_count = len(lines)
    shortage_line_count = len(shortage_codes)
    unknown_stock_line_count = len(unknown_stock_codes)
    shortage_codes_tuple = tuple(sorted(shortage_codes))
    unknown_stock_codes_tuple = tuple(sorted(unknown_stock_codes))

    return LcscAvailabilitySummary(
        configured=True,
        batch_quantity=batch_quantity,
        line_count=line_count,
        checked_line_count=checked_line_count,
        shortage_line_count=shortage_line_count,
        unknown_stock_line_count=unknown_stock_line_count,
        shortage_codes=shortage_codes_tuple,
        unknown_stock_codes=unknown_stock_codes_tuple,
        passed=not shortage_codes and not unknown_stock_codes,
        lines=tuple(lines),
    )


def summarize_lcsc_policy(spec: PhysicalSpec, board: Board) -> LcscPolicySummary | None:
    if spec.dfm is None or spec.dfm.lcsc_policy != "require_or_exception":
        return None
    bom_state = summarize_bom_state(spec, board)
    return LcscPolicySummary(
        enabled=True,
        mapped=bom_state.mapped_count,
        excepted=bom_state.excepted_count,
        missing=bom_state.missing_count,
        mapped_refs=bom_state.mapped_refs,
        excepted_refs=bom_state.excepted_refs,
        missing_refs=bom_state.missing_refs,
    )


def summarize_bom_state(spec: PhysicalSpec, board: Board) -> BomStateSummary:
    mapped_refs: list[str] = []
    excepted_refs: list[str] = []
    missing_refs: list[str] = []
    for ref in sorted(board.components):
        if _is_helper_component(ref):
            continue
        if spec.dfm is not None and ref in spec.dfm.lcsc_exceptions:
            excepted_refs.append(ref)
        elif spec.dfm is not None and spec.dfm.lcsc_parts.get(ref, "").strip():
            mapped_refs.append(ref)
        else:
            missing_refs.append(ref)
    return BomStateSummary(
        part_count=len(mapped_refs) + len(excepted_refs) + len(missing_refs),
        mapped_count=len(mapped_refs),
        missing_count=len(missing_refs),
        excepted_count=len(excepted_refs),
        mapped_refs=tuple(mapped_refs),
        missing_refs=tuple(missing_refs),
        excepted_refs=tuple(excepted_refs),
        passed=len(missing_refs) == 0,
    )


def summarize_part_alternates(spec: PhysicalSpec, board: Board) -> PartAlternatesSummary:
    alternates_by_ref: dict[str, tuple[str, ...]] = {}
    if spec.dfm is not None:
        alternates_by_ref = {
            ref: tuple(sorted(alternates))
            for ref, alternates in spec.dfm.lcsc_alternates.items()
        }

    refs = tuple(sorted(alternates_by_ref))
    valid_refs = {
        ref
        for ref in board.components
        if not _is_helper_component(ref)
    }
    unused_refs = tuple(sorted(ref for ref in refs if ref not in valid_refs))
    declared_count = sum(len(alternates_by_ref[ref]) for ref in refs)

    return PartAlternatesSummary(
        declared_count=declared_count,
        ref_count=len(refs),
        refs=refs,
        alternates_by_ref=alternates_by_ref,
        unused_ref_count=len(unused_refs),
        unused_refs=unused_refs,
        passed=len(unused_refs) == 0,
    )


def summarize_assembly_plan(spec: PhysicalSpec, board: Board) -> dict[str, Any]:
    configured_methods = spec.dfm.assembly_methods if spec.dfm is not None else {}
    production_refs = sorted(ref for ref in board.components if not _is_helper_component(ref))
    method_counts: dict[str, int] = {}
    refs_by_method: dict[str, list[str]] = {}
    missing_refs: list[str] = []

    for ref in production_refs:
        method = configured_methods.get(ref)
        if method is None:
            missing_refs.append(ref)
            continue
        method_counts[method] = method_counts.get(method, 0) + 1
        refs_by_method.setdefault(method, []).append(ref)

    production_ref_set = set(production_refs)
    unknown_refs = sorted(ref for ref in configured_methods if ref not in production_ref_set)
    method_counts = {method: method_counts[method] for method in sorted(method_counts)}
    refs_by_method = {method: sorted(refs_by_method[method]) for method in sorted(refs_by_method)}

    configured = bool(configured_methods)
    return {
        "configured": configured,
        "component_count": len(production_refs),
        "assigned_count": sum(method_counts.values()),
        "missing_count": len(missing_refs),
        "unknown_ref_count": len(unknown_refs),
        "method_counts": method_counts,
        "missing_refs": missing_refs,
        "unknown_refs": unknown_refs,
        "refs_by_method": refs_by_method,
        "pass": (not configured) or (not missing_refs and not unknown_refs),
    }


def map_drc_violations_to_production_checks(
    *,
    profile: str | None,
    drc_violations: list[DrcViolationEntry],
) -> list[ProductionCheckEntry]:
    if not profile:
        return []
    policy = _drc_dfm_policy_for_profile(profile)
    if not policy:
        return []

    findings: list[ProductionCheckEntry] = []
    for entry in drc_violations:
        mapped = policy.get(entry.code)
        if mapped is None:
            continue
        severity, code = mapped
        source = ""
        if entry.source_reasons:
            first = entry.source_reasons[0]
            source = first.source
        findings.append(
            ProductionCheckEntry(
                severity=severity,
                code=code,
                message=f"KiCad DRC {entry.code}: {entry.title}",
                source=source,
            )
        )
    return findings


def _production_entry_from_check_finding(finding) -> ProductionCheckEntry:
    return ProductionCheckEntry(
        severity=finding.severity,
        code=finding.code,
        message=finding.message,
        source=finding.source,
        stage=getattr(finding, "stage", ""),
        package=getattr(finding, "package", ""),
        evidence=dict(getattr(finding, "evidence", {}) or {}),
        source_details=dict(getattr(finding, "source_details", {}) or {}),
        waived=bool(getattr(finding, "waived", False)),
        waiver_reason=str(getattr(finding, "waiver_reason", "") or ""),
    )


def _drc_entry_from_pads(
    pads_with_nets: list[tuple[str, str]],
    route_by_net: dict[str, list[dict]],
    stitch_by_net: dict[str, list[dict]],
) -> DrcUnconnectedEntry:
    net = pads_with_nets[0][0] if pads_with_nets else ""
    pads = [pad for _, pad in pads_with_nets]
    routes = route_by_net.get(net, [])
    stitches = stitch_by_net.get(net, [])
    real_stitches = [
        raw
        for raw in stitches
        if str(raw.get("kind", "pad_vias")) not in {"deferred", "unrouted", "airwire"}
    ]
    deferred_stitches = [
        raw
        for raw in stitches
        if str(raw.get("kind", "pad_vias")) in {"deferred", "unrouted", "airwire"}
    ]
    route_names = [str(raw.get("name", raw.get("kind", "route"))) for raw in routes]
    groups = sorted({group for raw in routes for group in _route_groups(raw)})
    stitch_names = [str(raw.get("name", raw.get("kind", "power_stitch"))) for raw in stitches]
    source_reasons: list[DrcSourceReason] = []

    if routes:
        message = "route intent exists but KiCad still reports this connection open"
        source_reasons = [
            source_reason
            for raw in routes
            if (source_reason := _source_reason("route", raw)) is not None
        ]
    elif stitches:
        covered = set().union(*(_stitch_pad_refs(raw) for raw in real_stitches))
        missing = [pad for pad in pads if pad not in covered]
        deferred = set().union(*(_stitch_deferred_refs(raw) for raw in stitches))
        omitted = [pad for pad in missing if pad not in deferred]
        deferred_missing = [pad for pad in missing if pad in deferred]
        if omitted:
            message = "power stitch intent exists but omits " + ", ".join(omitted)
        elif deferred_missing:
            deferred_names = [
                str(raw.get("name", raw.get("kind", "power_stitch")))
                for raw in deferred_stitches
                if _stitch_deferred_refs(raw).intersection(deferred_missing)
            ]
            if deferred_names:
                message = "power pad intentionally deferred: " + ", ".join(deferred_names)
                source_reasons = [
                    source_reason
                    for raw in deferred_stitches
                    if _stitch_deferred_refs(raw).intersection(deferred_missing)
                    if (source_reason := _source_reason("power_stitch", raw)) is not None
                ]
            else:
                message = "power stitch has deferred pad intent for " + ", ".join(deferred_missing)
        else:
            message = "power stitch intent exists but KiCad still reports this connection open"
    else:
        message = "no route or power-stitch intent for this net"

    return DrcUnconnectedEntry(
        net=net,
        pads=pads,
        route_intents=route_names,
        route_groups=groups,
        power_stitches=stitch_names,
        source_reasons=sorted(set(source_reasons), key=lambda reason: (reason.kind, reason.name)),
        message=message,
    )


def _bump_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def summarize_drc_unconnected(entries: list[DrcUnconnectedEntry]) -> DrcUnconnectedSummary:
    summary = DrcUnconnectedSummary()
    buckets: dict[tuple[str, str], DrcResidualBucket] = {}
    for entry in entries:
        for group in entry.route_groups:
            _bump_count(summary.route_groups, group)
        if entry.route_intents and not entry.route_groups:
            _bump_count(summary.route_groups, "ungrouped")
        for route in entry.route_intents:
            _bump_count(summary.route_intents, route)
        for stitch in entry.power_stitches:
            _bump_count(summary.power_stitches, stitch)
        if not entry.route_intents and not entry.power_stitches:
            _bump_count(summary.unattributed_nets, entry.net or "<unknown>")

        if entry.route_groups:
            key = ("group", "+".join(entry.route_groups))
        elif entry.power_stitches:
            key = ("source", "power_stitch")
        else:
            key = ("source", "unmapped")
        bucket = buckets.setdefault(key, DrcResidualBucket(kind=key[0], name=key[1]))
        bucket.unconnected += 1
        bucket.pads += len(entry.pads)
        if entry.net:
            bucket.nets.add(entry.net)
        bucket.route_intents.update(entry.route_intents)
        bucket.power_stitches.update(entry.power_stitches)
        bucket.source_reasons.update(entry.source_reasons)
    summary.buckets = [buckets[key] for key in sorted(buckets)]
    return summary


def compile_physical(
    spec_path: Path,
    *,
    netlist_path: Path | None = None,
    output_path: Path,
    place_only: bool = False,
    drc_report: Path | None = None,
    run_drc: bool = True,
    strict: bool = False,
    enabled_route_groups: set[str] | None = None,
    probe_deferred_power: bool = False,
    production_check: bool = False,
    bom_output: Path | None = None,
    pnp_output: Path | None = None,
    jlc_bom_output: Path | None = None,
    jlc_pnp_output: Path | None = None,
    gerber_output_dir: Path | None = None,
    drill_output_dir: Path | None = None,
    production_report: Path | None = None,
    production_report_format: str = "text",
    drc_diagnostics_report: Path | None = None,
    drc_diagnostics_format: str = "text",
    route_diagnostics_report: Path | None = None,
    build_summary_output: Path | None = None,
    manufacturing_archive_output: Path | None = None,
    include_helpers_in_exports: bool = True,
    source_contract_path: Path | None = None,
    enable_checks: list[str] | None = None,
    disable_checks: list[str] | None = None,
    disable_check_reasons: dict[str, str] | None = None,
    production_profiles: list[str] | None = None,
    warnerr: bool = False,
    allow_network_checks: bool = False,
    project_context: Any | None = None,
) -> CompilePhysicalResult:
    spec = load_physical_spec(spec_path)
    if source_contract_path is None:
        source_contract_path = _source_contract_path_from_spec(spec_path)
    source_contract = load_source_contract(
        _resolve(source_contract_path, spec_path.parent)
        if source_contract_path is not None
        else None
    )
    base = spec_path.parent
    netlist = netlist_path or spec.source_netlist
    if netlist is None:
        raise ValueError("netlist path is required via --netlist or source.netlist")
    netlist = _resolve(netlist, base)

    netlist_board = NetlistReader().read(netlist)
    physical_residuals = _build_physical_residuals(spec, netlist_board)
    footprint_state = _build_footprint_state(spec, netlist_board)
    package_physical_context = _build_package_physical_context(project_context)
    source_handoff = _build_source_handoff(
        spec,
        netlist=netlist,
        board=netlist_board,
        physical_residuals=physical_residuals,
        footprint_state=footprint_state,
    )
    board, placement_report = build_physical_board(spec, netlist, loaded_board=netlist_board)

    route_report: list[RouteReportEntry] = []
    commit_violations: list[CommitViolation] = []
    route_failures: list[RouteFailureReport] = []
    generated_artifacts: set[Path] = set()

    if not place_only:
        fanout_report, fanout_violations = compile_fanouts(board, spec, strict=strict)
        try:
            route_report, route_violations = apply_routes(
                board,
                spec,
                strict=strict,
                enabled_groups=enabled_route_groups,
            )
        except RouteCommitFailureError as exc:
            route_failures.extend(exc.reports)
            if route_diagnostics_report is not None:
                _write_route_diagnostics_report(
                    route_failures,
                    route_diagnostics_report,
                    generated_artifacts=generated_artifacts,
                )
            raise
        apply_planes(board, spec)
        stitch_report, stitch_violations = apply_power_stitches(
            board,
            spec,
            strict=strict,
            probe_deferred=probe_deferred_power,
        )
        route_report = fanout_report + route_report + stitch_report
        commit_violations = fanout_violations + route_violations + stitch_violations

    output_path.parent.mkdir(parents=True, exist_ok=True)
    from pardal.kicad_sdk_writer import KiCadSDKWriter

    writer = KiCadSDKWriter()
    if not writer.write_board(board, str(output_path)):
        raise RuntimeError(f"Failed to write {output_path}")
    generated_artifacts: set[Path] = {output_path.resolve()}

    if bom_output is not None:
        bom_output.parent.mkdir(parents=True, exist_ok=True)
        _write_bom_csv(board, bom_output, include_helpers=include_helpers_in_exports)
        generated_artifacts.add(bom_output.resolve())
    if pnp_output is not None:
        pnp_output.parent.mkdir(parents=True, exist_ok=True)
        _write_pnp_csv(board, pnp_output, include_helpers=include_helpers_in_exports)
        generated_artifacts.add(pnp_output.resolve())
    if jlc_bom_output is not None:
        jlc_bom_output.parent.mkdir(parents=True, exist_ok=True)
        _write_jlc_bom_csv(
            board,
            jlc_bom_output,
            include_helpers=include_helpers_in_exports,
            lcsc_parts=spec.dfm.lcsc_parts if spec.dfm is not None else {},
            assembly_methods=spec.dfm.assembly_methods if spec.dfm is not None else {},
        )
        generated_artifacts.add(jlc_bom_output.resolve())
    if jlc_pnp_output is not None:
        jlc_pnp_output.parent.mkdir(parents=True, exist_ok=True)
        _write_jlc_pnp_csv(
            board,
            jlc_pnp_output,
            include_helpers=include_helpers_in_exports,
            assembly_methods=spec.dfm.assembly_methods if spec.dfm is not None else {},
        )
        generated_artifacts.add(jlc_pnp_output.resolve())
    if route_diagnostics_report is not None and not route_failures:
        _write_route_diagnostics_report(
            route_failures,
            route_diagnostics_report,
            generated_artifacts=generated_artifacts,
        )
    if gerber_output_dir is not None:
        export_gerbers(output_path, gerber_output_dir)
        generated_artifacts.add(gerber_output_dir.resolve())
    if drill_output_dir is not None:
        export_drill(output_path, drill_output_dir)
        generated_artifacts.add(drill_output_dir.resolve())

    result = CompilePhysicalResult(
        output=output_path,
        placement_report=placement_report,
        route_report=route_report,
        commit_violations=commit_violations,
        route_failures=route_failures,
        production_checks=[],
        lcsc_policy_summary=summarize_lcsc_policy(spec, board) if production_check else None,
        lcsc_database_summary=summarize_lcsc_database(spec, board),
        physical_residuals=physical_residuals,
        footprint_state=footprint_state,
        source_handoff=source_handoff,
        package_physical_context=package_physical_context,
    )
    validation_results_template_output = (
        build_summary_output.parent / _validation_results_template_filename()
        if build_summary_output is not None and spec.validation_tests
        else None
    )
    if run_drc and drc_report is not None:
        drc_report.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                "kicad-cli",
                "pcb",
                "drc",
                str(output_path),
                "--output",
                str(drc_report),
            ],
            check=False,
            text=True,
            capture_output=True,
        )
        result.drc_returncode = completed.returncode
        if completed.stdout:
            result.warnings.append(completed.stdout.strip())
        if completed.stderr:
            result.warnings.append(completed.stderr.strip())
        if drc_report.exists():
            generated_artifacts.add(drc_report.resolve())
        result.drc_unconnected = _parse_drc_unconnected(drc_report, spec)
        result.drc_violations = _parse_drc_violations(drc_report, spec)
    mapped_drc_checks: list[ProductionCheckEntry] = []
    if production_check:
        planned_artifacts = set(generated_artifacts)
        if production_report is not None:
            planned_artifacts.add(production_report.resolve())
        if build_summary_output is not None:
            planned_artifacts.add(build_summary_output.resolve())
        if manufacturing_archive_output is not None:
            planned_artifacts.add(manufacturing_archive_output.resolve())
        if route_diagnostics_report is not None:
            planned_artifacts.add(route_diagnostics_report.resolve())
        if validation_results_template_output is not None:
            planned_artifacts.add(validation_results_template_output.resolve())
        if run_drc and drc_report is not None:
            planned_artifacts.add(drc_report.resolve())
        if (
            run_drc
            and drc_diagnostics_report is not None
            and drc_report is not None
        ):
            planned_artifacts.add(drc_diagnostics_report.resolve())
        mapped_drc_checks = map_drc_violations_to_production_checks(
            profile=spec.dfm.profile if spec.dfm is not None else None,
            drc_violations=result.drc_violations,
        )
        result.production_checks = check_production_readiness(
            spec,
            board,
            artifact_root=output_path.parent,
            include_artifact_contract=True,
            generated_artifacts=planned_artifacts,
            physical_residuals=result.physical_residuals,
            route_report=result.route_report,
            source_contract=source_contract,
            artifact_paths={
                "bom": bom_output,
                "pnp": pnp_output,
                "jlc_bom": jlc_bom_output,
                "jlc_pnp": jlc_pnp_output,
                "gerbers": gerber_output_dir,
                "drill": drill_output_dir,
                "drc_report": drc_report,
                "production_report": production_report,
                "build_summary": build_summary_output,
                "manufacturing_archive": manufacturing_archive_output,
            },
            enable_checks=enable_checks,
            disable_checks=disable_checks,
            disable_check_reasons=disable_check_reasons,
            production_profiles=production_profiles,
            warnerr=warnerr,
            allow_network_checks=allow_network_checks,
            project_context=project_context,
        ) + mapped_drc_checks
        if warnerr:
            result.production_checks = escalate_production_warnings(result.production_checks)
    if production_report is not None:
        _write_production_report(
            result,
            production_report,
            report_format=production_report_format,
            lcsc_policy_summary=result.lcsc_policy_summary,
            generated_artifacts=generated_artifacts,
        )
    if drc_diagnostics_report is not None and run_drc and drc_report is not None:
        _write_drc_diagnostics_report(
            result,
            drc_diagnostics_report,
            report_format=drc_diagnostics_format,
            generated_artifacts=generated_artifacts,
        )
    if validation_results_template_output is not None:
        _write_validation_results_template(
            spec,
            validation_results_template_output,
            summary_output=build_summary_output,
            generated_artifacts=generated_artifacts,
        )
    if build_summary_output is not None:
        _write_build_summary(
            result,
            spec,
            output_path,
            enabled_route_groups=enabled_route_groups,
            strict=strict,
            production_check=production_check,
            run_drc=run_drc,
            drc_report=drc_report,
            bom_output=bom_output,
            pnp_output=pnp_output,
            jlc_bom_output=jlc_bom_output,
            jlc_pnp_output=jlc_pnp_output,
            gerber_output_dir=gerber_output_dir,
            drill_output_dir=drill_output_dir,
            drc_diagnostics_report=drc_diagnostics_report,
            production_report=production_report,
            build_summary_output=build_summary_output,
            manufacturing_archive_output=manufacturing_archive_output,
            route_diagnostics_report=route_diagnostics_report,
            validation_results_template_output=validation_results_template_output,
            generated_artifacts=generated_artifacts,
            board=board,
        )
    if manufacturing_archive_output is not None:
        _write_manufacturing_archive(
            manufacturing_archive_output,
            run_drc=run_drc,
            drc_report=drc_report,
            bom_output=bom_output,
            pnp_output=pnp_output,
            jlc_bom_output=jlc_bom_output,
            jlc_pnp_output=jlc_pnp_output,
            gerber_output_dir=gerber_output_dir,
            drill_output_dir=drill_output_dir,
            drc_diagnostics_report=drc_diagnostics_report,
            production_report=production_report,
            build_summary_output=build_summary_output,
            route_diagnostics_report=route_diagnostics_report,
            validation_results_template_output=validation_results_template_output,
            generated_artifacts=generated_artifacts,
        )
    return result


def _source_contract_path_from_spec(spec_path: Path) -> Path | None:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load source contract references") from exc
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return None
    raw = data.get("source_contract")
    if raw is None:
        return None
    if isinstance(raw, dict):
        path = raw.get("path")
    else:
        path = raw
    if not path:
        return None
    return Path(str(path))


def _is_helper_component(ref: str) -> bool:
    return ref.startswith(("TP", "FID", "MH"))


def _component_refs_for_export(board: Board, *, include_helpers: bool) -> list[str]:
    refs = sorted(board.components)
    if include_helpers:
        return refs
    return [ref for ref in refs if not _is_helper_component(ref)]


def _component_refs_for_jlc_export(
    board: Board,
    *,
    assembly_methods: dict[str, str],
) -> list[str]:
    return [
        ref
        for ref in sorted(board.components)
        if not _is_helper_component(ref)
        and str(assembly_methods.get(ref, "jlc_smt")).lower() in {"jlc_smt", "smt", "jlc"}
    ]


def _write_bom_csv(board: Board, output_path: Path, *, include_helpers: bool) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ref", "value", "footprint", "layer"])
        for ref in _component_refs_for_export(board, include_helpers=include_helpers):
            comp = board.components[ref]
            writer.writerow([comp.ref, comp.value, comp.footprint, comp.layer])


def _component_side(layer: str) -> str:
    if layer == "B.Cu":
        return "bottom"
    return "top"


def _write_pnp_csv(board: Board, output_path: Path, *, include_helpers: bool) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ref", "x_mm", "y_mm", "rotation_deg", "side", "footprint"])
        for ref in _component_refs_for_export(board, include_helpers=include_helpers):
            comp = board.components[ref]
            writer.writerow(
                [
                    comp.ref,
                    f"{comp.position[0]:.4f}",
                    f"{comp.position[1]:.4f}",
                    f"{comp.rotation:.2f}",
                    _component_side(comp.layer),
                    comp.footprint,
                ]
            )


def _write_jlc_bom_csv(
    board: Board,
    output_path: Path,
    *,
    include_helpers: bool,
    lcsc_parts: dict[str, str],
    assembly_methods: dict[str, str],
) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Designator", "Comment", "Footprint", "LCSC Part #"])
        for ref in _component_refs_for_jlc_export(board, assembly_methods=assembly_methods):
            comp = board.components[ref]
            writer.writerow([comp.ref, comp.value, comp.footprint, lcsc_parts.get(comp.ref, "")])


def _write_jlc_pnp_csv(
    board: Board,
    output_path: Path,
    *,
    include_helpers: bool,
    assembly_methods: dict[str, str],
) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for ref in _component_refs_for_jlc_export(board, assembly_methods=assembly_methods):
            comp = board.components[ref]
            writer.writerow(
                [
                    comp.ref,
                    f"{comp.position[0]:.4f}mm",
                    f"{comp.position[1]:.4f}mm",
                    "Bottom" if _component_side(comp.layer) == "bottom" else "Top",
                    f"{comp.rotation:.2f}",
                ]
            )
