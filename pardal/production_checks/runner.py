from __future__ import annotations

from collections import OrderedDict
import datetime as _dt
import json
from dataclasses import is_dataclass, replace
from importlib import import_module
from types import MappingProxyType
from typing import Any

from pardal.checks.api import Finding, registered_checks
from pardal.production_checks.models import CheckContext, CheckFinding
from pardal.production_checks.profile_resolution import profile_resolution_for_context
from pardal.production_checks.registry import registry

_STAGE_ORDER = {
    "manifest": 0,
    "source_contract": 1,
    "pre_route": 2,
    "post_route": 3,
    "fabrication": 4,
    "assembly": 5,
}

# Import modules for registration side effects.
for _module in ("analog", "general", "gd32", "jlcpcb", "lcsc"):
    import_module(f"pardal.production_checks.{_module}")


def run_production_checks(
    ctx: CheckContext,
    *,
    enable_checks: list[str] | None = None,
    disable_checks: list[str] | None = None,
    production_profiles: list[str] | None = None,
    disable_check_reasons: dict[str, str] | None = None,
) -> list[CheckFinding]:
    ctx = _with_project_source_contract(ctx)
    resolution = profile_resolution_for_context(
        ctx,
        cli_profiles=production_profiles,
        cli_enable_checks=enable_checks,
        cli_disable_checks=disable_checks,
        cli_disable_check_reasons=disable_check_reasons,
    )
    ctx = replace(ctx, profile_resolution=resolution)
    profiles = list(resolution["legacy_profiles"])
    enabled = registry.general_check_ids()
    enabled.update(resolution["enabled_checks"])
    enabled.difference_update(resolution["disabled_checks"])

    findings: list[CheckFinding] = []
    matched_waivers: set[str] = set()
    package_checks = registered_checks()
    globally_waivable: set[str] = set()
    for check_id in sorted(enabled, key=lambda item: _check_execution_key(item, package_checks)):
        check = registry.get(check_id)
        if check is None:
            package_check = package_checks.get(check_id)
            if package_check is None:
                findings.append(
                    CheckFinding(
                        "error",
                        "production_check.unknown",
                        f"unknown production check requested: {check_id}",
                        str(ctx.source_contract.path or getattr(ctx.spec, "path", "")),
                    )
                )
                continue
            if package_check.globally_waivable:
                globally_waivable.add(check_id)
            if package_check.requires_network and not ctx.allow_network_checks:
                findings.append(
                    CheckFinding(
                        "warning",
                        "production_check.network_disabled",
                        f"network-capable check skipped: {check_id}",
                        str(ctx.source_contract.path or getattr(ctx.spec, "path", "")),
                        stage=str(getattr(package_check.stage, "value", package_check.stage)),
                        package=package_check.package,
                    )
                )
                continue
            raw_findings = _run_package_check(package_check, ctx)
        else:
            if check.globally_waivable:
                globally_waivable.add(check_id)
            raw_findings = check.func(ctx)
        raw_findings = _apply_package_profile_severity(
            raw_findings,
            resolution["severity"],
        )
        raw_findings = _apply_profile_severity(raw_findings, profiles, ctx)
        findings.extend(_apply_waivers(raw_findings, ctx, matched_waivers, globally_waivable))
    findings.extend(_waiver_diagnostics(ctx, matched_waivers))
    return _dedupe(findings)


def _check_execution_key(check_id: str, package_checks: dict[str, Any]) -> tuple[int, str]:
    check = registry.get(check_id)
    stage = getattr(check, "stage", "") if check is not None else ""
    if not stage:
        package_check = package_checks.get(check_id)
        stage = getattr(package_check, "stage", "") if package_check is not None else ""
    stage_value = str(getattr(stage, "value", stage) or "")
    return (_STAGE_ORDER.get(stage_value, len(_STAGE_ORDER)), check_id)


def _with_project_source_contract(ctx: CheckContext) -> CheckContext:
    project_context = getattr(ctx, "project_context", None)
    project_contract = getattr(project_context, "source_contract", None)
    if project_contract is None or not _source_contract_empty(ctx.source_contract):
        return ctx
    return replace(ctx, source_contract=project_contract)


def _source_contract_empty(source_contract) -> bool:
    return (
        source_contract.path is None
        and not source_contract.profiles
        and not source_contract.enable_checks
        and not source_contract.disable_checks
        and not source_contract.waive_checks
        and not source_contract.rails
        and not source_contract.inputs
        and not source_contract.adc_filters
        and not source_contract.validation
        and not source_contract.components
        and not source_contract.part_aliases
    )


def _run_package_check(definition, ctx: CheckContext) -> list[CheckFinding]:
    converted: list[CheckFinding] = []
    try:
        result = definition.func(_readonly_check_context(ctx))
    except Exception as exc:  # noqa: BLE001 - package check failures become findings.
        return [
            _package_check_runtime_error(
                definition,
                "package.check_failed",
                "package check failed during execution",
                {"check_id": definition.id, "exception": type(exc).__name__},
            )
        ]
    if isinstance(result, Finding) or isinstance(result, (str, bytes, dict)) or result is None:
        return [
            _package_check_runtime_error(
                definition,
                "package.check_invalid_result",
                "package check must return an iterable of Finding objects",
                {"check_id": definition.id, "type": type(result).__name__},
            )
        ]
    try:
        iterator = iter(result)
    except TypeError:
        return [
            _package_check_runtime_error(
                definition,
                "package.check_invalid_result",
                "package check must return an iterable of Finding objects",
                {"check_id": definition.id, "type": type(result).__name__},
            )
        ]
    for index, finding in enumerate(iterator):
        if not isinstance(finding, Finding):
            converted.append(
                _package_check_runtime_error(
                    definition,
                    "package.check_invalid_finding",
                    "package check returned a non-Finding object",
                    {
                        "check_id": definition.id,
                        "index": index,
                        "type": type(finding).__name__,
                    },
                )
            )
            continue
        if finding.id != definition.id:
            converted.append(
                _package_check_runtime_error(
                    definition,
                    "package.check_wrong_finding_id",
                    "package check returned a finding for a different check ID",
                    {
                        "check_id": definition.id,
                        "finding_id": finding.id,
                        "index": index,
                    },
                )
            )
            continue
        converted.append(_convert_package_finding(finding, definition))
    return converted


def _package_check_runtime_error(
    definition,
    code: str,
    message: str,
    evidence: dict[str, Any],
) -> CheckFinding:
    return CheckFinding(
        "error",
        code,
        message,
        "",
        stage=str(getattr(definition.stage, "value", definition.stage) or ""),
        package=definition.package,
        evidence=evidence,
    )


def _readonly_check_context(ctx: CheckContext) -> CheckContext:
    return replace(
        ctx,
        source_contract=_readonly_source_contract(ctx.source_contract),
        generated_artifacts=frozenset(ctx.generated_artifacts),
        artifact_paths=_readonly(ctx.artifact_paths),
        build_summary=_readonly(ctx.build_summary),
        profile_resolution=_readonly(ctx.profile_resolution),
        project_context=_readonly(ctx.project_context),
    )


def _readonly_source_contract(source_contract):
    return replace(
        source_contract,
        profiles=_readonly(source_contract.profiles),
        enable_checks=tuple(source_contract.enable_checks),
        disable_checks=tuple(source_contract.disable_checks),
        waive_checks=_readonly(source_contract.waive_checks),
        rails=_readonly(source_contract.rails),
        inputs=_readonly(source_contract.inputs),
        adc_filters=_readonly(source_contract.adc_filters),
        validation=_readonly(source_contract.validation),
        components=_readonly(source_contract.components),
        part_aliases=_readonly(source_contract.part_aliases),
    )


def _readonly(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _readonly(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_readonly(item) for item in value)
    if isinstance(value, set):
        return frozenset(_readonly(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_readonly(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        replacements = {
            field_name: _readonly(getattr(value, field_name))
            for field_name in getattr(value, "__dataclass_fields__", {})
        }
        return replace(value, **replacements)
    return value


def _convert_package_finding(finding: Finding, definition=None) -> CheckFinding:
    return CheckFinding(
        getattr(finding.severity, "value", finding.severity),
        finding.id,
        finding.message,
        _format_package_source(finding.source),
        stage=str(getattr(finding.stage, "value", finding.stage) or ""),
        package=getattr(definition, "package", "") if definition is not None else "",
        evidence=dict(finding.evidence),
        source_details=dict(finding.source),
    )


def _format_package_source(source: dict) -> str:
    path = source.get("path")
    field = source.get("field")
    if path and field:
        return f"{path}:{field}"
    if path:
        return str(path)
    if field:
        return str(field)
    return ""


def _apply_package_profile_severity(
    findings: list[CheckFinding],
    severity: dict[str, str],
) -> list[CheckFinding]:
    if not severity:
        return findings
    adjusted: list[CheckFinding] = []
    for finding in findings:
        override = severity.get(finding.code)
        if override is None or override == finding.severity:
            adjusted.append(finding)
            continue
        adjusted.append(
            replace(finding, severity=override)
        )
    return adjusted


def _apply_profile_severity(
    findings: list[CheckFinding],
    profiles: list[str],
    ctx: CheckContext,
) -> list[CheckFinding]:
    if getattr(ctx, "project_context", None) is not None:
        return findings
    if "jlcpcb_full_pcba" not in profiles:
        return findings
    adjusted: list[CheckFinding] = []
    for finding in findings:
        if finding.code == "assembly.manual_part_present" and finding.severity == "warning":
            adjusted.append(
                replace(finding, severity="error")
            )
        else:
            adjusted.append(finding)
    return adjusted


def _apply_waivers(
    findings: list[CheckFinding],
    ctx: CheckContext,
    matched_waivers: set[str],
    globally_waivable: set[str],
) -> list[CheckFinding]:
    waived: list[CheckFinding] = []
    expired = _expired_waivers(ctx)
    for finding in findings:
        waiver = ctx.source_contract.waive_checks.get(finding.code)
        if not waiver:
            waived.append(finding)
            continue
        if finding.code in expired:
            waived.append(finding)
            continue
        reason = str(waiver.get("reason") or "").strip()
        if not _waiver_matches_finding(waiver, finding, globally_waivable):
            waived.append(finding)
            continue
        matched_waivers.add(finding.code)
        suffix = f" waived: {reason}" if reason else " waived"
        waived.append(
            replace(
                finding,
                severity="warning",
                code=f"{finding.code}.waived",
                message=finding.message + suffix,
                waived=True,
                waiver_reason=reason,
            )
        )
    return waived


def _waiver_matches_finding(
    waiver: dict[str, Any],
    finding: CheckFinding,
    globally_waivable: set[str],
) -> bool:
    stage = str(waiver.get("stage") or "").strip()
    if stage and stage != finding.stage:
        return False
    match = waiver.get("match")
    if match is not None:
        if not isinstance(match, dict):
            return False
        return _evidence_matches(match, finding.evidence)
    refs = [str(ref) for ref in waiver.get("refs") or []]
    if refs:
        return any(ref in finding.message for ref in refs)
    return finding.code in globally_waivable


def _evidence_matches(match: dict[str, Any], evidence: dict[str, Any]) -> bool:
    for value in evidence.values():
        if isinstance(value, list) and any(
            isinstance(item, dict) and _evidence_matches(match, item)
            for item in value
        ):
            return True
    for key, expected in match.items():
        if evidence.get(key) != expected:
            return False
    return True


def _waiver_diagnostics(
    ctx: CheckContext,
    matched_waivers: set[str],
) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    expired = _expired_waivers(ctx)
    for check_id in sorted(ctx.source_contract.waive_checks):
        if check_id in expired:
            findings.append(
                CheckFinding(
                    "error",
                    "waiver.expired",
                    f"waiver for {check_id} is expired",
                    str(ctx.source_contract.path or getattr(ctx.spec, "path", "")),
                )
            )
            continue
        if check_id not in matched_waivers:
            findings.append(
                CheckFinding(
                    "warning",
                    "waiver.unused",
                    f"waiver for {check_id} matched no finding",
                    str(ctx.source_contract.path or getattr(ctx.spec, "path", "")),
                )
            )
    return findings


def _expired_waivers(ctx: CheckContext) -> set[str]:
    today = _dt.date.today()
    expired: set[str] = set()
    for check_id, waiver in ctx.source_contract.waive_checks.items():
        expires = waiver.get("expires")
        if expires is None:
            continue
        if _dt.date.fromisoformat(str(expires)) < today:
            expired.add(check_id)
    return expired


def _dedupe(findings: list[CheckFinding]) -> list[CheckFinding]:
    seen: OrderedDict[tuple[str, str, str, str, str, str, str, str], CheckFinding] = OrderedDict()
    for finding in findings:
        seen[_finding_identity_key(finding)] = finding
    return sorted(seen.values(), key=_finding_sort_key)


def _finding_identity_key(finding: CheckFinding) -> tuple[str, str, str, str, str, str, str, str]:
    return (
        finding.severity,
        finding.code,
        finding.message,
        finding.source,
        finding.stage,
        finding.package,
        _stable_json(finding.evidence),
        _stable_json(finding.source_details),
    )


def _finding_sort_key(finding: CheckFinding) -> tuple[int, str, str, str, str, str]:
    return (
        _STAGE_ORDER.get(finding.stage, len(_STAGE_ORDER)),
        finding.code,
        finding.severity,
        finding.source,
        _stable_json(finding.evidence),
        finding.message,
    )


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)
