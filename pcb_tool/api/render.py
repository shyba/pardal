from __future__ import annotations

from pathlib import Path

from pcb_tool.kicad_render import Render3dOptions, render_3d_docker


def render_3d(
    pcb_path: str | Path,
    output_image: str | Path,
    *,
    use_docker: bool = True,
    options: Render3dOptions | None = None,
) -> Path:
    """Render a 3D image of a PCB.

    Currently only docker-backed KiCad 9 rendering is supported.
    """
    if not use_docker:
        raise NotImplementedError("Non-docker render is not implemented (requires KiCad 9 kicad-cli).")
    return render_3d_docker(pcb_path, output_image, options=options)

