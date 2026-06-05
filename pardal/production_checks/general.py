from __future__ import annotations

import math
from pathlib import Path

from pardal.production_checks.models import CheckContext, CheckFinding
from pardal.production_checks.registry import registry


def _artifact_exists(ctx: CheckContext, key: str) -> bool:
    path = ctx.artifact_paths.get(key)
    if path is None:
        return False
    resolved = path.resolve()
    if resolved in ctx.generated_artifacts:
        return True
    if not path.exists():
        return False
    if path.is_dir():
        return any(child.is_file() for child in path.rglob("*"))
    return path.stat().st_size > 0


def _spec_source(ctx: CheckContext) -> str:
    path = getattr(ctx.spec, "path", None)
    return str(path) if path else ""


@registry.register("release.gerbers_missing", default_severity="error")
def release_gerbers_missing(ctx: CheckContext) -> list[CheckFinding]:
    if _artifact_exists(ctx, "gerbers"):
        return []
    return [
        CheckFinding(
            "error",
            "release.gerbers_missing",
            "release profile requires generated Gerber files",
            _spec_source(ctx),
        )
    ]


@registry.register("release.drill_missing", default_severity="error")
def release_drill_missing(ctx: CheckContext) -> list[CheckFinding]:
    if _artifact_exists(ctx, "drill"):
        return []
    return [
        CheckFinding(
            "error",
            "release.drill_missing",
            "release profile requires generated Excellon drill files",
            _spec_source(ctx),
        )
    ]


@registry.register("release.archive_not_uploadable", default_severity="error")
def release_archive_not_uploadable(ctx: CheckContext) -> list[CheckFinding]:
    archive = ctx.manufacturing_archive
    if archive is None:
        return []
    if not archive.exists() or archive.stat().st_size <= 0:
        return [
            CheckFinding(
                "error",
                "release.archive_not_uploadable",
                "manufacturing archive is missing or empty",
                str(archive),
            )
        ]
    import zipfile

    with zipfile.ZipFile(archive) as zf:
        names = [info.filename for info in zf.infolist() if not info.is_dir()]
    has_gerber = any(name.startswith("gerbers/") and name.lower().endswith(".gbr") for name in names)
    has_drill = any(name.startswith("drill/") and name.lower().endswith((".drl", ".xnc")) for name in names)
    if has_gerber and has_drill:
        return []
    missing = []
    if not has_gerber:
        missing.append("gerbers/*.gbr")
    if not has_drill:
        missing.append("drill/*.drl")
    return [
        CheckFinding(
            "error",
            "release.archive_not_uploadable",
            "manufacturing archive is missing upload files: " + ", ".join(missing),
            str(archive),
        )
    ]


@registry.register("footprint.package_reference_missing", default_severity="error")
def footprint_package_reference_missing(ctx: CheckContext) -> list[CheckFinding]:
    project_context = getattr(ctx, "project_context", None)
    footprints = getattr(project_context, "footprints", {}) if project_context is not None else {}
    findings: list[CheckFinding] = []
    for ref, component in sorted(ctx.source_contract.components.items()):
        footprint_id = component.get("footprint_id")
        raw_footprint = component.get("footprint")
        if footprint_id:
            if str(footprint_id) not in footprints:
                findings.append(
                    CheckFinding(
                        "error",
                        "footprint.package_reference_missing",
                        f"component {ref} references unknown package footprint {footprint_id}",
                        _contract_source(ctx),
                    )
                )
            continue
        if raw_footprint:
            findings.append(
                CheckFinding(
                    "error",
                    "footprint.package_reference_missing",
                    f"component {ref} uses raw footprint {raw_footprint}; production profile requires package footprint_id",
                    _contract_source(ctx),
                )
            )
    return findings


@registry.register("footprint.package_mismatch", default_severity="error")
def footprint_package_mismatch(ctx: CheckContext) -> list[CheckFinding]:
    project_context = getattr(ctx, "project_context", None)
    if project_context is None:
        return []
    parts = getattr(project_context, "parts", {}) or {}
    footprints = getattr(project_context, "footprints", {}) or {}
    findings: list[CheckFinding] = []
    for ref, component in sorted(ctx.source_contract.components.items()):
        part_id = component.get("part_id")
        footprint_id = component.get("footprint_id")
        if not part_id or not footprint_id:
            continue
        part = parts.get(str(part_id))
        if part is None or not getattr(part, "footprint", None):
            continue
        selected_footprint = str(footprint_id)
        declared_footprint = str(part.footprint)
        if selected_footprint not in footprints:
            continue
        if selected_footprint != declared_footprint:
            findings.append(
                CheckFinding(
                    "error",
                    "footprint.package_mismatch",
                    (
                        f"component {ref} selects part {part_id} with footprint "
                        f"{declared_footprint}, but source contract selects {selected_footprint}"
                    ),
                    _contract_source(ctx),
                )
            )
    return findings


@registry.register("power.rail_budget_missing", default_severity="error")
def power_rail_budget_missing(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for name, rail in ctx.source_contract.rails.items():
        if rail.get("max_load_ma") is None:
            findings.append(
                CheckFinding(
                    "error",
                    "power.rail_budget_missing",
                    f"rail {name} requires max_load_ma in source contract",
                    _contract_source(ctx),
                )
            )
    return findings


@registry.register("power.linear_regulator_drop_too_high", default_severity="error")
def power_linear_regulator_drop_too_high(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for name, rail in ctx.source_contract.rails.items():
        regulator = str(rail.get("regulator", "")).lower()
        if regulator and regulator != "linear":
            continue
        input_v = _float_or_none(rail.get("input_voltage_v"))
        output_v = _float_or_none(rail.get("output_voltage_v"))
        load_ma = _float_or_none(rail.get("max_load_ma"))
        max_dissipation_mw = _float_or_none(rail.get("max_regulator_dissipation_mw"))
        if input_v is None or output_v is None or load_ma is None:
            continue
        dissipation_mw = max(0.0, input_v - output_v) * load_ma
        if max_dissipation_mw is None:
            findings.append(
                CheckFinding(
                    "error",
                    "power.ldo_thermal_budget_missing",
                    f"rail {name} requires max_regulator_dissipation_mw for linear regulator thermal budget",
                    _contract_source(ctx),
                )
            )
        elif dissipation_mw > max_dissipation_mw:
            findings.append(
                CheckFinding(
                    "error",
                    "power.linear_regulator_drop_too_high",
                    (
                        f"rail {name} linear regulator dissipates {dissipation_mw:.1f}mW, "
                        f"above budget {max_dissipation_mw:.1f}mW"
                    ),
                    _contract_source(ctx),
                )
            )
    return findings


@registry.register("power.ldo_thermal_budget_missing", default_severity="error")
def power_ldo_thermal_budget_missing(ctx: CheckContext) -> list[CheckFinding]:
    return []


@registry.register("power.rail_width_policy_missing", default_severity="error")
def power_rail_width_policy_missing(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for name, rail in ctx.source_contract.rails.items():
        if rail.get("min_trace_width_mm") is None:
            findings.append(
                CheckFinding(
                    "error",
                    "power.rail_width_policy_missing",
                    f"rail {name} requires min_trace_width_mm in source contract",
                    _contract_source(ctx),
                )
            )
    return findings


@registry.register("power.cap_voltage_rating_missing", default_severity="error")
def power_cap_voltage_rating_missing(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for ref, component in ctx.source_contract.components.items():
        kind = str(component.get("kind", component.get("type", ""))).lower()
        if kind != "capacitor" and not str(ref).upper().startswith("C"):
            continue
        if component.get("voltage_rating_v") is None:
            findings.append(
                CheckFinding(
                    "error",
                    "power.cap_voltage_rating_missing",
                    f"capacitor {ref} requires voltage_rating_v in source contract",
                    _contract_source(ctx),
                )
            )
    return findings


@registry.register("layout.power_net_uses_finepitch_width", default_severity="error")
def layout_power_net_uses_finepitch_width(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    rail_nets: dict[str, float] = {}
    for rail in ctx.source_contract.rails.values():
        min_width = _float_or_none(rail.get("min_trace_width_mm"))
        if min_width is None:
            continue
        for key in ("input_net", "output_net"):
            net = rail.get(key)
            if net:
                rail_nets[str(net)] = min_width
    if not rail_nets:
        return []
    for route in getattr(ctx.spec, "routes", []) or []:
        raw = getattr(route, "raw", {}) or {}
        net = str(raw.get("net", ""))
        if net not in rail_nets:
            continue
        width = _route_width_mm(ctx, raw)
        if width is not None and width < rail_nets[net]:
            findings.append(
                CheckFinding(
                    "error",
                    "layout.power_net_uses_finepitch_width",
                    (
                        f"power net {net} route {raw.get('name', '<unnamed>')} uses "
                        f"{width:.3f}mm below policy {rail_nets[net]:.3f}mm"
                    ),
                    _spec_source(ctx),
                )
            )
    return findings


@registry.register("layout.layer_roles_no_reference_plane", default_severity="warning")
def layout_layer_roles_no_reference_plane(ctx: CheckContext) -> list[CheckFinding]:
    roles = getattr(ctx.spec, "layer_roles", {}) or {}
    if any(role in {"ground_reference", "power_plane"} for role in roles.values()):
        return []
    return [
        CheckFinding(
            "warning",
            "layout.layer_roles_no_reference_plane",
            "no copper layer is declared as a ground reference or power plane",
            _spec_source(ctx),
        )
    ]


@registry.register("layout.no_ground_plane", default_severity="warning")
def layout_no_ground_plane(ctx: CheckContext) -> list[CheckFinding]:
    planes = getattr(ctx.spec, "planes", []) or []
    if any(str(getattr(plane, "net", "")).upper() == "GND" for plane in planes):
        return []
    return [
        CheckFinding(
            "warning",
            "layout.no_ground_plane",
            "no GND plane intent is declared",
            _spec_source(ctx),
        )
    ]


@registry.register("layout.decoupling_locality_unproven", default_severity="warning")
def layout_decoupling_locality_unproven(ctx: CheckContext) -> list[CheckFinding]:
    validation = ctx.source_contract.validation
    if validation.get("decoupling_locality_reviewed") is True:
        return []
    return [
        CheckFinding(
            "warning",
            "layout.decoupling_locality_unproven",
            "source contract does not record decoupling capacitor locality evidence",
            _contract_source(ctx),
        )
    ]


@registry.register("dfm.absolute_min_trace_clearance_used_globally", default_severity="warning")
def dfm_absolute_min_trace_clearance_used_globally(ctx: CheckContext) -> list[CheckFinding]:
    rules = getattr(ctx.spec, "rules", None)
    if rules is None:
        return []
    default_clearance = getattr(rules, "default_clearance", None)
    netclass_assignments = getattr(ctx.spec, "netclass_assignments", {}) or {}
    globally_assigned = {
        class_name
        for class_name, nets in netclass_assignments.items()
        if "*" in set(nets or [])
    }
    globally_minimum = False
    for class_name in globally_assigned:
        netclass = rules.netclasses.get(class_name)
        if netclass is None:
            continue
        width = getattr(netclass, "width", None)
        clearance = getattr(netclass, "clearance", None)
        if clearance is None:
            clearance = default_clearance
        if width is not None and clearance is not None and width <= 0.10 and clearance <= 0.10:
            globally_minimum = True
            break
    if globally_minimum:
        return [
            CheckFinding(
                "warning",
                "dfm.absolute_min_trace_clearance_used_globally",
                "global routing rules use 0.10mm width and clearance; add margin-specific netclasses",
                _spec_source(ctx),
            )
        ]
    return []


@registry.register("dfm.fabrication_tolerance_margin_missing", default_severity="warning")
def dfm_fabrication_tolerance_margin_missing(ctx: CheckContext) -> list[CheckFinding]:
    if ctx.source_contract.validation.get("fabrication_margin_reviewed") is True:
        return []
    return [
        CheckFinding(
            "warning",
            "dfm.fabrication_tolerance_margin_missing",
            "source contract does not record a fabrication tolerance margin review",
            _contract_source(ctx),
        )
    ]


@registry.register("validation.only_visual_inspection", default_severity="error")
def validation_only_visual_inspection(ctx: CheckContext) -> list[CheckFinding]:
    validation = ctx.source_contract.validation
    tests = list(getattr(ctx.spec, "validation_tests", []) or [])
    kinds = {str(getattr(test, "kind", "")).strip() for test in tests}
    has_non_visual_test = any(kind and kind != "visual_inspection" for kind in kinds)
    if (
        validation.get("erc_like_policy")
        and validation.get("measured_tests")
        and has_non_visual_test
    ):
        return []
    if tests and not has_non_visual_test:
        return [
            CheckFinding(
                "error",
                "validation.only_visual_inspection",
                "validation_tests only contain visual_inspection despite measured validation claims",
                _spec_source(ctx),
            )
        ]
    return [
        CheckFinding(
            "error",
            "validation.only_visual_inspection",
            "source contract requires ERC-like policy and measured validation tests, not only visual inspection",
            _contract_source(ctx),
        )
    ]


@registry.register("validation.no_erc_like_policy", default_severity="error")
def validation_no_erc_like_policy(ctx: CheckContext) -> list[CheckFinding]:
    if ctx.source_contract.validation.get("erc_like_policy"):
        return []
    return [
        CheckFinding(
            "error",
            "validation.no_erc_like_policy",
            "source contract requires erc_like_policy evidence",
            _contract_source(ctx),
        )
    ]


def _contract_source(ctx: CheckContext) -> str:
    return str(ctx.source_contract.path or "")


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_mm_or_none(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.endswith("mm"):
        text = text[:-2].strip()
    return _float_or_none(text)


def _route_width_mm(ctx: CheckContext, raw: dict) -> float | None:
    width = _parse_mm_or_none(raw.get("width"))
    if width is not None:
        return width

    netclass_name = raw.get("netclass")
    if netclass_name:
        width = _netclass_width(ctx, str(netclass_name))
        if width is not None:
            return width

    net = str(raw.get("net", ""))
    for class_name, patterns in (getattr(ctx.spec, "netclass_assignments", {}) or {}).items():
        if not isinstance(patterns, list):
            continue
        if "*" in patterns or net in {str(pattern) for pattern in patterns}:
            width = _netclass_width(ctx, str(class_name))
            if width is not None:
                return width

    rules = getattr(ctx.spec, "rules", None)
    default_width = getattr(rules, "default_width", None)
    if default_width is not None:
        return float(default_width)
    default_clearance = getattr(rules, "default_clearance", None)
    if default_clearance is not None:
        return float(default_clearance)
    return None


def _netclass_width(ctx: CheckContext, name: str) -> float | None:
    rules = getattr(ctx.spec, "rules", None)
    netclasses = getattr(rules, "netclasses", {}) or {}
    class_spec = netclasses.get(name)
    width = getattr(class_spec, "width", None)
    return float(width) if width is not None else None
