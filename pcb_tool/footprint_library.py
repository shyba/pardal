"""
Footprint Library

Defines standard footprint pad layouts for common components.
Each footprint function returns a list of Pad objects with correct positions.
"""

from pcb_tool.data_model import Pad


def get_footprint_pads(footprint_name: str) -> list[Pad]:
    """Get pad definitions for a footprint.

    Args:
        footprint_name: KiCad footprint library name (e.g., "Resistor_SMD:R_0805_2012Metric")

    Returns:
        List of Pad objects with correct positions

    Raises:
        ValueError: If footprint not found in library
    """
    # Extract footprint type from library name
    if ':' in footprint_name:
        footprint_type = footprint_name.split(':')[1]
    else:
        footprint_type = footprint_name

    # Map to handler function
    handlers = {
        # MOSFETs
        'TO-220-3_Vertical': _to220_vertical,

        # Resistors SMD
        'R_0805_2012Metric': _r0805,

        # Diodes THT
        'D_DO-41_SOD81_P10.16mm_Horizontal': _do41,

        # Capacitors
        'CP_Radial_D6.3mm_P2.50mm': _cap_radial_2_5mm,
        'C_0805_2012Metric': _c0805,

        # Connectors
        'PinHeader_1x03_P2.54mm_Vertical': lambda: _pin_header_1xn(3),
        'PinHeader_1x04_P2.54mm_Vertical': lambda: _pin_header_1xn(4),
        'PinHeader_1x05_P2.54mm_Vertical': lambda: _pin_header_1xn(5),
        'PinHeader_1x06_P2.54mm_Vertical': lambda: _pin_header_1xn(6),
        'PinHeader_1x07_P2.54mm_Vertical': lambda: _pin_header_1xn(7),
        'PinHeader_1x08_P2.54mm_Vertical': lambda: _pin_header_1xn(8),
        'PinHeader_1x10_P2.54mm_Vertical': lambda: _pin_header_1xn(10),
    }

    handler = handlers.get(footprint_type)
    if not handler:
        # Return generic single pad as fallback
        return [Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape="circle")]

    return handler()


# MOSFETs

def _to220_vertical() -> list[Pad]:
    """TO-220-3 vertical mount (3 pins in line, 2.54mm spacing).

    Pin 1: Gate (left)
    Pin 2: Source (center)
    Pin 3: Drain (right)
    """
    return [
        Pad(number=1, position_offset=(-2.54, 0.0), size=(2.0, 2.0), drill=1.0, shape="rect"),
        Pad(number=2, position_offset=(0.0, 0.0), size=(2.0, 2.0), drill=1.0, shape="circle"),
        Pad(number=3, position_offset=(2.54, 0.0), size=(2.0, 2.0), drill=1.0, shape="circle"),
    ]


# Resistors SMD

def _r0805() -> list[Pad]:
    """0805 resistor (2.0mm x 1.25mm body, 1.6mm pad spacing)."""
    return [
        Pad(number=1, position_offset=(-0.95, 0.0), size=(1.0, 1.3), shape="rect"),
        Pad(number=2, position_offset=(0.95, 0.0), size=(1.0, 1.3), shape="rect"),
    ]


# Diodes THT

def _do41() -> list[Pad]:
    """DO-41 diode horizontal (10.16mm lead spacing).

    Pin 1: Cathode (banded end)
    Pin 2: Anode
    """
    return [
        Pad(number=1, position_offset=(-5.08, 0.0), size=(1.6, 1.6), drill=0.8, shape="rect"),
        Pad(number=2, position_offset=(5.08, 0.0), size=(1.6, 1.6), drill=0.8, shape="circle"),
    ]


# Capacitors

def _cap_radial_2_5mm() -> list[Pad]:
    """Radial capacitor with 2.5mm lead spacing."""
    return [
        Pad(number=1, position_offset=(-1.25, 0.0), size=(1.6, 1.6), drill=0.8, shape="rect"),
        Pad(number=2, position_offset=(1.25, 0.0), size=(1.6, 1.6), drill=0.8, shape="circle"),
    ]


def _c0805() -> list[Pad]:
    """0805 capacitor (same as resistor)."""
    return _r0805()


# Connectors

def _pin_header_1xn(num_pins: int) -> list[Pad]:
    """Pin header 1xN vertical (2.54mm pin spacing).

    Args:
        num_pins: Number of pins in header

    Returns:
        List of pads spaced 2.54mm apart, centered on component
    """
    pads = []
    # Center the header: offset = (num_pins - 1) * 2.54 / 2
    center_offset = (num_pins - 1) * 2.54 / 2

    for i in range(num_pins):
        y_pos = i * 2.54 - center_offset
        shape = "rect" if i == 0 else "circle"
        pads.append(
            Pad(
                number=i + 1,
                position_offset=(0.0, y_pos),
                size=(1.7, 1.7),
                drill=1.0,
                shape=shape
            )
        )

    return pads


# Utility functions

def list_supported_footprints() -> list[str]:
    """Get list of all supported footprint names."""
    return [
        'Package_TO_SOT_THT:TO-220-3_Vertical',
        'Resistor_SMD:R_0805_2012Metric',
        'Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal',
        'Capacitor_THT:CP_Radial_D6.3mm_P2.50mm',
        'Capacitor_SMD:C_0805_2012Metric',
        'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x07_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical',
    ]
