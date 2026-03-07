from __future__ import annotations

import subprocess
from pathlib import Path


def _mojo_bin() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "pardal_router_mojo" / "build" / "pardal-router-mojo"


def test_fpga_small_tck_astar_capture_reproduces_no_path() -> None:
    # Captured A* input from a real fpga_small run at 0.2mm resolution.
    # When clearance/KO is treated as a *hard* block (allow_overlaps=False), the
    # net is unroutable in the current congested snapshot.
    bin_path = _mojo_bin()
    assert bin_path.exists(), f"missing mojo router binary at {bin_path} (run pardal_router_mojo/build.sh)"

    fixture = Path(__file__).with_name("data") / "fpga_small_tck_astar_strict_no_overlaps.json"
    proc = subprocess.run(
        [str(bin_path), "astar-direct", str(fixture)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "NO_PATH" in proc.stdout


def test_fpga_small_tck_astar_capture_succeeds_with_overlap_penalties() -> None:
    # Same snapshot, but with allow_overlaps=True, where KO/clearance becomes a
    # soft constraint (penalty) instead of a hard block. This should find a path.
    bin_path = _mojo_bin()
    assert bin_path.exists(), f"missing mojo router binary at {bin_path} (run pardal_router_mojo/build.sh)"

    fixture = Path(__file__).with_name("data") / "fpga_small_tck_astar_fail_0p2.json"
    proc = subprocess.run(
        [str(bin_path), "astar-direct", str(fixture)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "PATH_LEN" in proc.stdout
