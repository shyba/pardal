import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_shove_ripup_enables_crossing_on_two_layers(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo shove test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "pardal_router_mojo"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # Two nets must cross at the center. Without shove/ripup, routing sequentially
    # tends to fail for the second net under precommit shorts. With shove enabled,
    # the router is allowed to rip up the conflicting net and rely on a later pass
    # to reroute it using vias on the other layer.
    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu", "B.Cu"],
                "resolution_mm": 1.0,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": 9,
                "height": 9,
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
                        "start": {"layer": 0, "x": 0, "y": 4},
                        "goal": {"layer": 0, "x": 8, "y": 4},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 1.0,
                        "via_drill_mm": 0.4,
                        "uvia_diameter_mm": 1.0,
                        "uvia_drill_mm": 0.4,
                    },
                    {
                        "net": "B",
                        "net_id": 2,
                        "start": {"layer": 0, "x": 4, "y": 0},
                        "goal": {"layer": 0, "x": 4, "y": 8},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 1.0,
                        "via_drill_mm": 0.4,
                        "uvia_diameter_mm": 1.0,
                        "uvia_drill_mm": 0.4,
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
                "attempts": 1,
                "margin_init": 20,
                "margin_step": 20,
                "margin_max": 20,
                "enforce_spacing": False,
                "enforce_touch": True,
                "precommit_drc_enable": False,
                "precommit_shorts_enable": True,
                "pull_tight_enable": True,
                "shove_enable": True,
                "shove_max_rips": 4,
                "ripup_passes": 2,
                "ripup_k": 4,
                "astar_max_expansions": 200000,
                "max_time_ms": 3000,
                "per_net_time_ms": 1500,
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    assert out.get("failed_nets", []) == []

