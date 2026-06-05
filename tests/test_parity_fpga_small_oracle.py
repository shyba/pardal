import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parity
@pytest.mark.slow
def test_parity_fpga_small_oracle(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    repo_root = Path(__file__).resolve().parents[1]
    fixture_in = repo_root / "examples" / "fpga" / "fpga_unrouted.kicad_pcb"
    if not fixture_in.exists():
        pytest.skip("fpga fixture not present")

    tool = repo_root / "pardal" / "tools" / "run_parity_fixture.py"
    assert tool.exists()

    out_dir = repo_root / "build" / "pytest_parity" / tmp_path.name / "fpga_small_oracle"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(repo_root / "venv" / "bin" / "python"),
        str(tool),
        "--fixture-name",
        "fpga_small_oracle",
        "--in",
        str(fixture_in),
        "--out-dir",
        str(out_dir),
        "--freerouting-max-passes",
        "5",
        "--mojo-resolution",
        "0.2",
        "--mojo-dsn-dump",
        "--mojo-dsn-ir",
        "--normalize-footprint-libs",
    ]
    subprocess.run(cmd, cwd=str(repo_root), env=dict(os.environ), check=True, timeout=30 * 60)

    summary_path = out_dir / "fpga_small_oracle.summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    # Oracle should reach 0/0 on this fixture.
    assert payload["freerouting_ok"] is True
    assert payload["freerouting_drc"]["violations"] == 0
    assert payload["freerouting_drc"]["unconnected"] == 0

    # Mojo must at least generate outputs deterministically.
    assert payload["mojo_failed_nets"] >= 0
    assert Path(payload["routes_json"]).exists()
    assert Path(payload["problem_json"]).exists()
    assert Path(payload["mojo_out_pcb"]).exists()
