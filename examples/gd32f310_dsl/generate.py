#!/usr/bin/env python3
"""Generate the GD32F310C8T6 routing DSL example artifacts."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BOARD_ID = "gd32f310c8t6-lqfp48-breakout-v001"
LAYERS = [
    ("layer-fcu", "F.Cu", "signal"),
    ("layer-in1", "In1.Cu", "plane"),
    ("layer-in2", "In2.Cu", "plane"),
    ("layer-bcu", "B.Cu", "signal"),
]


PIN_ROWS = [
    (1, "VBAT", "power", ""),
    (2, "PC13", "gpio", "RTC_TAMP0, RTC_TS, RTC_OUT, WKUP1"),
    (3, "PC14", "gpio", "OSC32IN"),
    (4, "PC15", "gpio", "OSC32OUT"),
    (5, "PF0", "gpio", "OSCIN, CTC_SYNC"),
    (6, "PF1", "gpio", "OSCOUT"),
    (7, "NRST", "reset", ""),
    (8, "VSSA", "power", ""),
    (9, "VDDA", "power", ""),
    (10, "PA0", "gpio", "ADC_IN0, USART1_CTS, I2C1_SCL, RTC_TAMP1, WKUP0"),
    (11, "PA1", "gpio", "ADC_IN1, USART1_RTS, I2C1_SDA, EVENTOUT"),
    (12, "PA2", "gpio", "ADC_IN2, USART1_TX, TIMER14_CH0"),
    (13, "PA3", "gpio", "ADC_IN3, USART1_RX, TIMER14_CH1"),
    (14, "PA4", "gpio", "ADC_IN4, SPI0_NSS, I2S0_WS, USART1_CK, TIMER13_CH0, SPI1_NSS"),
    (15, "PA5", "gpio", "ADC_IN5, SPI0_SCK, I2S0_CK"),
    (16, "PA6", "gpio", "ADC_IN6, SPI0_MISO, I2S0_MCK, TIMER2_CH0, TIMER0_BRKIN, TIMER15_CH0, EVENTOUT"),
    (17, "PA7", "gpio", "ADC_IN7, SPI0_MOSI, I2S0_SD, TIMER2_CH1, TIMER13_CH0, TIMER0_CH0_ON, TIMER16_CH0, EVENTOUT"),
    (18, "PB0", "gpio", "ADC_IN8, TIMER2_CH2, TIMER0_CH1_ON, USART1_RX, EVENTOUT"),
    (19, "PB1", "gpio", "ADC_IN9, TIMER2_CH3, TIMER13_CH0, TIMER0_CH2_ON, SPI1_SCK"),
    (20, "PB2", "gpio", ""),
    (21, "PB10", "gpio", "I2C1_SCL, SPI1_IO2"),
    (22, "PB11", "gpio", "I2C1_SDA, EVENTOUT, SPI1_IO3"),
    (23, "VSS", "power", ""),
    (24, "VDD", "power", ""),
    (25, "PB12", "gpio", "SPI1_NSS, TIMER0_BRKIN, I2C1_SMBA, EVENTOUT"),
    (26, "PB13", "gpio", "SPI1_SCK, TIMER0_CH0_ON"),
    (27, "PB14", "gpio", "SPI1_MISO, TIMER0_CH1_ON, TIMER14_CH0"),
    (28, "PB15", "gpio", "SPI1_MOSI, TIMER0_CH2_ON, TIMER14_CH0_ON, TIMER14_CH1, RTC_REFIN, WKUP6"),
    (29, "PA8", "gpio", "USART0_CK, TIMER0_CH0, CK_OUT, USART1_TX, EVENTOUT, CTC_SYNC"),
    (30, "PA9", "gpio", "USART0_TX, TIMER0_CH1, TIMER14_BRKIN, I2C0_SCL"),
    (31, "PA10", "gpio", "USART0_RX, TIMER0_CH2, TIMER16_BRKIN, I2C0_SDA"),
    (32, "PA11", "gpio", "USART0_CTS, TIMER0_CH3, EVENTOUT, SPI1_IO2"),
    (33, "PA12", "gpio", "USART0_RTS, TIMER0_ETI, EVENTOUT, SPI1_IO3"),
    (34, "PA13", "gpio", "IFRP_OUT, SWDIO, SPI1_MISO"),
    (35, "PF6", "gpio", "I2C1_SCL"),
    (36, "PF7", "gpio", "I2C1_SDA"),
    (37, "PA14", "gpio", "USART1_TX, SWCLK, SPI1_MOSI"),
    (38, "PA15", "gpio", "SPI0_NSS, I2S0_WS, USART1_RX, SPI1_NSS, EVENTOUT"),
    (39, "PB3", "gpio", "SPI0_SCK, I2S0_CK, EVENTOUT"),
    (40, "PB4", "gpio", "SPI0_MISO, I2S0_MCK, TIMER2_CH0, EVENTOUT"),
    (41, "PB5", "gpio", "SPI0_MOSI, I2S0_SD, I2C0_SMBA, TIMER15_BRKIN, TIMER2_CH1, WKUP5"),
    (42, "PB6", "gpio", "I2C0_SCL, USART0_TX, TIMER15_CH0_ON"),
    (43, "PB7", "gpio", "I2C0_SDA, USART0_RX, TIMER16_CH0_ON"),
    (44, "BOOT0", "boot", ""),
    (45, "PB8", "gpio", "I2C0_SCL, TIMER15_CH0"),
    (46, "PB9", "gpio", "I2C0_SDA, IFRP_OUT, TIMER16_CH0, EVENTOUT, I2S0_MCK"),
    (47, "VSS", "power", ""),
    (48, "VDD", "power", ""),
]


ADC_PINS = {
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


JLC_PARTS = {
    "GD32F310C8T6": "C3009902",
    "AMS1117_3V3_SOT89": "C5120796",
    "SS14_SMA": "C7420316",
    "R_1K_0603": "C21190",
    "R_3K3_0603": "C22978",
    "C_100NF_0603": "C14663",
    "C_1UF_0603": "C15849",
    "C_10UF_0805": "C15850",
    "J_2P_5_08": "C8465",
}


ADC_FILTERS = [
    {
        "channel": channel,
        "pin": pin,
        "mcu_net": f"ADC{idx}_FILT",
        "input_net": f"ADC{idx}_IN",
        "input_ref": f"TPADC{idx}",
        "res_ref": f"RAD{idx}",
        "cap_ref": f"CAD{idx}",
        "mcu_pad": name,
    }
    for idx, (name, channel) in enumerate(ADC_PINS.items())
    for pin, pin_name, _kind, _functions in PIN_ROWS
    if pin_name == name
]


def _pin_position(pin: int) -> tuple[float, float]:
    pitch = 0.5
    half = 11 * pitch / 2
    if 1 <= pin <= 12:
        return (50.0 - half + (pin - 1) * pitch, 56.0)
    if 13 <= pin <= 24:
        return (56.0, 50.0 - half + (pin - 13) * pitch)
    if 25 <= pin <= 36:
        return (50.0 + half - (pin - 25) * pitch, 44.0)
    return (44.0, 50.0 + half - (pin - 37) * pitch)


def _header_position(pin: int) -> tuple[float, float]:
    pitch = 4.0
    if 1 <= pin <= 12:
        return (10.0, 28.0 + (pin - 1) * pitch)
    if 13 <= pin <= 24:
        return (28.0 + (pin - 13) * pitch, 90.0)
    if 25 <= pin <= 36:
        return (90.0, 72.0 - (pin - 25) * pitch)
    return (72.0 - (pin - 37) * pitch, 10.0)


def _physical_pad_position(pin: int) -> tuple[float, float]:
    pitch = 0.5
    if 1 <= pin <= 12:
        return (45.8375, 47.25 + (pin - 1) * pitch)
    if 13 <= pin <= 24:
        return (47.25 + (pin - 13) * pitch, 54.1625)
    if 25 <= pin <= 36:
        return (54.1625, 52.75 - (pin - 25) * pitch)
    return (52.75 - (pin - 37) * pitch, 45.8375)


def _route_points(pin: int) -> list[tuple[float, float]]:
    pad_x, pad_y = _physical_pad_position(pin)
    header_x, header_y = _header_position(pin)
    lane_step = 0.5
    if 1 <= pin <= 12:
        lane_x = 34.0 + (pin - 1) * lane_step
        return [(lane_x, pad_y), (lane_x, header_y), (header_x, header_y)]
    if 13 <= pin <= 24:
        lane_y = 60.5 + (pin - 13) * lane_step
        return [(pad_x, lane_y), (header_x, lane_y), (header_x, header_y)]
    if 25 <= pin <= 36:
        lane_x = 66.0 - (pin - 25) * lane_step
        return [(lane_x, pad_y), (lane_x, header_y), (header_x, header_y)]
    lane_y = 39.5 - (pin - 37) * lane_step
    return [(pad_x, lane_y), (header_x, lane_y), (header_x, header_y)]


def _pin_net(pin: int, name: str) -> str:
    if name in {"VDD", "VDDA", "VBAT"}:
        return "3V3"
    if name in {"VSS", "VSSA"}:
        return "GND"
    if name in ADC_PINS:
        idx = list(ADC_PINS).index(name)
        return f"ADC{idx}_FILT"
    return f"PIN_{pin:02d}_{name}"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _board_source_hash_payload(payload: dict[str, object]) -> dict[str, object]:
    return {
        "board_ir_id": payload["board_ir_id"],
        "units": payload["units"],
        "outline": payload["outline"],
        "bounds": payload["bounds"],
        "stackup": payload["stackup"],
        "nets": payload["nets"],
        "components": payload["components"],
        "pads": payload["pads"],
        "obstacles": payload["obstacles"],
        "envelopes": payload["envelopes"],
        "route_plan_anchor_ids": payload["route_plan_anchor_ids"],
    }


def _board_source() -> dict[str, object]:
    nets = [{"id": "net-gnd", "name": "GND"}, {"id": "net-3v3", "name": "3V3"}]
    components = [
        {
            "id": "comp-u1",
            "refdes": "U1",
            "footprint": "Package_QFP:LQFP-48_7x7mm_P0.5mm",
            "layer": "F.Cu",
            "position": {"x": 50.0, "y": 50.0},
            "rotation": 0.0,
        }
    ]
    pads = []
    route_plan_anchor_ids = ["comp-u1"]

    for pin, name, kind, _functions in PIN_ROWS:
        net = _pin_net(pin, name)
        if net not in {"GND", "3V3"}:
            nets.append({"id": f"net-pin-{pin:02d}", "name": net})
        header_ref = f"J{pin:02d}"
        header_id = f"comp-j{pin:02d}"
        x, y = _header_position(pin)
        components.append(
            {
                "id": header_id,
                "refdes": header_ref,
                "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical",
                "layer": "F.Cu",
                "position": {"x": x, "y": y},
                "rotation": 0.0,
            }
        )
        net_id = "net-gnd" if net == "GND" else "net-3v3" if net == "3V3" else f"net-pin-{pin:02d}"
        ux, uy = _pin_position(pin)
        pads.append(
            {
                "id": f"pad-u1-{pin}",
                "component_id": "comp-u1",
                "net_id": net_id,
                "layer": "F.Cu",
                "kind": "smd" if kind != "power" else "smd",
                "position": {"x": ux, "y": uy},
            }
        )
        pads.append(
            {
                "id": f"pad-j{pin:02d}-1",
                "component_id": header_id,
                "net_id": net_id,
                "layer": "F.Cu",
                "kind": "thru_hole",
                "position": {"x": x, "y": y},
            }
        )
        route_plan_anchor_ids.extend([header_id, f"pad-u1-{pin}", f"pad-j{pin:02d}-1"])

    payload = {
        "schema": "pardal.board_ir_source",
        "version": "0.1",
        "board_ir_id": BOARD_ID,
        "units": {"length": "mm", "angle": "deg"},
        "outline": [{"x": 0.0, "y": 0.0}, {"x": 100.0, "y": 0.0}, {"x": 100.0, "y": 100.0}, {"x": 0.0, "y": 100.0}],
        "bounds": {"min_x": 0.0, "min_y": 0.0, "max_x": 100.0, "max_y": 100.0},
        "stackup": [
            {"id": layer_id, "name": name, "kind": kind, "order": idx + 1}
            for idx, (layer_id, name, kind) in enumerate(LAYERS)
        ],
        "nets": nets,
        "components": components,
        "pads": pads,
        "obstacles": [
            {
                "id": "obs-mcu-courtyard",
                "kind": "courtyard",
                "layer": "F.Cu",
                "shape": {"type": "rect", "x": 43.0, "y": 43.0, "width": 14.0, "height": 14.0},
            }
        ],
        "envelopes": [
            {
                "id": "env-u1",
                "kind": "placement",
                "ref_id": "comp-u1",
                "layer": "F.Cu",
                "shape": {"type": "rect", "x": 42.0, "y": 42.0, "width": 16.0, "height": 16.0},
            }
        ],
        "provenance": {
            "source": "examples/gd32f310_dsl/generate.py",
            "datasheet": "GigaDevice GD32F310xx Datasheet Rev2.2, Table 2-4 GD32F310Cx LQFP48 pin definitions",
            "part": "GD32F310C8T6",
            "package": "LQFP48",
            "adc_channels": ADC_PINS,
        },
        "route_plan_anchor_ids": route_plan_anchor_ids,
    }
    return payload


def _routes_source(board_source: dict[str, object]) -> str:
    snapshot = "gd32f310c8t6-lqfp48-breakout-v001-snapshot-sha256:" + sha256(
        json.dumps(_board_source_hash_payload(board_source), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    lines = [
        "schema: pardal.routes",
        "version: 0.1",
        "board:",
        f"  board_ir_id: {BOARD_ID}",
        f"  frozen_board_snapshot_id: {snapshot}",
        "defaults:",
        "  units:",
        "    length: mm",
        "  search:",
        "    candidate_order: lexical",
        "    max_candidates: 4",
        "  diagnostics:",
        "    emit_best_failed_candidate: true",
        "route_groups:",
    ]
    for pin, name, kind, _functions in PIN_ROWS:
        net = _pin_net(pin, name)
        allowed = "[F.Cu, In1.Cu, In2.Cu, B.Cu]" if kind == "gpio" else "[F.Cu, B.Cu]"
        lines.extend(
            [
                f"  - id: rg_pin_{pin:02d}_{name.lower()}",
                f"    name: route_pin_{pin:02d}_{name.lower()}",
                "    select:",
                f"      nets: [{net}]",
                "      endpoints:",
                "        - ref: U1",
                f"          pads: [\"{pin}\"]",
                f"        - ref: J{pin:02d}",
                "          pads: [\"1\"]",
                "    scope:",
                f"      allowed_layers: {allowed}",
                "      forbidden_layers: []",
                "      corridors: []",
                "      keepouts:",
                "        - id: obs-mcu-courtyard",
                "          mode: soft",
                "    replacement:",
                "      mode: scoped",
                f"      nets: [{net}]",
                f"      existing_route_groups: [rg_pin_{pin:02d}_{name.lower()}]",
                "      allow_power: true",
                "      allow_planes: false",
                "      max_removed_segments: 8",
                "      max_removed_vias: 4",
                "    variables:",
                "      escape_layer:",
                f"        values: {allowed}",
            ]
        )
    return "\n".join(lines) + "\n"


def _source_manifest() -> dict[str, object]:
    pins = []
    for pin, name, kind, functions in PIN_ROWS:
        pins.append(
            {
                "pin": pin,
                "name": name,
                "kind": kind,
                "net": _pin_net(pin, name),
                "adc": ADC_PINS.get(name),
                "functions": [item.strip() for item in functions.split(",") if item.strip()],
            }
        )
    return {
        "schema": "pardal.gd32f310_source_manifest",
        "version": "0.1",
        "part": "GD32F310C8T6",
        "package": "LQFP48",
        "source": "GigaDevice GD32F310xx Datasheet Rev2.2 Table 2-4",
        "board": {"width_mm": 100.0, "height_mm": 100.0, "copper_layers": [name for _id, name, _kind in LAYERS]},
        "coverage": {
            "package_pin_count": len(PIN_ROWS),
            "represented_pin_count": len(pins),
            "adc_pin_count": len(ADC_PINS),
            "adc_channels": ADC_PINS,
            "adc_filter_count": len(ADC_FILTERS),
            "production_part_count": 7 + len(ADC_FILTERS) * 2,
        },
        "jlc_parts": JLC_PARTS,
        "power": {
            "input_voltage": "12V",
            "rails": ["12V_IN", "12V_PROT", "3V3", "GND"],
            "parts": ["J12V", "D1", "U2", "CIN1", "COUT1", "COUT2"],
        },
        "adc_filters": [
            {
                "channel": filt["channel"],
                "pin": filt["mcu_pad"],
                "input_net": filt["input_net"],
                "filtered_net": filt["mcu_net"],
                "parts": [filt["input_ref"], filt["res_ref"], filt["cap_ref"]],
            }
            for filt in ADC_FILTERS
        ],
        "pins": pins,
    }


def _backend_manifest() -> dict[str, object]:
    return {
        "backend": {"id": "mojo", "version": "1.0"},
        "capabilities": {
            "supported_layers": [name for _id, name, _kind in LAYERS],
            "vias": {"types": ["through", "blind", "buried"], "max_count": 256},
            "differential_pairs": False,
            "zones": True,
            "keepouts": True,
            "width_mm": {"min": 0.1, "max": 0.5},
            "clearance_mm": {"min": 0.1, "max": 0.3},
            "unsupported_features": [],
        },
    }


def _problem_payload() -> dict[str, object]:
    return {
        "schema": "mojo.problem",
        "version": "1.0",
        "backend": {"id": "mojo", "version": "1.0"},
        "board": {
            "board_ir_id": BOARD_ID,
            "frozen_board_snapshot_id": "",
            "stackup": [],
            "nets": [],
            "components": [],
            "pads": [],
            "obstacles": [],
        },
        "route_plan": {
            "route_plan_id": "",
            "route_plan_hash": "",
            "frozen_board_snapshot_id": "",
            "route_groups": [],
        },
        "unsupported_features": [],
        "problem_hash": "sha256:gd32f310c8t6-staged-empty-problem",
    }


def _netlist() -> str:
    comps = [
        '    (comp (ref "U1") (value "GD32F310C8T6") (footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm"))',
        '    (comp (ref "J12V") (value "12V_IN") (footprint "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"))',
        '    (comp (ref "D1") (value "SS14") (footprint "Diode_SMD:D_SMA"))',
        '    (comp (ref "U2") (value "AMS1117-3.3") (footprint "Package_TO_SOT_SMD:SOT-89-3"))',
        '    (comp (ref "CIN1") (value "10uF") (footprint "Capacitor_SMD:C_0805_2012Metric"))',
        '    (comp (ref "COUT1") (value "10uF") (footprint "Capacitor_SMD:C_0805_2012Metric"))',
        '    (comp (ref "COUT2") (value "100nF") (footprint "Capacitor_SMD:C_0603_1608Metric"))',
    ]
    for filt in ADC_FILTERS:
        comps.extend(
            [
                f'    (comp (ref "{filt["input_ref"]}") (value "{filt["channel"]}_IN") (footprint "TestPoint:TestPoint_Pad_1.0mm"))',
                f'    (comp (ref "{filt["res_ref"]}") (value "3.3k") (footprint "Resistor_SMD:R_0603_1608Metric"))',
                f'    (comp (ref "{filt["cap_ref"]}") (value "100nF") (footprint "Capacitor_SMD:C_0603_1608Metric"))',
            ]
        )
    net_nodes: dict[str, list[tuple[str, str]]] = {}
    for pin, name, _kind, _functions in PIN_ROWS:
        net_nodes.setdefault(_pin_net(pin, name), []).append(("U1", str(pin)))
    net_nodes.setdefault("12V_IN", []).append(("J12V", "1"))
    net_nodes.setdefault("GND", []).append(("J12V", "2"))
    net_nodes.setdefault("12V_PROT", []).extend([("D1", "2"), ("CIN1", "1"), ("U2", "3")])
    net_nodes.setdefault("12V_IN", []).append(("D1", "1"))
    net_nodes.setdefault("GND", []).extend([("CIN1", "2"), ("U2", "1"), ("COUT1", "2"), ("COUT2", "2")])
    net_nodes.setdefault("3V3", []).extend([("U2", "2"), ("COUT1", "1"), ("COUT2", "1")])
    for filt in ADC_FILTERS:
        net_nodes.setdefault(filt["mcu_net"], []).extend(
            [("U1", str(filt["pin"])), (filt["res_ref"], "2"), (filt["cap_ref"], "1")]
        )
        net_nodes.setdefault(filt["input_net"], []).extend(
            [(filt["input_ref"], "1"), (filt["res_ref"], "1")]
        )
        net_nodes.setdefault("GND", []).append((filt["cap_ref"], "2"))
    nets = []
    for code, (net, nodes) in enumerate(sorted(net_nodes.items()), start=1):
        deduped = sorted(set(nodes))
        node_lines = "\n".join(f'      (node (ref "{ref}") (pin "{pin}"))' for ref, pin in deduped)
        nets.append(f'    (net (code {code}) (name "{net}")\n{node_lines})')
    return "(export\n  (version \"E\")\n  (components\n" + "\n".join(comps) + "\n  )\n  (nets\n" + "\n".join(nets) + "\n  )\n)\n"


def _physical_spec() -> str:
    lines = [
        "source:",
        "  netlist: gd32f310c8t6.net",
        "board:",
        "  width: 100mm",
        "  height: 100mm",
        "  stackup: four_layer",
        "  copper_layers: [F.Cu, In1.Cu, In2.Cu, B.Cu]",
        "layer_roles:",
        "  F.Cu: signal",
        "  In1.Cu: signal",
        "  In2.Cu: signal",
        "  B.Cu: signal",
        "rules:",
        "  default_clearance: 0.10mm",
        "  default_width: 0.10mm",
        "  netclasses:",
        "    Power:",
        "      width: 0.20mm",
        "      clearance: 0.10mm",
        "      via:",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "    FinePitch:",
        "      width: 0.10mm",
        "      clearance: 0.10mm",
        "      via:",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "netclasses:",
        "  Power: [3V3, 12V_PROT]",
        "  FinePitch: [\"*\"]",
        "parts:",
        "  U1:",
        "    footprint: Package_QFP:LQFP-48_7x7mm_P0.5mm",
        "    at: [50mm, 50mm]",
        "    rotation: 0",
        "  J12V:",
        "    footprint: TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
        "    at: [84mm, 18mm]",
        "    rotation: 0",
        "  D1:",
        "    footprint: Diode_SMD:D_SMA",
        "    at: [72mm, 18mm]",
        "    rotation: 0",
        "  U2:",
        "    footprint: Package_TO_SOT_SMD:SOT-89-3",
        "    at: [72mm, 30mm]",
        "    rotation: 0",
        "  CIN1:",
        "    footprint: Capacitor_SMD:C_0805_2012Metric",
        "    at: [78mm, 22mm]",
        "    rotation: 0",
        "  COUT1:",
        "    footprint: Capacitor_SMD:C_0805_2012Metric",
        "    at: [88mm, 38mm]",
        "    rotation: 0",
        "  COUT2:",
        "    footprint: Capacitor_SMD:C_0603_1608Metric",
        "    at: [88mm, 34mm]",
        "    rotation: 0",
    ]
    for idx, filt in enumerate(ADC_FILTERS):
        if idx < 3:
            _pad_x, pad_y = _physical_pad_position(filt["pin"])
            y = 36.0 + idx * 6.0
            input_x = 8.0
            res_x = 20.0
            cap_x = 30.0
            input_y_override = y
        else:
            x = 20.0 + (idx - 3) * 10.0
            input_x = x
            res_x = x
            cap_x = x
            y = 72.0
            input_y_override = y
            input_y = y
            res_y = y - 4.0
            cap_y = y - 10.0
        if idx < 3:
            input_y = input_y_override
            res_y = y
            cap_y = y - 2.0
            res_rotation = 0
            cap_rotation = 90
        else:
            res_rotation = 90
            cap_rotation = 90
        lines.extend(
            [
                f"  {filt['input_ref']}:",
                "    footprint: TestPoint:TestPoint_Pad_1.0mm",
                f"    at: [{input_x:.3f}mm, {input_y:.3f}mm]",
                "    rotation: 0",
                f"  {filt['res_ref']}:",
                "    footprint: Resistor_SMD:R_0603_1608Metric",
                f"    at: [{res_x:.3f}mm, {res_y:.3f}mm]",
                f"    rotation: {res_rotation}",
                f"  {filt['cap_ref']}:",
                "    footprint: Capacitor_SMD:C_0603_1608Metric",
                f"    at: [{cap_x:.3f}mm, {cap_y:.3f}mm]",
                f"    rotation: {cap_rotation}",
            ]
        )
    lines.extend(
        [
        "routes:",
        "  - name: stitch_3v3_package_pins",
        "    kind: manual_polyline",
        "    net: 3V3",
        "    width: 0.20mm",
        "    layer: F.Cu",
        "    group: power_stitch",
        "    points:",
        "      - U1.48",
        "      - [47.2500mm, 40.0000mm]",
        "      - [60.0000mm, 40.0000mm]",
        "      - [60.0000mm, 58.0000mm]",
        "      - [52.7500mm, 58.0000mm]",
        "      - U1.24",
        "  - name: stitch_3v3_vbat_pin",
        "    kind: manual_polyline",
        "    net: 3V3",
        "    width: 0.20mm",
        "    layer: F.Cu",
        "    group: power_stitch",
        "    points:",
        "      - U1.1",
        "      - [44.0000mm, 47.2500mm]",
        "      - via: [44.0000mm, 47.2500mm]",
        "        to: B.Cu",
        "        layers: [F.Cu, B.Cu]",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "      - [44.0000mm, 40.0000mm]",
        "      - [47.2500mm, 40.0000mm]",
        "      - via: [47.2500mm, 40.0000mm]",
        "        to: F.Cu",
        "        layers: [F.Cu, B.Cu]",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "  - name: stitch_3v3_analog_pin",
        "    kind: manual_polyline",
        "    net: 3V3",
        "    width: 0.20mm",
        "    layer: F.Cu",
        "    group: power_stitch",
        "    points:",
        "      - U1.9",
        "      - [44.0000mm, 51.2500mm]",
        "      - via: [44.0000mm, 51.2500mm]",
        "        to: B.Cu",
        "        layers: [F.Cu, B.Cu]",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "      - [42.0000mm, 51.2500mm]",
        "      - [42.0000mm, 42.0000mm]",
        "      - via: [42.0000mm, 42.0000mm]",
        "        to: F.Cu",
        "        layers: [F.Cu, B.Cu]",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "      - [47.2500mm, 40.0000mm]",
        "  - name: stitch_gnd_package_pins",
        "    kind: manual_polyline",
        "    net: GND",
        "    layer: F.Cu",
        "    group: power_stitch",
        "    points:",
        "      - U1.47",
        "      - [47.7500mm, 43.0000mm]",
        "      - via: [47.7500mm, 43.0000mm]",
        "        to: B.Cu",
        "        layers: [F.Cu, B.Cu]",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "      - [50.0000mm, 43.0000mm]",
        "      - [50.0000mm, 50.7500mm]",
        "      - [43.5000mm, 50.7500mm]",
        "      - via: [43.5000mm, 50.7500mm]",
        "        to: F.Cu",
        "        layers: [F.Cu, B.Cu]",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "      - U1.8",
        "  - name: stitch_gnd_bottom_pin",
        "    kind: manual_polyline",
        "    net: GND",
        "    layer: F.Cu",
        "    group: power_stitch",
        "    points:",
        "      - U1.23",
        "      - [52.2500mm, 57.0000mm]",
        "      - via: [52.2500mm, 57.0000mm]",
        "        to: B.Cu",
        "        layers: [F.Cu, B.Cu]",
        "        diameter: 0.50mm",
        "        drill: 0.30mm",
        "      - [52.2500mm, 43.0000mm]",
        "      - [47.7500mm, 43.0000mm]",
        ]
    )
    lines.extend(
        [
            "  - name: route_12v_input_protection",
            "    kind: manual_polyline",
            "    net: 12V_IN",
            "    layer: F.Cu",
            "    group: power_input",
            "    points:",
            "      - J12V.1",
            "      - [84.0000mm, 12.0000mm]",
            "      - [72.0000mm, 12.0000mm]",
            "      - D1.1",
            "  - name: route_12v_protected_to_regulator",
            "    kind: manual_polyline",
            "    net: 12V_PROT",
            "    width: 0.20mm",
            "    layer: F.Cu",
            "    group: power_input",
            "    points:",
            "      - D1.2",
            "      - [76.0000mm, 18.0000mm]",
            "      - [76.0000mm, 22.0000mm]",
            "      - CIN1.1",
            "  - name: route_12v_protected_to_regulator",
            "    kind: manual_polyline",
            "    net: 12V_PROT",
            "    width: 0.20mm",
            "    layer: F.Cu",
            "    group: power_input",
            "    points:",
            "      - D1.2",
            "      - [74.0000mm, 24.0000mm]",
            "      - [86.0000mm, 24.0000mm]",
            "      - [86.0000mm, 31.5000mm]",
            "      - [70.0500mm, 31.5000mm]",
            "      - U2.3",
        ]
    )
    lines.extend(
        [
            "  - name: route_regulator_3v3_output",
            "    kind: manual_polyline",
            "    net: 3V3",
            "    width: 0.20mm",
            "    layer: F.Cu",
            "    group: power_output",
            "    points:",
            "      - U2.2",
            "      - [72.8000mm, 30.0000mm]",
            "      - via: [72.8000mm, 30.0000mm]",
            "        to: B.Cu",
            "        layers: [F.Cu, B.Cu]",
            "        diameter: 0.50mm",
            "        drill: 0.30mm",
            "      - [87.0500mm, 38.0000mm]",
            "      - via: [87.0500mm, 38.0000mm]",
            "        to: F.Cu",
            "        layers: [F.Cu, B.Cu]",
            "        diameter: 0.50mm",
            "        drill: 0.30mm",
            "      - COUT1.1",
            "      - COUT2.1",
            "      - via: [87.2250mm, 34.0000mm]",
            "        to: B.Cu",
            "        layers: [F.Cu, B.Cu]",
            "        diameter: 0.50mm",
            "        drill: 0.30mm",
            "      - [60.0000mm, 40.0000mm]",
            "      - via: [60.0000mm, 40.0000mm]",
            "        to: F.Cu",
            "        layers: [F.Cu, B.Cu]",
            "        diameter: 0.50mm",
            "        drill: 0.30mm",
            "      - [60.0000mm, 40.0000mm]",
            "  - name: route_power_ground",
            "    kind: manual_polyline",
            "    net: GND",
            "    layer: B.Cu",
            "    group: power_return",
            "    points:",
            "      - J12V.2",
            "      - [89.0800mm, 10.0000mm]",
            "      - [90.0000mm, 10.0000mm]",
            "      - [90.0000mm, 43.0000mm]",
            "      - [50.0000mm, 43.0000mm]",
            "  - name: route_input_cap_ground",
            "    kind: manual_polyline",
            "    net: GND",
            "    layer: F.Cu",
            "    group: power_return",
            "    points:",
            "      - CIN1.2",
            "      - [78.9500mm, 22.0000mm]",
            "      - [79.8000mm, 21.2000mm]",
            "      - via: [79.8000mm, 21.2000mm]",
            "        to: B.Cu",
            "        layers: [F.Cu, B.Cu]",
            "        diameter: 0.50mm",
            "        drill: 0.30mm",
            "      - [79.8000mm, 10.0000mm]",
            "      - [90.0000mm, 10.0000mm]",
            "  - name: route_regulator_ground",
            "    kind: manual_polyline",
            "    net: GND",
            "    layer: F.Cu",
            "    group: power_return",
            "    points:",
            "      - U2.1",
            "      - [68.8000mm, 30.0000mm]",
            "      - [68.8000mm, 28.8000mm]",
            "      - via: [68.8000mm, 28.8000mm]",
            "        to: B.Cu",
            "        layers: [F.Cu, B.Cu]",
            "        diameter: 0.50mm",
            "        drill: 0.30mm",
            "      - [68.8000mm, 10.0000mm]",
            "      - [90.0000mm, 10.0000mm]",
            "  - name: route_output_cap_ground",
            "    kind: manual_polyline",
            "    net: GND",
            "    layer: F.Cu",
            "    group: power_return",
            "    points:",
            "      - COUT1.2",
            "      - [88.9500mm, 38.0000mm]",
            "      - [89.8000mm, 38.8000mm]",
            "      - via: [89.8000mm, 38.8000mm]",
            "        to: B.Cu",
            "        layers: [F.Cu, B.Cu]",
            "        diameter: 0.50mm",
            "        drill: 0.30mm",
            "      - [89.8000mm, 10.0000mm]",
            "  - name: route_output_decoupler_ground",
            "    kind: manual_polyline",
            "    net: GND",
            "    layer: F.Cu",
            "    group: power_return",
            "    points:",
            "      - COUT2.2",
            "      - [88.7750mm, 34.0000mm]",
            "      - [89.8000mm, 33.2000mm]",
            "      - via: [89.8000mm, 33.2000mm]",
            "        to: B.Cu",
            "        layers: [F.Cu, B.Cu]",
            "        diameter: 0.50mm",
            "        drill: 0.30mm",
            "      - [89.8000mm, 10.0000mm]",
        ]
    )
    for idx, filt in enumerate(ADC_FILTERS):
        if idx < 3:
            pad_x, y = _physical_pad_position(filt["pin"])
            mcu_stub = [pad_x - 2.0, y]
            left_input_x = 8.0
            left_res_x = 20.0
            left_cap_x = 30.0
            filter_row_y = 36.0 + idx * 6.0
            filter_corridor_x = left_res_x + 3.0 + idx * 4.0
        else:
            x = 20.0 + (idx - 3) * 10.0
            y = 68.0
            pad_x, pad_y = _physical_pad_position(filt["pin"])
            mcu_stub = [pad_x, pad_y + 2.0]
            return_via_y = {8: 59.5, 9: 55.5}.get(idx, 56.0 + (idx - 3) * 1.5)
            return_via = [pad_x, return_via_y]
            signal_layer = "In1.Cu" if (idx % 2 or idx == 8) and idx != 9 else "In2.Cu"
        if idx < 3:
            gnd_return = [
                f"      - [{left_cap_x + 4.0:.4f}mm, {60.0 + idx * 2.0:.4f}mm]",
                f"      - [{50.0:.4f}mm, {60.0 + idx * 2.0:.4f}mm]",
                "      - [50.0000mm, 50.7500mm]",
            ]
            cap_return_via_x = left_cap_x + 4.0
            cap_return_via_y = filter_row_y - 2.0
        else:
            cap_return_via_x = x + 3.0
            cap_return_via_y = y - 4.0
            gnd_return = [
                f"      - [{cap_return_via_x:.4f}mm, 60.0000mm]",
                "      - [50.0000mm, 50.7500mm]",
            ]
        if idx < 3:
            input_points = [
                f"      - {filt['input_ref']}.1",
                f"      - [{left_input_x:.4f}mm, {filter_row_y:.4f}mm]",
                f"      - {filt['res_ref']}.1",
            ]
        else:
            input_points = [
                f"      - {filt['input_ref']}.1",
                f"      - {filt['res_ref']}.1",
            ]
        lines.extend(
            [
                f"  - name: route_{filt['channel'].lower()}_input",
                "    kind: manual_polyline",
                f"    net: {filt['input_net']}",
                "    layer: F.Cu",
                "    group: adc_filters",
                "    points:",
                *input_points,
                f"  - name: route_{filt['channel'].lower()}_filtered",
                "    kind: manual_polyline",
                f"    net: {filt['mcu_net']}",
                "    layer: F.Cu",
                "    group: adc_filters",
                "    points:",
                f"      - {filt['res_ref']}.2",
            ]
        )
        if idx < 3:
            lines.extend(
                [
                    f"      - [{filter_corridor_x:.4f}mm, {filter_row_y:.4f}mm]",
                    f"      - via: [{filter_corridor_x:.4f}mm, {filter_row_y:.4f}mm]",
                    "        to: B.Cu",
                    "        layers: [F.Cu, B.Cu]",
                    "        diameter: 0.55mm",
                    "        drill: 0.30mm",
                    f"      - [{filter_corridor_x:.4f}mm, {mcu_stub[1]:.4f}mm]",
                    f"      - via: [{filter_corridor_x:.4f}mm, {mcu_stub[1]:.4f}mm]",
                    "        to: F.Cu",
                    "        layers: [F.Cu, B.Cu]",
                    "        diameter: 0.55mm",
                    "        drill: 0.30mm",
                    f"      - [{mcu_stub[0]:.4f}mm, {mcu_stub[1]:.4f}mm]",
                    f"      - U1.{filt['pin']}",
                ]
            )
        else:
            lines.extend(
                [
                    f"      - [{x:.4f}mm, {y - 2.0:.4f}mm]",
                    f"      - via: [{x:.4f}mm, {y - 2.0:.4f}mm]",
                    f"        to: {signal_layer}",
                    f"        layers: [F.Cu, {signal_layer}]",
                    "        diameter: 0.55mm",
                    "        drill: 0.30mm",
                    f"      - [{x:.4f}mm, {return_via[1]:.4f}mm]",
                    f"      - [{return_via[0]:.4f}mm, {return_via[1]:.4f}mm]",
                    f"      - via: [{return_via[0]:.4f}mm, {return_via[1]:.4f}mm]",
                    "        to: F.Cu",
                    f"        layers: [F.Cu, {signal_layer}]",
                    "        diameter: 0.55mm",
                    "        drill: 0.30mm",
                    f"      - [{mcu_stub[0]:.4f}mm, {mcu_stub[1]:.4f}mm]",
                    f"      - U1.{filt['pin']}",
                ]
            )
        lines.extend(
            [
                f"  - name: route_{filt['channel'].lower()}_filter_cap_tap",
                "    kind: manual_polyline",
                f"    net: {filt['mcu_net']}",
                "    layer: F.Cu",
                "    group: adc_filters",
                "    points:",
                f"      - {filt['cap_ref']}.1",
                f"      - [{filter_corridor_x if idx < 3 else x:.4f}mm, {filter_row_y if idx < 3 else y - 2.0:.4f}mm]",
                f"  - name: route_{filt['channel'].lower()}_capacitor_return",
                "    kind: manual_polyline",
                "    net: GND",
                "    layer: F.Cu",
                "    group: adc_filters",
                "    points:",
                f"      - {filt['cap_ref']}.2",
                f"      - [{cap_return_via_x:.4f}mm, {cap_return_via_y:.4f}mm]",
                f"      - via: [{cap_return_via_x:.4f}mm, {cap_return_via_y:.4f}mm]",
                "        to: B.Cu",
                "        layers: [F.Cu, B.Cu]",
                "        diameter: 0.50mm",
                "        drill: 0.30mm",
                *gnd_return,
            ]
        )
    lines.extend(
        [
        "dfm:",
        "  profile: jlcpcb_4_layer_smt",
        "  lcsc_policy: require_or_exception",
        "  max_lcsc_exceptions: 0",
        "  lcsc_database:",
        "    path: ../../../jlcpcb-parts-database/db_build/jlcpcb-components.sqlite3",
        "    strict: true",
        "  assembly_methods:",
        "    U1: jlc_smt",
        "    J12V: manual_tht",
        "    D1: jlc_smt",
        "    U2: jlc_smt",
        "    CIN1: jlc_smt",
        "    COUT1: jlc_smt",
        "    COUT2: jlc_smt",
        ]
    )
    for filt in ADC_FILTERS:
        lines.extend(
            [
                f"    {filt['res_ref']}: jlc_smt",
                f"    {filt['cap_ref']}: jlc_smt",
            ]
        )
    lines.extend(
        [
            "  lcsc_parts:",
            f"    U1: {JLC_PARTS['GD32F310C8T6']}",
            f"    J12V: {JLC_PARTS['J_2P_5_08']}",
            f"    D1: {JLC_PARTS['SS14_SMA']}",
            f"    U2: {JLC_PARTS['AMS1117_3V3_SOT89']}",
            f"    CIN1: {JLC_PARTS['C_10UF_0805']}",
            f"    COUT1: {JLC_PARTS['C_10UF_0805']}",
            f"    COUT2: {JLC_PARTS['C_100NF_0603']}",
        ]
    )
    for filt in ADC_FILTERS:
        lines.extend(
            [
                f"    {filt['res_ref']}: {JLC_PARTS['R_3K3_0603']}",
                f"    {filt['cap_ref']}: {JLC_PARTS['C_100NF_0603']}",
            ]
        )
    lines.extend(
        [
        "  panelization:",
        "    mode: single_board",
            "  required_artifacts:",
            "    - gd32f310c8t6.jlc.bom.csv",
            "    - gd32f310c8t6.jlc.pnp.csv",
            "fiducials:",
            "  - name: fid_1",
            "    at: [5mm, 5mm]",
            "  - name: fid_2",
            "    at: [95mm, 5mm]",
            "  - name: fid_3",
            "    at: [90mm, 90mm]",
            "mounting_holes:",
            "  - name: mh_1",
            "    at: [6mm, 94mm]",
            "    diameter: 3.4mm",
            "    drill: 3.2mm",
            "  - name: mh_2",
            "    at: [94mm, 94mm]",
            "    diameter: 3.4mm",
            "    drill: 3.2mm",
            "validation_tests:",
            "  - name: adc_filter_response",
            "    kind: analog_measurement",
            "    net: ADC0_FILT",
            "    criteria: \"Inject a known DC level on ADC0_IN and verify ADC0_FILT settles within tolerance; RC cutoff is <= 500 Hz by source contract.\"",
        ]
    )
    return "\n".join(lines) + "\n"


def _ato_yaml() -> str:
    return """requires-atopile: ^0.10.0

paths:
  src: ./
  layout: ./layout

builds:
  default:
    entry: gd32f310c8t6.ato:GD32F310C8T6Breakout
"""


def _ato_source() -> str:
    pin_comments = "\n".join(
        f"    # pin {pin:02d}: {name} -> {_pin_net(pin, name)}" + (f" ({ADC_PINS[name]})" if name in ADC_PINS else "")
        for pin, name, _kind, _functions in PIN_ROWS
    )
    filter_instances = "\n".join(
        f"    # {filt['channel']}: {filt['input_ref']} -> {filt['res_ref']} -> {filt['cap_ref']} -> {filt['mcu_net']}"
        for filt in ADC_FILTERS
    )
    jlc_comments = "\n".join(f"    # {name}: {code}" for name, code in sorted(JLC_PARTS.items()))
    return f'''# GD32F310C8T6 source intent for the Pardal routing DSL example.
# The executable source-of-truth pin table is in generate.py and source_manifest.json.

module GD32F310Core:
{pin_comments}

module AdcInputFilter:
    # 3.3 kOhm series resistor, 100 nF shunt capacitor, source-side test pad.

module AdcFilterBank:
{filter_instances}

module TwelveVoltSupply:
    # J12V 12V input, SS14 reverse-protection diode, AMS1117-3.3 SOT-89 regulator.
    # CIN1/COUT1 are 10 uF bulk capacitors; COUT2 is 100 nF local decoupling.

module JlcCatalogParts:
{jlc_comments}

module GD32F310C8T6Breakout:
    # composed from GD32F310Core, AdcFilterBank, TwelveVoltSupply, and JlcCatalogParts
'''


def main() -> None:
    board_source = _board_source()
    _write_json(ROOT / "source_manifest.json", _source_manifest())
    _write_json(ROOT / "board_source.json", board_source)
    (ROOT / "routes.pdl.yaml").write_text(_routes_source(board_source), encoding="utf-8")
    _write_json(ROOT / "backend_manifest.json", _backend_manifest())
    _write_json(ROOT / "problem.json", _problem_payload())
    (ROOT / "gd32f310c8t6.net").write_text(_netlist(), encoding="utf-8")
    (ROOT / "board.pdl.yaml").write_text(_physical_spec(), encoding="utf-8")
    (ROOT / "ato.yaml").write_text(_ato_yaml(), encoding="utf-8")
    (ROOT / "gd32f310c8t6.ato").write_text(_ato_source(), encoding="utf-8")


if __name__ == "__main__":
    main()
