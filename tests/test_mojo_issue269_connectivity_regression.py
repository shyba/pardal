import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parity
@pytest.mark.slow
def test_issue269_mojo_connectivity_no_failed_power_nets(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    repo_root = Path(__file__).resolve().parents[1]
    python_bin = repo_root / "venv" / "bin" / "python"
    if not python_bin.exists():
        pytest.skip(f"missing python venv at {python_bin}")

    fixture_in = (
        repo_root.parent
        / "freerouting"
        / "tests"
        / "Issue269-NoViasOnPowerPlanes"
        / "Issue269-NoViasOnPowerPlanes.kicad_pcb"
    )
    if not fixture_in.exists():
        pytest.skip(f"fixture missing: {fixture_in}")

    tool = repo_root / "pardal" / "tools" / "run_parity_fixture.py"
    assert tool.exists()
    mojo_cfg = repo_root / "tests/fixtures/parity_fixtures" / "mojo_cfgs" / "issue269_strict_parity.json"
    assert mojo_cfg.exists()

    out_dir = repo_root / "build" / "pytest_parity" / tmp_path.name / "issue269_connectivity"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(python_bin),
        str(tool),
        "--fixture-name",
        "issue269_connectivity",
        "--in",
        str(fixture_in),
        "--out-dir",
        str(out_dir),
        "--skip-freerouting",
        "--mojo-cfg",
        str(mojo_cfg),
        "--mojo-resolution",
        "0.2",
    ]
    subprocess.run(cmd, cwd=str(repo_root), env=dict(os.environ), check=True, timeout=35 * 60)

    summary_path = out_dir / "issue269_connectivity.summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert payload["mojo_ok"] is True
    assert payload["mojo_drc"]["unconnected"] == 0
    assert payload["mojo_failed_nets"] == 0

    routes = json.loads(Path(payload["routes_json"]).read_text(encoding="utf-8"))
    failed = set(routes.get("failed_nets", []) or [])
    assert "+3V3" not in failed
    assert "GNDREF" not in failed
