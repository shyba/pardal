from __future__ import annotations

from pathlib import Path

from pardal.packages.lock import is_ignored_package_generated_path
from pardal.project.diagnostics import ProjectConfigError


def check_package_source_members(root: Path, *, code: str = "package.source_unsafe") -> None:
    for path in sorted(root.rglob("*")):
        if is_ignored_package_generated_path(path, root):
            continue
        if path.is_symlink():
            raise ProjectConfigError(
                code,
                "package source must not contain symlinks",
                path=path,
            )
        if path.is_file():
            if path.stat().st_nlink > 1:
                raise ProjectConfigError(
                    code,
                    "package source must not contain hardlinks",
                    path=path,
                )
            continue
        if path.is_dir():
            continue
        raise ProjectConfigError(
            code,
            "package source must contain only files and directories",
            path=path,
        )
