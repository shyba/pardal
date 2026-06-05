from __future__ import annotations

import csv

from pardal.production_checks.models import CheckContext, CheckFinding
from pardal.production_checks.registry import registry


@registry.register("jlcpcb.smt_required_artifacts", default_severity="error")
def jlcpcb_smt_required_artifacts(ctx: CheckContext) -> list[CheckFinding]:
    missing = [
        label
        for label, key in (("JLC BOM", "jlc_bom"), ("JLC PNP", "jlc_pnp"))
        if not _artifact_exists(ctx, key)
    ]
    if not missing:
        return []
    return [
        CheckFinding(
            "error",
            "jlcpcb.smt_required_artifacts",
            "JLCPCB SMT profile requires generated " + ", ".join(missing),
            str(getattr(ctx.spec, "path", "")),
        )
    ]


@registry.register("assembly.manual_part_present", default_severity="warning")
def assembly_manual_part_present(ctx: CheckContext) -> list[CheckFinding]:
    board = ctx.board
    if board is None:
        return []
    findings: list[CheckFinding] = []
    for ref, comp in sorted(board.components.items()):
        footprint = str(getattr(comp, "footprint", ""))
        if "TerminalBlock" not in footprint:
            continue
        findings.append(
            CheckFinding(
                "warning",
                "assembly.manual_part_present",
                f"component {ref} uses manual/through-hole style footprint {footprint}",
                str(getattr(ctx.spec, "path", "")),
            )
        )
    return findings


@registry.register("assembly.manual_part_exported_to_jlc", default_severity="error")
def assembly_manual_part_exported_to_jlc(ctx: CheckContext) -> list[CheckFinding]:
    manual_refs = _manual_refs(ctx)
    if not manual_refs:
        return []
    exported = {
        "JLC BOM": _csv_designators(ctx.artifact_paths.get("jlc_bom")),
        "JLC PNP": _csv_designators(ctx.artifact_paths.get("jlc_pnp")),
    }
    findings: list[CheckFinding] = []
    for label, refs in exported.items():
        leaked = sorted(manual_refs.intersection(refs))
        if leaked:
            findings.append(
                CheckFinding(
                    "error",
                    "assembly.manual_part_exported_to_jlc",
                    f"manual assembly refs exported to {label}: {', '.join(leaked)}",
                    str(ctx.artifact_paths.get("jlc_bom") or ctx.artifact_paths.get("jlc_pnp") or ""),
                )
            )
    return findings


def _artifact_exists(ctx: CheckContext, key: str) -> bool:
    path = ctx.artifact_paths.get(key)
    if path is None:
        return False
    if path.resolve() in ctx.generated_artifacts:
        return True
    if not path.exists():
        return False
    if path.is_dir():
        return any(child.is_file() for child in path.rglob("*"))
    return path.stat().st_size > 0


def _manual_refs(ctx: CheckContext) -> set[str]:
    manual: set[str] = set()
    dfm = getattr(ctx.spec, "dfm", None)
    for ref, method in (getattr(dfm, "assembly_methods", {}) or {}).items():
        if "manual" in str(method).lower() or "tht" in str(method).lower():
            manual.add(str(ref))
    board = ctx.board
    if board is not None:
        for ref, comp in sorted(board.components.items()):
            footprint = str(getattr(comp, "footprint", ""))
            if "TerminalBlock" in footprint:
                manual.add(str(ref))
    return manual


def _csv_designators(path) -> set[str]:
    if path is None or not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        refs: set[str] = set()
        for row in reader:
            designator = row.get("Designator") or ""
            for ref in designator.replace(";", ",").split(","):
                ref = ref.strip()
                if ref:
                    refs.add(ref)
        return refs
