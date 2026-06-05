from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pardal.routing_dsl.board_ir import load_board_ir
from pardal.routing_dsl.board_ir_producer import BoardIRProducerError, produce_board_ir


FIXTURE_PATH = Path("tests/fixtures/routing_dsl/board_ir_source.json")


def test_produce_board_ir_writes_deterministic_payload(tmp_path: Path) -> None:
    source = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    source_before = copy.deepcopy(source)
    output_path = tmp_path / "board.ir.json"

    result = produce_board_ir(source, output_path)
    again = produce_board_ir(source)

    assert source == source_before
    assert result.path == output_path
    assert output_path.exists()
    assert result.payload == again.payload
    assert result.payload["schema"] == "pardal.board_ir"
    assert result.payload["version"] == "0.1"
    assert result.payload["board_ir_id"] == "board-ir-demo-v001"
    assert result.payload["frozen_board_snapshot_id"].startswith("board-ir-demo-v001-snapshot-sha256:")
    assert result.payload["provenance"]["producer"]["schema"] == "pardal.board_ir_source"
    assert result.payload["provenance"]["producer"]["version"] == "0.1"

    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert load_board_ir(written) == load_board_ir(result.payload)
    assert load_board_ir(output_path) == load_board_ir(result.payload)


def test_produce_board_ir_snapshot_changes_with_geometry(tmp_path: Path) -> None:
    source = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    altered = copy.deepcopy(source)
    altered["components"][0]["position"]["x"] = 12.5

    original = produce_board_ir(source).payload
    changed = produce_board_ir(altered).payload

    assert original["frozen_board_snapshot_id"] != changed["frozen_board_snapshot_id"]
    assert original["provenance"]["producer"]["snapshot_hash"] != changed["provenance"]["producer"]["snapshot_hash"]


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload["pads"][0].__setitem__("net_id", "net-missing"), "unknown net"),
        (lambda payload: payload["pads"][0].__setitem__("layer", "Inner.Cu"), "unknown layer"),
        (lambda payload: payload["envelopes"][0].__setitem__("ref_id", "missing-id"), "unknown object"),
        (lambda payload: payload["stackup"].append({"id": "layer-fcu", "name": "Alt", "kind": "signal", "order": 4}), "duplicate stable id"),
        (lambda payload: payload["obstacles"][0]["shape"].__setitem__("type", "circle"), "unsupported obstacle shape"),
        (lambda payload: payload["outline"][0].__setitem__("x", float("inf")), "finite"),
        (lambda payload: payload.pop("bounds"), "bounds"),
        (lambda payload: payload["components"][0].pop("position"), "position"),
    ],
)
def test_produce_board_ir_rejects_bad_source(
    mutator,
    message: str,
) -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    mutator(payload)

    with pytest.raises(BoardIRProducerError, match=message):
        produce_board_ir(payload)
