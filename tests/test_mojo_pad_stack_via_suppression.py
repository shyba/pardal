import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_suppresses_via_on_pad_stack(tmp_path: Path):
    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "pardal_router_mojo"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not bin_path.exists():
        if not pixi or not Path(pixi).exists():
            pytest.skip("pixi not available and Mojo binary missing; skipping test")
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # Single net requiring only a layer change at one coordinate. The drilled
    # pad stack models existing vertical connectivity, so no additional via
    # should be emitted by the router at that coordinate.
    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu", "B.Cu"],
                "resolution_mm": 0.5,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": 5,
                "height": 5,
                "net_defaults": {
                    "track_width_mm": 0.2,
                    "clearance_mm": 0.0,
                    "via_diameter_mm": 0.6,
                    "via_drill_mm": 0.3,
                    "uvia_diameter_mm": 0.3,
                    "uvia_drill_mm": 0.1,
                },
                "nets": [
                    {
                        "net": "A",
                        "net_id": 1,
                        "start": {"layer": 0, "x": 2, "y": 2},
                        "goal": {"layer": 1, "x": 2, "y": 2},
                        "track_width_mm": 0.2,
                        "via_diameter_mm": 0.6,
                        "via_drill_mm": 0.3,
                        "uvia_diameter_mm": 0.3,
                        "uvia_drill_mm": 0.1,
                    }
                ],
                "circles": [],
                "polygons": [],
                "existing_vias": [],
                "pad_stacks": [
                    {
                        "net": "A",
                        "net_id": 1,
                        "layers": [0, 1],
                        "center": {"x": 2, "y": 2},
                        "drill_mm": 0.6,
                    }
                ],
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
                "margin_init": 2,
                "margin_step": 2,
                "margin_max": 2,
                "enforce_spacing": False,
                "enforce_touch": True,
                "escape_enable": False,
                "astar_max_expansions": 20000,
                "max_time_ms": 2000,
                "per_net_time_ms": 1000,
                "precommit_shorts_enable": True,
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    assert "A" not in out.get("failed_nets", [])
    assert len(out.get("vias", [])) == 0
