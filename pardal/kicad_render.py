"""KiCad 9 3D rendering helpers (docker-backed).

KiCad's `kicad-cli pcb render` exists in KiCad 9 and can produce a 3D render
image (PNG/JPEG) without a GUI.

This module provides an optional docker-backed wrapper so callers can render
even when the host system KiCad is older (e.g. KiCad 7).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pardal.kicad_docker import DEFAULT_IMAGE, run_kicad_cli_in_docker


@dataclass(frozen=True)
class Render3dOptions:
    side: str = "top"  # top|bottom|left|right|front|back
    width: int = 1600
    height: int = 900
    quality: str = "basic"  # basic|high|user|job_settings
    preset: str = "follow_plot_settings"
    background: str | None = None  # default|transparent|opaque
    perspective: bool = False
    floor: bool = False
    rotate: str | None = None  # "X,Y,Z" degrees
    zoom: float | None = None
    pan: str | None = None  # "X,Y,Z" cm
    pivot: str | None = None  # "X,Y,Z" cm


def render_3d_docker(
    pcb_path: str | Path,
    output_image: str | Path,
    *,
    options: Render3dOptions | None = None,
    image: str | None = None,
    timeout_s: float | None = 300.0,
) -> Path:
    """Render a `.kicad_pcb` to an image using KiCad 9 in docker."""
    opts = options or Render3dOptions()
    image = image or os.environ.get("PARDAL_KICAD_DOCKER_IMAGE") or DEFAULT_IMAGE

    pcb_path = Path(pcb_path)
    output_image = Path(output_image)

    if not pcb_path.exists():
        raise FileNotFoundError(pcb_path)

    output_image.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="pardal-kicad-render-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        board_name = "board.kicad_pcb"
        out_name = "render.png" if output_image.suffix.lower() not in {".png", ".jpg", ".jpeg"} else f"render{output_image.suffix.lower()}"

        (tmpdir_path / board_name).write_bytes(pcb_path.read_bytes())

        args: list[str] = [
            "pcb",
            "render",
            "--output",
            out_name,
            "--side",
            str(opts.side),
            "--width",
            str(int(opts.width)),
            "--height",
            str(int(opts.height)),
            "--quality",
            str(opts.quality),
            "--preset",
            str(opts.preset),
        ]
        if opts.background:
            args.extend(["--background", str(opts.background)])
        if opts.floor:
            args.append("--floor")
        if opts.perspective:
            args.append("--perspective")
        if opts.rotate:
            args.extend(["--rotate", str(opts.rotate)])
        if opts.zoom is not None:
            args.extend(["--zoom", str(opts.zoom)])
        if opts.pan:
            args.extend(["--pan", str(opts.pan)])
        if opts.pivot:
            args.extend(["--pivot", str(opts.pivot)])

        args.append(board_name)

        result = run_kicad_cli_in_docker(
            image=image,
            workdir_host=tmpdir_path,
            args=args,
            timeout_s=timeout_s,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "kicad-cli pcb render failed").strip())

        out_src = tmpdir_path / out_name
        if not out_src.exists() or out_src.stat().st_size == 0:
            raise RuntimeError("kicad-cli pcb render produced no output image")

        output_image.write_bytes(out_src.read_bytes())

    return output_image

