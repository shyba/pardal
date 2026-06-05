import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_precommit_via_blocks_other_net_track(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo via precommit test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "routing" / "mojo_router"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # Net A is a pure via-in-place (F.Cu->B.Cu) at the center.
    # Net B must cross that center point on F.Cu (no other route in corridor).
    # With precommit shorts enabled, B should be rejected due to via/track intersection.
    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu", "B.Cu"],
                "resolution_mm": 1.0,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": 7,
                "height": 7,
                "net_defaults": {
                    "track_width_mm": 1.0,
                    "clearance_mm": 0.0,
                    "via_diameter_mm": 1.0,
                    "via_drill_mm": 0.4,
                    "uvia_diameter_mm": 1.0,
                    "uvia_drill_mm": 0.4,
                },
                "nets": [
                    {
                        "net": "A",
                        "net_id": 1,
                        "start": {"layer": 0, "x": 3, "y": 3},
                        "goal": {"layer": 1, "x": 3, "y": 3},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 1.0,
                        "via_drill_mm": 0.4,
                        "uvia_diameter_mm": 1.0,
                        "uvia_drill_mm": 0.4,
                    },
                    {
                        "net": "B",
                        "net_id": 2,
                        "start": {"layer": 0, "x": 0, "y": 3},
                        "goal": {"layer": 0, "x": 6, "y": 3},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 1.0,
                        "via_drill_mm": 0.4,
                        "uvia_diameter_mm": 1.0,
                        "uvia_drill_mm": 0.4,
                    },
                ],
                "circles": [],
                "polygons": [
                    # Block all cells except the central row, ensuring B must pass through (3,3).
                    {"net_id": 0, "layers": [0, 1], "points": [{"x": 0, "y": 0}, {"x": 6, "y": 0}, {"x": 6, "y": 2}, {"x": 0, "y": 2}]},
                    {"net_id": 0, "layers": [0, 1], "points": [{"x": 0, "y": 4}, {"x": 6, "y": 4}, {"x": 6, "y": 6}, {"x": 0, "y": 6}]},
                ],
                "existing_vias": [],
                "pad_stacks": [],
            },
            indent=2,
        )
    )
    cfg.write_text(
        json.dumps(
            {
                "commit_routes": True,
                "ncr_iters": 0,
                "ripup_passes": 0,
                "attempts": 1,
                "margin_init": 10,
                "margin_step": 10,
                "margin_max": 10,
                "enforce_spacing": False,
                "enforce_touch": True,
                "escape_enable": False,
                "astar_max_expansions": 100000,
                "max_time_ms": 2000,
                "per_net_time_ms": 1000,
                "precommit_shorts_enable": True,
                "pull_tight_enable": True,
                # Force B to stay on F.Cu.
                "net_layer_allow": {"B": ["F.Cu"]},
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    assert "A" not in out.get("failed_nets", [])
    assert "B" in out.get("failed_nets", [])

