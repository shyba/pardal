"""
Footprint Library

Defines standard footprint pad layouts for common components.
Each footprint function returns a list of Pad objects with correct positions.
"""

from pcb_tool.data_model import Pad

# Map atopile footprint suffixes to KiCad names
SUFFIX_MAP = {
    'C0805': 'C_0805_2012Metric',
    'R0805': 'R_0805_2012Metric',
    'C0603': 'C_0603_1608Metric',
    'R0603': 'R_0603_1608Metric',
    'TO-220-3_Vertical': 'TO-220-3_Vertical',
    'SOT-223-3_TabPin2': 'SOT-223-3',
    'D_SMB': 'D_SMB',
}


def get_footprint_pads(footprint_name: str) -> tuple[list[Pad], str | None]:
    """Get pad definitions for a footprint.

    Args:
        footprint_name: KiCad footprint library name (e.g., "Resistor_SMD:R_0805_2012Metric")

    Returns:
        Tuple of (pads list, error message or None)
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
        'R_0805': _r0805,
        'R_0603_1608Metric': _r0603,
        'R_0603': _r0603,

        # Resistors THT
        'R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal': _r_axial_din0207,
        'R_Axial_DIN0207_L6.3mm': _r_axial_din0207,

        # Diodes THT
        'D_DO-41_SOD81_P10.16mm_Horizontal': _do41,

        # Capacitors
        'CP_Radial_D6.3mm_P2.50mm': _cap_radial_2_5mm,
        'C_0805_2012Metric': _c0805,
        'C_0805': _c0805,

        # ICs - SMD
        'SOT-223-3': _sot223_3,
        'SSOP-20_W5.3mm': _ssop20,

        # ICs - THT
        'DIP-8_W7.62mm': _dip8,

        # Test Points
        'TestPoint_Pad_1.0mm': _testpoint_1mm,

        # Connectors
        'PinHeader_1x03_P2.54mm_Vertical': lambda: _pin_header_1xn(3),
        'PinHeader_1x04_P2.54mm_Vertical': lambda: _pin_header_1xn(4),
        'PinHeader_1x04_P2.54mm': lambda: _pin_header_1xn(4),
        'PinHeader_1x05_P2.54mm_Vertical': lambda: _pin_header_1xn(5),
        'PinHeader_1x06_P2.54mm_Vertical': lambda: _pin_header_1xn(6),
        'PinHeader_1x07_P2.54mm_Vertical': lambda: _pin_header_1xn(7),
        'PinHeader_1x08_P2.54mm_Vertical': lambda: _pin_header_1xn(8),
        'PinHeader_1x10_P2.54mm_Vertical': lambda: _pin_header_1xn(10),
    }

    # Step 1: Try exact match
    handler = handlers.get(footprint_type)
    if handler:
        return (handler(), None)

    # Step 2: Try suffix mapping (for atopile footprints like Samsung_...:C0805)
    suffix = footprint_type.split('_')[-1] if '_' in footprint_type else footprint_type
    mapped = SUFFIX_MAP.get(suffix) or SUFFIX_MAP.get(footprint_type)
    if mapped:
        handler = handlers.get(mapped)
        if handler:
            return (handler(), None)

    # Step 3: Try pcbnew SDK fallback
    pads = _try_pcbnew_load(footprint_name)
    if pads:
        return (pads, None)

    # Step 4: Fail with error (NOT single pad!)
    return ([], f"Unknown footprint: {footprint_name}")


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


# Resistors SMD - additional sizes

def _r0603() -> list[Pad]:
    """0603 resistor (1.6mm x 0.8mm body)."""
    return [
        Pad(number=1, position_offset=(-0.75, 0.0), size=(0.8, 0.9), shape="rect"),
        Pad(number=2, position_offset=(0.75, 0.0), size=(0.8, 0.9), shape="rect"),
    ]


# Resistors THT

def _r_axial_din0207() -> list[Pad]:
    """Axial resistor DIN0207 (10.16mm lead spacing)."""
    return [
        Pad(number=1, position_offset=(-5.08, 0.0), size=(1.6, 1.6), drill=0.8, shape="rect"),
        Pad(number=2, position_offset=(5.08, 0.0), size=(1.6, 1.6), drill=0.8, shape="circle"),
    ]


# ICs - SMD

def _sot223_3() -> list[Pad]:
    """SOT-223-3 voltage regulator (LM1117, AMS1117, etc.)."""
    return [
        Pad(number=1, position_offset=(-2.3, 3.2), size=(1.0, 2.0), shape="rect"),   # Input
        Pad(number=2, position_offset=(0.0, 3.2), size=(1.0, 2.0), shape="rect"),    # GND/Tab
        Pad(number=3, position_offset=(2.3, 3.2), size=(1.0, 2.0), shape="rect"),    # Output
        Pad(number=4, position_offset=(0.0, -3.2), size=(3.5, 2.0), shape="rect"),   # Tab/heat sink
    ]


def _ssop20() -> list[Pad]:
    """SSOP-20 with 5.3mm body width, 0.65mm pitch."""
    pads = []
    for i in range(10):
        shape = "rect" if i == 0 else "rect"
        pads.append(Pad(number=i+1, position_offset=(-3.9, -2.925 + i*0.65),
                        size=(1.6, 0.4), shape=shape))
        pads.append(Pad(number=20-i, position_offset=(3.9, -2.925 + i*0.65),
                        size=(1.6, 0.4), shape="rect"))
    return pads


# ICs - THT

def _dip8() -> list[Pad]:
    """DIP-8 with 7.62mm (300mil) row spacing."""
    pads = []
    for i in range(4):
        shape = "rect" if i == 0 else "circle"
        pads.append(Pad(number=i+1, position_offset=(-3.81, -3.81 + i*2.54),
                        size=(1.6, 1.6), drill=0.8, shape=shape))
        pads.append(Pad(number=8-i, position_offset=(3.81, -3.81 + i*2.54),
                        size=(1.6, 1.6), drill=0.8, shape="circle"))
    return pads


# Test Points

def _testpoint_1mm() -> list[Pad]:
    """1mm test point pad."""
    return [Pad(number=1, position_offset=(0.0, 0.0), size=(1.0, 1.0), shape="circle")]


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
        # MOSFETs
        'Package_TO_SOT_THT:TO-220-3_Vertical',
        # Resistors SMD
        'Resistor_SMD:R_0805_2012Metric',
        'Resistor_SMD:R_0603_1608Metric',
        # Resistors THT
        'Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal',
        # Diodes THT
        'Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal',
        # Capacitors
        'Capacitor_THT:CP_Radial_D6.3mm_P2.50mm',
        'Capacitor_SMD:C_0805_2012Metric',
        # ICs - SMD
        'Package_TO_SOT_SMD:SOT-223-3',
        'Package_SO:SSOP-20_W5.3mm',
        # ICs - THT
        'Package_DIP:DIP-8_W7.62mm',
        # Test Points
        'TestPoint:TestPoint_Pad_1.0mm',
        # Connectors
        'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x07_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical',
        'Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical',
    ]


def _try_pcbnew_load(footprint_name: str) -> list[Pad] | None:
    """Try to load footprint from KiCad libraries using pcbnew SDK."""
    try:
        import pcbnew

        if ':' not in footprint_name:
            return None

        lib_name, fp_name = footprint_name.split(':', 1)

        # Try common library paths
        for base in ['/usr/share/kicad/footprints']:
            lib_path = f"{base}/{lib_name}.pretty"
            try:
                io = pcbnew.PCB_IO_KICAD_SEXPR()
                fp = io.FootprintLoad(lib_path, fp_name)
                if fp:
                    return _extract_pads_from_footprint(fp)
            except Exception:
                continue
        return None
    except ImportError:
        return None


def _extract_pads_from_footprint(fp) -> list[Pad]:
    """Extract Pad objects from pcbnew footprint."""
    import pcbnew

    pads = []
    fp_pos = fp.GetPosition()

    for kicad_pad in fp.Pads():
        pad_pos = kicad_pad.GetPosition()
        pads.append(Pad(
            number=kicad_pad.GetNumber(),
            position_offset=(
                pcbnew.ToMM(pad_pos.x - fp_pos.x),
                pcbnew.ToMM(pad_pos.y - fp_pos.y)
            ),
            size=(
                pcbnew.ToMM(kicad_pad.GetSize().x),
                pcbnew.ToMM(kicad_pad.GetSize().y)
            ),
            shape='rect' if kicad_pad.GetShape() == pcbnew.PAD_SHAPE_RECT else 'circle'
        ))

    return pads
