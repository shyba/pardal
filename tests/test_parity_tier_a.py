import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parity
@pytest.mark.slow
def test_parity_tier_a_issue269_min_fr_test_smoke(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    repo_root = Path(__file__).resolve().parents[1]
    fixture_in = repo_root.parent / "freerouting" / "tests" / "Issue269-min_fr_test" / "min_fr_test.kicad_pcb"
    if not fixture_in.exists():
        pytest.skip("FreeRouting min_fr_test fixture not present")

    tool = repo_root / "pardal" / "tools" / "run_parity_fixture.py"
    assert tool.exists()

    # Keep outputs inside the repo tree so docker-mounted tools can access them.
    out_dir = repo_root / "build" / "pytest_parity" / tmp_path.name / "tier_a"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(repo_root / "venv" / "bin" / "python"),
        str(tool),
        "--fixture-name",
        "tier_a_issue269_min_fr_test",
        "--in",
        str(fixture_in),
        "--out-dir",
        str(out_dir),
        "--freerouting-max-passes",
        "1",
        "--mojo-resolution",
        "0.2",
        "--mojo-dsn-dump",
        "--mojo-dsn-ir",
    ]
    subprocess.run(cmd, cwd=str(repo_root), env=dict(os.environ), check=True, timeout=15 * 60)

    summary_path = out_dir / "tier_a_issue269_min_fr_test.summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))

    assert payload["fixture"] == "tier_a_issue269_min_fr_test"
    assert payload["freerouting_ok"] in (True, False)
    assert payload["freerouting_drc"]["violations"] >= -1
    assert payload["freerouting_drc"]["unconnected"] >= -1
    assert payload["mojo_drc"]["violations"] >= 0
    assert payload["mojo_drc"]["unconnected"] >= 0
