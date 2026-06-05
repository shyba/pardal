from __future__ import annotations

from pardal.production_checks.models import CheckContext, CheckFinding
from pardal.production_checks.registry import registry


@registry.register("gd32.12v_input", default_severity="error")
def gd32_12v_input(ctx: CheckContext) -> list[CheckFinding]:
    input_spec = ctx.source_contract.inputs.get("12V_IN")
    if not input_spec:
        return [
            CheckFinding("error", "gd32.12v_input", "GD32 design requires 12V_IN input contract", _source(ctx))
        ]
    required = set(input_spec.get("required_protection") or [])
    missing = sorted({"reverse_polarity"} - required)
    if missing:
        return [
            CheckFinding(
                "error",
                "gd32.12v_input",
                "12V_IN contract missing protection: " + ", ".join(missing),
                _source(ctx),
            )
        ]
    findings: list[CheckFinding] = []
    parts = getattr(ctx.spec, "parts", {}) or {}
    if "current_limit" in required and not _has_current_limit_part(parts):
        findings.append(
            CheckFinding(
                "error",
                "gd32.12v_input",
                "12V_IN contract requires current_limit but no fuse/PTC/current limiter part is present",
                _source(ctx),
            )
        )
    if "transient" in required and not _has_transient_part(parts):
        findings.append(
            CheckFinding(
                "error",
                "gd32.12v_input",
                "12V_IN contract requires transient protection but no TVS/transient clamp part is present",
                _source(ctx),
            )
        )
    return findings


@registry.register("gd32.adc_frontend", default_severity="error")
def gd32_adc_frontend(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    filters = ctx.source_contract.adc_filters
    for index in range(10):
        name = f"ADC{index}"
        if filters.get(name) is None:
            findings.append(
                CheckFinding("error", "gd32.adc_frontend", f"{name} filter contract is missing", _source(ctx))
            )
    return findings


def _source(ctx: CheckContext) -> str:
    return str(ctx.source_contract.path or "")


def _has_current_limit_part(parts: dict) -> bool:
    for ref, part in parts.items():
        text = f"{ref} {getattr(part, 'footprint', '')}".lower()
        if ref.upper().startswith(("F", "PTC")) or any(token in text for token in ("fuse", "ptc", "polyfuse", "current")):
            return True
    return False


def _has_transient_part(parts: dict) -> bool:
    for ref, part in parts.items():
        text = f"{ref} {getattr(part, 'footprint', '')}".lower()
        if ref.upper().startswith(("TVS", "DTVS")) or any(token in text for token in ("tvs", "transient", "zener")):
            return True
    return False

