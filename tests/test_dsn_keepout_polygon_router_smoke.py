import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_dsn_keepout_polygon_routes_smoke(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo keepout polygon smoke test")

    ee_root = Path(__file__).resolve().parents[2]
    dsn = ee_root / "freerouting" / "tests" / "Issue229-display-8-digit-hc595.dsn"
    assert dsn.exists()

    from pcb_tool.tools.convert_dsn_to_problem import convert_dsn_to_problem

    problem = tmp_path / "problem.json"
    routes = tmp_path / "routes.json"
    cfg = tmp_path / "cfg.json"

    convert_dsn_to_problem(dsn_path=dsn, out_json=problem, net_limit=3)
    cfg.write_text(
        json.dumps(
            {
                "commit_routes": True,
                "ncr_iters": 0,
                "ripup_passes": 0,
                "attempts": 1,
                "margin_init": 64,
                "margin_step": 128,
                "margin_max": 256,
                "enforce_spacing": False,
                "enforce_touch": True,
                "escape_enable": False,
                "astar_max_expansions": 200000,
                "max_time_ms": 5000,
                "per_net_time_ms": 200,
            }
        )
    )

    mojo_root = ee_root / "pardal-pcb" / "pardal_router_mojo"
    bin_path = mojo_root / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        subprocess.run([pixi, "run", "bash", "build.sh"], cwd=mojo_root, check=True)

    env = dict(os.environ)
    subprocess.run([str(bin_path), str(problem), str(routes), str(cfg)], check=True, env=env)
    data = json.loads(routes.read_text())
    assert data["backend"] == "pardal_router_mojo"
    assert isinstance(data["tracks"], list)

