import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_dsn_dump_cli_smoke(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo DSN dump CLI smoke test")

    repo_root = Path(__file__).resolve().parents[1]
    mojo_root = repo_root / "routing" / "mojo_router"
    dsn = repo_root / "freerouting" / "tests" / "Issue269-min_fr_test" / "min_fr_test.dsn"
    if not dsn.exists():
        pytest.skip("freerouting fixture missing")

    out_json = tmp_path / "out.json"
    env = dict(os.environ)
    subprocess.run(
        [
            pixi,
            "run",
            "mojo",
            "run",
            "-I",
            ".",
            "main.mojo",
            "dsn-dump",
            str(dsn),
            str(out_json),
        ],
        cwd=mojo_root,
        env=env,
        check=True,
    )

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "pcb_name" in payload
    assert "layers" in payload
    assert "nets" in payload


@pytest.mark.slow
def test_mojo_dsn_ir_cli_smoke(tmp_path: Path):
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo DSN IR CLI smoke test")

    repo_root = Path(__file__).resolve().parents[1]
    mojo_root = repo_root / "routing" / "mojo_router"
    dsn = repo_root / "freerouting" / "tests" / "Issue269-min_fr_test" / "min_fr_test.dsn"
    if not dsn.exists():
        pytest.skip("freerouting fixture missing")

    out_json = tmp_path / "ir.json"
    env = dict(os.environ)
    subprocess.run(
        [
            pixi,
            "run",
            "mojo",
            "run",
            "-I",
            ".",
            "main.mojo",
            "dsn-ir",
            str(dsn),
            str(out_json),
        ],
        cwd=mojo_root,
        env=env,
        check=True,
    )

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "pcb_name" in payload
    assert "boundary_bbox_mm" in payload
    assert "pin_positions_mm" in payload
