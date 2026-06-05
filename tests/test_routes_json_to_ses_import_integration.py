import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pardal.tools.routes_json_to_ses import routes_to_ses


@pytest.mark.slow
def test_routes_json_to_ses_can_be_imported_by_kicad(tmp_path: Path):
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    # Use a real KiCad board that already has a matching DSN fixture.
    workspace_root = Path(__file__).resolve().parents[2]
    pcb_in = workspace_root / "freerouting" / "tests" / "Issue269-min_fr_test" / "min_fr_test.kicad_pcb"
    if not pcb_in.exists():
        pytest.skip("min_fr_test fixture not present")

    repo_root = Path(__file__).resolve().parents[1]
    tool = repo_root / "pardal" / "tools" / "run_parity_fixture.py"
    assert tool.exists()

    # Step 1: generate an importable SES template via FreeRouting.
    # Note: backend-route mounts the workspace root into docker and requires all
    # input/output files to be within that mount. Use a repo-local temp dir.
    out_dir = repo_root / "build" / "pytest_parity" / tmp_path.name
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(repo_root / "venv" / "bin" / "python"),
            str(tool),
            "--fixture-name",
            "min_fr_template",
            "--in",
            str(pcb_in),
            "--out-dir",
            str(out_dir),
            "--skip-mojo",
            "--freerouting-max-passes",
            "10",
        ],
        cwd=str(repo_root),
        env=dict(os.environ),
        check=True,
        timeout=10 * 60,
    )
    template_ses = out_dir / "min_fr_template.freerouting.ses"
    assert template_ses.exists()

    # Step 2: generate DSN + routes.json via backend-route (skip FreeRouting).
    subprocess.run(
        [
            str(repo_root / "venv" / "bin" / "python"),
            str(tool),
            "--fixture-name",
            "min_fr_mojo",
            "--in",
            str(pcb_in),
            "--out-dir",
            str(out_dir),
            "--skip-freerouting",
            "--mojo-resolution",
            "0.2",
        ],
        cwd=str(repo_root),
        env=dict(os.environ),
        check=True,
        timeout=10 * 60,
    )

    dsn = out_dir / "min_fr_mojo.kicad.dsn"
    routes = out_dir / "min_fr_mojo.mojo.routes.json"
    assert dsn.exists()
    assert routes.exists()
    payload = json.loads(routes.read_text(encoding="utf-8", errors="replace"))
    assert "tracks" in payload

    # Step 3: emit SES (by replacing network_out inside the template) and import it.
    ses = out_dir / "min_fr_mojo.mojo.ses"
    routes_to_ses(dsn=dsn, routes_json=routes, out_ses=ses, host="pardal", template_ses=template_ses)
    assert ses.exists()

    pcb_out = out_dir / "min_fr_mojo.imported.kicad_pcb"
    pcb_out.unlink(missing_ok=True)
    pcb_out.write_text(pcb_in.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workspace_root}:/work",
        "-v",
        f"{out_dir}:/out",
        "kicad/kicad:9.0.6-full",
        "bash",
        "-lc",
        "python3 - <<'PY'\n"
        "import pcbnew\n"
        "b = pcbnew.LoadBoard('/out/min_fr_mojo.imported.kicad_pcb')\n"
        "ok = pcbnew.ImportSpecctraSES(b, '/out/min_fr_mojo.mojo.ses')\n"
        "assert ok\n"
        "pcbnew.SaveBoard('/out/min_fr_mojo.imported.kicad_pcb', b)\n"
        "PY",
    ]
    subprocess.run(docker_cmd, check=True, timeout=10 * 60)

    # If import succeeded, KiCad should be able to DRC the output.
    drc_json = out_dir / "min_fr_mojo.imported.drc.json"
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{out_dir}:/out",
            "kicad/kicad:9.0.6-full",
            "kicad-cli",
            "pcb",
            "drc",
            "--format",
            "json",
            "--output",
            "/out/min_fr_mojo.imported.drc.json",
            "/out/min_fr_mojo.imported.kicad_pcb",
        ],
        check=True,
        timeout=10 * 60,
    )
    assert drc_json.exists()
