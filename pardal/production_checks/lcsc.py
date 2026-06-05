from __future__ import annotations

from pardal.production_checks.models import CheckContext, CheckFinding
from pardal.production_checks.registry import registry


@registry.register("lcsc.parts_require_mapping_or_exception", default_severity="error")
def lcsc_parts_require_mapping_or_exception(ctx: CheckContext) -> list[CheckFinding]:
    source_findings = _source_contract_lcsc_mapping_findings(ctx)
    if source_findings is not None:
        return source_findings
    spec = ctx.spec
    board = ctx.board
    dfm = getattr(spec, "dfm", None)
    if board is None or dfm is None:
        return []
    lcsc_parts = getattr(dfm, "lcsc_parts", {}) or {}
    lcsc_exceptions = getattr(dfm, "lcsc_exceptions", {}) or {}
    findings: list[CheckFinding] = []
    for ref, comp in sorted(board.components.items()):
        if ref.startswith(("TP", "FID", "MH")):
            continue
        if ref in lcsc_parts or ref in lcsc_exceptions:
            continue
        findings.append(
            CheckFinding(
                "error",
                "lcsc.parts_require_mapping_or_exception",
                f"component {ref} ({comp.footprint}) requires LCSC mapping or exception",
                str(getattr(spec, "path", "")),
            )
        )
    return findings


def _source_contract_lcsc_mapping_findings(ctx: CheckContext) -> list[CheckFinding] | None:
    components = ctx.source_contract.components
    if not components:
        return None
    project_context = getattr(ctx, "project_context", None)
    parts = getattr(project_context, "parts", {}) if project_context is not None else {}
    findings: list[CheckFinding] = []
    for ref, component in sorted(components.items()):
        if ref.startswith(("TP", "FID", "MH")):
            continue
        if component.get("lcsc") or component.get("lcsc_exception"):
            continue
        part_id = component.get("part_id")
        if part_id:
            part = parts.get(str(part_id))
            if part is not None and part.lcsc:
                continue
        findings.append(
            CheckFinding(
                "error",
                "lcsc.parts_require_mapping_or_exception",
                f"component {ref} requires LCSC mapping, package part with LCSC code, or exception",
                str(ctx.source_contract.path or getattr(ctx.spec, "path", "")),
            )
        )
    return findings


@registry.register("bom.lcsc_missing", default_severity="error")
def bom_lcsc_missing(ctx: CheckContext) -> list[CheckFinding]:
    return lcsc_parts_require_mapping_or_exception(ctx)


@registry.register("bom.lcsc_live_availability_stale", default_severity="warning")
def bom_lcsc_live_availability_stale(ctx: CheckContext) -> list[CheckFinding]:
    validation = ctx.source_contract.validation
    if validation.get("lcsc_availability_checked"):
        return []
    return [
        CheckFinding(
            "warning",
            "bom.lcsc_live_availability_stale",
            "source contract does not record live LCSC availability evidence",
            str(ctx.source_contract.path or getattr(ctx.spec, "path", "")),
        )
    ]
