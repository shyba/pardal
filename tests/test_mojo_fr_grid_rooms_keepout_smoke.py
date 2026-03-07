from __future__ import annotations

import subprocess
from pathlib import Path


def test_mojo_fr_grid_rooms_keepout_smoke() -> None:
    root = Path(__file__).resolve().parents[1]
    bin_path = root / "pardal_router_mojo" / "build" / "pardal-router-mojo"
    assert bin_path.exists(), f"missing mojo router binary at {bin_path} (run pardal_router_mojo/build.sh)"
    proc = subprocess.run(
        [str(bin_path), "fr-grid-rooms-keepout-smoke"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "ok" in proc.stdout

