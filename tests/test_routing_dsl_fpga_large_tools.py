from __future__ import annotations

import json
from pathlib import Path

from pardal.routing_dsl.fpga_large_tools import build_fpga_large_tooling_pack


def test_fpga_large_tooling_pack_emits_dry_run_manifest(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "tests/fixtures/parity_fixtures").mkdir(parents=True)
    (repo_root / "examples" / "fpga_large").mkdir(parents=True)
    (repo_root / "tests/fixtures/parity_fixtures" / "fpga_large_only.json").write_text("[]\n", encoding="utf-8")
    (repo_root / "examples" / "fpga_large" / "mojo_cfg_ncr_fast_keepouts_nooverlap.json").write_text("{}\n", encoding="utf-8")

    work_dir = tmp_path / "work"
    result = build_fpga_large_tooling_pack(repo_root=repo_root, work_dir=work_dir)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema"] == "pardal.routing_dsl_fpga_large"
    assert manifest["authority"]["generated_board_authority"] is False
    assert manifest["counts"]["authority_false_flags"] == 5
    assert manifest["commands"][0]["command"][0] == "python3"
    assert manifest["next_worklist"]["entries"][0]["kind"] == "derived-route-source"
    assert manifest["artifacts"]["board_fixture"]["sha256"]
    assert manifest["artifacts"]["backend_cfg"]["sha256"]
    assert manifest["artifacts"]["source_route_problem"]["sha256"]
    assert manifest["artifacts"]["derived_routes"]["sha256"]
    assert manifest["artifacts"]["next_worklist"]["sha256"]
    assert manifest["artifacts"]["report"]["sha256"]
    assert (work_dir / "manifest.json").exists()
    assert (work_dir / "problem.json").exists()
    assert (work_dir / "routes.json").exists()


def test_fpga_large_tooling_pack_hashes_written_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "tests/fixtures/parity_fixtures").mkdir(parents=True)
    (repo_root / "examples" / "fpga_large").mkdir(parents=True)
    (repo_root / "tests/fixtures/parity_fixtures" / "fpga_large_only.json").write_text("[]\n", encoding="utf-8")
    (repo_root / "examples" / "fpga_large" / "mojo_cfg_ncr_fast_keepouts_nooverlap.json").write_text("{}\n", encoding="utf-8")

    work_dir = tmp_path / "work"
    result = build_fpga_large_tooling_pack(repo_root=repo_root, work_dir=work_dir)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    for key in ("source_route_problem", "derived_routes", "next_worklist", "report"):
        path = Path(manifest["artifacts"][key]["path"])
        assert path.exists()
        assert manifest["artifacts"][key]["sha256"]
        assert manifest["artifacts"][key]["sha256"] == __import__("hashlib").sha256(path.read_bytes()).hexdigest()
