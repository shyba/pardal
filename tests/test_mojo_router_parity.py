import json
import os
import subprocess
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _mojo_router_bin() -> Path:
    return _repo_root() / "pardal_router_mojo" / "build" / "pardal-router-mojo"


def _build_mojo_router() -> Path:
    build_script = _repo_root() / "pardal_router_mojo" / "build.sh"
    if not build_script.exists():
        raise FileNotFoundError(build_script)
    subprocess.run([str(build_script)], cwd=build_script.parent, check=True)
    out = _mojo_router_bin()
    if not out.exists():
        raise FileNotFoundError(out)
    return out


def _run_router(problem_json: Path, cfg_json: Path | None = None) -> dict:
    router = _mojo_router_bin()
    if not router.exists():
        router = _build_mojo_router()

    out_routes = Path(os.getenv("PYTEST_TMPDIR", "/tmp")) / "mojo_parity.routes.json"
    if out_routes.exists():
        out_routes.unlink()

    cmd = [str(router), str(problem_json), str(out_routes)]
    if cfg_json is not None:
        cmd.append(str(cfg_json))
    subprocess.run(cmd, check=True)
    return json.loads(out_routes.read_text(encoding="utf-8"))


@pytest.mark.slow
def test_fpga_large_smoke_runs():
    problem = _repo_root() / "fpga_large" / "fpga_large_csg324_breakout_mojo.problem.json"
    assert problem.exists()

    out = _run_router(problem)
    assert isinstance(out.get("failed_nets", []), list)


@pytest.mark.slow
def test_small_fpga_routes_all_nets():
    problem = _repo_root() / "fpga" / "fpga_unrouted_mojo_drc23.problem.json"
    assert problem.exists()

    out = _run_router(problem)
    assert len(out.get("failed_nets", [])) == 0
