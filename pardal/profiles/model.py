from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ProfileDefinition:
    id: str
    package_id: str
    imports: tuple[str, ...] = ()
    enable_checks: frozenset[str] = frozenset()
    disable_checks: frozenset[str] = frozenset()
    severity: dict[str, str] = field(default_factory=dict)
    requires_contract: dict[str, bool] = field(default_factory=dict)
    path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict)
