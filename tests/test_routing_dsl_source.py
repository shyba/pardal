from pathlib import Path

import pytest

from pardal.routing_dsl import RoutingSourceParseError, load_routes_source
from pardal.routing_dsl.source import load_routes_source as load_routes_source_module


def _fixture(path: str) -> Path:
    return Path(__file__).parent / "fixtures" / "routing_dsl" / path


def test_parse_routing_source_positive_fixture() -> None:
    source = load_routes_source(_fixture("positive_routes.pdl.yaml"))
    assert source.schema == "pardal.routes"
    assert source.version == "0.1"
    assert source.board_ir_id == "dspic-dev-board-ir-v001"
    assert source.frozen_board_snapshot_id == "dspic-dev-board-snapshot-v001"
    assert source.defaults.units.length == "mm"
    assert source.defaults.search.max_candidates == 512
    assert len(source.route_groups) == 2

    first = source.route_groups[0]
    assert first.id == "rg_fpc_escape_a"
    assert first.source is not None
    assert isinstance(first.source.display(), str)
    assert first.select_nets == ("MCU_IO_01", "MCU_IO_02")
    assert first.select_endpoints == (("U1", ("A1", "B1")), ("J1", ("1", "2")))
    assert first.corridors and first.corridors[0].id == "fpc_lane_west"
    assert first.keepouts and first.keepouts[0].id == "antenna_keepout"
    assert len(first.variables) == 2
    assert first.variables[0].name == "lane_order"
    assert first.placement_moves and first.placement_moves[0].ref == "J1"
    assert first.placement_moves[0].envelope.dx == (-1.0, 1.0)
    assert first.replacement is not None

    second = source.route_groups[1]
    assert second.id == "rg_bus_escapes"
    assert second.allowed_layers == ("F.Cu", "B.Cu")


def test_routing_source_to_json_payload_is_stable() -> None:
    source = load_routes_source_module(_fixture("positive_routes.pdl.yaml"))
    payload = source.to_json_payload()

    assert payload["schema"] == "pardal.routes"
    assert payload["board"] == {
        "board_ir_id": "dspic-dev-board-ir-v001",
        "frozen_board_snapshot_id": "dspic-dev-board-snapshot-v001",
    }
    assert payload["defaults"]["search"]["max_candidates"] == 512
    assert payload["route_groups"][0]["scope"]["corridors"][0] == {"id": "fpc_lane_west", "mode": "hard"}
    assert payload["route_groups"][0]["placement_moves"][0]["envelope"]["dx"] == [-1.0, 1.0]
    assert "source" not in payload["route_groups"][0]


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("missing_schema.pdl.yaml", "schema is required"),
        ("wrong_schema.pdl.yaml", "unexpected schema"),
        ("missing_version.pdl.yaml", "version is required"),
        ("missing_board_snapshot.pdl.yaml", "board.frozen_board_snapshot_id is required"),
        ("missing_route_group_id.pdl.yaml", "missing route-group id"),
        ("unbounded_variable_range.pdl.yaml", "unbounded variable domain"),
        ("missing_replacement_mode.pdl.yaml", "replacement requires explicit mode"),
        ("nonfinite_placement_envelope.pdl.yaml", "must include units"),
    ],
)
def test_parse_routing_source_rejects_invalid_sources(fixture: str, message: str) -> None:
    with pytest.raises(RoutingSourceParseError, match=message):
        load_routes_source(_fixture(fixture))
