from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectDiagnostic:
    code: str
    message: str
    path: Path | None = None
    field: str = ""


class ProjectConfigError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        path: Path | None = None,
        field: str = "",
    ) -> None:
        self.diagnostic = ProjectDiagnostic(code, message, path, field)
        location = f"{path}" if path is not None else "<project>"
        suffix = f":{field}" if field else ""
        super().__init__(f"{code}: {location}{suffix}: {message}")
