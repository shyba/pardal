from __future__ import annotations

import json
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_json(relpath: str):
    return json.loads((_repo_root() / relpath).read_text(encoding="utf-8"))


def _tier_paths(relpath: str) -> list[str]:
    payload = _load_json(relpath)
    assert isinstance(payload, list)
    out: list[str] = []
    for item in payload:
        if isinstance(item, str):
            out.append(item)
            continue
        if isinstance(item, dict):
            path = item.get("path")
            pcb = item.get("pcb")
            if isinstance(path, str):
                out.append(path)
                continue
            if isinstance(pcb, str):
                out.append(pcb)
                continue
        raise AssertionError(f"unsupported tier row in {relpath}: {item!r}")
    return out


def _policy_maps() -> tuple[dict[str, str], dict[str, str]]:
    payload = _load_json("tests/fixtures/parity_fixtures/parity_gate_policy.json")
    assert isinstance(payload, list)
    by_name: dict[str, str] = {}
    by_pcb: dict[str, str] = {}
    for row in payload:
        assert isinstance(row, dict)
        mode = row.get("mode")
        assert isinstance(mode, str) and mode in {"routing_only_zero", "fr_exact_routing_only", "baseline_exact"}
        name = row.get("name")
        pcb = row.get("pcb")
        assert isinstance(name, str) or isinstance(pcb, str)
        if isinstance(name, str) and name:
            by_name[name] = mode
        if isinstance(pcb, str) and pcb:
            by_pcb[pcb] = mode
    return by_name, by_pcb


def test_parity_gate_policy_required_modes_for_applicable_now() -> None:
    by_name, _by_pcb = _policy_maps()
    assert by_name.get("issue180_core") == "routing_only_zero"
    assert by_name.get("fpga_small_core") == "routing_only_zero"
    assert by_name.get("issue269_power_planes_core") == "fr_exact_routing_only"


def test_parity_gate_policy_covers_fast_and_medium_tiers() -> None:
    _by_name, by_pcb = _policy_maps()
    fast = _tier_paths("tests/fixtures/parity_fixtures/fr_tiers/tier_fast.json")
    medium = _tier_paths("tests/fixtures/parity_fixtures/fr_tiers/tier_medium.json")
    for pcb in fast + medium:
        assert pcb in by_pcb, f"missing gate policy for tier fixture: {pcb}"
        assert by_pcb[pcb] == "baseline_exact", f"unexpected mode for {pcb}: {by_pcb[pcb]}"
