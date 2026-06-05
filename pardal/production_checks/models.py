from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


CheckSeverity = str
CheckStage = str
CheckFunction = Callable[["CheckContext"], list["CheckFinding"]]


@dataclass(frozen=True)
class CheckFinding:
    severity: CheckSeverity
    code: str
    message: str
    source: str = ""
    stage: str = ""
    package: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    source_details: dict[str, Any] = field(default_factory=dict)
    waived: bool = False
    waiver_reason: str = ""


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    findings: tuple[CheckFinding, ...] = ()


@dataclass(frozen=True)
class Waiver:
    id: str
    reason: str
    stage: str = ""
    match: dict[str, Any] = field(default_factory=dict)
    refs: tuple[str, ...] = ()
    owner: str = ""
    expires: str = ""


@dataclass(frozen=True)
class SourceContract:
    path: Path | None = None
    profiles: dict[str, str] = field(default_factory=dict)
    enable_checks: tuple[str, ...] = ()
    disable_checks: tuple[str, ...] = ()
    waive_checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    waivers: tuple[Waiver, ...] = ()
    rails: dict[str, dict[str, Any]] = field(default_factory=dict)
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    adc_filters: dict[str, dict[str, Any]] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    components: dict[str, dict[str, Any]] = field(default_factory=dict)
    part_aliases: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckContext:
    spec: Any
    board: Any | None = None
    source_contract: SourceContract = field(default_factory=SourceContract)
    artifact_root: Path | None = None
    generated_artifacts: frozenset[Path] = frozenset()
    artifact_paths: dict[str, Path | None] = field(default_factory=dict)
    build_summary: dict[str, Any] | None = None
    manufacturing_archive: Path | None = None
    production_profiles: tuple[str, ...] = ()
    project_context: Any | None = None
    profile_resolution: dict[str, Any] = field(default_factory=dict)
    allow_network_checks: bool = False


@dataclass(frozen=True)
class RegisteredCheck:
    check_id: str
    default_severity: CheckSeverity
    func: CheckFunction
    stage: CheckStage = ""
    general: bool = False
    globally_waivable: bool = False
