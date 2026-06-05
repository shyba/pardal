from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from pardal.project.diagnostics import ProjectConfigError


def load_yaml_file(path: Path, *, code: str, message: str) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ProjectConfigError(
            code,
            f"{message}: {exc}",
            path=path,
            field="yaml",
        ) from exc
