from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pardal.data_model import Board, NetClass


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def load_net_classes_from_project(project_path: Path) -> dict[str, NetClass]:
    """Load KiCad net classes from a `.kicad_pro` (KiCad 6+ JSON project)."""
    data = _read_json(project_path)
    net_settings = data.get("net_settings", {})
    classes = net_settings.get("classes", []) or []
    out: dict[str, NetClass] = {}
    for c in classes:
        try:
            name = str(c.get("name", "Default"))
            out[name] = NetClass(
                name=name,
                track_width=float(c.get("track_width", 0.25)),
                clearance=float(c.get("clearance", 0.2)),
                via_size=float(c.get("via_diameter", 0.8)),
                via_drill=float(c.get("via_drill", 0.4)),
            )
        except Exception:
            continue
    return out


def apply_project_net_settings(board: Board, pcb_path: Path) -> list[str]:
    """Apply net class defaults from the sibling `.kicad_pro` (if present)."""
    warnings: list[str] = []
    project_path = pcb_path.with_suffix(".kicad_pro")
    if not project_path.exists():
        return warnings

    try:
        net_classes = load_net_classes_from_project(project_path)
    except Exception as e:
        warnings.append(f"Failed to load project net settings: {e}")
        return warnings

    for nc in net_classes.values():
        board.add_net_class(nc)

    # KiCad supports netclass assignments/patterns, but the fpga_large fixtures use
    # the Default class for every net. If no assignments exist, apply Default.
    default = board.net_classes.get("Default")
    if default is None:
        return warnings

    for net in board.nets.values():
        if not net.net_class:
            net.net_class = "Default"
        if net.net_class == "Default":
            net.track_width = default.track_width
            net.via_size = default.via_size
            net.via_drill = default.via_drill

    return warnings

