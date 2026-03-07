from __future__ import annotations

from pathlib import Path

from pcb_tool.tools.run_parity_fixture import (
    DrcStats,
    FixtureSummary,
    IrStats,
    TimingStats,
    append_parity_diary_entry,
)


def _mk_summary(*, fixture: str, mojo_v: int, mojo_u: int, mojo_ro_v: int, mojo_ro_u: int) -> FixtureSummary:
    return FixtureSummary(
        fixture=fixture,
        input_pcb="in.kicad_pcb",
        kicad_raw_dsn="kicad_raw.dsn",
        kicad_dsn="kicad.dsn",
        kicad_dsn_dump_json="kicad.dump.json",
        kicad_dsn_dump_ok=True,
        kicad_dsn_dump_error="",
        kicad_dsn_ir_json="kicad.ir.json",
        kicad_dsn_ir_ok=True,
        kicad_dsn_ir_error="",
        freerouting_out_pcb="fr.kicad_pcb",
        mojo_out_pcb="mojo.kicad_pcb",
        freerouting_drc=DrcStats(violations=0, unconnected=0),
        mojo_drc=DrcStats(violations=mojo_v, unconnected=mojo_u),
        freerouting_drc_routing_only=DrcStats(violations=0, unconnected=0),
        mojo_drc_routing_only=DrcStats(violations=mojo_ro_v, unconnected=mojo_ro_u),
        delta_drc_violations=0,
        delta_drc_unconnected=0,
        delta_drc_violations_routing_only=0,
        delta_drc_unconnected_routing_only=0,
        mojo_failed_nets=0,
        mojo_tracks=10,
        mojo_vias=2,
        routes_json="routes.json",
        problem_json="problem.json",
        freerouting_ok=True,
        freerouting_error="",
        mojo_ok=True,
        mojo_error="",
        freerouting_raw_dsn="fr_raw.dsn",
        freerouting_dsn="fr.dsn",
        freerouting_ses="fr.ses",
        freerouting_log_file="fr.log",
        freerouting_stdout_log="fr.stdout.log",
        freerouting_stderr_log="fr.stderr.log",
        freerouting_trace_jsonl="fr.trace.jsonl",
        freerouting_trace_ok=True,
        freerouting_trace_error="",
        freerouting_dsn_dump_json="fr.dump.json",
        freerouting_dsn_dump_ok=True,
        freerouting_dsn_dump_error="",
        freerouting_dsn_ir_json="fr.ir.json",
        freerouting_dsn_ir_ok=True,
        freerouting_dsn_ir_error="",
        kicad_ir_stats=IrStats(bbox_w_mm=1.0, bbox_h_mm=1.0, pins=1, wires=1, vias=1),
        freerouting_ir_stats=IrStats(bbox_w_mm=1.0, bbox_h_mm=1.0, pins=1, wires=1, vias=1),
        delta_ir_wires=0,
        delta_ir_vias=0,
        delta_ir_pins=0,
        timing_s=TimingStats(
            kicad_export_dsn_s=0.1,
            freerouting_route_s=0.1,
            mojo_backend_route_s=0.1,
            kicad_drc_freerouting_s=0.1,
            kicad_drc_mojo_s=0.1,
        ),
        mojo_violation_types={"clearance": max(0, mojo_v), "shorting_items": 1 if mojo_v else 0},
        freerouting_violation_types={},
    )


def test_append_parity_diary_entry_creates_and_appends(tmp_path: Path) -> None:
    diary = tmp_path / "PARITY_DIARY.md"
    summaries = [_mk_summary(fixture="issue180", mojo_v=0, mojo_u=0, mojo_ro_v=0, mojo_ro_u=0)]

    append_parity_diary_entry(
        diary_path=diary,
        summaries=summaries,
        source="run_parity_fixture",
        label="issue180_regcheck",
        suite_out_dir=tmp_path / "out",
    )

    text = diary.read_text(encoding="utf-8")
    assert "# FreeRouting Parity Diary" in text
    assert "run_parity_fixture: issue180_regcheck" in text
    assert "`issue180`" in text
    assert "routing-only 0/0" in text
    assert "routing-only clean fixtures: Mojo 1/1, FR 1/1" in text
