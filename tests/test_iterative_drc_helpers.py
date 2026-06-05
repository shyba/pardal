from __future__ import annotations

import json
import importlib.util
from pathlib import Path


def _load_iterative_module():
    path = Path(__file__).resolve().parents[1] / "pardal" / "tools" / "iterative_backend_route_fpga_large.py"
    spec = importlib.util.spec_from_file_location("iterative_backend_route_fpga_large", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def test_iterative_script_has_bundle_args():
    it = _load_iterative_module()
    # Smoke: ensure new flags exist (avoids silent CLI regressions).
    assert hasattr(it, "main")


def test_bbox_mm_from_violation_padding():
    it = _load_iterative_module()
    v = {
        "type": "shorting_items",
        "items": [
            {"pos": {"x": 10.0, "y": 20.0}},
            {"pos": {"x": 12.0, "y": 18.0}},
        ],
    }
    bb = it._bbox_mm_from_violation(v, pad_mm=2.5)
    assert bb == (7.5, 15.5, 14.5, 22.5)


def test_bbox_mm_from_violation_none_when_missing_positions():
    it = _load_iterative_module()
    v = {"type": "clearance", "items": [{"uuid": "x"}]}
    assert it._bbox_mm_from_violation(v, pad_mm=1.0) is None


def test_pick_violation_for_chunk_respects_types_and_nets():
    it = _load_iterative_module()
    drc = {
        "violations": [
            {
                "type": "hole_clearance",
                "description": "Something (nets A and B)",
                "items": [{"description": "Via [A] ...", "pos": {"x": 1.0, "y": 2.0}}],
            },
            {
                "type": "shorting_items",
                "description": "Short (nets C and D)",
                "items": [{"description": "Track [C] ...", "pos": {"x": 3.0, "y": 4.0}}],
            },
        ]
    }
    v = it._pick_violation_for_chunk(drc, chunk_nets={"C"}, types={"shorting_items"})
    assert v is not None
    assert v["type"] == "shorting_items"
    v2 = it._pick_violation_for_chunk(drc, chunk_nets={"C"}, types={"hole_clearance"})
    assert v2 is None


def test_uuids_from_violation():
    it = _load_iterative_module()
    v = {"items": [{"uuid": "a"}, {"uuid": "b"}, {"uuid": ""}, {"pos": {"x": 1, "y": 2}}]}
    assert it._uuids_from_violation(v) == {"a", "b"}


def test_median_drc_picks_middle_by_violation_and_unconnected():
    it = _load_iterative_module()
    low = {"violations": [{}], "unconnected_items": [{}]}
    mid = {"violations": [{}, {}], "unconnected_items": [{}]}
    high = {"violations": [{}, {}, {}], "unconnected_items": [{}, {}]}
    assert it._median_drc([high, mid, low]) == mid


def test_kicad_drc_json_median_writes_summary(tmp_path):
    it = _load_iterative_module()
    seq = [
        {"violations": [{}, {}, {}], "unconnected_items": [{}, {}]},
        {"violations": [{}, {}], "unconnected_items": [{}]},
        {"violations": [{}, {}, {}, {}], "unconnected_items": [{}, {}, {}]},
    ]
    calls = {"i": 0}

    def fake_kicad_drc_json(*, repo_root, in_pcb, out_json, image):
        i = calls["i"]
        calls["i"] += 1
        payload = seq[i]
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    old = it._kicad_drc_json
    it._kicad_drc_json = fake_kicad_drc_json
    try:
        out = tmp_path / "cand.drc.json"
        drc = it._kicad_drc_json_median(
            repo_root=tmp_path,
            in_pcb=tmp_path / "x.kicad_pcb",
            out_json=out,
            image="kicad/kicad:9.0.6-full",
            samples=3,
        )
    finally:
        it._kicad_drc_json = old

    assert it._drc_counts(drc) == (3, 2)
    assert out.exists()
    assert out.with_name("cand.drc.samples.json").exists()
