from __future__ import annotations

import subprocess
from pathlib import Path


def _mojo_bin() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "pardal_router_mojo" / "build" / "pardal-router-mojo"


def test_mojo_astar_direct_finds_path_in_corridor() -> None:
    # This is a low-noise reproducer: a 1-cell-tall corridor between two blocked
    # rectangles. A* must find a path from left to right.
    bin_path = _mojo_bin()
    assert bin_path.exists(), f"missing mojo router binary at {bin_path} (run pardal_router_mojo/build.sh)"

    fixture = Path(__file__).with_name("data") / "astar_narrow_corridor_coarse_fails.json"
    proc = subprocess.run(
        [str(bin_path), "astar-direct", str(fixture)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"expected path; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    assert "PATH_LEN" in proc.stdout

