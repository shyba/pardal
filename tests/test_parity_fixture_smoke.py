import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.slow
def test_parity_fixture_fpga_small_smoke(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    repo_root = Path(__file__).resolve().parents[1]
    fixture_in = repo_root / "fpga" / "fpga_unrouted.kicad_pcb"
    if not fixture_in.exists():
        pytest.skip("fpga fixture not present")

    tool = repo_root / "pcb_tool" / "tools" / "run_parity_fixture.py"
    assert tool.exists()

    out_dir = repo_root / "build" / "pytest_parity" / tmp_path.name / "fpga_small_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = repo_root / "fpga" / "mojo_cfg_fpga_small_overlap.json"
    if not cfg.exists():
        pytest.skip("mojo cfg missing")

    cmd = [
        str(repo_root / "venv" / "bin" / "python"),
        str(tool),
        "--fixture-name",
        "fpga_small",
        "--in",
        str(fixture_in),
        "--out-dir",
        str(out_dir),
        "--skip-freerouting",
        "--mojo-cfg",
        str(cfg),
        "--mojo-resolution",
        "0.2",
        "--mojo-route-timeout-s",
        "30",
        "--normalize-footprint-libs",
    ]
    env = dict(os.environ)
    subprocess.run(cmd, cwd=str(repo_root), env=env, check=True)

    summary_path = out_dir / "fpga_small.summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["fixture"] == "fpga_small"
    # This fixture run skips FreeRouting, so oracle DRC stats are not computed.
    assert payload["freerouting_drc"]["violations"] == -1
    assert payload["mojo_drc"]["violations"] >= 0
    assert payload["mojo_failed_nets"] >= -1
    assert payload["freerouting_ok"] in (True, False)
    assert "delta_drc_violations" in payload
    assert "delta_drc_unconnected" in payload
    assert "kicad_raw_dsn" in payload
    assert "kicad_dsn" in payload
    assert "kicad_dsn_dump_json" in payload
    assert "kicad_dsn_dump_ok" in payload
    assert "kicad_dsn_dump_error" in payload
    assert "kicad_dsn_ir_json" in payload
    assert "kicad_dsn_ir_ok" in payload
    assert "kicad_dsn_ir_error" in payload
    assert "freerouting_raw_dsn" in payload
    assert "freerouting_dsn" in payload
    assert "freerouting_ses" in payload
    assert "freerouting_dsn_dump_json" in payload
    assert "freerouting_dsn_dump_ok" in payload
    assert "freerouting_dsn_dump_error" in payload
    assert "freerouting_dsn_ir_json" in payload
    assert "freerouting_dsn_ir_ok" in payload
    assert "freerouting_dsn_ir_error" in payload
    assert "kicad_ir_stats" in payload
    assert "freerouting_ir_stats" in payload
    assert "delta_ir_wires" in payload
    assert "delta_ir_vias" in payload
    assert "delta_ir_pins" in payload
    assert "timing_s" in payload
    assert "mojo_violation_types" in payload
    assert "freerouting_violation_types" in payload


@pytest.mark.slow
def test_parity_fixture_fpga_large_mojo_only_smoke(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    repo_root = Path(__file__).resolve().parents[1]
    fixture_in = repo_root / "fpga_large" / "fpga_large_csg324_breakout.kicad_pcb"
    if not fixture_in.exists():
        pytest.skip("fpga_large fixture not present")

    tool = repo_root / "pcb_tool" / "tools" / "run_parity_fixture.py"
    assert tool.exists()

    out_dir = repo_root / "build" / "pytest_parity" / tmp_path.name / "fpga_large_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = repo_root / "fpga_large" / "mojo_cfg_ncr_fast.json"
    if not cfg.exists():
        pytest.skip("mojo cfg missing")

    cmd = [
        str(repo_root / "venv" / "bin" / "python"),
        str(tool),
        "--fixture-name",
        "fpga_large_mojo",
        "--in",
        str(fixture_in),
        "--out-dir",
        str(out_dir),
        "--skip-freerouting",
        "--mojo-cfg",
        str(cfg),
        "--mojo-resolution",
        "0.2",
        "--normalize-footprint-libs",
    ]
    env = dict(os.environ)
    subprocess.run(cmd, cwd=str(repo_root), env=env, check=True, timeout=20 * 60)

    summary_path = out_dir / "fpga_large_mojo.summary.json"
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload["fixture"] == "fpga_large_mojo"
    assert payload["mojo_drc"]["unconnected"] >= 0
    assert payload["mojo_failed_nets"] >= -1
    assert payload["freerouting_ok"] is False
    assert payload["delta_drc_violations"] == -1
    assert payload["delta_drc_unconnected"] == -1
    assert "kicad_raw_dsn" in payload
    assert "kicad_dsn" in payload
    assert "kicad_dsn_dump_json" in payload
    assert "kicad_dsn_dump_ok" in payload
    assert "kicad_dsn_dump_error" in payload
    assert "kicad_dsn_ir_json" in payload
    assert "kicad_dsn_ir_ok" in payload
    assert "kicad_dsn_ir_error" in payload
    assert "freerouting_raw_dsn" in payload
    assert "freerouting_dsn" in payload
    assert "freerouting_ses" in payload
    assert "freerouting_dsn_dump_json" in payload
    assert "freerouting_dsn_dump_ok" in payload
    assert "freerouting_dsn_dump_error" in payload
    assert "freerouting_dsn_ir_json" in payload
    assert "freerouting_dsn_ir_ok" in payload
    assert "freerouting_dsn_ir_error" in payload
    assert "kicad_ir_stats" in payload
    assert "freerouting_ir_stats" in payload
    assert "delta_ir_wires" in payload
    assert "delta_ir_vias" in payload
    assert "delta_ir_pins" in payload
    assert "timing_s" in payload
    assert "mojo_violation_types" in payload
    assert "freerouting_violation_types" in payload
