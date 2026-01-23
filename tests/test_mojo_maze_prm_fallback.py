import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_maze_prm_fallback_routes_simple_obstacle(tmp_path: Path):
    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "pardal_router_mojo"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
        if not pixi or not Path(pixi).exists():
            pytest.skip("pixi not available to build Mojo router")
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # Single-layer 2-pin net, with a circular keepout blocking the straight-line path.
    # Force A* to fail by limiting expansions to near-zero so the PRM fallback is used.
    data = {
        "resolution_mm": 1.0,
        "layers": ["F.Cu"],
        "width": 80,
        "height": 60,
        "net_defaults": {
            "track_width_mm": 1.0,
            "clearance_mm": 1.0,
            "via_diameter_mm": 1.0,
            "via_drill_mm": 0.5,
            "uvia_diameter_mm": 0.8,
            "uvia_drill_mm": 0.3,
        },
        "nets": [
            {
                "net": "N1",
                "net_id": 1,
                "track_width_mm": 1.0,
                "via_diameter_mm": 1.0,
                "via_drill_mm": 0.5,
                "uvia_diameter_mm": 0.8,
                "uvia_drill_mm": 0.3,
                "start": {"layer": 0, "x": 5, "y": 30},
                "goal": {"layer": 0, "x": 75, "y": 30},
            }
        ],
        "circles": [
            {
                "net_id": 0,
                "center": {"x": 40, "y": 30},
                "r": 12,
                "layers": [0],
            }
        ],
        "polygons": [],
        "existing_vias": [],
        "pad_stacks": [],
    }
    problem.write_text(json.dumps(data))

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
                "astar_max_expansions": 1,
                "maze_fallback_enable": True,
                "maze_samples": 4000,
                "maze_k_neigh": 24,
                "max_time_ms": 5000,
            }
        )
    )

    env = dict(os.environ)
    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True, env=env)
    out = json.loads(routes.read_text())
    assert out["backend"] == "pardal_router_mojo"
    assert out["failed_nets"] == []
    assert out["tracks"], "expected at least one track segment from PRM fallback"
