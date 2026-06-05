from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED_ARTIFACTS = (
    "board_source",
    "routes_source",
    "board_ir",
    "route_plan",
    "backend_manifest",
    "route_candidates",
    "apply_report",
    "diagnostics",
    "check_report",
)


def test_routing_dsl_example_cli_writes_complete_manifest(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    source_example = repo_root / "examples" / "routing_dsl"
    example_dir = tmp_path / "routing_dsl_example"
    shutil.copytree(source_example, example_dir)

    cmd = [
        sys.executable,
        "-m",
        "pardal.tools.routing_dsl_example",
        "--example-dir",
        str(example_dir),
    ]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    manifest_path = Path(proc.stdout.strip().splitlines()[-1])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema"] == "pardal.routing_dsl_example"
    assert manifest["authority"] == {
        "generated_board_authority": False,
        "routing_authority": False,
        "release_authority": False,
        "jlc_upload_authority": False,
        "orderable_claim": False,
    }
    assert manifest["counts"]["route_groups"] > 0
    assert manifest["counts"]["candidates"] > 0
    assert set(REQUIRED_ARTIFACTS).issubset(manifest["artifacts"])

    for key in REQUIRED_ARTIFACTS:
        artifact = manifest["artifacts"][key]
        path = Path(artifact["path"])
        assert path.exists(), key
        assert artifact["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(), key

    diagnostics = json.loads(Path(manifest["artifacts"]["diagnostics"]["path"]).read_text(encoding="utf-8"))
    assert diagnostics["schema"] == "pardal.route_diagnostics"
    assert diagnostics["diagnostics_hash"]
    assert diagnostics["row_count"] == len(diagnostics["rows"])
    assert diagnostics["summary"]["by_stage"] == []

    check_report = json.loads(Path(manifest["artifacts"]["check_report"]["path"]).read_text(encoding="utf-8"))
    assert check_report["schema"] == "pardal.route_dsl_example_check"
    assert check_report["check_hash"]
    assert check_report["counts"]["route_groups"] > 0
    assert check_report["counts"]["candidate_count"] > 0
    assert check_report["counts"]["diagnostics_rows"] >= 0
    assert check_report["authority"] == manifest["authority"]
    assert check_report["board_ir_ok"] is True
    assert check_report["route_plan_ok"] is True
    assert check_report["candidates_ok"] is True
    assert check_report["apply_report_ok"] is True
    assert check_report["diagnostics_ok"] is True
    assert check_report["diagnostics_hash"]
