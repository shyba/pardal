from __future__ import annotations

from pathlib import Path

from pardal.packages.lock import LockFile, load_lock_file
from pardal.project.diagnostics import ProjectConfigError


def load_project_lock_file(path: Path) -> LockFile:
    try:
        return load_lock_file(path)
    except ValueError as exc:
        raise ProjectConfigError(
            "project.lock_invalid",
            str(exc),
            path=path,
            field="pardal.lock",
        ) from exc
