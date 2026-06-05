from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


MEDIUM_FIXTURES = [
    "freerouting/tests/Issue191-processor.Z80/processor.Z80.kicad_pcb",
    "freerouting/tests/Issue230-CNH_Functional_Tester/CNH_Functional_Tester_1.kicad_pcb",
    "freerouting/tests/Issue269-NoWiresOnPowerLayers/proba.kicad_pcb",
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_fixture(raw: str) -> Path:
    repo_root = _repo_root()
    workspace_root = repo_root.parent
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    cand = (workspace_root / p).resolve()
    if cand.exists():
        return cand
    return (repo_root / p).resolve()


def _fixture_id_from_path(pcb: Path) -> str:
    parts = list(pcb.parts)
    try:
        idx = parts.index("freerouting")
        rel = Path(*parts[idx + 2 :])
        return str(rel).replace("/", "__")
    except ValueError:
        return pcb.name.replace("/", "__")


def _baseline_json_for_fixture(pcb: Path) -> Path:
    repo_root = _repo_root()
    return repo_root / "tests/fixtures/parity_fixtures" / "baselines" / _fixture_id_from_path(pcb) / "baseline.json"


def _extract_last_json_obj(text: str) -> dict:
    lines = text.splitlines()
    start = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "{":
            start = i
            break
    if start is None:
        return json.loads(text)
    return json.loads("\n".join(lines[start:]) + "\n")


def _run_check(*, fixture: Path, out_dir: Path, timeout_s: float) -> dict:
    repo_root = _repo_root()
    python_bin = repo_root / "venv" / "bin" / "python"
    if not python_bin.exists():
        pytest.skip(f"missing python venv at {python_bin}")
    cmd = [
        str(python_bin),
        "-m",
        "pardal.tools.check_mojo_against_kicad_baseline",
        str(fixture),
        "--out-dir",
        str(out_dir),
        "--timeout-s",
        str(float(timeout_s)),
        "--drc-timeout-s",
        str(float(timeout_s)),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        env=dict(os.environ),
        check=False,
        capture_output=True,
        text=True,
        timeout=max(int(timeout_s) + 120, 300),
    )
    assert proc.returncode == 0, (
        f"strict parity check failed for {fixture} (rc={proc.returncode})\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )
    payload = _extract_last_json_obj(proc.stdout)
    assert payload.get("ok") is True
    assert "baseline_violation_types" in payload
    assert "mojo_violation_types" in payload
    return payload


@pytest.mark.slow
@pytest.mark.parametrize("fixture_rel", MEDIUM_FIXTURES)
def test_mojo_matches_fr_baseline_medium(fixture_rel: str, tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    fixture = _resolve_fixture(fixture_rel)
    if not fixture.exists():
        pytest.skip(f"fixture missing: {fixture}")

    baseline_json = _baseline_json_for_fixture(fixture)
    if not baseline_json.exists():
        pytest.skip(f"baseline missing: {baseline_json}")

    out_dir = _repo_root() / "build" / "pytest_parity_baseline" / tmp_path.name / "medium"
    out_dir.mkdir(parents=True, exist_ok=True)
    _run_check(fixture=fixture, out_dir=out_dir, timeout_s=240.0)
