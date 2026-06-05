from __future__ import annotations

import json
from pathlib import Path

from pardal.routing_dsl.fpga_large_tools import build_fpga_large_finish_readiness_pack
from pardal import cli as cli_module


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _seed_repo(repo_root: Path) -> None:
    (repo_root / "tests/fixtures/parity_fixtures").mkdir(parents=True, exist_ok=True)
    (repo_root / "examples" / "fpga_large").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests" / "fixtures" / "routing_dsl").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests/fixtures/parity_fixtures" / "fpga_large_only.json").write_text("[]\n", encoding="utf-8")
    (repo_root / "examples" / "fpga_large" / "mojo_cfg_ncr_fast_keepouts_nooverlap.json").write_text("{}\n", encoding="utf-8")
    (repo_root / "tests" / "fixtures" / "routing_dsl" / "board.ir.json").write_text((FIXTURES / "board.ir.json").read_text(encoding="utf-8"), encoding="utf-8")
    (repo_root / "tests" / "fixtures" / "routing_dsl" / "route-plan-source.pdl.yaml").write_text((FIXTURES / "route-plan-source.pdl.yaml").read_text(encoding="utf-8"), encoding="utf-8")


def _run_cli(monkeypatch, capsys, *args: str) -> tuple[int, str, str]:
    monkeypatch.setattr("sys.argv", ["pardal", *args])
    code = cli_module.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_finish_readiness_dry_run_emits_manifest_and_summary(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _seed_repo(repo_root)

    result = build_fpga_large_finish_readiness_pack(repo_root=repo_root, work_dir=tmp_path / "work")
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert result.status == "continue"
    assert manifest["schema"] == "pardal.routing_dsl_fpga_large"
    assert manifest["mode"]["dry_run"] is True
    assert manifest["authority"]["routing_authority"] is False
    assert manifest["artifacts"]["board_ir"]["sha256"]
    assert manifest["artifacts"]["routes_pdl"]["sha256"]
    assert manifest["artifacts"]["route_plan_ir"]["sha256"]
    assert manifest["artifacts"]["backend_manifest"]["sha256"]
    assert manifest["artifacts"]["route_candidates"]["sha256"]
    assert manifest["artifacts"]["route_diagnostics"]["sha256"]
    assert manifest["artifacts"]["apply_report"]["sha256"]
    assert manifest["artifacts"]["drc"]["sha256"]
    assert manifest["artifacts"]["next_worklist"]["sha256"]
    assert manifest["artifacts"]["summary"]["sha256"]
    assert (tmp_path / "work" / "summary.md").read_text(encoding="utf-8").startswith("# fpga_large finish readiness")


def test_finish_readiness_explicit_net_list_is_route_linked(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _seed_repo(repo_root)

    result = build_fpga_large_finish_readiness_pack(
        repo_root=repo_root,
        work_dir=tmp_path / "work",
        net_list=("U1_C6", "U1_C7"),
        max_route_groups=1,
    )
    next_worklist = json.loads((tmp_path / "work" / "next-worklist.json").read_text(encoding="utf-8"))

    assert result.status == "continue"
    assert next_worklist["entries"][0]["kind"] == "explicit-net"
    assert next_worklist["entries"][0]["net"] == "U1_C6"
    assert next_worklist["entries"][0]["route_group_id"]


def test_finish_readiness_from_drc_buckets_unconnected_items(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _seed_repo(repo_root)
    drc_source = tmp_path / "input-drc.json"
    drc_source.write_text(
        json.dumps(
            {
                "$schema": "https://schemas.kicad.org/drc.v1.json",
                "coordinate_units": "mm",
                "unconnected_items": [
                    {
                        "type": "unconnected_items",
                        "description": "Missing connection between items",
                        "items": [
                            {"description": "Pad C6 [U1_C6] of U1 on F.Cu"},
                            {"description": "Pad 1 [U1_C6] of TP42 on F.Cu"},
                        ],
                    }
                ],
                "violations": [],
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_fpga_large_finish_readiness_pack(
        repo_root=repo_root,
        work_dir=tmp_path / "work",
        from_drc=drc_source,
        max_route_groups=2,
    )
    next_worklist = json.loads((tmp_path / "work" / "next-worklist.json").read_text(encoding="utf-8"))
    drc = json.loads((tmp_path / "work" / "drc.json").read_text(encoding="utf-8"))

    assert result.status == "continue"
    assert drc["$schema"].startswith("https://schemas.kicad.org/drc.v1.json")
    assert next_worklist["entries"]
    assert next_worklist["entries"][0]["kind"] == "drc-linked"
    assert next_worklist["entries"][0]["route_group_id"]


def test_finish_readiness_cli_prepare_and_resume(monkeypatch, capsys, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    _seed_repo(repo_root)
    work_dir = tmp_path / "work"

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "fpga-large",
        "prepare",
        "--repo-root",
        str(repo_root),
        "--work-dir",
        str(work_dir),
        "--max-route-groups",
        "3",
        "--budget-s",
        "12",
        "--candidate-cap",
        "2",
    )
    assert code == 0
    assert err == ""
    assert "manifest.json" in out
    assert (work_dir / "manifest.json").exists()

    code, out, err = _run_cli(
        monkeypatch,
        capsys,
        "route-dsl",
        "fpga-large",
        "resume",
        "--repo-root",
        str(repo_root),
        "--work-dir",
        str(work_dir),
        "--manifest",
        str(work_dir / "manifest.json"),
    )
    assert code == 0
    assert err == ""
    assert "manifest.json" in out
