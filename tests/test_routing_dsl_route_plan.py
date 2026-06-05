from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from pardal.routing_dsl.board_ir import load_board_ir
from pardal.routing_dsl.route_plan import (
    RoutePlanResolutionError,
    normalize_route_plan_payload,
    resolve_route_plan,
    route_plan_hash_payload,
)
from pardal.routing_dsl.source import load_routes_source


FIXTURES = Path(__file__).parent / "fixtures" / "routing_dsl"


def _source() -> object:
    return load_routes_source(FIXTURES / "route-plan-source.pdl.yaml")


def _board() -> object:
    return load_board_ir(FIXTURES / "board.ir.json")


def test_resolve_route_plan_is_deterministic() -> None:
    plan = resolve_route_plan(_source(), _board())
    repeat = resolve_route_plan(_source(), _board())

    assert plan == repeat
    assert plan["schema"] == "pardal.route_plan"
    assert plan["version"] == "0.1"
    assert plan["board_ir_id"] == "board-ir-demo-v001"
    assert plan["frozen_board_snapshot_id"] == "board-snapshot-demo-v001"
    assert plan["route_plan_id"] == "route-plan-" + str(plan["route_plan_hash"]).removeprefix("sha256:")[:8]
    assert plan["route_plan_id"].startswith("route-plan-")
    assert plan["route_plan_hash"]
    assert str(plan["route_plan_hash"]).startswith("sha256:")

    groups = plan["route_groups"]
    assert [group["route_group_id"] for group in groups] == ["rg_route_u1_to_j1", "rg_route_bus"]
    first = groups[0]
    assert first["source_route_group_name"] == "route_u1_to_j1"
    assert first["select"]["nets"] == [{"id": "net-sig", "name": "SIG_A"}]
    assert first["select"]["endpoints"][0]["pads"][0]["id"] == "pad-u1-1"
    assert first["scope"]["allowed_layers"][0]["name"] == "F.Cu"
    assert first["scope"]["corridors"][0]["id"] == "obs-antenna"
    assert first["placement_moves"][0]["envelope"]["dx"] == (-1.0, 1.0)
    assert first["variables"][0]["name"] == "fanout_side"
    assert first["candidates"][0]["candidate_index"] == 0
    assert first["candidates"][0]["assignment_hash"]
    assert first["assignment_hash"]


def test_route_plan_payload_round_trips_and_rehashes() -> None:
    plan = resolve_route_plan(_source(), _board())
    normalized = normalize_route_plan_payload(plan)
    round_tripped = normalize_route_plan_payload(json.loads(json.dumps(plan, sort_keys=True)))

    assert normalized == round_tripped
    assert normalized["route_plan_id"] == plan["route_plan_id"]
    assert normalized["route_plan_hash"] == plan["route_plan_hash"]
    assert route_plan_hash_payload(plan) == route_plan_hash_payload(normalized)
    assert normalized["route_groups"][0]["placement_moves"][0]["envelope"]["dx"] == [-1.0, 1.0]
    assert normalized["source"]["path"].endswith("route-plan-source.pdl.yaml")


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda source: replace(source, board_ir_id="other-board"), "board_ir_id"),
        (
            lambda source: replace(source, frozen_board_snapshot_id="other-snapshot"),
            "frozen_board_snapshot_id",
        ),
        (
            lambda source: replace(
                source,
                route_groups=(
                    replace(source.route_groups[0], select_nets=("NET_MISSING",)),
                    source.route_groups[1],
                ),
            ),
            "unknown net",
        ),
        (
            lambda source: replace(
                source,
                route_groups=(
                    replace(
                        source.route_groups[0],
                        select_endpoints=(("U1", ("99",)),),
                    ),
                    source.route_groups[1],
                ),
            ),
            "unknown pad",
        ),
        (
            lambda source: replace(
                source,
                route_groups=(
                    replace(
                        source.route_groups[0],
                        allowed_layers=("F.Cu", "Inner.Cu"),
                    ),
                    source.route_groups[1],
                ),
            ),
            "unknown layer",
        ),
        (
            lambda source: replace(
                source,
                route_groups=(
                    replace(
                        source.route_groups[0],
                        corridors=(replace(source.route_groups[0].corridors[0], id="missing-obstacle"),),
                    ),
                    source.route_groups[1],
                ),
            ),
            "unknown obstacle",
        ),
    ],
)
def test_resolve_route_plan_rejects_invalid_references(mutator, message: str) -> None:
    source = mutator(_source())
    with pytest.raises(RoutePlanResolutionError, match=message):
        resolve_route_plan(source, _board())


def test_resolve_route_plan_rejects_candidate_cap_overflow() -> None:
    source = _source()
    group = source.route_groups[0]
    expanded = replace(
        group,
        variables=(
            replace(group.variables[0], values=("west", "south", "east")),
            replace(group.variables[1], values=(1, 2, 3)),
        ),
    )
    source = replace(source, route_groups=(expanded, source.route_groups[1]))

    with pytest.raises(RoutePlanResolutionError, match="candidate count exceeds cap"):
        resolve_route_plan(source, _board())


def test_resolve_route_plan_rejects_duplicate_output_ids() -> None:
    source = _source()
    duplicated = replace(source, route_groups=(source.route_groups[0], source.route_groups[0]))

    with pytest.raises(RoutePlanResolutionError, match="duplicate route plan output id"):
        resolve_route_plan(duplicated, _board())
