from __future__ import annotations

import math
import re

from pardal.production_checks.models import CheckContext, CheckFinding
from pardal.production_checks.registry import registry


@registry.register("analog.rc_filter_contract_complete", default_severity="error")
def analog_rc_filter_contract_complete(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for name, raw in _rc_filters(ctx).items():
        for key in ("input_net", "filtered_net", "resistor_ref", "capacitor_ref", "max_bandwidth_hz"):
            if raw.get(key) in (None, ""):
                findings.append(
                    CheckFinding(
                        "error",
                        "analog.rc_filter_contract_complete",
                        f"{name} RC filter contract requires {key}",
                        _source(ctx),
                    )
                )
    return findings


@registry.register("analog.rc_filter_values_resolve", default_severity="error")
def analog_rc_filter_values_resolve(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for name, raw in _rc_filters(ctx).items():
        resistor_ref = str(raw.get("resistor_ref") or "")
        capacitor_ref = str(raw.get("capacitor_ref") or "")
        resistor = _component_value(ctx, resistor_ref)
        capacitor = _component_value(ctx, capacitor_ref)
        if _parse_resistance_ohm(resistor) is None:
            findings.append(
                CheckFinding(
                    "error",
                    "analog.rc_filter_values_resolve",
                    f"{name} resistor {resistor_ref or '<missing>'} value is missing or unparsable",
                    _source(ctx),
                )
            )
        if _parse_capacitance_farad(capacitor) is None:
            findings.append(
                CheckFinding(
                    "error",
                    "analog.rc_filter_values_resolve",
                    f"{name} capacitor {capacitor_ref or '<missing>'} value is missing or unparsable",
                    _source(ctx),
                )
            )
    return findings


@registry.register("analog.rc_filter_cutoff_within_limit", default_severity="error")
def analog_rc_filter_cutoff_within_limit(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    for name, raw in _rc_filters(ctx).items():
        bandwidth = _float_or_none(raw.get("max_bandwidth_hz"))
        resistor = _component_value(ctx, str(raw.get("resistor_ref") or ""))
        capacitor = _component_value(ctx, str(raw.get("capacitor_ref") or ""))
        resistance = _parse_resistance_ohm(resistor)
        capacitance = _parse_capacitance_farad(capacitor)
        if bandwidth is None or resistance is None or capacitance is None:
            continue
        cutoff = 1.0 / (2.0 * math.pi * resistance * capacitance)
        if cutoff > bandwidth:
            findings.append(
                CheckFinding(
                    "error",
                    "analog.rc_filter_cutoff_within_limit",
                    (
                        f"{name} RC cutoff {cutoff:.1f}Hz exceeds contract "
                        f"{bandwidth:.1f}Hz using {raw.get('resistor_ref')}={resistor} "
                        f"and {raw.get('capacitor_ref')}={capacitor}"
                    ),
                    _source(ctx),
                )
            )
    return findings


def rc_filter_findings(ctx: CheckContext) -> list[CheckFinding]:
    """Compatibility helper for device profiles that previously owned RC checks."""
    return (
        analog_rc_filter_contract_complete(ctx)
        + analog_rc_filter_values_resolve(ctx)
        + analog_rc_filter_cutoff_within_limit(ctx)
    )


def _rc_filters(ctx: CheckContext) -> dict[str, dict]:
    return ctx.source_contract.adc_filters


def _source(ctx: CheckContext) -> str:
    return str(ctx.source_contract.path or "")


def _component_value(ctx: CheckContext, ref: str) -> str | None:
    board = ctx.board
    if board is not None and ref in getattr(board, "components", {}):
        value = getattr(board.components[ref], "value", None)
        if value:
            return str(value)
    part = (getattr(ctx.spec, "parts", {}) or {}).get(ref)
    value = getattr(part, "value", None)
    return str(value) if value else None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_resistance_ohm(value: str | None) -> float | None:
    return _parse_metric_value(value, {"r": 1.0, "": 1.0, "k": 1e3, "m": 1e6})


def _parse_capacitance_farad(value: str | None) -> float | None:
    return _parse_metric_value(
        value,
        {"f": 1.0, "uf": 1e-6, "µf": 1e-6, "nf": 1e-9, "pf": 1e-12},
    )


def _parse_metric_value(value: str | None, suffixes: dict[str, float]) -> float | None:
    if not value:
        return None
    text = value.strip().lower().replace("ω", "").replace("ohm", "")
    text = text.replace(" ", "")
    match = re.fullmatch(r"(?P<num>\d+(?:\.\d+)?)(?P<suffix>[a-zµ]*)", text)
    if not match:
        return None
    suffix = match.group("suffix")
    if suffix not in suffixes:
        return None
    return float(match.group("num")) * suffixes[suffix]
