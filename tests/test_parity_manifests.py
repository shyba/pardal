from __future__ import annotations

import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    return _repo_root().parent


def _resolve_path(raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    ws = (_workspace_root() / p).resolve()
    if ws.exists():
        return ws
    return (_repo_root() / p).resolve()


def _load_json(relpath: str):
    return json.loads((_repo_root() / relpath).read_text(encoding="utf-8"))


def test_parity_core_required_fixtures_have_pinned_cfg() -> None:
    core = _load_json("parity_fixtures/parity_core.json")
    assert isinstance(core, list)
    by_name = {str(row["name"]): row for row in core if isinstance(row, dict) and "name" in row}

    required = {
        "issue180_core",
        "fpga_small_core",
        "fpga_large_core",
        "issue269_power_planes_core",
    }
    missing = sorted(name for name in required if name not in by_name)
    assert not missing, f"missing required parity_core fixtures: {missing}"

    for name in sorted(required):
        row = by_name[name]
        cfg = row.get("mojo_cfg")
        assert isinstance(cfg, str) and cfg.strip(), f"{name} must pin mojo_cfg"
        cfg_path = _resolve_path(cfg)
        assert cfg_path.exists(), f"{name} mojo_cfg file missing: {cfg_path}"

        pcb = row.get("pcb")
        assert isinstance(pcb, str) and pcb.strip(), f"{name} must define pcb path"
        pcb_path = _resolve_path(pcb)
        assert pcb_path.exists(), f"{name} pcb file missing: {pcb_path}"


def test_fr_tier_placement_for_issue269_no_vias() -> None:
    fast = _load_json("parity_fixtures/fr_tiers/tier_fast.json")
    medium = _load_json("parity_fixtures/fr_tiers/tier_medium.json")
    target = "freerouting/tests/Issue269-NoViasOnPowerPlanes/Issue269-NoViasOnPowerPlanes.kicad_pcb"
    assert target not in fast
    assert target in medium


def test_parity_applicable_now_tracks_current_scope() -> None:
    applicable = _load_json("parity_fixtures/parity_applicable_now.json")
    assert isinstance(applicable, list)
    by_name = {str(row["name"]): row for row in applicable if isinstance(row, dict) and "name" in row}
    expected = {
        "issue180_core",
        "fpga_small_core",
        "issue269_power_planes_core",
    }
    assert set(by_name.keys()) == expected
    assert "fpga_large_core" not in by_name

    core = _load_json("parity_fixtures/parity_core.json")
    core_by_name = {str(row["name"]): row for row in core if isinstance(row, dict) and "name" in row}
    for name in sorted(expected):
        assert name in core_by_name
        app_row = by_name[name]
        core_row = core_by_name[name]
        assert app_row.get("pcb") == core_row.get("pcb")
        cfg = core_row.get("mojo_cfg")
        assert isinstance(cfg, str) and cfg.strip(), f"{name} must pin mojo_cfg in parity_core"
        cfg_path = _resolve_path(cfg)
        assert cfg_path.exists(), f"{name} mojo_cfg file missing: {cfg_path}"
