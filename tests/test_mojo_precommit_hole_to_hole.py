import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_precommit_via_hole_to_hole_blocks_other_net(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo via hole clearance test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "routing" / "mojo_router"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # Net A and B are both via-in-place, but their copper annular rings are
    # intentionally small while their drills are large and overlapping.
    # This models KiCad hole-to-hole DRC: even if copper rings don't overlap,
    # the drills must respect hole clearance.
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
                    "via_diameter_mm": 0.7,
                    "via_drill_mm": 1.2,
                    "uvia_diameter_mm": 0.7,
                    "uvia_drill_mm": 1.2,
                },
                "nets": [
                    {
                        "net": "A",
                        "net_id": 1,
                        "start": {"layer": 0, "x": 3, "y": 3},
                        "goal": {"layer": 1, "x": 3, "y": 3},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 0.7,
                        "via_drill_mm": 1.2,
                        "uvia_diameter_mm": 0.7,
                        "uvia_drill_mm": 1.2,
                    },
                    {
                        "net": "B",
                        "net_id": 2,
                        "start": {"layer": 0, "x": 4, "y": 3},
                        "goal": {"layer": 1, "x": 4, "y": 3},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 0.7,
                        "via_drill_mm": 1.2,
                        "uvia_diameter_mm": 0.7,
                        "uvia_drill_mm": 1.2,
                    },
                ],
                "circles": [],
                "polygons": [],
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
                "astar_max_expansions": 50000,
                "max_time_ms": 2000,
                "per_net_time_ms": 1000,
                "precommit_shorts_enable": True,
                "pull_tight_enable": True,
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    assert "A" not in out.get("failed_nets", [])
    assert "B" in out.get("failed_nets", [])

