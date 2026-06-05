import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.xfail(
    reason=(
        "Known gap: same-(x,y) cross-layer route can be reported connected "
        "after via conflict rollback; this fixture depends on that path."
    ),
    strict=False,
)
def test_mojo_precommit_respects_existing_via_drill_mm(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo existing-via drill test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "routing" / "mojo_router"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # Block every cell except the single start/goal coordinate so the router can
    # only solve this net with a direct via.
    width = 11
    height = 11
    sx = 5
    sy = 6
    circles = []
    for y in range(height):
        for x in range(width):
            if x == sx and y == sy:
                continue
            circles.append(
                {
                    "net_id": 0,
                    "center": {"x": x, "y": y},
                    "r": 0,
                    "layers": [0, 1],
                }
            )

    # Existing via is adjacent to the only legal via location. The annulus is tiny,
    # but drill is large enough to violate hole-to-hole clearance.
    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu", "B.Cu"],
                "resolution_mm": 0.5,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": width,
                "height": height,
                "net_defaults": {
                    "track_width_mm": 0.2,
                    "clearance_mm": 0.0,
                    "via_diameter_mm": 0.2,
                    "via_drill_mm": 0.2,
                    "uvia_diameter_mm": 0.2,
                    "uvia_drill_mm": 0.2,
                },
                "nets": [
                    {
                        "net": "A",
                        "net_id": 1,
                        "start": {"layer": 0, "x": sx, "y": sy},
                        "goal": {"layer": 1, "x": sx, "y": sy},
                        "track_width_mm": 0.2,
                        "via_diameter_mm": 0.2,
                        "via_drill_mm": 0.2,
                        "uvia_diameter_mm": 0.2,
                        "uvia_drill_mm": 0.2,
                    }
                ],
                "circles": circles,
                "polygons": [],
                "existing_vias": [
                    {
                        "net": "B",
                        "net_id": 2,
                        "layers": [0, 1],
                        "center": {"x": sx, "y": sy - 1},
                        "size_mm": 0.2,
                        "drill_mm": 1.2,
                    }
                ],
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
                "precommit_index_existing_vias": True,
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    assert "A" in out.get("failed_nets", [])
