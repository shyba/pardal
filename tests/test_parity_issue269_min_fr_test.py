import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_parity_fixture_issue269_min_fr_test_freerouting_only(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    repo_root = Path(__file__).resolve().parents[1]
    fixture_in = repo_root.parent / "freerouting" / "tests" / "Issue269-min_fr_test" / "min_fr_test.kicad_pcb"
    if not fixture_in.exists():
        pytest.skip("FreeRouting min_fr_test fixture not present")

    tool = repo_root / "pardal" / "tools" / "run_parity_fixture.py"
    assert tool.exists()

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(repo_root / "venv" / "bin" / "python"),
        str(tool),
        "--fixture-name",
        "issue269_min_fr_test",
        "--in",
        str(fixture_in),
        "--out-dir",
        str(out_dir),
        "--skip-mojo",
        "--freerouting-max-passes",
        "10",
    ]
    env = dict(os.environ)
    subprocess.run(cmd, cwd=str(repo_root), env=env, check=True, timeout=10 * 60)

    summary_path = out_dir / "issue269_min_fr_test.summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["fixture"] == "issue269_min_fr_test"
    assert payload["freerouting_ok"] is True
    # This is primarily a harness test: DRC may still be non-zero depending on settings.
    assert payload["freerouting_drc"]["violations"] >= 0
    assert payload["freerouting_drc"]["unconnected"] >= 0
    assert payload["mojo_out_pcb"] == ""
    assert payload["mojo_drc"]["violations"] == -1

