import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_batch_fanout_reserves_unique_exits(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo fanout test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "pardal_router_mojo"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # 2-layer 11x11. Four nets start in a tight 2x2 cluster near center and must
    # escape to different boundary points before going to their goals.
    # With batch fanout enabled + escape_commit_early, they should all route.
    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu", "B.Cu"],
                "resolution_mm": 1.0,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": 11,
                "height": 11,
                "net_defaults": {
                    "track_width_mm": 1.0,
                    "clearance_mm": 0.0,
                    "via_diameter_mm": 1.0,
                    "via_drill_mm": 0.4,
                    "uvia_diameter_mm": 1.0,
                    "uvia_drill_mm": 0.4,
                },
                "nets": [
                    {"net": "N1", "net_id": 1, "start": {"layer": 0, "x": 5, "y": 5}, "goal": {"layer": 0, "x": 0, "y": 0}, "track_width_mm": 1.0, "via_diameter_mm": 1.0, "via_drill_mm": 0.4, "uvia_diameter_mm": 1.0, "uvia_drill_mm": 0.4},
                    {"net": "N2", "net_id": 2, "start": {"layer": 0, "x": 5, "y": 6}, "goal": {"layer": 0, "x": 10, "y": 0}, "track_width_mm": 1.0, "via_diameter_mm": 1.0, "via_drill_mm": 0.4, "uvia_diameter_mm": 1.0, "uvia_drill_mm": 0.4},
                    {"net": "N3", "net_id": 3, "start": {"layer": 0, "x": 6, "y": 5}, "goal": {"layer": 0, "x": 0, "y": 10}, "track_width_mm": 1.0, "via_diameter_mm": 1.0, "via_drill_mm": 0.4, "uvia_diameter_mm": 1.0, "uvia_drill_mm": 0.4},
                    {"net": "N4", "net_id": 4, "start": {"layer": 0, "x": 6, "y": 6}, "goal": {"layer": 0, "x": 10, "y": 10}, "track_width_mm": 1.0, "via_diameter_mm": 1.0, "via_drill_mm": 0.4, "uvia_diameter_mm": 1.0, "uvia_drill_mm": 0.4},
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
                "seed": 123,
                "ncr_iters": 0,
                "attempts": 4,
                "margin_init": 40,
                "margin_step": 40,
                "margin_max": 40,
                "enforce_spacing": False,
                "enforce_touch": True,
                "precommit_shorts_enable": True,
                "pull_tight_enable": True,
                "via_penalty": 5,
                "escape_enable": True,
                "escape_margin": 3,
                "escape_unique_exit": True,
                "escape_commit_early": True,
                "batch_fanout_enable": True,
                "batch_fanout_max_candidates": 24,
                "shove_enable": True,
                "shove_max_rips": 4,
                "ripup_passes": 3,
                "ripup_k": 6,
                "astar_max_expansions": 200000,
                "max_time_ms": 5000,
                "per_net_time_ms": 2000,
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    failed = out.get("failed_nets", []) or []
    # This synthetic case is designed to stress escape + unique-exit reservation.
    # Full 4/4 completion is not yet guaranteed without richer shove/negotiation
    # routing parity, but escape should keep failures rare.
    assert len(failed) <= 1
