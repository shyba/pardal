import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_precommit_shorts_blocks_unavoidable_crossing(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo shorts precommit test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "routing" / "mojo_router"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # Build a 7x7 board where only a '+' corridor is open:
    # - row y=3 is open
    # - col x=3 is open
    # All other cells are blocked by 4 quadrant polygons.
    #
    # Net A must go left->right on row 3.
    # Net B must go top->bottom on col 3.
    # They must cross at (3,3) with no alternative route, so precommit shorts should
    # reject routing the second net.
    polys = [
        # top-left quadrant (x=0..2, y=0..2)
        {"net_id": 0, "layers": [0], "points": [{"x": 0, "y": 0}, {"x": 2, "y": 0}, {"x": 2, "y": 2}, {"x": 0, "y": 2}]},
        # top-right quadrant (x=4..6, y=0..2)
        {"net_id": 0, "layers": [0], "points": [{"x": 4, "y": 0}, {"x": 6, "y": 0}, {"x": 6, "y": 2}, {"x": 4, "y": 2}]},
        # bottom-left quadrant (x=0..2, y=4..6)
        {"net_id": 0, "layers": [0], "points": [{"x": 0, "y": 4}, {"x": 2, "y": 4}, {"x": 2, "y": 6}, {"x": 0, "y": 6}]},
        # bottom-right quadrant (x=4..6, y=4..6)
        {"net_id": 0, "layers": [0], "points": [{"x": 4, "y": 4}, {"x": 6, "y": 4}, {"x": 6, "y": 6}, {"x": 4, "y": 6}]},
    ]

    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu"],
                "resolution_mm": 1.0,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": 7,
                "height": 7,
                "net_defaults": {
                    "track_width_mm": 1.0,
                    "clearance_mm": 0.0,
                    "via_diameter_mm": 0.6,
                    "via_drill_mm": 0.3,
                    "uvia_diameter_mm": 0.35,
                    "uvia_drill_mm": 0.15,
                },
                "nets": [
                    {
                        "net": "A",
                        "net_id": 1,
                        "start": {"layer": 0, "x": 0, "y": 3},
                        "goal": {"layer": 0, "x": 6, "y": 3},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 0.6,
                        "via_drill_mm": 0.3,
                        "uvia_diameter_mm": 0.35,
                        "uvia_drill_mm": 0.15,
                    },
                    {
                        "net": "B",
                        "net_id": 2,
                        "start": {"layer": 0, "x": 3, "y": 0},
                        "goal": {"layer": 0, "x": 3, "y": 6},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 0.6,
                        "via_drill_mm": 0.3,
                        "uvia_diameter_mm": 0.35,
                        "uvia_drill_mm": 0.15,
                    },
                ],
                "circles": [],
                "polygons": polys,
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
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    assert "A" not in out.get("failed_nets", [])
    assert "B" in out.get("failed_nets", [])


@pytest.mark.slow
def test_mojo_precommit_shorts_blocks_unavoidable_crossing_fast_index(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo shorts precommit test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "routing" / "mojo_router"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    polys = [
        {"net_id": 0, "layers": [0], "points": [{"x": 0, "y": 0}, {"x": 2, "y": 0}, {"x": 2, "y": 2}, {"x": 0, "y": 2}]},
        {"net_id": 0, "layers": [0], "points": [{"x": 4, "y": 0}, {"x": 6, "y": 0}, {"x": 6, "y": 2}, {"x": 4, "y": 2}]},
        {"net_id": 0, "layers": [0], "points": [{"x": 0, "y": 4}, {"x": 2, "y": 4}, {"x": 2, "y": 6}, {"x": 0, "y": 6}]},
        {"net_id": 0, "layers": [0], "points": [{"x": 4, "y": 4}, {"x": 6, "y": 4}, {"x": 6, "y": 6}, {"x": 4, "y": 6}]},
    ]

    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu"],
                "resolution_mm": 1.0,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": 7,
                "height": 7,
                "net_defaults": {
                    "track_width_mm": 1.0,
                    "clearance_mm": 0.0,
                    "via_diameter_mm": 0.6,
                    "via_drill_mm": 0.3,
                    "uvia_diameter_mm": 0.35,
                    "uvia_drill_mm": 0.15,
                },
                "nets": [
                    {
                        "net": "A",
                        "net_id": 1,
                        "start": {"layer": 0, "x": 0, "y": 3},
                        "goal": {"layer": 0, "x": 6, "y": 3},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 0.6,
                        "via_drill_mm": 0.3,
                        "uvia_diameter_mm": 0.35,
                        "uvia_drill_mm": 0.15,
                    },
                    {
                        "net": "B",
                        "net_id": 2,
                        "start": {"layer": 0, "x": 3, "y": 0},
                        "goal": {"layer": 0, "x": 3, "y": 6},
                        "track_width_mm": 1.0,
                        "via_diameter_mm": 0.6,
                        "via_drill_mm": 0.3,
                        "uvia_diameter_mm": 0.35,
                        "uvia_drill_mm": 0.15,
                    },
                ],
                "circles": [],
                "polygons": polys,
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
                "precommit_fast_index_enable": True,
                "precommit_fast_index_cell_mm": 2.0,
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    assert "A" not in out.get("failed_nets", [])
    assert "B" in out.get("failed_nets", [])
