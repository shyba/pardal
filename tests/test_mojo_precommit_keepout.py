import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_precommit_keepout_blocks_route(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo keepout precommit test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "routing" / "mojo_router"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # One net must pass through a vertical keepout wall on F.Cu; with precommit DRC enabled,
    # routing should be rejected and the net reported as failed.
    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu", "B.Cu"],
                "resolution_mm": 1.0,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": 20,
                "height": 20,
                "net_defaults": {
                    "track_width_mm": 1.0,
                    "clearance_mm": 0.5,
                    "via_diameter_mm": 0.6,
                    "via_drill_mm": 0.3,
                    "uvia_diameter_mm": 0.35,
                    "uvia_drill_mm": 0.15,
                },
                "nets": [
                    {
                        "net": "N1",
                        "net_id": 1,
                        "start": {"layer": 0, "x": 2, "y": 10},
                        "goal": {"layer": 0, "x": 18, "y": 10},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 0.6,
                        "via_drill_mm": 0.3,
                        "uvia_diameter_mm": 0.35,
                        "uvia_drill_mm": 0.15,
                    }
                ],
                "circles": [],
                "polygons": [
                    {
                        "net_id": 0,
                        "layers": [0],
                        "points": [
                            {"x": 9, "y": 0},
                            {"x": 11, "y": 0},
                            {"x": 11, "y": 19},
                            {"x": 9, "y": 19},
                        ],
                    }
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
                "margin_init": 50,
                "margin_step": 50,
                "margin_max": 50,
                "enforce_spacing": False,
                "enforce_touch": True,
                "escape_enable": False,
                "astar_max_expansions": 200000,
                "max_time_ms": 2000,
                "per_net_time_ms": 500,
                "precommit_drc_enable": True,
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    assert "N1" in out.get("failed_nets", [])
