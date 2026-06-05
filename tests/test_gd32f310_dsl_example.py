from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

from pardal.routing_dsl.board_ir import load_board_ir
from pardal.routing_dsl.board_ir_producer import produce_board_ir
from pardal.routing_dsl.route_plan import resolve_route_plan
from pardal.routing_dsl.source import parse_routes_source


EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "gd32f310_dsl"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gd32f310_dsl_generate", EXAMPLE_DIR / "generate.py")
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_gd32f310_source_manifest_covers_package_pins_and_adc_channels() -> None:
    generator = _load_generator()
    manifest = generator._source_manifest()

    assert manifest["part"] == "GD32F310C8T6"
    assert manifest["package"] == "LQFP48"
    assert manifest["coverage"]["package_pin_count"] == 48
    assert manifest["coverage"]["represented_pin_count"] == 48
    assert manifest["coverage"]["adc_pin_count"] == 10
    assert manifest["coverage"]["adc_filter_count"] == 10
    assert manifest["coverage"]["production_part_count"] == 27
    assert manifest["coverage"]["adc_channels"] == {
        "PA0": "ADC_IN0",
        "PA1": "ADC_IN1",
        "PA2": "ADC_IN2",
        "PA3": "ADC_IN3",
        "PA4": "ADC_IN4",
        "PA5": "ADC_IN5",
        "PA6": "ADC_IN6",
        "PA7": "ADC_IN7",
        "PB0": "ADC_IN8",
        "PB1": "ADC_IN9",
    }
    assert manifest["board"]["width_mm"] == 100.0
    assert manifest["board"]["height_mm"] == 100.0
    assert manifest["board"]["copper_layers"] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert manifest["power"]["rails"] == ["12V_IN", "12V_PROT", "3V3", "GND"]
    assert manifest["jlc_parts"]["GD32F310C8T6"] == "C3009902"
    assert manifest["jlc_parts"]["AMS1117_3V3_SOT89"] == "C5120796"
    assert len(manifest["adc_filters"]) == 10


def test_gd32f310_board_source_and_routes_are_fresh() -> None:
    generator = _load_generator()
    board_source = generator._board_source()
    board_result = produce_board_ir(board_source)
    board = load_board_ir(board_result.payload)
    routes = parse_routes_source(generator._routes_source(board_source))
    route_plan = resolve_route_plan(routes, board)

    assert board.board_ir_id == "gd32f310c8t6-lqfp48-breakout-v001"
    assert board.bounds == {"min_x": 0.0, "min_y": 0.0, "max_x": 100.0, "max_y": 100.0}
    assert [layer.name for layer in board.stackup] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert len(board.components) == 49
    assert len(board.pads) == 96
    assert routes.frozen_board_snapshot_id == board.frozen_board_snapshot_id
    assert len(routes.route_groups) == 48
    assert len(route_plan["route_groups"]) == 48


def test_gd32f310_physical_spec_declares_fab_smoke_contract() -> None:
    spec = yaml.safe_load((EXAMPLE_DIR / "board.pdl.yaml").read_text(encoding="utf-8"))

    assert spec["board"]["width"] == "100mm"
    assert spec["board"]["height"] == "100mm"
    assert spec["board"]["copper_layers"] == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    assert spec["rules"]["default_clearance"] == "0.10mm"
    assert spec["dfm"]["lcsc_database"]["strict"] is True
    assert spec["dfm"]["profile"] == "jlcpcb_4_layer_smt"
    assert spec["dfm"]["required_artifacts"] == [
        "gd32f310c8t6.jlc.bom.csv",
        "gd32f310c8t6.jlc.pnp.csv",
    ]
    assert len(spec["parts"]) == 37
    assert spec["parts"]["J12V"]["footprint"].startswith("TerminalBlock_Phoenix:")
    assert spec["parts"]["U2"]["footprint"] == "Package_TO_SOT_SMD:SOT-89-3"
    assert spec["validation_tests"][0]["net"] == "ADC0_FILT"


def test_gd32f310_atopile_source_has_modular_component_groups() -> None:
    generator = _load_generator()
    source = generator._ato_source()

    assert "module GD32F310Core:" in source
    assert "module AdcInputFilter:" in source
    assert "module AdcFilterBank:" in source
    assert "module TwelveVoltSupply:" in source
    assert "module JlcCatalogParts:" in source
    assert "module GD32F310C8T6Breakout:" in source
    assert "ADC_IN9" in source
    assert "C3009902" in source
