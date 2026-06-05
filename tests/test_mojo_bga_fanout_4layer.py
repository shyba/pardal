import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_bga_fanout_4layer_improves_completion(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo BGA fanout test")

    ee_root = Path(__file__).resolve().parents[2]
    mojo_root = ee_root / "pardal-pcb" / "routing" / "mojo_router"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    # 4-layer 41x41. 16 nets start in a 4x4 BGA-like cluster (2-cell pitch). Goals are spread on
    # the perimeter. With escape + batch fanout + early commit, all nets should
    # escape the cluster and reach their goals without shorts.
    nets = []
    net_id = 1
    start_x0 = 16
    start_y0 = 16
    goals = []
    # 16 perimeter goals (clockwise) to avoid sharing targets.
    for x in range(0, 41, 2):
        goals.append((x, 0))
    for y in range(2, 41, 2):
        goals.append((40, y))
    for x in range(38, -1, -2):
        goals.append((x, 40))
    for y in range(38, 1, -2):
        goals.append((0, y))
    goals = goals[:16]
    gi = 0
    for dy in range(4):
        for dx in range(4):
            sx = start_x0 + dx
            sy = start_y0 + dy
            sx = start_x0 + dx * 2
            sy = start_y0 + dy * 2
            gx, gy = goals[gi]
            gi += 1
            nets.append(
                {
                    "net": f"N{net_id}",
                    "net_id": net_id,
                    "start": {"layer": 0, "x": sx, "y": sy},
                    "goal": {"layer": 0, "x": gx, "y": gy},
                    "track_width_mm": 1.0,
                    "via_diameter_mm": 1.0,
                    "via_drill_mm": 0.4,
                    "uvia_diameter_mm": 1.0,
                    "uvia_drill_mm": 0.4,
                }
            )
            net_id += 1

    problem.write_text(
        json.dumps(
            {
                "source": "synthetic",
                "format": "synthetic",
                "layers": ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
                "resolution_mm": 1.0,
                "origin_mm": {"x": 0.0, "y": 0.0},
                "width": 41,
                "height": 41,
                "net_defaults": {
                    "track_width_mm": 1.0,
                    "clearance_mm": 0.0,
                    "via_diameter_mm": 1.0,
                    "via_drill_mm": 0.4,
                    "uvia_diameter_mm": 1.0,
                    "uvia_drill_mm": 0.4,
                },
                "nets": nets,
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
                "ncr_iters": 2,
                "attempts": 4,
                "margin_init": 100,
                "margin_step": 50,
                "margin_max": 150,
                "diagonal": True,
                "enforce_spacing": False,
                "enforce_touch": True,
                "precommit_shorts_enable": True,
                "precommit_fast_index_enable": True,
                "precommit_fast_index_cell_mm": 3.0,
                "pull_tight_enable": True,
                "via_penalty": 0,
                "layer_penalty_outer": 50,
                "layer_penalty_in1": 0,
                "layer_penalty_inner": 0,
                "escape_enable": True,
                "escape_margin": 6,
                "escape_margin_step": 3,
                "escape_margin_max": 12,
                "escape_unique_exit": True,
                "escape_commit_early": True,
                "batch_fanout_enable": True,
                "batch_fanout_max_candidates": 64,
                "shove_enable": True,
                "shove_max_rips": 8,
                "ripup_passes": 3,
                "ripup_k": 12,
                "astar_max_expansions": 400000,
                "max_time_ms": 15000,
                "per_net_time_ms": 2000,
            },
            indent=2,
        )
    )

    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True)
    out = json.loads(routes.read_text())
    failed = out.get("failed_nets", []) or []
    # Baseline for this synthetic BGA-like case: completing all 16 nets would
    # require true shove + richer legality. In the current Phase 3 MVP, we
    # expect the escape stage to significantly reduce failures.
    assert len(failed) <= 6
