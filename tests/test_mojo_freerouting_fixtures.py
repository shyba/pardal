import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_mojo_freerouting_fixture_parser_smoke():
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo fixture parser smoke test")

    repo_root = Path(__file__).resolve().parents[1]
    mojo_root = repo_root / "pardal_router_mojo"
    test_file = mojo_root / "tests" / "test_freerouting_fixtures.mojo"
    if not test_file.exists():
        raise FileNotFoundError(test_file)

    env = dict(os.environ)
    subprocess.run(
        [pixi, "run", "mojo", "run", "-I", ".", str(test_file.relative_to(mojo_root))],
        cwd=mojo_root,
        env=env,
        check=True,
    )


@pytest.mark.slow
def test_mojo_dsn_typed_extraction_smoke():
    pixi = shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    if not pixi or not Path(pixi).exists():
        pytest.skip("pixi not available; skipping Mojo DSN typed extraction test")

    repo_root = Path(__file__).resolve().parents[1]
    mojo_root = repo_root / "pardal_router_mojo"
    test_file = mojo_root / "tests" / "test_dsn_extract.mojo"
    if not test_file.exists():
        raise FileNotFoundError(test_file)

    env = dict(os.environ)
    subprocess.run(
        [pixi, "run", "mojo", "run", "-I", ".", str(test_file.relative_to(mojo_root))],
        cwd=mojo_root,
        env=env,
        check=True,
    )
