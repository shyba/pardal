from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Callable, Iterable


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Stage(str, Enum):
    MANIFEST = "manifest"
    SOURCE_CONTRACT = "source_contract"
    PRE_ROUTE = "pre_route"
    POST_ROUTE = "post_route"
    FABRICATION = "fabrication"
    ASSEMBLY = "assembly"


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    severity: Severity
    message: str
    stage: Stage
    evidence: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id
            or self.id.strip() != self.id
            or CHECK_ID_RE.fullmatch(self.id) is None
        ):
            raise ValueError("finding id must be a non-empty stable identifier")
        if not isinstance(self.severity, Severity):
            raise ValueError("finding severity must be a Severity")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("finding message must be a non-empty string")
        if not isinstance(self.stage, Stage):
            raise ValueError("finding stage must be a Stage")
        if not isinstance(self.evidence, dict):
            raise ValueError("finding evidence must be a dictionary")
        if not isinstance(self.source, dict):
            raise ValueError("finding source must be a dictionary")


CheckFunction = Callable[[Any], Iterable[Finding]]


@dataclass(frozen=True, slots=True)
class CheckDefinition:
    id: str
    stage: Stage
    default_severity: Severity
    func: CheckFunction
    requires_network: bool = False
    globally_waivable: bool = False
    package: str = ""


_REGISTERED: dict[str, CheckDefinition] = {}
CHECK_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]*$")


class DuplicateCheckIdError(ValueError):
    def __init__(self, check_id: str) -> None:
        self.check_id = check_id
        super().__init__(f"duplicate check id {check_id!r}")


def check(
    *,
    id: str,
    stage: Stage,
    default_severity: Severity,
    requires_network: bool = False,
    globally_waivable: bool = False,
) -> Callable[[CheckFunction], CheckFunction]:
    _validate_check_definition(
        id=id,
        stage=stage,
        default_severity=default_severity,
        requires_network=requires_network,
        globally_waivable=globally_waivable,
    )

    def decorator(func: CheckFunction) -> CheckFunction:
        if id in _REGISTERED:
            raise DuplicateCheckIdError(id)
        _REGISTERED[id] = CheckDefinition(
            id=id,
            stage=stage,
            default_severity=default_severity,
            func=func,
            requires_network=requires_network,
            globally_waivable=globally_waivable,
        )
        return func

    return decorator


def _validate_check_definition(
    *,
    id: str,
    stage: Stage,
    default_severity: Severity,
    requires_network: bool,
    globally_waivable: bool,
) -> None:
    if not isinstance(id, str) or not id or id.strip() != id or CHECK_ID_RE.fullmatch(id) is None:
        raise ValueError("check id must be a non-empty stable identifier")
    if not isinstance(stage, Stage):
        raise ValueError("check stage must be a Stage")
    if not isinstance(default_severity, Severity):
        raise ValueError("check default_severity must be a Severity")
    if not isinstance(requires_network, bool):
        raise ValueError("check requires_network must be a boolean")
    if not isinstance(globally_waivable, bool):
        raise ValueError("check globally_waivable must be a boolean")


def registered_checks() -> dict[str, CheckDefinition]:
    return dict(_REGISTERED)


def set_check_package(check_id: str, package: str) -> None:
    definition = _REGISTERED.get(check_id)
    if definition is None:
        return
    _REGISTERED[check_id] = CheckDefinition(
        id=definition.id,
        stage=definition.stage,
        default_severity=definition.default_severity,
        func=definition.func,
        requires_network=definition.requires_network,
        globally_waivable=definition.globally_waivable,
        package=package,
    )
