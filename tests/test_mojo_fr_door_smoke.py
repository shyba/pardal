from __future__ import annotations

import subprocess
from pathlib import Path


def test_mojo_fr_door_smoke() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    mojo_dir = repo_root / "pardal-pcb" / "pardal_router_mojo"
    binary = mojo_dir / "build" / "pardal-router-mojo"

    if not binary.exists():
        subprocess.check_call(["bash", str(mojo_dir / "build.sh")], cwd=str(repo_root))

    out = subprocess.check_output([str(binary), "fr-door-smoke"], cwd=str(repo_root), text=True)
    assert "ok" in out

