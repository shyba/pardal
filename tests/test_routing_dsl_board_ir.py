from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from pardal.routing_dsl.board_ir import BoardIRValidationError, load_board_ir


FIXTURE_PATH = Path("tests/fixtures/routing_dsl/board.ir.json")


def test_load_board_ir_fixture_is_deterministic() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    board_ir = load_board_ir(payload)
    board_ir_again = load_board_ir(FIXTURE_PATH)

    assert board_ir == board_ir_again
    assert board_ir.board_ir_id == "board-ir-demo-v001"
    assert board_ir.frozen_board_snapshot_id == "board-snapshot-demo-v001"
    assert board_ir.units == {"length": "mm", "angle": "deg"}
    assert [layer.name for layer in board_ir.stackup] == ["F.Cu", "In1.Cu", "B.Cu"]
    assert [net.name for net in board_ir.nets] == ["GND", "VCC", "SIG_A"]
    assert [component.refdes for component in board_ir.components] == ["U1", "J1"]
    assert {pad.id for pad in board_ir.pads} == {"pad-u1-1", "pad-u1-2", "pad-j1-1"}
    assert {obstacle.id for obstacle in board_ir.obstacles} == {"obs-antenna"}
    assert {envelope.id for envelope in board_ir.envelopes} == {"env-u1", "env-j1"}
    assert board_ir.route_plan_anchor_ids == ["comp-u1", "comp-j1", "pad-u1-1", "pad-j1-1"]


def test_board_ir_to_json_payload_is_stable() -> None:
    board_ir = load_board_ir(FIXTURE_PATH)
    payload = board_ir.to_json_payload()

    assert payload["schema"] == "pardal.board_ir"
    assert payload["version"] == "0.1"
    assert payload["units"] == {"length": "mm", "angle": "deg"}
    assert payload["stackup"][0] == {"id": "layer-fcu", "name": "F.Cu", "kind": "signal", "order": 1}
    assert payload["components"][0]["position"] == {"x": 12.0, "y": 12.0}
    assert payload["pads"][0]["net_id"] == "net-sig"
    assert payload["route_plan_anchor_ids"] == ["comp-u1", "comp-j1", "pad-u1-1", "pad-j1-1"]


@pytest.mark.parametrize(
    ("mutator", "message"),
        [
            (lambda payload: payload.__setitem__("schema", "wrong.schema"), "schema"),
            (lambda payload: payload.__setitem__("version", "0.2"), "version"),
            (lambda payload: payload.pop("board_ir_id"), "board_ir_id"),
            (
                lambda payload: payload["stackup"].append(
                    {"id": "layer-fcu", "name": "Inner.Dup", "kind": "signal", "order": 4}
                ),
                "duplicate",
            ),
        (
            lambda payload: payload["pads"][0].__setitem__("layer", "Inner.Cu"),
            "unknown layer",
        ),
        (
            lambda payload: payload["pads"][1].__setitem__("net_id", "net-missing"),
            "unknown net",
        ),
        (
            lambda payload: payload["envelopes"][0].__setitem__("ref_id", "missing-id"),
            "unknown object",
        ),
        (
            lambda payload: payload["outline"][0].__setitem__("x", float("inf")),
            "finite",
        ),
    ],
)
def test_load_board_ir_rejects_malformed_geometry(
    mutator,
    message: str,
) -> None:
    payload = copy.deepcopy(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
    mutator(payload)

    with pytest.raises(BoardIRValidationError, match=message):
        load_board_ir(payload)


def test_load_board_ir_requires_required_fields() -> None:
    payload = copy.deepcopy(json.loads(FIXTURE_PATH.read_text(encoding="utf-8")))
    del payload["components"]

    with pytest.raises(BoardIRValidationError, match="components"):
        load_board_ir(payload)
