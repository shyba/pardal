import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parity
@pytest.mark.slow
def test_issue269_strict_exact_parity(tmp_path: Path):
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

    out_dir = repo_root / "build" / "pytest_parity" / tmp_path.name / "issue269_strict_exact"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(python_bin),
        str(tool),
        "--fixture-name",
        "issue269_strict_exact",
        "--in",
        str(fixture_in),
        "--out-dir",
        str(out_dir),
        "--freerouting-max-passes",
        "5",
        "--freerouting-job-timeout",
        "00:05:00",
        "--mojo-cfg",
        str(mojo_cfg),
        "--mojo-resolution",
        "0.2",
    ]
    subprocess.run(cmd, cwd=str(repo_root), env=dict(os.environ), check=True, timeout=45 * 60)

    summary_path = out_dir / "issue269_strict_exact.summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert payload["freerouting_ok"] is True
    assert payload["mojo_ok"] is True
    assert payload["mojo_failed_nets"] == 0

    assert payload["mojo_drc"]["violations"] == payload["freerouting_drc"]["violations"]
    assert payload["mojo_drc"]["unconnected"] == payload["freerouting_drc"]["unconnected"]
    assert payload["mojo_drc_routing_only"]["violations"] == payload["freerouting_drc_routing_only"]["violations"]
    assert payload["mojo_drc_routing_only"]["unconnected"] == payload["freerouting_drc_routing_only"]["unconnected"]
