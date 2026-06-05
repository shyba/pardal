"""KiCad CLI execution via Docker (optional).

This is primarily meant for environments where:
- `kicad-cli` is missing, or too old (e.g. KiCad 7 lacks `pcb drc` / `pcb render`)
- the `pcbnew` Python module is not available in the current virtualenv

Nothing in `pardal` requires Docker by default; callers must opt in.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


DEFAULT_IMAGE = "kicad/kicad:9.0.6-full"


@dataclass(frozen=True)
class DockerKicad:
    image: str = DEFAULT_IMAGE


def build_kicad_cli_docker_cmd(
    *,
    image: str,
    workdir_host: Path,
    args: list[str],
) -> list[str]:
    """Build a `docker run ... kicad-cli ...` command.

    `workdir_host` is mounted read-write to `/work` in the container.
    """
    workdir_host = Path(workdir_host).resolve()

    return [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{workdir_host}:/work",
        "-w",
        "/work",
        image,
        "kicad-cli",
        *args,
    ]


def run_kicad_cli_in_docker(
    *,
    image: str = DEFAULT_IMAGE,
    workdir_host: Path,
    args: list[str],
    timeout_s: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `kicad-cli` within a KiCad docker image."""
    cmd = build_kicad_cli_docker_cmd(image=image, workdir_host=workdir_host, args=args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)

