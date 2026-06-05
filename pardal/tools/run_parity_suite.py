#!/usr/bin/env python3
"""Run a suite of parity fixtures via `run_parity_fixture.run_fixture`.

This is a convenience wrapper for the parity plan:
- runs a list of `.kicad_pcb` fixtures (FreeRouting oracle + Mojo backend-route)
- writes per-fixture artifacts into a single out directory
- emits `suite_summary.json` and a human-readable summary table
- supports per-fixture Mojo budgets/timeouts and regression gates vs baseline JSON
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pardal.freerouting_backend import FreeroutingRunConfig
from pardal.kicad_docker import DEFAULT_IMAGE
from pardal.tools.run_parity_fixture import FixtureSummary, append_parity_diary_entry, run_fixture

TIER_TO_FILE: dict[str, str] = {
    "applicable": "tests/fixtures/parity_fixtures/parity_applicable_now.json",
    "fast": "tests/fixtures/parity_fixtures/fr_tiers/tier_fast.json",
    "medium": "tests/fixtures/parity_fixtures/fr_tiers/tier_medium.json",
    "nightly": "tests/fixtures/parity_fixtures/fr_tiers/tier_nightly.json",
}


@dataclass(frozen=True)
class SuiteRow:
    fixture: str
    input_pcb: str
    freerouting_ok: bool
    freerouting_violations: int
    freerouting_unconnected: int
    freerouting_violations_routing_only: int
    freerouting_unconnected_routing_only: int
    mojo_violations: int
    mojo_unconnected: int
    mojo_violations_routing_only: int
    mojo_unconnected_routing_only: int
    mojo_failed_nets: int
    mojo_route_p50_s: float
    mojo_route_p90_s: float
    mojo_route_runs: int
    runtime_s: float


@dataclass(frozen=True)
class GatePolicyRule:
    mode: str
    fixture: str
    input_pcb: str


def _load_fixture_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("fixture list must be a JSON list of objects")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"fixture[{i}] must be an object")
        if "name" not in item or "pcb" not in item:
            raise ValueError(f"fixture[{i}] must include 'name' and 'pcb'")
        out.append(item)
    return out


def _load_tier_paths(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"tier file must be a list: {path}")
    out: list[str] = []
    for i, item in enumerate(payload):
        raw: str | None = None
        if isinstance(item, str):
            raw = item
        elif isinstance(item, dict):
            maybe_path = item.get("path")
            maybe_pcb = item.get("pcb")
            if isinstance(maybe_path, str):
                raw = maybe_path
            elif isinstance(maybe_pcb, str):
                raw = maybe_pcb
        if not raw:
            raise ValueError(f"tier[{i}] in {path} must be a path string or object with 'path'/'pcb'")
        out.append(raw)
    return out


def _fixture_name_from_pcb(raw: str) -> str:
    p = Path(raw)
    parent = p.parent.name.replace(".", "_").replace("-", "_")
    stem = p.stem.replace(".", "_").replace("-", "_")
    if parent:
        return f"{parent}_{stem}"
    return stem or "fixture"


def _resolve_pcb_path(*, workspace_root: Path, project_root: Path, raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    # Prefer workspace-root-relative (can reference freerouting/, etc)
    cand = (workspace_root / p).resolve()
    if cand.exists():
        return cand
    # Fallback: project-root-relative
    return (project_root / p).resolve()


def _resolve_optional_path(*, workspace_root: Path, project_root: Path, raw: str | None) -> Path | None:
    if raw is None:
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    cand = (workspace_root / p).resolve()
    if cand.exists():
        return cand
    return (project_root / p).resolve()


def _default_tier_a(workspace_root: Path, project_root: Path) -> list[dict[str, Any]]:
    # Keep this intentionally small. Add more once this is stable in CI.
    return [
        {
            "name": "tier_a_issue269_min_fr_test",
            "pcb": str(workspace_root / "freerouting" / "tests" / "Issue269-min_fr_test" / "min_fr_test.kicad_pcb"),
            "freerouting_max_passes": 1,
            "mojo_resolution": 0.2,
        },
    ]


def _default_tier_core(workspace_root: Path, project_root: Path) -> list[dict[str, Any]]:
    core_json = project_root / "tests/fixtures/parity_fixtures" / "parity_core.json"
    if core_json.exists():
        return _load_fixture_list(core_json)
    return [
        {
            "name": "issue180_core",
            "pcb": str(workspace_root / "freerouting" / "tests" / "Issue180-Test" / "Test.kicad_pcb"),
            "freerouting_max_passes": 50,
            "freerouting_job_timeout": "00:05:00",
            "mojo_cfg": str(project_root / "tests/fixtures/parity_fixtures" / "mojo_cfgs" / "issue180_core_pinned.json"),
            "mojo_resolution": 0.1,
            "mojo_budget_s": 120,
            "normalize_footprint_libs": True,
        },
        {
            "name": "fpga_small_core",
            "pcb": str(project_root / "examples" / "fpga" / "fpga_unrouted.kicad_pcb"),
            "freerouting_max_passes": 5,
            "freerouting_job_timeout": "00:02:00",
            "mojo_cfg": str(
                project_root / "tests/fixtures/parity_fixtures" / "mojo_cfgs" / "fpga_small_escape_legalize_nobatch_m20.json"
            ),
            "mojo_resolution": 0.2,
            "mojo_budget_s": 240,
        },
        {
            "name": "fpga_large_core",
            "pcb": str(project_root / "examples" / "fpga_large" / "fpga_large_rust_strict_fast_0p2.kicad_pcb"),
            "freerouting_max_passes": 50,
            "freerouting_job_timeout": "00:10:00",
            "mojo_cfg": str(project_root / "examples" / "fpga_large" / "mojo_cfg_ncr_fast_keepouts_nooverlap.json"),
            "mojo_resolution": 0.2,
            "mojo_budget_s": 60,
        },
        {
            "name": "issue269_power_planes_core",
            "pcb": str(
                workspace_root
                / "freerouting"
                / "tests"
                / "Issue269-NoViasOnPowerPlanes"
                / "Issue269-NoViasOnPowerPlanes.kicad_pcb"
            ),
            "freerouting_max_passes": 5,
            "freerouting_job_timeout": "00:05:00",
            "mojo_cfg": str(project_root / "tests/fixtures/parity_fixtures" / "mojo_cfgs" / "issue269_strict_parity.json"),
            "mojo_resolution": 0.2,
            "mojo_budget_s": 240,
        },
    ]


def _with_max_time_ms(cfg: Path | None, *, out_path: Path, max_time_ms: int) -> Path:
    payload: dict[str, Any] = {}
    if cfg is not None and cfg.exists():
        raw = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
        if isinstance(raw, dict):
            payload = raw
    payload["max_time_ms"] = int(max_time_ms)
    if "per_net_time_ms" not in payload:
        payload["per_net_time_ms"] = int(max(50, min(30_000, max_time_ms // 20)))
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def _with_json_overrides(cfg: Path | None, *, out_path: Path, overrides: dict[str, Any]) -> Path:
    payload: dict[str, Any] = {}
    if cfg is not None and cfg.exists():
        raw = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
        if isinstance(raw, dict):
            payload = raw
    for key, value in overrides.items():
        if value is not None:
            payload[str(key)] = value
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path


def _summary_gate_metrics(summary: FixtureSummary) -> dict[str, Any]:
    return {
        "freerouting_ok": bool(summary.freerouting_ok),
        "freerouting_violations": int(summary.freerouting_drc.violations),
        "freerouting_unconnected": int(summary.freerouting_drc.unconnected),
        "freerouting_violations_routing_only": int(summary.freerouting_drc_routing_only.violations),
        "freerouting_unconnected_routing_only": int(summary.freerouting_drc_routing_only.unconnected),
        "mojo_violations": int(summary.mojo_drc.violations),
        "mojo_unconnected": int(summary.mojo_drc.unconnected),
        "mojo_violations_routing_only": int(summary.mojo_drc_routing_only.violations),
        "mojo_unconnected_routing_only": int(summary.mojo_drc_routing_only.unconnected),
        "mojo_failed_nets": int(summary.mojo_failed_nets),
    }


def _summary_signature(summary: FixtureSummary) -> tuple[int, ...]:
    m = _summary_gate_metrics(summary)
    return (
        int(bool(m["freerouting_ok"])),
        int(m["freerouting_violations"]),
        int(m["freerouting_unconnected"]),
        int(m["freerouting_violations_routing_only"]),
        int(m["freerouting_unconnected_routing_only"]),
        int(m["mojo_violations"]),
        int(m["mojo_unconnected"]),
        int(m["mojo_violations_routing_only"]),
        int(m["mojo_unconnected_routing_only"]),
        int(m["mojo_failed_nets"]),
    )


def _validate_pinned_mojo_cfg(
    *,
    fixtures: list[dict[str, Any]],
    workspace_root: Path,
    project_root: Path,
    require_pinned_cfg: bool,
) -> None:
    if not require_pinned_cfg:
        return

    missing_cfg: list[str] = []
    missing_cfg_file: list[str] = []
    for fx in fixtures:
        name = str(fx.get("name", "<unnamed>"))
        raw_cfg = fx.get("mojo_cfg")
        if not isinstance(raw_cfg, str) or not raw_cfg.strip():
            missing_cfg.append(name)
            continue
        cfg_path = _resolve_optional_path(workspace_root=workspace_root, project_root=project_root, raw=raw_cfg)
        if cfg_path is None or not cfg_path.exists():
            missing_cfg_file.append(f"{name} -> {raw_cfg}")

    problems: list[str] = []
    if missing_cfg:
        problems.append("missing mojo_cfg: " + ", ".join(sorted(missing_cfg)))
    if missing_cfg_file:
        problems.append("missing mojo_cfg file: " + ", ".join(sorted(missing_cfg_file)))
    if problems:
        raise SystemExit(
            "Fixtures must pin per-fixture Mojo configs for parity reproducibility. "
            + " | ".join(problems)
            + " (use --allow-unpinned-mojo-cfg to override)"
        )


def _build_baseline(summaries: list[FixtureSummary]) -> dict[str, Any]:
    return {
        "version": 1,
        "fixtures": {s.fixture: _summary_gate_metrics(s) for s in summaries},
    }


def _load_baseline(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if isinstance(payload, dict) and isinstance(payload.get("fixtures"), dict):
        return {
            str(k): dict(v)
            for k, v in payload["fixtures"].items()
            if isinstance(k, str) and isinstance(v, dict)
        }
    if isinstance(payload, dict) and isinstance(payload.get("summaries"), list):
        out: dict[str, dict[str, Any]] = {}
        for row in payload["summaries"]:
            if not isinstance(row, dict):
                continue
            name = row.get("fixture")
            if not isinstance(name, str):
                continue
            out[name] = {
                "freerouting_ok": bool(row.get("freerouting_ok", False)),
                "freerouting_violations": int((row.get("freerouting_drc") or {}).get("violations", -1)),
                "freerouting_unconnected": int((row.get("freerouting_drc") or {}).get("unconnected", -1)),
                "freerouting_violations_routing_only": int(
                    (row.get("freerouting_drc_routing_only") or {}).get("violations", -1)
                ),
                "freerouting_unconnected_routing_only": int(
                    (row.get("freerouting_drc_routing_only") or {}).get("unconnected", -1)
                ),
                "mojo_violations": int((row.get("mojo_drc") or {}).get("violations", -1)),
                "mojo_unconnected": int((row.get("mojo_drc") or {}).get("unconnected", -1)),
                "mojo_violations_routing_only": int((row.get("mojo_drc_routing_only") or {}).get("violations", -1)),
                "mojo_unconnected_routing_only": int(
                    (row.get("mojo_drc_routing_only") or {}).get("unconnected", -1)
                ),
                "mojo_failed_nets": int(row.get("mojo_failed_nets", -1)),
            }
        return out
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        out = {}
        for row in payload["rows"]:
            if not isinstance(row, dict):
                continue
            name = row.get("fixture")
            if not isinstance(name, str):
                continue
            out[name] = {
                "freerouting_ok": bool(row.get("freerouting_ok", False)),
                "freerouting_violations": int(row.get("freerouting_violations", -1)),
                "freerouting_unconnected": int(row.get("freerouting_unconnected", -1)),
                "mojo_violations": int(row.get("mojo_violations", -1)),
                "mojo_unconnected": int(row.get("mojo_unconnected", -1)),
                "mojo_failed_nets": int(row.get("mojo_failed_nets", -1)),
            }
        return out
    raise ValueError(f"Unsupported baseline JSON schema: {path}")


def _load_gate_policy(
    *,
    path: Path,
    workspace_root: Path,
    project_root: Path,
) -> list[GatePolicyRule]:
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(payload, list):
        raise ValueError(f"gate policy must be a JSON list: {path}")
    out: list[GatePolicyRule] = []
    allowed_modes = {"routing_only_zero", "fr_exact_routing_only", "baseline_exact"}
    for i, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"gate policy row {i} in {path} must be an object")
        raw_mode = item.get("mode")
        if not isinstance(raw_mode, str) or raw_mode not in allowed_modes:
            raise ValueError(
                f"gate policy row {i} in {path} has invalid mode={raw_mode!r}; "
                f"allowed={sorted(allowed_modes)}"
            )
        raw_name = item.get("name", "")
        fixture = str(raw_name).strip() if isinstance(raw_name, str) else ""
        raw_pcb = item.get("pcb", "")
        input_pcb = ""
        if isinstance(raw_pcb, str) and raw_pcb.strip():
            input_pcb = str(
                _resolve_pcb_path(
                    workspace_root=workspace_root,
                    project_root=project_root,
                    raw=raw_pcb.strip(),
                ).resolve()
            )
        if not fixture and not input_pcb:
            raise ValueError(f"gate policy row {i} in {path} must include at least one of 'name' or 'pcb'")
        out.append(
            GatePolicyRule(
                mode=raw_mode,
                fixture=fixture,
                input_pcb=input_pcb,
            )
        )
    return out


def _fixture_id_from_pcb_path(pcb: Path) -> str:
    parts = list(pcb.parts)
    try:
        idx = parts.index("freerouting")
        rel = Path(*parts[idx + 2 :])  # skip freerouting/tests
        return str(rel).replace("/", "__")
    except ValueError:
        return pcb.name.replace("/", "__")


def _baseline_counts_for_fixture(*, project_root: Path, fixture: FixtureSummary) -> tuple[int, int] | None:
    try:
        pcb = Path(fixture.input_pcb).resolve()
    except Exception:
        return None
    fixture_id = _fixture_id_from_pcb_path(pcb)
    baseline_json = (
        project_root
        / "tests/fixtures/parity_fixtures"
        / "baselines"
        / fixture_id
        / "baseline.json"
    )
    if not baseline_json.exists():
        return None
    payload = json.loads(baseline_json.read_text(encoding="utf-8", errors="replace"))
    drc = payload.get("drc")
    if not isinstance(drc, dict):
        return None
    try:
        v = int(drc.get("violations", -1))
        u = int(drc.get("unconnected", -1))
    except Exception:
        return None
    if v < 0 or u < 0:
        return None
    return v, u


def _mode_for_fixture(*, summary: FixtureSummary, rules: list[GatePolicyRule]) -> str:
    fixture_name = str(summary.fixture)
    try:
        input_pcb = str(Path(summary.input_pcb).resolve())
    except Exception:
        input_pcb = str(summary.input_pcb)
    for r in rules:
        if r.fixture and r.fixture == fixture_name:
            return r.mode
    for r in rules:
        if r.input_pcb and r.input_pcb == input_pcb:
            return r.mode
    return ""


def _gate_by_policy(
    *,
    current: list[FixtureSummary],
    policy_rules: list[GatePolicyRule],
    project_root: Path,
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    checks: list[str] = []
    for s in current:
        mode = _mode_for_fixture(summary=s, rules=policy_rules)
        if not mode:
            continue
        m = _summary_gate_metrics(s)
        fx = s.fixture
        if mode == "routing_only_zero":
            v = int(m.get("mojo_violations_routing_only", -1))
            u = int(m.get("mojo_unconnected_routing_only", -1))
            f = int(m.get("mojo_failed_nets", -1))
            if v != 0 or u != 0:
                failures.append(f"{fx}: routing_only_zero violated (mojo routing-only {v}/{u})")
            else:
                checks.append(f"{fx}: routing_only_zero ok (0/0)")
            if f != 0:
                failures.append(f"{fx}: routing_only_zero violated (mojo_failed_nets={f})")
            else:
                checks.append(f"{fx}: routing_only_zero mojo_failed_nets ok (0)")
            continue
        if mode == "fr_exact_routing_only":
            fr_ok = bool(m.get("freerouting_ok", False))
            fr_v = int(m.get("freerouting_violations_routing_only", -1))
            fr_u = int(m.get("freerouting_unconnected_routing_only", -1))
            mo_v = int(m.get("mojo_violations_routing_only", -1))
            mo_u = int(m.get("mojo_unconnected_routing_only", -1))
            f = int(m.get("mojo_failed_nets", -1))
            if not fr_ok:
                failures.append(f"{fx}: fr_exact_routing_only violated (freerouting_ok=false)")
            if fr_v < 0 or fr_u < 0 or mo_v < 0 or mo_u < 0:
                failures.append(
                    f"{fx}: fr_exact_routing_only missing routing-only metrics "
                    f"(fr={fr_v}/{fr_u}, mojo={mo_v}/{mo_u})"
                )
            elif fr_v != mo_v or fr_u != mo_u:
                failures.append(
                    f"{fx}: fr_exact_routing_only mismatch "
                    f"(fr={fr_v}/{fr_u}, mojo={mo_v}/{mo_u})"
                )
            else:
                checks.append(f"{fx}: fr_exact_routing_only ok ({mo_v}/{mo_u})")
            if f != 0:
                failures.append(f"{fx}: fr_exact_routing_only violated (mojo_failed_nets={f})")
            else:
                checks.append(f"{fx}: fr_exact_routing_only mojo_failed_nets ok (0)")
            continue
        if mode == "baseline_exact":
            baseline = _baseline_counts_for_fixture(project_root=project_root, fixture=s)
            if baseline is None:
                failures.append(f"{fx}: baseline_exact missing baseline.json")
                continue
            want_v, want_u = baseline
            got_v = int(m.get("mojo_violations", -1))
            got_u = int(m.get("mojo_unconnected", -1))
            if got_v != want_v or got_u != want_u:
                failures.append(
                    f"{fx}: baseline_exact mismatch "
                    f"(baseline={want_v}/{want_u}, mojo={got_v}/{got_u})"
                )
            else:
                checks.append(f"{fx}: baseline_exact ok ({got_v}/{got_u})")
            continue
        failures.append(f"{fx}: unsupported gate policy mode={mode!r}")
    return failures, checks


def _gate_regressions(
    *,
    current: list[FixtureSummary],
    baseline: dict[str, dict[str, Any]],
    allow_missing_fixtures: bool,
) -> tuple[list[str], list[str]]:
    current_map = {s.fixture: _summary_gate_metrics(s) for s in current}
    failures: list[str] = []
    checks: list[str] = []
    tracked_keys = (
        "mojo_violations",
        "mojo_unconnected",
        "mojo_violations_routing_only",
        "mojo_unconnected_routing_only",
        "mojo_failed_nets",
    )
    for fx, want in baseline.items():
        got = current_map.get(fx)
        if got is None:
            if not allow_missing_fixtures:
                failures.append(f"{fx}: missing from current suite run")
            continue
        if bool(want.get("freerouting_ok", False)) and not bool(got.get("freerouting_ok", False)):
            failures.append(f"{fx}: freerouting_ok regressed (baseline=True, current=False)")
        for key in tracked_keys:
            wv = want.get(key, None)
            if wv is None:
                continue
            try:
                w = int(wv)
            except Exception:
                continue
            if w < 0:
                continue
            g = int(got.get(key, -1))
            if g < 0 or g > w:
                failures.append(f"{fx}: {key} regressed (baseline={w}, current={g})")
            else:
                checks.append(f"{fx}: {key} ok ({g} <= {w})")
    return failures, checks


def _gate_fr_exact(*, current: list[FixtureSummary]) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    checks: list[str] = []
    key_pairs = (
        ("violations", "freerouting_violations", "mojo_violations"),
        ("unconnected", "freerouting_unconnected", "mojo_unconnected"),
        ("violations_routing_only", "freerouting_violations_routing_only", "mojo_violations_routing_only"),
        ("unconnected_routing_only", "freerouting_unconnected_routing_only", "mojo_unconnected_routing_only"),
    )
    for s in current:
        m = _summary_gate_metrics(s)
        fx = s.fixture
        if not bool(m.get("freerouting_ok", False)):
            failures.append(f"{fx}: freerouting_ok is false")
        for label, fr_key, mojo_key in key_pairs:
            fr_v = int(m.get(fr_key, -1))
            mojo_v = int(m.get(mojo_key, -1))
            if fr_v < 0 or mojo_v < 0:
                failures.append(f"{fx}: missing metrics for {label} (fr={fr_v}, mojo={mojo_v})")
                continue
            if mojo_v != fr_v:
                failures.append(f"{fx}: FR exact mismatch for {label} (fr={fr_v}, mojo={mojo_v})")
            else:
                checks.append(f"{fx}: FR exact {label} ok ({mojo_v} == {fr_v})")
        failed_nets = int(m.get("mojo_failed_nets", -1))
        if failed_nets != 0:
            failures.append(f"{fx}: mojo_failed_nets must be 0 (current={failed_nets})")
        else:
            checks.append(f"{fx}: mojo_failed_nets ok (0)")
    return failures, checks


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--fixtures-json", type=Path, default=None, help="JSON list: [{name, pcb, ...}, ...]")
    ap.add_argument(
        "--tier",
        choices=["a", "core", "applicable", "fast", "medium", "nightly"],
        default=None,
        help="Use a built-in tier fixture list.",
    )
    ap.add_argument("--kicad-image", default=DEFAULT_IMAGE)
    ap.add_argument("--freerouting-seed", type=int, default=1)
    ap.add_argument("--freerouting-max-passes", type=int, default=1)
    ap.add_argument("--freerouting-job-timeout", type=str, default=None)
    ap.add_argument("--freerouting-java-image", type=str, default="eclipse-temurin:21-jre")
    ap.add_argument("--freerouting-no-fanout", action="store_true")
    ap.add_argument("--freerouting-strip-planes", action="store_true")
    ap.add_argument("--freerouting-enable-logging", action="store_true")
    ap.add_argument("--freerouting-log-level", type=str, default=None)
    ap.add_argument("--freerouting-capture-stdout", action="store_true")
    ap.add_argument("--freerouting-capture-stderr", action="store_true")
    ap.add_argument("--freerouting-use-local-jar", type=Path, default=None)
    ap.add_argument(
        "--freerouting-trace-jsonl",
        type=str,
        default="off",
        help="FreeRouting decision trace output: off | auto | <path relative to fixture out-dir or absolute>.",
    )
    ap.add_argument(
        "--freerouting-trace-nets",
        type=str,
        default=None,
        help="Optional FreeRouting trace net filter (csv names/#ids or 're:<regex>').",
    )
    ap.add_argument("--freerouting-trace-max-events", type=int, default=None)
    ap.add_argument("--mojo-cfg", type=Path, default=None)
    ap.add_argument("--mojo-resolution", type=float, default=0.2)
    ap.add_argument("--skip-freerouting", action="store_true")
    ap.add_argument("--skip-mojo", action="store_true")
    ap.add_argument("--mojo-budget-s", type=float, default=None, help="Global Mojo route budget (seconds).")
    ap.add_argument("--mojo-extract-timeout-s", type=float, default=None)
    ap.add_argument("--mojo-route-timeout-s", type=float, default=None)
    ap.add_argument("--mojo-apply-timeout-s", type=float, default=None)
    ap.add_argument(
        "--warm-runs",
        type=int,
        default=1,
        help="Run Mojo backend-route N warm runs per fixture (N>1 performs 1 warmup + N measured runs).",
    )
    ap.add_argument(
        "--perf-mode",
        choices=["safe", "fast"],
        default="safe",
        help="Mojo perf mode override written into per-fixture cfg overlays.",
    )
    ap.add_argument(
        "--perf-json",
        action="store_true",
        help="Emit Mojo perf sidecars and suite-level `mojo_perf_summary.json`.",
    )
    ap.add_argument(
        "--normalize-footprint-libs",
        action="store_true",
        help="Materialize referenced footprint libraries before routing.",
    )
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--kicad-drc-timeout-s", type=float, default=300.0)
    ap.add_argument("--mojo-dsn-dump", action="store_true")
    ap.add_argument("--mojo-dsn-ir", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--no-update-diary",
        action="store_true",
        help="Disable automatic PARITY_DIARY.md append for this suite batch.",
    )
    ap.add_argument(
        "--diary-path",
        type=Path,
        default=None,
        help="Override diary path (default: <project_root>/PARITY_DIARY.md).",
    )
    ap.add_argument(
        "--diary-label",
        type=str,
        default=None,
        help="Optional short label for the diary batch entry.",
    )
    ap.add_argument(
        "--write-baseline-json",
        type=Path,
        default=None,
        help="Write compact baseline JSON from this suite run for future regression gates.",
    )
    ap.add_argument(
        "--gate-baseline-json",
        type=Path,
        default=None,
        help="Fail if current metrics regress versus this baseline JSON/suite_summary.json.",
    )
    ap.add_argument(
        "--gate-allow-missing-fixtures",
        action="store_true",
        help="Allow baseline fixtures to be absent from this suite run.",
    )
    ap.add_argument(
        "--allow-unpinned-mojo-cfg",
        action="store_true",
        help="Allow fixtures without per-fixture `mojo_cfg` (not recommended for parity runs).",
    )
    ap.add_argument(
        "--determinism-runs",
        type=int,
        default=1,
        help="Run each fixture N times and fail if summary metrics differ across runs.",
    )
    ap.add_argument(
        "--gate-fr-exact",
        action="store_true",
        help="Fail if Mojo metrics are not exactly equal to FreeRouting metrics on each fixture.",
    )
    ap.add_argument(
        "--gate-policy-json",
        type=Path,
        default=None,
        help="Fixture policy JSON with per-fixture gate modes (routing_only_zero|fr_exact_routing_only|baseline_exact).",
    )
    args = ap.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    workspace_root = Path(__file__).resolve().parents[3]

    if args.fixtures_json and args.tier:
        raise SystemExit("Use exactly one of --fixtures-json or --tier.")

    if args.fixtures_json:
        fixtures = _load_fixture_list(args.fixtures_json)
    elif args.tier == "a":
        fixtures = _default_tier_a(workspace_root=workspace_root, project_root=project_root)
    elif args.tier == "core":
        fixtures = _default_tier_core(workspace_root=workspace_root, project_root=project_root)
    elif args.tier in TIER_TO_FILE:
        tier_file = (project_root / TIER_TO_FILE[str(args.tier)]).resolve()
        if not tier_file.exists():
            raise SystemExit(f"missing tier file: {tier_file}")
        tier_paths = _load_tier_paths(tier_file)
        core_fx = _default_tier_core(workspace_root=workspace_root, project_root=project_root)
        by_pcb: dict[str, dict[str, Any]] = {}
        for fx in core_fx:
            pcb_path = _resolve_pcb_path(
                workspace_root=workspace_root,
                project_root=project_root,
                raw=str(fx["pcb"]),
            )
            by_pcb[str(pcb_path)] = fx
        fixtures = []
        for raw in tier_paths:
            pcb = _resolve_pcb_path(workspace_root=workspace_root, project_root=project_root, raw=raw)
            key = str(pcb)
            if key in by_pcb:
                fixtures.append(dict(by_pcb[key]))
            else:
                fixtures.append(
                    {
                        "name": _fixture_name_from_pcb(raw),
                        "pcb": raw,
                    }
                )
    else:
        raise SystemExit("Provide --fixtures-json or --tier (a|core|applicable|fast|medium|nightly).")

    if args.limit and args.limit > 0:
        fixtures = fixtures[: int(args.limit)]

    require_pinned_cfg = not bool(args.allow_unpinned_mojo_cfg) and args.tier != "a"
    _validate_pinned_mojo_cfg(
        fixtures=fixtures,
        workspace_root=workspace_root,
        project_root=project_root,
        require_pinned_cfg=require_pinned_cfg,
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)

    suite_started = time.perf_counter()
    rows: list[SuiteRow] = []
    summaries: list[FixtureSummary] = []
    determinism_failures: list[str] = []
    determinism_runs = int(args.determinism_runs)
    if determinism_runs <= 0:
        determinism_runs = 1

    for i, fx in enumerate(fixtures, start=1):
        name = str(fx["name"])
        pcb = _resolve_pcb_path(workspace_root=workspace_root, project_root=project_root, raw=str(fx["pcb"]))
        if not pcb.exists():
            print(f"[{i}/{len(fixtures)}] {name}: SKIP missing pcb={pcb}")
            continue

        out_dir = args.out_dir / name
        out_dir.mkdir(parents=True, exist_ok=True)

        fr_enable_logging = bool(fx.get("freerouting_enable_logging", args.freerouting_enable_logging))
        fr_log_level_raw = fx.get("freerouting_log_level", args.freerouting_log_level)
        fr_log_level = None if fr_log_level_raw is None else str(fr_log_level_raw)
        if fr_log_level is not None:
            fr_enable_logging = True

        fr_capture_stdout = bool(fx.get("freerouting_capture_stdout", args.freerouting_capture_stdout))
        fr_capture_stderr = bool(fx.get("freerouting_capture_stderr", args.freerouting_capture_stderr))

        fr_use_local_jar_raw = fx.get(
            "freerouting_use_local_jar",
            str(args.freerouting_use_local_jar) if args.freerouting_use_local_jar is not None else None,
        )
        fr_use_local_jar = _resolve_optional_path(
            workspace_root=workspace_root,
            project_root=project_root,
            raw=str(fr_use_local_jar_raw) if fr_use_local_jar_raw is not None else None,
        )

        fr_tmpdir_relpath: str | None = None
        if fr_enable_logging:
            fr_tmpdir_host = (out_dir / "_freerouting_tmp").resolve()
            try:
                fr_tmpdir_relpath = str(fr_tmpdir_host.relative_to(workspace_root))
            except ValueError:
                fr_tmpdir_relpath = None

        fr_trace_mode_raw = fx.get("freerouting_trace_jsonl", args.freerouting_trace_jsonl)
        fr_trace_path: Path | None = None
        if fr_trace_mode_raw is not None:
            if isinstance(fr_trace_mode_raw, bool):
                fr_trace_text = "auto" if fr_trace_mode_raw else "off"
            else:
                fr_trace_text = str(fr_trace_mode_raw).strip()
            if fr_trace_text and fr_trace_text.lower() != "off":
                if fr_trace_text.lower() == "auto":
                    fr_trace_path = (out_dir / f"{name}.freerouting.trace.jsonl").resolve()
                else:
                    trace_candidate = Path(fr_trace_text)
                    if not trace_candidate.is_absolute():
                        trace_candidate = (out_dir / trace_candidate).resolve()
                    fr_trace_path = trace_candidate.resolve()

        fr_trace_nets_raw = fx.get("freerouting_trace_nets", args.freerouting_trace_nets)
        fr_trace_max_events_raw = fx.get("freerouting_trace_max_events", args.freerouting_trace_max_events)
        fr_jvm_props: list[str] = []
        if fr_trace_path is not None:
            try:
                fr_trace_rel = str(fr_trace_path.relative_to(workspace_root)).replace("\\", "/")
            except ValueError as e:
                raise SystemExit(
                    f"FreeRouting trace path for fixture '{name}' must be under workspace root ({workspace_root}): {fr_trace_path}"
                ) from e
            fr_jvm_props.append(f"-Dfreerouting.trace.path=/work/{fr_trace_rel}")
            if fr_trace_nets_raw is not None and str(fr_trace_nets_raw).strip():
                fr_jvm_props.append(f"-Dfreerouting.trace.net_filter={str(fr_trace_nets_raw).strip()}")
            if fr_trace_max_events_raw is not None:
                fr_jvm_props.append(f"-Dfreerouting.trace.max_events={int(fr_trace_max_events_raw)}")

        fr_cfg = FreeroutingRunConfig(
            kicad_docker_image=str(args.kicad_image),
            java_docker_image=str(fx.get("freerouting_java_image", args.freerouting_java_image)),
            max_passes=int(fx.get("freerouting_max_passes", args.freerouting_max_passes)),
            fanout=not bool(fx.get("freerouting_no_fanout", args.freerouting_no_fanout)),
            strip_planes=bool(fx.get("freerouting_strip_planes", args.freerouting_strip_planes)),
            random_seed=int(fx.get("freerouting_seed", args.freerouting_seed)),
            router_job_timeout=str(fx.get("freerouting_job_timeout", args.freerouting_job_timeout))
            if (fx.get("freerouting_job_timeout", args.freerouting_job_timeout) is not None)
            else None,
            disable_logging=not bool(fr_enable_logging),
            enable_logging=bool(fr_enable_logging),
            log_level=fr_log_level,
            java_tmpdir_relpath=fr_tmpdir_relpath,
            capture_stdout_path=((out_dir / f"{name}.freerouting.stdout.log").resolve() if fr_capture_stdout else None),
            capture_stderr_path=((out_dir / f"{name}.freerouting.stderr.log").resolve() if fr_capture_stderr else None),
            jar_override=fr_use_local_jar,
            jvm_props=tuple(fr_jvm_props),
        )

        mojo_resolution = float(fx.get("mojo_resolution", args.mojo_resolution))
        mojo_cfg = _resolve_optional_path(
            workspace_root=workspace_root,
            project_root=project_root,
            raw=str(fx["mojo_cfg"]) if ("mojo_cfg" in fx and fx["mojo_cfg"] is not None) else (str(args.mojo_cfg) if args.mojo_cfg else None),
        )
        mojo_budget_s = fx.get("mojo_budget_s", args.mojo_budget_s)
        mojo_route_timeout_s = fx.get("mojo_route_timeout_s", args.mojo_route_timeout_s)
        mojo_extract_timeout_s = fx.get("mojo_extract_timeout_s", args.mojo_extract_timeout_s)
        mojo_apply_timeout_s = fx.get("mojo_apply_timeout_s", args.mojo_apply_timeout_s)
        normalize_footprint_libs = bool(fx.get("normalize_footprint_libs", args.normalize_footprint_libs))
        warm_runs = max(1, int(fx.get("warm_runs", args.warm_runs)))
        perf_mode = str(fx.get("perf_mode", args.perf_mode)).strip().lower()
        if perf_mode not in {"safe", "fast"}:
            perf_mode = "safe"

        if mojo_budget_s is not None and not bool(args.skip_mojo):
            max_time_ms = max(1, int(float(mojo_budget_s) * 1000.0) - 500)
            out_cfg = out_dir / f"{name}.mojo_budget_cfg.json"
            mojo_cfg = _with_max_time_ms(mojo_cfg, out_path=out_cfg, max_time_ms=max_time_ms)
            if mojo_route_timeout_s is None:
                mojo_route_timeout_s = float(mojo_budget_s) + 2.0

        if perf_mode != "safe" and not bool(args.skip_mojo):
            out_cfg = out_dir / f"{name}.mojo_perf_cfg.json"
            mojo_cfg = _with_json_overrides(
                mojo_cfg,
                out_path=out_cfg,
                overrides={"perf_mode": perf_mode, "adaptive_time_budget": True},
            )

        mojo_perf_json = (out_dir / f"{name}.mojo.perf.json") if bool(args.perf_json) else None

        print(f"[{i}/{len(fixtures)}] {name} (pcb={pcb})")
        t0 = time.perf_counter()
        summary: FixtureSummary | None = None
        first_signature: tuple[int, ...] | None = None
        run_i = 0
        while run_i < determinism_runs:
            run_out_dir = out_dir if run_i == 0 else (out_dir / f"run_{run_i + 1}")
            run_out_dir.mkdir(parents=True, exist_ok=True)
            run_summary = run_fixture(
                workspace_root=workspace_root,
                project_root=project_root,
                fixture_name=name,
                input_pcb=pcb,
                out_dir=run_out_dir,
                kicad_image=str(args.kicad_image),
                freerouting_cfg=fr_cfg,
                mojo_cfg_json=mojo_cfg,
                mojo_resolution_mm=mojo_resolution,
                mojo_inflate_mm=None,
                run_freerouting=not bool(args.skip_freerouting),
                run_mojo=not bool(args.skip_mojo),
                # Avoid stale mojo cache reuse for per-fixture pinned cfg runs.
                cache=(not bool(args.no_cache))
                and (mojo_cfg is None)
                and warm_runs <= 1
                and (not bool(args.perf_json)),
                drc_timeout_s=float(args.kicad_drc_timeout_s),
                mojo_dump_dsn=bool(args.mojo_dsn_dump),
                mojo_dump_ir=bool(args.mojo_dsn_ir),
                normalize_footprint_libs=normalize_footprint_libs,
                mojo_extract_timeout_s=None if mojo_extract_timeout_s is None else float(mojo_extract_timeout_s),
                mojo_route_timeout_s=None if mojo_route_timeout_s is None else float(mojo_route_timeout_s),
                mojo_apply_timeout_s=None if mojo_apply_timeout_s is None else float(mojo_apply_timeout_s),
                mojo_warm_runs=warm_runs,
                mojo_perf_json=mojo_perf_json,
                mojo_perf_mode=perf_mode,
            )
            this_signature = _summary_signature(run_summary)
            if run_i == 0:
                summary = run_summary
                first_signature = this_signature
                (out_dir / f"{name}.summary.json").write_text(
                    json.dumps(asdict(run_summary), indent=2, sort_keys=True), encoding="utf-8"
                )
            else:
                (run_out_dir / f"{name}.summary.json").write_text(
                    json.dumps(asdict(run_summary), indent=2, sort_keys=True), encoding="utf-8"
                )
                if first_signature is not None and this_signature != first_signature:
                    determinism_failures.append(
                        f"{name}: run1={first_signature} run{run_i + 1}={this_signature}"
                    )
            run_i += 1

        if summary is None:
            raise RuntimeError(f"internal error: no summary captured for fixture {name}")
        if bool(args.perf_json) and (not bool(args.skip_mojo)):
            if not summary.mojo_perf_json:
                raise RuntimeError(f"{name}: --perf-json requested but fixture summary has no mojo perf sidecar")
            perf_path = Path(summary.mojo_perf_json)
            if not perf_path.exists():
                raise RuntimeError(f"{name}: perf sidecar missing on disk: {perf_path}")
            if not summary.mojo_phase_times:
                raise RuntimeError(f"{name}: --perf-json requested but fixture summary has empty mojo_phase_times")
        dt = time.perf_counter() - t0

        rows.append(
            SuiteRow(
                fixture=name,
                input_pcb=str(pcb),
                freerouting_ok=bool(summary.freerouting_ok),
                freerouting_violations=int(summary.freerouting_drc.violations),
                freerouting_unconnected=int(summary.freerouting_drc.unconnected),
                freerouting_violations_routing_only=int(summary.freerouting_drc_routing_only.violations),
                freerouting_unconnected_routing_only=int(summary.freerouting_drc_routing_only.unconnected),
                mojo_violations=int(summary.mojo_drc.violations),
                mojo_unconnected=int(summary.mojo_drc.unconnected),
                mojo_violations_routing_only=int(summary.mojo_drc_routing_only.violations),
                mojo_unconnected_routing_only=int(summary.mojo_drc_routing_only.unconnected),
                mojo_failed_nets=int(summary.mojo_failed_nets),
                mojo_route_p50_s=float(summary.timing_s.mojo_route_p50_s),
                mojo_route_p90_s=float(summary.timing_s.mojo_route_p90_s),
                mojo_route_runs=len(summary.timing_s.mojo_route_runs_s),
                runtime_s=float(dt),
            )
        )
        summaries.append(summary)

    gate_failures: list[str] = []
    gate_checks: list[str] = []
    if args.gate_baseline_json is not None:
        baseline = _load_baseline(args.gate_baseline_json.resolve())
        gate_failures, gate_checks = _gate_regressions(
            current=summaries,
            baseline=baseline,
            allow_missing_fixtures=bool(args.gate_allow_missing_fixtures),
        )
    if determinism_failures:
        for msg in determinism_failures:
            gate_failures.append(f"determinism regression: {msg}")
    if bool(args.gate_fr_exact):
        exact_failures, exact_checks = _gate_fr_exact(current=summaries)
        gate_failures.extend(exact_failures)
        gate_checks.extend(exact_checks)
    gate_policy_path: Path
    if args.gate_policy_json is not None:
        gate_policy_path = args.gate_policy_json.resolve()
        if not gate_policy_path.exists():
            raise SystemExit(f"missing gate policy json: {gate_policy_path}")
    else:
        gate_policy_path = (project_root / "tests/fixtures/parity_fixtures" / "parity_gate_policy.json").resolve()
    if gate_policy_path.exists():
        policy_rules = _load_gate_policy(
            path=gate_policy_path,
            workspace_root=workspace_root,
            project_root=project_root,
        )
        policy_failures, policy_checks = _gate_by_policy(
            current=summaries,
            policy_rules=policy_rules,
            project_root=project_root,
        )
        gate_failures.extend(policy_failures)
        gate_checks.extend(policy_checks)

    total_dt = time.perf_counter() - suite_started
    out = {
        "cwd": os.getcwd(),
        "count": len(rows),
        "runtime_s": total_dt,
        "rows": [asdict(r) for r in rows],
        "summaries": [asdict(s) for s in summaries],
        "gate_baseline_json": str(args.gate_baseline_json.resolve()) if args.gate_baseline_json else "",
        "gate_policy_json": str(gate_policy_path) if gate_policy_path.exists() else "",
        "gate_checks": gate_checks,
        "gate_failures": gate_failures,
        "determinism_runs": determinism_runs,
        "determinism_failures": determinism_failures,
        "warm_runs": int(args.warm_runs),
        "perf_mode": str(args.perf_mode),
        "perf_json": bool(args.perf_json),
        "gate_ok": len(gate_failures) == 0,
    }
    (args.out_dir / "suite_summary.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")

    if bool(args.perf_json):
        perf_summary = {
            "rows": [
                {
                    "fixture": s.fixture,
                    "mojo_perf_mode": s.mojo_perf_mode,
                    "mojo_perf_json": s.mojo_perf_json,
                    "mojo_route_p50_s": s.timing_s.mojo_route_p50_s,
                    "mojo_route_p90_s": s.timing_s.mojo_route_p90_s,
                    "mojo_route_runs": len(s.timing_s.mojo_route_runs_s),
                    "phase_times": s.mojo_phase_times,
                    "operation_counts": s.mojo_operation_counts,
                }
                for s in summaries
            ]
        }
        (args.out_dir / "mojo_perf_summary.json").write_text(
            json.dumps(perf_summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if args.write_baseline_json is not None:
        baseline_payload = _build_baseline(summaries=summaries)
        args.write_baseline_json.parent.mkdir(parents=True, exist_ok=True)
        args.write_baseline_json.write_text(
            json.dumps(baseline_payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    skip_diary_update = bool(args.no_update_diary) or bool(os.getenv("CODEX_CI"))
    if summaries and not skip_diary_update:
        diary_path = args.diary_path.resolve() if args.diary_path else (project_root / "PARITY_DIARY.md")
        try:
            append_parity_diary_entry(
                diary_path=diary_path,
                summaries=summaries,
                source="run_parity_suite",
                label=args.diary_label or args.out_dir.name,
                suite_out_dir=args.out_dir,
            )
        except Exception as e:  # noqa: BLE001
            print(f"warning: failed to append diary entry: {type(e).__name__}: {e}")

    # Print a compact table.
    print(
        "\nfixture,fr_ok,fr_v,fr_u,fr_v_ro,fr_u_ro,mojo_v,mojo_u,mojo_v_ro,mojo_u_ro,mojo_failed,mojo_p50_s,mojo_p90_s,mojo_runs,sec"
    )
    for r in rows:
        print(
            f"{r.fixture},{int(r.freerouting_ok)},{r.freerouting_violations},{r.freerouting_unconnected},"
            f"{r.freerouting_violations_routing_only},{r.freerouting_unconnected_routing_only},"
            f"{r.mojo_violations},{r.mojo_unconnected},"
            f"{r.mojo_violations_routing_only},{r.mojo_unconnected_routing_only},"
            f"{r.mojo_failed_nets},{r.mojo_route_p50_s:.2f},{r.mojo_route_p90_s:.2f},{r.mojo_route_runs},{r.runtime_s:.2f}"
        )
    if gate_checks:
        print("\ngate checks:")
        for msg in gate_checks:
            print(f"- {msg}")
    if gate_failures:
        print("\ngate failures:")
        for msg in gate_failures:
            print(f"- {msg}")
    if determinism_failures:
        print("\ndeterminism failures:")
        for msg in determinism_failures:
            print(f"- {msg}")
    print(f"\nwrote {args.out_dir / 'suite_summary.json'}")
    if gate_failures:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
