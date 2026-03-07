from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parity
@pytest.mark.slow
def test_parity_applicable_suite_policy_gates(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    repo_root = Path(__file__).resolve().parents[1]
    python_bin = repo_root / "venv" / "bin" / "python"
    if not python_bin.exists():
        pytest.skip(f"missing python venv at {python_bin}")

    out_dir = repo_root / "build" / "pytest_parity_suite" / tmp_path.name / "applicable"
    out_dir.mkdir(parents=True, exist_ok=True)

    tool = repo_root / "pcb_tool" / "tools" / "run_parity_suite.py"
    policy_json = repo_root / "parity_fixtures" / "parity_gate_policy.json"
    assert tool.exists()
    assert policy_json.exists()

    cmd = [
        str(python_bin),
        str(tool),
        "--out-dir",
        str(out_dir),
        "--tier",
        "applicable",
        "--gate-policy-json",
        str(policy_json),
    ]
    subprocess.run(cmd, cwd=str(repo_root), env=dict(os.environ), check=True, timeout=120 * 60)

    payload = json.loads((out_dir / "suite_summary.json").read_text(encoding="utf-8"))
    rows = payload.get("rows")
    assert isinstance(rows, list)
    by_name = {str(r["fixture"]): r for r in rows if isinstance(r, dict) and "fixture" in r}
    assert set(by_name.keys()) == {"issue180_core", "fpga_small_core", "issue269_power_planes_core"}

    for name in ("issue180_core", "fpga_small_core"):
        row = by_name[name]
        assert int(row["mojo_violations_routing_only"]) == 0
        assert int(row["mojo_unconnected_routing_only"]) == 0
        assert int(row["mojo_failed_nets"]) == 0

    strict = by_name["issue269_power_planes_core"]
    assert int(strict["mojo_violations_routing_only"]) == int(strict["freerouting_violations_routing_only"])
    assert int(strict["mojo_unconnected_routing_only"]) == int(strict["freerouting_unconnected_routing_only"])
    assert int(strict["mojo_failed_nets"]) == 0

    assert payload.get("gate_ok") is True
