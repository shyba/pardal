"""Footprint name normalization shared by netlist import and writers."""

from __future__ import annotations


FOOTPRINT_ALIASES = {
    "atopile:C_0603_1608Metric": "Capacitor_SMD:C_0603_1608Metric",
    "atopile:R_0603_1608Metric": "Resistor_SMD:R_0603_1608Metric",
    "atopile:LED_0603_1608Metric": "LED_SMD:LED_0603_1608Metric",
    "atopile:PinHeader_1x06_P2.54mm_Vertical": (
        "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical"
    ),
    "atopile:PinHeader_1x08_P2.54mm_Vertical": (
        "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical"
    ),
    "atopile:TQFP-64_10x10mm_P0.5mm": "Package_QFP:TQFP-64_10x10mm_P0.5mm",
    "Package_QFP:LQFP-64_10x10mm_P0.5mm": "Package_QFP:TQFP-64_10x10mm_P0.5mm",
}


def normalize_footprint_name(name: str, aliases: dict[str, str] | None = None) -> str:
    """Normalize known local/atopile footprint names to KiCad library names."""
    if aliases and name in aliases:
        return aliases[name]
    return FOOTPRINT_ALIASES.get(name, name)
